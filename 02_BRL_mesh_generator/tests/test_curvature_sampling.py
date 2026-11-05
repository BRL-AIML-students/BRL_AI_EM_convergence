"""Preserve the full grid, maxima and first feedback seeds across memory tiles."""
import numpy as np
import pytest

from brl_mesh import curvature_sampling as sampling
from brl_mesh.errors import MeshBlocked


def original_weights(dimension, n):
    return (np.linspace(0, 1, n) if dimension == 1 else
            np.array([(1-i/(n-1)-j/(n-1), i/(n-1), j/(n-1))
                      for i in range(n) for j in range(n-i)]))


@pytest.mark.parametrize('dimension', [1, 2])
@pytest.mark.parametrize('n', [3, 10, 19, 37])
def test_tiled_weights_keep_original_values_and_order(monkeypatch, dimension, n):
    monkeypatch.setattr(sampling, '_SAMPLE_POINTS', 31)
    parts = list(sampling._weights(dimension, n))
    assert all(len(part) <= 31 for part in parts)
    np.testing.assert_array_equal(np.concatenate(parts), original_weights(dimension, n))


@pytest.mark.parametrize('dimension', [1, 2])
@pytest.mark.parametrize('budget', [31, 997, 24320])
@pytest.mark.parametrize('constant', [False, True])
def test_complete_grid_maxima_and_first_seed_are_independent_of_tiles(monkeypatch, dimension, budget, constant):
    monkeypatch.setattr(sampling, '_SAMPLE_POINTS', budget)
    xyz = np.array([[(0., 0, 0), (1, 0, 0), (0, 1, 0)],
                    [(2., 0, 0), (3, 0, 0), (2, 1, 0)],
                    [(0., 2, 0), (1, 2, 0), (0, 3, 0)]])[:, :dimension+1]

    def project(dim, tag, points):
        result = points.copy()
        result[:, 2] = .125 if constant else np.abs(np.sin(points[:, 0]*3)+np.cos(points[:, 1]*4))
        return result, None

    weights = original_weights(dimension, 19)
    points = (np.einsum('ij,ejk->eik', weights, xyz) if dimension == 2 else
              xyz[:, :1]+weights[None, :, None]*(xyz[:, 1:]-xyz[:, :1]))
    projected, _ = project(dimension, 7, points.reshape(-1, 3))
    projected = projected.reshape(points.shape)
    distances = np.linalg.norm(projected-points, axis=2)
    expected_maxima = distances.max(axis=1)
    expected_seeds = projected[np.arange(len(xyz)), distances.argmax(axis=1)]
    batches = list(sampling.deviation_batches(dimension, 7, xyz, 19, project, seeds=True))
    np.testing.assert_array_equal(np.concatenate([r[1] for r in batches]), expected_maxima)
    np.testing.assert_array_equal(np.concatenate([r[2] for r in batches]), expected_seeds)


def test_1000_node_grid_checks_every_sample_in_small_calls():
    xyz = np.array([[(0., 0, 0), (1, 0, 0), (0, 1, 0)]])
    calls = []

    def project(dim, tag, points):
        calls.append(len(points))
        result = points.copy()
        result[:, 2] = .125
        return result, None

    batches = list(sampling.deviation_batches(2, 7, xyz, 1000, project, seeds=True))
    assert sum(calls) == 1000*1001//2
    assert max(calls) <= sampling._SAMPLE_POINTS
    assert len(calls) > 1
    np.testing.assert_array_equal(batches[0][1], [.125])
    np.testing.assert_array_equal(batches[0][2], [[0., 0., .125]])


def test_nonfinite_sample_distance_blocks():
    xyz = np.array([[(0., 0, 0), (1, 0, 0), (0, 1, 0)]])
    with pytest.raises(MeshBlocked, match='유한하지'):
        list(sampling.deviation_batches(2, 7, xyz, 3,
             lambda dim, tag, points: (np.full_like(points, np.nan), None)))


@pytest.mark.parametrize('origins', [(0., 1e6), (-5e5, 5e5), (1e6, 1e6+1)])
def test_projection_round_trip_uses_original_group_scale_across_tiles(monkeypatch, origins):
    from brl_mesh import curvature as curve
    import gmsh

    def closest(dim, tag, points):
        points = np.asarray(points).reshape(-1, 3)
        return points.ravel(), points[:, :2].ravel()

    def value(dim, tag, parameters):
        uv = np.asarray(parameters).reshape(-1, 2)
        return np.column_stack((uv, np.full(len(uv), 2e-8))).ravel()

    monkeypatch.setattr(gmsh.model, 'getClosestPoint', closest)
    monkeypatch.setattr(gmsh.model, 'getValue', value)
    monkeypatch.setattr(gmsh.model, 'isInside', lambda dim, tag, uv, **kw: len(uv)//2)
    monkeypatch.setattr(gmsh.option, 'getNumber', lambda name: 1e-8)
    xyz = np.tile(np.array([[(0., 0, 0), (1, 0, 0), (0, 1, 0)]]), (129, 1, 1))
    xyz[:127, :, 0] += origins[0]
    xyz[127, :, 0] += origins[1]
    weights = original_weights(2, 20)
    # The original full logical group accepts, while the following small group
    # must still reject. Neither smaller tiles nor the full mesh define scale.
    curve.project(2, 7, np.einsum('ij,ejk->eik', weights, xyz[:128]).reshape(-1, 3))
    with pytest.raises(MeshBlocked, match='projection_incomplete'):
        curve.project(2, 7, np.einsum('ij,ejk->eik', weights, xyz[128:]).reshape(-1, 3))
    stream = sampling.deviation_batches(2, 7, xyz, 20, curve.project, audit_factory=curve._ProjectionAudit)
    start, maxima, _ = next(stream)
    assert start == 0 and len(maxima) == 128
    with pytest.raises(MeshBlocked, match='projection_incomplete'):
        next(stream)


def test_projection_group_keeps_initial_and_trim_round_trip_gates_separate(monkeypatch):
    from brl_mesh import curvature as curve
    import gmsh
    monkeypatch.setattr(gmsh.option, 'getNumber', lambda name: 1e-8)
    audit = curve._ProjectionAudit()
    audit.observe(np.array([[-5e5, 0, 0]]), np.array([[-5e5, 0, 0]]), 2e-8)
    audit.observe(np.array([[5e5, 0, 0]]), np.array([[5e5, 0, 0]]), 0.)
    audit.trim_error = 2e-8
    audit.require_pass()
    audit.initial_error = 4e-8
    with pytest.raises(MeshBlocked, match='^projection_incomplete'):
        audit.require_pass()
    audit.initial_error = 0.
    audit.trim_error = 4e-8
    with pytest.raises(MeshBlocked, match='^projection_trim_incomplete'):
        audit.require_pass()


def test_trim_replacement_round_trip_is_recorded_before_group_gate(monkeypatch):
    from brl_mesh import curvature as curve
    import gmsh
    state = {'trim': False}

    def closest(dim, tag, coordinates):
        points = np.asarray(coordinates).reshape(-1, 3).copy()
        if dim == 2:
            state['trim'] = False
            return points.ravel(), points[:, :2].ravel()
        points[:, 1:] = 0
        return points.ravel(), points[:, 0]

    def parameters(dim, tag, coordinates):
        points = np.asarray(coordinates).reshape(-1, 3)
        if dim == 2:
            state['trim'] = True
            return points[:, :2].ravel()
        return points[:, 0]

    def value(dim, tag, coordinates):
        if dim == 1:
            x = np.asarray(coordinates).ravel()
            return np.column_stack((x, np.zeros((len(x), 2)))).ravel()
        uv = np.asarray(coordinates).reshape(-1, 2)
        return np.column_stack((uv, np.full(len(uv), 2e-8 if state['trim'] else 0.))).ravel()

    monkeypatch.setattr(gmsh.model, 'getClosestPoint', closest)
    monkeypatch.setattr(gmsh.model, 'getParametrization', parameters)
    monkeypatch.setattr(gmsh.model, 'getParametrizationBounds', lambda *a: ([-1e7], [1e7]))
    monkeypatch.setattr(gmsh.model, 'getValue', value)
    monkeypatch.setattr(gmsh.model, 'isInside',
        lambda dim, tag, uv, **kw: int(np.count_nonzero(np.asarray(uv).reshape(-1, 2)[:, 1] == 0)))
    monkeypatch.setattr(gmsh.model, 'getBoundary', lambda *a, **kw: [(1, 10)])
    monkeypatch.setattr(gmsh.model.occ, 'getMass', lambda *a: 1.)
    monkeypatch.setattr(gmsh.option, 'getNumber', lambda name: 1e-8)
    points = np.array([[0., 1., 0.]])
    with pytest.raises(MeshBlocked, match='^projection_trim_incomplete'):
        curve.project(2, 7, points)
    audit = curve._ProjectionAudit()
    result, _ = curve.project(2, 7, points, audit=audit)
    np.testing.assert_array_equal(result, [[0., 0., 0.]])
    assert audit.initial_error == 0 and audit.trim_error == 2e-8
    with pytest.raises(MeshBlocked, match='^projection_trim_incomplete'):
        audit.require_pass()
    # A distant sample of this same logical group preserves the old tolerance.
    audit.observe(np.array([[1e6, 0., 0.]]), np.array([[1e6, 0., 0.]]), 0.)
    audit.require_pass()
