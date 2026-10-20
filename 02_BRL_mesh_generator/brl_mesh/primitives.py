"""Native OCC solids and a connected, oriented two-sheet dihedral."""
import math
import sys

import gmsh

from .config import Sphere, Cube, Cylinder, Dihedral
from .errors import ConfigurationError, MeshBlocked


def parameters(geometry, scale):
    names = {Sphere: ('radius',), Cube: ('side',), Cylinder: ('radius', 'height'),
             Dihedral: ('length', 'width1', 'width2')}[type(geometry)]
    sizes = {name: getattr(geometry, name)*scale for name in names}
    origin = tuple(v*scale for v in geometry.origin)
    if not all(math.isfinite(v) for v in (*sizes.values(), *origin)) or min(sizes.values()) <= 0:
        raise ConfigurationError('native geometry: 단위 변환 결과가 유효하지 않습니다')
    precision = 128*sys.float_info.epsilon*max(*sizes.values(), *(abs(v) for v in origin))
    if min(sizes.values()) <= precision:
        raise ConfigurationError('native geometry: origin에서 치수를 표현할 수 없습니다')
    x, y, z = origin
    if isinstance(geometry, Sphere):
        r = sizes['radius']
        limits = (x-r, x+r, y-r, y+r, z-r, z+r)
    elif isinstance(geometry, Cube):
        a = sizes['side']
        limits = (x, x+a, y, y+a, z, z+a)
    elif isinstance(geometry, Cylinder):
        r, h = sizes['radius'], sizes['height']
        limits = (x-r, x+r, y-r, y+r, z, z+h)
    else:
        angle = math.radians(geometry.angle_deg)
        dx, dy = sizes['width2']*math.cos(angle), sizes['width2']*math.sin(angle)
        if dy <= precision:
            raise ConfigurationError('dihedral: 각도와 폭을 좌표 정밀도에서 구분할 수 없습니다')
        limits = (x+min(0, dx), x+max(sizes['width1'], dx), y, y+dy, z, z+sizes['length'])
    if not all(math.isfinite(v) for v in limits):
        raise ConfigurationError('native geometry: 단위 변환 후 좌표 범위를 초과했습니다')
    return sizes, origin


def build(geometry, scale):
    sizes, origin = parameters(geometry, scale)
    x, y, z = origin
    occ = gmsh.model.occ
    if isinstance(geometry, Sphere):
        occ.addSphere(x, y, z, sizes['radius'])
    elif isinstance(geometry, Cube):
        a = sizes['side']
        occ.addBox(x, y, z, a, a, a)
    elif isinstance(geometry, Cylinder):
        occ.addCylinder(x, y, z, 0, 0, sizes['height'], sizes['radius'])
    else:
        length, w1, w2 = (sizes[k] for k in ('length', 'width1', 'width2'))
        angle = math.radians(geometry.angle_deg)
        c, s = math.cos(angle), math.sin(angle)
        bottom, top = occ.addPoint(x, y, z), occ.addPoint(x, y, z+length)
        hinge = occ.addLine(bottom, top)
        a, b = occ.addPoint(x+w1, y, z), occ.addPoint(x+w1, y, z+length)
        face1 = occ.addPlaneSurface([occ.addCurveLoop([
            hinge, occ.addLine(top, b), occ.addLine(b, a), occ.addLine(a, bottom)])])
        a, b = occ.addPoint(x+w2*c, y+w2*s, z), occ.addPoint(x+w2*c, y+w2*s, z+length)
        face2 = occ.addPlaneSurface([occ.addCurveLoop([
            occ.addLine(bottom, a), occ.addLine(a, b), occ.addLine(b, top), -hinge])])
        occ.synchronize()
        signs = {}
        for face, expected in ((face1, (0, 1, 0)), (face2, (s, -c, 0))):
            low, high = gmsh.model.getParametrizationBounds(2, face)
            normal = gmsh.model.getNormal(face, [(a+b)/2 for a, b in zip(low, high)])
            dot = sum(a*b for a, b in zip(normal, expected))
            if not math.isfinite(dot) or abs(dot) < .5:
                raise MeshBlocked('dihedral: sheet 기준 방향이 유효하지 않습니다')
            signs[face] = 1 if dot > 0 else -1
        return signs
    return {}
