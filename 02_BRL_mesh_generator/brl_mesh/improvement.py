"""Bounded node relocation with a fresh verdict and exact coordinate/parameter rollback."""
from __future__ import annotations

from dataclasses import dataclass

import gmsh
import numpy as np

from .config import Improvement
from .errors import MeshBlocked
from .inspection import Inspection, MeshContract, inspect_mesh
from .model import SurfaceMesh, snapshot


@dataclass(frozen=True)
class _Node:
    coordinates: np.ndarray
    parameters: np.ndarray
    dimension: int
    entity: int


def _nodes() -> dict[int, _Node]:
    result = {}
    ids, _, _ = gmsh.model.mesh.getNodes()
    for node in map(int, ids):
        xyz, param, dim, entity = gmsh.model.mesh.getNode(node)
        result[node] = _Node(np.asarray(xyz).copy(), np.asarray(param).copy(), dim, entity)
    return result


def _groups() -> tuple:
    return tuple((dim, tag, tuple(sorted(map(int, gmsh.model.getEntitiesForPhysicalGroup(dim, tag)))))
                 for dim, tag in sorted(gmsh.model.getPhysicalGroups()))


def _elements() -> tuple:
    result = []
    for dimension, entity in gmsh.model.getEntities():
        types, id_blocks, node_blocks = gmsh.model.mesh.getElements(dimension, entity)
        for kind, ids, conn in zip(types, id_blocks, node_blocks):
            if not len(ids):
                continue
            order = np.argsort(ids)
            result.append((dimension, entity, int(kind), tuple(map(int, ids[order])),
                           tuple(map(int, np.asarray(conn).reshape(len(ids), -1)[order].ravel()))))
    return tuple(sorted(result))


@dataclass(frozen=True)
class _State:
    mesh: SurfaceMesh
    nodes: dict[int, _Node]
    groups: tuple
    entities: tuple
    elements: tuple


def _unchanged_structure(state: _State, after: SurfaceMesh) -> dict:
    current = _nodes()
    if (not state.mesh.same_structure(after) or set(current) != set(state.nodes) or _groups() != state.groups
            or tuple(sorted(gmsh.model.getEntities())) != state.entities or _elements() != state.elements
            or any((old.dimension, old.entity) != (current[n].dimension, current[n].entity) for n, old in state.nodes.items())):
        raise MeshBlocked('개선 중 연결·ID·PID·entity 분류가 바뀌었습니다. 발행을 차단합니다')
    return current


def _rollback(state: _State, membership: dict[int, int], contract: MeshContract) -> tuple[SurfaceMesh, Inspection]:
    try:
        _unchanged_structure(state, snapshot(membership, check_validity=False))
        for node, old in state.nodes.items():
            gmsh.model.mesh.setNode(node, old.coordinates.tolist(), old.parameters.tolist())
        restored, current = snapshot(membership), _nodes()
        _unchanged_structure(state, restored)
        if not np.array_equal(state.mesh.coordinates, restored.coordinates) or any(
                not np.array_equal(old.coordinates, current[n].coordinates)
                or not np.array_equal(old.parameters, current[n].parameters) for n, old in state.nodes.items()):
            raise MeshBlocked('좌표/parametric coordinate의 정확한 복구에 실패했습니다')
        inspection = inspect_mesh(restored, contract)
        inspection.require_nonshape_pass()
        return restored, inspection
    except Exception as exc:
        raise MeshBlocked(f'rollback 실패로 발행을 차단합니다: {exc}') from exc


def _not_increased(old: float, new: float, absolute_tolerance: float = 0.0) -> bool:
    if not np.isfinite(old) or not np.isfinite(new):
        return False
    return new <= old + 1e-10 * abs(old) + absolute_tolerance


def _acceptable(before: Inspection, after: Inspection) -> bool:
    if after.issues or not after.icn:
        return False
    shape_preserved = (_not_increased(before.shape.aspect_ratio_max, after.shape.aspect_ratio_max)
                       and _not_increased(-before.shape.minimum_angle_deg, -after.shape.minimum_angle_deg))
    rank_improved = (after.shape.violating_count < before.shape.violating_count
                     or (after.shape.violating_count == before.shape.violating_count
                         and after.minimum_icn > before.minimum_icn + 1e-12))
    preserved = all(_not_increased(old, new) for old, new in (
        (before.edge_max_to_target, after.edge_max_to_target),
        (before.local_edge_max_to_target, after.local_edge_max_to_target),
        (before.deviation_ratio_max, after.deviation_ratio_max),
        (before.topology.adjacent_size_ratio_max, after.topology.adjacent_size_ratio_max)))
    noise = max(before.coordinate_noise, after.coordinate_noise)
    geometry_preserved = all(_not_increased(old, new, noise) for old, new in (
        (before.normals.max_centroid_deviation, after.normals.max_centroid_deviation),
        (before.normals.max_node_deviation, after.normals.max_node_deviation)))
    geometry_preserved = geometry_preserved and _not_increased(
        before.geometry.area_relative_error_max, after.geometry.area_relative_error_max, 64 * np.finfo(float).eps)
    old_volume, new_volume = before.geometry.volume_relative_error_max, after.geometry.volume_relative_error_max
    if old_volume is None:
        geometry_preserved = geometry_preserved and new_volume is None
    else:
        geometry_preserved = (geometry_preserved and new_volume is not None
                              and _not_increased(old_volume, new_volume, 64 * np.finfo(float).eps))
    return (shape_preserved and rank_improved and preserved and geometry_preserved
            and after.minimum_icn >= before.minimum_icn - 1e-12)


@dataclass(frozen=True)
class Attempt:
    method: str
    accepted: bool
    rolled_back: bool


@dataclass(frozen=True)
class ImprovementResult:
    mesh: SurfaceMesh
    inspection: Inspection
    attempts: tuple[Attempt, ...]


def improve(membership: dict[int, int], contract: MeshContract, settings: Improvement) -> ImprovementResult:
    mesh = snapshot(membership)
    inspection = inspect_mesh(mesh, contract)
    # Connectivity/orientation/measurement failures never enter a relocation loop.
    inspection.require_nonshape_pass()
    attempts = []
    passes = settings.max_passes if settings.enabled else 0
    for i in range(passes):
        if inspection.shape.violating_count == 0:
            break
        before, previous = mesh, inspection
        state = _State(before, _nodes(), _groups(), tuple(sorted(gmsh.model.getEntities())), _elements())
        method = ('Relocate2D', 'Laplace2D')[i % 2]
        try:
            gmsh.model.mesh.optimize(method, niter=1, dimTags=[(2, t) for t in sorted(membership)])
            candidate = snapshot(membership, check_validity=False)
            current = _unchanged_structure(state, candidate)
        except Exception as exc:
            # Restore only when the original connectivity/classification still exists.
            _rollback(state, membership, contract)
            raise MeshBlocked(f'개선 실행 실패, 좌표 복구 후 발행 차단: {exc}') from exc
        try:
            after = inspect_mesh(candidate, contract)
        except MeshBlocked:
            mesh, inspection = _rollback(state, membership, contract)
            attempts.append(Attempt(method, False, True))
            continue
        except Exception as exc:
            _rollback(state, membership, contract)
            raise MeshBlocked(f'개선 후 검사 실패, 복구 후 발행 차단: {exc}') from exc
        fixed_nodes_preserved = all(np.array_equal(old.coordinates, current[n].coordinates)
                                    and np.array_equal(old.parameters, current[n].parameters)
                                    for n, old in state.nodes.items() if old.dimension < 2)
        accepted = fixed_nodes_preserved and _acceptable(previous, after)
        if accepted:
            mesh, inspection = candidate, after
        else:
            mesh, inspection = _rollback(state, membership, contract)
        attempts.append(Attempt(method, accepted, not accepted))
    return ImprovementResult(mesh, inspection, tuple(attempts))
