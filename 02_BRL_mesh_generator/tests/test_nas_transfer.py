import hashlib
import os
from pathlib import Path
import threading

import pytest

from brl_mesh import nas_transfer
from brl_mesh.errors import MeshBlocked


def transfer(tmp_path, data=b'valid NAS'):
    source = tmp_path / 'source.nas'
    source.write_bytes(data)
    value = nas_transfer.NasTransfer(source, tmp_path / 'output', 'run_test', hashlib.sha256(data).hexdigest())
    return value


def finish(value):
    value.thread.join(timeout=5)
    assert value.ready()


def test_transfer_and_existing_result_preserved(tmp_path):
    previous = tmp_path / 'output' / 'previous' / 'mesh.nas'
    previous.parent.mkdir(parents=True)
    previous.write_bytes(b'old')
    value = transfer(tmp_path)
    finish(value)
    assert Path(value.commit()).read_bytes() == b'valid NAS'
    assert previous.read_bytes() == b'old'


def test_stage_changed_after_validation_is_blocked(tmp_path):
    value = transfer(tmp_path)
    finish(value)
    if os.name == 'nt':
        with pytest.raises(PermissionError):
            (value.stage / 'mesh.nas').write_bytes(b'corrupted')
        assert Path(value.commit()).read_bytes() == b'valid NAS'
    else:
        (value.stage / 'mesh.nas').write_bytes(b'corrupted')
        with pytest.raises(MeshBlocked, match='변경'):
            value.commit()
        value.cleanup()
        assert not value.stage.exists()


def test_cancel_waits_for_inflight_io_and_cleans_owned_stage(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = nas_transfer._digest
    def blocked(stream, cancel):
        entered.set()
        assert release.wait(5)
        return original(stream, cancel)
    monkeypatch.setattr(nas_transfer, '_digest', blocked)
    value = transfer(tmp_path)
    assert entered.wait(5)
    value.cancel()
    assert not value.ready()
    release.set()
    finish(value)
    assert isinstance(value.error, InterruptedError)
    assert not list((tmp_path / 'output').glob('.pending-*'))
    with pytest.raises(InterruptedError):
        value.commit()


def test_wrong_source_digest_never_publishes(tmp_path):
    source = tmp_path / 'source.nas'
    source.write_bytes(b'changed')
    value = nas_transfer.NasTransfer(source, tmp_path / 'output', 'run_test', '0' * 64)
    finish(value)
    with pytest.raises(MeshBlocked, match='변경'):
        value.commit()
    assert not (tmp_path / 'output' / 'run_test').exists()


def test_controller_poll_and_cancel_do_not_wait_for_blocked_transfer(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from brl_mesh import native_ui as ui, model
    entered, release = threading.Event(), threading.Event()
    digest = nas_transfer._digest
    def blocked(stream, cancelled):
        entered.set()
        assert release.wait(5)
        return digest(stream, cancelled)
    monkeypatch.setattr(nas_transfer, '_digest', blocked)
    config = object()
    mesh = object()
    scene = SimpleNamespace(require_current=lambda config: None, generation_provenance='reference',
                            cad=SimpleNamespace(digest=None))
    monkeypatch.setattr(ui, 'read_controls', lambda *args: config)
    monkeypatch.setattr(ui.provenance, 'require_current', lambda *args: None)
    monkeypatch.setattr(model, 'assert_current', lambda *args: None)
    source = tmp_path / 'source'
    source.write_bytes(b'good')
    closed = []
    job = SimpleNamespace(config=config, action=4, process=SimpleNamespace(poll=lambda: 0),
                          result=lambda: {'publication': 'run_test', 'warnings': []},
                          adopt=lambda result, old: (scene, mesh), close=lambda: closed.append(True))
    job.start_publication = lambda result: nas_transfer.NasTransfer(
        source, tmp_path / 'output', 'run_test', hashlib.sha256(b'good').hexdigest())
    controller = ui.AsyncController.__new__(ui.AsyncController)
    controller.job, controller.scene, controller.last_mesh = job, scene, mesh
    controller.transfer = controller.transfer_result = None
    controller.base = controller.base_dir = None
    controller.close_requested = controller.cancel_pending = controller.close_after_cancel = False
    controller.cancel_cause = None
    statuses = []
    controller.status = lambda message, path='': statuses.append((message, path))
    controller.poll()
    assert entered.wait(5) and controller.transfer is not None
    controller.poll()
    assert 'transferring' in statuses[-1][0]
    controller.cancel()
    assert controller.job is job and controller.cancel_pending and not closed
    release.set()
    controller.transfer.thread.join(timeout=5)
    controller.poll()
    assert controller.job is None and closed == [True]
    assert not (tmp_path / 'output' / 'run_test').exists()


def test_existing_final_and_unrelated_pending_are_preserved(tmp_path):
    value = transfer(tmp_path)
    finish(value)
    final = tmp_path / 'output' / 'run_test'
    final.mkdir()
    (final / 'mesh.nas').write_bytes(b'old')
    unrelated = tmp_path / 'output' / '.pending-other'
    unrelated.mkdir()
    with pytest.raises(MeshBlocked, match='이미 존재'):
        value.commit()
    value.cleanup()
    assert (final / 'mesh.nas').read_bytes() == b'old'
    assert unrelated.is_dir()


def test_cleanup_error_is_reported(tmp_path, monkeypatch):
    value = transfer(tmp_path)
    finish(value)
    unlink = Path.unlink
    def blocked(path, *args, **kwargs):
        if path == value.stage / 'mesh.nas':
            raise PermissionError('locked')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', blocked)
    value.cleanup()
    assert 'locked' in value.warning
    unlink(value.stage / 'mesh.nas')
    value.stage.rmdir()


def test_controller_rechecks_settings_and_blocks_staged_result(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from brl_mesh import native_ui as ui
    config, changed = object(), object()
    current = [config]
    monkeypatch.setattr(ui, 'read_controls', lambda *args: current[0])
    source = tmp_path / 'source'
    source.write_bytes(b'valid')
    mesh = object()
    scene = SimpleNamespace(require_current=lambda value: None)
    closed = []
    job = SimpleNamespace(config=config, action=4, process=SimpleNamespace(poll=lambda: 0),
                          result=lambda: {'publication': 'run_test'},
                          adopt=lambda result, old: (scene, mesh), close=lambda: closed.append(True))
    job.start_publication = lambda result: nas_transfer.NasTransfer(
        source, tmp_path / 'output', 'run_test', hashlib.sha256(b'valid').hexdigest())
    controller = ui.AsyncController.__new__(ui.AsyncController)
    controller.job, controller.scene, controller.last_mesh = job, scene, mesh
    controller.transfer = controller.transfer_result = None
    controller.base = controller.base_dir = None
    controller.close_requested = controller.cancel_pending = controller.close_after_cancel = False
    controller.cancel_cause = None
    statuses = []
    controller.status = lambda message, path='': statuses.append((message, path))
    controller.poll()
    controller.transfer.thread.join(timeout=5)
    assert controller.transfer.ready()
    current[0] = changed
    controller.poll()
    assert controller.job is None and closed == [True]
    assert statuses[-1][0].startswith('Blocked:')
    assert not (tmp_path / 'output' / 'run_test').exists()
    assert not list((tmp_path / 'output').glob('.pending-*'))


def test_live_transfer_cannot_be_cleaned_or_job_closed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from brl_mesh.native_job import NativeJob
    entered, release = threading.Event(), threading.Event()
    original = nas_transfer._digest
    def blocked(stream, cancelled):
        entered.set()
        assert release.wait(5)
        return original(stream, cancelled)
    monkeypatch.setattr(nas_transfer, '_digest', blocked)
    value = transfer(tmp_path)
    assert entered.wait(5)
    job = NativeJob.__new__(NativeJob)
    job.transfer, job.process = value, None
    cleaned = []
    job.storage = SimpleNamespace(cleanup=lambda: cleaned.append(True))
    with pytest.raises(RuntimeError, match='진행 중'):
        value.cleanup()
    with pytest.raises(RuntimeError, match='종료되지'):
        job.close()
    assert not cleaned
    value.cancel()
    release.set()
    finish(value)
    job.close()
    assert cleaned == [True]


def test_status_error_during_live_transfer_retains_ownership(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from brl_mesh import native_ui as ui, model
    entered, release = threading.Event(), threading.Event()
    original = nas_transfer._digest
    def blocked(stream, cancelled):
        entered.set()
        assert release.wait(5)
        return original(stream, cancelled)
    monkeypatch.setattr(nas_transfer, '_digest', blocked)
    config, mesh = object(), object()
    scene = SimpleNamespace(require_current=lambda config: None)
    monkeypatch.setattr(ui, 'read_controls', lambda *args: config)
    monkeypatch.setattr(model, 'assert_current', lambda *args: None)
    source = tmp_path / 'source'
    source.write_bytes(b'valid')
    closed = []
    job = SimpleNamespace(config=config, action=4, process=SimpleNamespace(poll=lambda: 0),
                          result=lambda: {'publication': 'run_test'}, adopt=lambda *_: (scene, mesh),
                          close=lambda: closed.append(True))
    job.start_publication = lambda _: nas_transfer.NasTransfer(
        source, tmp_path / 'output', 'run_test', hashlib.sha256(b'valid').hexdigest())
    controller = ui.AsyncController.__new__(ui.AsyncController)
    controller.job, controller.scene, controller.last_mesh = job, scene, mesh
    controller.transfer = controller.transfer_result = None
    controller.base = controller.base_dir = None
    controller.close_requested = controller.cancel_pending = controller.close_after_cancel = False
    controller.cancel_cause = None
    statuses = []
    def status(message, path=''):
        if message == 'Working: transferring validated NAS' and not statuses:
            statuses.append(('failed', ''))
            raise RuntimeError('status failed')
        statuses.append((message, path))
    controller.status = status
    controller.poll()
    assert entered.wait(5)
    assert controller.job is job and controller.cancel_pending and not closed
    release.set()
    controller.transfer.thread.join(timeout=5)
    controller.poll()
    assert controller.job is None and closed == [True]
    assert 'status failed' in statuses[-1][0]
    assert not (tmp_path / 'output' / 'run_test').exists()


def test_cancel_after_validation_releases_file_handle(tmp_path):
    value = transfer(tmp_path)
    finish(value)
    value.cancel()
    value.cleanup()
    assert value.locked_stream is None and not value.stage.exists()


def test_rename_failure_releases_file_handle_and_allows_cleanup(tmp_path, monkeypatch):
    value = transfer(tmp_path)
    finish(value)
    original = Path.rename
    def fail(path, dest):
        if path == value.stage:
            raise PermissionError('rename locked')
        return original(path, dest)
    monkeypatch.setattr(Path, 'rename', fail)
    with pytest.raises(PermissionError, match='rename locked'):
        value.commit()
    assert value.locked_stream is None
    value.cleanup()
    assert not value.stage.exists()


def test_post_commit_status_error_keeps_published_path(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from brl_mesh import native_ui as ui, model
    config, mesh = object(), object()
    scene = SimpleNamespace(require_current=lambda config: None, generation_provenance='reference',
                            cad=SimpleNamespace(digest=None))
    monkeypatch.setattr(ui, 'read_controls', lambda *args: config)
    monkeypatch.setattr(ui.provenance, 'require_current', lambda *args: None)
    monkeypatch.setattr(model, 'assert_current', lambda *args: None)
    source = tmp_path / 'source'
    source.write_bytes(b'valid')
    closed = []
    job = SimpleNamespace(config=config, action=4, process=SimpleNamespace(poll=lambda: 0),
                          result=lambda: {'publication': 'run_test'}, adopt=lambda *_: (scene, mesh),
                          close=lambda: closed.append(True))
    job.start_publication = lambda _: nas_transfer.NasTransfer(
        source, tmp_path / 'output', 'run_test', hashlib.sha256(b'valid').hexdigest())
    controller = ui.AsyncController.__new__(ui.AsyncController)
    controller.job, controller.scene, controller.last_mesh = job, scene, mesh
    controller.transfer = controller.transfer_result = None
    controller.base = controller.base_dir = None
    controller.close_requested = controller.cancel_pending = controller.close_after_cancel = False
    controller.cancel_cause = None
    statuses = []
    def status(message, path=''):
        if message == 'NAS published':
            raise RuntimeError('UI status failure')
        statuses.append((message, path))
    controller.status = status
    controller.poll()
    controller.transfer.thread.join(timeout=5)
    controller.poll()
    assert controller.job is None and closed == [True]
    assert statuses[-1][0].startswith('NAS published; completion warning:')
    assert Path(statuses[-1][1]).read_bytes() == b'valid'


def test_extra_file_in_stage_blocks_publication(tmp_path):
    value = transfer(tmp_path)
    finish(value)
    (value.stage / 'unexpected').write_bytes(b'extra')
    with pytest.raises(MeshBlocked, match='임시 폴더가 변경'):
        value.commit()
    value.cleanup()
    assert (value.stage / 'unexpected').read_bytes() == b'extra'
    assert '다른 파일' in value.warning
    assert not (tmp_path / 'output' / 'run_test').exists()


@pytest.mark.skipif(os.name != 'nt', reason='Windows handle ownership')
def test_fdopen_failure_closes_windows_handle(tmp_path, monkeypatch):
    path = tmp_path / 'target'
    path.write_bytes(b'x')
    monkeypatch.setattr(nas_transfer.os, 'fdopen', lambda *args, **kwargs:
                        (_ for _ in ()).throw(OSError('fdopen failed')))
    with pytest.raises(OSError, match='fdopen failed'):
        nas_transfer._locked_reader(path)
    path.write_bytes(b'y')  # A leaked deny-write handle would block this.


def test_job_close_cleans_ready_transfer_and_reports_cleanup_warning(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from brl_mesh.native_job import NativeJob
    value = transfer(tmp_path)
    finish(value)
    unlink = Path.unlink
    def blocked(path, *args, **kwargs):
        if path == value.stage / 'mesh.nas':
            raise PermissionError('locked pending')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', blocked)
    job = NativeJob.__new__(NativeJob)
    job.transfer, job.process = value, None
    cleaned = []
    job.storage = SimpleNamespace(cleanup=lambda: cleaned.append(True))
    with pytest.raises(RuntimeError, match='locked pending'):
        job.close()
    assert cleaned == [True] and value.locked_stream is None
    unlink(value.stage / 'mesh.nas')
    value.stage.rmdir()


def test_finish_job_keeps_live_transfer_when_worker_is_done(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from brl_mesh import native_ui as ui
    entered, release = threading.Event(), threading.Event()
    original = nas_transfer._digest
    def blocked(stream, cancelled):
        entered.set()
        assert release.wait(5)
        return original(stream, cancelled)
    monkeypatch.setattr(nas_transfer, '_digest', blocked)
    value = transfer(tmp_path)
    assert entered.wait(5)
    closed = []
    job = SimpleNamespace(transfer=value, process=SimpleNamespace(poll=lambda: 0), close=lambda: closed.append(True))
    controller = ui.AsyncController.__new__(ui.AsyncController)
    controller.job, controller.transfer, controller.cancel_pending = job, None, False
    statuses = []
    controller.status = lambda message, path='': statuses.append(message)
    assert not controller._finish_job(job)
    assert controller.job is job and controller.transfer is value and controller.cancel_pending and not closed
    release.set()
    finish(value)


def test_replaced_stage_directory_is_preserved(tmp_path):
    value = transfer(tmp_path)
    finish(value)
    value.locked_stream.close()
    value.locked_stream = None
    original = value.stage.with_name('moved-original')
    value.stage.rename(original)
    value.stage.mkdir()
    external = value.stage / 'mesh.nas'
    external.write_bytes(b'external')
    with pytest.raises(MeshBlocked, match='임시 폴더가 변경'):
        value.commit()
    value.cleanup()
    assert external.read_bytes() == b'external'
    assert '소유권' in value.warning
    assert (original / 'mesh.nas').read_bytes() == b'valid NAS'


def test_replaced_target_file_is_preserved(tmp_path):
    value = transfer(tmp_path)
    finish(value)
    value.locked_stream.close()
    value.locked_stream = None
    target = value.stage / 'mesh.nas'
    target.rename(value.stage / 'original')
    target.write_bytes(b'external')
    value.cleanup()
    assert target.read_bytes() == b'external'
    assert (value.stage / 'original').read_bytes() == b'valid NAS'
    assert '소유권' in value.warning
