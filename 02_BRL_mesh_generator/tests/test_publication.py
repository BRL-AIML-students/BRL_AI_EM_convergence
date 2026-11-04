from pathlib import Path
from types import SimpleNamespace

import pytest

from brl_mesh import engine, nas
from brl_mesh.errors import MeshBlocked


def test_publish_validates_locally_before_destination(square, config, monkeypatch):
    monkeypatch.setattr(engine, 'assert_current', lambda mesh: None)
    monkeypatch.setattr(engine, 'snapshot', lambda membership: square)
    monkeypatch.setattr(engine, 'inspect_mesh', lambda *args: SimpleNamespace(require_pass=lambda: None))
    monkeypatch.setattr(engine.provenance, 'require_current', lambda *args: None)
    scene = SimpleNamespace(require_current=lambda config: None, membership={}, contract=None,
                            generation_provenance={'schema': 1}, cad=SimpleNamespace(digest=None))
    validate = nas.validate
    def check_local(path, expected, **kwargs):
        assert not config.output_dir.exists()
        assert '.cache' in path.parts
        validate(path, expected, **kwargs)
    monkeypatch.setattr(nas, 'validate', check_local)
    result = engine.publish(square, config, scene)
    assert result.nas_path.is_file()
    assert not list(config.output_dir.glob('.pending-*'))


def test_publish_transfer_mismatch_preserves_existing(square, config, monkeypatch):
    monkeypatch.setattr(engine, 'assert_current', lambda mesh: None)
    monkeypatch.setattr(engine, 'snapshot', lambda membership: square)
    monkeypatch.setattr(engine, 'inspect_mesh', lambda *args: SimpleNamespace(require_pass=lambda: None))
    monkeypatch.setattr(engine.provenance, 'require_current', lambda *args: None)
    scene = SimpleNamespace(require_current=lambda config: None, membership={}, contract=None,
                            generation_provenance={'schema': 1}, cad=SimpleNamespace(digest=None))
    config.output_dir.mkdir(parents=True, exist_ok=True)
    existing = config.output_dir / 'run_existing' / 'mesh.nas'
    existing.parent.mkdir()
    existing.write_bytes(b'previous')
    other = config.output_dir / '.pending-other'
    other.mkdir()
    def corrupt(source, target):
        Path(target).write_bytes(b'corrupt')
    monkeypatch.setattr(engine.shutil, 'copyfile', corrupt)
    with pytest.raises(MeshBlocked, match='전송 검증'):
        engine.publish(square, config, scene)
    assert existing.read_bytes() == b'previous'
    assert list(config.output_dir.glob('.pending-*')) == [other]


def test_published_result_survives_local_cleanup_failure(square, config, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(engine, 'assert_current', lambda mesh: None)
    monkeypatch.setattr(engine, 'snapshot', lambda membership: square)
    monkeypatch.setattr(engine, 'inspect_mesh', lambda *args: SimpleNamespace(require_pass=lambda: None))
    monkeypatch.setattr(engine.provenance, 'require_current', lambda *args: None)
    scene = SimpleNamespace(require_current=lambda config: None, membership={}, contract=None,
                            generation_provenance={'schema': 1}, cad=SimpleNamespace(digest=None))
    remove = engine.shutil.rmtree
    leftovers = []
    def fail_local(path, *args, **kwargs):
        if Path(path).name.startswith('publish-'):
            leftovers.append(Path(path))
            raise PermissionError('locked local')
        return remove(path, *args, **kwargs)
    monkeypatch.setattr(engine.shutil, 'rmtree', fail_local)
    try:
        result = engine.publish(square, config, scene)
        assert result.nas_path.is_file()
        assert len(result.warnings) == 1 and 'locked local' in result.warnings[0]
    finally:
        for path in leftovers:
            remove(path)


def test_primary_failure_and_cleanup_failure_are_both_preserved(square, config, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(engine, 'assert_current', lambda mesh: None)
    monkeypatch.setattr(engine, 'snapshot', lambda membership: square)
    monkeypatch.setattr(engine, 'inspect_mesh', lambda *args: SimpleNamespace(require_pass=lambda: None))
    monkeypatch.setattr(engine.provenance, 'require_current', lambda *args: None)
    scene = SimpleNamespace(require_current=lambda config: None, membership={}, contract=None,
                            generation_provenance={'schema': 1}, cad=SimpleNamespace(digest=None))
    monkeypatch.setattr(nas, 'validate', lambda *args, **kwargs: (_ for _ in ()).throw(MeshBlocked('reader failed')))
    remove = engine.shutil.rmtree
    leftovers = []
    def fail_local(path, *args, **kwargs):
        leftovers.append(Path(path))
        raise PermissionError('locked local')
    monkeypatch.setattr(engine.shutil, 'rmtree', fail_local)
    try:
        with pytest.raises(MeshBlocked, match='reader failed') as error:
            engine.publish(square, config, scene)
        assert 'locked local' in error.value.__notes__[0]
        assert not config.output_dir.exists()
    finally:
        for path in leftovers:
            remove(path)
