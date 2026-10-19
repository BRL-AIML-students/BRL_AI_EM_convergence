from dataclasses import replace

import numpy as np
import pytest

from brl_mesh.topology import BoundaryIntent, inspect_topology
from tests.support import exposed_edges, mesh_from


def codes(result):
    return {x.code for x in result.issues}


def junction(height=0):
    return mesh_from([(0, 0, 0), (2, 0, 0), (0, 2, 0), (1, height, 0), (1, -1, 0), (2, -1, 0)],
                     [(1, 2, 3), (4, 5, 6)])


def test_intended_open_boundary_and_missing_intent(square):
    assert not inspect_topology(square, BoundaryIntent(exposed_edges(square), 1)).issues
    missing = inspect_topology(square, BoundaryIntent(None, 1))
    assert any(x.code == 'boundary_intent_missing' and x.status == 'incomplete' for x in missing.issues)


@pytest.mark.parametrize('scale', [1, .001])
def test_t_junction_is_detected_even_if_boundaries_are_allowed(scale):
    mesh = junction()
    mesh = replace(mesh, coordinates=mesh.coordinates * scale)
    assert 't_junction' in codes(inspect_topology(mesh, BoundaryIntent(exposed_edges(mesh), 2)))


def test_ambiguous_near_edge_and_budget_are_incomplete():
    mesh = junction(1e-11)
    result = inspect_topology(mesh, BoundaryIntent(exposed_edges(mesh), 2))
    assert any(x.code == 'ambiguous_proximity' and x.status == 'incomplete' for x in result.issues)
    budget = inspect_topology(mesh, BoundaryIntent(exposed_edges(mesh), 2, max_candidate_tests=1))
    assert any(x.code == 'topology_budget' and x.status == 'incomplete' for x in budget.issues)


def test_nonmanifold_edge_and_vertex():
    edge_mesh = mesh_from([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (.5, 0, 1)],
                          [(1, 2, 3), (2, 1, 4), (1, 2, 5)])
    assert 'nonmanifold_edge' in codes(inspect_topology(edge_mesh, BoundaryIntent(exposed_edges(edge_mesh), 1)))
    vertex_mesh = mesh_from([(0, 0, 0), (1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)],
                            [(1, 2, 3), (1, 4, 5)])
    assert 'nonmanifold_vertex' in codes(inspect_topology(vertex_mesh, BoundaryIntent(exposed_edges(vertex_mesh), 2)))


def test_shared_edge_winding_is_independent_of_shape(square):
    mesh = replace(square, connectivity=np.array([[10, 20, 30], [10, 40, 30]]))
    assert 'inconsistent_winding' in codes(inspect_topology(mesh, BoundaryIntent(exposed_edges(mesh), 1)))


def test_intended_separation_is_preserved_without_welding():
    gap = 1e-11
    mesh = mesh_from([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, gap), (1, 0, gap), (0, 1, gap)],
                     [(1, 2, 3), (4, 5, 6)], [1, 2])
    before = mesh.coordinates.copy()
    allowed = BoundaryIntent(exposed_edges(mesh), 2, frozenset({(1, 2)}), protected_gap=gap)
    assert not inspect_topology(mesh, allowed).issues
    assert np.array_equal(mesh.coordinates, before)
    conflict = inspect_topology(mesh, replace(allowed, separated_surfaces=frozenset()))
    assert any(x.code == 'gap_tolerance_conflict' and x.status == 'incomplete' for x in conflict.issues)


def test_expected_components_and_boundary_are_checked(square):
    result = inspect_topology(square, BoundaryIntent(frozenset(), 2))
    assert {'unexpected_components', 'unexpected_boundary'} <= codes(result)


@pytest.mark.parametrize('change', [{'max_candidate_tests': 0}, {'relative_tolerance': float('nan')}, {'protected_gap': 0}])
def test_invalid_audit_settings_are_incomplete(square, change):
    result = inspect_topology(square, replace(BoundaryIntent(exposed_edges(square), 1), **change))
    assert any(x.status == 'incomplete' for x in result.issues)
