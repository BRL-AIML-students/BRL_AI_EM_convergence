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


def test_worker_publish_after_output_directory_change(controller, config, tmp_path):
    controller.perform(2)
    wait(controller)
    scene = controller.scene
    assert scene is not None
    target = tmp_path / 'new-output'
    gmsh.onelab.setString(ui.OUTPUT, [target.as_posix()])
    controller.invalidate_if_changed()
    assert controller.scene is scene
    controller.perform(4)
    wait(controller)
    assert gmsh.onelab.getString(ui.STATUS) == ['NAS published']
    assert Path(gmsh.onelab.getString(ui.NAS_PATH)[0]).parent.parent == target


def test_worker_output_change_during_job_blocks_publication(controller, config, tmp_path):
    controller.perform(1)
    gmsh.onelab.setString(ui.OUTPUT, [(tmp_path / 'other').as_posix()])
    wait(controller)
    assert '설정이 변경' in gmsh.onelab.getString(ui.STATUS)[0]
    assert not config.output_dir.exists()
    assert not (tmp_path / 'other').exists()


def test_failed_generation_retains_previous_current_scene(controller):
    controller.perform(2)
    wait(controller)
    scene, mesh = controller.scene, controller.last_mesh
    controller.perform(2)
    controller.job.process.terminate()
    controller.job.process.wait(timeout=5)
    wait(controller)
    assert controller.scene is scene and controller.last_mesh is mesh
    assert gmsh.onelab.getString(ui.STATUS)[0].startswith('Blocked:')


def test_cancel_action_retains_previous_scene_and_window(controller):
    controller.perform(2)
    wait(controller)
    scene = controller.scene
    controller.perform(2)
    process = controller.job.process
    controller.perform(6)
    assert process.poll() is not None and controller.job is None
    assert controller.scene is scene and not controller.close_requested
    assert 'previous mesh retained' in gmsh.onelab.getString(ui.STATUS)[0]


def test_cancel_invalidates_scene_if_controls_changed(controller):
    controller.perform(2)
    wait(controller)
    controller.perform(2)
    gmsh.onelab.setNumber(ui.TARGET, [.3])
    controller.perform(6)
    assert controller.scene is None and controller.last_mesh is None
    assert 'regenerate required' in gmsh.onelab.getString(ui.STATUS)[0]


def test_adopt_failure_after_model_clear_never_restores_old_scene(controller, monkeypatch):
    controller.perform(2)
    wait(controller)
    assert controller.scene is not None
    controller.perform(2)
    def broken_adopt(*args):
        gmsh.clear()
        raise RuntimeError('import failed')
    monkeypatch.setattr(controller.job, 'adopt', broken_adopt)
    wait(controller)
    assert controller.scene is None and controller.last_mesh is None
    assert 'import failed' in gmsh.onelab.getString(ui.STATUS)[0]


def test_cleanup_failure_does_not_hide_successful_publication(controller, monkeypatch):
    controller.perform(1)
    job = controller.job
    close = job.close
    def cleanup_fails():
        close()
        raise PermissionError('locked')
    monkeypatch.setattr(job, 'close', cleanup_fails)
    wait(controller)
    assert controller.scene is not None
    assert gmsh.onelab.getString(ui.STATUS)[0].startswith('NAS published; temporary cleanup failed:')
    assert Path(gmsh.onelab.getString(ui.NAS_PATH)[0]).is_file()


def test_failed_termination_keeps_worker_owned_and_blocks_new_job(controller, monkeypatch):
    controller.perform(1)
    job = controller.job
    close = job.close
    def termination_fails():
        raise PermissionError('termination denied')
    monkeypatch.setattr(job, 'close', termination_fails)
    controller.perform(6)
    assert controller.job is job and controller.cancel_pending
    assert job.process.poll() is None
    controller.poll()
    controller.perform(1)
    assert controller.job is job
    monkeypatch.setattr(job, 'close', close)
    controller.perform(6)
    assert job.process.poll() is not None and controller.job is None
    assert not controller.cancel_pending


def test_poll_failure_and_termination_failure_retain_job(controller, monkeypatch):
    controller.perform(1)
    job = controller.job
    close = job.close
    monkeypatch.setattr(job, 'result', lambda: (_ for _ in ()).throw(RuntimeError('result failed')))
    monkeypatch.setattr(job, 'close', lambda: (_ for _ in ()).throw(PermissionError('termination denied')))
    controller.poll()
    assert controller.job is job and controller.cancel_pending
    assert 'result failed' in gmsh.onelab.getString(ui.STATUS)[0]
    assert 'termination denied' in gmsh.onelab.getString(ui.STATUS)[0]
    controller.perform(1)
    assert controller.job is job
    monkeypatch.setattr(job, 'close', close)
    controller.perform(6)
    assert controller.job is None


def test_close_retries_worker_termination_without_closing_window(controller, monkeypatch):
    controller.perform(1)
    job = controller.job
    close = job.close
    monkeypatch.setattr(job, 'close', lambda: (_ for _ in ()).throw(PermissionError('termination denied')))
    controller.perform(5)
    assert controller.job is job and controller.cancel_pending and not controller.close_requested
    monkeypatch.setattr(job, 'close', close)
    controller.perform(5)
    assert controller.job is None and controller.close_requested


def test_worker_publication_warnings_reach_ui(controller, monkeypatch):
    controller.perform(1)
    job = controller.job
    result = job.result
    def with_warning():
        value = result()
        if value is not None:
            value['warnings'] = ['local cleanup failed']
        return value
    monkeypatch.setattr(job, 'result', with_warning)
    wait(controller)
    assert 'NAS published; local cleanup failed' == gmsh.onelab.getString(ui.STATUS)[0]
    assert Path(gmsh.onelab.getString(ui.NAS_PATH)[0]).is_file()
