from dataclasses import replace
import json
import subprocess
import sys

import gmsh
import pytest

from brl_mesh import resources
from brl_mesh.config import Configuration
from brl_mesh.engine import run, mesh_model, publish
from brl_mesh.errors import ConfigurationError, MeshBlocked
from brl_mesh.model import snapshot
from brl_mesh.resources import Resources, resource_scope, checkpoint
from brl_mesh.sizing_config import Curvature


def test_real_process_memory_api_and_mesh_limits(config):
    assert 0 < resources.memory_mb() < 2048
    for limits in (Resources(max_nodes=1), Resources(max_triangles=1), Resources(max_memory_mb=.001)):
        with pytest.raises(MeshBlocked, match='resource_(mesh|memory)_limit'):
            run(replace(config, resources=limits))
        assert not config.output_dir.exists()
        assert not gmsh.isInitialized()


def test_action_time_and_projection_budgets_are_shared_and_reset(monkeypatch):
    now = [100.]
    monkeypatch.setattr(resources.time, 'monotonic', lambda: now[0])
    with resource_scope(Resources(max_seconds=2, max_projection_samples=5)):
        checkpoint(samples=3)
        with resource_scope(Resources()):
            with pytest.raises(MeshBlocked, match='resource_projection_limit'):
                checkpoint(samples=3)
    with resource_scope(Resources(max_seconds=2)):
        now[0] += 3
        with pytest.raises(MeshBlocked, match='resource_time_limit'):
            checkpoint()
    now[0] = 1000  # UI idle time is outside the next action's budget.
    with resource_scope(Resources(max_seconds=2, max_projection_samples=5)):
        checkpoint(samples=5)


def test_curvature_projection_work_limit_blocks_without_output(config):
    configured = replace(config, sizing=replace(config.sizing, curvature=Curvature(absolute_tolerance=.01)),
                         resources=Resources(max_projection_samples=1))
    with pytest.raises(MeshBlocked, match='resource_projection_limit'):
        run(configured)
    assert not config.output_dir.exists()


def test_post_nas_validation_limit_removes_only_current_pending(config, monkeypatch):
    old = run(config).nas_path
    content = old.read_bytes()
    import brl_mesh.engine as engine
    real_validate = engine.nas.validate
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        def validate(*args):
            real_validate(*args)
            monkeypatch.setattr(resources, 'memory_mb', lambda: 10000)
        monkeypatch.setattr(engine.nas, 'validate', validate)
        with pytest.raises(MeshBlocked, match='resource_memory_limit'):
            publish(mesh, config, scene)
    assert old.read_bytes() == content
    assert list(config.output_dir.rglob('mesh.nas')) == [old]
    assert not list(config.output_dir.glob('.pending-*'))


@pytest.mark.parametrize('key,value', [('max_nodes', True), ('max_triangles', 0), ('max_nodes', 1.1),
    ('max_seconds', float('inf')), ('max_memory_mb', -1), ('max_projection_samples', '5'), ('max_circle', 200)])
def test_resource_schema_is_strict(config, key, value):
    data = config.to_dict()
    data['resources'] = {key: value}
    with pytest.raises(ConfigurationError):
        Configuration.from_dict(data)


def test_real_cli_resource_block_preserves_previous_nas(config, tmp_path):
    old = run(config).nas_path
    data = config.to_dict()
    data['resources'] = {'max_triangles': 1}
    path = tmp_path/'limit.json'
    path.write_text(json.dumps(data), encoding='utf8')
    completed = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'brl_mesh', str(path)],
                               capture_output=True, text=True, encoding='utf8', timeout=20)
    assert completed.returncode == 2
    assert not completed.stdout.strip()
    state = json.loads(completed.stderr)
    assert state['status'] == 'blocked' and 'resource_mesh_limit' in state['reason']
    assert list(config.output_dir.rglob('mesh.nas')) == [old]
