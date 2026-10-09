"""Shared generation/inspection session; caller owns Gmsh initialize/finalize."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import gmsh
import numpy as np

from .geometry import build, assign_surface_groups
from .meshdata import snapshot
from .quality import analyze
from .sizing import plan, apply
from .normals import inspect as inspect_normals


@dataclass
class Context:
    configuration: dict
    geometry: dict
    sizing: dict
    membership: dict
    groups: list
    model_name: str
    model_signature: tuple


def model_signature() -> tuple:
    """CAD/group changes invalidate analytic references, even with unchanged tags."""
    entities = []
    occ_entities = set(gmsh.model.occ.getEntities())
    for dim in (2, 3):
        for _, tag in sorted(gmsh.model.getEntities(dim)):
            kind = gmsh.model.getType(dim, tag)
            # Both model and OCC bounding boxes can incorporate cached surface
            # triangulation after meshing. CAD moments do not use mesh bounds.
            moments = (gmsh.model.occ.getMass(dim,tag),
                       tuple(gmsh.model.occ.getCenterOfMass(dim,tag)),
                       tuple(gmsh.model.occ.getMatrixOfInertia(dim,tag))) if (dim,tag) in occ_entities else ()
            boundary = tuple(sorted(gmsh.model.getBoundary([(dim, tag)], oriented=True)))
            entities.append((dim, tag, kind, moments, boundary))
    groups = tuple((pid, tuple(sorted(gmsh.model.getEntitiesForPhysicalGroup(2, pid))))
                   for _, pid in sorted(gmsh.model.getPhysicalGroups(2)))
    return tuple(entities), groups


def adopt_current(configuration: dict) -> Context:
    """Inspect a model opened with native File/Open; never infer a CAD analytic reference."""
    cfg=deepcopy(configuration)
    surfaces=gmsh.model.getEntities(2)
    if not surfaces: raise ValueError("current Gmsh model has no surfaces")
    membership={}
    fallback=max([int(p) for _,p in gmsh.model.getPhysicalGroups(2)] + [cfg["export"]["pid_start"]-1])+1
    for i,(_,surface) in enumerate(sorted(surfaces)):
        groups=gmsh.model.getPhysicalGroupsForEntity(2,surface)
        if len(groups)>1: raise ValueError("multiple physical groups on one surface have ambiguous PID meaning")
        membership[surface]=int(groups[0]) if len(groups) else fallback
        if not len(groups): fallback+=1
    mesh=snapshot(membership)
    xyz=mesh["coordinates"]
    span=xyz.max(axis=0)-xyz.min(axis=0)
    scale=float(np.linalg.norm(span))
    if not np.isfinite(scale) or scale<=0: raise ValueError("invalid loaded model scale")
    tris=xyz[np.searchsorted(mesh["node_ids"],mesh["connectivity"])]
    area=float(np.linalg.norm(np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0]),axis=1).sum()/2)
    volumes=gmsh.model.getEntities(3)
    closed=sorted({abs(int(t)) for d,t in gmsh.model.getBoundary(volumes,combined=False,oriented=False) if d==2}) if volumes else []
    geometry={"analytic_kind":None,"analytic_parameters":None,"source_kind":"native_current_model","scale":scale,
              "surface_count":len(surfaces),"volume_count":len(volumes),"closed_surface_tags":closed,
              "surface_area":area,"bbox_min":xyz.min(axis=0).tolist(),"bbox_max":xyz.max(axis=0).tolist(),
              "explicit_scale":1.0,"output_unit":cfg["output_unit"],"length_unit":cfg["output_unit"]}
    target=cfg["mesh"]["target_size"] or scale*cfg["mesh"]["scale_fraction"]
    sizing={"target_size":target,"user_size_cap":cfg["mesh"]["user_size_cap"],"growth_assessment_limit":cfg["mesh"]["growth_assessment_limit"],
            "candidate_rules":[],"narrow_gap_detected":None,"narrow_gap_evidence":{"coverage":"not_assessed","reason":"loaded current model"},
            "budget_conflict":None,"element_budget":cfg["mesh"]["element_budget"],"chord_tolerance":scale*cfg["mesh"]["chord_tolerance_fraction"],
            "wave":{"enabled":False},"local":{"fields_applied":[]},"coverage":"inspection_only"}
    groups=[{"pid":pid,"name":f"loaded_pid_{pid}","surface_tags":[t for t,p in membership.items() if p==pid]} for pid in sorted(set(membership.values()))]
    return Context(cfg,geometry,sizing,membership,groups,gmsh.model.getCurrent(),model_signature())


def prepare(configuration: dict) -> Context:
    cfg = deepcopy(configuration)
    gmsh.clear()
    gmsh.model.add(cfg["name"])
    geometry = build(cfg["geometry"], cfg["length_unit"], cfg["output_unit"])
    tags = cfg["mesh"]["improvement"]["fragment_surface_tags"]
    if tags:
        if geometry["volume_count"]:
            raise ValueError("explicit surface fragment is limited to open CAD sheets; do not destroy solid boundaries")
        present = {t for _, t in gmsh.model.getEntities(2)}
        if not set(tags).issubset(present):
            raise ValueError("fragment_surface_tags refers to missing CAD surfaces")
        output, mapping = gmsh.model.occ.fragment([(2, tags[0])], [(2, t) for t in tags[1:]])
        gmsh.model.occ.synchronize()
        geometry["fragment"] = {"input_surface_tags": tags, "output_entities": [list(x) for x in output],
                                "input_to_output": [[list(x) for x in group] for group in mapping]}
        geometry["analytic_kind"] = None
        geometry["surface_count"] = len(gmsh.model.getEntities(2))
        geometry["surface_area"] = sum(gmsh.model.occ.getMass(2,t) for _,t in gmsh.model.getEntities(2))
    sizing = plan(geometry, cfg["mesh"])
    if sizing["user_size_cap"] is not None and sizing["target_size"] > sizing["user_size_cap"] * (1+1e-12):
        raise ValueError("minimum size or budget conflicts with user_size_cap; revise explicit constraints")
    apply(sizing)
    membership, groups = assign_surface_groups(cfg["export"]["pid_start"])
    if tags:
        # One source group may produce several new faces; preserve its original PID.
        original = {tag: cfg["export"]["pid_start"] + i for i,tag in enumerate(sorted(present))}
        for tag in present - set(tags):
            membership[tag] = original[tag]
        owners = {}
        for tag, mapped in zip(tags, geometry["fragment"]["input_to_output"]):
            for dim, new in mapped:
                if dim == 2:
                    if new in owners and owners[new] != tag:
                        raise ValueError("overlapping source faces have ambiguous PID provenance")
                    owners[new] = tag
                    membership[new] = original[tag]
        groups = [{"pid": pid, "name": f"source_surface_{source}", "surface_tags": sorted(t for t,p in membership.items() if p==pid),
                   "source_surface_tag": source} for source,pid in original.items() if pid in membership.values()]
        for _, pid in gmsh.model.getPhysicalGroups(2):
            gmsh.model.removePhysicalGroups([(2,pid)])
        for group in groups:
            gmsh.model.addPhysicalGroup(2, group["surface_tags"], group["pid"])
    return Context(cfg, geometry, sizing, membership, groups, gmsh.model.getCurrent(),model_signature())


def generate(context: Context) -> None:
    gmsh.model.mesh.generate(2)
    for _, volume in gmsh.model.getEntities(3):
        gmsh.model.mesh.setOutwardOrientation(volume)


def current(context: Context, profile: dict) -> tuple[dict, dict]:
    if gmsh.model.getCurrent() != context.model_name:
        raise ValueError("Gmsh model changed; rebuild BRL geometry before inspection")
    present = {t for _,t in gmsh.model.getEntities(2)}
    if present != set(context.membership):
        raise ValueError("CAD surface set changed; rebuild to refresh PID and boundary intent")
    if model_signature() != context.model_signature:
        raise ValueError("CAD or physical groups changed; rebuild or adopt the current model")
    # Topology metadata must follow the current model, including native CAD edits.
    volumes=gmsh.model.getEntities(3)
    context.geometry["closed_surface_tags"] = sorted({abs(int(t)) for d,t in gmsh.model.getBoundary(volumes,combined=False,oriented=False) if d==2}) if volumes else []
    context.geometry["volume_count"] = len(volumes)
    mesh = snapshot(context.membership)
    mesh["outward_normal_audit"] = inspect_normals(mesh)
    budget = context.sizing["element_budget"]
    context.sizing["post_mesh_budget"] = {"coverage": "not_assessed" if budget is None else "assessed",
                                         "actual_triangle_count": len(mesh["element_ids"]), "element_budget": budget,
                                         "budget_met": None if budget is None else len(mesh["element_ids"]) <= budget}
    assessment = analyze(mesh, context.geometry, context.sizing, profile, context.configuration["quality"])
    return mesh, assessment


def _rank(assessment: dict) -> tuple:
    shape = assessment["scores"]["element_shape"]["metrics"]
    return (shape["violating_element_count"], shape["aspect_ratio_max"] or float("inf"), -shape["minimum_angle_deg"])


def _nonshape_gates(assessment: dict) -> set:
    return {g["code"] for g in assessment["fatal_gates"] if g["code"] != "triangle_shape_limits"}


def _nonworse(before: dict, after: dict) -> bool:
    # Compare raw evidence: saturated 100-point scores can conceal regressions.
    checks = {
        "geometry_fidelity": ("area_relative_error", "volume_relative_error", "maximum_centroid_chord_error"),
        "size_compliance": ("longest_edge_to_target_q95", "edge_max", "elements_over_problem_ratio"),
        "gradation_and_features": ("adjacent_size_ratio_q99", "adjacent_size_ratio_max"),
    }
    for name, keys in checks.items():
        old, new = before["scores"][name], after["scores"][name]
        if old["coverage"] == "assessed" and new["coverage"] != "assessed":
            return False
        for key in keys:
            value = old["metrics"].get(key)
            if value is None:
                continue
            candidate = new["metrics"].get(key)
            if candidate is None or not np.isfinite(candidate) or candidate > value + 1e-10 * max(1, abs(value)):
                return False
    return True


def improve(context: Context, profile: dict) -> tuple[dict, dict, list]:
    mesh, assessment = current(context, profile)
    settings = context.configuration["mesh"]["improvement"]
    history = []
    if context.sizing.get("controlled", False):
        return mesh, assessment, history
    if not settings["enabled"] or _nonshape_gates(assessment):
        return mesh, assessment, history
    for i in range(settings["max_passes"]):
        if not assessment["fatal_gates"]:
            break
        method = settings["methods"][i % len(settings["methods"])]
        old = mesh
        before = assessment
        gmsh.model.mesh.optimize(method, niter=1, dimTags=[(2,t) for t in context.membership])
        candidate, after = current(context, profile)
        same_topology = all(np.array_equal(old[key], candidate[key]) for key in
                            ("node_ids", "element_ids", "connectivity", "pids", "surface_tags", "cad_boundary_edges"))
        # Point relocation must improve shape and preserve assessed geometry/size metrics.
        accepted = same_topology and not _nonshape_gates(after) and _rank(after) < _rank(before) and _nonworse(before, after)
        if not accepted:
            # Relocate2D/Laplace2D preserve connectivity; never approximate a rollback.
            if not same_topology:
                raise RuntimeError("surface relocation changed mesh topology; export withheld")
            for node, point in zip(old["node_ids"],old["coordinates"]):
                gmsh.model.mesh.setNode(int(node),point.tolist(),[])
            mesh,assessment=current(context,profile)
        else:
            mesh,assessment=candidate,after
        history.append({"method":method,"accepted":accepted,"before":list(_rank(before)),"after":list(_rank(after))})
    return mesh, assessment, history
