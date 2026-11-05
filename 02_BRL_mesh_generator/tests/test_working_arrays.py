"""Stable surface grouping and tiled support widths preserve measurement inputs."""
import numpy as np
import pytest

from brl_mesh.features import _support_width
from brl_mesh.model import surface_groups


@pytest.mark.parametrize('tags', [[7]*40, [50, 2, 50, 9, 2, 9, 50], list(range(1, 1001))*3, []])
def test_surface_groups_match_per_face_filter_and_keep_element_order(tags):
    values = np.array(tags, dtype=np.int64)
    groups = surface_groups(values)
    assert list(groups) == sorted(set(tags))
    for tag, indices in groups.items():
        np.testing.assert_array_equal(indices, np.flatnonzero(values == tag))
    if len(values):
        values[0] = 12345
        changed = surface_groups(values)
        np.testing.assert_array_equal(changed[12345], np.flatnonzero(values == 12345))


@pytest.mark.parametrize('count', [4, 257, 4201])
def test_tiled_support_width_matches_all_point_normal_projection(count):
    rng = np.random.default_rng(121)
    points = rng.normal(size=(count, 2))
    normals = rng.normal(size=(273, 2))
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    expected = float(np.ptp(points @ normals.T, axis=0).min())
    assert _support_width(points, normals) == pytest.approx(expected, rel=4*np.finfo(float).eps)
