"""CAD ownership, single unit conversion and immutable generation references."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

import gmsh

from .config import CadFile, Configuration, Plate, Ogive, Sphere, Cube, Cylinder, Dihedral
from .errors import ConfigurationError, MeshBlocked

# Explicit OpenCASCADE output-unit identifiers, verified with each importer.
OCC_UNITS = {'m': 'M', 'cm': 'CM', 'mm': 'MM', 'um': 'UM'}


def source_digest(config: Configuration) -> str | None:
    if isinstance(config.geometry, CadFile):
        with config.geometry.path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    return None


def import_cad(geometry: CadFile, config: Configuration) -> None:
    suffix = geometry.path.suffix.lower()
    file_format = {'.step': 'step', '.stp': 'step', '.iges': 'iges', '.igs': 'iges', '.brep': 'brep'}[suffix]
    # Scale the complete imported BREP compound BEFORE Gmsh binds entity tags.
    # Scaling already-bound volume roots can retag their boundary surfaces.
    # The native compound transform includes independent sheets/curves/points.
    gmsh.option.setNumber('Geometry.OCCScaling', config.unit_scale if suffix == '.brep' else 1)
    if file_format == 'iges':
        # Gmsh 4.15.2 calls setTargetUnit BEFORE constructing its IGES reader.
        # In a fresh process the OCC xstep unit table does not exist yet.
        # An explicit disposable read initializes it, without guessing units or
        # retaining geometry from that read. The second read applies the unit.
        current = gmsh.model.getCurrent()
        gmsh.model.add('BRL_IGES_initialization')
        try:
            gmsh.option.setString('Geometry.OCCTargetUnit', '')
            gmsh.model.occ.importShapes(str(geometry.path), highestDimOnly=False, format=file_format)
        finally:
            gmsh.model.remove()
            gmsh.model.setCurrent(current)
    gmsh.option.setString('Geometry.OCCTargetUnit', OCC_UNITS[config.output_unit])
    gmsh.model.occ.importShapes(str(geometry.path), highestDimOnly=False, format=file_format)


def fingerprint() -> tuple:
    """Capture topology and CAD metrics; never use observed triangle openings."""
    result = []
    for dim, tag in sorted(gmsh.model.getEntities()):
        boundary = tuple(gmsh.model.getBoundary([(dim, tag)], combined=False, oriented=True)) if dim else ()
        shape = (tuple(gmsh.model.getValue(0, tag, [])) if dim == 0 else
                 (float(gmsh.model.occ.getMass(dim, tag)), *gmsh.model.occ.getCenterOfMass(dim, tag),
                  *gmsh.model.occ.getMatrixOfInertia(dim, tag)))
        result.append((dim, tag, gmsh.model.getType(dim, tag), boundary,
                       tuple(gmsh.model.getBoundingBox(dim, tag)), shape,
                       tuple(map(int, gmsh.model.getPhysicalGroupsForEntity(dim, tag)))))
    groups = tuple((dim, tag, tuple(map(int, gmsh.model.getEntitiesForPhysicalGroup(dim, tag))))
                   for dim, tag in sorted(gmsh.model.getPhysicalGroups()))
    return gmsh.model.getCurrent(), tuple(gmsh.model.list()), tuple(result), groups


def surface_components() -> tuple[dict[int, int], set[int]]:
    surfaces = [tag for _, tag in gmsh.model.getEntities(2)]
    parents = {tag: tag for tag in surfaces}
    def find(tag):
        while parents[tag] != tag:
            tag = parents[tag]
        return tag
    curves = {}
    for face in surfaces:
        for dim, edge in gmsh.model.getBoundary([(2, face)], combined=False, oriented=False):
            if dim == 1:
                edge = abs(edge)
                if edge in curves:
                    parents[find(face)] = find(curves[edge])
                else:
                    curves[edge] = face
    solid_faces = {abs(tag) for dim, tag in gmsh.model.getBoundary(gmsh.model.getEntities(3),
                   combined=False, oriented=False) if dim == 2} if gmsh.model.getEntities(3) else set()
    return {face: find(face) for face in surfaces}, set(surfaces) - solid_faces


@dataclass(frozen=True)
class CadReference:
    config: Configuration
    membership: dict[int, int]
    components: int
    sheet_signs: dict[int, int]
    signature: tuple
    digest: str | None

    def require_current(self, config: Configuration) -> None:
        if config != self.config:
            raise MeshBlocked('설정이 생성 시점과 다릅니다. 다시 생성하세요')
        try:
            if source_digest(config) != self.digest:
                raise MeshBlocked('입력 CAD 파일이 변경됐습니다. 다시 생성하세요')
            if fingerprint() != self.signature:
                raise MeshBlocked('CAD 또는 Physical Group/PID가 변경됐습니다. 다시 생성하세요')
        except MeshBlocked:
            raise
        except Exception as exc:
            raise MeshBlocked(f'CAD 참조를 재확인하지 못했습니다: {exc}') from exc


def build_geometry(config: Configuration) -> CadReference:
    geometry = config.geometry
    before = source_digest(config)
    gmsh.model.add('BRL_surface')
    if isinstance(geometry, Plate):
        x, y, z = (v * config.unit_scale for v in geometry.origin)
        length, width = geometry.length * config.unit_scale, geometry.width * config.unit_scale
        if x + length <= x or y + width <= y:
            raise ConfigurationError('좌표 정밀도 범위에서 판의 길이/폭을 표현할 수 없습니다')
        face = gmsh.model.occ.addRectangle(x, y, z, length, width)
        signs = {face: 1}
    elif isinstance(geometry, Ogive):
        from .ogive import build
        signs = build(geometry, config.unit_scale)
    elif isinstance(geometry, (Sphere, Cube, Cylinder, Dihedral)):
        from .primitives import build
        signs = build(geometry, config.unit_scale)
    else:
        import_cad(geometry, config)
        signs = dict(geometry.sheet_normals)
    gmsh.model.occ.synchronize()
    membership = {face: face for _, face in sorted(gmsh.model.getEntities(2))}
    if not membership:
        raise ConfigurationError('CAD에 표면이 없습니다. curve/point만으로 NAS를 생성하지 않습니다')
    components, sheets = surface_components()
    if isinstance(geometry, CadFile):
        if set(signs) - sheets:
            raise ConfigurationError('sheet_normals에 없는 sheet 또는 solid 경계 surface가 지정됐습니다')
        if geometry.sheet_normal is not None:
            signs = {face: signs.get(face, geometry.sheet_normal) for face in sheets}
        if sheets - set(signs):
            raise ConfigurationError(f'열린 sheet 기준 방향이 필요합니다: {sorted(sheets - set(signs))}')
        for a, b in geometry.separated_surfaces:
            if a not in components or b not in components or components[a] == components[b]:
                raise ConfigurationError('separated_surfaces는 서로 연결되지 않은 실제 CAD surface 쌍이어야 합니다')
    for face, pid in membership.items():
        gmsh.model.addPhysicalGroup(2, [face], pid)
        gmsh.model.setPhysicalName(2, pid, f'surface_{face}')
    if source_digest(config) != before:
        raise ConfigurationError('읽는 동안 입력 CAD 파일이 변경됐습니다')
    return CadReference(config, membership, len(set(components.values())), signs, fingerprint(), before)
