"""Connectivity and local node/edge conformity, independently of shape quality.

Vertex/edge auditing does not certify absence of arbitrary face intersections.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .model import SurfaceMesh
from .validation import Issue


@dataclass(frozen=True)
class BoundaryIntent:
    # None means unknown, not an automatic permission for all observed openings.
    expected_edges: frozenset[tuple[int, int]] | None
    expected_components: int
    separated_surfaces: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    protected_gap: float | None = None
    relative_tolerance: float = 1e-9


@dataclass(frozen=True)
class TopologyValues:
    issues: tuple[Issue, ...]
    component_count: int
    boundary_edges: frozenset[tuple[int, int]]
    adjacent_size_ratio_max: float


class _Sets:
    def __init__(self, n):
        self.parents = list(range(n))

    def find(self, i):
        while self.parents[i] != i:
            self.parents[i] = self.parents[self.parents[i]]
            i = self.parents[i]
        return i

    def join(self, a, b):
        self.parents[self.find(b)] = self.find(a)


class _Boxes:
    """Balanced AABB candidate index; actual distances are checked separately."""
    def __init__(self, low, high):
        self.low, self.high, self.nodes = low, high, []
        self.root = self._build(np.arange(len(low)))

    def _build(self, ids):
        lo, hi = self.low[ids].min(axis=0), self.high[ids].max(axis=0)
        index = len(self.nodes)
        self.nodes.append(None)
        if len(ids) <= 16:
            self.nodes[index] = (lo, hi, ids, -1, -1)
        else:
            centers = (self.low[ids] + self.high[ids]) / 2
            ordered = ids[np.argsort(centers[:, np.argmax(np.ptp(centers, axis=0))], kind='stable')]
            middle = len(ordered) // 2
            self.nodes[index] = (lo, hi, None, self._build(ordered[:middle]), self._build(ordered[middle:]))
        return index

    def candidates(self, points):
        """Yield point/edge arrays, visiting each box once per point batch."""
        pending = [(self.root, np.arange(len(points)))]
        while pending:
            index, point_ids = pending.pop()
            lo, hi, ids, left, right = self.nodes[index]
            point_ids = point_ids[np.all((points[point_ids] >= lo) & (points[point_ids] <= hi), axis=1)]
            if not len(point_ids):
                continue
            if ids is None:
                pending.extend(((left, point_ids), (right, point_ids)))
            else:
                candidates = points[point_ids, None, :]
                mask = np.all((candidates >= self.low[ids]) & (candidates <= self.high[ids]), axis=2)
                rows, columns = np.nonzero(mask)
                if len(rows):
                    yield point_ids[rows], ids[columns]


def inspect_topology(mesh: SurfaceMesh, intent: BoundaryIntent) -> TopologyValues:
    mesh.validate()
    issues = []
    if (type(intent.expected_components) is not int or intent.expected_components < 1
            or not np.isfinite(intent.relative_tolerance) or not 0 < intent.relative_tolerance < 0.01
            or (intent.protected_gap is not None and (not np.isfinite(intent.protected_gap) or intent.protected_gap <= 0))):
        return TopologyValues((Issue('invalid_topology_intent', '검사 조건이 유효하지 않습니다', 'incomplete'),),
                              0, frozenset(), float('inf'))
    edges, incident, node_surfaces = defaultdict(list), defaultdict(list), defaultdict(set)
    for i, nodes in enumerate(mesh.connectivity):
        for node in map(int, nodes):
            incident[node].append(i)
            node_surfaces[node].add(int(mesh.surface_tags[i]))
        for j in range(3):
            a, b = int(nodes[j]), int(nodes[(j + 1) % 3])
            edges[tuple(sorted((a, b)))].append((i, a, b))
    components = _Sets(len(mesh.element_ids))
    fan_links = defaultdict(list)
    xyz = mesh.triangles()
    double_area = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1)
    adjacent_ratio = 1.0
    for edge, owners in edges.items():
        if len(owners) > 2:
            issues.append(Issue('nonmanifold_edge', f'edge {edge}에 3개 이상 요소가 접합니다'))
        if len(owners) == 2 and owners[0][1:] != owners[1][1:][::-1]:
            issues.append(Issue('inconsistent_winding', f'공유 edge {edge}의 방향이 일치하지 않습니다'))
        for other in owners[1:]:
            first = owners[0][0]
            components.join(first, other[0])
            for node in edge:
                fan_links[node].append((first, other[0]))
            adjacent_ratio = max(adjacent_ratio, float(np.sqrt(max(double_area[first], double_area[other[0]])
                                                               / min(double_area[first], double_area[other[0]]))))
    for node, triangles in incident.items():
        local = _Sets(len(triangles))
        indices = {t: i for i, t in enumerate(triangles)}
        for a, b in fan_links[node]:
            local.join(indices[a], indices[b])
        if len({local.find(i) for i in range(len(triangles))}) > 1:
            issues.append(Issue('nonmanifold_vertex', f'node {node}의 삼각형 fan이 끊어져 있습니다'))
    count = len({components.find(i) for i in range(len(mesh.element_ids))})
    if count != intent.expected_components:
        issues.append(Issue('unexpected_components', f'연결 성분 {count}개, 기대값 {intent.expected_components}개'))
    boundary = frozenset(edge for edge, owners in edges.items() if len(owners) == 1)
    if intent.expected_edges is None:
        issues.append(Issue('boundary_intent_missing', '기대한 열린/닫힌 경계가 명시되지 않았습니다', 'incomplete'))
    elif boundary != intent.expected_edges:
        issues.append(Issue('unexpected_boundary', '실제 열린 경계와 지정한 경계가 다릅니다'))
    separated = {tuple(sorted(pair)) for pair in intent.separated_surfaces}
    surfaces = set(map(int, mesh.surface_tags))
    if any(len(pair) != 2 or pair[0] == pair[1] or not set(pair) <= surfaces for pair in separated):
        issues.append(Issue('invalid_separation', '분리할 surface 지정이 유효하지 않습니다', 'incomplete'))
    edge_nodes = np.asarray(list(edges), dtype=np.int64)
    endpoints = mesh.coordinates[np.searchsorted(mesh.node_ids, edge_nodes)]
    a, b = endpoints[:, 0], endpoints[:, 1]
    vector = b - a
    lengths = np.linalg.norm(vector, axis=1)
    numeric = 64 * np.finfo(float).eps * np.max(np.abs(endpoints), axis=(1, 2))
    exact = np.maximum(numeric, lengths * 32 * np.finfo(float).eps)
    tolerance = np.maximum(exact, lengths * intent.relative_tolerance)
    tree = _Boxes(np.minimum(a, b) - tolerance[:, None], np.maximum(a, b) + tolerance[:, None])
    codes = set()
    for start in range(0, len(mesh.node_ids), 2048):
        points = mesh.coordinates[start:start+2048]
        for rows, edge_ids in tree.candidates(points):
            nodes = mesh.node_ids[start+rows]
            keep = np.all(nodes[:, None] != edge_nodes[edge_ids], axis=1)
            rows, edge_ids, nodes = rows[keep], edge_ids[keep], nodes[keep]
            if not len(rows):
                continue
            offsets = points[rows] - a[edge_ids]
            vectors = vector[edge_ids]
            projections = np.einsum('ij,ij->i', offsets, vectors) / lengths[edge_ids]**2
            distances = np.linalg.norm(offsets - projections[:, None]*vectors, axis=1)
            close = distances <= tolerance[edge_ids]
            # Only geometric contacts need the per-surface separation policy.
            for node, ei, projection, distance in zip(nodes[close], edge_ids[close],
                                                       projections[close], distances[close]):
                node, ei = int(node), int(ei)
                point = mesh.coordinates[np.searchsorted(mesh.node_ids, node)]
                edge = tuple(map(int, edge_nodes[ei]))
                edge_surfaces = {int(mesh.surface_tags[owner[0]]) for owner in edges[edge]}
                if all(tuple(sorted((s, t))) in separated for s in node_surfaces[node] for t in edge_surfaces):
                    continue
                tau = float(tolerance[ei])
                if intent.protected_gap is not None and tau >= intent.protected_gap / 10:
                    codes.add(('gap_tolerance_conflict', 'incomplete'))
                    continue
                endpoint_distance = min(np.linalg.norm(point - a[ei]), np.linalg.norm(point - b[ei]))
                if endpoint_distance <= tau:
                    codes.add(('unshared_coincident_nodes' if endpoint_distance <= exact[ei] else 'ambiguous_proximity',
                               'blocked' if endpoint_distance <= exact[ei] else 'incomplete'))
                elif tau / lengths[ei] < projection < 1 - tau / lengths[ei]:
                    codes.add(('t_junction' if distance <= exact[ei] else 'ambiguous_proximity',
                               'blocked' if distance <= exact[ei] else 'incomplete'))
    for code, status in sorted(codes):
        issues.append(Issue(code, '공유되지 않은 node/edge 관계 또는 불확실한 근접 관계가 있습니다', status))
    return TopologyValues(tuple(issues), count, boundary, adjacent_ratio)
