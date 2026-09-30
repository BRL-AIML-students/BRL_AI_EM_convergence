from pathlib import Path

import pytest

from geometry_mesh.config import validate
from geometry_mesh.pipeline import run


def test_wave_validation_and_unit_limit(tmp_path: Path):
    cfg = validate({"geometry": {"kind": "plate", "parameters": {"length": 100, "width": 100}},
                    "mesh": {"wave": {"enabled": True, "frequency_hz": 3e9}}})
    assert cfg["mesh"]["wave"]["elements_per_wavelength"] == 10
    with pytest.raises(ValueError, match="frequency_hz"):
        validate({"mesh": {"wave": {"enabled": True}}})
    result = run({"name": "wave", "output_dir": str(tmp_path),
                  "geometry": {"kind": "plate", "parameters": {"length": 80, "width": 60}},
                  "mesh": {"wave": {"enabled": True, "frequency_hz": 3e9,
                                    "elements_per_wavelength": 10}}})
    assert result["sizing"]["wave"]["wavelength_output_units"] == pytest.approx(99.93081933333334)
    assert result["sizing"]["target_size"] <= result["sizing"]["wave"]["size_limit_output_units"]


def test_local_box_reduces_edges_only_near_box(tmp_path: Path):
    report = run({"name": "box_refinement", "output_dir": str(tmp_path),
                  "geometry": {"kind": "plate", "parameters": {"length": 100, "width": 100}},
                  "mesh": {"scale_fraction": 0.12,
                           "local": {"enabled": True, "feature_threshold_fraction": 0.1,
                                     "transition_fraction": 0.03,
                                     "boxes": [{"min": [0, 0, -1], "max": [20, 20, 1], "size": 2}]}}})
    assert report["status"] == "complete"
    assert any(item["type"] == "Box" for item in report["sizing"]["local"]["fields_applied"])
    nas = Path(report["output_directory"]) / "box_refinement.nas"
    nodes = {}
    triangles = []
    for line in nas.read_text().splitlines():
        parts = line.split(",")
        if parts[0] == "GRID":
            nodes[int(parts[1])] = tuple(map(float, parts[3:6]))
        elif parts[0] == "CTRIA3":
            triangles.append(tuple(map(int, parts[3:6])))
    from math import dist
    from statistics import median
    near, far = [], []
    for triangle in triangles:
        points = [nodes[tag] for tag in triangle]
        x = sum(p[0] for p in points) / 3
        y = sum(p[1] for p in points) / 3
        longest = max(dist(points[i], points[(i + 1) % 3]) for i in range(3))
        if 2 < x < 18 and 2 < y < 18:
            near.append(longest)
        elif 50 < x < 90 and 50 < y < 90:
            far.append(longest)
    assert near and far
    assert median(near) < median(far) / 2


def test_small_curves_create_local_distance_field(tmp_path: Path):
    report = run({"name": "narrow_plate", "output_dir": str(tmp_path),
                  "geometry": {"kind": "plate", "parameters": {"length": 10, "width": 100}},
                  "mesh": {"scale_fraction": 0.1,
                           "local": {"feature_threshold_fraction": 0.2}}})
    assert report["status"] == "complete"
    assert len(report["sizing"]["local"]["curve_tags"]) == 2
    assert report["sizing"]["local"]["fields_applied"][0]["type"] == "Distance+Threshold"


def test_cylinder_seam_does_not_trigger_local_refinement(tmp_path: Path):
    report = run({"name": "cylinder_seam", "output_dir": str(tmp_path),
                  "geometry": {"kind": "cylinder", "parameters": {"radius": 11, "height": 7}},
                  "mesh": {"scale_fraction": 0.06,
                           "local": {"feature_threshold_fraction": 0.25}}})
    assert report["status"] == "complete"
    assert report["sizing"]["local"]["excluded_seam_curve_tags"]
    assert not report["sizing"]["local"]["curve_tags"]
    assert not report["sizing"]["local"]["fields_applied"]
