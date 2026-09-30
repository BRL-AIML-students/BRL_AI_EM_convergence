from __future__ import annotations

from typing import Any

import gmsh
import numpy as np


def snapshot(surface_pid: dict[int, int]) -> dict[str, Any]:
    element_ids: list[np.ndarray] = []
    connections: list[np.ndarray] = []
    pids: list[np.ndarray] = []
    surface_tags: list[np.ndarray] = []
    for _, surface in sorted(gmsh.model.getEntities(2)):
        kinds, ids_blocks, node_blocks = gmsh.model.mesh.getElements(2, surface)
        for kind, ids, nodes in zip(kinds, ids_blocks, node_blocks):
            if len(ids) == 0:
                continue
            properties = gmsh.model.mesh.getElementProperties(int(kind))
            if int(kind) != 2 or int(properties[3]) != 3:
                raise ValueError(f"only first-order triangles are allowed; found {properties[0]}")
            count = len(ids)
            element_ids.append(np.asarray(ids, dtype=np.int64))
            connections.append(np.asarray(nodes, dtype=np.int64).reshape(count, 3))
            pids.append(np.full(count, surface_pid[surface], dtype=np.int64))
            surface_tags.append(np.full(count, surface, dtype=np.int64))
    if not element_ids:
        raise ValueError("surface meshing produced no triangles")
    ids = np.concatenate(element_ids)
    conn = np.concatenate(connections)
    pid = np.concatenate(pids)
    surface_tag = np.concatenate(surface_tags)
    order = np.argsort(ids)
    ids, conn, pid, surface_tag = ids[order], conn[order], pid[order], surface_tag[order]
    if len(np.unique(ids)) != len(ids):
        raise ValueError("duplicate element identifiers were produced")

    node_ids, coordinates, _ = gmsh.model.mesh.getNodes()
    node_ids = np.asarray(node_ids, dtype=np.int64)
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, 3)
    node_order = np.argsort(node_ids)
    node_ids, coordinates = node_ids[node_order], coordinates[node_order]
    used = np.unique(conn)
    indices = np.searchsorted(node_ids, used)
    if np.any(indices >= len(node_ids)) or not np.array_equal(node_ids[indices], used):
        raise ValueError("triangle connectivity references a missing node")
    return {"node_ids": used, "coordinates": coordinates[indices], "element_ids": ids, "connectivity": conn, "pids": pid, "surface_tags": surface_tag}
