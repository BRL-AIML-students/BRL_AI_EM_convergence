"""Development-only real FLTK stage/pump probe; never edits product code.

Runs the product event loop and injects Generate + publish / Close through the
ONELAB API. This measures calls and event-pump call intervals, not mouse input,
user interaction latency, first visible pixels, GPU completion, or a universal
maximum UI freeze. Run serially from this local checkout after source freezes.

  python -B -X utf8 -m tools.native_fltk_probe --label fltk --case small_plate
  python -B -X utf8 -m tools.native_fltk_probe --label fltk --case large_plate

Default: small_plate once. Run each case/trial in a fresh process; repeated FLTK
initialization in one process has produced an access violation. All NAS/worker files are owned temporary artifacts;
only newly allocated local JSON measurement files are retained.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
from functools import wraps
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

import gmsh
import numpy as np

from brl_mesh import model, nas, native_job, native_ui, provenance
from brl_mesh.config import Configuration
from brl_mesh.engine import Scene
from brl_mesh.nas_transfer import NasTransfer


_ROOT = Path(__file__).resolve().parent.parent
_CASES = {'small_plate': (1., 1., .25), 'large_plate': (100., 60., .5)}
_LIMITATIONS = [
    'Real FLTK loop with API-injected Actions; no mouse/keyboard interaction measurement.',
    'Pump entry intervals include requested FLTK wait plus Python body work and instrumentation.',
    'Loop-body gaps are from wait return to next wait entry; no continuous responsiveness guarantee.',
    'First mesh render means the first explicit gmsh.graphics.draw call, not first pixels or GPU completion.',
    'Initial Gmsh/FLTK/controller setup and the first explicit mesh draw are separate events.',
    'Final-current observer checks add overhead: affected pump intervals are marked and separately excluded.',
    'Independent NAS re-reading happens after the product loop and is excluded from pump statistics.',
    'Nested stage event durations must not be summed as independent elapsed time.',
    'Source changes during/between trials invalidate comparisons; no speedup claim from one run.',
    'Window size, display driver, desktop/session state and OS scheduling are uncontrolled.',
]


class Recorder:
    def __init__(self, config, expected_hash, timeout):
        self.config, self.expected_hash, self.timeout = config, expected_hash, timeout
        self.origin = time.perf_counter()
        self.main_thread = threading.get_ident()
        self.events, self.pumps, self.observers = [], [], []
        self.controller = None
        self.previous_enter = self.previous_return = None
        self.cycles = self.draws = 0
        self.injected = False
        self.published_path = self.expected_digest = None
        self.final_mesh = self.final_metadata = None
        self.validation_error = None

    def event(self, name, start, end, error=None):
        self.events.append({'name': name, 'start_seconds': start-self.origin,
                            'seconds': end-start, 'thread': ('main' if threading.get_ident() == self.main_thread else 'helper'),
                            'error': error})

    def observe_publication(self, transfer, path):
        if threading.get_ident() != self.main_thread:
            raise RuntimeError('Publication commit unexpectedly ran off the main thread')
        start = time.perf_counter()
        self.published_path, self.expected_digest = str(path), transfer.digest
        try:
            scene, mesh = self.controller.scene, self.controller.last_mesh
            scene.require_current(self.config)
            model.assert_current(mesh)
            self.final_metadata = provenance.require_current(scene.generation_provenance, self.config, scene.cad.digest)
            if self.final_metadata['source']['sha256'] != self.expected_hash:
                raise RuntimeError('Source changed before final current check')
            self.final_mesh = copy.deepcopy(mesh)
        except Exception as exc:
            # An observer failure invalidates this trial without changing the
            # product's already committed publication or cleanup state machine.
            self.validation_error = f'{type(exc).__name__}: {exc}'
        finally:
            end = time.perf_counter()
            self.observers.append((start, end))
            self.event('probe_final_current_observer', start, end)

    def patch(self, stack, target, attribute, label, after=None):
        old = getattr(target, attribute)
        @wraps(old)
        def wrapped(*args, **kwargs):
            start = time.perf_counter()
            error = None
            try:
                result = old(*args, **kwargs)
            except BaseException as exc:
                error = f'{type(exc).__name__}: {exc}'
                raise
            finally:
                name = label
                if label == 'graphics_draw':
                    self.draws += 1
                    name = 'graphics_draw_first_mesh' if self.draws == 1 else 'graphics_draw_later'
                self.event(name, start, time.perf_counter(), error)
            if after is not None:
                after(args, result)
            return result
        setattr(target, attribute, wrapped)
        stack.callback(setattr, target, attribute, old)

    def phase(self):
        if self.published_path:
            return 'after_publication'
        if self.controller is None or self.controller.job is None:
            return 'initial_idle' if not self.injected else 'idle_after_action'
        return 'transfer' if self.controller.transfer is not None else 'worker_or_adopt'

    def install(self, stack):
        for target, attr, label in [
            (gmsh, 'initialize', 'gmsh_initialize'),
            (gmsh.fltk, 'initialize', 'fltk_initialize'),
            (gmsh.fltk, 'update', 'onelab_update'),
            (gmsh.graphics, 'draw', 'graphics_draw'),
            (native_job.NativeJob, '__init__', 'job_init'),
            (native_job, 'save_mesh', 'parent_save_mesh'),
            (native_job, 'write_json', 'parent_request_json'),
            (native_job.NativeJob, 'adopt', 'adopt'),
            (native_job.NativeJob, 'start_publication', 'transfer_start'),
            (Scene, 'require_current', 'scene_current'),
            (provenance, 'require_current', 'provenance_current'),
            (model, 'assert_current', 'mesh_current'),
            (NasTransfer, '_run', 'transfer_helper_run'),
        ]:
            self.patch(stack, target, attr, label)
        self.patch(stack, native_ui.AsyncController, '__init__', 'controller_install',
                   lambda args, _result: setattr(self, 'controller', args[0]))
        self.patch(stack, NasTransfer, 'commit', 'transfer_commit',
                   lambda args, result: self.observe_publication(args[0], result))
        old_wait = gmsh.fltk.wait

        def wait(delay):
            enter = time.perf_counter()
            phase = self.phase()
            if self.previous_enter is not None:
                self.pumps.append({'phase_before_wait': phase,
                    'interval_start_seconds': self.previous_enter-self.origin,
                    'entry_gap_seconds': enter-self.previous_enter,
                    'loop_body_gap_seconds': enter-self.previous_return,
                    'probe_observer_overlap': any(start < enter and end > self.previous_enter
                                                  for start, end in self.observers)})
            self.previous_enter = enter
            try:
                old_wait(delay)
            finally:
                self.previous_return = time.perf_counter()
            self.cycles += 1
            if not self.injected and self.cycles == 2:
                gmsh.onelab.setString(native_ui.ACTION, [native_ui.ACTIONS[1]])
                self.injected = True
            elif self.published_path and self.controller.job is None:
                gmsh.onelab.setString(native_ui.ACTION, [native_ui.ACTIONS[5]])
            status = list(gmsh.onelab.getString(native_ui.STATUS))
            if status and status[0].startswith('Blocked:'):
                raise RuntimeError(status[0])
            if time.perf_counter()-self.origin > self.timeout:
                raise TimeoutError(f'FLTK probe exceeded explicit {self.timeout:g}s timeout: {status}')
        gmsh.fltk.wait = wait
        stack.callback(setattr, gmsh.fltk, 'wait', old_wait)

    def summary(self):
        def stats(rows):
            result = {'samples': len(rows)}
            for key in ('entry_gap_seconds', 'loop_body_gap_seconds'):
                values = [row[key] for row in rows]
                result[key] = ({'max': max(values), 'median': float(np.median(values)),
                                'p95': float(np.percentile(values, 95))} if values else None)
            return result
        return {'all_intervals': stats(self.pumps),
                'excluding_probe_observer_intervals': stats([row for row in self.pumps if not row['probe_observer_overlap']]),
                'per_phase': {phase: stats([row for row in self.pumps if row['phase_before_wait'] == phase])
                              for phase in sorted({row['phase_before_wait'] for row in self.pumps})}}


def _trial(case, trial, output, expected_hash, timeout):
    length, width, size = _CASES[case]
    config = Configuration.from_dict({'schema_version': 1, 'geometry': {'kind': 'plate', 'length': length, 'width': width},
        'length_unit': 'mm', 'output_unit': 'mm',
        'mesh': {'target_size': size, 'wave': {'frequency_hz': 1e9}}, 'output_dir': str(output)})
    recorder = Recorder(config, expected_hash, timeout)
    record = {'case': case, 'trial': trial, 'status': 'running', 'comparison_valid': False,
              'effective_config_before_launch': provenance.effective_config(config),
              'source_hash_before': provenance.source_hash()}
    try:
        if record['source_hash_before'] != expected_hash:
            raise RuntimeError('Source changed before trial')
        with ExitStack() as stack:
            recorder.install(stack)
            native_ui.launch(config, _ROOT)
        if recorder.validation_error is not None:
            raise RuntimeError(recorder.validation_error)
        if gmsh.isInitialized() or recorder.published_path is None:
            raise RuntimeError('FLTK loop did not finalize with a captured publication')
        path = Path(recorder.published_path)
        start = time.perf_counter()
        nas.validate(path, recorder.final_mesh, provenance=recorder.final_metadata)
        digest = nas.file_digest(path)
        if digest != recorder.expected_digest:
            raise RuntimeError('Transferred NAS hash differs from validated worker result')
        recorder.event('post_loop_independent_nas_check', start, time.perf_counter())
        record.update(status='ok', nodes=len(recorder.final_mesh.node_ids), triangles=len(recorder.final_mesh.element_ids),
                      nas_bytes=path.stat().st_size, nas_sha256=digest,
                      effective_config=recorder.final_metadata['effective_config'],
                      configured_options=recorder.final_metadata['configured_options'],
                      comparison_valid=True)
    except Exception as exc:
        record.update(status='error', error=f'{type(exc).__name__}: {exc}')
    finally:
        record.update(source_hash_after=provenance.source_hash(), events=recorder.events,
                      pump_intervals=recorder.pumps, pump_summary=recorder.summary(),
                      fltk_wait_calls=recorder.cycles, explicit_mesh_draw_calls=recorder.draws,
                      session_finalized=not gmsh.isInitialized())
        if record['source_hash_after'] != expected_hash or record['status'] != 'ok':
            record['comparison_valid'] = False
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--case', choices=list(_CASES), action='append', dest='cases')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=600.)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.label) or args.repeat < 1 or not np.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('Use a safe label and positive repeat/timeout')
    if args.repeat != 1 or (args.cases is not None and len(args.cases) != 1):
        parser.error('Run exactly one case and one repeat per fresh process')
    if gmsh.isInitialized():
        parser.error('A fresh owned Gmsh process is required')
    cache = _ROOT / '.cache' / 'performance' / 'native-fltk'
    cache.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=args.label+'-', dir=cache))
    expected_hash = provenance.source_hash()
    report = {'schema': 1, 'kind': 'actual_fltk_api_injected_pump_stage_probe', 'limitations': _LIMITATIONS,
              'source_sha256': expected_hash, 'tool_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'python': sys.version, 'gmsh': gmsh.__version__, 'numpy': np.__version__,
              'comparison_valid': False, 'records': []}
    destination = root / 'results.json'

    def checkpoint():
        report['source_sha256_final'] = provenance.source_hash()
        report['comparison_valid'] = ('error' not in report and report['source_sha256_final'] == expected_hash
                                      and bool(report['records']) and all(row['comparison_valid'] for row in report['records']))
        pending = root / 'results.pending'
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        pending.replace(destination)
    try:
        for case in args.cases or ['small_plate']:
            for trial in range(args.repeat):
                with tempfile.TemporaryDirectory(prefix='trial-', dir=root) as local:
                    record = _trial(case, trial, Path(local) / 'publication', expected_hash, args.timeout)
                record['owned_trial_files_removed'] = not Path(local).exists()
                report['records'].append(record)
                checkpoint()
                print(json.dumps({key: record.get(key) for key in ('case', 'trial', 'status', 'comparison_valid',
                    'nodes', 'triangles', 'fltk_wait_calls', 'explicit_mesh_draw_calls', 'error')}, ensure_ascii=False), flush=True)
                if not record['comparison_valid']:
                    raise RuntimeError('Trial failed or source changed; subsequent comparisons stopped')
    except Exception as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        checkpoint()
        print(json.dumps({'results': str(destination), 'comparison_valid': report['comparison_valid']}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
