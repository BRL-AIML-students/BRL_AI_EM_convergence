import gmsh
import pytest

from geometry_mesh.config import validate
from geometry_mesh.geometry import build
from geometry_mesh.pipeline import run
from geometry_mesh.sizing import plan, apply, CONTROLLED_OPTIONS, C0


def test_manual_bounds_ignore_small_features_and_hold_gmsh_options():
    cfg = validate({"geometry": {"kind": "plate", "parameters": {"length": 1, "width": 100}}, "mesh": {"controlled": True, "mode": "fixed", "minimum_size": .2, "target_size": 8}})
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.model.add("controlled")
        geometry = build(cfg["geometry"], "mm", "mm")
        for wave in (False, True):
            cfg["mesh"]["wave"].update(enabled=wave, frequency_hz=10e9)
            sizing = plan(geometry, cfg["mesh"])
            apply(sizing)
            assert sizing["target_size"] == pytest.approx(min(8, C0 / 10e9 * 1000 / 10) if wave else 8)
            assert sizing["minimum_size"] == .2
            assert not sizing["local"]["fields_applied"]
            assert set(r["rule"] for r in sizing["candidate_rules"]) <= {"manual_bounds", "wavelength"}
            for key, value in CONTROLLED_OPTIONS.items():
                assert gmsh.option.getNumber(key) == value
    finally:
        gmsh.finalize()


def test_controlled_auto_bounds_and_no_postprocessing(tmp_path):
    result = run({"output_dir": str(tmp_path), "geometry": {"kind": "plate", "parameters": {"length": 10, "width": 10}}, "mesh": {"controlled": True, "scale_fraction": .2, "minimum_size_fraction": .01}})
    assert result["sizing"]["minimum_size"] == pytest.approx(result["geometry"]["scale"] * .01)
    assert result["sizing"]["target_size"] == pytest.approx(result["geometry"]["scale"] * .2)
    assert not result["improvement_history"]
    assert result["sizing"]["applied_options"]["Mesh.Smoothing"] == 1


def test_wave_adjusts_manual_floor_when_necessary():
    cfg = validate({"mesh": {"controlled": True, "mode": "fixed", "minimum_size": 4, "target_size": 8, "wave": {"enabled": True, "frequency_hz": 10e9}}})
    sizing = plan({"scale": 100, "surface_area": 1000, "output_unit": "mm"}, cfg["mesh"])
    assert sizing["minimum_size"] == sizing["target_size"]
    assert sizing["wave"]["minimum_adjusted_for_wave"] is True


@pytest.mark.parametrize("mesh", [{"mode": "fixed", "target_size": 2}, {"mode": "fixed", "minimum_size": 3, "target_size": 2}, {"element_budget": 100}, {"minimum_size_fraction": .2, "scale_fraction": .1}])
def test_controlled_invalid_bounds_and_conflicting_controls(mesh):
    with pytest.raises(ValueError):
        validate({"mesh": {"controlled": True, **mesh}})
