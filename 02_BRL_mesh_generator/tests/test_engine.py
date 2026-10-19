from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from brl_mesh import engine, nas
from brl_mesh.errors import MeshBlocked
from brl_mesh.model import snapshot


def test_generation_repeats_without_overwriting_and_only_publishes_nas(config):
    first, second = engine.run(config), engine.run(config)
    assert first.nas_path != second.nas_path
    assert first.nas_path.read_bytes() == second.nas_path.read_bytes()
    files = sorted(config.output_dir.rglob('*'))
    assert {p.name for p in files if p.is_file()} == {'mesh.nas'}
    assert len([p for p in files if p.is_file()]) == 2
    assert not list(config.output_dir.glob('.pending-*'))


def test_unit_conversion_is_applied_to_geometry(config):
    config = replace(config, output_unit='m', target_size=0.00025)
    with engine.mesh_model(config) as scene:
        membership = scene.membership
        mesh = snapshot(membership)
    assert np.ptp(mesh.coordinates, axis=0) == pytest.approx([0.001, 0.001, 0])


def test_failed_independent_validation_preserves_prior_output_and_cleans_stage(config, monkeypatch):
    old_file = config.output_dir / 'previous' / 'mesh.nas'
    old_file.parent.mkdir(parents=True)
    old_file.write_text('previous result', encoding='ascii')
    called = []
    def fail(*_):
        called.append(True)
        raise MeshBlocked('independent reader failure')
    monkeypatch.setattr(nas, 'validate', fail)
    with engine.mesh_model(config) as scene:
        membership = scene.membership
        with pytest.raises(MeshBlocked, match='independent reader failure'):
            engine.publish(snapshot(membership), config, scene)
    assert called == [True]
    assert old_file.read_text(encoding='ascii') == 'previous result'
    assert list(config.output_dir.iterdir()) == [old_file.parent]


def test_cli_success_and_invalid_input_have_minimal_json_state(tmp_path):
    config_path = tmp_path / 'plate.json'
    config_path.write_text(json.dumps({'schema_version': 1, 'geometry': {'kind': 'plate', 'length': 1, 'width': 1},
                                     'mesh': {'target_size': 0.25}, 'output_dir': 'result'}), encoding='utf-8')
    environment = os.environ | {'PYTHONUTF8': '1'}
    valid = subprocess.run([sys.executable, '-m', 'brl_mesh', str(config_path)],
                           capture_output=True, text=True, encoding='utf-8', env=environment)
    assert valid.returncode == 0, valid.stderr
    state = json.loads(valid.stdout)
    assert set(state) == {'status', 'nas_path'} and state['status'] == 'ok'
    assert Path(state['nas_path']).is_file()
    config_path.write_text('{"schema_version":2}', encoding='utf-8')
    invalid = subprocess.run([sys.executable, '-m', 'brl_mesh', str(config_path)],
                             capture_output=True, text=True, encoding='utf-8', env=environment)
    assert invalid.returncode == 1 and not invalid.stdout
    assert json.loads(invalid.stderr)['status'] == 'error'


def test_cli_disabled_improvement_still_blocks_bad_shape(tmp_path):
    source = tmp_path / 'thin.json'
    source.write_text(json.dumps({'schema_version': 1,
        'geometry': {'kind': 'plate', 'length': 1, 'width': .01},
        'mesh': {'target_size': .25}, 'improvement': {'enabled': False},
        'output_dir': 'blocked-output'}), encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'brl_mesh', str(source)],
                            capture_output=True, text=True, encoding='utf-8', env=os.environ | {'PYTHONUTF8': '1'})
    assert result.returncode == 2 and not result.stdout
    assert json.loads(result.stderr)['status'] == 'blocked'
    assert not (tmp_path / 'blocked-output').exists()
