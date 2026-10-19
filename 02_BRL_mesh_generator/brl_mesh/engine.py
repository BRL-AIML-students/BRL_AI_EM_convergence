from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import tempfile
import uuid

import gmsh

from . import nas
from .checks import check_plate_geometry
from .config import Configuration
from .errors import ConfigurationError, MeshBlocked
from .improvement import Attempt, improve
from .inspection import MeshContract, cad_boundary_intent, inspect_mesh
from .model import SurfaceMesh, snapshot, assert_current


@contextmanager
def plate_model(config: Configuration):
    """Own one Gmsh session; never clear a model owned by another caller."""
    if gmsh.isInitialized():
        raise RuntimeError("기존 Gmsh session이 있습니다. 독립 프로세스에서 실행하세요")
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('General.NumThreads', 1)
        for dimension in (1, 2, 3):
            gmsh.option.setNumber(f'Mesh.MaxNumThreads{dimension}D', 1)
        gmsh.option.setNumber('Mesh.RandomSeed', 1)
        gmsh.option.setNumber('Mesh.Algorithm', 6)
        gmsh.option.setNumber('Mesh.ElementOrder', 1)
        gmsh.option.setNumber('Mesh.RecombineAll', 0)
        gmsh.option.setNumber('Mesh.MeshSizeFromPoints', 0)
        gmsh.option.setNumber('Mesh.MeshSizeFromCurvature', 0)
        gmsh.option.setNumber('Mesh.MeshSizeExtendFromBoundary', 0)
        gmsh.option.setNumber('Mesh.MeshSizeMin', config.target_size)
        gmsh.option.setNumber('Mesh.MeshSizeMax', config.target_size)
        gmsh.model.add('BRL_plate')
        x, y, z = (v * config.unit_scale for v in config.plate.origin)
        length, width = config.plate.length * config.unit_scale, config.plate.width * config.unit_scale
        if x + length <= x or y + width <= y:
            raise ConfigurationError("좌표 정밀도 범위에서 판의 길이/폭을 표현할 수 없습니다")
        face = gmsh.model.occ.addRectangle(x, y, z, length, width)
        gmsh.model.occ.synchronize()
        gmsh.model.addPhysicalGroup(2, [face], 1)
        gmsh.model.setPhysicalName(2, 1, 'plate')
        gmsh.model.mesh.generate(2)
        yield {face: 1}
    finally:
        gmsh.finalize()


@dataclass(frozen=True)
class RunResult:
    nas_path: Path
    node_count: int
    triangle_count: int
    attempts: tuple[Attempt, ...] = ()


def plate_contract(config: Configuration, membership: dict[int, int]) -> MeshContract:
    if len(membership) != 1 or set(membership.values()) != {1}:
        raise MeshBlocked('현재 CLI는 PID=1의 단일 판만 지원합니다')
    for surface in membership:
        if set(map(int, gmsh.model.getPhysicalGroupsForEntity(2, surface))) != {1}:
            raise MeshBlocked('현재 판의 Physical Group/PID가 변경됐습니다')
    return MeshContract(cad_boundary_intent(1), {surface: 1 for surface in membership}, config.target_size,
                        lambda mesh: check_plate_geometry(mesh, config))


def publish(mesh: SurfaceMesh, config: Configuration) -> RunResult:
    """Publish one NAS after required checks, without overwriting previous runs."""
    assert_current(mesh)
    membership = {int(surface): int(mesh.pids[mesh.surface_tags == surface][0]) for surface in set(mesh.surface_tags)}
    current = snapshot(membership)
    inspect_mesh(current, plate_contract(config, membership)).require_pass()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    run_name = 'run_' + uuid.uuid4().hex
    stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=config.output_dir))
    final = config.output_dir / run_name
    try:
        nas.write(stage / 'mesh.nas', current, config.output_unit)
        nas.validate(stage / 'mesh.nas', current)
        # Same-volume directory rename makes only the verified file visible as a run.
        stage.rename(final)
        return RunResult(final / 'mesh.nas', len(mesh.node_ids), len(mesh.element_ids))
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def run(config: Configuration) -> RunResult:
    with plate_model(config) as membership:
        prepared = improve(membership, plate_contract(config, membership), config.improvement)
        prepared.inspection.require_pass()
        return replace(publish(prepared.mesh, config), attempts=prepared.attempts)
