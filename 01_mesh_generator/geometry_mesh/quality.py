from __future__ import annotations

import math
from typing import Any

import numpy as np


def _percentile(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q))


def _score_lower(value: float, good: float, bad: float) -> float:
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return 100.0 * (bad - value) / (bad - good)


def _score_higher(value: float, bad: float, good: float) -> float:
    return _score_lower(-value, -good, -bad)


def _item(score: float | None, metrics: dict[str, Any], rationale: str, problems: list[int] | None = None,
          reason: str | None = None) -> dict[str, Any]:
    assessed = score is not None
    band = "not_assessed" if not assessed else ("good" if score >= 80 else "warn" if score >= 50 else "poor")
    return {
        "coverage": "assessed" if assessed else "not_assessed",
        "score": round(float(score), 3) if assessed else None,
        "status_band": band,
        "metrics": metrics,
        "problem_element_ids": problems or [],
        "rationale": rationale,
        "not_assessed_reason": None if assessed else reason,
        "recommendations": [],
    }


def analyze(mesh: dict[str, Any], geometry: dict[str, Any], sizing: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    node_ids = mesh["node_ids"]
    coords = mesh["coordinates"]
    conn = mesh["connectivity"]
    eids = mesh["element_ids"]
    idx = np.searchsorted(node_ids, conn)
    xyz = coords[idx]
    edge_vectors = np.stack((xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 1], xyz[:, 0] - xyz[:, 2]), axis=1)
    lengths = np.linalg.norm(edge_vectors, axis=2)
    cross = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    areas = np.linalg.norm(cross, axis=1) / 2.0
    finite = bool(np.all(np.isfinite(coords)) and np.all(np.isfinite(areas)))
    zero_mask = areas <= max(geometry["scale"] ** 2 * 1e-24, np.finfo(float).tiny)

    cosines = np.empty((len(conn), 3), dtype=float)
    a, b, c = lengths[:, 0], lengths[:, 1], lengths[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        cosines[:, 0] = (a * a + c * c - b * b) / (2 * a * c)
        cosines[:, 1] = (a * a + b * b - c * c) / (2 * a * b)
        cosines[:, 2] = (b * b + c * c - a * a) / (2 * b * c)
        angles = np.degrees(np.arccos(np.clip(cosines, -1, 1)))
        min_angles = np.min(angles, axis=1)
        max_angles = np.max(angles, axis=1)
        quality = 4.0 * math.sqrt(3.0) * areas / np.sum(lengths * lengths, axis=1)

    all_edges = np.concatenate((conn[:, [0, 1]], conn[:, [1, 2]], conn[:, [2, 0]]))
    edge_owner = np.tile(np.arange(len(conn)), 3)
    canonical = np.sort(all_edges, axis=1)
    unique_edges, inverse, counts = np.unique(canonical, axis=0, return_inverse=True, return_counts=True)
    directions = np.where(all_edges[:, 0] < all_edges[:, 1], 1, -1)
    balance = np.bincount(inverse, weights=directions)
    boundary_edges = int(np.count_nonzero(counts == 1))
    nonmanifold_groups = np.flatnonzero(counts > 2)
    inconsistent_groups = np.flatnonzero((counts == 2) & (balance != 0))
    nonmanifold_eids = sorted({int(eids[edge_owner[i]]) for group in nonmanifold_groups for i in np.flatnonzero(inverse == group)})
    inconsistent_eids = sorted({int(eids[edge_owner[i]]) for group in inconsistent_groups for i in np.flatnonzero(inverse == group)})
    duplicate_rows = len(np.unique(np.sort(conn, axis=1), axis=0)) != len(conn)
    expected_closed = geometry["volume_count"] > 0

    shape_cfg = profile["thresholds"]["element_shape"]
    shape_problems = eids[(min_angles < shape_cfg["problem_min_angle_deg"]) | (quality < shape_cfg["problem_quality"])].astype(int).tolist()
    shape_score = min(
        _score_higher(float(np.nanmin(min_angles)), shape_cfg["min_angle_bad"], shape_cfg["min_angle_good"]),
        _score_higher(_percentile(quality, 1), shape_cfg["quality_q01_bad"], shape_cfg["quality_q01_good"]),
    )
    shape_metrics = {
        "minimum_angle_deg": float(np.nanmin(min_angles)), "angle_q01_deg": _percentile(min_angles, 1),
        "maximum_angle_deg": float(np.nanmax(max_angles)), "minimum_mean_ratio": float(np.nanmin(quality)),
        "mean_ratio_q01": _percentile(quality, 1), "mean_ratio_mean": float(np.nanmean(quality)),
    }

    longest = np.max(lengths, axis=1)
    size_ratio = longest / sizing["target_size"]
    size_cfg = profile["thresholds"]["size_compliance"]
    cap = sizing["user_size_cap"]
    violations = eids[longest > (cap if cap is not None else sizing["target_size"]) * size_cfg["problem_ratio"]].astype(int).tolist()
    size_score = _score_lower(_percentile(size_ratio, 95), size_cfg["q95_good"], size_cfg["q95_bad"])
    size_metrics = {
        "edge_min": float(np.min(lengths)), "edge_mean": float(np.mean(lengths)), "edge_max": float(np.max(lengths)),
        "longest_edge_to_target_q95": _percentile(size_ratio, 95), "target_size": sizing["target_size"],
        "user_size_cap": cap, "elements_over_problem_ratio": len(violations),
    }

    characteristic = np.sqrt(areas)
    adjacent_ratios: list[float] = []
    gradation_problems: set[int] = set()
    for group in np.flatnonzero(counts == 2):
        owners = edge_owner[np.flatnonzero(inverse == group)]
        ratio = float(max(characteristic[owners]) / min(characteristic[owners]))
        adjacent_ratios.append(ratio)
        if ratio > sizing["growth_assessment_limit"]:
            gradation_problems.update(map(int, eids[owners]))
    gradation_q99 = _percentile(np.asarray(adjacent_ratios), 99) if adjacent_ratios else 1.0
    growth_bad = max(sizing["growth_assessment_limit"] * 1.75, sizing["growth_assessment_limit"] + 0.5)
    gradation_score = _score_lower(gradation_q99, sizing["growth_assessment_limit"], growth_bad)
    surface_values, surface_counts = np.unique(mesh["surface_tags"], return_counts=True)
    feature_cfg = profile["thresholds"]["gradation_and_features"]
    minimum_surface_triangles = int(surface_counts.min())
    feature_score = _score_higher(minimum_surface_triangles, feature_cfg["surface_triangles_bad"], feature_cfg["surface_triangles_good"])
    gradation_score = min(gradation_score, feature_score)
    for surface in surface_values[surface_counts < feature_cfg["surface_triangles_good"]]:
        gradation_problems.update(map(int, eids[mesh["surface_tags"] == surface]))
    gradation_metrics = {
        "adjacent_size_ratio_q99": gradation_q99, "adjacent_size_ratio_max": max(adjacent_ratios, default=1.0),
        "growth_assessment_limit": sizing["growth_assessment_limit"], "small_edge_measure": min((r.get("source_measure") for r in sizing["candidate_rules"] if r["rule"] == "small_edge"), default=None),
        "narrow_gap_detected": sizing["narrow_gap_detected"], "narrow_gap_evidence": sizing["narrow_gap_evidence"], "budget_conflict": sizing["budget_conflict"],
        "post_mesh_budget": sizing["post_mesh_budget"],
        "minimum_triangles_per_geometric_surface": minimum_surface_triangles,
        "geometric_surface_count": int(len(surface_values)),
    }

    fidelity = _geometry_fidelity(mesh, xyz, areas, geometry, sizing, profile)
    topo_metrics = {
        "boundary_edges": boundary_edges, "nonmanifold_edges": len(nonmanifold_groups),
        "inconsistent_orientation_edges": len(inconsistent_groups), "expected_closed": expected_closed,
        "closed_manifold_consistently_oriented": boundary_edges == 0 and not len(nonmanifold_groups) and not len(inconsistent_groups),
    }
    topo_problems = sorted(set(nonmanifold_eids + inconsistent_eids))
    topo_score = 100.0
    if nonmanifold_groups.size or inconsistent_groups.size:
        topo_score = 0.0
    elif expected_closed and boundary_edges:
        topo_score = 0.0
    elif boundary_edges and geometry["analytic_kind"] not in {"plate", "disk"}:
        topo_score = 70.0

    fatal: list[dict[str, Any]] = []
    if not finite:
        fatal.append({"code": "nonfinite_mesh", "message": "mesh contains non-finite values"})
    if np.any(zero_mask):
        fatal.append({"code": "degenerate_triangles", "message": "mesh contains zero-area triangles", "element_ids": eids[zero_mask].astype(int).tolist()})
    if duplicate_rows:
        fatal.append({"code": "duplicate_triangles", "message": "mesh contains duplicate connectivity"})
    if nonmanifold_groups.size:
        fatal.append({"code": "nonmanifold_edges", "message": "edges are shared by more than two triangles", "element_ids": nonmanifold_eids})
    if inconsistent_groups.size:
        fatal.append({"code": "inconsistent_normals", "message": "adjacent triangle winding is inconsistent", "element_ids": inconsistent_eids})
    if expected_closed and boundary_edges:
        fatal.append({"code": "open_volume_boundary", "message": "a solid geometry produced an open surface mesh"})

    scores = {
        "element_shape": _item(shape_score, shape_metrics, "Worst of minimum-angle and lower-tail mean-ratio mappings from the versioned profile.", shape_problems),
        "size_compliance": _item(size_score, size_metrics, "Maps the 95th percentile longest-edge/target ratio independently.", violations),
        "gradation_and_features": _item(gradation_score, gradation_metrics, "Uses adjacent element-size ratios plus triangle coverage of every geometric surface; edge and gap rules remain separate raw evidence.", sorted(gradation_problems)),
        "geometry_fidelity": fidelity,
        "topology_and_normals": _item(topo_score, topo_metrics, "Structural edge incidence and winding checks; closed solid boundaries are required." if expected_closed else "Structural edge incidence and winding checks; open analytic sheets are allowed.", topo_problems),
        "nas_export_integrity": _item(None, {}, "Assessed only after writing and parsing the NAS file.", reason="export has not yet been validated"),
    }
    advice = {
        "element_shape": "Inspect listed low-angle elements and simplify or locally refine nearby geometric details.",
        "size_compliance": "Reduce the target or user cap if the listed elements exceed the intended size envelope.",
        "gradation_and_features": "Refine under-covered surfaces or relax abrupt local size changes near the listed elements.",
        "geometry_fidelity": "Tighten chord tolerance or target size when analytic deviation is above the accepted band.",
        "topology_and_normals": "Repair open, nonmanifold, or inconsistently oriented boundaries before downstream use.",
        "nas_export_integrity": "Regenerate the export and inspect parser evidence before using the file.",
    }
    for name, item in scores.items():
        if item["coverage"] == "not_assessed":
            item["recommendations"] = ["Review the stated coverage limitation and perform an external geometry-reference check when required."]
        elif item["status_band"] != "good":
            item["recommendations"] = [advice[name]]
    budget_evidence = sizing["post_mesh_budget"]
    if budget_evidence["coverage"] == "assessed" and not budget_evidence["budget_met"]:
        scores["gradation_and_features"]["recommendations"].append(
            "The generated triangle count exceeds the configured estimate-based budget; increase the budget or coarsen the geometry settings."
        )
    raw = {
        "node_count": int(len(coords)), "triangle_count": int(len(conn)), "surface_area": float(np.sum(areas)),
        "bbox_min": coords.min(axis=0).tolist(), "bbox_max": coords.max(axis=0).tolist(),
        "element_ids": {"minimum": int(eids.min()), "maximum": int(eids.max())},
    }
    return {"raw_metrics": raw, "scores": scores, "fatal_gates": fatal}


def _geometry_fidelity(mesh: dict[str, Any], xyz: np.ndarray, areas: np.ndarray, geometry: dict[str, Any],
                       sizing: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    kind = geometry["analytic_kind"]
    if kind is None:
        return _item(None, {}, "No generic distance-to-CAD reference is claimed.", reason="imported or CSG geometry has no robust analytic reference in this version")
    p = geometry["analytic_parameters"]
    unit_scale = geometry["explicit_scale"]
    coords = mesh["coordinates"]
    area = float(np.sum(areas))
    volume = abs(float(np.einsum("ij,ij->i", xyz[:, 0], np.cross(xyz[:, 1], xyz[:, 2])).sum() / 6.0))
    expected_area: float
    expected_volume: float | None = None
    chord_error = 0.0
    if kind == "plate":
        expected_area = p["length"] * p["width"] * unit_scale ** 2
    elif kind == "disk":
        expected_area = math.pi * (p["radius"] * unit_scale) ** 2
    elif kind == "sphere":
        radius = p["radius"] * unit_scale
        expected_area = 4 * math.pi * radius ** 2
        expected_volume = 4 * math.pi * radius ** 3 / 3
        origin = np.asarray(p.get("origin", [0, 0, 0]), dtype=float) * unit_scale
        chord_error = float(np.max(np.maximum(0.0, radius - np.linalg.norm(xyz.mean(axis=1) - origin, axis=1))))
    elif kind == "box":
        l, w, h = p["length"] * unit_scale, p["width"] * unit_scale, p["height"] * unit_scale
        expected_area, expected_volume = 2 * (l * w + l * h + w * h), l * w * h
    else:
        r, h = p["radius"] * unit_scale, p["height"] * unit_scale
        expected_area, expected_volume = 2 * math.pi * r * (r + h), math.pi * r * r * h
    area_error = abs(area - expected_area) / expected_area
    volume_error = abs(volume - expected_volume) / expected_volume if expected_volume else None
    tolerance = sizing["chord_tolerance"]
    cfg = profile["thresholds"]["geometry_fidelity"]
    normalized = max(area_error / cfg["area_relative_good"], (volume_error or 0) / cfg["volume_relative_good"], chord_error / tolerance if tolerance else 0)
    score = _score_lower(normalized, 1.0, cfg["bad_multiple"])
    metrics = {
        "analytic_kind": kind, "discrete_area": area, "reference_area": expected_area,
        "area_relative_error": area_error, "discrete_volume": volume if expected_volume else None,
        "reference_volume": expected_volume, "volume_relative_error": volume_error,
        "maximum_centroid_chord_error": chord_error if kind == "sphere" else None,
        "chord_tolerance": tolerance,
    }
    return _item(score, metrics, "Analytic area/volume and, for a sphere, triangle-centroid chord deviation are mapped against profile tolerances.")


def add_nas_result(assessment: dict[str, Any], result: dict[str, Any]) -> None:
    score = 100.0 if result["valid"] else 0.0
    assessment["scores"]["nas_export_integrity"] = _item(
        score, result, "Requires the exact allowed card set, counts, identifiers, connectivity, PIDs, and coordinates to round-trip.",
        result.get("problem_element_ids", []),
    )
    if not result["valid"]:
        assessment["scores"]["nas_export_integrity"]["recommendations"] = ["Do not use the NAS file; regenerate it and resolve every independent-reader mismatch."]
    if not result["valid"]:
        assessment["fatal_gates"].append({"code": "nas_export_invalid", "message": result["message"]})
