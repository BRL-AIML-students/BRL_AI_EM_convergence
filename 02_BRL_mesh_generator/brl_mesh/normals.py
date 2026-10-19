"""CAD-referenced orientation; element quality cannot certify outward normals."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import gmsh
import numpy as np

from .model import SurfaceMesh
from .validation import Issue


@dataclass(frozen=True)
class NormalValues:
    issues: tuple[Issue, ...]
    max_centroid_deviation: float
    max_node_deviation: float


def _outward_sign(volume: int, point: np.ndarray, normal: np.ndarray, local_length: float) -> int:
    numeric = 64 * np.finfo(float).eps * max(float(np.max(np.abs(point))), local_length)
    step = max(local_length * 1e-5, numeric)
    for factor in (1, 10, 100, .1, .01, .001, 1000):
        offset = normal * step * factor
        plus = gmsh.model.isInside(3, volume, (point + offset).tolist())
        minus = gmsh.model.isInside(3, volume, (point - offset).tolist())
        if plus == 0 and minus == 1:
            return 1
        if plus == 1 and minus == 0:
            return -1
    raise ValueError('CAD solid 양쪽의 안/밖을 구분하지 못했습니다')


def inspect_normals(mesh: SurfaceMesh, sheet_signs: dict[int, int]) -> NormalValues:
    """sheet_signs chooses +1/-1 relative to CAD parametrization, not solid outward.

    Every mesh surface must have exactly one solid owner or an explicit sheet
    reference. Missing CAD operations/direction remain incomplete and block output.
    """
    mesh.validate()
    issues, owners = [], defaultdict(set)
    try:
        for _, volume in gmsh.model.getEntities(3):
            for dim, tag in gmsh.model.getBoundary([(3, volume)], oriented=False):
                if dim == 2:
                    owners[abs(int(tag))].add(int(volume))
    except Exception as exc:
        return NormalValues((Issue('cad_owners_unavailable', str(exc), 'incomplete'),), float('inf'), float('inf'))
    xyz = mesh.triangles()
    cross = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    magnitude = np.linalg.norm(cross, axis=1)
    max_centroid, max_node = 0.0, 0.0
    for surface in sorted(set(map(int, mesh.surface_tags))):
        indices = np.flatnonzero(mesh.surface_tags == surface)
        try:
            if len(owners[surface]) > 1:
                raise ValueError('여러 solid가 공유하는 면의 바깥 방향이 불명확합니다')
            if not owners[surface] and sheet_signs.get(surface) not in (-1, 1):
                raise ValueError('열린 sheet의 기준 방향이 지정되지 않았습니다')
            centroids = xyz[indices].mean(axis=1)
            points, parameters = gmsh.model.getClosestPoint(2, surface, centroids.ravel())
            points = np.asarray(points, dtype=float).reshape(-1, 3)
            reference = np.asarray(gmsh.model.getNormal(surface, parameters), dtype=float).reshape(-1, 3)
            if points.shape != centroids.shape or reference.shape != centroids.shape:
                raise ValueError('CAD projection/normal 결과가 불완전합니다')
            norm = np.linalg.norm(reference, axis=1)
            if not np.isfinite(points).all() or not np.isfinite(norm).all() or np.any(norm <= 0):
                raise ValueError('CAD normal 또는 projection이 유효하지 않습니다')
            reference = reference / norm[:, None]
            local_lengths = np.sqrt(magnitude[indices])
            if owners[surface]:
                volume = next(iter(owners[surface]))
                signs = np.array([_outward_sign(volume, p, n, float(h))
                                  for p, n, h in zip(points, reference, local_lengths)])
            else:
                signs = np.full(len(indices), sheet_signs[surface])
            cosine = signs * np.einsum('ij,ij->i', cross[indices], reference) / magnitude[indices]
            if np.any(cosine < -1e-8):
                issues.append(Issue('inward_normal', f'surface {surface}의 요소가 기준 방향과 반대입니다'))
            if np.any(np.abs(cosine) <= 1e-8):
                issues.append(Issue('normal_ambiguous', f'surface {surface}의 방향을 판정할 수 없습니다', 'incomplete'))
            centroid_error = float(np.linalg.norm(centroids - points, axis=1).max())
            max_centroid = max(max_centroid, centroid_error)
            nodes = np.unique(mesh.connectivity[indices])
            coordinates = mesh.coordinates[np.searchsorted(mesh.node_ids, nodes)]
            projected, _ = gmsh.model.getClosestPoint(2, surface, coordinates.ravel())
            projected = np.asarray(projected, dtype=float).reshape(-1, 3)
            if projected.shape != coordinates.shape or not np.isfinite(projected).all():
                raise ValueError('node CAD projection이 불완전합니다')
            node_error = float(np.linalg.norm(coordinates - projected, axis=1).max())
            max_node = max(max_node, node_error)
            tolerance = max(float(np.median(local_lengths)) * 1e-8,
                            64 * np.finfo(float).eps * float(np.max(np.abs(coordinates))))
            if node_error > tolerance:
                issues.append(Issue('off_cad_nodes', f'surface {surface}에서 node가 CAD 면을 벗어났습니다'))
        except Exception as exc:
            issues.append(Issue('normal_incomplete', f'surface {surface}: {exc}', 'incomplete'))
            max_centroid, max_node = float('inf'), float('inf')
    return NormalValues(tuple(issues), max_centroid, max_node)
