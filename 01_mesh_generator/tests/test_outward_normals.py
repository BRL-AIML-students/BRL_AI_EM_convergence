from copy import deepcopy
import gmsh
import numpy as np
import pytest

from geometry_mesh.config import validate
from geometry_mesh.pipeline import initialize, _profile, publish_current
from geometry_mesh.session import prepare, generate, current, adopt_current


@pytest.fixture
def session():
    initialize()
    try:
        yield
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


def box(origin=None):
    return {"kind": "box", "parameters": {"length": 10, "width": 10, "height": 10,
            "origin": origin or [0, 0, 0]}}


@pytest.mark.parametrize("geometry", [
    box(), box([1e5, 0, 0]),
    {"kind": "sphere", "parameters": {"radius": 5}},
    {"kind": "fuse", "objects": [box(), box([20, 0, 0])]},
    {"kind": "cut", "objects": [box(), {"kind": "box", "parameters": {
        "length": 6, "width": 6, "height": 6, "origin": [2, 2, 2]}}]},
])
def test_cad_direction_checked_without_changing_mesh(session, tmp_path, geometry):
    cfg = validate({"name": "normals", "output_dir": str(tmp_path), "geometry": geometry,
                    "mesh": {"local": {"enabled": False}, "scale_fraction": .2}})
    context = prepare(cfg)
    generate(context)
    before, assessment = current(context, _profile())
    audit = assessment["scores"]["topology_and_normals"]["metrics"]["outward_normals"]
    assert audit["coverage"] == "assessed"
    assert not audit["reversed_element_ids"]
    assert not audit["ambiguous_element_ids"]
    original = deepcopy(before)
    gmsh.model.mesh.reverse(gmsh.model.getEntities(2))
    reversed_mesh, reversed_assessment = current(context, _profile())
    assert "inward_cad_normals" in {gate["code"] for gate in reversed_assessment["fatal_gates"]}
    assert np.array_equal(original["coordinates"], reversed_mesh["coordinates"])
    assert not np.array_equal(original["connectivity"], reversed_mesh["connectivity"])
    report = publish_current(context)
    assert report["status"] == "invalid" and report["artifacts"]["nas"] is None
    after, _ = current(context, _profile())
    assert np.array_equal(after["connectivity"], reversed_mesh["connectivity"])


def test_native_cad_adoption_uses_same_direction_gate(session, tmp_path):
    cfg = validate({"output_dir": str(tmp_path), "geometry": box(),
                    "mesh": {"local": {"enabled": False}}})
    context = prepare(cfg)
    generate(context)
    gmsh.model.mesh.reverse(gmsh.model.getEntities(2))
    loaded = adopt_current(cfg)
    report = publish_current(loaded)
    assert report["status"] == "invalid"
    assert "inward_cad_normals" in {g["code"] for g in report["assessment"]["fatal_gates"]}


def test_discrete_closed_mesh_has_explicit_direction_coverage(session, tmp_path):
    cfg = validate({"output_dir": str(tmp_path), "geometry": box(),
                    "mesh": {"local": {"enabled": False}}})
    context = prepare(cfg)
    generate(context)
    gmsh.option.setNumber("Mesh.SaveAll", 1)
    path = tmp_path / "mesh.msh"
    gmsh.write(str(path))
    gmsh.clear()
    gmsh.open(str(path))
    loaded = adopt_current(cfg)
    _, assessment = current(loaded, _profile())
    audit = assessment["scores"]["topology_and_normals"]["metrics"]["outward_normals"]
    assert audit["coverage"] == "not_assessed"
    assert not {g["code"] for g in assessment["fatal_gates"]} & {"inward_cad_normals", "outward_normals_review_required"}


def test_unavailable_cad_direction_withholds_export(session, tmp_path, monkeypatch):
    cfg = validate({"output_dir": str(tmp_path), "geometry": box()})
    context = prepare(cfg)
    generate(context)
    monkeypatch.setattr(gmsh.model, "isInside", lambda *args, **kwargs: 0)
    report = publish_current(context)
    assert report["status"] == "invalid" and report["artifacts"]["nas"] is None
    assert "outward_normals_review_required" in {g["code"] for g in report["assessment"]["fatal_gates"]}
    assert report["assessment"]["quality_gate_status"] == "review_required"


def test_open_sheet_direction_is_not_inferred(session, tmp_path):
    cfg = validate({"output_dir": str(tmp_path), "mesh": {"local": {"enabled": False}}})
    context = prepare(cfg)
    generate(context)
    gmsh.model.mesh.reverse(gmsh.model.getEntities(2))
    _, assessment = current(context, _profile())
    audit = assessment["scores"]["topology_and_normals"]["metrics"]["outward_normals"]
    assert audit["coverage"] == "not_assessed"
    assert assessment["quality_gate_status"] == "pass"
