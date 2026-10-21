"""Actual subprocess integration, including transport and publication guards."""
from dataclasses import replace
from pathlib import Path
import time

import gmsh
import pytest

from brl_mesh import native_ui as ui
from brl_mesh.config import Configuration
from brl_mesh.engine import run
from tests.support import distort_interior


def wait(controller):
    deadline = time.monotonic()+90
    cycles = 0
    while controller.job is not None:
        controller.poll()
        cycles += 1
        assert time.monotonic() < deadline, 'native worker timeout'
        time.sleep(.01)
    return cycles


@pytest.fixture
def controller(config):
    gmsh.initialize(readConfigFiles=False)
    gmsh.option.setNumber('General.Terminal', 0)
    control = ui.AsyncController(config, config.output_dir.parent)
    try:
        yield control
    finally:
        control.cancel()
        gmsh.finalize()


@pytest.mark.parametrize('example', ['plate', 'sphere', 'ogive', 'cube', 'cylinder_native', 'dihedral',
                                     'circle_223', 'thin_plate', 'gaps'])
def test_worker_matches_cli_and_current_actions(tmp_path, example):
    source = Path('examples') / (example+'.json')
    config = replace(Configuration.load(source), output_dir=tmp_path/'output')
    expected = run(config).nas_path.read_bytes()
    gmsh.initialize(readConfigFiles=False)
    gmsh.option.setNumber('General.Terminal', 0)
    control = ui.AsyncController(config, tmp_path)
    try:
        control.perform(2)
        assert control.job is not None
        wait(control)
        assert 'Mesh ready' in gmsh.onelab.getString(ui.STATUS)[0]
        control.perform(3)
        wait(control)
        assert 'completed' in gmsh.onelab.getString(ui.STATUS)[0]
        control.perform(4)
        wait(control)
        assert gmsh.onelab.getString(ui.STATUS) == ['NAS published']
        assert Path(gmsh.onelab.getString(ui.NAS_PATH)[0]).read_bytes() == expected
        assert len(gmsh.view.getTags()) == 0
    finally:
        control.cancel()
        gmsh.finalize()


def test_changed_controls_discard_completed_publication(controller, config):
    controller.perform(1)
    gmsh.onelab.setNumber(ui.TARGET, [.3])
    wait(controller)
    assert '설정이 변경' in gmsh.onelab.getString(ui.STATUS)[0]
    assert not config.output_dir.exists()


def test_manual_edit_during_publication_cannot_publish_stale_mesh(controller, config):
    controller.perform(2)
    wait(controller)
    assert controller.scene is not None
    controller.perform(4)
    distort_interior(controller.scene.membership)
    wait(controller)
    assert gmsh.onelab.getString(ui.STATUS)[0].startswith('Blocked:')
    assert not config.output_dir.exists()


def test_current_defective_mesh_is_blocked_in_worker(controller, config):
    controller.perform(2)
    wait(controller)
    distort_interior(controller.scene.membership)
    controller.perform(4)
    wait(controller)
    assert gmsh.onelab.getString(ui.STATUS)[0].startswith('Blocked:')
    assert not config.output_dir.exists()


def test_cancel_terminates_child_and_removes_only_job_temporary_files(controller, config):
    controller.perform(1)
    process, root = controller.job.process, controller.job.root
    controller.cancel()
    assert process.poll() is not None and not root.exists()
    assert not config.output_dir.exists()


def test_worker_crash_is_consumed_without_publication(controller, config):
    controller.perform(1)
    controller.job.process.terminate()
    controller.job.process.wait(timeout=5)
    wait(controller)
    assert gmsh.onelab.getString(ui.STATUS)[0].startswith('Blocked:')
    assert not config.output_dir.exists()


def test_repeated_actions_do_not_start_duplicate_jobs(controller, config):
    controller.perform(1)
    process = controller.job.process
    for _ in range(3):
        gmsh.onelab.setString(ui.ACTION, [ui.ACTIONS[1]])
        controller.dispatch()
        assert controller.job.process is process
        assert gmsh.onelab.getString(ui.ACTION) == ['Idle']
    wait(controller)
    assert gmsh.onelab.getString(ui.STATUS) == ['NAS published']
    assert len(list(config.output_dir.rglob('mesh.nas'))) == 1


def test_curved_shape_selection_preserves_explicit_curvature_choice(controller, config):
    for kind in ('sphere', 'cylinder', 'ogive', 'plate'):
        gmsh.onelab.setString(ui.KIND, [kind])
        controller.invalidate_if_changed(deep=False)
        assert list(gmsh.onelab.getNumber(ui.CURVATURE_ENABLED)) == [0]
    gmsh.onelab.setNumber(ui.CURVATURE_ENABLED, [1])
    gmsh.onelab.setString(ui.KIND, ['sphere'])
    controller.invalidate_if_changed(deep=False)
    assert list(gmsh.onelab.getNumber(ui.CURVATURE_ENABLED)) == [1]
