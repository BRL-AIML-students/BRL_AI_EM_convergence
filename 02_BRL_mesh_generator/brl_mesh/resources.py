"""Cooperative, fail-closed operation budgets; never kill the native UI process.

Opaque OCC/Gmsh calls are checked before and after, not preempted. Memory is
current process private committed bytes on Windows (RSS on Linux), not a hard
allocator cap or a peak-memory measurement. A UI idle interval is not work time.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
import ctypes
import math
import os
from pathlib import Path
import time

from .errors import MeshBlocked
from .schema import object_value, integer, number


@dataclass(frozen=True)
class Resources:
    max_nodes: int = 150000
    max_triangles: int = 200000
    max_memory_mb: float = 2048
    max_seconds: float = 300
    max_projection_samples: int = 20000000

    def to_dict(self):
        return asdict(self)

    @classmethod
    def parse(cls, value):
        data = object_value(value, set(cls.__dataclass_fields__), set(), 'resources')
        result = {}
        for key, value in data.items():
            result[key] = (number(value, 'resources.'+key, positive=True) if key in
                           ('max_seconds', 'max_memory_mb') else integer(value, 'resources.'+key, 1, 100000000))
        return cls(**result)


def memory_mb():
    if os.name == 'nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        *[(key, ctypes.c_size_t) for key in ('PeakWorkingSetSize', 'WorkingSetSize',
                          'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                          'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        read = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
        read.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        read.restype = wintypes.BOOL
        if not read(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise MeshBlocked('resource_memory_incomplete: process memory를 읽지 못했습니다')
        return counters.PrivateUsage / 1024**2
    if Path('/proc/self/statm').exists():
        return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')/1024**2
    raise MeshBlocked('resource_memory_incomplete: 지원하지 않는 process memory API입니다')


class Budget:
    def __init__(self, limits):
        self.limits = limits
        self.started = time.monotonic()
        self.samples = 0

    def check(self, *, mesh=False, samples=0):
        self.samples += samples
        limits = self.limits
        if self.samples > limits.max_projection_samples:
            raise MeshBlocked(f'resource_projection_limit: {self.samples} > {limits.max_projection_samples}')
        if time.monotonic()-self.started > limits.max_seconds:
            raise MeshBlocked(f'resource_time_limit: 작업 시간 한도 {limits.max_seconds:g} s 초과')
        used = memory_mb()
        if not math.isfinite(used) or used < 0:
            raise MeshBlocked('resource_memory_incomplete: process memory 값이 유효하지 않습니다')
        if used > limits.max_memory_mb:
            raise MeshBlocked(f'resource_memory_limit: process memory {used:.1f} > {limits.max_memory_mb:g} MiB')
        if mesh:
            import gmsh
            nodes = len(gmsh.model.mesh.getNodes()[0])
            triangles = len(gmsh.model.mesh.getElementsByType(2)[0])
            if nodes > limits.max_nodes or triangles > limits.max_triangles:
                raise MeshBlocked(f'resource_mesh_limit: nodes {nodes}/{limits.max_nodes}, '
                                  f'triangles {triangles}/{limits.max_triangles}; 요구를 완화하지 않습니다')


_active = ContextVar('brl_resource_budget', default=None)


def checkpoint(*, mesh=False, samples=0):
    active = _active.get()
    if active is not None:
        active.check(mesh=mesh, samples=samples)


@contextmanager
def resource_scope(limits):
    """Nested shared-core calls consume the same action budget."""
    if _active.get() is not None:
        yield _active.get()
        return
    budget = Budget(limits)
    token = _active.set(budget)
    try:
        budget.check()
        yield budget
    finally:
        _active.reset(token)
