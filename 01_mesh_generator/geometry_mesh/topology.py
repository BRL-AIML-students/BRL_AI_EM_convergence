"""ID topology and spatial conformity checks; proximity never silently welds nodes."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np


class AABBTree:
    """Balanced bounding-box tree. Query results are candidates, not verdicts."""
    def __init__(self, low: np.ndarray, high: np.ndarray):
        self.low, self.high = low, high
        self.nodes: list[tuple] = []
        self.root = self._build(np.arange(len(low))) if len(low) else -1

    def _build(self, indices: np.ndarray) -> int:
        low, high = self.low[indices].min(axis=0), self.high[indices].max(axis=0)
        index = len(self.nodes)
        self.nodes.append(None)
        if len(indices) <= 16:
            self.nodes[index] = (low, high, -1, -1, indices)
        else:
            centers = (self.low[indices] + self.high[indices]) * 0.5
            axis = int(np.argmax(np.ptp(centers, axis=0)))
            order = np.argsort(centers[:, axis], kind="stable")
            split = len(order) // 2
            left, right = self._build(indices[order[:split]]), self._build(indices[order[split:]])
            self.nodes[index] = (low, high, left, right, None)
        return index

    def query(self, low: np.ndarray, high: np.ndarray):
        pending = [self.root] if self.root >= 0 else []
        while pending:
            lo, hi, left, right, indices = self.nodes[pending.pop()]
            if np.any(hi < low) or np.any(lo > high):
                continue
            if indices is None:
                pending.extend((left, right))
            else:
                selected = indices[np.all(self.high[indices] >= low, axis=1) & np.all(self.low[indices] <= high, axis=1)]
                yield from map(int, selected)


class DisjointSet:
    def __init__(self, size: int):
        self.parents = list(range(size))

    def find(self, item: int) -> int:
        while item != self.parents[item]:
            self.parents[item] = self.parents[self.parents[item]]
            item = self.parents[item]
        return item

    def join(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parents[max(a, b)] = min(a, b)


def inspect(mesh: dict[str, Any], geometry: dict[str, Any], settings: dict[str, Any]) -> tuple[dict, list]:
    ids, xyz, conn = mesh["node_ids"], mesh["coordinates"], mesh["connectivity"]
    eids, surfaces = mesh["element_ids"], mesh["surface_tags"]
    incident = defaultdict(list)
    star_links = defaultdict(list)
    edges: dict[tuple[int, int], list[int]] = defaultdict(list)
    node_surfaces = defaultdict(set)
    components = DisjointSet(len(conn))
    for index, tri in enumerate(conn):
        for node in tri:
            incident[int(node)].append(index)
            node_surfaces[int(node)].add(int(surfaces[index]))
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges[tuple(sorted((int(a), int(b))))].append(index)
    for edge, owners in edges.items():
        for owner in owners[1:]:
            components.join(owners[0], owner)
            for node in edge:
                star_links[node].append((owners[0], owner))
    bad_fans = []
    for node, owners in incident.items():
        local = DisjointSet(len(owners))
        mapping = {owner: i for i, owner in enumerate(owners)}
        for a, b in star_links[node]:
            local.join(mapping[a], mapping[b])
        if len({local.find(i) for i in range(len(owners))}) > 1:
            bad_fans.append({"node_id": node, "element_ids": [int(eids[i]) for i in owners]})
    groups = defaultdict(list)
    for i in range(len(conn)):
        groups[components.find(i)].append(i)
    closed_surfaces = set(geometry.get("closed_surface_tags", []))
    cad_edges = {tuple(sorted(map(int, e))) for e in mesh.get("cad_boundary_edges", [])}
    records, gates = [], []
    for owners in groups.values():
        own = set(owners)
        tags = sorted(set(map(int, surfaces[owners])))
        boundaries = [edge for edge, es in edges.items() if len(es) == 1 and es[0] in own]
        mode = settings["boundary_mode"]
        closed = mode == "closed" or (mode == "auto" and bool(closed_surfaces.intersection(tags)))
        # Legacy analytic inputs can declare closure without surface-tag metadata.
        if mode == "auto" and "closed_surface_tags" not in geometry:
            closed = bool(geometry.get("volume_count", 0))
        internal = [list(edge) for edge in boundaries if edge not in cad_edges] if mesh.get("cad_boundary_edges") is not None else []
        records.append({"surface_tags": tags, "element_count": len(owners), "expected_closed": closed,
                        "boundary_edges": len(boundaries), "unexpected_boundary_edges": internal,
                        "boundary_intent_evidence": "cad_curves" if cad_edges else "explicit_mode" if mode != "auto" else "unavailable"})
        if closed and boundaries:
            gates.append({"code": "open_volume_boundary", "message": "closed component has exposed edges", "surface_tags": tags})
        if not closed and internal:
            gates.append({"code": "unexpected_open_boundary", "message": "open component has an edge outside its CAD boundary", "edges": internal})
    if bad_fans:
        gates.append({"code": "nonmanifold_vertices", "message": "disconnected triangle fans at shared vertices", "vertices": bad_fans})

    # Each edge has its own tolerance; large distant edges do not inflate small gaps.
    edge_nodes = np.asarray(list(edges), dtype=np.int64)
    index = np.searchsorted(ids, edge_nodes)
    a, b = xyz[index[:, 0]], xyz[index[:, 1]]
    vectors = b - a
    lengths = np.linalg.norm(vectors, axis=1)
    numeric = 64 * np.finfo(float).eps * np.maximum(np.max(np.abs(a), axis=1), np.max(np.abs(b), axis=1))
    tolerances = np.maximum(np.maximum(numeric, settings["absolute_tolerance"]), lengths * settings["relative_tolerance"])
    tree = AABBTree(np.minimum(a, b) - tolerances[:, None], np.maximum(a, b) + tolerances[:, None])
    separated = {tuple(sorted(pair)) for pair in settings["separated_surface_pairs"]}
    present = set(map(int, surfaces))
    if any(not set(pair).issubset(present) for pair in separated):
        gates.append({"code": "unknown_separated_surface", "message": "explicit separation refers to a missing surface tag"})
    candidates, confirmed, duplicate, ignored = [], [], {}, 0
    candidate_tests = 0
    complete = True
    for node, point in zip(map(int, ids), xyz):
        for ei in tree.query(point, point):
            edge = tuple(map(int, edge_nodes[ei]))
            if node in edge or lengths[ei] == 0:
                continue
            candidate_tests += 1
            if candidate_tests > settings["max_candidate_tests"]:
                complete = False
                break
            tau = float(tolerances[ei])
            esurfaces = {int(surfaces[i]) for i in edges[edge]}
            nsurfaces = node_surfaces[node]
            intended_separate = all(tuple(sorted((x, y))) in separated for x in nsurfaces for y in esurfaces)
            if intended_separate:
                ignored += 1
                continue
            if settings["protected_gap"] is not None and tau >= settings["protected_gap"] / 10:
                candidates.append({"node_id": node, "edge": list(edge), "reason": "tolerance conflicts with protected gap", "tolerance": tau})
                continue
            t = float(np.dot(point - a[ei], vectors[ei]) / lengths[ei] ** 2)
            distance = float(np.linalg.norm(point - (a[ei] + t * vectors[ei])))
            if distance > tau:
                continue
            near_endpoint = min(np.linalg.norm(point - a[ei]), np.linalg.norm(point - b[ei]))
            exact = max(float(numeric[ei]), float(lengths[ei] * 32 * np.finfo(float).eps))
            if near_endpoint <= tau:
                other = edge[int(np.linalg.norm(point - b[ei]) < np.linalg.norm(point - a[ei]))]
                pair = tuple(sorted((node, other)))
                duplicate[pair] = {"node_ids": list(pair), "distance": float(near_endpoint), "confirmed": bool(near_endpoint <= exact)}
            elif tau / lengths[ei] < t < 1 - tau / lengths[ei]:
                record = {"node_id": node, "edge": list(edge), "distance": distance, "tolerance": tau,
                          "element_ids": sorted(set(int(eids[i]) for i in incident[node] + edges[edge]))}
                (confirmed if distance <= exact else candidates).append(record)
        if not complete:
            break
    if confirmed:
        gates.append({"code": "t_junctions", "message": "nonconforming vertex lies inside an unsplit edge", "junctions": confirmed})
    exact_duplicates = [r for r in duplicate.values() if r["confirmed"]]
    near_duplicates = [r for r in duplicate.values() if not r["confirmed"]]
    if exact_duplicates:
        gates.append({"code": "unshared_coincident_nodes", "message": "coincident node positions use different IDs", "nodes": exact_duplicates})
    if candidates or near_duplicates or not complete:
        gates.append({"code": "conformity_review_required", "message": "ambiguous proximity or spatial audit budget exceeded; export withheld"})
    return {"coverage": "assessed" if complete else "partial", "components": records,
            "nonmanifold_vertices": bad_fans, "t_junctions": confirmed, "proximity_candidates": candidates,
            "coincident_nodes": list(duplicate.values()), "explicitly_separated_candidates": ignored,
            "candidate_tests": candidate_tests, "audit_complete": complete,
            "tolerance": {"absolute": settings["absolute_tolerance"], "relative": settings["relative_tolerance"], "numeric_multiplier": 64},
            "triangle_intersections": {"coverage": "not_assessed", "reason": "vertex/edge audit does not certify absence of arbitrary face intersections"}}, gates
