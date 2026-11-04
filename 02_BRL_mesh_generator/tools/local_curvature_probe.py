"""Developer-only isolated baseline/local comparison; not a product diagnostic.

Pure repetitions and separately instrumented runs are never pooled. Baseline
CurvaturePlan is loaded from a saved source module, without replacing files.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

import gmsh
import numpy as np

from brl_mesh import curvature, engine, provenance
from brl_mesh.config import Configuration


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_plan(path):
    spec = importlib.util.spec_from_file_location('brl_mesh._local_probe_baseline', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.CurvaturePlan


def instrument(base, evidence):
    state = {'inside_callback': False}
    generate = gmsh.model.mesh.generate
    def timed_generate(*args, **kwargs):
        started = time.perf_counter()
        evidence['generate_calls'] += 1
        try:
            return generate(*args, **kwargs)
        finally:
            evidence['generate_seconds'] += time.perf_counter()-started
    gmsh.model.mesh.generate = timed_generate
    # Count CAD calls only inside the size callback; measurement is timed alone.
    for name in ('getParametrization', 'getParametrizationBounds', 'getPrincipalCurvatures', 'getCurvature'):
        original = getattr(gmsh.model, name)
        def counted(*args, _name=name, _original=original, **kwargs):
            if state['inside_callback']:
                counts = evidence['callback_cad_calls']
                counts[_name] = counts.get(_name, 0)+1
            return _original(*args, **kwargs)
        setattr(gmsh.model, name, counted)
    class Instrumented(base):
        def target(self, *args):
            state['inside_callback'] = True
            started = time.perf_counter()
            evidence['callback_calls'] += 1
            try:
                return super().target(*args)
            finally:
                evidence['callback_seconds'] += time.perf_counter()-started
                state['inside_callback'] = False
        def measure(self, *args, **kwargs):
            started = time.perf_counter()
            evidence['measure_calls'] += 1
            try:
                return super().measure(*args, **kwargs)
            finally:
                evidence['measure_seconds'] += time.perf_counter()-started
    return Instrumented


def child(args):
    root = Path(args.root).resolve()
    source = Path(args.baseline).resolve() if args.implementation == 'baseline' else Path(curvature.__file__)
    base = load_plan(source) if args.implementation == 'baseline' else curvature.CurvaturePlan
    evidence = {'callback_calls': 0, 'callback_seconds': 0., 'callback_cad_calls': {},
                'measure_calls': 0, 'measure_seconds': 0.,
                'generate_calls': 0, 'generate_seconds': 0.}
    engine.CurvaturePlan = instrument(base, evidence) if args.instrumented else base
    cad = root/'inputs'/(args.case+'.brep')
    config = Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'cad', 'path': str(cad), 'sheet_normal': 1},
        'mesh': {'target_size': .8 if args.case == 'local-bend' else .7,
                 'curvature': {'absolute_tolerance': .01 if args.case == 'local-bend' else .02,
                               'feedback': 'local'}},
        'output_dir': str(Path(args.output).resolve().with_suffix('')/'nas')})
    record = {'case': args.case, 'implementation': args.implementation, 'instrumented': args.instrumented,
              'effective_feedback': 'entity' if args.implementation == 'baseline' else 'local',
              'curvature_implementation_path': str(source), 'curvature_implementation_sha256': digest(source),
              'current_engine_sha256': digest(engine.__file__), 'cad_sha256': digest(cad),
              'config': config.to_dict(), 'gmsh_version': gmsh.__version__,
              'product_source_hash_before': provenance.source_hash(),
              'provenance_note': 'NAS uses current engine metadata; actual injected curvature source hash is recorded separately.'}
    started = time.perf_counter()
    try:
        with engine.mesh_model(config) as scene:
            scene, prepared = engine.prepare_generated(scene, config)
            prepared.inspection.require_pass()
            mesh = prepared.mesh
            xyz = mesh.triangles()
            record.update(history=scene.curvature.history, nodes=len(mesh.node_ids), triangles=len(mesh.element_ids),
                          outside_triangles=int(np.count_nonzero(xyz.mean(axis=1)[:, 0] < 4))
                          if args.case == 'local-bend' else None,
                          sampled_deviation_ratio=prepared.inspection.deviation_ratio_max,
                          minimum_angle=prepared.inspection.shape.minimum_angle_deg,
                          maximum_aspect=prepared.inspection.shape.aspect_ratio_max)
            published = engine.publish(mesh, config, scene)
            record.update(full_contract_pass=True, independent_nas_pass=True,
                          nas_path=str(published.nas_path), nas_sha256=digest(published.nas_path))
        record['success'] = True
    except Exception as exc:
        record.update(success=False, error=repr(exc), traceback=traceback.format_exc())
    record['total_seconds'] = time.perf_counter()-started
    record['product_source_hash_after'] = provenance.source_hash()
    record['product_source_unchanged'] = (record['product_source_hash_before'] ==
                                          record['product_source_hash_after'])
    if not record['product_source_unchanged']:
        record.update(success=False, error='Product source changed during the isolated run')
    if args.instrumented:
        record['instrumentation'] = evidence
    Path(args.output).write_text(json.dumps(record, indent=2), encoding='utf-8')
    return 0 if record['success'] else 1


def run(args):
    root = Path(args.root).resolve()
    (root/'inputs').mkdir(parents=True, exist_ok=True)
    from tests.test_local_curvature import write_local_bend
    from tests.curvature_support import write_curved
    cases = args.cases or ([args.case] if args.case else ['local-bend', 'sphere'])
    for name in cases:
        if name == 'local-bend':
            write_local_bend(root/'inputs'/(name+'.brep'))
        else:
            write_curved(root/'inputs'/(name+'.brep'), 'sphere')
    records = []
    failed = False
    for name in cases:
        # AB/BA/AB pure elapsed. Instrumented evidence is one separate pair.
        schedule = [(trial, method, False) for trial in range(args.repeat)
                    for method in (('baseline', 'current') if trial % 2 == 0 else ('current', 'baseline'))]
        schedule += [(0, method, True) for method in ('baseline', 'current')]
        for trial, method, measured in schedule:
            output = root/f'{name}-{method}-{"metrics" if measured else trial}.json'
            command = [sys.executable, '-B', '-X', 'utf8', '-m', 'tools.local_curvature_probe',
                       '--child', '--root', str(root), '--baseline', str(Path(args.baseline).resolve()),
                       '--implementation', method, '--case', name, '--output', str(output)]
            if measured:
                command.append('--instrumented')
            completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
            if not output.exists():
                raise RuntimeError(f'child failed before result: {completed.stderr}')
            record = json.loads(output.read_text(encoding='utf-8'))
            record['trial'] = trial
            records.append(record)
            print(json.dumps({key: record.get(key) for key in
                              ('case', 'implementation', 'instrumented', 'success', 'total_seconds', 'triangles', 'outside_triangles')}), flush=True)
            if completed.returncode:
                failed = True
        (root/'results.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default='.cache/performance/local-curvature-20261103')
    parser.add_argument('--baseline', default='.cache/audit-20261102/curvature-before-local.py')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--case', choices=['local-bend', 'sphere'])
    parser.add_argument('--cases', nargs='+', choices=['local-bend', 'sphere'])
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--implementation', choices=['baseline', 'current'])
    parser.add_argument('--instrumented', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    return child(args) if args.child else run(args)


if __name__ == '__main__':
    raise SystemExit(main())
