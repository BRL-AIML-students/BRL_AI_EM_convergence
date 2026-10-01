from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import tempfile
import uuid
from typing import Any, Callable

import gmsh
import numpy as np

from . import config as config_module
from .nas import validate as validate_nas, write as write_nas
from .quality import add_nas_result
from .reporting import write_html, write_json, json_safe


def _profile() -> dict[str, Any]:
    path = Path(__file__).parent / "profiles" / "quality-v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def initialize() -> None:
    gmsh.initialize(readConfigFiles=False)
    gmsh.logger.start()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("General.NumThreads", 1)
    for option in ("Mesh.MaxNumThreads1D", "Mesh.MaxNumThreads2D", "Mesh.MaxNumThreads3D"):
        gmsh.option.setNumber(option, 1)


def publish_current(context, improvement_history: list | None = None) -> dict:
    # Always inspect the actual current Gmsh snapshot immediately before output.
    from .session import current
    cfg, geometry, sizing, groups = context.configuration, context.geometry, context.sizing, context.groups
    profile = _profile()
    mesh, assessment = current(context, profile)
    output_root = Path(cfg["output_dir"]).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = f'{cfg["name"]}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}'
    final = output_root / run_id
    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.pending-", dir=output_root))
    try:
        if sizing["wave"]["enabled"]:
            indices = np.searchsorted(mesh["node_ids"], mesh["connectivity"])
            triangles = mesh["coordinates"][indices]
            edge_lengths = np.stack([
                np.linalg.norm(triangles[:, i] - triangles[:, (i + 1) % 3], axis=1)
                for i in range(3)
            ], axis=1)
            longest = np.max(edge_lengths, axis=1)
            limit = sizing["wave"]["size_limit_output_units"]
            sizing["wave"]["post_mesh"] = {
                "longest_edge_q95_to_wave_limit": float(np.percentile(longest / limit, 95)),
                "longest_edge_max_to_wave_limit": float(np.max(longest / limit)),
                "triangles_with_longest_edge_over_wave_limit": int(np.count_nonzero(longest > limit)),
                "triangle_count": int(len(longest)),
                "note": "This checks surface triangle edges, not solver convergence or an exact meshing constraint.",
            }
        actual_triangles = int(len(mesh["element_ids"]))
        element_budget = sizing["element_budget"]
        sizing["post_mesh_budget"] = {
            "coverage": "not_assessed" if element_budget is None else "assessed",
            "actual_triangle_count": actual_triangles,
            "element_budget": element_budget,
            "budget_met": None if element_budget is None else actual_triangles <= element_budget,
            "note": (
                "No element budget was configured."
                if element_budget is None
                else "The budget is checked after meshing; the pre-mesh area estimate is not a hard Gmsh element-count constraint."
            ),
        }
        nas_path = stage / f'{cfg["name"]}.nas'
        if not assessment["fatal_gates"]:
            write_nas(nas_path, mesh, cfg["output_unit"])
            add_nas_result(assessment, validate_nas(nas_path, mesh))
            if assessment["fatal_gates"]:
                nas_path.unlink(missing_ok=True)
        gmsh.option.setNumber("Mesh.SaveAll", 1)
        gmsh.write(str(stage / "diagnostic.msh"))
        report = {
            "report_version": "2.0.0", "run_id": run_id,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "status": "invalid" if assessment["fatal_gates"] else "complete",
            "configuration": cfg,
            "units": {
                "input_length_unit": cfg["length_unit"], "output_length_unit": cfg["output_unit"],
                "explicit_scale": geometry["explicit_scale"],
                "cad_semantics": ("Native File/Open coordinates are unchanged and interpreted in output_length_unit; BRL input-unit conversion is not applied."
                                  if geometry["source_kind"] == "native_current_model" else
                                  "STEP/IGES metadata is converted to output_length_unit; BREP is unitless and uses explicit_scale."),
            },
            "geometry": geometry, "sizing": sizing, "surface_groups": groups,
            "assessment": assessment, "score_profile": profile, "improvement_history": improvement_history or [],
            "artifacts": {"nas": f'{cfg["name"]}.nas' if nas_path.exists() else None, "diagnostic_mesh": "diagnostic.msh", "report_json": "report.json", "quality_html": "quality_report.html"},
            "environment": {"python": platform.python_version(), "gmsh": gmsh.__version__, "numpy": np.__version__, "threads": 1, "read_config_files": False},
            "limitations": [
                "Imported CAD, native opened models and boolean CSG geometry fidelity are not assessed because no robust analytic reference or trimmed-surface projection audit is implemented.",
                "General triangle-face intersections are not assessed by the vertex-edge conformity audit.",
                "Automatic relocation preserves connectivity; arbitrary existing-mesh T-junction repair is not implemented.",
                "The growth setting is an assessment limit, not a guaranteed meshing constraint.",
                "Optional narrow-gap detection uses disjoint volume bounding boxes and is not an exact surface-clearance calculation.",
            ],
        }
        report=json_safe(report)
        write_json(stage / "report.json", report)
        write_html(stage / "quality_report.html", report)
        (stage / "gmsh.log").write_text("\n".join(gmsh.logger.get()) + "\n", encoding="utf-8")
        os.replace(stage, final)
        report["output_directory"] = str(final)
        return report
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def run(configuration: dict[str, Any], progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    from .session import prepare, generate, improve
    emit = progress or (lambda _: None)
    cfg = config_module.validate(configuration)
    if gmsh.isInitialized():
        raise RuntimeError("run() owns its Gmsh session; use session API for an existing model")
    initialize()
    try:
        emit("generating first-order triangular surface mesh")
        context = prepare(cfg)
        generate(context)
        _, _, history = improve(context, _profile())
        report = publish_current(context, history)
        emit(f"published atomic output: {report['output_directory']}")
        return report
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


def run_file(path: str | Path, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    return run(config_module.load(path), progress=progress)
