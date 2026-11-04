"""Cancelable file-only NAS staging; never calls Gmsh or ONELAB."""
from __future__ import annotations

import hashlib
import ctypes
import os
from pathlib import Path
import stat
import tempfile
import threading

from .errors import MeshBlocked


def _identity(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _digest(stream, cancel):
    digest = hashlib.sha256()
    while True:
        if cancel.is_set():
            raise InterruptedError('NAS 전송이 취소됐습니다')
        block = stream.read(1024 * 1024)
        if not block:
            return digest.hexdigest()
        digest.update(block)


def _locked_reader(path):
    """Windows: deny writers while permitting rename/delete; POSIX: regular reader."""
    if os.name != 'nt':
        return path.open('rb')
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 0x00000001 | 0x00000004, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    try:
        return os.fdopen(descriptor, 'rb')
    except Exception:
        os.close(descriptor)
        raise


class NasTransfer:
    """One owner of a staging directory; poll/commit from the calling thread."""
    def __init__(self, source: Path, output: Path, name: str, digest: str):
        if Path(name).name != name or not name.startswith('run_'):
            raise MeshBlocked('작업 결과의 발행 이름이 유효하지 않습니다')
        self.source, self.output, self.name, self.digest = source, output, name, digest
        self.cancelled = threading.Event()
        self.stage = None
        self.identity = None
        self.stage_identity = None
        self.owned_file_identity = None
        self.stage_done = False
        self.error = None
        self.warning = ''
        self.locked_stream = None
        self.thread = threading.Thread(target=self._run, name='brl-nas-transfer', daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.output.mkdir(parents=True, exist_ok=True)
            with self.source.open('rb') as source:
                source_before = _identity(os.fstat(source.fileno()))
                if _digest(source, self.cancelled) != self.digest:
                    raise MeshBlocked('검증 이후 NAS가 변경됐습니다')
                if _identity(os.fstat(source.fileno())) != source_before:
                    raise MeshBlocked('NAS 원본이 전송 중 변경됐습니다')
                source.seek(0)
                self.stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=self.output))
                stage_stat = self.stage.stat()
                self.stage_identity = (stage_stat.st_dev, stage_stat.st_ino)
                target = self.stage / 'mesh.nas'
                with target.open('xb') as out:
                    target_stat = os.fstat(out.fileno())
                    self.owned_file_identity = (target_stat.st_dev, target_stat.st_ino)
                    while True:
                        if self.cancelled.is_set():
                            raise InterruptedError('NAS 전송이 취소됐습니다')
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        out.write(block)
                if _identity(os.fstat(source.fileno())) != source_before:
                    raise MeshBlocked('NAS 원본이 전송 중 변경됐습니다')
            self.locked_stream = _locked_reader(target)
            stream = self.locked_stream
            before = _identity(os.fstat(stream.fileno()))
            if _digest(stream, self.cancelled) != self.digest:
                raise MeshBlocked('NAS 전송 검증이 일치하지 않습니다')
            after = _identity(os.fstat(stream.fileno()))
            if before != after or _identity(target.stat()) != after:
                raise MeshBlocked('NAS 전송 결과가 검증 중 변경됐습니다')
            self.identity = after
            if self.cancelled.is_set():
                raise InterruptedError('NAS 전송이 취소됐습니다')
        except Exception as exc:
            self.error = exc
            self._cleanup_owned()

    def _cleanup_owned(self):
        warnings = []
        if self.locked_stream is not None:
            try:
                self.locked_stream.close()
                self.locked_stream = None
            except Exception as exc:
                warnings.append(f'NAS 파일 핸들 정리 실패: {exc}')
        if self.stage is not None and not self.stage_done:
            try:
                stage_info = self.stage.lstat()
                if (self.stage_identity is None or not stat.S_ISDIR(stage_info.st_mode)
                        or (stage_info.st_dev, stage_info.st_ino) != self.stage_identity):
                    raise RuntimeError('임시 폴더 소유권이 달라 보존했습니다')
                target = self.stage / 'mesh.nas'
                try:
                    target_info = target.lstat()
                except FileNotFoundError:
                    target_info = None
                if target_info is not None:
                    if (self.owned_file_identity is None or not stat.S_ISREG(target_info.st_mode)
                            or (target_info.st_dev, target_info.st_ino) != self.owned_file_identity):
                        raise RuntimeError('임시 NAS 소유권이 달라 보존했습니다')
                    target.unlink()
                if any(self.stage.iterdir()):
                    raise RuntimeError('임시 폴더에 다른 파일이 있어 보존했습니다')
                self.stage.rmdir()
                self.stage_done = True
            except Exception as exc:
                warnings.append(f'임시 폴더 정리 실패 ({self.stage}): {exc}')
        if warnings:
            self.warning = '; '.join(warnings)

    def cleanup(self):
        if not self.ready():
            raise RuntimeError('진행 중인 NAS 전송을 정리할 수 없습니다')
        self._cleanup_owned()

    def cancel(self):
        self.cancelled.set()

    def ready(self):
        return not self.thread.is_alive()

    def commit(self):
        if not self.ready():
            raise RuntimeError('NAS 전송이 아직 진행 중입니다')
        if self.error:
            raise self.error
        if self.cancelled.is_set():
            raise InterruptedError('NAS 전송이 취소됐습니다')
        target = self.stage / 'mesh.nas'
        stage_stat = self.stage.stat()
        if (self.stage.is_symlink() or (stage_stat.st_dev, stage_stat.st_ino) != self.stage_identity
                or target.is_symlink() or set(self.stage.iterdir()) != {target}):
            raise MeshBlocked('NAS 전송 임시 폴더가 변경됐습니다')
        if _identity(target.stat()) != self.identity:
            raise MeshBlocked('검증 이후 NAS 전송 결과가 변경됐습니다')
        if os.name != 'nt':
            with target.open('rb') as stream:
                if _digest(stream, self.cancelled) != self.digest:
                    raise MeshBlocked('검증 이후 NAS 전송 결과가 변경됐습니다')
        final = self.output / self.name
        if final.exists():
            raise MeshBlocked('발행 대상이 이미 존재합니다')
        # Windows cannot rename the parent directory while its child is open.
        # Keep writers excluded until immediately before rename.
        self.locked_stream.close()
        self.locked_stream = None
        self.stage.rename(final)
        self.stage_done = True
        return str(final / 'mesh.nas')
