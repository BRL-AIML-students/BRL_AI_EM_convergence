from types import SimpleNamespace

import gmsh
import numpy as np
import pytest

from brl_mesh import curvature as curve
from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model
from brl_mesh.errors import MeshBlocked
from brl_mesh.model import snapshot


def pending_plan(monkeypatch, records):
    plan = object.__new__(curve.CurvaturePlan)
    plan.settings = SimpleNamespace(max_iterations=3, feedback='local')
    plan.iterations = 0
    plan.scales = {(1, 10): 1., (2, 1): 1.}
    plan._patches = {}
    plan.verified = None
    deviation = curve.Deviation(((2, 1, 100, .02),), (((2, 1), 2.),))
    plan._feedback = (deviation, object(), tuple(records), ('CAD', 'boundary'))
    monkeypatch.setattr(curve, 'assert_current', lambda mesh: None)
    monkeypatch.setattr(curve, '_measurement_key', lambda mesh: ('CAD', 'boundary'))
    return plan, deviation


def test_overlap_uses_min_within_iteration_and_repeated_feedback_keeps_progress(monkeypatch):
    record = (1, (0., 0., 0.), 2., .5)
    plan, deviation = pending_plan(monkeypatch, [record]*100)
    plan.refine(deviation)
    assert plan._local_scale(1, [0, 0, 0]) == .5
    assert plan._local_scale(1, [1, 0, 0]) == .5  # Full core; half the support radius.
    assert plan._local_scale(1, [1.5, 0, 0]) == pytest.approx(.90625)
    assert plan._local_scale(1, [3, 0, 0]) == 1
    assert plan._local_scale(2, [0, 0, 0]) == 1
    assert 0 < 1-plan._local_scale(1, [1.999, 0, 0]) < 1e-10
    first = [plan._local_scale(1, [x, 0, 0]) for x in (0, .5, 1, 2, 3)]
    plan._feedback = (deviation, object(), (record,), ('CAD', 'boundary'))
    plan.refine(deviation)
    assert plan._local_scale(1, [0, 0, 0]) == .25
    assert all(plan._local_scale(1, [x, 0, 0]) <= old for x, old in zip((0, .5, 1, 2, 3), first))
    assert plan.scales[2, 1] == 1  # No face-wide reduction.
    with pytest.raises(MeshBlocked, match='feedback_incomplete'):
        plan.refine(deviation)


@pytest.mark.parametrize('radius', [0, np.nan])
def test_invalid_local_support_is_explicitly_blocked(monkeypatch, radius):
    plan, deviation = pending_plan(monkeypatch, [(1, (0., 0., 0.), radius, .5)])
    with pytest.raises(MeshBlocked, match='feedback_incomplete'):
        plan.refine(deviation)


def test_boundary_target_consumes_face_local_request(monkeypatch):
    plan, deviation = pending_plan(monkeypatch, [(1, (0., 0., 0.), 2., .5)])
    plan.refine(deviation)
    plan.cap = 1.
    plan.curve_faces = {10: (1, 2)}
    plan.point_curves = {20: (10,)}
    plan.size = lambda dim, tag, point: plan._local_scale(tag, point) if dim == 2 else 1.
    assert plan.target(1, 10, [0, 0, 0]) == .5
    assert plan.target(0, 20, [0, 0, 0]) == .5
    assert plan.target(1, 10, [3, 0, 0]) == 1.


def test_entity_mode_keeps_surface_wide_feedback_without_local_regions(monkeypatch):
    plan, deviation = pending_plan(monkeypatch, [])
    plan.settings.feedback = 'entity'
    plan.refine(deviation)
    assert plan.scales[2, 1] == pytest.approx(.7/np.sqrt(2))
    assert plan._patches == {} and plan._feedback is None


def test_local_request_does_not_clamp_below_minimum(monkeypatch):
    plan, deviation = pending_plan(monkeypatch, [(1, (0., 0., 0.), 2., .25)])
    plan.refine(deviation)
    plan.tolerances = {(2, 1): .01}
    plan.cap, plan.floor, plan.requests = 1., .2, {}
    monkeypatch.setattr(gmsh.model, 'getParametrization', lambda *args: [0, 0])
    monkeypatch.setattr(gmsh.model, 'getPrincipalCurvatures',
                        lambda *args: ([1], [1], [1, 0, 0], [0, 1, 0]))
    with pytest.raises(MeshBlocked, match='curvature_minimum_conflict'):
        plan.size(2, 1, [0, 0, 0])


@pytest.mark.parametrize('budget', [31, 24320])
def test_final_grid_feedback_owns_final_sample_seeds_and_is_consumed_once(square, monkeypatch, budget):
    from brl_mesh import curvature_sampling
    monkeypatch.setattr(curvature_sampling, '_SAMPLE_POINTS', budget)
    plan, _ = pending_plan(monkeypatch, [])
    plan.settings = SimpleNamespace(max_iterations=3, verification_nodes=19, feedback='local')
    plan.tolerances = {(2, 7): .01}
    plan.scales = {(2, 7): 1.}
    def project(dim, tag, points, *, audit=None):
        projected = points.copy()
        projected[np.isclose(points[:, 0], 1/18, rtol=0, atol=1e-15), 2] += .02
        if audit is not None:
            audit.observe(points, projected, 0.)
        return projected, np.zeros((len(points), 2))
    monkeypatch.setattr(curve, 'project', project)
    coarse = plan.measure(square, sampling=10)
    assert coarse.ratio == 0 and plan._feedback is None
    final = plan.measure(square)
    assert final.ratio == 2 and plan._feedback[0] is final
    assert plan.verified[1] == 2
    with pytest.raises(MeshBlocked, match='feedback_incomplete'):
        plan.refine(coarse)
    plan.refine(final)
    assert plan._feedback is None and plan.verified is None
    centers = plan._patches[7][0][0]
    np.testing.assert_allclose(centers[:, 0], 1/18, rtol=0, atol=1e-15)
    np.testing.assert_allclose(plan._patches[7][0][1], 4*np.sqrt(2))
    with pytest.raises(MeshBlocked, match='feedback_incomplete'):
        plan.refine(final)


def test_cad_or_boundary_key_change_blocks_feedback_without_partial_mutation(monkeypatch):
    plan, deviation = pending_plan(monkeypatch, [(1, (0., 0., 0.), 2., .5)])
    monkeypatch.setattr(curve, '_measurement_key', lambda mesh: ('CAD', 'changed curve connectivity'))
    with pytest.raises(MeshBlocked, match='feedback_incomplete.*CAD/경계'):
        plan.refine(deviation)
    assert not plan._patches and plan.iterations == 0


def test_missing_surface_feedback_does_not_partially_install_valid_regions(monkeypatch):
    plan, _ = pending_plan(monkeypatch, [(1, (0., 0., 0.), 2., .5)])
    deviation = curve.Deviation((), (((2, 1), 2.), ((2, 2), 2.)))
    plan.scales[2, 2] = 1.
    plan._feedback = (deviation, object(), ((1, (0., 0., 0.), 2., .5),), ('CAD', 'boundary'))
    with pytest.raises(MeshBlocked, match='feedback_incomplete'):
        plan.refine(deviation)
    assert not plan._patches and plan.iterations == 0


def test_boundary_connectivity_change_invalidates_pending_local_feedback(tmp_path):
    from tests.test_curvature import config_for
    config = config_for(tmp_path, 'disk')
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        plan = scene.curvature
        deviation = curve.Deviation((), (((2, 1), 2.),))
        plan._feedback = (deviation, mesh, ((1, (0., 0., 0.), .2, .5),), curve._measurement_key(mesh))
        before = len(plan._patches.get(1, ()))
        edge = min(plan.curves)
        gmsh.model.mesh.reverse([(1, edge)])
        # Surface nodes/connectivity/coordinates remain identical.
        current = snapshot(scene.membership)
        assert mesh.same_structure(current)
        np.testing.assert_array_equal(mesh.coordinates, current.coordinates)
        with pytest.raises(MeshBlocked, match='feedback_incomplete.*CAD/경계'):
            plan.refine(deviation)
        assert len(plan._patches.get(1, ())) == before


def write_local_bend(path):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        occ = gmsh.model.occ
        points = [occ.addPoint(x, y, z) for y in (0, 3)
                  for x, z in enumerate([0, 0, 0, 0, 0, 0, 0, .5, 2])]
        face = occ.addBSplineSurface(points, 9, degreeU=3, degreeV=1)
        occ.synchronize()
        assert gmsh.model.getEntities(2) == [(2, face)]
        maximum, minimum, _, _ = gmsh.model.getPrincipalCurvatures(face, [2, .5, 5.25, .5])
        assert abs(maximum[0]) < 1e-12 and abs(maximum[1]) > .5
        assert np.isfinite(gmsh.model.getNormal(face, [2, .5, 5.25, .5])).all()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def test_single_face_local_bend_feedback_and_full_contract(tmp_path):
    path = write_local_bend(tmp_path/'local-bend.brep')
    config = Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'cad', 'path': str(path), 'sheet_normal': 1},
        'mesh': {'target_size': .8, 'curvature': {'absolute_tolerance': .01, 'feedback': 'local'}},
        'output_dir': str(tmp_path/'output')})
    with mesh_model(config) as scene:
        from brl_mesh.inspection import inspect_mesh
        mesh = snapshot(scene.membership)
        plan = scene.curvature
        assert plan.history[0][1] > 1+1e-10
        assert plan.history[-1][1] <= 1+1e-10
        assert plan._patches
        assert plan.scales[2, 1] == 1
        assert plan._local_scale(1, [0, 1.5, 0]) == 1
        assert plan._local_scale(1, [6.4, 1.5, .25]) < 1
        inspect_mesh(mesh, scene.contract).require_pass()
