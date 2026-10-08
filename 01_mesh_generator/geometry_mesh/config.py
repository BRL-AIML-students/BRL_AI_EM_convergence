from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any


CAD_SUFFIXES = {".step", ".stp", ".iges", ".igs", ".brep"}
PRIMITIVES = {"plate", "disk", "sphere", "box", "cylinder", "ogive"}
OPERATIONS = {"fuse", "cut", "intersect"}

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "name": "surface_mesh",
    "naming": {"automatic": True, "source_name": None, "case": ""},
    "output_dir": "outputs",
    "length_unit": "mm",
    "output_unit": "mm",
    "geometry": {"kind": "plate", "parameters": {"length": 100.0, "width": 100.0}},
    "mesh": {
        "mode": "auto",
        "scale_fraction": 0.06,
        "chord_tolerance_fraction": 0.002,
        "small_feature_divisions": 2.5,
        "minimum_size_fraction": 0.0005,
        "user_size_cap": None,
        "target_size": None,
        "growth_assessment_limit": 1.6,
        "element_budget": None,
        "budget_policy": "respect_features",
        "narrow_gap": {"enabled": False, "max_fraction": 0.03, "divisions": 3.0},
        "wave": {"enabled": False, "frequency_hz": None, "elements_per_wavelength": 10.0,
                 "relative_permittivity": 1.0, "relative_permeability": 1.0},
        "local": {"enabled": True, "feature_threshold_fraction": 0.25,
                  "near_size_fraction": 0.25, "transition_fraction": 0.15,
                  "boxes": []},
        "improvement": {"enabled": True, "max_passes": 3,
                        "methods": ["Relocate2D", "Laplace2D"], "fragment_surface_tags": []},
    },
    "export": {"pid_start": 1},
    "quality": {
        "max_aspect_ratio": 3.0, "min_angle_deg": 20.0,
        "topology": {"boundary_mode": "auto", "absolute_tolerance": 0.0,
                     "relative_tolerance": 1e-10, "protected_gap": None,
                     "separated_surface_pairs": [], "max_candidate_tests": 2000000},
    },
}


def _merge(base: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in supplied.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _positive(value: Any, path: str, *, allow_none: bool = False) -> None:
    if allow_none and value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{path} must be a finite positive number")


def _validate_node(node: dict[str, Any], path: str = "geometry") -> None:
    kind = node.get("kind")
    if kind in PRIMITIVES:
        unknown_node = set(node) - {"kind", "parameters"}
        if unknown_node:
            raise ValueError(f"unknown keys at {path}: {sorted(unknown_node)}")
        params = node.get("parameters", {})
        required = {
            "plate": ("length", "width"), "disk": ("radius",), "sphere": ("radius",),
            "box": ("length", "width", "height"), "cylinder": ("radius", "height"),
            "ogive": ("D", "L", "t"),
        }[kind]
        for key in required:
            if kind == "ogive" and key == "t":
                value = params.get("t")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"{path}.parameters.t must be finite and nonnegative")
                continue
            _positive(params.get(key), f"{path}.parameters.{key}")
        if kind == "ogive":
            if params["L"] < params["D"] / 2:
                raise ValueError("tangent ogive requires L >= D/2")
            if params["t"] >= params["D"] / 2:
                raise ValueError("ogive t must be smaller than D/2")
            if params["t"] > 0 and params["L"] == params["D"] / 2:
                raise ValueError("finite-thickness ogive requires L > D/2 with the existing offset construction")
        unknown_params = set(params) - set(required) - {"origin"}
        if unknown_params:
            raise ValueError(f"unknown keys at {path}.parameters: {sorted(unknown_params)}")
        origin = params.get("origin", [0.0, 0.0, 0.0])
        if len(origin) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in origin):
            raise ValueError(f"{path}.parameters.origin must contain three finite numbers")
    elif kind == "cad":
        unknown_node = set(node) - {"kind", "path"}
        if unknown_node:
            raise ValueError(f"unknown keys at {path}: {sorted(unknown_node)}")
        source = Path(str(node.get("path", "")))
        if not source.is_file() or source.suffix.lower() not in CAD_SUFFIXES:
            raise ValueError(f"{path}.path must be an existing STEP/STP/IGES/IGS/BREP file")
    elif kind in OPERATIONS:
        unknown_node = set(node) - {"kind", "objects"}
        if unknown_node:
            raise ValueError(f"unknown keys at {path}: {sorted(unknown_node)}")
        objects = node.get("objects")
        if not isinstance(objects, list) or len(objects) < 2:
            raise ValueError(f"{path}.objects must contain at least two geometry nodes")
        for index, child in enumerate(objects):
            if not isinstance(child, dict):
                raise ValueError(f"{path}.objects[{index}] must be an object")
            _validate_node(child, f"{path}.objects[{index}]")
    else:
        raise ValueError(f"{path}.kind is not supported: {kind!r}")


def validate(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("configuration root must be an object")
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown top-level keys: {sorted(unknown)}")
    merged = _merge(DEFAULTS, config)
    # 기존 JSON의 명시적 name은 자동 이름을 선택하지 않는 한 유지한다.
    if "name" in config and "naming" not in config:
        merged["naming"]["automatic"] = False
    naming = merged["naming"]
    if not isinstance(naming, dict) or set(naming) - set(DEFAULTS["naming"]):
        raise ValueError("unknown naming keys")
    if not isinstance(naming["automatic"], bool):
        raise ValueError("naming.automatic must be boolean")
    if naming["source_name"] is not None and (not isinstance(naming["source_name"], str) or not naming["source_name"].strip()):
        raise ValueError("naming.source_name must be a non-empty string or null")
    case = naming["case"]
    if not isinstance(case, str) or len(case) > 40 or any(not (c.isalnum() or c in "_-") for c in case):
        raise ValueError("naming.case must be a short portable suffix")
    # Geometry nodes are discriminated unions, not partial updates of the default plate.
    if "geometry" in config:
        merged["geometry"] = deepcopy(config["geometry"])
    if merged["version"] != 1:
        raise ValueError("only configuration version 1 is supported")
    for key in ("length_unit", "output_unit"):
        if merged[key] not in {"m", "cm", "mm", "um"}:
            raise ValueError(f"{key} must be one of m, cm, mm, um")
    name = merged["name"]
    if not isinstance(name, str) or not name or any(c in name for c in '<>:"/\\|?*'):
        raise ValueError("name must be a non-empty portable file name")
    if not isinstance(merged["output_dir"], str) or not merged["output_dir"].strip():
        raise ValueError("output_dir must be a non-empty path")
    _validate_node(merged["geometry"])
    mesh = merged["mesh"]
    unknown_mesh = set(mesh) - set(DEFAULTS["mesh"])
    if unknown_mesh:
        raise ValueError(f"unknown mesh keys: {sorted(unknown_mesh)}")
    if mesh["mode"] not in {"auto", "fixed"}:
        raise ValueError("mesh.mode must be auto or fixed")
    for key in ("scale_fraction", "chord_tolerance_fraction", "small_feature_divisions", "minimum_size_fraction", "growth_assessment_limit"):
        _positive(mesh[key], f"mesh.{key}")
    _positive(mesh["user_size_cap"], "mesh.user_size_cap", allow_none=True)
    _positive(mesh["target_size"], "mesh.target_size", allow_none=True)
    if mesh["mode"] == "fixed" and mesh["target_size"] is None:
        raise ValueError("mesh.target_size is required in fixed mode")
    if mesh["budget_policy"] not in {"respect_features", "respect_budget"}:
        raise ValueError("mesh.budget_policy must be respect_features or respect_budget")
    if mesh["element_budget"] is not None:
        if isinstance(mesh["element_budget"], bool) or not isinstance(mesh["element_budget"], int) or mesh["element_budget"] < 4:
            raise ValueError("mesh.element_budget must be an integer of at least 4")
    gap = mesh["narrow_gap"]
    unknown_gap = set(gap) - set(DEFAULTS["mesh"]["narrow_gap"])
    if unknown_gap:
        raise ValueError(f"unknown mesh.narrow_gap keys: {sorted(unknown_gap)}")
    if not isinstance(gap["enabled"], bool):
        raise ValueError("mesh.narrow_gap.enabled must be boolean")
    _positive(gap["max_fraction"], "mesh.narrow_gap.max_fraction")
    _positive(gap["divisions"], "mesh.narrow_gap.divisions")
    wave = mesh["wave"]
    if set(wave) - set(DEFAULTS["mesh"]["wave"]):
        raise ValueError("unknown mesh.wave keys")
    if not isinstance(wave["enabled"], bool):
        raise ValueError("mesh.wave.enabled must be boolean")
    _positive(wave["frequency_hz"], "mesh.wave.frequency_hz", allow_none=not wave["enabled"])
    for key in ("elements_per_wavelength", "relative_permittivity", "relative_permeability"):
        _positive(wave[key], f"mesh.wave.{key}")
    local = mesh["local"]
    if set(local) - set(DEFAULTS["mesh"]["local"]):
        raise ValueError("unknown mesh.local keys")
    if not isinstance(local["enabled"], bool):
        raise ValueError("mesh.local.enabled must be boolean")
    for key in ("feature_threshold_fraction", "near_size_fraction", "transition_fraction"):
        _positive(local[key], f"mesh.local.{key}")
    if local["near_size_fraction"] >= 1:
        raise ValueError("mesh.local.near_size_fraction must be below 1")
    if not isinstance(local["boxes"], list):
        raise ValueError("mesh.local.boxes must be a list")
    for index, box in enumerate(local["boxes"]):
        if not isinstance(box, dict) or set(box) != {"min", "max", "size"}:
            raise ValueError(f"mesh.local.boxes[{index}] needs min, max, size")
        for side in ("min", "max"):
            coords = box[side]
            if not isinstance(coords, list) or len(coords) != 3 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in coords
            ):
                raise ValueError(f"mesh.local.boxes[{index}].{side} needs three finite coordinates")
        if any(a >= b for a, b in zip(box["min"], box["max"])):
            raise ValueError(f"mesh.local.boxes[{index}] min must be below max")
        _positive(box["size"], f"mesh.local.boxes[{index}].size")
    pid_start = merged["export"]["pid_start"]
    unknown_export = set(merged["export"]) - set(DEFAULTS["export"])
    if unknown_export:
        raise ValueError(f"unknown export keys: {sorted(unknown_export)}")
    if isinstance(pid_start, bool) or not isinstance(pid_start, int) or pid_start < 1:
        raise ValueError("export.pid_start must be a positive integer")
    quality = merged["quality"]
    improvement = mesh["improvement"]
    if not isinstance(improvement, dict) or set(improvement) - set(DEFAULTS["mesh"]["improvement"]):
        raise ValueError("unknown mesh.improvement keys")
    if not isinstance(improvement["enabled"], bool):
        raise ValueError("mesh.improvement.enabled must be boolean")
    passes = improvement["max_passes"]
    if isinstance(passes, bool) or not isinstance(passes, int) or not 0 <= passes <= 3:
        raise ValueError("mesh.improvement.max_passes must be an integer between 0 and 3")
    if not isinstance(improvement["methods"], list) or not improvement["methods"] or any(not isinstance(m,str) or m not in {"Relocate2D", "Laplace2D"} for m in improvement["methods"]):
        raise ValueError("mesh.improvement.methods must contain Relocate2D or Laplace2D")
    tags = improvement["fragment_surface_tags"]
    if not isinstance(tags, list) or any(isinstance(t, bool) or not isinstance(t, int) or t <= 0 for t in tags) or len(set(tags)) != len(tags) or len(tags) == 1:
        raise ValueError("mesh.improvement.fragment_surface_tags requires zero or at least two unique positive surface tags")
    if not isinstance(quality, dict) or set(quality) - set(DEFAULTS["quality"]):
        raise ValueError("unknown quality keys")
    _positive(quality["max_aspect_ratio"], "quality.max_aspect_ratio")
    _positive(quality["min_angle_deg"], "quality.min_angle_deg")
    if quality["max_aspect_ratio"] < 1 or quality["max_aspect_ratio"] > 3:
        raise ValueError("quality.max_aspect_ratio must be between 1 and 3 (no automatic waiver)")
    if quality["min_angle_deg"] < 20 or quality["min_angle_deg"] > 60:
        raise ValueError("quality.min_angle_deg must be between 20 and 60")
    topo = quality["topology"]
    if not isinstance(topo, dict) or set(topo) - set(DEFAULTS["quality"]["topology"]):
        raise ValueError("unknown quality.topology keys")
    if topo["boundary_mode"] not in {"auto", "open", "closed"}:
        raise ValueError("quality.topology.boundary_mode must be auto, open or closed")
    _positive(topo["relative_tolerance"], "quality.topology.relative_tolerance")
    _positive(topo["protected_gap"], "quality.topology.protected_gap", allow_none=True)
    absolute = topo["absolute_tolerance"]
    if isinstance(absolute, bool) or not isinstance(absolute, (int, float)) or not math.isfinite(absolute) or absolute < 0:
        raise ValueError("quality.topology.absolute_tolerance must be finite and nonnegative")
    budget = topo["max_candidate_tests"]
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 10000000:
        raise ValueError("quality.topology.max_candidate_tests must be an integer between 1 and 10000000")
    pairs = topo["separated_surface_pairs"]
    if not isinstance(pairs, list):
        raise ValueError("quality.topology.separated_surface_pairs must be a list")
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 for x in pair) or pair[0] == pair[1]:
            raise ValueError("separated_surface_pairs requires pairs of distinct positive surface tags")
    return merged


def load(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    # Input paths are relative to the configuration file; output paths remain caller-relative.
    geometry = data.get("geometry", {}) if isinstance(data, dict) else {}
    _resolve_cad_paths(geometry, source.parent)
    return validate(data)


def _resolve_cad_paths(node: dict[str, Any], base: Path) -> None:
    if node.get("kind") == "cad" and "path" in node:
        candidate = Path(node["path"])
        if not candidate.is_absolute():
            node["path"] = str((base / candidate).resolve())
    for child in node.get("objects", []):
        _resolve_cad_paths(child, base)
