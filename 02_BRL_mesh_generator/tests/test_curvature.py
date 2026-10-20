from dataclasses import replace
import math
from types import SimpleNamespace

import gmsh
import numpy as np
import pytest

from brl_mesh import curvature as curve
from brl_mesh.cad import build_geometry
from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model, publish, run
from brl_mesh.errors import ConfigurationError, MeshBlocked
from brl_mesh.improvement import _acceptable
from brl_mesh.inspection import inspect_mesh
from brl_mesh.model import snapshot
from brl_mesh.sizing import apply_sizing
from brl_mesh.sizing_config import Curvature
from tests.curvature_support import write_curved


def config_for(tmp_path, kind='cylinder', **curvature):
    path = write_curved(tmp_path/(kind+'.brep'), kind)
    return Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'cad', 'path': str(path), 'sheet_normal': 1},
        'mesh': {'target_size': .7, 'curvature': {'absolute_tolerance': .02} | curvature},
        'output_dir': str(tmp_path/'outputs')})


@pytest.mark.parametrize('kind', ['sphere', 'disk', 'cylinder', 'fillet', 'ogive'])
def test_real_curved_geometry_feedback_and_current_deviation(tmp_path, kind):
    config = config_for(tmp_path, kind, absolute_tolerance=.01 if kind == 'fillet' else .02)
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        inspection = inspect_mesh(mesh, scene.contract)
        inspection.require_nonshape_pass()
        plan = scene.curvature
        assert plan.history[-1][1] <= 1+1e-10
        assert inspection.deviation_ratio_max <= 1+1e-10
        if kind in ('sphere', 'fillet'):
            assert plan.iterations > 0  # Actual measurement drives regeneration.
        if kind == 'sphere':
            assert any(dim == 1 for dim, _ in plan.tolerances)  # Seam retained.
            xyz = mesh.triangles()
            center_errors = 1-np.linalg.norm(xyz.mean(axis=1), axis=1)
            assert center_errors.max() <= .02*(1+1e-10)
            assert np.linalg.norm(mesh.coordinates, axis=1) == pytest.approx(1)
            assert plan.size(2, 1, [0, 0, 1]) == pytest.approx(plan.size(2, 1, [1, 0, 0]))
        if kind == 'ogive':
            face = next(iter(plan.faces))
            assert plan.size(2, face, [0, 0, 3]) < plan.size(2, face, [1, 0, 0])
            xyz = mesh.triangles()
            edges = np.linalg.norm(xyz[:, [1, 2, 0]]-xyz, axis=2).mean(axis=1)
            z = xyz[:, :, 2].mean(axis=1)
            assert np.median(edges[z > 2.7]) < np.median(edges[z < .5])
        assert not gmsh.view.getTags().size


def test_more_than_200_circle_requirement_reaches_actual_boundary(tmp_path):
    config = config_for(tmp_path, 'large_disk', absolute_tolerance=.001)
    config = replace(config, target_size=1)
    with mesh_model(config) as scene:
        plan = scene.curvature
        assert curve.circle_divisions(10, .001) == 223
        assert curve.circle_divisions(100, .001) == 703
        boundary = next(iter(plan.curves))
        assert plan.requests[1, boundary].circle_divisions == 223
        ids = gmsh.model.mesh.getElementsByType(1, boundary)[0]
        assert len(ids) >= 223
        assert gmsh.option.getNumber('Mesh.MeshSizeFromCurvature') == 0
        mesh = snapshot(scene.membership)
        points = mesh.coordinates[np.searchsorted(mesh.node_ids, np.asarray(
            gmsh.model.mesh.getElementsByType(1, boundary)[1]).reshape(-1, 2))]
        # Independent exact circle sagitta at each chord midpoint.
        assert np.max(10-np.linalg.norm(points.mean(axis=1), axis=1)) <= .001
        inspection = inspect_mesh(mesh, scene.contract)
        inspection.require_pass()
        result = publish(mesh, config, scene)
        assert {p.name for p in result.nas_path.parent.iterdir()} == {'mesh.nas'}


def test_iteration_limit_blocks_instead_of_accepting_initial_estimate(tmp_path):
    config = config_for(tmp_path, 'sphere', max_iterations=0)
    with pytest.raises(MeshBlocked, match='curvature_iteration_limit'):
        run(config)
    assert not config.output_dir.exists()
    assert not gmsh.isInitialized()


def test_minimum_size_conflict_is_not_silently_clamped(tmp_path):
    config = config_for(tmp_path, 'sphere')
    config = replace(config, sizing=replace(config.sizing, minimum_size=.5))
    with pytest.raises(MeshBlocked, match='curvature_minimum_conflict'):
        run(config)
    assert not config.output_dir.exists()


def test_projection_failure_or_trim_failure_never_passes(tmp_path, monkeypatch):
    config = config_for(tmp_path, 'disk')
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        real = gmsh.model.getClosestPoint
        monkeypatch.setattr(gmsh.model, 'getClosestPoint', lambda *a, **kw: ([float('nan')], []))
        with pytest.raises(MeshBlocked, match='projection_incomplete'):
            scene.curvature.measure(mesh)
        monkeypatch.setattr(gmsh.model, 'getClosestPoint', real)
        monkeypatch.setattr(gmsh.model, 'isInside', lambda *a, **kw: 0)
        with pytest.raises(MeshBlocked, match='projection_trim_incomplete'):
            scene.curvature.measure(mesh)
    assert not config.output_dir.exists()


def test_changed_current_mesh_fails_absolute_gate_at_publish(tmp_path):
    config = config_for(tmp_path, 'cylinder')
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        ids, xyz, _ = gmsh.model.mesh.getNodes(2, 1)
        xyz = np.asarray(xyz).reshape(-1, 3)
        node = int(ids[np.argmin(np.linalg.norm(xyz-[1, 0, 1], axis=1))])
        old = mesh.coordinates[np.searchsorted(mesh.node_ids, node)]
        neighbors = np.unique(mesh.connectivity[np.any(mesh.connectivity == node, axis=1)])
        points = mesh.coordinates[np.searchsorted(mesh.node_ids, neighbors)]
        angles = np.arctan2(points[:, 1], points[:, 0])-np.arctan2(old[1], old[0])
        angles = (angles+np.pi)%(2*np.pi)-np.pi
        moved = .2*old+.8*points[np.argmax(np.abs(angles))]
        moved[:2] /= np.linalg.norm(moved[:2])  # Node remains exactly on the cylinder CAD.
        gmsh.model.mesh.setNode(node, moved, gmsh.model.getParametrization(2, 1, moved))
        current = snapshot(scene.membership)
        inspection = inspect_mesh(current, scene.contract)
        assert [issue.code for issue in inspection.issues] == ['cad_deviation']
        with pytest.raises(MeshBlocked, match='cad_deviation'):
            publish(current, config, scene)
    assert not config.output_dir.exists()


def test_verified_deviation_reuse_tracks_boundary_mesh_and_cad(tmp_path, monkeypatch):
    config = config_for(tmp_path, 'disk')
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        plan, calls = scene.curvature, []
        original = plan.measure
        def measured(*args, **kwargs):
            calls.append(True)
            return original(*args, **kwargs)
        monkeypatch.setattr(plan, 'measure', measured)
        assert plan.deviation_ratio(mesh) <= 1
        assert not calls
        # Surface triangles alone do not describe all inputs to curve deviation.
        edge = min(plan.curves)
        ids = gmsh.model.mesh.getElementsByType(1, edge)[0]
        gmsh.model.mesh.removeElements(1, edge, list(map(int, ids)))
        with pytest.raises(MeshBlocked, match='deviation_incomplete'):
            plan.deviation_ratio(mesh)
        assert len(calls) == 1
        key = curve._measurement_key(mesh)
        gmsh.model.occ.translate(gmsh.model.getEntities(2), 0, 0, 1)
        gmsh.model.occ.synchronize()
        assert curve._measurement_key(mesh) != key


def test_local_radius_and_relative_feature_scales_do_not_use_global_bbox(tmp_path):
    config = config_for(tmp_path, 'mixed_curvature', relative_tolerance=.001)
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        build_geometry(config)
        plan = curve.CurvaturePlan(config, apply_sizing(config))
        assert plan.tolerances[2, 1] == pytest.approx(math.sqrt(4*math.pi)*.001)
        assert plan.tolerances[2, 2] == pytest.approx(math.sqrt(16*math.pi)*.001)
        first = plan.size(2, 1, [1, 0, 0])
        second = plan.size(2, 2, [12, 0, 0])
        assert second/first == pytest.approx(2)
        # Translation enlarges global bbox but changes neither local radius nor
        # the local feature's area-based relative tolerance.
        gmsh.model.occ.translate([(3, 2)], 1000, 0, 0)
        gmsh.model.occ.synchronize()
        moved = curve.CurvaturePlan(config, SimpleNamespace(global_size=.7, minimum_size=1e-10))
        assert moved.size(2, 1, [1, 0, 0]) == pytest.approx(first)
    finally:
        gmsh.finalize()


def test_callback_failure_is_recorded_and_callback_is_removed(tmp_path, monkeypatch):
    config = config_for(tmp_path, 'disk')
    real = gmsh.model.mesh.removeSizeCallback
    calls = []
    def remove():
        calls.append(True)
        real()
    monkeypatch.setattr(gmsh.model.mesh, 'removeSizeCallback', remove)
    monkeypatch.setattr(curve.CurvaturePlan, 'target', lambda *a: (_ for _ in ()).throw(ValueError('bad CAD')))
    with pytest.raises(MeshBlocked, match='curvature_callback_incomplete.*bad CAD'):
        run(config)
    assert calls == [True]
    assert not gmsh.isInitialized()


@pytest.mark.parametrize('invalid', ['directions', 'curvatures'])
def test_invalid_principal_curvature_api_is_not_consumed(tmp_path, monkeypatch, invalid):
    config = config_for(tmp_path, 'sphere')
    def broken(*args):
        return ([float('nan') if invalid == 'curvatures' else 1], [1], [0, 0, 0], [0, 0, 0])
    monkeypatch.setattr(gmsh.model, 'getPrincipalCurvatures', broken)
    with pytest.raises(MeshBlocked, match='curvature_callback_incomplete'):
        run(config)
    assert not config.output_dir.exists()


@pytest.mark.parametrize('changes', [{}, {'absolute_tolerance': 0}, {'absolute_tolerance': True},
    {'absolute_tolerance': float('nan')}, {'relative_tolerance': 1}, {'absolute_tolerance': .01, 'max_iterations': True},
    {'absolute_tolerance': .01, 'sampling_nodes': 2}, {'absolute_tolerance': .01, 'verification_nodes': 9},
    {'absolute_tolerance': .01, 'points_per_circle': 200}])
def test_curvature_schema_rejects_invalid_requests(config, changes):
    value = config.to_dict()
    value['mesh']['curvature'] = changes
    with pytest.raises(ConfigurationError):
        Configuration.from_dict(value)


def test_curvature_disabled_preserves_plate_bytes_and_flat_case(config):
    expected = run(config).nas_path.read_bytes()
    enabled = replace(config, sizing=replace(config.sizing, curvature=Curvature(absolute_tolerance=.001)))
    assert run(enabled).nas_path.read_bytes() == expected
    with mesh_model(enabled) as scene:
        inspection = inspect_mesh(snapshot(scene.membership), scene.contract)
        weaker = replace(inspection, icn={e: v*.99 for e, v in inspection.icn.items()}, deviation_ratio_max=.2)
        candidate = replace(inspection, deviation_ratio_max=.2)
        assert _acceptable(weaker, candidate)
        assert not _acceptable(weaker, replace(candidate, deviation_ratio_max=.3))
