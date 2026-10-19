"""Resolve requested sizes, apply native fields, and audit local relocation scale."""
from __future__ import annotations

from dataclasses import dataclass
import math

import gmsh
import numpy as np

from .config import UNIT_METRES
from .errors import MeshBlocked
from .features import Feature, discover


@dataclass(frozen=True)
class AppliedFeature:
    feature: Feature
    hold: float
    transition: float
    sampling: int = 0


@dataclass(frozen=True)
class FieldBinding:
    tag: int
    kind: str
    numbers: tuple[tuple[str, float], ...] = ()
    lists: tuple[tuple[str, tuple[float, ...]], ...] = ()
    strings: tuple[tuple[str, str], ...] = ()

    def require_current(self):
        field = gmsh.model.mesh.field
        if (field.getType(self.tag) != self.kind or
                any(field.getNumber(self.tag, k) != v for k, v in self.numbers) or
                any(tuple(field.getNumbers(self.tag, k)) != v for k, v in self.lists) or
                any(field.getString(self.tag, k) != v for k, v in self.strings)):
            raise MeshBlocked('size_field_changed: 적용한 크기장이 변경됐습니다. 다시 생성하세요')


@dataclass(frozen=True)
class SizingPlan:
    global_size: float
    minimum_size: float
    sources: tuple[tuple[str, float], ...]
    features: tuple[AppliedFeature, ...]
    fields: tuple[FieldBinding, ...]
    background: int | None
    options: tuple[tuple[str, float], ...]

    def require_current(self):
        if set(map(int, gmsh.model.mesh.field.list())) != {field.tag for field in self.fields}:
            raise MeshBlocked('size_field_changed: 크기장 구성이 변경됐습니다. 다시 생성하세요')
        for field in self.fields:
            field.require_current()
        if any(gmsh.option.getNumber(name) != value for name, value in self.options):
            raise MeshBlocked('size_options_changed: 적용한 크기 옵션이 변경됐습니다. 다시 생성하세요')

    def nominal_sizes(self, coordinates, surfaces=None):
        """Continuous CAD-distance design, not Gmsh's sampled-field evaluator.

        Used only for relocation non-regression. No strict every-edge target or
        EM accuracy assertion is inferred from this midpoint-based audit.
        """
        coordinates = np.asarray(coordinates, dtype=float).reshape(-1, 3)
        result = np.full(len(coordinates), self.global_size)
        work = len(coordinates)*sum(max(1, len(item.feature.curves)) for item in self.features)
        if work > 50_000_000:
            raise MeshBlocked('local_size_audit_incomplete: 국소 크기 감사 작업 한도에 도달했습니다')
        for item in self.features:
            feature = item.feature
            if feature.bounds is not None:
                low = np.asarray(feature.bounds[:3])-item.hold
                high = np.asarray(feature.bounds[3:])+item.hold
                distance = np.linalg.norm(np.maximum(np.maximum(low-coordinates, coordinates-high), 0), axis=1)
                fraction = np.clip(distance/item.transition, 0, 1)
            else:
                distance = np.full(len(coordinates), np.inf)
                for curve in feature.curves:
                    closest, _ = gmsh.model.getClosestPoint(1, curve, coordinates.ravel())
                    closest = np.asarray(closest, dtype=float).reshape(-1, 3)
                    if closest.shape != coordinates.shape or not np.isfinite(closest).all():
                        raise MeshBlocked('local_size_audit_incomplete: CAD curve projection 실패')
                    # In this build getClosestPoint(1) returns correct coordinates
                    # but can leave its parameter output uninitialized. Recover
                    # parameters explicitly from those projected coordinates.
                    parameters = gmsh.model.getParametrization(1, curve, closest.ravel())
                    low, high = gmsh.model.getParametrizationBounds(1, curve)
                    parameters = np.clip(np.asarray(parameters), low[0], high[0])
                    projected = np.asarray(gmsh.model.getValue(1, curve, parameters)).reshape(-1, 3)
                    if projected.shape != coordinates.shape or not np.isfinite(projected).all():
                        raise MeshBlocked('local_size_audit_incomplete: CAD curve projection 실패')
                    distance = np.minimum(distance, np.linalg.norm(coordinates-projected, axis=1))
                fraction = np.clip((distance-item.hold)/item.transition, 0, 1)
            candidate = feature.size + fraction*(self.global_size-feature.size)
            if feature.surface is not None and surfaces is not None:
                candidate = np.where(np.asarray(surfaces) == feature.surface, feature.size, candidate)
            result = np.minimum(result, candidate)
        if not np.isfinite(result).all() or np.any(result <= 0):
            raise MeshBlocked('local_size_audit_incomplete: 유효한 요청 길이를 계산하지 못했습니다')
        return result

    def local_edge_ratio(self, mesh):
        if not self.features:
            return 0.
        xyz = mesh.triangles()
        start = xyz.reshape(-1, 3)
        end = xyz[:, [1, 2, 0]].reshape(-1, 3)
        midpoint = (start+end)/2
        target = self.nominal_sizes(midpoint, np.repeat(mesh.surface_tags, 3))
        return float(np.max(np.linalg.norm(end-start, axis=1)/target))


def resolve_global(config):
    boxes = np.array([gmsh.model.getBoundingBox(2, face) for _, face in gmsh.model.getEntities(2)])
    extent = boxes[:, 3:].max(axis=0)-boxes[:, :3].min(axis=0)
    diameter = float(np.linalg.norm(extent))
    sources = []
    if config.target_size is not None:
        sources.append(('user', config.target_size))
    wave = config.sizing.wave
    if wave is not None:
        length = (299792458/wave.frequency_hz/math.sqrt(wave.relative_permittivity)
                  /math.sqrt(wave.relative_permeability)/wave.elements_per_wavelength/UNIT_METRES[config.output_unit])
        sources.append(('wave', length))
    if not sources:
        sources.append(('fallback', diameter*config.sizing.fallback_fraction))
    if any(not math.isfinite(value) or value <= 0 for _, value in sources):
        raise MeshBlocked('global_size_incomplete: 유효한 전역 크기를 계산하지 못했습니다')
    return min(value for _, value in sources), tuple(sources)


def curve_sampling(curves, size, hold, transition, settings):
    spacing = settings.sampling_fraction*min(size, transition, hold if hold > 0 else size)
    maximum = settings.max_sampling
    if spacing <= 0 or not math.isfinite(spacing):
        raise MeshBlocked('sampling_incomplete: 거리 field 표본 간격을 표현하지 못했습니다')
    requested = 2*max(gmsh.model.occ.getMass(1, c) for c in curves)/spacing
    if not math.isfinite(requested):
        raise MeshBlocked('sampling_incomplete: 필요한 표본 수가 유한 범위를 초과했습니다')
    count = max(8, math.ceil(requested)+2)
    while count <= maximum:
        stable = True
        for curve in curves:
            low, high = gmsh.model.getParametrizationBounds(1, curve)
            points = np.asarray(gmsh.model.getValue(1, curve, np.linspace(low[0], high[0], count))).reshape(-1, 3)
            lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
            mass = gmsh.model.occ.getMass(1, curve)
            if (not np.isfinite(points).all() or not len(lengths) or
                    lengths.max() > spacing or lengths.sum() < .999*mass):
                stable = False
                break
        if stable:
            return count
        count *= 2
    raise MeshBlocked(f'sampling_incomplete: 필요한 Distance.Sampling={count}, 한도={maximum}; 요구를 clamp하지 않습니다')


def apply_sizing(config):
    global_size, sources = resolve_global(config)
    features = discover(config, global_size)
    floor = config.sizing.minimum_size
    minimum = min([global_size, *(feature.size for feature in features)])
    if floor is not None and minimum < floor*(1-1e-12):
        raise MeshBlocked(f'minimum_size_conflict: 필수 요청 {minimum:g} < 하한 {floor:g}')
    if floor is not None:
        minimum = floor
    magnitude = max(abs(float(v)) for _, tag in gmsh.model.getEntities(2) for v in gmsh.model.getBoundingBox(2, tag))
    if minimum < 128*np.finfo(float).eps*magnitude:
        raise MeshBlocked('size_precision_conflict: 요청 길이가 CAD 좌표 정밀도보다 작습니다')
    field, bindings, applied, leaves = gmsh.model.mesh.field, [], [], []
    if len(field.list()):
        raise MeshBlocked('기존 외부 field가 있습니다. 빈 model에서 다시 생성하세요')
    def add(kind, numbers=None, lists=None, strings=None):
        tag = field.add(kind)
        numbers, lists, strings = numbers or {}, lists or {}, strings or {}
        for k, v in numbers.items(): field.setNumber(tag, k, v)
        for k, v in lists.items(): field.setNumbers(tag, k, v)
        for k, v in strings.items(): field.setString(tag, k, v)
        bindings.append(FieldBinding(tag, kind, tuple(numbers.items()),
                                     tuple((k, tuple(v)) for k, v in lists.items()), tuple(strings.items())))
        return tag
    settings = config.sizing.local
    for feature in features:
        hold = settings.hold_distance if settings.hold_distance is not None else feature.size
        transition = (settings.transition_distance if settings.transition_distance is not None else
                      (global_size-feature.size)/settings.growth_rate)
        if not math.isfinite(hold+transition) or transition <= 0 or hold+transition <= hold:
            raise MeshBlocked('transition_incomplete: 유지/전이 거리를 표현하지 못했습니다')
        sampling = 0
        if feature.bounds is not None:
            low, high = np.asarray(feature.bounds[:3])-hold, np.asarray(feature.bounds[3:])+hold
            numbers = {'VIn': feature.size, 'VOut': global_size, 'Thickness': transition,
                       **{axis+'Min': float(value) for axis, value in zip('XYZ', low)},
                       **{axis+'Max': float(value) for axis, value in zip('XYZ', high)}}
            leaves.append(add('Box', numbers))
        else:
            sampling = curve_sampling(feature.curves, feature.size, hold, transition, settings)
            endpoints = sorted({abs(tag) for curve in feature.curves for dim, tag in
                                gmsh.model.getBoundary([(1, curve)], oriented=False) if dim == 0})
            distance = add('Distance', {'Sampling': sampling},
                           {'CurvesList': feature.curves, 'PointsList': endpoints, 'SurfacesList': []})
            leaves.append(add('Threshold', {'InField': distance, 'SizeMin': feature.size, 'SizeMax': global_size,
                                            'DistMin': hold, 'DistMax': hold+transition, 'Sigmoid': 0, 'StopAtDistMax': 0}))
            if feature.surface is not None:
                constant = add('MathEval', strings={'F': format(feature.size, '.17g')})
                leaves.append(add('Restrict', {'InField': constant, 'IncludeBoundary': 1, 'IncludeEmbedded': 1},
                                  {'SurfacesList': [feature.surface], 'CurvesList': [], 'PointsList': [], 'VolumesList': []}))
        applied.append(AppliedFeature(feature, hold, transition, sampling))
    background = None
    if leaves:
        constant = add('MathEval', strings={'F': format(global_size, '.17g')})
        background = add('Min', lists={'FieldsList': [constant, *leaves]})
        field.setAsBackgroundMesh(background)
    options = {'Mesh.MeshSizeMin': minimum, 'Mesh.MeshSizeMax': global_size, 'Mesh.MeshSizeFactor': 1,
               'Mesh.MeshSizeFromPoints': 0, 'Mesh.MeshSizeFromCurvature': 0, 'Mesh.MeshSizeExtendFromBoundary': 0}
    for name, value in options.items(): gmsh.option.setNumber(name, value)
    plan = SizingPlan(global_size, minimum, sources, tuple(applied), tuple(bindings), background, tuple(options.items()))
    plan.require_current()
    return plan
