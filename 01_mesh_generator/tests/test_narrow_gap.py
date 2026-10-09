import gmsh
import numpy as np
import pytest

from geometry_mesh.config import validate
from geometry_mesh.pipeline import initialize
from geometry_mesh.session import prepare, generate
from geometry_mesh.meshdata import snapshot


@pytest.fixture
def session():
    initialize()
    try:
        yield
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


def configuration(enabled=True, **mesh):
    return validate({"geometry": {"kind": "fuse", "objects": [
        {"kind": "box", "parameters": {"length": 2, "width": 2, "height": 2}},
        {"kind": "box", "parameters": {"length": 2, "width": 2, "height": 2, "origin": [2.12, 0, 0]}},
    ]}, "mesh": {"narrow_gap": {"enabled": enabled, "divisions": 1}, **mesh}})


def test_gap_creates_real_gmsh_field_without_small_features(session):
    context = prepare(configuration())
    sizing = context.sizing
    assert not sizing["local"]["curve_tags"] and not sizing["local"]["surface_tags"]
    assert sizing["narrow_gap_detected"] == pytest.approx(.12, abs=1e-6)
    regions = sizing["narrow_gap_evidence"]["candidate_regions"]
    assert len(regions) == 1 and len(regions[0]["volume_tags"]) == 2
    fields = sizing["local"]["fields_applied"]
    assert len(fields) == 1 and fields[0]["source"] == "narrow_gap_bbox"
    tag = gmsh.model.mesh.field.list()[0]
    assert gmsh.model.mesh.field.getNumber(tag, "VIn") == pytest.approx(.12, abs=1e-6)


def edges_at_faces(context):
    generate(context)
    mesh = snapshot(context.membership)
    triangles = mesh["coordinates"][np.searchsorted(mesh["node_ids"], mesh["connectivity"])]
    center = triangles.mean(axis=1)
    longest = np.max(np.stack([np.linalg.norm(triangles[:, i] - triangles[:, (i + 1) % 3], axis=1)
                              for i in range(3)]), axis=0)
    interior = (center[:, 1] > .3) & (center[:, 1] < 1.7) & (center[:, 2] > .3) & (center[:, 2] < 1.7)
    near = interior & (np.isclose(center[:, 0], 2) | np.isclose(center[:, 0], 2.12))
    far = interior & (np.isclose(center[:, 0], 0) | np.isclose(center[:, 0], 4.12))
    return float(np.median(longest[near])), float(np.median(longest[far]))


def test_gap_refines_facing_faces_and_preserves_far_size(session):
    off_near, off_far = edges_at_faces(prepare(configuration(False)))
    on_near, on_far = edges_at_faces(prepare(configuration(True)))
    assert on_near < off_near * .65
    assert on_near < on_far * .65
    assert on_far > off_far * .75


def test_gap_field_records_minimum_size_clamp(session):
    context = prepare(configuration(minimum_size=.2))
    field = context.sizing["local"]["fields_applied"][0]
    assert field["minimum_size_clamped"]
    assert field["size_applied"] == .2


def test_global_gap_and_controlled_exclusion_remain_explicit(session):
    context = prepare(configuration(local={"enabled": False}))
    assert context.sizing["target_size"] == pytest.approx(.12, abs=1e-6)
    assert context.sizing["narrow_gap_evidence"]["planned_application"] == "global_size"
    assert not context.sizing["local"]["fields_applied"]
    context = prepare(configuration(controlled=True))
    assert context.sizing["narrow_gap_detected"] is None
    assert not context.sizing["local"]["gap_boxes"]
    assert not context.sizing["local"]["fields_applied"]
