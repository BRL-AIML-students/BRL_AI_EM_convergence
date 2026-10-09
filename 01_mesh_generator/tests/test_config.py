import json
import re

import pytest

from geometry_mesh.config import validate, load
from geometry_mesh.cli import main


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


def supplied_at(path, value):
    result = {}
    node = result
    keys = path.split(".")
    for key in keys[:-1]:
        node[key] = {}
        node = node[key]
    node[keys[-1]] = value
    return result


@pytest.mark.parametrize("path", [
    "mesh", "mesh.wave", "mesh.local", "mesh.narrow_gap", "mesh.improvement",
    "naming", "export", "quality", "quality.topology", "geometry", "geometry.parameters",
])
@pytest.mark.parametrize("value", [None, 1, [], True, "invalid"])
def test_object_types_raise_located_value_error(path, value):
    with pytest.raises(ValueError, match=re.escape(path) + " must be an object"):
        validate(supplied_at(path, value))


@pytest.mark.parametrize("value", [None, 1, {}, "xyz", [0, 0], [0, 0, True]])
def test_origin_array_types_are_validated(value):
    with pytest.raises(ValueError, match="geometry.parameters.origin"):
        validate({"geometry": {"kind": "plate", "parameters": {"length": 1, "width": 1, "origin": value}}})


@pytest.mark.parametrize("path", ["length_unit", "output_unit", "mesh.mode", "mesh.budget_policy", "quality.topology.boundary_mode", "geometry.kind"])
@pytest.mark.parametrize("value", [[], {}, None])
def test_enum_container_types_raise_value_error(path, value):
    with pytest.raises(ValueError, match=re.escape(path)):
        validate(supplied_at(path, value))


@pytest.mark.parametrize("data,path", [
    ({"geometry": None}, "geometry"),
    ({"geometry": []}, "geometry"),
    ({"geometry": {"kind": "cad", "path": None}}, "geometry.path"),
    ({"geometry": {"kind": "cad", "path": []}}, "geometry.path"),
    ({"geometry": {"kind": "cut", "objects": None}}, "geometry.objects"),
    ({"geometry": {"kind": "cut", "objects": [None, {}]}}, "geometry.objects[0]"),
    ({"geometry": {"kind": "cut", "objects": [[], {}]}}, "geometry.objects[0]"),
    ({"mesh": None}, "mesh"),
])
def test_invalid_file_structure_has_same_validation_contract(tmp_path, data, path):
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(path)):
        load(source)


def test_cli_invalid_object_is_located_error_without_generation(tmp_path, capsys):
    source = tmp_path / "invalid.json"
    source.write_text('{"mesh":null}', encoding="utf-8")
    assert main([str(source), "--quiet"]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert "mesh must be an object" in output.err
