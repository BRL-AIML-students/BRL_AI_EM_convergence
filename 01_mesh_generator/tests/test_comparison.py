import json
from pathlib import Path
import pytest

from geometry_mesh.comparison import compare, configurations


def configuration(tmp_path):
    return {"output_dir": str(tmp_path), "geometry": {"kind": "plate", "parameters": {"length": 40, "width": 30}},
            "mesh": {"minimum_size": .1, "target_size": 6, "scale_fraction": .08,
                     "wave": {"frequency_hz": 10e9}}}


def test_four_cases_isolate_only_two_controls(tmp_path):
    cases = configurations(configuration(tmp_path))
    assert [label for label, _ in cases] == ["baseline", "waveOnly", "autoSizeOnly", "combined"]
    for i, (label, cfg) in enumerate(cases):
        assert cfg["mesh"]["mode"] == ("auto" if i >= 2 else "fixed")
        assert cfg["mesh"]["wave"]["enabled"] == (i % 2 == 1)
        assert cfg["naming"]["case"] == ("" if label == "combined" else label)
        assert not cfg["mesh"]["improvement"]["enabled"]


def test_real_comparison_keeps_settings_reports_and_nas(tmp_path):
    result = compare(configuration(tmp_path))
    manifest = json.loads((Path(result["output_directory"]) / "comparison.json").read_text(encoding="utf-8"))
    assert len(manifest["cases"]) == 4
    sizes = {c["case"]: c["maximum_size"] for c in result["cases"]}
    assert sizes["baseline"] == 6
    assert sizes["autoSizeOnly"] == pytest.approx(4, abs=1e-6)
    assert sizes["waveOnly"] == pytest.approx(2.99792458)
    assert sizes["combined"] == pytest.approx(sizes["waveOnly"])
    options = []
    for case in result["cases"]:
        assert case["status"] in {"complete", "invalid"}
        output = Path(case["output_directory"])
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        assert not report["improvement_history"]
        options.append({k: v for k, v in case["applied_options"].items() if k not in {"Mesh.MeshSizeMin", "Mesh.MeshSizeMax"}})
        if case["status"] == "complete":
            assert (output / case["nas"]).is_file()
            if case["case"] == "combined":
                assert not case["nas"].endswith("_combined.nas")
        else:
            assert case["nas"] is None
            assert (output / "diagnostic.msh").is_file()
    assert all(o == options[0] for o in options)


def test_batch_preserves_failed_cases_and_continues(tmp_path, monkeypatch):
    cfg = configuration(tmp_path)
    actual = __import__("geometry_mesh.comparison", fromlist=["run"]).run
    def fails_once(case):
        if case["naming"]["case"] == "baseline":
            raise RuntimeError("expected test failure")
        return actual(case)
    monkeypatch.setattr("geometry_mesh.comparison.run", fails_once)
    result = compare(cfg)
    assert result["status"] == "partial"
    assert result["cases"][0]["error"] == "expected test failure"
    assert len(result["cases"]) == 4
