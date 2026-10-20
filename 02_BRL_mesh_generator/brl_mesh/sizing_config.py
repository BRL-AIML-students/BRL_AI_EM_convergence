"""User requests only; CAD measurements and applied fields live in sizing.py."""
from dataclasses import asdict, dataclass

from .errors import ConfigurationError
from .schema import object_value as obj, number, integer, boolean


@dataclass(frozen=True)
class Wave:
    frequency_hz: float
    elements_per_wavelength: float = 10
    relative_permittivity: float = 1
    relative_permeability: float = 1


@dataclass(frozen=True)
class Rule:
    enabled: bool = False
    divisions: float = 3
    entities: tuple[int, ...] = ()


@dataclass(frozen=True)
class Gaps:
    enabled: bool = False
    divisions: float = 3
    pairs: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class CurveTarget:
    entity: int
    size: float


@dataclass(frozen=True)
class BoxTarget:
    bounds: tuple[float, ...]
    size: float


@dataclass(frozen=True)
class LocalSizing:
    short_edges: Rule = Rule()
    widths: Rule = Rule()
    gaps: Gaps = Gaps()
    curves: tuple[CurveTarget, ...] = ()
    boxes: tuple[BoxTarget, ...] = ()
    hold_distance: float | None = None
    transition_distance: float | None = None
    growth_rate: float = .3
    sampling_fraction: float = .25


@dataclass(frozen=True)
class Curvature:
    absolute_tolerance: float | None = None
    relative_tolerance: float | None = None
    max_iterations: int = 3
    sampling_nodes: int = 10
    verification_nodes: int = 19


@dataclass(frozen=True)
class Sizing:
    wave: Wave | None = None
    fallback_fraction: float = .1
    minimum_size: float | None = None
    local: LocalSizing = LocalSizing()
    curvature: Curvature | None = None

    def to_dict(self, target):
        result = {}
        if target is not None:
            result['target_size'] = target
        if self.wave is not None:
            result['wave'] = asdict(self.wave)
        if self.minimum_size is not None:
            result['minimum_size'] = self.minimum_size
        if self.fallback_fraction != .1:
            result['fallback_fraction'] = self.fallback_fraction
        if self.local != LocalSizing():
            result['local'] = _json_value(asdict(self.local))
        if self.curvature is not None:
            result['curvature'] = _json_value(asdict(self.curvature))
        return result


def _json_value(value):
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items() if v is not None}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    return value


def _array(value, name):
    if not isinstance(value, list):
        raise ConfigurationError(f'{name}: 배열이 필요합니다')
    return value


def _tags(value, name):
    result = tuple(integer(v, name, high=2_147_483_647) for v in _array(value, name))
    if len(set(result)) != len(result):
        raise ConfigurationError(f'{name}: 중복 entity입니다')
    return result


def _divisions(value, name):
    result = number(value, name, positive=True)
    if result < 1:
        raise ConfigurationError(f'{name}: 1 이상이 필요합니다')
    return result


def _rule(value, name):
    data = obj(value, {'enabled', 'divisions', 'entities'}, set(), name)
    return Rule(boolean(data.get('enabled', False), name),
                _divisions(data.get('divisions', 3), name), _tags(data.get('entities', []), name))


def parse_sizing(value):
    mesh = obj(value, {'target_size', 'wave', 'fallback_fraction', 'minimum_size', 'local', 'curvature'}, set(), 'mesh')
    target = number(mesh['target_size'], 'target_size', positive=True) if 'target_size' in mesh else None
    wave = None
    if 'wave' in mesh:
        data = obj(mesh['wave'], set(Wave.__dataclass_fields__), {'frequency_hz'}, 'wave')
        wave = Wave(**{k: number(v, 'wave.'+k, positive=True) for k, v in data.items()})
    fraction = number(mesh.get('fallback_fraction', .1), 'fallback_fraction', positive=True)
    if fraction > 1:
        raise ConfigurationError('fallback_fraction: 1 이하여야 합니다')
    floor = number(mesh['minimum_size'], 'minimum_size', positive=True) if 'minimum_size' in mesh else None
    local = obj(mesh.get('local', {}), set(LocalSizing.__dataclass_fields__), set(), 'local')
    short = _rule(local.get('short_edges', {}), 'short_edges')
    widths = _rule(local.get('widths', {}), 'widths')
    data = obj(local.get('gaps', {}), {'enabled', 'divisions', 'pairs'}, set(), 'gaps')
    pairs = []
    for pair in _array(data.get('pairs', []), 'gaps.pairs'):
        tags = _tags(pair, 'gaps.pairs')
        if len(tags) != 2:
            raise ConfigurationError('gaps.pairs: 서로 다른 surface tag 2개가 필요합니다')
        key = tuple(sorted(tags))
        if key in pairs:
            raise ConfigurationError('gaps.pairs: 중복 쌍입니다')
        pairs.append(key)
    gaps = Gaps(boolean(data.get('enabled', False), 'gaps.enabled'),
                _divisions(data.get('divisions', 3), 'gaps.divisions'), tuple(pairs))
    curves, boxes = [], []
    for row in _array(local.get('curves', []), 'curves'):
        row = obj(row, {'entity', 'size'}, {'entity', 'size'}, 'curves')
        curves.append(CurveTarget(integer(row['entity'], 'curve.entity', high=2_147_483_647), number(row['size'], 'curve.size', positive=True)))
    if len({c.entity for c in curves}) != len(curves):
        raise ConfigurationError('curves: 중복 entity입니다')
    for row in _array(local.get('boxes', []), 'boxes'):
        row = obj(row, {'bounds', 'size'}, {'bounds', 'size'}, 'boxes')
        bounds = tuple(number(v, 'box.bounds') for v in _array(row['bounds'], 'box.bounds'))
        if len(bounds) != 6 or any(bounds[i] > bounds[i+3] for i in range(3)):
            raise ConfigurationError('box.bounds: xmin,ymin,zmin,xmax,ymax,zmax 순서가 필요합니다')
        boxes.append(BoxTarget(bounds, number(row['size'], 'box.size', positive=True)))
    hold = number(local['hold_distance'], 'hold_distance') if 'hold_distance' in local else None
    if hold is not None and hold < 0:
        raise ConfigurationError('hold_distance: 0 이상이어야 합니다')
    transition = number(local['transition_distance'], 'transition_distance', positive=True) if 'transition_distance' in local else None
    growth = number(local.get('growth_rate', .3), 'growth_rate', positive=True)
    sampling = number(local.get('sampling_fraction', .25), 'sampling_fraction', positive=True)
    if sampling > .5:
        raise ConfigurationError('sampling_fraction: 0.5 이하여야 합니다')
    settings = LocalSizing(short, widths, gaps, tuple(curves), tuple(boxes), hold, transition, growth, sampling)
    curvature = None
    if 'curvature' in mesh:
        data = obj(mesh['curvature'], set(Curvature.__dataclass_fields__), set(), 'curvature')
        tolerances = {key: number(data[key], 'curvature.'+key, positive=True)
                      for key in ('absolute_tolerance', 'relative_tolerance') if key in data}
        if not tolerances:
            raise ConfigurationError('curvature: absolute_tolerance 또는 relative_tolerance가 필요합니다')
        if tolerances.get('relative_tolerance', 0) >= 1:
            raise ConfigurationError('relative_tolerance: 1보다 작아야 합니다')
        sampling = integer(data.get('sampling_nodes', 10), 'sampling_nodes', 3)
        verification = integer(data.get('verification_nodes', 19), 'verification_nodes', 3)
        if verification < sampling:
            raise ConfigurationError('verification_nodes: sampling_nodes 이상이어야 합니다')
        curvature = Curvature(**tolerances,
                              max_iterations=integer(data.get('max_iterations', 3), 'max_iterations', 0),
                              sampling_nodes=sampling, verification_nodes=verification)
    return target, Sizing(wave, fraction, floor, settings, curvature)
