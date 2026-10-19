from contextlib import contextmanager

import gmsh
import numpy as np

from brl_mesh.model import SurfaceMesh


def mesh_from(points, triangles, surfaces=None):
    n = len(triangles)
    return SurfaceMesh(np.arange(1, len(points) + 1), np.asarray(points, dtype=float), np.arange(1, n + 1),
                       np.asarray(triangles, dtype=int), np.ones(n, dtype=int),
                       np.ones(n, dtype=int) if surfaces is None else np.asarray(surfaces, dtype=int))


def exposed_edges(mesh):
    counts = {}
    for row in mesh.connectivity:
        for i in range(3):
            edge = tuple(sorted((int(row[i]), int(row[(i + 1) % 3]))))
            counts[edge] = counts.get(edge, 0) + 1
    return frozenset(e for e, count in counts.items() if count == 1)


def distort_interior(membership, fraction=.85):
    """Move an actual CAD-face interior node towards a neighbor without remeshing."""
    from brl_mesh.model import snapshot
    mesh = snapshot(membership)
    face = next(iter(membership))
    nodes, coordinates, _ = gmsh.model.mesh.getNodes(2, face)
    coordinates = np.asarray(coordinates).reshape(-1, 3)
    node = int(nodes[np.argmin(np.linalg.norm(coordinates - [.5, .5, 0], axis=1))])
    point = mesh.coordinates[np.searchsorted(mesh.node_ids, node)].copy()
    incident = mesh.connectivity[np.any(mesh.connectivity == node, axis=1)]
    neighbor = next(int(n) for n in np.unique(incident) if n != node)
    target = mesh.coordinates[np.searchsorted(mesh.node_ids, neighbor)].copy()
    moved = point + fraction * (target - point)
    gmsh.model.mesh.setNode(node, moved.tolist(), gmsh.model.getParametrization(2, face, moved.tolist()).tolist())
    return node, point, target


@contextmanager
def cad_mesh(kind='box'):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('General.NumThreads', 1)
        gmsh.option.setNumber('Mesh.MeshSizeMin', .35)
        gmsh.option.setNumber('Mesh.MeshSizeMax', .35)
        gmsh.model.add(kind)
        if kind == 'box':
            gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
        elif kind == 'sphere':
            gmsh.model.occ.addSphere(0, 0, 0, 1)
        elif kind == 'shared_face':
            a = gmsh.model.occ.addBox(0, 0, 0, 1, 1, 1)
            b = gmsh.model.occ.addBox(1, 0, 0, 1, 1, 1)
            gmsh.model.occ.fragment([(3, a)], [(3, b)])
        gmsh.model.occ.synchronize()
        membership = {}
        for pid, (_, surface) in enumerate(gmsh.model.getEntities(2), 1):
            membership[surface] = pid
            gmsh.model.addPhysicalGroup(2, [surface], pid)
        gmsh.model.mesh.generate(2)
        yield membership
    finally:
        gmsh.finalize()
