from __future__ import annotations

from dataclasses import dataclass

import gmsh
import numpy as np

from .errors import MeshBlocked


@dataclass(frozen=True)
class SurfaceMesh:
    node_ids: np.ndarray
    coordinates: np.ndarray
    element_ids: np.ndarray
    connectivity: np.ndarray
    pids: np.ndarray
    surface_tags: np.ndarray

    def same_structure(self, other: SurfaceMesh) -> bool:
        return all(np.array_equal(getattr(self, name), getattr(other, name)) for name in
                   ('node_ids', 'element_ids', 'connectivity', 'pids', 'surface_tags'))

    def triangles(self) -> np.ndarray:
        return self.coordinates[np.searchsorted(self.node_ids, self.connectivity)]

    def validate(self) -> None:
        if self.node_ids.ndim != 1 or self.element_ids.ndim != 1:
            raise MeshBlocked("node/element ID는 1차원 배열이어야 합니다")
        n, m = len(self.node_ids), len(self.element_ids)
        if n < 3 or m < 1:
            raise MeshBlocked("비어 있거나 불완전한 표면 메쉬입니다")
        if self.coordinates.shape != (n, 3) or self.connectivity.shape != (m, 3):
            raise MeshBlocked("좌표 또는 삼각형 연결 배열의 크기가 잘못됐습니다")
        arrays = (self.node_ids, self.element_ids, self.connectivity, self.pids, self.surface_tags)
        if any(not np.issubdtype(a.dtype, np.integer) for a in arrays):
            raise MeshBlocked("ID와 연결은 정수여야 합니다")
        if self.node_ids.ndim != 1 or self.element_ids.ndim != 1 or any(a.shape != (m,) for a in (self.pids, self.surface_tags)):
            raise MeshBlocked("ID·PID·surface 배열의 크기가 잘못됐습니다")
        if any(np.any(a <= 0) for a in arrays) or not np.isfinite(self.coordinates).all():
            raise MeshBlocked("유한 좌표와 양의 ID가 필요합니다")
        if np.any(self.node_ids[1:] <= self.node_ids[:-1]) or np.any(self.element_ids[1:] <= self.element_ids[:-1]):
            raise MeshBlocked("node/element ID는 중복 없이 정렬돼야 합니다")
        used = np.unique(self.connectivity)
        if not np.array_equal(used, self.node_ids):
            raise MeshBlocked("누락 참조 또는 사용되지 않는 node가 있습니다")
        sorted_conn = np.sort(self.connectivity, axis=1)
        if np.any(np.diff(sorted_conn, axis=1) == 0):
            raise MeshBlocked("삼각형에 같은 node가 반복됩니다")
        if len(np.unique(sorted_conn, axis=0)) != m:
            raise MeshBlocked("중복 삼각형이 있습니다")
        xyz = self.triangles()
        double_area = np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1)
        if not np.isfinite(double_area).all() or np.any(double_area <= 0):
            raise MeshBlocked("퇴화 또는 수치 범위를 초과한 삼각형이 있습니다")


def snapshot(surface_pid: dict[int, int], *, check_validity: bool = True) -> SurfaceMesh:
    blocks = []
    for _, surface in sorted(gmsh.model.getEntities(2)):
        if surface not in surface_pid:
            raise MeshBlocked("분류되지 않은 CAD surface가 있습니다")
        types, element_blocks, node_blocks = gmsh.model.mesh.getElements(2, surface)
        if not any(len(elements) for elements in element_blocks):
            raise MeshBlocked(f'CAD surface {surface}의 삼각형이 누락됐습니다')
        for element_type, elements, nodes in zip(types, element_blocks, node_blocks):
            if not len(elements):
                continue
            if element_type != 2:
                raise MeshBlocked("1차 삼각형 표면 요소만 지원합니다")
            blocks.append((np.asarray(elements, dtype=np.int64),
                           np.asarray(nodes, dtype=np.int64).reshape(-1, 3),
                           np.full(len(elements), surface_pid[surface], dtype=np.int64),
                           np.full(len(elements), surface, dtype=np.int64)))
    if not blocks:
        raise MeshBlocked("표면 삼각형이 생성되지 않았습니다")
    elements, conn, pids, surfaces = (np.concatenate([b[i] for b in blocks]) for i in range(4))
    order = np.argsort(elements)
    node_ids, coordinates, _ = gmsh.model.mesh.getNodes()
    node_ids = np.asarray(node_ids, dtype=np.int64)
    coordinates = np.asarray(coordinates, dtype=float).reshape(-1, 3)
    node_order = np.argsort(node_ids)
    node_ids, coordinates = node_ids[node_order], coordinates[node_order]
    used = np.unique(conn)
    indices = np.searchsorted(node_ids, used)
    if np.any(indices >= len(node_ids)) or not np.array_equal(node_ids[indices], used):
        raise MeshBlocked("생성 메쉬에 누락된 node 참조가 있습니다")
    mesh = SurfaceMesh(used, coordinates[indices], elements[order], conn[order], pids[order], surfaces[order])
    if check_validity:
        mesh.validate()
    return mesh


def assert_current(mesh: SurfaceMesh) -> None:
    """Reject stale coordinates, connectivity, IDs or surface classification."""
    if not gmsh.isInitialized():
        raise MeshBlocked('현재 Gmsh model이 없습니다')
    membership = {}
    for surface in set(map(int, mesh.surface_tags)):
        pids = np.unique(mesh.pids[mesh.surface_tags == surface])
        if len(pids) != 1:
            raise MeshBlocked('한 surface의 PID 분류가 유일하지 않습니다')
        membership[surface] = int(pids[0])
    current = snapshot(membership)
    if not current.same_structure(mesh) or not np.array_equal(current.coordinates, mesh.coordinates):
        raise MeshBlocked('검사 대상 snapshot이 현재 메쉬와 일치하지 않습니다')
