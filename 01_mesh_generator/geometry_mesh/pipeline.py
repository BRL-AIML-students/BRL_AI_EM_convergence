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
from .geometry import assign_surface_groups, build
from .meshdata import snapshot
from .nas import validate as validate_nas, write as write_nas
from .quality import add_nas_result, analyze
from .reporting import write_html, write_json
from .sizing import apply as apply_sizing, plan as plan_sizing


def _profile() -> dict[str, Any]:
    path = Path(__file__).parent / "profiles" / "quality-v2.json"
    return json.loads(path.read_text(encoding="utf-8"))


def run(configuration: dict[str, Any], progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    emit = progress or (lambda _: None)
    cfg = config_module.validate(configuration)
    output_root = Path(cfg["output_dir"]).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = f'{cfg["name"]}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}'
    final = output_root / run_id
    stage = Path(tempfile.mkdtemp(prefix=f".{run_id}.pending-", dir=output_root))
    initialized = False
    report: dict[str, Any] | None = None
    try:
        emit("initializing deterministic Gmsh session")
        gmsh.initialize(readConfigFiles=False)
        initialized = True
        gmsh.logger.start()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        for option in ("Mesh.MaxNumThreads1D", "Mesh.MaxNumThreads2D", "Mesh.MaxNumThreads3D"):
            gmsh.option.setNumber(option, 1)
        gmsh.model.add(cfg["name"])
        geometry = build(cfg["geometry"], cfg["length_unit"], cfg["output_unit"])
        sizing = plan_sizing(geometry, cfg["mesh"])
        apply_sizing(sizing)
        membership, groups = assign_surface_groups(cfg["export"]["pid_start"])
        emit("generating first-order triangular surface mesh")
        gmsh.model.mesh.generate(2)
        for _, volume in gmsh.model.getEntities(3):
            gmsh.model.mesh.setOutwardOrientation(volume)
        mesh = snapshot(membership)
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
        profile = _profile()
        assessment = analyze(mesh, geometry, sizing, profile, cfg["quality"])
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
                "cad_semantics": "STEP/IGES metadata is converted to output_length_unit; BREP is unitless and uses explicit_scale.",
            },
            "geometry": geometry, "sizing": sizing, "surface_groups": groups,
            "assessment": assessment, "score_profile": profile,
            "artifacts": {"nas": f'{cfg["name"]}.nas' if nas_path.exists() else None, "diagnostic_mesh": "diagnostic.msh", "report_json": "report.json", "quality_html": "quality_report.html"},
            "environment": {"python": platform.python_version(), "gmsh": gmsh.__version__, "numpy": np.__version__, "threads": 1, "read_config_files": False},
            "limitations": [
                "Imported CAD and boolean CSG geometry fidelity is not assessed in version 0.1 because no robust analytic reference or trimmed-surface projection audit is implemented.",
                "The growth setting is an assessment limit, not a guaranteed meshing constraint.",
                "Optional narrow-gap detection uses disjoint volume bounding boxes and is not an exact surface-clearance calculation.",
            ],
        }
        write_json(stage / "report.json", report)
        write_html(stage / "quality_report.html", report)
        (stage / "gmsh.log").write_text("\n".join(gmsh.logger.get()) + "\n", encoding="utf-8")
        gmsh.logger.stop()
        gmsh.finalize()
        initialized = False
        os.replace(stage, final)
        report["output_directory"] = str(final)
        emit(f"published atomic output: {final}")
        return report
    except Exception:
        if initialized:
            try:
                gmsh.finalize()
            except Exception:
                pass
        shutil.rmtree(stage, ignore_errors=True)
        raise


def run_file(path: str | Path, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    return run(config_module.load(path), progress=progress)
