from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError
from .schema import object_value as _object, number as _number
from .sizing_config import Sizing, parse_sizing

UNIT_METRES = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6}


def _unit(value: object, name: str) -> str:
    if not isinstance(value, str) or value not in UNIT_METRES:
        raise ConfigurationError(f"{name}: m, cm, mm, um 중 하나를 사용하세요")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(f"JSON 키 중복: {key}")
        result[key] = value
    return result


@dataclass(frozen=True)
class Plate:
    length: float
    width: float
    origin: tuple[float, float, float]


@dataclass(frozen=True)
class CadFile:
    path: Path
    sheet_normal: int | None = None
    sheet_normals: tuple[tuple[int, int], ...] = ()
    separated_surfaces: frozenset[tuple[int, int]] = frozenset()
    protected_gap: float | None = None


@dataclass(frozen=True)
class Improvement:
    enabled: bool = True
    max_passes: int = 3

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.max_passes) is not int or not 0 <= self.max_passes <= 10:
            raise ConfigurationError('improvement: enabled는 bool, max_passes는 0–10 정수여야 합니다')


@dataclass(frozen=True)
class Configuration:
    geometry: Plate | CadFile
    length_unit: str
    output_unit: str
    target_size: float | None
    output_dir: Path
    improvement: Improvement = Improvement()
    sizing: Sizing = Sizing()

    @property
    def unit_scale(self) -> float:
        return UNIT_METRES[self.length_unit] / UNIT_METRES[self.output_unit]

    def to_dict(self) -> dict:
        geometry = self.geometry
        if isinstance(geometry, Plate):
            value = {'kind': 'plate', 'length': geometry.length, 'width': geometry.width,
                     'origin': list(geometry.origin)}
        else:
            value = {'kind': 'cad', 'path': str(geometry.path)}
            if geometry.sheet_normal is not None:
                value['sheet_normal'] = geometry.sheet_normal
            if geometry.sheet_normals:
                value['sheet_normals'] = {str(k): v for k, v in geometry.sheet_normals}
            if geometry.separated_surfaces:
                value['separated_surfaces'] = [list(pair) for pair in sorted(geometry.separated_surfaces)]
            if geometry.protected_gap is not None:
                value['protected_gap'] = geometry.protected_gap
        return {'schema_version': 1, 'geometry': value, 'length_unit': self.length_unit,
                'output_unit': self.output_unit, 'mesh': self.sizing.to_dict(self.target_size),
                'improvement': {'enabled': self.improvement.enabled, 'max_passes': self.improvement.max_passes},
                'output_dir': str(self.output_dir)}

    @classmethod
    def from_dict(cls, value: object, base_dir: Path | None = None) -> Configuration:
        root = _object(value, {"schema_version", "geometry", "length_unit", "output_unit", "mesh", "output_dir", "improvement"},
                       {"schema_version", "geometry", "mesh"}, "configuration")
        if type(root["schema_version"]) is not int or root["schema_version"] != 1:
            raise ConfigurationError("schema_version: 현재 지원하는 버전은 정수 1입니다")
        geometry = _geometry(root['geometry'], base_dir or Path.cwd())
        target, sizing = parse_sizing(root['mesh'])
        improvement = _object(root.get('improvement', {}), {'enabled', 'max_passes'}, set(), 'improvement')
        enabled, passes = improvement.get('enabled', True), improvement.get('max_passes', 3)
        output = root.get("output_dir", "outputs")
        if not isinstance(output, str) or not output.strip():
            raise ConfigurationError("output_dir: 비어 있지 않은 경로 문자열이 필요합니다")
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = (base_dir or Path.cwd()) / output_path
        config = cls(geometry, _unit(root.get("length_unit", "mm"), "length_unit"),
                     _unit(root.get("output_unit", "mm"), "output_unit"),
                     target, output_path.resolve(), Improvement(enabled, passes), sizing)
        if isinstance(geometry, Plate):
            scaled = [geometry.length * config.unit_scale, geometry.width * config.unit_scale,
                      *(x * config.unit_scale for x in geometry.origin)]
            if not all(math.isfinite(x) for x in scaled) or min(scaled[:2]) <= 0:
                raise ConfigurationError("단위 변환 결과가 유효하지 않습니다")
        return config

    @classmethod
    def load(cls, path: str | Path) -> Configuration:
        source = Path(path).resolve()
        try:
            value = json.loads(source.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"설정 파일을 읽을 수 없습니다: {exc}") from exc
        return cls.from_dict(value, source.parent)


def _sign(value: object, name: str) -> int:
    if type(value) is not int or value not in (-1, 1):
        raise ConfigurationError(f'{name}: CAD parameter normal에 대한 정수 +1/-1이 필요합니다')
    return value


def _surface_id(value: object) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or value != str(int(value)) or int(value) < 1:
        raise ConfigurationError('sheet_normals: key는 양의 surface tag 문자열이어야 합니다')
    return int(value)


def _geometry(value: object, base: Path) -> Plate | CadFile:
    if not isinstance(value, dict):
        raise ConfigurationError('geometry: object가 필요합니다')
    if value.get('kind') == 'plate':
        geometry = _object(value, {'kind', 'length', 'width', 'origin'}, {'kind', 'length', 'width'}, 'geometry')
        origin = geometry.get('origin', [0, 0, 0])
        if not isinstance(origin, (list, tuple)) or len(origin) != 3:
            raise ConfigurationError('geometry.origin: 좌표 3개가 필요합니다')
        return Plate(_number(geometry['length'], 'geometry.length', positive=True),
                     _number(geometry['width'], 'geometry.width', positive=True),
                     tuple(_number(x, 'geometry.origin') for x in origin))
    if value.get('kind') != 'cad':
        raise ConfigurationError('geometry.kind: plate 또는 cad를 사용하세요')
    geometry = _object(value, {'kind', 'path', 'sheet_normal', 'sheet_normals', 'separated_surfaces', 'protected_gap'},
                       {'kind', 'path'}, 'geometry')
    path = geometry['path']
    if not isinstance(path, str) or not path.strip():
        raise ConfigurationError('geometry.path: CAD 경로 문자열이 필요합니다')
    source = (base / path).resolve()
    if source.suffix.lower() not in {'.step', '.stp', '.iges', '.igs', '.brep'} or not source.is_file():
        raise ConfigurationError('geometry.path: 존재하는 STEP/IGES/BREP 파일이 필요합니다')
    default = _sign(geometry['sheet_normal'], 'sheet_normal') if 'sheet_normal' in geometry else None
    normals = geometry.get('sheet_normals', {})
    if not isinstance(normals, dict):
        raise ConfigurationError('sheet_normals: surface tag와 +1/-1의 object가 필요합니다')
    signs = tuple(sorted((_surface_id(k), _sign(v, 'sheet_normals')) for k, v in normals.items()))
    pairs = geometry.get('separated_surfaces', [])
    if not isinstance(pairs, list):
        raise ConfigurationError('separated_surfaces: surface tag 쌍의 배열이 필요합니다')
    normalized = set()
    for pair in pairs:
        if (not isinstance(pair, list) or len(pair) != 2 or
                any(type(tag) is not int or tag < 1 for tag in pair) or pair[0] == pair[1]):
            raise ConfigurationError('separated_surfaces: 서로 다른 양의 정수 surface tag 2개가 필요합니다')
        key = tuple(sorted(pair))
        if key in normalized:
            raise ConfigurationError('separated_surfaces: 중복 쌍입니다')
        normalized.add(key)
    gap = _number(geometry['protected_gap'], 'protected_gap', positive=True) if 'protected_gap' in geometry else None
    if gap is not None and not normalized:
        raise ConfigurationError('protected_gap: separated_surfaces 지정이 필요합니다')
    return CadFile(source, default, signs, frozenset(normalized), gap)
