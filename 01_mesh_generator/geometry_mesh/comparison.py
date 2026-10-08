"""동일 형상에서 파장·자동 크기의 2×2 비교를 실행한다."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import uuid

from .config import validate
from .pipeline import run
from .reporting import write_json

CASES = (("baseline", False, False), ("waveOnly", False, True),
         ("autoSizeOnly", True, False), ("combined", True, True))


def configurations(configuration: dict) -> list[tuple[str, dict]]:
    base = validate(configuration)
    # 수동 baseline과 파장 ON 사례도 생성 전에 검증한다.
    probe = deepcopy(base)
    probe["mesh"].update(controlled=True, mode="fixed")
    probe["mesh"]["wave"]["enabled"] = True
    validate(probe)
    cases = []
    for label, automatic, wave in CASES:
        cfg = deepcopy(base)
        cfg["mesh"].update(controlled=True, mode="auto" if automatic else "fixed")
        cfg["mesh"]["wave"]["enabled"] = wave
        cfg["mesh"]["local"]["enabled"] = False
        cfg["mesh"]["local"]["boxes"] = []
        cfg["mesh"]["narrow_gap"]["enabled"] = False
        cfg["mesh"]["improvement"]["enabled"] = False
        cfg["naming"].update(automatic=True, case="" if label == "combined" else label)
        cases.append((label, validate(cfg)))
    return cases


def compare(configuration: dict, progress=None) -> dict:
    cases = configurations(configuration)
    root = Path(cases[0][1]["output_dir"]).resolve() / f'comparison_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}'
    root.mkdir(parents=True)
    manifest = {"comparison_version": "1.0", "status": "running", "output_directory": str(root),
                "configuration": validate(configuration), "cases": [], "planned_cases": [c[0] for c in cases],
                "note": "Same geometry and controlled Gmsh settings. Shape/topology checks remain active; failed cases do not publish NAS. This is mesh validation, not MoM accuracy validation."}
    def save():
        pending = root / ".comparison.pending.json"
        write_json(pending, manifest)
        pending.replace(root / "comparison.json")
    save()
    for label, cfg in cases:
        if progress:
            progress(f"comparison case: {label}")
        cfg["output_dir"] = str(root / label)
        try:
            report = run(cfg)
            manifest["cases"].append({"case": label, "status": report["status"], "output_directory": report["output_directory"],
                                      "nas": report["artifacts"]["nas"], "minimum_size": report["sizing"]["minimum_size"],
                                      "maximum_size": report["sizing"]["target_size"], "output_unit": cfg["output_unit"],
                                      "triangle_count": report["assessment"]["raw_metrics"]["triangle_count"],
                                      "timings": report["sizing"]["timings"], "applied_options": report["sizing"]["applied_options"],
                                      "fatal_gates": report["assessment"]["fatal_gates"], "environment": report["environment"]})
        except Exception as exc:
            manifest["cases"].append({"case": label, "status": "error", "nas": None, "error": str(exc)})
        save()
    manifest["status"] = "complete" if all(c["status"] == "complete" for c in manifest["cases"]) else "partial"
    save()
    return manifest
