from dataclasses import replace

import numpy as np
import pytest

from brl_mesh.checks import check_plate_geometry, check_shape, measure_shape
from brl_mesh.errors import MeshBlocked
from brl_mesh.topology import BoundaryIntent, inspect_topology


def test_valid_square_open_boundary_and_normal(square, config):
    check_plate_geometry(square, config)
    result = check_shape(square)
    assert result.minimum_angle_deg == pytest.approx(45)
    assert result.aspect_ratio_max < 3


@pytest.mark.parametrize('damage', ['missing', 'duplicate_id', 'duplicate_triangle', 'degenerate', 'nonfinite'])
def test_structural_damage_blocks(square, damage):
    if damage == 'missing':
        conn = square.connectivity.copy()
        conn[0, 0] = 999
        square = replace(square, connectivity=conn)
    elif damage == 'duplicate_id':
        square = replace(square, node_ids=np.array([10, 20, 20, 40]))
    elif damage == 'duplicate_triangle':
        square = replace(square, node_ids=square.node_ids[:3], coordinates=square.coordinates[:3],
                         connectivity=np.array([[10, 20, 30], [10, 20, 30]]))
    elif damage == 'degenerate':
        xyz = square.coordinates.copy()
        xyz[1] = [0.5, 0.5, 0]
        square = replace(square, coordinates=xyz)
    else:
        xyz = square.coordinates.copy()
        xyz[0, 0] = np.nan
        square = replace(square, coordinates=xyz)
    with pytest.raises(MeshBlocked):
        square.validate()


def test_good_shapes_with_disconnected_duplicate_nodes_block(square, config):
    broken = replace(square,
        node_ids=np.array([10, 20, 30, 40, 50, 60]),
        coordinates=np.vstack([square.coordinates, square.coordinates[[0, 2]]]),
        connectivity=np.array([[10, 20, 30], [50, 60, 40]]))
    check_shape(broken)  # Both individual triangles still have good shape.
    result = inspect_topology(broken, BoundaryIntent(frozenset({(10, 20), (20, 30), (30, 40), (10, 40)}), 1))
    assert 'unshared_coincident_nodes' in {x.code for x in result.issues}


def test_geometry_does_not_stand_in_for_normal_direction(square, config):
    broken = replace(square, connectivity=square.connectivity[:, ::-1].copy())
    check_plate_geometry(broken, config)
    check_shape(broken)  # The separate CAD normal inspector must catch this.


def test_skinny_triangle_does_not_bypass_existing_policy(square):
    xyz = square.coordinates.copy()
    xyz[:, 1] *= 0.01
    with pytest.raises(MeshBlocked, match=r'AR=.*최소각=.*위반 요소=2'):
        check_shape(replace(square, coordinates=xyz))


@pytest.mark.parametrize('separation', [10., 1e12])
def test_shape_uses_each_triangle_scale_despite_distant_components(square, separation):
    triangle = np.array([[0., 0., 0.], [1., 0., 0.], [.5, np.sqrt(3)/2, 0.]])
    mesh = replace(square, node_ids=np.arange(1, 7),
                   coordinates=np.vstack([triangle, triangle+[separation, 0, 0]]),
                   connectivity=np.array([[1, 2, 3], [4, 5, 6]]))
    result = check_shape(mesh)
    assert result.aspect_ratios == pytest.approx([1., 1.])
    assert result.minimum_angles == pytest.approx([60., 60.])


def test_local_shape_matches_previous_formula_on_resolved_triangles(square):
    xyz = square.coordinates.copy()
    xyz[2] = [.8, 1.1, .3]
    mesh = replace(square, coordinates=xyz)
    triangles = mesh.triangles()
    triangles = (triangles-triangles[:, :1])/np.max(np.ptp(xyz, axis=0))
    edges = np.stack([triangles[:, (i+1) % 3]-triangles[:, i] for i in range(3)], axis=1)
    lengths = np.linalg.norm(edges, axis=2)
    area = np.linalg.norm(np.cross(triangles[:, 1], triangles[:, 2]), axis=1)/2
    aspect = lengths.max(axis=1)*lengths.sum(axis=1)/(4*np.sqrt(3)*area)
    angles = []
    for i in range(3):
        a = triangles[:, (i+1) % 3]-triangles[:, i]
        b = triangles[:, (i+2) % 3]-triangles[:, i]
        angles.append(np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=1),
                                          np.einsum('ij,ij->i', a, b))))
    actual = measure_shape(mesh)
    np.testing.assert_allclose(actual.aspect_ratios, aspect, rtol=2e-15)
    np.testing.assert_allclose(actual.minimum_angles, np.min(angles, axis=0), rtol=2e-15)


def test_local_shape_keeps_degeneracy_and_unresolved_coordinate_guards(square):
    for coordinates in (
            np.array([[0., 0., 0.], [1., 0., 0.], [.5, 1e-25, 0.], [0., 1., 0.]]),
            square.coordinates+1e20):
        with pytest.raises(MeshBlocked, match='퇴화'):
            measure_shape(replace(square, coordinates=coordinates))
