from dataclasses import replace
from types import SimpleNamespace

import gmsh
import numpy as np
import pytest

from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model
from brl_mesh.features import Feature
from brl_mesh.model import snapshot
from brl_mesh.sizing import AppliedFeature, SizingPlan


def original_ratio(plan, mesh):
    xyz = mesh.triangles()
    start = xyz.reshape(-1, 3)
    end = xyz[:, [1, 2, 0]].reshape(-1, 3)
    midpoint = (start+end)/2
    return float(np.max(np.linalg.norm(end-start, axis=1)/
                        plan.nominal_sizes(midpoint, np.repeat(mesh.surface_tags, 3))))


@pytest.mark.parametrize('kind', ['manual', 'width'])
def test_real_curve_audit_matches_original_and_projects_fewer_points(tmp_path, monkeypatch, kind):
    local = ({'curves': [{'entity': 1, 'size': .2}]} if kind == 'manual' else
             {'widths': {'enabled': True}})
    config = Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'plate', 'length': 4, 'width': .6},
        'mesh': {'target_size': 1, 'local': local}, 'output_dir': str(tmp_path/'output')})
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        counts = []
        project = gmsh.model.getClosestPoint
        def counted(dim, tag, coordinates):
            counts.append(len(coordinates)//3)
            return project(dim, tag, coordinates)
        monkeypatch.setattr(gmsh.model, 'getClosestPoint', counted)
        expected = original_ratio(scene.sizing, mesh)
        original_count = sum(counts)
        counts.clear()
        assert scene.sizing.local_edge_ratio(mesh) == expected
        if kind == 'width':
            assert sum(counts) < original_count
        else:
            assert sum(counts) == original_count  # Avoid sorting overhead for a single CAD curve.


def plan_with_curve():
    feature = Feature('test', (1,), None, .1, curves=(1, 2, 3, 4), surface=7)
    return SizingPlan(1., .1, (), (AppliedFeature(feature, 0., 1.),), (), None, ())


def test_same_midpoint_on_different_surfaces_keeps_restrict_targets(square, monkeypatch):
    mesh = replace(square, surface_tags=np.array([7, 8]))
    points, surfaces = [], []
    def targets(self, xyz, tags):
        points.extend(xyz.copy())
        surfaces.extend(tags.copy())
        return np.where(tags == 7, .1, .7)
    monkeypatch.setattr(SizingPlan, 'nominal_sizes', targets)
    plan = plan_with_curve()
    expected = original_ratio(plan, mesh)
    points.clear(); surfaces.clear()
    assert plan.local_edge_ratio(mesh) == expected
    diagonal = [(tag, point) for tag, point in zip(surfaces, points) if np.array_equal(point, [.5, .5, 0])]
    assert {tag for tag, _ in diagonal} == {7, 8}


def test_bounded_audit_keeps_original_midpoints_and_later_batch_maximum(monkeypatch):
    triangle = np.array([[1e12, 0., 0.], [1e12+1., 0., 0.], [1e12, 1., 0.]])
    triangles = np.repeat(triangle[None], 4100, axis=0)
    triangles[-1, 1:, 1] += 10.
    mesh = SimpleNamespace(triangles=lambda: triangles, surface_tags=np.full(4100, 7))
    calls = []
    def targets(self, xyz, tags):
        calls.append(xyz.copy())
        return np.full(len(xyz), .3)
    monkeypatch.setattr(SizingPlan, 'nominal_sizes', targets)
    plan = plan_with_curve()
    expected = original_ratio(plan, mesh)
    original_points = calls.pop()
    assert plan.local_edge_ratio(mesh) == expected
    assert len(calls) > 1
    for batch in calls:
        assert len(batch) <= 3*4096
        assert len(batch) == len(np.unique(batch, axis=0))
        assert all(np.any(np.all(original_points == point, axis=1)) for point in batch)
