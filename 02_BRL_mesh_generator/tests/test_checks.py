from dataclasses import replace

import numpy as np
import pytest

from brl_mesh.checks import check_plate_geometry, check_shape
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
    with pytest.raises(MeshBlocked, match='AR'):
        check_shape(replace(square, coordinates=xyz))
