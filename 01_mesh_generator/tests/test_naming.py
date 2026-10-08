from pathlib import Path
import json

from geometry_mesh.config import validate
from geometry_mesh.naming import resolve, number
from geometry_mesh.pipeline import run


def test_readable_units_case_and_legacy_name():
    assert number(4.0000000224) == "4"
    assert number(.02500000014) == "0p025"
    cfg = validate({"geometry": {"kind": "ogive", "parameters": {"D": 110, "L": 200, "t": .5}}, "length_unit": "mm", "output_unit": "m", "naming": {"case": "noWave"}, "mesh": {"wave": {"frequency_hz": 9.5e9}}})
    name = resolve(cfg, {"minimum_size": .001, "target_size": .003})
    assert name == "ogive_D110_L200_t0p5_mm_hMin0p001m_hMax0p003m_f9p5GHz_N10_noWave"
    assert resolve(validate({"name": "legacy"}), {}) == "legacy"


def test_cad_original_name_and_sanitization(tmp_path):
    cad = tmp_path / "cad_opaque.step"
    cad.touch()
    cfg = validate({"geometry": {"kind": "cad", "path": str(cad)}, "naming": {"source_name": "한글 원본.step"}})
    assert resolve(cfg, {"minimum_size": .2, "target_size": 2}) == "한글_원본_hMin0p2mm_hMax2mm"


def test_automatic_publication_uses_actual_sizing_and_unique_run_folder(tmp_path: Path):
    cfg = {"output_dir": str(tmp_path), "geometry": {"kind": "plate", "parameters": {"length": 12, "width": 8}}, "mesh": {"scale_fraction": .2}}
    first, second = run(cfg), run(cfg)
    for report in (first, second):
        name = resolve(report["configuration"], report["sizing"])
        assert report["status"] == "complete"
        assert report["artifacts"]["nas"] == name + ".nas"
        assert (Path(report["output_directory"]) / (name + ".nas")).is_file()
        saved = json.loads((Path(report["output_directory"]) / "report.json").read_text(encoding="utf-8"))
        assert saved["configuration"]["name"] == name
    assert first["output_directory"] != second["output_directory"]
    assert first["artifacts"]["nas"] == second["artifacts"]["nas"]
