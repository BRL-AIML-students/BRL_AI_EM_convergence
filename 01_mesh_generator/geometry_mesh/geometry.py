from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import gmsh

UNIT_METRES = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6}


def _primitive(node: dict[str, Any], scale: float) -> list[tuple[int, int]]:
    occ = gmsh.model.occ
    kind = node["kind"]
    p = node.get("parameters", {})
    x, y, z = (float(value) * scale for value in p.get("origin", [0.0, 0.0, 0.0]))
    if kind == "plate":
        return [(2, occ.addRectangle(x, y, z, p["length"] * scale, p["width"] * scale))]
    if kind == "disk":
        return [(2, occ.addDisk(x, y, z, p["radius"] * scale, p["radius"] * scale))]
    if kind == "sphere":
        return [(3, occ.addSphere(x, y, z, p["radius"] * scale))]
    if kind == "box":
        return [(3, occ.addBox(x, y, z, p["length"] * scale, p["width"] * scale, p["height"] * scale))]
    if kind == "cylinder":
        return [(3, occ.addCylinder(x, y, z, 0.0, 0.0, p["height"] * scale, p["radius"] * scale))]
    if kind == "ogive":
        from .ogive import build as build_ogive
        return build_ogive(p["D"] * scale, p["L"] * scale, p["t"] * scale, (x, y, z))
    raise ValueError(f"unsupported primitive {kind}")


def _build_node(node: dict[str, Any], scale: float, output_unit: str) -> list[tuple[int, int]]:
    kind = node["kind"]
    occ = gmsh.model.occ
    if kind in {"plate", "disk", "sphere", "box", "cylinder", "ogive"}:
        return _primitive(node, scale)
    if kind == "cad":
        suffix = Path(node["path"]).suffix.lower()
        if suffix != ".brep":
            gmsh.option.setString("Geometry.OCCTargetUnit", output_unit.upper())
        imported = occ.importShapes(str(Path(node["path"]).resolve()), highestDimOnly=False)
        if not imported:
            raise ValueError("CAD import produced no entities")
        top_dim = max(dim for dim, _ in imported)
        roots = [dt for dt in imported if dt[0] == top_dim]
        if suffix == ".brep" and scale != 1.0:
            occ.dilate(roots, 0.0, 0.0, 0.0, scale, scale, scale)
        return roots
    children = [_build_node(child, scale, output_unit) for child in node["objects"]]
    current = children[0]
    for tools in children[1:]:
        if kind == "fuse":
            current, _ = occ.fuse(current, tools, removeObject=True, removeTool=True)
        elif kind == "cut":
            current, _ = occ.cut(current, tools, removeObject=True, removeTool=True)
        else:
            current, _ = occ.intersect(current, tools, removeObject=True, removeTool=True)
        if not current:
            raise ValueError(f"{kind} operation produced an empty geometry")
    return current


def build(spec: dict[str, Any], length_unit: str, output_unit: str) -> dict[str, Any]:
    explicit_scale = UNIT_METRES[length_unit] / UNIT_METRES[output_unit]
    roots = _build_node(spec, explicit_scale, output_unit)
    gmsh.model.occ.synchronize()
    surfaces = gmsh.model.getEntities(2)
    if not surfaces:
        raise ValueError("geometry contains no surfaces")
    bbox = gmsh.model.getBoundingBox(-1, -1)
    spans = [bbox[i + 3] - bbox[i] for i in range(3)]
    scale = math.sqrt(sum(span * span for span in spans))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("geometry bounding box has zero or invalid scale")
    surface_area = sum(gmsh.model.occ.getMass(2, tag) for _, tag in surfaces)
    if not math.isfinite(surface_area) or surface_area <= 0:
        raise ValueError("geometry surface area is zero or invalid")
    volumes = gmsh.model.getEntities(3)
    closed_surface_tags = sorted({abs(int(tag)) for dim, tag in gmsh.model.getBoundary(volumes, combined=False, oriented=False) if dim == 2}) if volumes else []
    return {
        "root_entities": [[int(d), int(t)] for d, t in roots],
        "surface_count": len(surfaces),
        "volume_count": len(volumes),
        "closed_surface_tags": closed_surface_tags,
        "bbox_min": list(map(float, bbox[:3])),
        "bbox_max": list(map(float, bbox[3:])),
        "scale": float(scale),
        "surface_area": float(surface_area),
        "analytic_kind": spec["kind"] if spec["kind"] in {"plate", "disk", "sphere", "box", "cylinder"} else None,
        "analytic_parameters": spec.get("parameters") if spec["kind"] in {"plate", "disk", "sphere", "box", "cylinder"} else None,
        "source_kind": spec["kind"],
        "length_unit": length_unit,
        "output_unit": output_unit,
        "explicit_scale": explicit_scale,
    }


def assign_surface_groups(pid_start: int) -> tuple[dict[int, int], list[dict[str, Any]]]:
    membership: dict[int, int] = {}
    groups: list[dict[str, Any]] = []
    for offset, (_, surface) in enumerate(sorted(gmsh.model.getEntities(2))):
        pid = pid_start + offset
        gmsh.model.addPhysicalGroup(2, [surface], pid)
        name = gmsh.model.getEntityName(2, surface) or f"surface_{surface}"
        gmsh.model.setPhysicalName(2, pid, name)
        membership[surface] = pid
        groups.append({"pid": pid, "name": name, "surface_tags": [surface]})
    return membership, groups
