import json

import gmsh
import numpy as np
import pytest

from brl_mesh import native_ui as ui
from brl_mesh.config import Configuration
from brl_mesh.engine import configure_mesh, run
from brl_mesh.errors import ConfigurationError
from brl_mesh.model import snapshot
from tests.test_native_ui import controller, action


def test_unsupported_native_width_preserves_existing_mesh(controller):
    assert 'ready' in action(controller, 2)
    before = snapshot(controller.scene.membership)
    gmsh.onelab.setString(ui.KIND, ['ogive'])
    gmsh.onelab.setNumber(ui.WIDTH_ENABLED, [1])
    assert 'width_unsupported' in action(controller, 1)
    after = snapshot({int(s): int(s) for s in before.surface_tags})
    assert before.same_structure(after)
    assert np.array_equal(before.coordinates, after.coordinates)
    assert gmsh.onelab.getString(ui.NAS_PATH) == ['']


def test_idle_avoids_mesh_scan_but_publish_detects_edit(controller, monkeypatch):
    action(controller, 2)
    ids, xyz, uv = gmsh.model.mesh.getNodes(2, 1)
    node = int(ids[0])
    point, parameters, _, _ = gmsh.model.mesh.getNode(node)
    gmsh.model.mesh.setNode(node, [*point[:2], point[2]+1], parameters)
    import brl_mesh.cad as cad
    real = cad.fingerprint
    monkeypatch.setattr(cad, 'fingerprint', lambda: pytest.fail('idle scanned CAD'))
    controller.invalidate_if_changed(deep=False)
    monkeypatch.setattr(cad, 'fingerprint', real)
    assert 'Blocked:' in action(controller, 4)
    assert gmsh.onelab.getString(ui.NAS_PATH) == ['']


def test_generation_fits_camera_once_and_shows_triangles(controller):
    for axis in 'XYZ':
        gmsh.option.setNumber('General.Scale'+axis, 100)
        gmsh.option.setNumber('General.Translation'+axis, 99)
    gmsh.option.setNumber('Mesh.SurfaceEdges', 0)
    assert 'ready' in action(controller, 2)
    assert gmsh.option.getNumber('Mesh.SurfaceEdges') == 1
    assert gmsh.option.getNumber('Mesh.SurfaceFaces') == 1
    assert gmsh.option.getNumber('General.TranslationX') == 0
    assert 0 < gmsh.option.getNumber('General.ScaleX') <= .8
    gmsh.option.setNumber('General.ScaleX', 1.7)
    controller.invalidate_if_changed(deep=False)
    controller.dispatch()
    assert gmsh.option.getNumber('General.ScaleX') == 1.7


def test_switch_to_curved_shape_enables_scale_independent_default(controller):
    gmsh.onelab.setString(ui.KIND, ['ogive'])
    controller.invalidate_if_changed(deep=False)
    config = ui.read_controls(controller.base, controller.base_dir)
    assert config.sizing.curvature.relative_tolerance == .001
    assert config.sizing.curvature.absolute_tolerance is None
    gmsh.onelab.setNumber(ui.CURVATURE_ENABLED, [0])
    controller.invalidate_if_changed(deep=False)
    assert ui.read_controls(controller.base, controller.base_dir).sizing.curvature is None


def test_curved_shape_default_generates_and_publishes(controller):
    gmsh.onelab.setString(ui.KIND, ['ogive'])
    assert action(controller, 1) == 'NAS published'
    assert controller.scene.curvature.history[-1][1] <= 1
    assert 'run_ogive_' in gmsh.onelab.getString(ui.NAS_PATH)[0]


def test_output_identifies_geometry_without_report_files(config):
    result = run(config)
    assert 'plate' in result.nas_path.parent.name
    assert {p.name for p in result.nas_path.parent.iterdir()} == {'mesh.nas'}
    header = result.nas_path.read_text(encoding='ascii').splitlines()
    geometry = json.loads(next(row.split(': ', 1)[1] for row in header if row.startswith('$ geometry input:')))
    assert geometry == config.to_dict()['geometry']


@pytest.mark.parametrize('data', [{'resources': {'max_nodes': 1}},
                                {'resources': {'max_memory_mb': 2048}}])
def test_removed_resource_schema_is_not_silently_accepted(config, data):
    with pytest.raises(ConfigurationError):
        Configuration.from_dict(config.to_dict() | data)


def test_sampling_and_iteration_settings_have_no_resource_ceiling(config, controller):
    value = config.to_dict()
    value['mesh']['curvature'] = {'absolute_tolerance': .01, 'sampling_nodes': 101,
                                 'verification_nodes': 201, 'max_iterations': 11}
    value['improvement']['max_passes'] = 11
    parsed = Configuration.from_dict(value)
    assert parsed.sizing.curvature.verification_nodes == 201
    ui.install_controls(parsed)
    assert ui.read_controls(parsed, parsed.output_dir) == parsed


def test_generation_does_not_override_native_thread_settings(config, controller):
    gmsh.option.setNumber('General.NumThreads', 2)
    gmsh.option.setNumber('Mesh.MaxNumThreads2D', 0)
    configure_mesh(config)
    assert gmsh.option.getNumber('General.NumThreads') == 2
    assert gmsh.option.getNumber('Mesh.MaxNumThreads2D') == 0
