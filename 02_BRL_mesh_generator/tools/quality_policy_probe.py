"""Development-only reproducible comparison; does not define an ICN cutoff."""
import json
import math

import gmsh
import numpy as np

from brl_mesh.checks import measure_shape
from brl_mesh.errors import MeshBlocked
from brl_mesh.model import SurfaceMesh
from brl_mesh.quality import read_icn


def run_probe() -> dict:
    cases = [(x, height) for x in (-.5, 0, .1, .3, .5, .8, 1, 1.3)
             for height in (.02, .1, .2, .3, .4, .5, .8, math.sqrt(3) / 2, 1, 1.5, 2, 3, 4)]
    xyz = np.array([p for i, (x, height) in enumerate(cases)
                    for p in ((10 * i, 0, 0), (10 * i + 1, 0, 0), (10 * i + x, height, 0))], dtype=float)
    nodes = np.arange(1, len(xyz) + 1)
    ids = np.arange(100, 100 + len(cases))
    conn = nodes.reshape(-1, 3)
    mesh = SurfaceMesh(nodes, xyz, ids, conn, np.ones(len(ids), dtype=int), np.ones(len(ids), dtype=int))
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.model.add('policy_probe')
        gmsh.model.addDiscreteEntity(2, 1)
        gmsh.model.mesh.addNodes(2, 1, nodes, xyz.ravel())
        gmsh.model.mesh.addElementsByType(1, 2, ids, conn.ravel())
        shape = measure_shape(mesh)
        icn = read_icn(mesh)
        api = gmsh.model.mesh.getElementQualities(ids, 'minSICN')
        rows = [dict(x=x, height=h, ar=float(ar), angle=float(angle), icn=icn[int(eid)],
                     accepted=bool(ar <= 3 and angle >= 20))
                for (x, h), ar, angle, eid in zip(cases, shape.aspect_ratios, shape.minimum_angles, ids)]
        accepted = min((r for r in rows if r['accepted']), key=lambda r: r['icn'])
        rejected = max((r for r in rows if not r['accepted']), key=lambda r: r['icn'])
        damaged = SurfaceMesh(np.array([1, 2, 3]), np.array([[0., 0, 0], [1., 0, 0], [.5, 0, 0]]),
                              np.array([1]), np.array([[1, 2, 3]]), np.array([1]), np.array([1]))
        degenerate_blocked = False
        try:
            damaged.validate()
        except MeshBlocked:
            degenerate_blocked = True
        return dict(gmsh=gmsh.__version__, cases=len(cases), accepted=sum(r['accepted'] for r in rows),
                    accepted_low_icn=accepted, rejected_high_icn=rejected,
                    single_icn_cutoff_preserves_policy=rejected['icn'] < accepted['icn'],
                    plugin_api_max_difference=float(np.max(np.abs(api - [icn[int(e)] for e in ids]))),
                    degenerate_preflight_blocked=degenerate_blocked)
    finally:
        gmsh.finalize()


if __name__ == '__main__':
    print(json.dumps(run_probe(), ensure_ascii=False, indent=2))
