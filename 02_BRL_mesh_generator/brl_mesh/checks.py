"""The retained AR/angle acceptance policy and separate plate geometry checks."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .config import Configuration
from .errors import MeshBlocked
from .model import SurfaceMesh


@dataclass(frozen=True)
class ShapeValues:
    aspect_ratios: np.ndarray
    minimum_angles: np.ndarray

    @property
    def aspect_ratio_max(self) -> float:
        return float(self.aspect_ratios.max())

    @property
    def minimum_angle_deg(self) -> float:
        return float(self.minimum_angles.min())

    @property
    def violating_count(self) -> int:
        return int(np.count_nonzero((self.aspect_ratios > 3.0) | (self.minimum_angles < 20.0)))

    def require_pass(self) -> None:
        if self.violating_count:
            raise MeshBlocked('형상 조건 AR ≤ 3, 최소각 ≥ 20°를 만족하지 않습니다')


def measure_shape(mesh: SurfaceMesh) -> ShapeValues:
    """AR=Lmax*perimeter/(4 sqrt(3) area); policy is not an ICN conversion."""
    mesh.validate()
    xyz = mesh.triangles()
    scale = float(np.max(np.ptp(mesh.coordinates, axis=0)))
    if not math.isfinite(scale) or scale <= 0:
        raise MeshBlocked('형상 길이 범위가 유효하지 않습니다')
    xyz = (xyz - xyz[:, :1]) / scale
    edges = np.stack([xyz[:, (i + 1) % 3] - xyz[:, i] for i in range(3)], axis=1)
    lengths = np.linalg.norm(edges, axis=2)
    area = np.linalg.norm(np.cross(xyz[:, 1], xyz[:, 2]), axis=1) / 2
    if np.any(area <= 1e-24):
        raise MeshBlocked('형상 크기에 비해 퇴화한 삼각형이 있습니다')
    aspect = lengths.max(axis=1) * lengths.sum(axis=1) / (4 * math.sqrt(3) * area)
    angles = []
    for i in range(3):
        a, b = xyz[:, (i + 1) % 3] - xyz[:, i], xyz[:, (i + 2) % 3] - xyz[:, i]
        angles.append(np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=1), np.einsum('ij,ij->i', a, b))))
    if not np.isfinite(aspect).all() or not np.isfinite(angles).all():
        raise MeshBlocked('형상 품질 계산이 유한하지 않습니다')
    return ShapeValues(aspect, np.min(angles, axis=0))


def check_shape(mesh: SurfaceMesh) -> ShapeValues:
    values = measure_shape(mesh)
    values.require_pass()
    return values


def check_plate_geometry(mesh: SurfaceMesh, config: Configuration) -> None:
    """Only the configured plane/extent/area, not topology or normal orientation."""
    mesh.validate()
    origin = np.asarray(config.geometry.origin) * config.unit_scale
    length, width = config.geometry.length * config.unit_scale, config.geometry.width * config.unit_scale
    size = max(length, width)
    relative = (mesh.coordinates - origin) / size
    lx, ly, tolerance = length / size, width / size, 1e-9
    if (np.any(relative[:, :2] < -tolerance) or np.any(relative[:, 0] > lx + tolerance)
            or np.any(relative[:, 1] > ly + tolerance) or np.any(np.abs(relative[:, 2]) > tolerance)):
        raise MeshBlocked('메쉬가 지정한 판의 범위를 벗어납니다')
    xyz = relative[np.searchsorted(mesh.node_ids, mesh.connectivity)]
    area = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1).sum() / 2
    if not math.isclose(float(area), lx * ly, rel_tol=1e-9, abs_tol=0):
        raise MeshBlocked('메쉬 면적과 판 면적이 일치하지 않습니다')
