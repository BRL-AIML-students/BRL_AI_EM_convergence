"""Transaction-local integer incidence tables for the connectivity audit."""
from dataclasses import dataclass

import numpy as np

from .validation import Issue


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


def _starts(counts):
    return np.r_[0, np.cumsum(counts[:-1])]


@dataclass(frozen=True)
class _Links:
    edges: np.ndarray
    owners: np.ndarray
    edge_starts: np.ndarray
    edge_counts: np.ndarray
    incident: np.ndarray
    node_starts: np.ndarray
    node_counts: np.ndarray

    def edge_surfaces(self, mesh, edge):
        start = self.edge_starts[edge]
        triangles = self.owners[start:start+self.edge_counts[edge]] // 3
        return np.unique(mesh.surface_tags[triangles])

    def node_surfaces(self, mesh, node):
        index = np.searchsorted(mesh.node_ids, node)
        start = self.node_starts[index]
        triangles = self.incident[start:start+self.node_counts[index]] // 3
        return np.unique(mesh.surface_tags[triangles])


def inspect_links(mesh, xyz):
    """Keep owner order, orientation, vertex fans and nonmanifold diagnostics."""
    oriented = np.stack((mesh.connectivity, np.roll(mesh.connectivity, -1, axis=1)), axis=2).reshape(-1, 2)
    edges, first, inverse, counts = np.unique(np.sort(oriented, axis=1), axis=0,
        return_index=True, return_inverse=True, return_counts=True)
    # Preserve the previous first-occurrence edge order, including diagnostics.
    order = np.argsort(first)
    remap = np.empty(len(order), dtype=np.intp)
    remap[order] = np.arange(len(order))
    inverse = remap[inverse]
    edges, counts = edges[order], counts[order]
    owners = np.argsort(inverse, kind='stable')
    starts = _starts(counts)
    two = np.flatnonzero(counts == 2)
    winding = np.zeros(len(edges), dtype=bool)
    winding[two] = np.any(oriented[owners[starts[two]]] != oriented[owners[starts[two]+1]][:, ::-1], axis=1)
    issues = []
    for index in np.flatnonzero((counts > 2) | winding):
        edge = tuple(map(int, edges[index]))
        issues.append(Issue('nonmanifold_edge', f'edge {edge}에 3개 이상 요소가 접합니다') if counts[index] > 2 else
                      Issue('inconsistent_winding', f'공유 edge {edge}의 방향이 일치하지 않습니다'))

    other = np.ones(len(owners), dtype=bool)
    other[starts] = False
    edge_ids = np.repeat(np.arange(len(edges)), counts)[other]
    left = owners[starts[edge_ids]] // 3
    right = owners[other] // 3
    components = _Sets(len(mesh.element_ids))
    for a, b in zip(left, right):
        components.join(int(a), int(b))
    count = len({components.find(i) for i in range(len(mesh.element_ids))})
    area = np.linalg.norm(np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0]), axis=1)
    adjacent = float(np.sqrt(np.maximum(area[left], area[right])/np.minimum(area[left], area[right])).max(initial=1.))

    incident = np.argsort(mesh.connectivity.ravel(), kind='stable')
    node_counts = np.bincount(np.searchsorted(mesh.node_ids, mesh.connectivity).ravel(), minlength=len(mesh.node_ids))
    node_starts = _starts(node_counts)
    fan_nodes = edges[edge_ids].ravel()
    fan_order = np.argsort(fan_nodes, kind='stable')
    fan_left, fan_right = np.repeat(left, 2)[fan_order], np.repeat(right, 2)[fan_order]
    fan_counts = np.bincount(np.searchsorted(mesh.node_ids, fan_nodes), minlength=len(mesh.node_ids))
    fan_starts = _starts(fan_counts)
    # Vertex diagnostics keep the original first-occurrence node order too.
    for index in np.argsort(incident[node_starts]):
        start = node_starts[index]
        triangles = incident[start:start+node_counts[index]] // 3
        local = _Sets(len(triangles))
        indices = {int(t): i for i, t in enumerate(triangles)}
        start = fan_starts[index]
        stop = start + fan_counts[index]
        for a, b in zip(fan_left[start:stop], fan_right[start:stop]):
            local.join(indices[int(a)], indices[int(b)])
        if len({local.find(i) for i in range(len(triangles))}) > 1:
            issues.append(Issue('nonmanifold_vertex', f'node {int(mesh.node_ids[index])}의 삼각형 fan이 끊어져 있습니다'))
    boundary = frozenset(tuple(map(int, edge)) for edge in edges[counts == 1])
    return (tuple(issues), count, boundary, adjacent,
            _Links(edges, owners, starts, counts, incident, node_starts, node_counts))
