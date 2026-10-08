from pathlib import Path

import gmsh
import pytest

from geometry_mesh.config import validate
from geometry_mesh.geometry import build
from geometry_mesh.pipeline import run
from geometry_mesh.native_ui import parameters, read_configuration


@pytest.mark.parametrize("t,area,volume", [(0, 48131.04921155456, 0), (3, 93201.5311996645, 138254.5150867228)])
def test_legacy_ogive_geometry_and_unit_conversion(t, area, volume):
    # 기존 make_ogive_cad.py / Gmsh 4.15.2의 D=110,L=200 기준 OCC 측정값.
    gmsh.initialize(readConfigFiles=False)
    gmsh.option.setNumber("General.Terminal", 0)
    try:
        gmsh.model.add("ogive_reference")
        info = build({"kind": "ogive", "parameters": {"D": 110, "L": 200, "t": t, "origin": [10, 20, 30]}}, "mm", "m")
        assert info["surface_area"] == pytest.approx(area * 1e-6, rel=1e-8)
        assert sum(gmsh.model.occ.getMass(3, tag) for _, tag in gmsh.model.getEntities(3)) == pytest.approx(volume * 1e-9, abs=1e-12)
        assert info["volume_count"] == (1 if t else 0)
        assert info["bbox_min"] == pytest.approx([-.045, -.035, .03], abs=2e-7)
        assert info["bbox_max"] == pytest.approx([.065, .075, .23], abs=2e-7)
        assert info["analytic_kind"] is None
    finally:
        gmsh.finalize()


@pytest.mark.parametrize("t", [0, 3])
def test_ogive_pipeline_and_no_step(tmp_path: Path, t):
    report = run({"name": "ogive", "output_dir": str(tmp_path), "geometry": {"kind": "ogive", "parameters": {"D": 110, "L": 200, "t": t}}, "mesh": {"scale_fraction": .04}})
    assert report["assessment"]["raw_metrics"]["triangle_count"] > 0
    assert report["geometry"]["volume_count"] == (1 if t else 0)
    assert not list(tmp_path.rglob("*.step"))
    gates = {g["code"] for g in report["assessment"]["fatal_gates"]}
    assert not gates - {"triangle_shape_limits"}, gates


def test_ogive_native_parameters_roundtrip():
    cfg = validate({"geometry": {"kind": "ogive", "parameters": {"D": 110, "L": 200, "t": 0}}})
    gmsh.initialize(readConfigFiles=False)
    try:
        import json
        gmsh.onelab.set(json.dumps(parameters(cfg)))
        assert read_configuration(cfg)["geometry"] == {"kind": "ogive", "parameters": {"D": 110., "L": 200., "t": 0., "origin": [0., 0., 0.]}}
    finally:
        gmsh.finalize()


@pytest.mark.parametrize("updates", [{"D": 0}, {"L": 20}, {"t": -1}, {"t": 55}, {"t": float("nan")}])
def test_ogive_invalid_parameters(updates):
    with pytest.raises(ValueError):
        validate({"geometry": {"kind": "ogive", "parameters": {"D": 110, "L": 200, "t": 3, **updates}}})
