"""Bounded CAD measurements. Unsupported width geometry is never a pass."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations, product
import math

import gmsh
import numpy as np

from .cad import surface_components
from .errors import ConfigurationError, MeshBlocked


@dataclass(frozen=True)
class Feature:
    kind: str
    entities: tuple[int, ...]
    measured: float | None
    size: float
    curves: tuple[int, ...] = ()
    surface: int | None = None
    bounds: tuple[float, ...] | None = None


def surface_curves():
    mapping, seams = {}, set()
    for _, surface in gmsh.model.getEntities(2):
        _, loops = gmsh.model.occ.getCurveLoops(surface)
        tags = [abs(int(tag)) for loop in loops for tag in loop]
        mapping[surface] = tuple(sorted(set(tags)))
        seams.update(tag for tag, count in Counter(tags).items() if count > 1)
    return mapping, seams


def polygon_width(surface):
    """Minimum supporting-line width of a convex, planar, straight-edge face.

    This is orientation invariant and resolves a long thin rectangle. It is not
    a general local-neck, curved-face or self-proximity estimator.
    """
    if gmsh.model.getType(2, surface) != 'Plane':
        raise MeshBlocked(f'width_unsupported: surface {surface}는 평면이 아닙니다')
    _, loops = gmsh.model.occ.getCurveLoops(surface)
    if len(loops) != 1:
        raise MeshBlocked(f'width_unsupported: surface {surface}의 hole/multiple loop')
    curves = [abs(int(t)) for t in loops[0]]
    links = defaultdict(list)
    for curve in curves:
        if gmsh.model.getType(1, curve) != 'Line':
            raise MeshBlocked(f'width_unsupported: surface {surface}의 곡선 경계')
        points = [abs(tag) for dim, tag in gmsh.model.getBoundary([(1, curve)], oriented=False) if dim == 0]
        if len(points) != 2 or points[0] == points[1]:
            raise MeshBlocked('width_incomplete: 경계 endpoint를 구성하지 못했습니다')
        a, b = points
        links[a].append(b); links[b].append(a)
    if len(links) < 3 or any(len(neighbors) != 2 for neighbors in links.values()):
        raise MeshBlocked('width_incomplete: 단순 polygon 경계를 구성하지 못했습니다')
    start = min(links)
    order, visited, previous, current = [], set(), None, start
    while current not in visited:
        order.append(current)
        visited.add(current)
        other = next(tag for tag in links[current] if tag != previous)
        previous, current = current, other
    if current != start or len(order) != len(links):
        raise MeshBlocked('width_incomplete: 열린/중복 polygon 경계')
    xyz = np.array([gmsh.model.getValue(0, tag, []) for tag in order], dtype=float)
    xyz -= xyz[0].copy()
    scale = float(np.max(np.ptp(xyz, axis=0)))
    if not np.isfinite(xyz).all() or not math.isfinite(scale) or scale <= 0:
        raise MeshBlocked('width_incomplete: 유효한 polygon 좌표가 없습니다')
    points = xyz / scale
    _, singular, vectors = np.linalg.svd(points - points.mean(axis=0), full_matrices=False)
    if singular[1] <= 1e-12 or singular[2] > 1e-9:
        raise MeshBlocked('width_incomplete: 평면 polygon의 수치 정밀도가 부족합니다')
    uv = points @ vectors[:2].T
    edges = np.roll(uv, -1, axis=0) - uv
    turns = edges[:, 0]*np.roll(edges, -1, axis=0)[:, 1] - edges[:, 1]*np.roll(edges, -1, axis=0)[:, 0]
    if np.any(turns > 1e-12) and np.any(turns < -1e-12):
        raise MeshBlocked(f'width_unsupported: surface {surface}의 비볼록 neck/접힘')
    lengths = np.linalg.norm(edges, axis=1)
    if np.any(lengths <= 1e-12):
        raise MeshBlocked('width_incomplete: 중복/수치상 퇴화 경계')
    normals = np.column_stack((-edges[:, 1], edges[:, 0])) / lengths[:, None]
    projections = uv @ normals.T
    width = float(np.ptp(projections, axis=0).min()) * scale
    if not math.isfinite(width) or width <= 0:
        raise MeshBlocked('width_incomplete: 유효한 폭이 없습니다')
    return width


def independent_pairs(components, owners):
    groups = defaultdict(list)
    for face, component in sorted(components.items()):
        groups[component].append(face)
    for group_a, group_b in combinations(groups.values(), 2):
        common_owner = set.intersection(*(owners[face] for face in group_a+group_b))
        if common_owner:
            continue  # Inner/outer shells of the same solid are not free gaps.
        for a, b in product(group_a, group_b):
            if not owners[a] & owners[b]:
                yield tuple(sorted((a, b)))


def discover(config, global_size):
    local = config.sizing.local
    if not (local.short_edges.enabled or local.widths.enabled or local.gaps.enabled or local.curves or local.boxes):
        return ()
    mapping, seams = surface_curves()
    all_surfaces, all_curves = set(mapping), {tag for tags in mapping.values() for tag in tags}
    result = []
    def append(feature):
        if not math.isfinite(feature.size) or feature.size <= 0:
            raise MeshBlocked(f'feature_size_incomplete: {feature.kind} 길이를 표현하지 못했습니다')
        if feature.size < global_size*(1-1e-12):
            result.append(feature)
    if local.short_edges.enabled:
        chosen = set(local.short_edges.entities) if local.short_edges.entities else all_curves - seams
        if chosen - all_curves or (local.short_edges.entities and chosen & seams):
            raise ConfigurationError('short_edges.entities: 실제 surface 경계의 non-seam curve가 필요합니다')
        for curve in sorted(chosen):
            length = float(gmsh.model.occ.getMass(1, curve))
            if not math.isfinite(length) or length < 0:
                raise MeshBlocked(f'edge_length_incomplete: curve {curve}')
            if length == 0:  # Degenerate CAD pole, not a finite short-edge request.
                continue
            append(Feature('short_edge', (curve,), length, length/local.short_edges.divisions, (curve,)))
    if local.widths.enabled:
        chosen = set(local.widths.entities) if local.widths.entities else all_surfaces
        if chosen - all_surfaces:
            raise ConfigurationError('widths.entities: 실제 surface tag가 필요합니다')
        for surface in sorted(chosen):
            width = polygon_width(surface)
            append(Feature('width', (surface,), width, width/local.widths.divisions,
                           mapping[surface], surface))
    if local.gaps.enabled:
        components, _ = surface_components()
        owners = defaultdict(set)
        for _, volume in gmsh.model.getEntities(3):
            for dim, tag in gmsh.model.getBoundary([(3, volume)], oriented=False):
                if dim == 2:
                    owners[abs(tag)].add(volume)
        boxes = {tag: np.asarray(gmsh.model.getBoundingBox(2, tag), dtype=float) for tag in all_surfaces}
        explicit = bool(local.gaps.pairs)
        pairs = local.gaps.pairs if explicit else independent_pairs(components, owners)
        for a, b in pairs:
            if a not in all_surfaces or b not in all_surfaces:
                raise ConfigurationError('gaps.pairs: 실제 surface tag 쌍이 필요합니다')
            if components[a] == components[b] or owners[a] & owners[b]:
                if explicit:
                    raise ConfigurationError('gaps.pairs: 공유 연결/같은 solid를 분리 gap으로 지정할 수 없습니다')
                continue
            box_a, box_b = boxes[a], boxes[b]
            separation = np.maximum(np.maximum(box_a[:3]-box_b[3:], box_b[:3]-box_a[3:]), 0)
            if np.linalg.norm(separation) >= global_size*local.gaps.divisions:
                continue
            try:
                measured = np.asarray(gmsh.model.occ.getDistance(2, a, 2, b), dtype=float)
            except Exception as exc:
                raise MeshBlocked(f'gap_measurement_incomplete: {a},{b}: {exc}') from exc
            if measured.shape != (7,) or not np.isfinite(measured).all() or measured[0] < 0:
                raise MeshBlocked(f'gap_measurement_incomplete: {a},{b}')
            distance, p, q = float(measured[0]), measured[1:4], measured[4:7]
            numeric = max(128*np.finfo(float).eps*float(np.max(np.abs(measured[1:]))), global_size*1e-12)
            if distance <= numeric:
                raise MeshBlocked(f'gap_contact_or_ambiguous: {a},{b}; 분리 entity의 접촉/간극 0은 자동 병합하지 않습니다')
            if abs(float(np.linalg.norm(p-q))-distance) > max(numeric, distance*1e-8):
                raise MeshBlocked('gap_measurement_incomplete: 최소 거리와 반환 endpoint가 다릅니다')
            # Keep the overlapping extent plus the shortest connector: conservative
            # AABB region, not a map of equal gap width over an arbitrary face.
            low = np.minimum(np.maximum(box_a[:3], box_b[:3]), np.minimum(p, q))
            high = np.maximum(np.minimum(box_a[3:], box_b[3:]), np.maximum(p, q))
            append(Feature('gap', (a, b), distance, distance/local.gaps.divisions,
                           bounds=tuple(np.r_[low, high])))
    existing_curves = {tag for _, tag in gmsh.model.getEntities(1)}
    for request in local.curves:
        if request.entity not in existing_curves:
            raise ConfigurationError('curves.entity: 실제 CAD curve tag가 필요합니다')
        append(Feature('manual_curve', (request.entity,), None, min(request.size, global_size), (request.entity,)))
    for index, request in enumerate(local.boxes):
        append(Feature('manual_box', (index,), None, min(request.size, global_size), bounds=request.bounds))
    return tuple(result)
