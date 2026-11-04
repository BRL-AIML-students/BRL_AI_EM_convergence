"""Development-only, isolated NAS round-trip and hash memory measurements.

Runs two source trees serially with the same Python dependencies and synthetic
mesh. Windows peak is process PeakWorkingSetSize (not Python tracemalloc).
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def process_memory():
    if os.name == 'nt':
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                        ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                        ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                        ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'metric': 'process_peak_working_set_bytes', 'peak_bytes': counters.PeakWorkingSetSize,
                'current_bytes': counters.WorkingSetSize}
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'metric': 'process_peak_rss_bytes', 'peak_bytes': int(peak * (1 if sys.platform == 'darwin' else 1024)),
            'current_bytes': None}


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_digest(root):
    digest = hashlib.sha256()
    for path in sorted((root / 'brl_mesh').glob('*.py')):
        for value in (path.name.encode('utf-8'), path.read_bytes()):
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
    return digest.hexdigest()


def mesh_for(count):
    import numpy as np
    from brl_mesh.model import SurfaceMesh
    ids = np.arange(1, count + 3, dtype=np.int64)
    positions = np.arange(1, count + 2, dtype=np.float64)
    xyz = np.zeros((count + 2, 3), dtype=np.float64)
    xyz[1:, 0] = positions
    xyz[1:, 1] = positions * positions
    connectivity = np.column_stack((np.ones(count, dtype=np.int64), ids[1:-1], ids[2:]))
    elements = np.arange(1, count + 1, dtype=np.int64)
    return SurfaceMesh(ids, xyz, elements, connectivity, np.ones(count, dtype=np.int64),
                       np.ones(count, dtype=np.int64))


def worker(args):
    sys.path.insert(0, str(args.source.resolve()))
    if args.phase == 'hash':
        before = process_memory()
        start = time.perf_counter()
        if args.hash_method == 'read_bytes':
            digest = hashlib.sha256(args.file.read_bytes()).hexdigest()
        else:
            digest = file_hash(args.file)
        elapsed = time.perf_counter() - start
        result = {'seconds': elapsed, 'sha256': digest, 'before': before, 'after': process_memory()}
    else:
        from brl_mesh import nas
        mesh = mesh_for(args.count)
        if args.phase == 'prepare':
            start = time.perf_counter()
            nas.write(args.file, mesh, 'mm')
            result = {'seconds': time.perf_counter() - start, 'sha256': file_hash(args.file),
                      'size_bytes': args.file.stat().st_size}
        else:
            before = process_memory()
            start = time.perf_counter()
            nas.validate(args.file, mesh)
            result = {'seconds': time.perf_counter() - start, 'before': before, 'after': process_memory()}
    print('NAS_PROBE ' + json.dumps(result, sort_keys=True), flush=True)


def run_worker(source, count, phase, path, hash_method):
    command = [sys.executable, '-B', '-X', 'utf8', str(Path(__file__).resolve()), '--worker',
               '--source', str(source), '--count', str(count), '--phase', phase,
               '--file', str(path), '--hash-method', hash_method]
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
    lines = [line[len('NAS_PROBE '):] for line in completed.stdout.splitlines() if line.startswith('NAS_PROBE ')]
    if completed.returncode != 0 or len(lines) != 1:
        raise RuntimeError(f'{phase} failed for {source}: exit={completed.returncode}\n{completed.stderr}\n{completed.stdout}')
    return json.loads(lines[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--current', type=Path)
    parser.add_argument('--counts', type=int, nargs='+', default=[10000, 100000, 1000000])
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--source', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--count', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--phase', choices=['prepare', 'validate', 'hash'], help=argparse.SUPPRESS)
    parser.add_argument('--file', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--hash-method', choices=['read_bytes', 'file_digest'], default='file_digest')
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    if args.baseline is None or args.current is None or args.repeats < 1 or any(count < 1 for count in args.counts):
        parser.error('--baseline, --current and positive counts are required')
    sources = [('baseline', args.baseline.resolve(), 'read_bytes'),
               ('current', args.current.resolve(), 'file_digest')]
    for _, source, _ in sources:
        if not (source / 'brl_mesh' / 'nas.py').is_file():
            parser.error(f'brl_mesh/nas.py not found: {source}')
    source_digests = {label: source_digest(source) for label, source, _ in sources}
    result = {'python': sys.version, 'numpy': importlib.metadata.version('numpy'),
              'pynastran': importlib.metadata.version('pyNastran'),
              'source_sha256_direct_brl_mesh_py': source_digests, 'runs': [], 'limitations':
              'Serial subprocesses; synthetic fan mesh; process lifetime peak includes imports and mesh setup, '
              'not a phase-exclusive peak or Python tracemalloc. Validate includes independent pyNastran. '
              'Direct NAS writer has no provenance comments. Hash operations emulate native worker methods; '
              'native worker transport is not run. Hash baseline uses read_bytes; current uses file_digest. '
              'External load and filesystem cache uncontrolled.'}
    cache = Path(__file__).resolve().parent.parent / '.cache' / 'nas-memory-probe'
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=cache) as temporary:
        for count in args.counts:
            for repeat in range(args.repeats):
                for label, source, method in sources:
                    path = Path(temporary) / f'{label}-{count}-{repeat}.nas'
                    prepare = run_worker(source, count, 'prepare', path, method)
                    validation = run_worker(source, count, 'validate', path, method)
                    hashed = run_worker(source, count, 'hash', path, method)
                    if prepare['sha256'] != hashed['sha256']:
                        raise RuntimeError('NAS hash mismatch between preparation and hash worker')
                    result['runs'].append({'label': label, 'source': str(source), 'triangles': count,
                                           'repeat': repeat + 1, 'hash_method': method, 'prepare': prepare,
                                           'validate': validation, 'hash': hashed})
                if result['runs'][-1]['prepare']['sha256'] != result['runs'][-2]['prepare']['sha256']:
                    raise RuntimeError(f'baseline/current NAS differ at {count} triangles')
    if any(source_digest(source) != source_digests[label] for label, source, _ in sources):
        raise RuntimeError('Source files changed during measurement; results are not comparable')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
