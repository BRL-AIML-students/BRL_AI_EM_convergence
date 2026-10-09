"""Read-only comparison against CAD solid boundaries, including cavity walls."""
from __future__ import annotations

from collections import defaultdict

import gmsh
import numpy as np


def _outward_sign(volume, points, normals, local_size):
    # Surface parametrization and signed boundary tags are not interchangeable
    # with getNormal(). Classify both sides of the actual CAD solid instead.
    for index in np.linspace(0, len(points) - 1, min(3, len(points)), dtype=int):
        point, normal = points[index], normals[index]
        magnitude = np.linalg.norm(normal)
        if not np.isfinite(magnitude) or magnitude == 0:
            continue
        normal = normal / magnitude
        numeric = 64 * np.finfo(float).eps * max(1, np.max(np.abs(point)))
        step = max(local_size * 1e-5, numeric)
        for factor in (1, 10, 100, .1, .01):
            offset = normal * step * factor
            plus = gmsh.model.isInside(3, volume, (point + offset).tolist())
            minus = gmsh.model.isInside(3, volume, (point - offset).tolist())
            if plus == 0 and minus == 1:
                return 1
            if plus == 1 and minus == 0:
                return -1
    raise ValueError("CAD solid classification could not establish the outward side")


def inspect(mesh):
    owners = defaultdict(list)
    occ = set(gmsh.model.occ.getEntities())
    for _, volume in gmsh.model.getEntities(3):
        if (3, volume) in occ:
            for dim, surface in gmsh.model.getBoundary([(3, volume)], oriented=False):
                if dim == 2:
                    owners[surface].append(volume)
    triangles = mesh["coordinates"][np.searchsorted(mesh["node_ids"], mesh["connectivity"])]
    cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    magnitudes = np.linalg.norm(cross, axis=1)
    reversed_ids, ambiguous_ids, records = [], [], []
    checked = 0
    for surface in sorted(owners):
        indices = np.flatnonzero(mesh["surface_tags"] == surface)
        if not len(indices):
            continue
        ids = mesh["element_ids"][indices].astype(int).tolist()
        record = {"surface_tag": surface, "volume_tags": owners[surface], "element_count": len(ids)}
        try:
            if len(owners[surface]) != 1:
                raise ValueError("one surface bounds multiple solids with ambiguous outward intent")
            if not np.all(np.isfinite(triangles[indices])) or np.any(magnitudes[indices] <= 0):
                raise ValueError("invalid triangle coordinates or degenerate normals")
            closest, parameters = gmsh.model.getClosestPoint(2, surface, triangles[indices].mean(axis=1).ravel())
            points = np.asarray(closest).reshape(-1, 3)
            reference = np.asarray(gmsh.model.getNormal(surface, parameters)).reshape(-1, 3)
            if points.shape != (len(indices), 3) or reference.shape != points.shape or not np.all(np.isfinite(points)):
                raise ValueError("incomplete CAD normal projection")
            local_size = float(np.sqrt(np.median(magnitudes[indices])))
            sign = _outward_sign(owners[surface][0], points, reference, local_size)
            norm = np.linalg.norm(reference, axis=1)
            if np.any(norm == 0) or not np.all(np.isfinite(norm)):
                raise ValueError("undefined CAD surface normal")
            cosine = sign * np.einsum("ij,ij->i", cross[indices], reference) / (magnitudes[indices] * norm)
            reversed_ids.extend(mesh["element_ids"][indices[cosine < -1e-8]].astype(int).tolist())
            ambiguous_ids.extend(mesh["element_ids"][indices[np.abs(cosine) <= 1e-8]].astype(int).tolist())
            checked += len(indices)
            record.update(coverage="assessed", minimum_cosine=float(np.min(cosine)))
        except Exception as exc:
            # Gmsh raises plain Exception for unavailable geometric operations.
            ambiguous_ids.extend(ids)
            record.update(coverage="not_assessed", reason=str(exc))
        records.append(record)
    reversed_ids, ambiguous_ids = sorted(set(reversed_ids)), sorted(set(ambiguous_ids))
    gates = []
    if reversed_ids:
        gates.append({"code": "inward_cad_normals", "message": "triangles oppose the outward CAD solid boundary", "element_ids": reversed_ids})
    if ambiguous_ids:
        gates.append({"code": "outward_normals_review_required", "message": "CAD boundary normal direction is ambiguous; export withheld", "element_ids": ambiguous_ids})
    return {
        "coverage": "partial" if ambiguous_ids else "assessed" if records else "not_assessed",
        "method": "CAD projection normals oriented by solid point classification",
        "scope": "CAD solid boundary triangles; open sheets and discrete models have no absolute direction reference",
        "assessed_element_count": checked, "unassessed_element_count": len(triangles) - checked,
        "reversed_element_ids": reversed_ids, "ambiguous_element_ids": ambiguous_ids,
        "surface_results": records,
    }, gates
