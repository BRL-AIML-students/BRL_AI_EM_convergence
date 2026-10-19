"""Stage-1 checks for a single rectangle; not generic CAD inspection."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math

import numpy as np

from .config import Configuration
from .errors import MeshBlocked
from .model import SurfaceMesh


@dataclass(frozen=True)
class ShapeValues:
    aspect_ratio_max: float
    minimum_angle_deg: float


def check_shape(mesh: SurfaceMesh) -> ShapeValues:
    """Retain the old two acceptance rules until stage-2 policy validation.

    AR = longest edge * perimeter / (4 sqrt(3) area). No score is computed.
    ICN is probed separately, not added as another production threshold.
    """
    mesh.validate()
    xyz = mesh.triangles()
    scale = float(np.max(np.ptp(mesh.coordinates, axis=0)))
    if not math.isfinite(scale) or scale <= 0:
        raise MeshBlocked("형상 길이 범위가 유효하지 않습니다")
    xyz = (xyz - xyz[:, :1]) / scale
    edges = np.stack([xyz[:, (i + 1) % 3] - xyz[:, i] for i in range(3)], axis=1)
    lengths = np.linalg.norm(edges, axis=2)
    area = np.linalg.norm(np.cross(xyz[:, 1], xyz[:, 2]), axis=1) / 2
    if np.any(area <= 1e-24):
        raise MeshBlocked("형상 크기에 비해 퇴화한 삼각형이 있습니다")
    aspect = lengths.max(axis=1) * lengths.sum(axis=1) / (4 * math.sqrt(3) * area)
    angles = []
    for i in range(3):
        a, b = xyz[:, (i + 1) % 3] - xyz[:, i], xyz[:, (i + 2) % 3] - xyz[:, i]
        angles.append(np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=1), np.einsum('ij,ij->i', a, b))))
    minimum = float(np.min(angles))
    if not np.isfinite(aspect).all() or np.any(aspect > 3.0) or minimum < 20.0:
        raise MeshBlocked("기존 형상 조건 AR ≤ 3, 최소각 ≥ 20°를 만족하지 않습니다")
    return ShapeValues(float(aspect.max()), minimum)


def check_plate(mesh: SurfaceMesh, config: Configuration) -> ShapeValues:
    """Check the expected single open rectangle with its explicit +Z normal."""
    shape = check_shape(mesh)
    origin = np.asarray(config.plate.origin) * config.unit_scale
    length = config.plate.length * config.unit_scale
    width = config.plate.width * config.unit_scale
    size = max(length, width)
    relative = (mesh.coordinates - origin) / size
    lx, ly = length / size, width / size
    tolerance = 1e-9
    if (np.any(relative[:, :2] < -tolerance) or np.any(relative[:, 0] > lx + tolerance)
            or np.any(relative[:, 1] > ly + tolerance) or np.any(np.abs(relative[:, 2]) > tolerance)):
        raise MeshBlocked("메쉬가 지정한 판의 범위를 벗어납니다")
    if len(np.unique(mesh.coordinates, axis=0)) != len(mesh.node_ids):
        raise MeshBlocked("같은 좌표의 분리된 node가 있습니다")
    if len(np.unique(mesh.pids)) != 1 or len(np.unique(mesh.surface_tags)) != 1:
        raise MeshBlocked("현재 단일 판의 PID/surface 분류가 아닙니다")
    xyz = relative[np.searchsorted(mesh.node_ids, mesh.connectivity)]
    cross_z = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])[:, 2]
    if np.any(cross_z <= 0):
        raise MeshBlocked("판의 +Z 기준과 winding이 일치하지 않습니다")
    if not math.isclose(float(cross_z.sum() / 2), lx * ly, rel_tol=1e-9, abs_tol=0):
        raise MeshBlocked("메쉬 면적과 판 면적이 일치하지 않습니다")
    owners: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
    for triangle, nodes in enumerate(mesh.connectivity):
        for i in range(3):
            a, b = int(nodes[i]), int(nodes[(i + 1) % 3])
            owners[tuple(sorted((a, b)))].append((triangle, a, b))
    neighbors = [set() for _ in mesh.element_ids]
    boundary_length = 0.0
    for (a, b), uses in owners.items():
        if len(uses) > 2:
            raise MeshBlocked("nonmanifold edge가 있습니다")
        if len(uses) == 2:
            first, second = uses
            if first[1:] != second[1:][::-1]:
                raise MeshBlocked("공유 edge의 winding이 일치하지 않습니다")
            neighbors[first[0]].add(second[0])
            neighbors[second[0]].add(first[0])
        else:
            ends = relative[np.searchsorted(mesh.node_ids, [a, b])]
            on_boundary = any(np.all(np.abs(ends[:, axis] - limit) <= tolerance)
                              for axis, limit in ((0, 0), (0, lx), (1, 0), (1, ly)))
            if not on_boundary:
                raise MeshBlocked("예상치 못한 열린 경계 또는 T-junction이 있습니다")
            boundary_length += float(np.linalg.norm(ends[1] - ends[0]))
    if not math.isclose(boundary_length, 2 * (lx + ly), rel_tol=1e-9):
        raise MeshBlocked("판의 경계 길이가 일치하지 않습니다")
    visited, pending = {0}, [0]
    while pending:
        for neighbor in neighbors[pending.pop()]:
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    if len(visited) != len(mesh.element_ids):
        raise MeshBlocked("판의 삼각형 연결이 끊어져 있습니다")
    return shape
