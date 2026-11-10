from dataclasses import replace
from pathlib import Path

import gmsh
import numpy as np
import pytest

from brl_mesh.config import Configuration
from brl_mesh.development_metrics import _size_compliance, measure_development_metrics
from brl_mesh.engine import mesh_model, prepare_generated


def test_efficiency_index_is_reciprocal_and_preserves_direction():
    assert _size_compliance(np.ones(2))['efficiency_index'] == 1
    result = _size_compliance(np.array([.5, 2, 2]))
    assert result['efficiency_index'] == pytest.approx(np.exp(-.5))
    assert result['below_band'] == pytest.approx(1 / 3)
    assert result['above_band'] == pytest.approx(2 / 3)


def test_box_regions_and_edge_coverage():
    config = Configuration.from_dict({
        'schema_version': 1, 'geometry': {'kind': 'plate', 'length': 10, 'width': 10},
        'mesh': {'target_size': 1, 'local': {'boxes': [{'bounds': [4, 4, -.1, 6, 6, .1], 'size': .3}]}},
    })
    with mesh_model(config) as scene:
        scene, prepared = prepare_generated(scene, config)
        mesh = prepared.mesh
        view_tags = gmsh.view.getTags().copy()
        visibility = gmsh.model.mesh.getVisibility(mesh.element_ids)
        result = measure_development_metrics(mesh, scene)
        edges = result['edges']
        by_region = edges['by_midpoint_region']
        assert set(by_region) == {'core', 'transition', 'global'}
        assert by_region['core']['length']['p50'] < by_region['transition']['length']['p50']
        assert by_region['transition']['length']['p50'] < by_region['global']['length']['p50']
        boundary = len(prepared.inspection.topology.boundary_edges)
        assert edges['length']['count'] == (3 * len(mesh.element_ids) + boundary) // 2
        assert edges['normalized_interior']['count'] == edges['length']['count'] - boundary
        assert edges['transition']['all']['max'] == pytest.approx(
            prepared.inspection.topology.adjacent_size_ratio_max)
        assert next(iter(result['facets_by_face'].values()))['normal_degrees']['max'] < 1e-10
        assert np.array_equal(gmsh.view.getTags(), view_tags)
        assert np.array_equal(gmsh.model.mesh.getVisibility(mesh.element_ids), visibility)


def test_sphere_facet_normal_matches_analytic_cad_normal():
    config = Configuration.load(Path(__file__).resolve().parents[1] / 'examples' / 'sphere.json')
    with mesh_model(config) as scene:
        scene, prepared = prepare_generated(scene, config)
        mesh = prepared.mesh
        requests = dict(scene.curvature.requests)
        result = measure_development_metrics(mesh, scene)
        assert scene.curvature.requests == requests
        assert 'curvature' in result['edges']['by_midpoint_region']
        face = next(iter(result['facets_by_face'].values()))
        assert face['unavailable_normal_samples'] == 0
        worst = face['normal_degrees']
        triangle = mesh.triangles()[np.searchsorted(mesh.element_ids, worst['element_id'])]
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        radial = np.array(worst['sample_point'])
        angle = np.degrees(np.arctan2(np.linalg.norm(np.cross(normal, radial)), abs(np.dot(normal, radial))))
        assert worst['max'] == pytest.approx(angle, abs=1e-9)
        distance = face['distance']
        assert distance['max'] == pytest.approx(1 - np.linalg.norm(distance['sample_point']), abs=1e-9)


def test_gmsh_gamma_matches_twice_inradius_over_circumradius(config):
    with mesh_model(config) as scene:
        scene, prepared = prepare_generated(scene, config)
        mesh = prepared.mesh
        xyz = mesh.triangles()
        a, b, c = np.linalg.norm(np.roll(xyz, -1, axis=1) - xyz, axis=2).T
        area = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1) / 2
        expected = 16 * area**2 / ((a + b + c) * a * b * c)
        assert gmsh.model.mesh.getElementQualities(mesh.element_ids, 'gamma') == pytest.approx(expected)
        result = measure_development_metrics(mesh, scene)['radius_ratio']
        assert result['min'] == pytest.approx(expected.min())
        assert result['p05'] == pytest.approx(np.percentile(expected, 5))
        assert result['minimum_element_id'] in mesh.element_ids
