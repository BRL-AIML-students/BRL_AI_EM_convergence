"""Fresh native OCC fixtures; no archived runtime or intermediate STEP import."""
import math
import subprocess
import sys
from pathlib import Path

import gmsh


def write_curved(path, kind):
    subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c',
                    'from tests.curvature_support import build; import sys; build(sys.argv[1],sys.argv[2])',
                    str(path), kind], capture_output=True, check=True, timeout=20)
    return path


def build(path, kind):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        occ = gmsh.model.occ
        if kind == 'sphere':
            occ.addSphere(0, 0, 0, 1)
        elif kind in ('disk', 'large_disk'):
            radius = 10 if kind == 'large_disk' else 1
            occ.addDisk(0, 0, 0, radius, radius)
        elif kind == 'cylinder':
            occ.addCylinder(0, 0, 0, 0, 0, 2, 1)
        elif kind == 'fillet':
            volume = occ.addBox(0, 0, 0, 2, 2, 2)
            occ.synchronize()
            occ.fillet([volume], [tag for _, tag in gmsh.model.getEntities(1)], [.15])
        elif kind == 'ogive':
            # Exact tangent-ogive meridian: D=2,L=3,R=(L^2+(D/2)^2)/D=5.
            center = occ.addPoint(-4, 0, 0)
            base, tip = occ.addPoint(1, 0, 0), occ.addPoint(0, 0, 3)
            arc = occ.addCircleArc(base, center, tip)
            half = next(tag for dim, tag in occ.revolve([(1, arc)], 0, 0, 0, 0, 0, 1, math.pi) if dim == 2)
            other = occ.copy([(2, half)])
            occ.rotate(other, 0, 0, 0, 0, 0, 1, math.pi)
            occ.fragment([(2, half)], other)
        elif kind == 'mixed_curvature':
            occ.addSphere(0, 0, 0, 1)
            occ.addSphere(10, 0, 0, 2)
        else:
            raise ValueError(kind)
        occ.synchronize()
        gmsh.write(str(Path(path)))
    finally:
        gmsh.finalize()
