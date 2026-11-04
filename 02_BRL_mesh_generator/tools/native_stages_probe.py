"""Headless wall-clock stages of the native worker handoff (developer tool).

No FLTK window, rendering or event pump is measured. These synchronous stage
costs cannot establish actual UI latency or a maximum UI freeze duration.
Run serially from the local checkout, e.g.:

  python -B -X utf8 -m tools.native_stages_probe --label o5 --case plate --case sphere --repeat 3
  python -B -X utf8 -m tools.native_stages_probe --label smoke --case smoke_plate --action publish-current

NAS/MSH/worker files are created in owned local temporary directories, checked
through the product contracts, then removed. Only the JSON measurement record
is retained in a newly allocated .cache/performance/native-stages directory.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time

import gmsh
import numpy as np

from brl_mesh import native_job, nas, provenance
from brl_mesh.config import Configuration
from brl_mesh.engine import generate, prepare_generated
from brl_mesh.inspection import inspect_mesh
from brl_mesh.model import assert_current


_ROOT = Path(__file__).resolve().parent.parent
_CASES = {
    'plate': ({'kind': 'plate', 'length': 100, 'width': 60}, {'target_size': 1.}),
    'sphere': ({'kind': 'sphere', 'radius': 1},
               {'target_size': .4, 'curvature': {'relative_tolerance': .001}}),
    'smoke_plate': ({'kind': 'plate', 'length': 1, 'width': 1}, {'target_size': .25}),
}
_ACTIONS = {'generate-publish': 1, 'publish-current': 4}
_LIMITS = [
    'Headless synchronous stages only; no FLTK window, rendering or event pump.',
    'Stage durations do not establish actual UI latency or maximum freeze duration.',
    'Worker wait begins after NativeJob construction; worker startup can overlap construction.',
    'init_save_mesh and init_request_json are nested in init_total; do not add them to that total.',
    'publish-current setup generates/checks a parent mesh before measured job construction.',
    'Action 1 adopt imports fresh CAD/MSH; action 4 adopt checks the unchanged parent mesh without import.',
    'Post-adopt full mesh checks and post-commit independent NAS checks are extra probe checks, timed separately.',
    'Comparisons are invalid if product source hash changes during or between trials.',
]


@contextmanager
def _measure_init_parts(seconds):
    """Observe existing constructor calls; worker process uses its own module."""
    old_save, old_write = native_job.save_mesh, native_job.write_json

    def save(*args, **kwargs):
        start = time.perf_counter()
        try:
            return old_save(*args, **kwargs)
        finally:
            seconds['init_save_mesh'] = (seconds['init_save_mesh'] or 0.) + time.perf_counter()-start

    def write(path, *args, **kwargs):
        start = time.perf_counter()
        try:
            return old_write(path, *args, **kwargs)
        finally:
            if Path(path).name == 'request.json':
                seconds['init_request_json'] = (seconds['init_request_json'] or 0.) + time.perf_counter()-start

    native_job.save_mesh, native_job.write_json = save, write
    try:
        yield
    finally:
        native_job.save_mesh, native_job.write_json = old_save, old_write


def _trial(case, action, trial, output, expected_hash, timeout):
    geometry, sizing = _CASES[case]
    record = {'case': case, 'action': action, 'trial': trial, 'status': 'running',
              'comparison_valid': False, 'seconds': {key: None for key in (
                  'parent_setup', 'init_total', 'init_save_mesh', 'init_request_json',
                  'worker_wait', 'adopt', 'post_adopt_checks', 'commit_publication',
                  'post_commit_independent_checks', 'job_close', 'gmsh_finalize')}}
    seconds = record['seconds']
    record['source_hash_before'] = provenance.source_hash()
    if record['source_hash_before'] != expected_hash:
        raise RuntimeError('Product source changed before trial; comparison is invalid')
    config = Configuration.from_dict({'schema_version': 1, 'geometry': geometry,
        'length_unit': 'mm', 'output_unit': 'mm', 'mesh': sizing, 'output_dir': str(output)})
    record['effective_config'] = provenance.effective_config(config)
    job, scene = None, None
    gmsh.initialize(readConfigFiles=False)
    gmsh.option.setNumber('General.Terminal', 0)
    try:
        if _ACTIONS[action] == 4:
            start = time.perf_counter()
            scene = generate(config)
            scene, _prepared = prepare_generated(scene, config)
            seconds['parent_setup'] = time.perf_counter()-start
        with _measure_init_parts(seconds):
            start = time.perf_counter()
            job = native_job.NativeJob(config, _ACTIONS[action], scene)
            seconds['init_total'] = time.perf_counter()-start
        start = time.perf_counter()
        deadline = start+timeout
        while True:
            result = job.result()
            if result is not None:
                break
            if time.perf_counter() >= deadline:
                raise TimeoutError(f'Worker wait exceeded explicit timeout {timeout:g}s')
            time.sleep(.01)
        seconds['worker_wait'] = time.perf_counter()-start
        start = time.perf_counter()
        scene, mesh = job.adopt(result, scene)
        seconds['adopt'] = time.perf_counter()-start
        start = time.perf_counter()
        assert_current(mesh)
        scene.require_current(config)
        metadata = provenance.require_current(scene.generation_provenance, config, scene.cad.digest)
        inspect_mesh(mesh, scene.contract).require_pass()
        seconds['post_adopt_checks'] = time.perf_counter()-start
        start = time.perf_counter()
        transfer = job.start_publication(result)
        if transfer is None:
            raise RuntimeError('Publication action returned no transfer')
        while not transfer.ready():
            time.sleep(.01)
        try:
            published = transfer.commit()
        finally:
            transfer.cleanup()
        seconds['commit_publication'] = time.perf_counter()-start
        if not published:
            raise RuntimeError('Publication action returned no NAS')
        start = time.perf_counter()
        path = Path(published)
        # Re-read independently after transfer; retain current-mesh checks too.
        assert_current(mesh)
        nas.validate(path, mesh, provenance=metadata)
        digest = nas.file_digest(path)
        if digest != result['nas_digest']:
            raise RuntimeError('Post-commit NAS digest differs from worker reference')
        seconds['post_commit_independent_checks'] = time.perf_counter()-start
        record.update(nodes=len(mesh.node_ids), triangles=len(mesh.element_ids),
                      nas_bytes=path.stat().st_size, nas_sha256=digest,
                      requested_algorithm=metadata['configured_options']['Mesh.Algorithm'],
                      worker_warnings=result.get('warnings', []))
        record['source_hash_after'] = provenance.source_hash()
        if record['source_hash_after'] != expected_hash or metadata['source']['sha256'] != expected_hash:
            raise RuntimeError('Product source changed during trial; comparison is invalid')
        record.update(status='ok', comparison_valid=True)
    except Exception as exc:
        record.update(status='error', error=f'{type(exc).__name__}: {exc}')
    finally:
        if job is not None:
            start = time.perf_counter()
            try:
                job.close()
            except Exception as exc:
                record.update(status='error', cleanup_error=f'{type(exc).__name__}: {exc}')
            seconds['job_close'] = time.perf_counter()-start
        start = time.perf_counter()
        gmsh.finalize()
        seconds['gmsh_finalize'] = time.perf_counter()-start
        record['source_hash_after'] = provenance.source_hash()
        if record['source_hash_after'] != expected_hash or record['status'] != 'ok':
            record['comparison_valid'] = False
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True, help='Local output label (letters/digits/_/-)')
    parser.add_argument('--case', choices=list(_CASES), action='append', dest='cases')
    parser.add_argument('--action', choices=list(_ACTIONS), action='append', dest='actions')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--worker-timeout', type=float, default=600., help='Explicit per-trial wait timeout seconds')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label):
        parser.error('label must contain only letters, digits, _ or -')
    if args.repeat < 1 or not np.isfinite(args.worker_timeout) or args.worker_timeout <= 0:
        parser.error('repeat and worker-timeout must be positive')
    if gmsh.isInitialized():
        parser.error('Run in a fresh process; an existing Gmsh session is not owned by this probe')
    cache = _ROOT / '.cache' / 'performance' / 'native-stages'
    cache.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=args.label+'-', dir=cache))
    expected_hash = provenance.source_hash()
    report = {'schema': 1, 'kind': 'headless_native_stage_wall_clock', 'limitations': _LIMITS,
              'source_sha256': expected_hash, 'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'python': sys.version, 'gmsh': gmsh.__version__, 'numpy': np.__version__,
              'comparison_valid': True, 'records': []}
    destination = root / 'results.json'

    def checkpoint():
        report['source_sha256_final'] = provenance.source_hash()
        report['comparison_valid'] = ('error' not in report and report['source_sha256_final'] == expected_hash
                                      and all(row['comparison_valid'] for row in report['records']))
        pending = root / 'results.pending'
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        pending.replace(destination)

    try:
        for case in args.cases or ['plate', 'sphere']:
            for action in args.actions or ['generate-publish']:
                for trial in range(args.repeat):
                    with tempfile.TemporaryDirectory(prefix='trial-', dir=root) as local:
                        record = _trial(case, action, trial, Path(local) / 'publication', expected_hash,
                                        args.worker_timeout)
                    record['owned_trial_files_removed'] = not Path(local).exists()
                    report['records'].append(record)
                    checkpoint()
                    print(json.dumps(record, ensure_ascii=False), flush=True)
                    if not record['comparison_valid']:
                        raise RuntimeError('Trial failed or source changed; remaining comparisons stopped')
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        report['comparison_valid'] = False
        checkpoint()
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        checkpoint()
        print(json.dumps({'results': str(destination), 'comparison_valid': report['comparison_valid']}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
