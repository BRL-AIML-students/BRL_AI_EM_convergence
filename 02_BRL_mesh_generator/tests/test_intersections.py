import numpy as np
import pytest

from brl_mesh.intersections import _TriangleBoxes, intersection_issues
from brl_mesh.topology import BoundaryIntent, inspect_topology
from tests.support import exposed_edges, mesh_from


def issues(points, cells=((1, 2, 3), (4, 5, 6)), surfaces=None):
    mesh = mesh_from(points, cells, surfaces)
    return intersection_issues(mesh.triangles(), mesh.connectivity, mesh.element_ids)


CROSSING = np.array([(-1, -1, 0), (1, -1, 0), (0, 1, 0),
                     (0, -.5, -1), (0, -.5, 1), (0, .5, .3)])


@pytest.mark.parametrize('scale', [1e-9, 1., 1e9])
@pytest.mark.parametrize('rotate', [False, True])
def test_interior_crossing_with_local_scale_and_rotation(scale, rotate):
    points = CROSSING.copy()
    if rotate:
        q, _ = np.linalg.qr(np.array([[1., .3, .1], [.4, 1, .2], [.1, .2, 1]]))
        points = points @ q
    assert {x.code for x in issues(points*scale)} == {'triangle_intersection'}


@pytest.mark.parametrize('scale', [1e-9, 1., 1e9])
def test_coplanar_containment_and_crossing_edges(scale):
    outer = np.array([(0, 0, 0), (4, 0, 0), (0, 4, 0)])
    inner = np.array([(.5, .5, 0), (1., .5, 0), (.5, 1., 0)])
    assert issues(np.vstack((outer, inner))*scale)
    crossing = np.array([(0, 0, 0), (2, 0, 0), (1, 2, 0),
                         (0, 1.5, 0), (2, 1.5, 0), (1, -.5, 0)])
    assert issues(crossing*scale)


@pytest.mark.parametrize('height', [0., 1e-12, 1.])
def test_shared_edge_normal_dihedral_and_coplanar_neighbours(height):
    points = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, height)]
    assert not issues(points, ((1, 2, 3), (2, 1, 4)))


def test_shared_edge_foldover_and_shared_vertex_overlap_blocked():
    assert issues([(0, 0, 0), (1, 0, 0), (0, 1, 0), (.5, .5, 0)],
                  ((1, 2, 3), (2, 1, 4)))
    assert issues([(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, .2, 0), (.2, 1, 0)],
                  ((1, 2, 3), (1, 4, 5)))


@pytest.mark.parametrize('gap', [1e-8, 1e-14, 1e-18])
def test_positive_parallel_and_coplanar_gaps_preserved(gap):
    points = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                       (0, 0, gap), (1, 0, gap), (0, 1, gap)])
    assert not issues(points)
    points = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0),
                       (-gap, 0, 0), (-1, 0, 0), (-gap, 1, 0)])
    assert not issues(points)


def test_separation_intent_cannot_authorize_actual_crossing():
    mesh = mesh_from(CROSSING, [(1, 2, 3), (4, 5, 6)], [1, 2])
    result = inspect_topology(mesh, BoundaryIntent(exposed_edges(mesh), 2, frozenset({(1, 2)})))
    assert any(x.code == 'triangle_intersection' and x.status == 'blocked' for x in result.issues)


def test_bvh_pairs_match_exhaustive_boxes_without_duplicates():
    rng = np.random.default_rng(124)
    triangles = rng.random((61, 3, 3))
    boxes = _TriangleBoxes(triangles)
    actual = [tuple(sorted((int(i), int(j)))) for left, right in boxes.pairs() for i, j in zip(left, right)]
    expected = [(i, j) for i in range(61) for j in range(i+1, 61)
                if np.all(boxes.low[i] <= boxes.high[j]) and np.all(boxes.low[j] <= boxes.high[i])]
    assert len(actual) == len(set(actual))
    assert set(actual) == set(expected)

@pytest.mark.parametrize('kind', ['box', 'sphere'])
def test_normal_closed_cad_surfaces_do_not_intersect(kind):
    from brl_mesh.model import snapshot
    from tests.support import cad_mesh
    with cad_mesh(kind) as membership:
        mesh = snapshot(membership)
        assert not intersection_issues(mesh.triangles(), mesh.connectivity, mesh.element_ids)


def test_crossing_independent_cad_sheets_block_nas_publication(tmp_path):
    import math
    import gmsh
    from brl_mesh.config import Configuration
    from brl_mesh.engine import run
    from brl_mesh.errors import MeshBlocked
    path = tmp_path / 'crossing.brep'
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.model.add('crossing')
        gmsh.model.occ.addRectangle(0, 0, 0, 2, 2)
        vertical = gmsh.model.occ.addRectangle(0, 0, 0, 1, 1)
        gmsh.model.occ.rotate([(2, vertical)], 0, 0, 0, 0, 1, 0, math.pi/2)
        gmsh.model.occ.translate([(2, vertical)], .371, .237, .531)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    destination = tmp_path / 'publication'
    config = Configuration.from_dict({
        'schema_version': 1, 'geometry': {'kind': 'cad', 'path': str(path), 'sheet_normal': 1},
        'mesh': {'target_size': .19}, 'output_dir': str(destination)})
    with pytest.raises(MeshBlocked, match='면 교차/중첩'):
        run(config)
    assert not list(destination.rglob('*.nas'))

@pytest.mark.parametrize('angle', [.13, .71, 1.42])
def test_rotated_coplanar_containment(angle):
    points = np.array([(0, 0, 0), (4, 0, 0), (0, 4, 0),
                       (.5, .5, 0), (1., .5, 0), (.5, 1., 0)])
    q, _ = np.linalg.qr(np.array([[1., angle, .1], [.4, 1, angle], [angle, .2, 1]]))
    assert issues(points @ q)


def test_batched_predicate_agrees_with_scalar_reference():
    from brl_mesh.intersections import _batch, _pair
    rng = np.random.default_rng(742)
    a, b = rng.normal(size=(2, 250, 3, 3))
    # Include general crossing, shared vertex, shared edge and coplanar cases.
    shared = np.arange(len(a)) % 3
    for i in range(len(a)):
        b[i, :shared[i]] = a[i, :shared[i]]
    a[::4, :, 2] = b[::4, :, 2] = 0
    mapping = {None: 0, 'triangle_intersection': 1, 'uncertain_triangle_intersection': 2}
    expected = [mapping[_pair(ta, tb, int(n))] for ta, tb, n in zip(a, b, shared)]
    assert np.array_equal(_batch(a, b, shared), expected)

@pytest.mark.parametrize('points', [
    # Independent vertex touching the other triangle's face interior.
    [(-1, -1, 0), (1, -1, 0), (0, 1, 0),
     (0, 0, 0), (1, -.5, 1), (-1, -.5, 1)],
    # Independent edges crossing at a single point, with no node on that point.
    [(-1, 0, 0), (1, 0, 0), (0, 1, 0),
     (0, 0, -1), (0, 0, 1), (0, -1, 0)],
])
def test_independent_single_point_contacts_are_blocked(points):
    mesh = mesh_from(points, [(1, 2, 3), (4, 5, 6)], [1, 2])
    result = inspect_topology(mesh, BoundaryIntent(exposed_edges(mesh), 2, frozenset({(1, 2)})))
    assert any(x.code == 'triangle_intersection' and x.status == 'blocked' for x in result.issues)


@pytest.mark.parametrize('gap', [1e-8, 1e-14, 1e-18])
def test_point_contact_counterparts_with_positive_gap_are_preserved(gap):
    vertex_face = np.array([(-1, -1, 0), (1, -1, 0), (0, 1, 0),
                            (0, 0, 0), (1, -.5, 1), (-1, -.5, 1)], dtype=float)
    vertex_face[3:, 2] += gap
    assert not issues(vertex_face)
    edge_edge = np.array([(-1, 0, 0), (1, 0, 0), (0, 1, 0),
                          (0, 0, -1), (0, 0, 1), (0, -1, 0)], dtype=float)
    edge_edge[3:, 1] -= gap
    assert not issues(edge_edge)


def test_normal_shared_vertex_point_contact_is_preserved():
    assert not issues([(-1, -1, 0), (1, -1, 0), (0, 0, 0),
                       (1, -.5, 1), (-1, -.5, 1)],
                      ((1, 2, 3), (3, 4, 5)))


def test_confirmed_intersection_stops_before_later_candidate_batches(monkeypatch):
    import brl_mesh.intersections as module
    triangles = CROSSING.reshape(2, 3, 3)
    cells = np.arange(1, 7).reshape(2, 3)

    def candidates(_self):
        # A full first batch contains confirmed intersections. Consuming the
        # next batch would perform needless work after the audit is blocked.
        yield np.zeros(4096, dtype=int), np.ones(4096, dtype=int)
        raise AssertionError('confirmed intersection must stop candidate traversal')

    monkeypatch.setattr(module._TriangleBoxes, 'pairs', candidates)
    result = module.intersection_issues(triangles, cells, np.array([71, 84]))
    assert any(x.code == 'triangle_intersection' and '71' in x.message and '84' in x.message for x in result)

@pytest.mark.parametrize('count', [1, 2, 31, 32, 33, 63, 65, 129])
@pytest.mark.parametrize('layout', ['overlapping', 'sparse', 'touching'])
def test_bvh_leaf_boundaries_preserve_exact_unordered_candidates(count, layout):
    rng = np.random.default_rng(519)
    triangles = rng.random((count, 3, 3))
    if layout == 'sparse':
        triangles += (np.arange(count)*3)[:, None, None]
    elif layout == 'touching':
        # Consecutive boxes touch exactly; all have zero extent along z.
        triangles = np.array([[(i, 0, 0), (i+1, 0, 0), (i, 1, 0)] for i in range(count)], dtype=float)
    boxes = _TriangleBoxes(triangles)
    actual = [tuple(sorted((int(i), int(j)))) for left, right in boxes.pairs() for i, j in zip(left, right)]
    expected = {(i, j) for i in range(count) for j in range(i+1, count)
                if np.all(boxes.low[i] <= boxes.high[j]) and np.all(boxes.low[j] <= boxes.high[i])}
    assert len(actual) == len(set(actual))
    assert set(actual) == expected
