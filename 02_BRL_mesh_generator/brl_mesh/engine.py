from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
import uuid

import gmsh

from . import nas
from .checks import check_plate
from .config import Configuration
from .errors import ConfigurationError
from .model import SurfaceMesh, snapshot


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


def publish(mesh: SurfaceMesh, config: Configuration) -> RunResult:
    """Publish one NAS after required checks, without overwriting previous runs."""
    check_plate(mesh, config)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    run_name = 'run_' + uuid.uuid4().hex
    stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=config.output_dir))
    final = config.output_dir / run_name
    try:
        nas.write(stage / 'mesh.nas', mesh, config.output_unit)
        nas.validate(stage / 'mesh.nas', mesh)
        # Same-volume directory rename makes only the verified file visible as a run.
        stage.rename(final)
        return RunResult(final / 'mesh.nas', len(mesh.node_ids), len(mesh.element_ids))
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def run(config: Configuration) -> RunResult:
    with plate_model(config) as membership:
        return publish(snapshot(membership), config)
