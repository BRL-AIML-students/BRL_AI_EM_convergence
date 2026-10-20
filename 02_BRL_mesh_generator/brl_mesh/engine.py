from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import tempfile
import uuid

import gmsh

from . import nas
from .cad import CadReference, build_geometry
from .checks import check_plate_geometry
from .config import CadFile, Configuration, Plate
from .improvement import Attempt, improve
from .inspection import MeshContract, cad_boundary_intent, inspect_mesh
from .model import SurfaceMesh, snapshot, assert_current
from .errors import MeshBlocked
from .sizing import SizingPlan, apply_sizing
from .curvature import CurvaturePlan


def boundary_state() -> tuple:
    result = []
    for dim in (0, 1):
        for _, tag in sorted(gmsh.model.getEntities(dim)):
            types, ids, nodes = gmsh.model.mesh.getElements(dim, tag)
            node_ids, coordinates, parameters = gmsh.model.mesh.getNodes(dim, tag)
            result.append((dim, tag, tuple(map(int, types)), tuple(tuple(map(int, b)) for b in ids),
                           tuple(tuple(map(int, b)) for b in nodes), tuple(map(int, node_ids)),
                           tuple(coordinates), tuple(parameters)))
    return tuple(result)


@dataclass(frozen=True)
class Scene:
    cad: CadReference
    contract: MeshContract
    fixed_boundary: tuple
    sizing: SizingPlan
    curvature: CurvaturePlan | None = None

    @property
    def membership(self) -> dict[int, int]:
        return dict(self.cad.membership)

    def require_current(self, config: Configuration) -> None:
        self.cad.require_current(config)
        self.sizing.require_current()
        if boundary_state() != self.fixed_boundary:
            raise MeshBlocked('CAD point/curve mesh가 생성 시점과 다릅니다. 다시 생성하세요')


def configure_mesh(config: Configuration) -> None:
    gmsh.option.setNumber('General.Terminal', 0)
    for key, value in {'RandomSeed': 1, 'Algorithm': 6, 'ElementOrder': 1, 'RecombineAll': 0,
                       'MeshSizeFromPoints': 0, 'MeshSizeFromCurvature': 0,
                       'MeshSizeExtendFromBoundary': 0}.items():
        gmsh.option.setNumber('Mesh.' + key, value)


def generate(config: Configuration) -> Scene:
    """Build in an owned, empty session; shared by the CLI and native UI."""
    if gmsh.model.getEntities():
        raise RuntimeError('생성에는 비어 있는 Gmsh model이 필요합니다')
    configure_mesh(config)
    reference = build_geometry(config)
    sizing = apply_sizing(config)
    curvature = CurvaturePlan(config, sizing) if config.sizing.curvature is not None else None
    for face, sign in reference.sheet_signs.items():
        gmsh.model.mesh.setReverse(2, face, sign < 0)
    while True:
        with curvature.callback() if curvature else nullcontext():
            gmsh.model.mesh.generate(2)
        if curvature is None:
            break
        current = snapshot(reference.membership)
        deviation = curvature.measure(current, curvature.settings.sampling_nodes)
        if deviation.ratio <= 1+1e-10 and curvature.settings.verification_nodes != curvature.settings.sampling_nodes:
            deviation = curvature.measure(current)
        curvature.history.append((len(current.element_ids), deviation.ratio))
        if deviation.ratio <= 1+1e-10:
            break
        curvature.refine(deviation)
        del current, deviation  # Do not retain the previous arrays during regeneration.
        gmsh.model.mesh.clear()
    fixed_boundary = boundary_state()
    def geometry_check(mesh):
        reference.require_current(config)
        sizing.require_current()
        if boundary_state() != fixed_boundary:
            raise MeshBlocked('CAD point/curve mesh가 생성 시점과 다릅니다. 다시 생성하세요')
        if isinstance(config.geometry, Plate):
            check_plate_geometry(mesh, config)
    options = {}
    if isinstance(config.geometry, CadFile):
        options = {'separated_surfaces': config.geometry.separated_surfaces,
                   'protected_gap': config.geometry.protected_gap}
    contract = MeshContract(cad_boundary_intent(reference.components, **options), reference.sheet_signs,
                            sizing.global_size, geometry_check, sizing.local_edge_ratio,
                            curvature.deviation_ratio if curvature else None)
    return Scene(reference, contract, fixed_boundary, sizing, curvature)


@contextmanager
def mesh_model(config: Configuration):
    """Own one Gmsh session; never clear a model owned by another caller."""
    if gmsh.isInitialized():
        raise RuntimeError('기존 Gmsh session이 있습니다. 독립 프로세스에서 실행하세요')
    gmsh.initialize(readConfigFiles=False)
    try:
        yield generate(config)
    finally:
        gmsh.finalize()


@dataclass(frozen=True)
class RunResult:
    nas_path: Path
    node_count: int
    triangle_count: int
    attempts: tuple[Attempt, ...] = ()


def publish(mesh: SurfaceMesh, config: Configuration, scene: Scene) -> RunResult:
    """Reinspect the current mesh against its generation reference before output."""
    assert_current(mesh)
    scene.require_current(config)
    current = snapshot(scene.membership)
    inspect_mesh(current, scene.contract).require_pass()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    geometry = config.to_dict()['geometry']
    dimensions = '_'.join(f'{key}{geometry[key]:g}' for key in
                          ('diameter', 'length', 'thickness', 'radius', 'side', 'height')
                          if key in geometry)
    run_name = f"run_{geometry['kind']}_{dimensions}_{uuid.uuid4().hex}"
    stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=config.output_dir))
    final = config.output_dir / run_name
    try:
        nas.write(stage / 'mesh.nas', current, config.output_unit,
                  geometry=geometry, length_unit=config.length_unit)
        nas.validate(stage / 'mesh.nas', current)
        stage.rename(final)
        return RunResult(final / 'mesh.nas', len(mesh.node_ids), len(mesh.element_ids))
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def run(config: Configuration) -> RunResult:
    with mesh_model(config) as scene:
        prepared = improve(scene.membership, scene.contract, config.improvement)
        prepared.inspection.require_pass()
        return replace(publish(prepared.mesh, config, scene), attempts=prepared.attempts)
