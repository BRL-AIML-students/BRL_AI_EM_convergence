from pathlib import Path
import subprocess
import sys
import math
import gmsh


def polygon(points):
    ids=[gmsh.model.occ.addPoint(*p) for p in points]
    edges=[gmsh.model.occ.addLine(a,b) for a,b in zip(ids,ids[1:]+ids[:1])]
    return gmsh.model.occ.addPlaneSurface([gmsh.model.occ.addCurveLoop(edges)])


def write_case(path, kind):
    subprocess.run([sys.executable,'-B','-X','utf8','-c',
        'from tests.sizing_support import _write_case; from pathlib import Path; import sys; '
        '_write_case(Path(sys.argv[1]),sys.argv[2])',str(path),kind],
        capture_output=True,check=True,timeout=20)
    return path


def _write_case(path, kind):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal',0)
        if kind=='widths':
            gmsh.model.occ.addRectangle(0,0,0,10,.6)
            gmsh.model.occ.addRectangle(30,0,0,10,1.2)
        elif kind=='rotated':
            face=gmsh.model.occ.addRectangle(0,0,0,10,.6)
            gmsh.model.occ.rotate([(2,face)],0,0,0,1,1,1,.7)
            gmsh.model.occ.translate([(2,face)],100,200,300)
        elif kind=='gaps':
            for x,z in [(0,0),(0,.6),(20,0),(20,1.2)]:
                gmsh.model.occ.addRectangle(x,0,z,4,4)
        elif kind in ('adjacent','contact'):
            a=gmsh.model.occ.addRectangle(0,0,0,2,2)
            b=gmsh.model.occ.addRectangle(2,0,0,2,2)
            if kind=='adjacent':gmsh.model.occ.fragment([(2,a)],[(2,b)])
        elif kind=='false_bbox':
            polygon([(0,0,0),(4,0,0),(0,4,0)])
            polygon([(4,4,0),(2.8,4,0),(4,2.8,0)])
        elif kind=='concave':
            polygon([(0,0,0),(3,0,0),(3,1,0),(1,1,0),(1,3,0),(0,3,0)])
        elif kind=='hole':
            outer=gmsh.model.occ.addRectangle(0,0,0,4,4)
            inner=gmsh.model.occ.addDisk(2,2,0,.5,.5)
            gmsh.model.occ.cut([(2,outer)],[(2,inner)])
        elif kind=='cylinder':
            gmsh.model.occ.addCylinder(0,0,0,0,0,.2,1)
        elif kind=='disk':
            gmsh.model.occ.addDisk(0,0,0,2,2)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:gmsh.finalize()
