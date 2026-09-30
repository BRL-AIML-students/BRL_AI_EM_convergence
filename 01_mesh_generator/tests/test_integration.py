import json
from pathlib import Path

import pytest

from geometry_mesh.pipeline import run


@pytest.mark.parametrize("kind,parameters", [
    ("plate", {"length": 12.0, "width": 8.0}),
    ("disk", {"radius": 5.0}),
    ("sphere", {"radius": 5.0}),
    ("box", {"length": 8.0, "width": 6.0, "height": 4.0}),
    ("cylinder", {"radius": 3.0, "height": 7.0}),
])
def test_generated_shape_pipeline(tmp_path: Path, kind: str, parameters: dict):
    report = run({
        "version": 1, "name": kind, "output_dir": str(tmp_path),
        "length_unit": "cm", "output_unit": "mm",
        "geometry": {"kind": kind, "parameters": parameters},
        "mesh": {"mode": "auto", "scale_fraction": 0.15, "chord_tolerance_fraction": 0.01},
    })
    output = Path(report["output_directory"])
    saved = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert (output / f"{kind}.nas").is_file()
    assert (output / "quality_report.html").is_file()
    assert saved["units"]["explicit_scale"] == 10.0
    assert set(saved["assessment"]["scores"]) == {
        "element_shape", "size_compliance", "gradation_and_features", "geometry_fidelity",
        "topology_and_normals", "nas_export_integrity",
    }
    assert saved["sizing"]["post_mesh_budget"]["actual_triangle_count"] == saved["assessment"]["raw_metrics"]["triangle_count"]
    assert all("overall" not in key and "total" not in key for key in saved)


def test_csg_cut_pipeline(tmp_path: Path):
    report = run({
        "version": 1, "name": "cut", "output_dir": str(tmp_path),
        "geometry": {"kind": "cut", "objects": [
            {"kind": "box", "parameters": {"length": 8, "width": 6, "height": 4}},
            {"kind": "cylinder", "parameters": {"radius": 1, "height": 4, "origin": [4, 3, 0]}},
        ]},
        "mesh": {"mode": "auto", "scale_fraction": 0.18, "chord_tolerance_fraction": 0.02},
    })
    saved = json.loads((Path(report["output_directory"]) / "report.json").read_text())
    assert saved["assessment"]["scores"]["geometry_fidelity"]["coverage"] == "not_assessed"


def test_unit_conversion_fidelity(tmp_path: Path):
    report = run({
        "version": 1, "name": "unit_sphere", "output_dir": str(tmp_path),
        "length_unit": "mm", "output_unit": "m",
        "geometry": {"kind": "sphere", "parameters": {"radius": 100.0}},
        "mesh": {"mode": "auto", "scale_fraction": 0.16, "chord_tolerance_fraction": 0.01},
    })
    item = report["assessment"]["scores"]["geometry_fidelity"]
    assert item["coverage"] == "assessed"
    assert item["metrics"]["reference_area"] == pytest.approx(4 * 3.141592653589793 * 0.1 ** 2)
