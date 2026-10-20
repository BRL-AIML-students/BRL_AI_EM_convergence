"""User-scale ogive acceptance with independent analytic surface distances."""
from dataclasses import replace
from pathlib import Path
import json
import math
import time

import numpy as np

from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model, publish
from brl_mesh.improvement import improve


def analytic_deviation(mesh, diameter, length, sampling):
    radius = length*length/diameter+diameter/4
    center = diameter/2-radius
    tip_angle = math.asin(length/radius)
    weights = np.array([(1-i/(sampling-1)-j/(sampling-1), i/(sampling-1), j/(sampling-1))
                        for i in range(sampling) for j in range(sampling-i)])
    xyz, largest = mesh.triangles(), 0.
    for start in range(0, len(xyz), 128):
        points = np.einsum('ij,ejk->eik', weights, xyz[start:start+128]).reshape(-1, 3)
        r, z = np.linalg.norm(points[:, :2], axis=1), points[:, 2]
        angle = np.clip(np.arctan2(z, r-center), 0, tip_angle)
        distance = np.hypot(r-(center+radius*np.cos(angle)), z-radius*np.sin(angle))
        largest = max(largest, float(distance.max()))
    return largest


def main():
    output = Path('.cache/reassessment/acceptance').resolve()
    config = replace(Configuration.load('examples/ogive_50x100.json'), output_dir=output)
    started = time.perf_counter()
    print('Generating user-scale ogive', flush=True)
    with mesh_model(config) as scene:
        print('Generated; history='+str(scene.curvature.history), flush=True)
        result = improve(scene.membership, scene.contract, config.improvement)
        result.inspection.require_pass()
        print('Quality checks passed', flush=True)
        deviations = {str(n): analytic_deviation(result.mesh, 50, 100, n) for n in (10, 19, 37)}
        assert max(deviations.values()) <= .01*(1+1e-10)
        published = publish(result.mesh, config, scene)
        evidence = {'nodes': published.node_count, 'triangles': published.triangle_count,
                    'history': scene.curvature.history, 'independent_deviation_mm': deviations,
                    'aspect_ratio_max': result.inspection.shape.aspect_ratio_max,
                    'minimum_angle_deg': result.inspection.shape.minimum_angle_deg,
                    'nas_path': str(published.nas_path), 'seconds': time.perf_counter()-started}
        (output/'verification.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps(evidence), flush=True)


if __name__ == '__main__':
    main()
