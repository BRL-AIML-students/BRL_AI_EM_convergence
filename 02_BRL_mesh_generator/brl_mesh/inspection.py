"""One current inspection shared by improvement and publication."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import gmsh
import numpy as np

from .checks import ShapeValues, measure_shape
from .errors import MeshBlocked
from .model import SurfaceMesh, assert_current
from .normals import NormalValues, inspect_normals
from .preservation import GeometryValues, measure_geometry
from .quality import read_icn
from .topology import BoundaryIntent, TopologyValues, inspect_topology
from .validation import Issue, require_pass


@dataclass(frozen=True)
class MeshContract:
    boundary: BoundaryIntent
    sheet_signs: dict[int, int]
    target_size: float
    geometry_check: Callable[[SurfaceMesh], None] | None = None


@dataclass(frozen=True)
class Inspection:
    shape: ShapeValues
    icn: dict[int, float]
    topology: TopologyValues
    normals: NormalValues
    geometry: GeometryValues
    issues: tuple[Issue, ...]
    edge_max_to_target: float
    coordinate_noise: float

    @property
    def minimum_icn(self) -> float:
        return min(self.icn.values()) if self.icn else float('-inf')

    def require_nonshape_pass(self) -> None:
        require_pass(self.issues)

    def require_pass(self) -> None:
        self.require_nonshape_pass()
        self.shape.require_pass()


def cad_boundary_intent(expected_components: int, **kwargs) -> BoundaryIntent:
    """Expected open edges come from CAD curves, never the observed triangle holes."""
    try:
        boundary_curves = gmsh.model.getBoundary(gmsh.model.getEntities(2), combined=True, oriented=False)
        edges = set()
        for dimension, curve in boundary_curves:
            if dimension != 1:
                raise ValueError('surface 경계 차원이 유효하지 않습니다')
            types, _, blocks = gmsh.model.mesh.getElements(1, abs(curve))
            for kind, nodes in zip(types, blocks):
                if kind != 1 and len(nodes):
                    raise ValueError('1차 경계 line만 지원합니다')
                edges.update(tuple(sorted(map(int, edge))) for edge in np.asarray(nodes).reshape(-1, 2))
        return BoundaryIntent(frozenset(edges), expected_components, **kwargs)
    except Exception as exc:
        raise MeshBlocked(f'CAD의 예상 경계를 구성하지 못했습니다: {exc}') from exc


def inspect_mesh(mesh: SurfaceMesh, contract: MeshContract) -> Inspection:
    mesh.validate()
    assert_current(mesh)
    shape = measure_shape(mesh)
    topology = inspect_topology(mesh, contract.boundary)
    normals = inspect_normals(mesh, contract.sheet_signs)
    geometry = measure_geometry(mesh)
    issues = list(topology.issues + normals.issues + geometry.issues)
    if not np.isfinite(contract.target_size) or contract.target_size <= 0:
        issues.append(Issue('invalid_target', '목표 길이가 유효하지 않습니다', 'incomplete'))
    if contract.geometry_check is not None:
        try:
            contract.geometry_check(mesh)
        except MeshBlocked as exc:
            issues.append(Issue('geometry_constraints', str(exc)))
        except Exception as exc:
            issues.append(Issue('geometry_incomplete', str(exc), 'incomplete'))
    icn = {}
    if not issues:
        try:
            icn = read_icn(mesh)
            if any(value <= 0 for value in icn.values()):
                issues.append(Issue('element_validity', 'Plugin ICN이 양의 유효 값을 반환하지 않았습니다'))
        except Exception as exc:
            issues.append(Issue('quality_incomplete', str(exc), 'incomplete'))
    xyz = mesh.triangles()
    longest = max(float(np.linalg.norm(xyz[:, (i + 1) % 3] - xyz[:, i], axis=1).max()) for i in range(3))
    ratio = longest / contract.target_size if np.isfinite(contract.target_size) and contract.target_size > 0 else float('inf')
    noise = 64 * np.finfo(float).eps * max(float(np.max(np.abs(mesh.coordinates))), longest)
    return Inspection(shape, icn, topology, normals, geometry, tuple(issues), ratio, noise)
