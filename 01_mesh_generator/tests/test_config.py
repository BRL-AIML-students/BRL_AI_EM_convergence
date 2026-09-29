from pathlib import Path

import pytest

from geometry_mesh.config import validate


def test_defaults_and_units():
    cfg = validate({
        "version": 1, "name": "p", "output_dir": "out", "length_unit": "cm", "output_unit": "mm",
        "geometry": {"kind": "disk", "parameters": {"radius": 2.0}},
    })
    assert cfg["mesh"]["mode"] == "auto"
    assert cfg["output_unit"] == "mm"


def test_rejects_unknown_physics_or_other_key():
    with pytest.raises(ValueError, match="unknown top-level"):
        validate({"version": 1, "name": "p", "output_dir": "out", "geometry": {"kind": "disk", "parameters": {"radius": 2}}, "analysis": {}})


def test_fixed_requires_target():
    with pytest.raises(ValueError, match="target_size"):
        validate({"version": 1, "name": "p", "output_dir": "out", "geometry": {"kind": "plate", "parameters": {"length": 1, "width": 1}}, "mesh": {"mode": "fixed"}})

