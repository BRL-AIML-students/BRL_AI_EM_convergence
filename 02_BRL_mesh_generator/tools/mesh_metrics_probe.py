"""Measure prepared generator meshes without publishing a NAS or changing the UI."""
import argparse
import json
from pathlib import Path
from time import perf_counter

import gmsh

from brl_mesh.config import Configuration
from brl_mesh.development_metrics import measure_development_metrics
from brl_mesh.engine import mesh_model, prepare_generated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('--normal-grid', type=int, default=4, choices=range(2, 17, 2))
    args = parser.parse_args()
    config = Configuration.load(args.config)
    started = perf_counter()
    with mesh_model(config) as scene:
        scene, prepared = prepare_generated(scene, config)
        prepared_at = perf_counter()
        metrics = measure_development_metrics(prepared.mesh, scene, normal_grid=args.normal_grid)
        print(json.dumps({
            'gmsh': gmsh.__version__,
            'output_unit': config.output_unit,
            'global_size': scene.sizing.global_size,
            'triangles': len(prepared.mesh.element_ids),
            'prepared_seconds': prepared_at - started,
            'measurement_seconds': perf_counter() - prepared_at,
            'existing_deviation_ratio': prepared.inspection.deviation_ratio_max if scene.curvature else None,
            **metrics,
        }, allow_nan=False, indent=2))


if __name__ == '__main__':
    main()
