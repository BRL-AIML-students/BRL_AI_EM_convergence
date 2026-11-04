from dataclasses import replace
import json

import pytest

from brl_mesh import provenance
from brl_mesh.errors import MeshBlocked


def test_capture_and_verify_generation_conditions(config, tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, 'source_hash', lambda: 'a' * 64)
    monkeypatch.setattr(provenance, 'git_state', lambda: {'base_commit': 'b' * 40, 'brl_mesh_dirty': True, 'git_status_scope': 'brl_mesh tracked and unignored untracked files'})
    monkeypatch.setattr(provenance.gmsh.option, 'getNumber', lambda name: 6 if name == 'Mesh.Algorithm' else 1)
    captured = provenance.capture(config, None)
    data = json.loads(captured)
    assert data['source']['brl_mesh_dirty'] is True
    assert data['actual_algorithm'] is None and data['actual_threads'] is None
    provenance.require_current(captured, replace(config, output_dir=tmp_path / 'elsewhere'), None)
    with pytest.raises(MeshBlocked, match='변경'):
        provenance.require_current(captured, replace(config, output_unit='m'), None)
    with pytest.raises(MeshBlocked, match='변경'):
        provenance.require_current(captured, config, 'new CAD digest')
    monkeypatch.setattr(provenance, 'source_hash', lambda: 'c' * 64)
    with pytest.raises(MeshBlocked, match='변경'):
        provenance.require_current(captured, config, None)


def test_missing_generation_provenance_is_rejected(config):
    with pytest.raises(MeshBlocked, match='provenance'):
        provenance.require_current(None, config, None)


def test_schema3_requires_canonical_curvature_feedback(config, monkeypatch):
    from brl_mesh.sizing_config import Curvature
    monkeypatch.setattr(provenance.gmsh.option, 'getNumber', lambda name: 6 if name == 'Mesh.Algorithm' else 1)
    configured = replace(config, sizing=replace(config.sizing, curvature=Curvature(absolute_tolerance=.01)))
    data = json.loads(provenance.capture(configured, None))
    assert data['schema'] == 3
    assert data['effective_config']['mesh']['curvature']['feedback'] == 'entity'
    old = json.loads(provenance.canonical(data))
    old['schema'] = 2
    with pytest.raises(MeshBlocked, match='schema'):
        provenance.validate_schema(old)
    del data['effective_config']['mesh']['curvature']['feedback']
    with pytest.raises(MeshBlocked, match='schema'):
        provenance.validate_schema(data)


@pytest.mark.parametrize('change', ['bool_schema', 'extra', 'actual', 'bad_hash', 'missing_option'])
def test_strict_schema_rejects_invalid_metadata(config, monkeypatch, change):
    monkeypatch.setattr(provenance.gmsh.option, 'getNumber', lambda name: 6 if name == 'Mesh.Algorithm' else 1)
    data = json.loads(provenance.capture(config, None))
    if change == 'bool_schema':
        data['schema'] = True
    elif change == 'extra':
        data['extra'] = 'untrusted'
    elif change == 'actual':
        data['actual_algorithm'] = 6
    elif change == 'bad_hash':
        data['source']['sha256'] = 'x' * 64
    else:
        data['configured_options'].pop('Mesh.Algorithm')
    with pytest.raises(MeshBlocked, match='schema'):
        provenance.validate_schema(data)
    with pytest.raises(MeshBlocked, match='provenance'):
        provenance.require_current(provenance.canonical(data), config, None)


@pytest.mark.parametrize('change', ['unknown_mesh', 'negative_size', 'unit'])
def test_nested_effective_config_is_strict(config, monkeypatch, change):
    monkeypatch.setattr(provenance.gmsh.option, 'getNumber', lambda name: 6 if name == 'Mesh.Algorithm' else 1)
    data = json.loads(provenance.capture(config, None))
    if change == 'unknown_mesh':
        data['effective_config']['mesh']['extra'] = 1
    elif change == 'negative_size':
        data['effective_config']['mesh']['target_size'] = -1
    else:
        data['effective_config']['output_unit'] = 'yard'
    with pytest.raises(MeshBlocked, match='schema'):
        provenance.validate_schema(data)


def test_cad_metadata_validates_without_original_file(config, tmp_path, monkeypatch):
    from brl_mesh.config import CadFile
    from dataclasses import replace
    missing = tmp_path / 'not-present.step'
    monkeypatch.setattr(provenance.gmsh.option, 'getNumber', lambda name: 6 if name == 'Mesh.Algorithm' else 1)
    cad_config = replace(config, geometry=CadFile(missing))
    data = json.loads(provenance.capture(cad_config, 'a' * 64))
    provenance.validate_schema(data)
    assert not missing.exists()
    with pytest.raises(ValueError):
        from brl_mesh.config import Configuration
        Configuration.from_dict({**data['effective_config'], 'output_dir': str(tmp_path)})


def test_equivalent_integer_and_float_configurations_are_normalized(config, tmp_path, monkeypatch):
    monkeypatch.setattr(provenance.gmsh.option, 'getNumber', lambda name: 6 if name == 'Mesh.Algorithm' else 1)
    integer = replace(config, target_size=1)
    floating = replace(config, target_size=1.0, output_dir=tmp_path / 'other')
    captured = provenance.capture(integer, None)
    provenance.require_current(captured, floating, None)
    assert provenance.effective_config(integer) == provenance.effective_config(floating)
    assert provenance.canonical(provenance.effective_config(integer)) == provenance.canonical(provenance.effective_config(floating))
