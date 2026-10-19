import json
from dataclasses import replace

import gmsh
import numpy as np
import pytest

from brl_mesh import native_ui as ui
from brl_mesh.engine import run
from brl_mesh.model import snapshot
from tests.support import distort_interior
from tests.test_cad import cad_config, write_cad


@pytest.fixture
def controller(config):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        yield ui.Controller(config, config.output_dir.parent)
    finally:
        gmsh.finalize()


def action(controller, code):
    gmsh.onelab.setString(ui.ACTION, [ui.ACTIONS[code]])
    controller.dispatch()
    assert gmsh.onelab.getString(ui.ACTION) == ['Idle']
    return gmsh.onelab.getString(ui.STATUS)[0]


def test_native_and_cli_share_exact_output_and_idle_never_duplicates(config):
    expected = run(config).nas_path.read_bytes()
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        controller = ui.Controller(config, config.output_dir.parent)
        definition = json.loads(gmsh.onelab.get(ui.ACTION))
        assert definition['choices'] == list(ui.ACTIONS.values())
        assert json.loads(gmsh.onelab.get(ui.CAD_PATH))['kind'] == 'file'
        assert ui.read_controls(config, config.output_dir.parent) == config
        assert action(controller, 1) == 'NAS published'
        from pathlib import Path
        path = Path(gmsh.onelab.getString(ui.NAS_PATH)[0])
        assert path.read_bytes() == expected
        for _ in range(3):
            controller.dispatch()
        assert len(list(config.output_dir.rglob('mesh.nas'))) == 2
        assert len(gmsh.view.getTags()) == 0
    finally:
        gmsh.finalize()


@pytest.mark.parametrize('mutation', ['size', 'unit', 'cad', 'physical', 'invalid_value'])
def test_control_or_cad_change_invalidates_prior_result(controller, config, mutation):
    assert 'ready' in action(controller, 2)
    if mutation == 'size':
        gmsh.onelab.setNumber(ui.TARGET, [.3])
    elif mutation == 'unit':
        gmsh.onelab.setString(ui.OUTPUT_UNIT, ['cm'])
    elif mutation == 'cad':
        gmsh.model.occ.translate(gmsh.model.getEntities(2), .1, 0, 0)
        gmsh.model.occ.synchronize()
    elif mutation == 'physical':
        gmsh.model.removePhysicalGroups()
    else:
        gmsh.onelab.setNumber(ui.PASSES, [1.5])
    controller.invalidate_if_changed()
    assert controller.scene is None
    assert 'Blocked:' in action(controller, 4)
    assert not config.output_dir.exists()


def test_manual_interior_mesh_change_discards_old_result_and_rechecks_current(controller, config):
    action(controller, 2)
    scene = controller.scene
    distort_interior(scene.membership)
    controller.invalidate_if_changed()
    assert controller.scene is scene and controller.last_mesh is None
    assert 'Blocked:' in action(controller, 4)
    assert not config.output_dir.exists()
    assert 'completed' in action(controller, 3)
    assert action(controller, 4) == 'NAS published'


def test_manual_boundary_line_connectivity_cannot_be_published(controller, config):
    action(controller, 2)
    line = gmsh.model.getEntities(1)[0][1]
    types, ids, nodes = gmsh.model.mesh.getElements(1, line)
    gmsh.model.mesh.removeElements(1, line, [int(ids[0][0])])
    assert 'Blocked:' in action(controller, 4)
    assert not config.output_dir.exists()


def test_native_cad_fields_roundtrip_and_changed_source_requires_regeneration(tmp_path):
    path = write_cad(tmp_path / 'sheet.brep')
    config = cad_config(path, geometry={'sheet_normal': -1, 'sheet_normals': {'1': -1}})
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        controller = ui.Controller(config, tmp_path)
        assert ui.read_controls(config, tmp_path) == config
        assert 'ready' in action(controller, 2)
        path.write_bytes(path.read_bytes() + b'\n')
        controller.invalidate_if_changed()
        assert controller.scene is None
        assert 'Blocked:' in action(controller, 4)
    finally:
        gmsh.finalize()
    assert not config.output_dir.exists()


def test_native_error_consumes_action_without_publishing(controller, config):
    gmsh.onelab.setString(ui.ACTION, ['unknown action'])
    controller.dispatch()
    assert gmsh.onelab.getString(ui.ACTION) == ['Idle']
    assert gmsh.onelab.getString(ui.STATUS)[0].startswith('Blocked:')
    assert not config.output_dir.exists()
    action(controller, 5)
    assert controller.close_requested


def test_real_native_loop_wiring_on_fake_fltk_surface(config, monkeypatch):
    # Controller/ONELAB/Gmsh remain real; this test does not claim visual QA.
    events = []
    monkeypatch.setattr(gmsh.fltk, 'initialize', lambda: events.append('initialize'))
    monkeypatch.setattr(gmsh.fltk, 'openTreeItem', lambda name: events.append(name))
    monkeypatch.setattr(gmsh.fltk, 'isAvailable', lambda: True)
    def wait(_):
        gmsh.onelab.setString(ui.ACTION, [ui.ACTIONS[1 if 'published' not in events else 5]])
    def update():
        if gmsh.onelab.getString(ui.STATUS) == ['NAS published']:
            events.append('published')
    monkeypatch.setattr(gmsh.fltk, 'wait', wait)
    monkeypatch.setattr(gmsh.fltk, 'update', update)
    ui.launch(config, config.output_dir.parent)
    assert events == ['initialize', 'ONELAB', 'published']
    assert len(list(config.output_dir.rglob('mesh.nas'))) == 1
    assert not gmsh.isInitialized()


def test_window_close_during_wait_does_not_reopen_or_dispatch(config, monkeypatch):
    available = True
    monkeypatch.setattr(gmsh.fltk, 'initialize', lambda: None)
    monkeypatch.setattr(gmsh.fltk, 'openTreeItem', lambda _: None)
    monkeypatch.setattr(gmsh.fltk, 'isAvailable', lambda: available)
    def close(_):
        nonlocal available
        available = False
        gmsh.onelab.setString(ui.ACTION, [ui.ACTIONS[1]])
    monkeypatch.setattr(gmsh.fltk, 'wait', close)
    monkeypatch.setattr(gmsh.fltk, 'update', lambda: pytest.fail('closed window must not reopen'))
    ui.launch(config, config.output_dir.parent)
    assert not config.output_dir.exists()
    assert not gmsh.isInitialized()


def test_geometry_controls_show_only_applied_inputs(controller):
    assert not json.loads(gmsh.onelab.get(ui.CAD_PATH))['visible']
    assert not json.loads(gmsh.onelab.get(ui.SHEET_SIGN))['visible']
    assert json.loads(gmsh.onelab.get(ui.LENGTH))['visible']
    gmsh.onelab.setString(ui.KIND,['cad'])
    controller.invalidate_if_changed()
    assert json.loads(gmsh.onelab.get(ui.CAD_PATH))['visible']
    assert json.loads(gmsh.onelab.get(ui.SHEET_SIGN))['visible']
    assert not json.loads(gmsh.onelab.get(ui.LENGTH))['visible']
