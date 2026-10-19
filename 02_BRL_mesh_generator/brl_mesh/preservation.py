"""CAD area/volume evidence consumed by relocation acceptance, not an accuracy score."""
from dataclasses import dataclass

import gmsh
import numpy as np

from .model import SurfaceMesh
from .validation import Issue


@dataclass(frozen=True)
class GeometryValues:
    issues: tuple[Issue, ...]
    area_relative_error_max: float
    volume_relative_error_max: float | None


def measure_geometry(mesh: SurfaceMesh) -> GeometryValues:
    xyz = mesh.triangles()
    cross = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    areas = np.linalg.norm(cross, axis=1) / 2
    errors, volumes = [], []
    try:
        for surface in sorted(set(map(int, mesh.surface_tags))):
            reference = gmsh.model.occ.getMass(2, surface)
            if not np.isfinite(reference) or reference <= 0:
                raise ValueError('CAD 면적을 계산하지 못했습니다')
            measured = float(areas[mesh.surface_tags == surface].sum())
            errors.append(abs(measured - reference) / reference)
        for _, volume in gmsh.model.getEntities(3):
            surfaces = {abs(tag) for dim, tag in gmsh.model.getBoundary([(3, volume)], oriented=False) if dim == 2}
            if not surfaces <= set(map(int, mesh.surface_tags)):
                raise ValueError('solid 경계 일부가 mesh에 없습니다')
            indices = np.flatnonzero(np.isin(mesh.surface_tags, list(surfaces)))
            origin = xyz[indices].reshape(-1, 3).mean(axis=0)
            measured = float(np.einsum('ij,ij->i', xyz[indices, 0] - origin, cross[indices]).sum() / 6)
            reference = gmsh.model.occ.getMass(3, volume)
            if not np.isfinite(reference) or reference <= 0:
                raise ValueError('CAD 체적을 계산하지 못했습니다')
            volumes.append(abs(measured - reference) / reference)
        if not np.isfinite(errors).all() or not np.isfinite(volumes).all():
            raise ValueError('면적/체적 오차가 유한하지 않습니다')
        return GeometryValues((), max(errors), max(volumes) if volumes else None)
    except Exception as exc:
        return GeometryValues((Issue('geometry_evidence_incomplete', str(exc), 'incomplete'),), float('inf'), None)
