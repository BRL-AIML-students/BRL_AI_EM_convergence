from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import tempfile
import uuid
import math

import gmsh

from . import nas, provenance
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
    generation_provenance: str | None = None

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
    reference, sizing, curvature = prepare_geometry(config)
    return _generate_candidate(config, reference, sizing, curvature)


def _generate_candidate(config, reference, sizing, curvature):
    """Generate one candidate; exceptions never trigger an algorithm retry."""
    generation_provenance = provenance.capture(config, reference.digest)
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
    return scene_from_current(config, reference, sizing, curvature, generation_provenance)



def prepare_generated(scene, config, phase=None):
    """Check/improve a new mesh, optionally regenerating one shape-only failure.

    Never use for current-mesh actions: regeneration intentionally replaces IDs
    and boundary discretization, whereas relocation preserves those invariants.
    """
    scene.require_current(config)
    generation = provenance.require_current(scene.generation_provenance, config, scene.cad.digest)
    prepared = improve(scene.membership, scene.contract, config.improvement)
    prepared.inspection.require_nonshape_pass()
    if (prepared.inspection.shape.violating_count and config.generation.quality_retry == 'delaunay'
            and generation['configured_options']['Mesh.Algorithm'] == 6):
        if not prepared.inspection.icn or any(not math.isfinite(v) or v <= 0
                                               for v in prepared.inspection.icn.values()):
            raise MeshBlocked('생성 재시도 전 ICN 유효성을 확인하지 못했습니다')
        # Reject stale CAD/field/options before discarding the failed mesh.
        scene.require_current(config)
        provenance.require_current(scene.generation_provenance, config, scene.cad.digest)
        if phase is not None:
            phase('Shape-only failure: regenerating once with requested Algorithm 5')
        gmsh.model.mesh.clear()
        types, ids, _ = gmsh.model.mesh.getElements()
        if any(len(block) for block in ids) or len(gmsh.model.mesh.getNodes()[0]):
            raise MeshBlocked('생성 재시도 전에 이전 mesh를 완전히 제거하지 못했습니다')
        scene.cad.require_current(config)
        scene.sizing.require_current()
        # Do not carry feedback scales, cached samples or failed candidate IDs.
        curvature = CurvaturePlan(config, scene.sizing) if config.sizing.curvature is not None else None
        gmsh.option.setNumber('Mesh.Algorithm', 5)
        scene = _generate_candidate(config, scene.cad, scene.sizing, curvature)
        prepared = improve(scene.membership, scene.contract, config.improvement)
    prepared.inspection.require_pass()
    return scene, prepared


def prepare_geometry(config):
    """Create CAD and fields without generating or inspecting triangles."""
    configure_mesh(config)
    reference = build_geometry(config)
    sizing = apply_sizing(config)
    curvature = CurvaturePlan(config, sizing) if config.sizing.curvature is not None else None
    return reference, sizing, curvature


def scene_from_current(config, reference, sizing, curvature, generation_provenance=None):
    """Bind current curve/point mesh to its independently built CAD reference."""
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
    return Scene(reference, contract, fixed_boundary, sizing, curvature, generation_provenance)


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
    warnings: tuple[str, ...] = ()


def publish(mesh: SurfaceMesh, config: Configuration, scene: Scene) -> RunResult:
    """Reinspect the current mesh against its generation reference before output."""
    assert_current(mesh)
    scene.require_current(config)
    metadata = provenance.require_current(scene.generation_provenance, config, scene.cad.digest)
    current = snapshot(scene.membership)
    inspect_mesh(current, scene.contract).require_pass()
    geometry = config.to_dict()['geometry']
    dimensions = '_'.join(f'{key}{geometry[key]:g}' for key in
                          ('diameter', 'length', 'thickness', 'radius', 'side', 'height')
                          if key in geometry)
    run_name = f"run_{geometry['kind']}_{dimensions}_{uuid.uuid4().hex}"
    cache = Path(__file__).resolve().parent.parent / '.cache' / 'publication'
    cache.mkdir(parents=True, exist_ok=True)
    local = Path(tempfile.mkdtemp(prefix='publish-', dir=cache))
    stage = None
    result = None
    error = None
    warnings = []
    try:
        source = local / 'mesh.nas'
        nas.write(source, current, config.output_unit,
                  geometry=geometry, length_unit=config.length_unit, provenance=metadata)
        nas.validate(source, current, provenance=metadata)
        digest = nas.file_digest(source)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=config.output_dir))
        target = stage / 'mesh.nas'
        shutil.copyfile(source, target)
        if nas.file_digest(target) != digest:
            raise MeshBlocked('NAS 전송 검증이 일치하지 않습니다')
        final = config.output_dir / run_name
        stage.rename(final)
        result = RunResult(final / 'mesh.nas', len(mesh.node_ids), len(mesh.element_ids))
    except BaseException as exc:
        error = exc
    finally:
        for owned in (stage, local):
            if owned is None:
                continue
            try:
                if owned.exists():
                    shutil.rmtree(owned)
            except Exception as exc:
                warnings.append(f'임시 폴더 정리 실패 ({owned}): {exc}')
    if error is not None:
        for warning in warnings:
            error.add_note(warning)
        raise error.with_traceback(error.__traceback__)
    return replace(result, warnings=tuple(warnings))



def run(config: Configuration) -> RunResult:
    with mesh_model(config) as scene:
        scene, prepared = prepare_generated(scene, config)
        return replace(publish(prepared.mesh, config, scene), attempts=prepared.attempts)
