from copy import deepcopy
import math
from pathlib import Path

import gmsh
import numpy as np
import pytest

from geometry_mesh.config import DEFAULTS, validate
from geometry_mesh.pipeline import _profile, run
from geometry_mesh.quality import analyze
from geometry_mesh.topology import inspect


def mesh(points, triangles, surfaces=None):
    return {"node_ids": np.arange(1, len(points) + 1), "coordinates": np.asarray(points, dtype=float),
            "element_ids": np.arange(101, 101 + len(triangles)), "connectivity": np.asarray(triangles),
            "pids": np.ones(len(triangles), dtype=int), "surface_tags": np.asarray(surfaces or [1]*len(triangles))}


def settings(**changes):
    result = deepcopy(DEFAULTS["quality"]["topology"])
    result.update(boundary_mode="open", **changes)
    return result


def codes(gates):
    return {g["code"] for g in gates}


def shape(m):
    geometry = {"scale": 1.0, "volume_count": 0, "analytic_kind": None}
    sizing = {"target_size": 1.0, "user_size_cap": None, "growth_assessment_limit": 1.6,
              "candidate_rules": [], "narrow_gap_detected": None, "narrow_gap_evidence": {},
              "budget_conflict": None, "post_mesh_budget": {"coverage": "not_assessed"}}
    config = deepcopy(DEFAULTS["quality"]); config["topology"]["boundary_mode"] = "open"
    return analyze(m, geometry, sizing, _profile(), config)


@pytest.mark.parametrize("scale", [1e-6, 1, 1e6])
def test_analytical_aspect_and_sliver_gate(scale):
    m = mesh(np.asarray([[0,0,0],[1,0,0],[.5,math.sqrt(3)/2,0]])*scale, [[1,2,3]])
    a = shape(m)
    assert a["scores"]["element_shape"]["metrics"]["aspect_ratio_max"] == pytest.approx(1)
    assert a["quality_gate_status"] == "pass"
    m["coordinates"][2] = np.asarray([.5,.01,0])*scale
    a = shape(m)
    assert a["scores"]["element_shape"]["metrics"]["aspect_ratio_max"] == pytest.approx(57.7407998374)
    assert "triangle_shape_limits" in codes(a["fatal_gates"])
    assert a["scores"]["element_shape"]["problem_element_ids"] == [101]


def test_t_junction_and_conforming_split_in_bent_surface():
    points = [[0,0,0],[2,0,0],[1,0,0],[1,1,0],[.5,-1,.2],[1.5,-1,.2]]
    bad = mesh(points, [[1,2,4],[1,5,3],[3,6,2]])
    report, gates = inspect(bad, {}, settings())
    assert "t_junctions" in codes(gates)
    assert any(r["node_id"]==3 and r["edge"]==[1,2] for r in report["t_junctions"])
    good = mesh(points, [[1,3,4],[3,2,4],[1,5,3],[3,6,2]])
    report, gates = inspect(good, {}, settings())
    assert not report["t_junctions"] and not gates


def test_intentional_gap_is_not_welded_and_ambiguous_gap_blocks():
    m = mesh([[0,0,0],[2,0,0],[1,1,0],[1,-1e-5,0],[.5,-1,0],[1.5,-1,0]], [[1,2,3],[4,5,6]], [1,2])
    report, gates = inspect(m, {}, settings())
    assert not gates
    report, gates = inspect(m, {}, settings(absolute_tolerance=1e-4))
    assert not report["t_junctions"]
    assert "conformity_review_required" in codes(gates)
    report, gates = inspect(m, {}, settings(absolute_tolerance=1e-4, separated_surface_pairs=[[1,2]]))
    assert not gates and report["explicitly_separated_candidates"]


def test_different_ids_at_same_position_and_vertex_fans():
    m=mesh([[0,0,0],[1,0,0],[0,1,0],[0,0,0],[-1,0,0],[0,-1,0]], [[1,2,3],[4,5,6]])
    report,gates=inspect(m,{},settings())
    assert "unshared_coincident_nodes" in codes(gates)
    m["connectivity"][1,0]=1
    report,gates=inspect(m,{},settings())
    assert "nonmanifold_vertices" in codes(gates)


def test_component_closure_is_not_global_and_resource_limit_is_not_pass():
    m=mesh([[0,0,0],[1,0,0],[0,1,0],[0,0,1],[3,0,0],[4,0,0],[3,1,0]],
           [[1,3,2],[1,2,4],[2,3,4],[3,1,4],[5,6,7]],[1,1,1,1,2])
    report,gates=inspect(m,{"closed_surface_tags":[1]}, {**settings(),"boundary_mode":"auto"})
    assert [x["expected_closed"] for x in report["components"]]==[True,False]
    assert "open_volume_boundary" not in codes(gates)
    bad=mesh([[0,0,0],[2,0,0],[1,0,0],[1,1,0],[.5,-1,0],[1.5,-1,0]],[[1,2,4],[1,5,3],[3,6,2]])
    report,gates=inspect(bad,{},settings(max_candidate_tests=1))
    assert not report["audit_complete"]
    assert "conformity_review_required" in codes(gates)


def test_no_automatic_waiver_or_invalid_policy():
    with pytest.raises(ValueError,match="no automatic waiver"):
        validate({"quality":{"max_aspect_ratio":5}})
    with pytest.raises(ValueError,match="min_angle_deg"):
        validate({"quality":{"min_angle_deg":15}})


def test_shape_failure_withholds_nas_but_keeps_diagnostics(tmp_path: Path):
    report=run({"name":"strict", "output_dir":str(tmp_path), "geometry":{"kind":"plate","parameters":{"length":10,"width":10}},
                "mesh":{"local":{"enabled":False}}, "quality":{"max_aspect_ratio":1.01,"min_angle_deg":59}})
    assert report["status"]=="invalid" and report["assessment"]["quality_gate_status"]=="fail"
    output=Path(report["output_directory"])
    assert not (output/'strict.nas').exists()
    assert (output/'report.json').exists() and (output/'quality_report.html').exists()
