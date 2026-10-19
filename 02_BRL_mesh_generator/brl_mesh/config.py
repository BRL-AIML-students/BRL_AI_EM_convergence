from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError

UNIT_METRES = {"m": 1.0, "cm": 1e-2, "mm": 1e-3, "um": 1e-6}


def _object(value: object, allowed: set[str], required: set[str], name: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name}: object가 필요합니다")
    unknown, missing = set(value) - allowed, required - set(value)
    if unknown or missing:
        raise ConfigurationError(f"{name}: 알 수 없는 키 {sorted(unknown)}, 누락된 키 {sorted(missing)}")
    return value


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ConfigurationError(f"{name}: 유한한 숫자가 필요합니다")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ConfigurationError(f"{name}: 숫자 범위를 초과했습니다") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise ConfigurationError(f"{name}: {'양의 ' if positive else ''}유한한 숫자가 필요합니다")
    return result


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
class Improvement:
    enabled: bool = True
    max_passes: int = 3

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.max_passes) is not int or not 0 <= self.max_passes <= 10:
            raise ConfigurationError('improvement: enabled는 bool, max_passes는 0–10 정수여야 합니다')


@dataclass(frozen=True)
class Configuration:
    plate: Plate
    length_unit: str
    output_unit: str
    target_size: float
    output_dir: Path
    improvement: Improvement = Improvement()

    @property
    def unit_scale(self) -> float:
        return UNIT_METRES[self.length_unit] / UNIT_METRES[self.output_unit]

    @classmethod
    def from_dict(cls, value: object, base_dir: Path | None = None) -> Configuration:
        root = _object(value, {"schema_version", "geometry", "length_unit", "output_unit", "mesh", "output_dir", "improvement"},
                       {"schema_version", "geometry", "mesh"}, "configuration")
        if type(root["schema_version"]) is not int or root["schema_version"] != 1:
            raise ConfigurationError("schema_version: 현재 지원하는 버전은 정수 1입니다")
        geometry = _object(root["geometry"], {"kind", "length", "width", "origin"},
                           {"kind", "length", "width"}, "geometry")
        if geometry["kind"] != "plate":
            raise ConfigurationError("현재 CLI에서는 geometry.kind=plate만 지원합니다")
        origin = geometry.get("origin", [0, 0, 0])
        if not isinstance(origin, (list, tuple)) or len(origin) != 3:
            raise ConfigurationError("geometry.origin: 좌표 3개가 필요합니다")
        plate = Plate(_number(geometry["length"], "geometry.length", positive=True),
                      _number(geometry["width"], "geometry.width", positive=True),
                      tuple(_number(x, "geometry.origin") for x in origin))
        mesh = _object(root["mesh"], {"target_size"}, {"target_size"}, "mesh")
        improvement = _object(root.get('improvement', {}), {'enabled', 'max_passes'}, set(), 'improvement')
        enabled, passes = improvement.get('enabled', True), improvement.get('max_passes', 3)
        output = root.get("output_dir", "outputs")
        if not isinstance(output, str) or not output.strip():
            raise ConfigurationError("output_dir: 비어 있지 않은 경로 문자열이 필요합니다")
        output_path = Path(output)
        if not output_path.is_absolute():
            output_path = (base_dir or Path.cwd()) / output_path
        config = cls(plate, _unit(root.get("length_unit", "mm"), "length_unit"),
                     _unit(root.get("output_unit", "mm"), "output_unit"),
                     _number(mesh["target_size"], "mesh.target_size", positive=True), output_path.resolve(),
                     Improvement(enabled, passes))
        scaled = [plate.length * config.unit_scale, plate.width * config.unit_scale,
                  *(x * config.unit_scale for x in plate.origin)]
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
