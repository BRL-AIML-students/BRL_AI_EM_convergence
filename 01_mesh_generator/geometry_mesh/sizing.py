from __future__ import annotations

import math
from collections import Counter
from typing import Any

import gmsh

METRES_PER_UNIT = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6}
C0 = 299_792_458.0

CONTROLLED_OPTIONS = {
    "Mesh.MeshSizeFromCurvature": 0, "Mesh.MeshSizeFromPoints": 1,
    "Mesh.MeshSizeExtendFromBoundary": 1, "Mesh.Algorithm": 6,
    "Mesh.ElementOrder": 1, "Mesh.RecombineAll": 0,
    "Mesh.Smoothing": 1, "Mesh.Optimize": 1,
}


def _controlled_plan(geometry: dict, settings: dict) -> dict:
    scale = geometry["scale"]
    automatic = settings["mode"] == "auto"
    low = scale * settings["minimum_size_fraction"] if automatic else settings["minimum_size"]
    high = scale * settings["scale_fraction"] if automatic else settings["target_size"]
    rules = [{"rule": "automatic_bounds" if automatic else "manual_bounds", "minimum_size": low, "candidate_size": high}]
    wave = settings["wave"]
    details = {"enabled": wave["enabled"]}
    if wave["enabled"]:
        wavelength = C0 / (wave["frequency_hz"] * math.sqrt(wave["relative_permittivity"] * wave["relative_permeability"])) / METRES_PER_UNIT[geometry["output_unit"]]
        limit = wavelength / wave["elements_per_wavelength"]
        details.update(frequency_hz=wave["frequency_hz"], wavelength_output_units=wavelength,
                       size_limit_output_units=limit, elements_per_wavelength=wave["elements_per_wavelength"],
                       relative_permittivity=wave["relative_permittivity"], relative_permeability=wave["relative_permeability"],
                       minimum_adjusted_for_wave=low > limit,
                       assumption="homogeneous lossless medium; phase wavelength only")
        high, low = min(high, limit), min(low, limit)
        rules.append({"rule": "wavelength", "candidate_size": limit})
    return {
        "controlled": True, "automatic_bounds": automatic, "model_scale": scale,
        "minimum_size": low, "target_size": high, "user_size_cap": None,
        "chord_tolerance": scale * settings["chord_tolerance_fraction"], "curvature_samples_per_circle": 0,
        "growth_assessment_limit": settings["growth_assessment_limit"],
        "estimated_elements": max(1, math.ceil(geometry["surface_area"] / (math.sqrt(3) * high * high / 4))),
        "element_budget": None, "budget_conflict": None, "narrow_gap_detected": None,
        "narrow_gap_evidence": {"coverage": "not_assessed", "reason": "controlled mode excludes gap sizing"},
        "candidate_rules": rules, "wave": details,
        "local": {"enabled": False, "curve_tags": [], "surface_tags": [], "excluded_seam_curve_tags": [],
                  "smallest_feature": None, "near_size_fraction": settings["local"]["near_size_fraction"],
                  "transition_distance": 0, "boxes": [], "fields_applied": []},
        "excluded_controls": ["curvature", "small_features", "local_fields", "box_fields", "narrow_gap", "budget", "post_mesh_improvement"],
    }


def _bbox_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum(max(0.0, a[i] - b[i + 3], b[i] - a[i + 3]) ** 2 for i in range(3)))


def _narrow_gap(geometry: dict[str, Any], settings: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    if not settings["enabled"]:
        return None, {"coverage": "not_assessed", "reason": "narrow-gap check disabled", "method": "disjoint volume bounding-box distance"}
    volumes = gmsh.model.getEntities(3)
    if len(volumes) < 2:
        return None, {"coverage": "not_assessed", "reason": "fewer than two volume entities", "method": "disjoint volume bounding-box distance"}
    boxes = [gmsh.model.getBoundingBox(dim, tag) for dim, tag in volumes]
    maximum = geometry["scale"] * settings["max_fraction"]
    candidates = [
        _bbox_distance(boxes[i], boxes[j])
        for i in range(len(boxes)) for j in range(i + 1, len(boxes))
    ]
    candidates = [gap for gap in candidates if 0 < gap <= maximum]
    if not candidates:
        return None, {"coverage": "not_assessed", "reason": "volume boxes overlap or no positive box gap is within the search distance", "method": "disjoint volume bounding-box distance"}
    return min(candidates), {"coverage": "assessed", "reason": None, "method": "disjoint volume bounding-box distance", "limitation": "axis-aligned boxes can overestimate proximity and do not measure exact surface clearance"}


def _seam_curve_tags() -> set[int]:
    """Find CAD parameterization seams repeated in a surface boundary loop."""
    seams: set[int] = set()
    for _, surface in gmsh.model.getEntities(2):
        _, loops = gmsh.model.occ.getCurveLoops(surface)
        for loop in loops:
            seams.update(int(tag) for tag, count in Counter(map(abs, loop)).items() if count > 1)
    return seams


def plan(geometry: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    if settings["controlled"]:
        return _controlled_plan(geometry, settings)
    scale = geometry["scale"]
    seam_curve_tags = _seam_curve_tags()
    lengths = []
    curve_measures = []
    for _, tag in gmsh.model.getEntities(1):
        value = gmsh.model.occ.getMass(1, tag)
        if tag not in seam_curve_tags and math.isfinite(value) and value > scale * 1e-12:
            lengths.append(float(value))
            curve_measures.append((int(tag), float(value)))
    face_scales = []
    face_measures = []
    for _, tag in gmsh.model.getEntities(2):
        value = gmsh.model.occ.getMass(2, tag)
        if math.isfinite(value) and value > 0:
            face_scales.append(math.sqrt(float(value)))
            face_measures.append((int(tag), math.sqrt(float(value))))
    base = settings["target_size"] if settings["mode"] == "fixed" else scale * settings["scale_fraction"]
    reasons = [{"rule": "model_scale", "candidate_size": base}]
    feature = None
    if lengths:
        feature = min(lengths) / settings["small_feature_divisions"]
        reasons.append({"rule": "small_edge", "source_measure": min(lengths), "candidate_size": feature})
    if face_scales:
        face_size = min(face_scales) / settings["small_feature_divisions"]
        feature = min(feature, face_size) if feature is not None else face_size
        reasons.append({"rule": "small_face", "source_measure": min(face_scales), "candidate_size": face_size})
    gap, gap_evidence = _narrow_gap(geometry, settings["narrow_gap"])
    if gap is not None:
        gap_size = gap / settings["narrow_gap"]["divisions"]
        feature = min(feature, gap_size) if feature is not None else gap_size
        reasons.append({"rule": "narrow_gap_bbox", "source_measure": gap, "candidate_size": gap_size})
    floor = scale * settings["minimum_size_fraction"]
    local = settings["local"]
    requested = min(base, feature) if feature is not None and not local["enabled"] else base
    cap = settings["user_size_cap"]
    if cap is not None:
        requested = min(requested, cap)
        reasons.append({"rule": "user_cap", "candidate_size": cap})
    requested = max(floor, requested)
    wave = settings["wave"]
    wave_details = {"enabled": wave["enabled"]}
    if wave["enabled"]:
        wavelength_m = C0 / (wave["frequency_hz"] * math.sqrt(
            wave["relative_permittivity"] * wave["relative_permeability"]))
        wavelength = wavelength_m / METRES_PER_UNIT[geometry["output_unit"]]
        wave_size = wavelength / wave["elements_per_wavelength"]
        requested = min(requested, wave_size)
        floor = min(floor, wave_size)
        wave_details.update({"frequency_hz": wave["frequency_hz"],
                             "wavelength_output_units": wavelength,
                             "size_limit_output_units": wave_size,
                             "elements_per_wavelength": wave["elements_per_wavelength"],
                             "relative_permittivity": wave["relative_permittivity"],
                             "relative_permeability": wave["relative_permeability"],
                             "assumption": "homogeneous lossless medium; phase wavelength only"})
        reasons.append({"rule": "wavelength", "candidate_size": wave_size})
    triangle_area = math.sqrt(3.0) * requested * requested / 4.0
    estimated = max(1, math.ceil(geometry["surface_area"] / triangle_area))
    conflict = None
    budget = settings["element_budget"]
    if budget is not None and estimated > budget:
        budget_size = math.sqrt(geometry["surface_area"] / (budget * math.sqrt(3.0) / 4.0))
        conflict = {
            "type": "element_budget_vs_geometry_resolution",
            "estimated_elements_at_geometry_size": estimated,
            "element_budget": budget,
            "geometry_size": requested,
            "budget_size": budget_size,
            "policy": settings["budget_policy"],
        }
        if settings["budget_policy"] == "respect_budget":
            requested = max(requested, budget_size)
            if wave["enabled"]:
                requested = min(requested, wave_details["size_limit_output_units"])
    # Convert the relative chord target into Gmsh's samples-per-circle control.
    chord = scale * settings["chord_tolerance_fraction"]
    ratio = min(0.999999, max(1e-12, chord / scale))
    curvature_samples = max(8, min(200, math.ceil(math.pi / math.sqrt(2.0 * ratio))))
    return {
        "model_scale": scale,
        "minimum_size": floor,
        "target_size": requested,
        "user_size_cap": cap,
        "chord_tolerance": chord,
        "curvature_samples_per_circle": curvature_samples,
        "growth_assessment_limit": settings["growth_assessment_limit"],
        "estimated_elements": estimated,
        "element_budget": budget,
        "budget_conflict": conflict,
        "narrow_gap_detected": gap,
        "narrow_gap_evidence": gap_evidence,
        "candidate_rules": reasons,
        "wave": wave_details,
        "local": {"enabled": local["enabled"], "curve_tags": [tag for tag, length in curve_measures
                  if length <= scale * local["feature_threshold_fraction"]],
                  "excluded_seam_curve_tags": sorted(seam_curve_tags),
                  "surface_tags": [tag for tag, size in face_measures
                  if size <= scale * local["feature_threshold_fraction"]],
                  "smallest_feature": feature, "near_size_fraction": local["near_size_fraction"],
                  "transition_distance": scale * local["transition_fraction"],
                  "boxes": local["boxes"], "fields_applied": []},
    }


def apply(sizing: dict[str, Any]) -> None:
    gmsh.option.setNumber("Mesh.MeshSizeMin", sizing["minimum_size"])
    gmsh.option.setNumber("Mesh.MeshSizeMax", sizing["target_size"])
    if sizing.get("controlled", False):
        for option, value in CONTROLLED_OPTIONS.items():
            gmsh.option.setNumber(option, value)
        sizing["applied_options"] = {**CONTROLLED_OPTIONS, "Mesh.MeshSizeMin": sizing["minimum_size"], "Mesh.MeshSizeMax": sizing["target_size"]}
        return
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", sizing["curvature_samples_per_circle"])
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 1)
    local = sizing["local"]
    if local["enabled"]:
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        fields = []
        if local["curve_tags"] or local["surface_tags"]:
            distance = gmsh.model.mesh.field.add("Distance")
            if local["curve_tags"]:
                gmsh.model.mesh.field.setNumbers(distance, "CurvesList", local["curve_tags"])
            if local["surface_tags"]:
                gmsh.model.mesh.field.setNumbers(distance, "SurfacesList", local["surface_tags"])
            threshold = gmsh.model.mesh.field.add("Threshold")
            near = min(sizing["target_size"] * local["near_size_fraction"],
                       local["smallest_feature"] or sizing["target_size"])
            near = max(sizing["minimum_size"], near)
            gmsh.model.mesh.field.setNumber(threshold, "InField", distance)
            gmsh.model.mesh.field.setNumber(threshold, "SizeMin", near)
            gmsh.model.mesh.field.setNumber(threshold, "SizeMax", sizing["target_size"])
            gmsh.model.mesh.field.setNumber(threshold, "DistMin", 0)
            gmsh.model.mesh.field.setNumber(threshold, "DistMax", local["transition_distance"])
            fields.append(threshold)
            local["fields_applied"].append({"type": "Distance+Threshold", "near_size": near,
                                            "far_size": sizing["target_size"]})
        for box in local["boxes"]:
            tag = gmsh.model.mesh.field.add("Box")
            for axis, low, high in zip("XYZ", box["min"], box["max"]):
                gmsh.model.mesh.field.setNumber(tag, axis + "Min", low)
                gmsh.model.mesh.field.setNumber(tag, axis + "Max", high)
            gmsh.model.mesh.field.setNumber(tag, "VIn", max(sizing["minimum_size"],
                                                              min(box["size"], sizing["target_size"])))
            gmsh.model.mesh.field.setNumber(tag, "VOut", sizing["target_size"])
            gmsh.model.mesh.field.setNumber(tag, "Thickness", local["transition_distance"])
            fields.append(tag)
            local["fields_applied"].append({"type": "Box", "bounds": box})
        if fields:
            if len(fields) > 1:
                combined = gmsh.model.mesh.field.add("Min")
                gmsh.model.mesh.field.setNumbers(combined, "FieldsList", fields)
                gmsh.model.mesh.field.setAsBackgroundMesh(combined)
            else:
                gmsh.model.mesh.field.setAsBackgroundMesh(fields[0])
    gmsh.option.setNumber("Mesh.Algorithm", 5 if local["fields_applied"] else 6)
    gmsh.option.setNumber("Mesh.ElementOrder", 1)
    gmsh.option.setNumber("Mesh.RecombineAll", 0)
    gmsh.option.setNumber("Mesh.Smoothing", 3)
    gmsh.option.setNumber("Mesh.Optimize", 1)
