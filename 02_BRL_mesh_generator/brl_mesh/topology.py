"""Connectivity, node/edge conformity and triangle interior intersections."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .intersections import intersection_issues
from .model import SurfaceMesh
from .topology_links import inspect_links
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
    xyz = mesh.triangles()
    result = _inspect_connections(mesh, intent, xyz)
    # Node/edge maps and candidate arrays no longer coexist with triangle BVH.
    issues = result.issues + tuple(intersection_issues(xyz, mesh.connectivity, mesh.element_ids))
    return TopologyValues(issues, result.component_count, result.boundary_edges, result.adjacent_size_ratio_max)


def _inspect_connections(mesh, intent, xyz):
    """Connection and node/edge audit; private arrays die before intersections."""
    link_issues, count, boundary, adjacent_ratio, links = inspect_links(mesh, xyz)
    issues = list(link_issues)
    if count != intent.expected_components:
        issues.append(Issue('unexpected_components', f'연결 성분 {count}개, 기대값 {intent.expected_components}개'))
    if intent.expected_edges is None:
        issues.append(Issue('boundary_intent_missing', '기대한 열린/닫힌 경계가 명시되지 않았습니다', 'incomplete'))
    elif boundary != intent.expected_edges:
        issues.append(Issue('unexpected_boundary', '실제 열린 경계와 지정한 경계가 다릅니다'))
    separated = {tuple(sorted(pair)) for pair in intent.separated_surfaces}
    surfaces = set(map(int, mesh.surface_tags))
    if any(len(pair) != 2 or pair[0] == pair[1] or not set(pair) <= surfaces for pair in separated):
        issues.append(Issue('invalid_separation', '분리할 surface 지정이 유효하지 않습니다', 'incomplete'))
    edge_nodes = links.edges
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
                edge_surfaces = links.edge_surfaces(mesh, ei)
                if all(tuple(sorted((int(s), int(t)))) in separated
                       for s in links.node_surfaces(mesh, node) for t in edge_surfaces):
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
