"""Local developer benchmark; never writes into the archived implementation."""
import argparse
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import time

from brl_mesh.config import Configuration
from brl_mesh.engine import run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--plain', action='store_true', help='Disable cProfile for wall-clock comparisons')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--case', action='append', dest='cases')
    args = parser.parse_args()
    root = Path('.cache/performance') / args.label
    root.mkdir(parents=True, exist_ok=True)
    results = []
    for name, geometry, size, curvature in [
        ('plate', {'kind': 'plate', 'length': 100, 'width': 60}, 1., None),
        ('sphere', {'kind': 'sphere', 'radius': 10}, .5, None),
        ('sphere_coarse', {'kind': 'sphere', 'radius': 1}, .4, None),
        ('sphere_auto_curvature', {'kind': 'sphere', 'radius': 1}, .4,
         {'relative_tolerance': .001}),
    ]:
        if args.cases and name not in args.cases:
            continue
        mesh = {'target_size': size}
        if curvature:
            mesh['curvature'] = curvature
        config = Configuration.from_dict({
            'schema_version': 1, 'geometry': geometry,
            'length_unit': 'mm', 'output_unit': 'mm', 'mesh': mesh,
            'output_dir': str((root / name).resolve())})
        for trial in range(args.repeat):
            profiler = cProfile.Profile()
            start = time.perf_counter()
            result = run(config) if args.plain else profiler.runcall(run, config)
            elapsed = time.perf_counter() - start
            if not args.plain:
                with (root / (name + f'-{trial}.txt')).open('w', encoding='utf-8') as stream:
                    pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(35)
            payload = result.nas_path.read_bytes()
            record = dict(case=name, trial=trial, seconds=elapsed, nodes=result.node_count,
                          triangles=result.triangle_count, bytes=len(payload),
                          sha256=hashlib.sha256(payload).hexdigest())
            results.append(record)
            print(json.dumps(record), flush=True)
    (root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
