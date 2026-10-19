"""Exact native OCC tangent ogive: arc, half revolution, copy and join.

D/L/t retain their geometric meaning; no STEP intermediate or archive imports.
"""
import math
import sys

from .errors import ConfigurationError, MeshBlocked


def parameters(geometry, scale):
    d, length, t = (geometry.diameter*scale, geometry.length*scale, geometry.thickness*scale)
    origin = tuple(v*scale for v in geometry.origin)
    radius = (length/d)*length+d/4 if d > 0 else float('inf')
    if not all(math.isfinite(v) for v in (d, length, t, radius, *origin)) or min(d, length) <= 0:
        raise ConfigurationError('ogive: 단위 변환/원호 반경을 표현하지 못했습니다')
    if geometry.thickness > 0 and t <= 0:
        raise ConfigurationError('ogive: 양의 두께가 단위 변환에서 소실됐습니다')
    r = d/2
    precision = 128*sys.float_info.epsilon*max(radius, length, *(abs(v) for v in origin))
    if length <= r or not 0 <= t < r or r <= precision or (t and min(t, r-t) <= precision):
        raise ConfigurationError('ogive: D/L/t 조건 또는 좌표 정밀도에 맞지 않습니다')
    x, y, z = origin
    if not all(math.isfinite(v) for v in (x+r, x-r, y+r, y-r, z+length, x+r-radius)):
        raise ConfigurationError('ogive: 단위 변환 후 좌표 범위를 초과했습니다')
    if x+r == x or x-r == x or y+r == y or y-r == y or z+length == z:
        raise ConfigurationError('ogive: origin에서 반경/길이를 표현하지 못했습니다')
    return d, length, t, radius, r-radius, origin


def _one(entities, dimension):
    tags = [tag for dim, tag in entities if dim == dimension]
    if len(tags) != 1:
        raise MeshBlocked(f'ogive_construction_incomplete: dimension {dimension} entity {tags}')
    return tags[0]


def build(geometry, scale):
    import gmsh
    d, length, t, radius, center_x, origin = parameters(geometry, scale)
    occ = gmsh.model.occ
    before = set(occ.getEntities())
    x, y, z = origin
    center = occ.addPoint(x+center_x, y, z)
    base, tip = occ.addPoint(x+d/2, y, z), occ.addPoint(x, y, z+length)
    outer = occ.addCircleArc(base, center, tip)
    if t:
        inner_radius = radius-t
        inner_tip = math.sqrt(d/2-t)*math.sqrt(2*radius-d/2-t)
        if not 0 < inner_tip < length or inner_radius == radius:
            raise ConfigurationError('ogive: 내부 tip/벽 두께를 표현하지 못했습니다')
        ibase, itip = occ.addPoint(x+d/2-t, y, z), occ.addPoint(x, y, z+inner_tip)
        inner = occ.addCircleArc(ibase, center, itip)
        tip_line, base_line = occ.addLine(tip, itip), occ.addLine(ibase, base)
        loop = occ.addCurveLoop([outer, tip_line, -inner, base_line])
        section = (2, occ.addPlaneSurface([loop]))
    else:
        section = (1, outer)
    dim = section[0]+1
    first = _one(occ.revolve([section], *origin, 0, 0, 1, math.pi), dim)
    second = _one(occ.copy([(dim, first)]), dim)
    occ.rotate([(dim, second)], *origin, 0, 0, 1, math.pi)
    if t:
        joined, _ = occ.fuse([(dim, first)], [(dim, second)])
        roots = [(dim, _one(joined, dim))]
    else:
        joined, _ = occ.fragment([(dim, first)], [(dim, second)])
        roots = [entity for entity in joined if entity[0] == dim]
        if len(roots) != 2:
            raise MeshBlocked('ogive_construction_incomplete: 반회전 sheet 두 면이 필요합니다')
    occ.synchronize()
    keep, pending = set(roots), list(roots)
    while pending:
        entity = pending.pop()
        if entity[0]:
            for dimension, tag in gmsh.model.getBoundary([entity], combined=False, oriented=False):
                child = (dimension, abs(tag))
                if child not in keep:
                    keep.add(child)
                    pending.append(child)
    for dimension in (2, 1, 0):
        unused = [dt for dt in occ.getEntities(dimension) if dt not in before and dt not in keep]
        if unused:
            occ.remove(unused, recursive=False)
    occ.synchronize()
    if t:
        return {}
    # Auto-reference the known native sheet outward direction analytically.
    signs = {}
    for _, face in roots:
        low, high = gmsh.model.getParametrizationBounds(2, face)
        uv = [(a+b)/2 for a, b in zip(low, high)]
        point = gmsh.model.getValue(2, face, uv)
        normal = gmsh.model.getNormal(face, uv)
        x, y, z = (p-o for p, o in zip(point, origin))
        r = math.hypot(x, y)
        if r <= 0:
            raise MeshBlocked('ogive_normal_incomplete: sheet 기준점이 축 위입니다')
        outward = ((r-center_x)*x/r, (r-center_x)*y/r, z)
        dot = sum(a*b for a, b in zip(normal, outward))
        if not math.isfinite(dot) or abs(dot) <= 1e-12*math.hypot(*outward):
            raise MeshBlocked('ogive_normal_incomplete: sheet 기준 방향을 구하지 못했습니다')
        signs[face] = 1 if dot > 0 else -1
    return signs
