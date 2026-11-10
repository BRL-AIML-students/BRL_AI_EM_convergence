"""Native ONELAB controls; all numeric work belongs to the shared engine."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import sys
import threading
from time import monotonic

import gmsh

from . import provenance
from .config import CadFile, Configuration, Plate, Ogive, Sphere, Cube, Cylinder, Dihedral
from .engine import Scene, generate, prepare_generated, publish
from .errors import ConfigurationError, MeshBlocked
from .improvement import improve
from .model import SurfaceMesh, assert_current, snapshot
from .quality import add_quality_view
from .sizing_config import Wave, Curvature

PREFIX = 'BRL/'
ACTION = PREFIX + '00 Action'
STATUS = PREFIX + '01 Status'
NAS_PATH = PREFIX + '02 NAS path'
KIND = PREFIX + '10 Geometry'
CAD_PATH = PREFIX + '11 CAD file'
LENGTH = PREFIX + '12 Plate length'
WIDTH = PREFIX + '13 Plate width'
DIAMETER = PREFIX + '15 Ogive diameter D'
OGIVE_LENGTH = PREFIX + '16 Ogive length L'
THICKNESS = PREFIX + '17 Ogive thickness t'
ORIGIN = [PREFIX + f'14 Origin {axis}' for axis in 'XYZ']
SPHERE_RADIUS = PREFIX + 'Geometry/Sphere radius'
CUBE_SIDE = PREFIX + 'Geometry/Cube side'
CYLINDER_RADIUS = PREFIX + 'Geometry/Cylinder radius'
CYLINDER_HEIGHT = PREFIX + 'Geometry/Cylinder height'
DIHEDRAL_LENGTH = PREFIX + 'Geometry/Dihedral length'
DIHEDRAL_WIDTH1 = PREFIX + 'Geometry/Dihedral width 1'
DIHEDRAL_WIDTH2 = PREFIX + 'Geometry/Dihedral width 2'
DIHEDRAL_ANGLE = PREFIX + 'Geometry/Dihedral angle deg'
NATIVE_SHAPES = {
    'sphere': (Sphere, Sphere(1), {'radius': SPHERE_RADIUS}),
    'cube': (Cube, Cube(2), {'side': CUBE_SIDE}),
    'cylinder': (Cylinder, Cylinder(1, 2), {'radius': CYLINDER_RADIUS, 'height': CYLINDER_HEIGHT}),
    'dihedral': (Dihedral, Dihedral(2, 2, 2), {'length': DIHEDRAL_LENGTH,
                  'width1': DIHEDRAL_WIDTH1, 'width2': DIHEDRAL_WIDTH2, 'angle_deg': DIHEDRAL_ANGLE}),
}
GEOMETRY_CHOICES = ['plate', 'ogive', *NATIVE_SHAPES, 'cad']
INPUT_UNIT = PREFIX + '20 Length unit (native and BREP)'
OUTPUT_UNIT = PREFIX + '21 Output unit'
TARGET = PREFIX + '22 Target size (output unit)'
SHEET_SIGN = PREFIX + '23 Sheet direction'
IMPROVE = PREFIX + '30 Improve if needed'
PASSES = PREFIX + '31 Maximum improvement passes'
QUALITY_RETRY = PREFIX + '32 Shape-only generation retry'
OUTPUT = PREFIX + '40 Output folder'
APPLIED_SIZE = PREFIX + '03 Applied global size'
QUALITY_COLORS = PREFIX + '04 Quality colors'
QUALITY_METRICS = ['Off', 'ICN', 'Aspect ratio', 'Radius ratio']
CAP_ENABLED = PREFIX + 'Sizing/Use explicit size cap'
WAVE_ENABLED = PREFIX + 'Sizing/Wavelength enabled'
FREQUENCY = PREFIX + 'Sizing/Frequency Hz'
WAVE_DIV = PREFIX + 'Sizing/Elements per wavelength'
EPSILON = PREFIX + 'Sizing/Relative permittivity'
MU = PREFIX + 'Sizing/Relative permeability'
FALLBACK = PREFIX + 'Sizing/Fallback fraction'
FLOOR_ENABLED = PREFIX + 'Sizing/Minimum size enabled'
FLOOR = PREFIX + 'Sizing/Minimum size (output unit)'
SHORT_ENABLED = PREFIX + 'Local/Short edges enabled'
SHORT_DIV = PREFIX + 'Local/Edge divisions'
WIDTH_ENABLED = PREFIX + 'Local/Widths enabled'
WIDTH_DIV = PREFIX + 'Local/Width divisions'
GAP_ENABLED = PREFIX + 'Local/Gaps enabled'
GAP_DIV = PREFIX + 'Local/Gap divisions'
HOLD_AUTO = PREFIX + 'Local/Automatic hold distance'
HOLD = PREFIX + 'Local/Hold distance (output unit)'
TRANSITION_AUTO = PREFIX + 'Local/Automatic transition'
TRANSITION = PREFIX + 'Local/Transition distance (output unit)'
GROWTH = PREFIX + 'Local/Transition slope'
SAMPLING = PREFIX + 'Local/Distance sampling fraction'
CURVATURE_ENABLED = PREFIX + 'Curvature/Enabled'
ABS_ENABLED = PREFIX + 'Curvature/Absolute tolerance enabled'
ABS_TOL = PREFIX + 'Curvature/Absolute tolerance (output unit)'
REL_ENABLED = PREFIX + 'Curvature/Relative tolerance enabled'
REL_TOL = PREFIX + 'Curvature/Relative tolerance'
CURV_ITERATIONS = PREFIX + 'Curvature/Maximum regenerations'
CURV_SAMPLING = PREFIX + 'Curvature/Sampling nodes per edge'
CURV_VERIFY = PREFIX + 'Curvature/Verification nodes per edge'
CURV_FEEDBACK = PREFIX + 'Curvature/Feedback'
ACTIONS = {0: 'Idle', 1: 'Generate + publish NAS', 2: 'Generate mesh',
           3: 'Improve current mesh', 4: 'Publish current mesh', 5: 'Close', 6: 'Cancel current job',
           7: 'Update quality colors'}
SHEET_DIRECTIONS = {'Not specified': 0, 'CAD normal +': 1, 'CAD normal -': -1}


def _parameter(name, value, **options):
    return {'type': 'string' if isinstance(value, str) else 'number',
            'name': name, 'values': [value], **options}


def install_controls(config: Configuration) -> None:
    is_plate = isinstance(config.geometry, Plate)
    plate = config.geometry if is_plate else Plate(100, 60, (0, 0, 0))
    ogive = config.geometry if isinstance(config.geometry, Ogive) else Ogive(2, 3)
    cad = config.geometry if isinstance(config.geometry, CadFile) else None
    origin = config.geometry.origin if not cad else (0, 0, 0)
    sizing, local = config.sizing, config.sizing.local
    wave = sizing.wave or Wave(1e9)
    curvature = sizing.curvature or Curvature(absolute_tolerance=.01)
    parameters = [
        _parameter(ACTION, ACTIONS[0], choices=list(ACTIONS.values())),
        _parameter(STATUS, 'Ready: choose an Action', readOnly=True),
        _parameter(NAS_PATH, '', readOnly=True),
        _parameter(QUALITY_COLORS, 'Off', choices=QUALITY_METRICS,
                   help='지표를 선택한 뒤 Action → Update quality colors를 실행하세요.'),
        _parameter(KIND, config.to_dict()['geometry']['kind'], choices=GEOMETRY_CHOICES),
        _parameter(CAD_PATH, cad.path.as_posix() if cad else '', kind='file'),
        _parameter(LENGTH, plate.length, min=0), _parameter(WIDTH, plate.width, min=0),
        *[_parameter(name, value) for name, value in zip(ORIGIN, origin)],
        _parameter(DIAMETER, ogive.diameter, min=0), _parameter(OGIVE_LENGTH, ogive.length, min=0),
        _parameter(THICKNESS, ogive.thickness, min=0),
        *[_parameter(control, getattr(config.geometry if isinstance(config.geometry, shape) else default, key),
                     **({'min': 0, 'max': 180} if key == 'angle_deg' else {'min': 0}))
          for shape, default, controls in NATIVE_SHAPES.values() for key, control in controls.items()],
        _parameter(INPUT_UNIT, config.length_unit, choices=['m', 'cm', 'mm', 'um']),
        _parameter(OUTPUT_UNIT, config.output_unit, choices=['m', 'cm', 'mm', 'um']),
        _parameter(TARGET, config.target_size if config.target_size is not None else 1, min=0),
        _parameter(SHEET_SIGN, {v: k for k, v in SHEET_DIRECTIONS.items()}[
                       cad.sheet_normal if cad and cad.sheet_normal else (1 if is_plate else 0)],
                   choices=list(SHEET_DIRECTIONS)),
        _parameter(IMPROVE, int(config.improvement.enabled), choices=[0, 1]),
        _parameter(PASSES, config.improvement.max_passes, min=0, step=1),
        _parameter(QUALITY_RETRY, config.generation.quality_retry, choices=['none', 'delaunay'],
                   help='기본 none. 생성·개선 후 AR/최소각만 실패하면 Algorithm 5로 한 번 재생성합니다.'),
        _parameter(OUTPUT, config.output_dir.as_posix()),
        _parameter(APPLIED_SIZE, 0, readOnly=True),
        _parameter(CAP_ENABLED, int(config.target_size is not None), choices=[0, 1]),
        _parameter(WAVE_ENABLED, int(sizing.wave is not None), choices=[0, 1]),
        _parameter(FREQUENCY, wave.frequency_hz, min=0),
        _parameter(WAVE_DIV, wave.elements_per_wavelength, min=0),
        _parameter(EPSILON, wave.relative_permittivity, min=0),
        _parameter(MU, wave.relative_permeability, min=0),
        _parameter(FALLBACK, sizing.fallback_fraction, min=0, max=1),
        _parameter(FLOOR_ENABLED, int(sizing.minimum_size is not None), choices=[0, 1]),
        _parameter(FLOOR, sizing.minimum_size if sizing.minimum_size is not None else .01, min=0),
        _parameter(SHORT_ENABLED, int(local.short_edges.enabled), choices=[0, 1]),
        _parameter(SHORT_DIV, local.short_edges.divisions, min=1),
        _parameter(WIDTH_ENABLED, int(local.widths.enabled), choices=[0, 1],
                   help='직선 경계의 볼록 평면만 지원합니다. ogive/sphere/cylinder에서는 해제하세요.'),
        _parameter(WIDTH_DIV, local.widths.divisions, min=1),
        _parameter(GAP_ENABLED, int(local.gaps.enabled), choices=[0, 1]),
        _parameter(GAP_DIV, local.gaps.divisions, min=1),
        _parameter(HOLD_AUTO, int(local.hold_distance is None), choices=[0, 1]),
        _parameter(HOLD, local.hold_distance if local.hold_distance is not None else 0, min=0),
        _parameter(TRANSITION_AUTO, int(local.transition_distance is None), choices=[0, 1]),
        _parameter(TRANSITION, local.transition_distance if local.transition_distance is not None else 1, min=0),
        _parameter(GROWTH, local.growth_rate, min=0),
        _parameter(SAMPLING, local.sampling_fraction, min=0, max=.5),
        _parameter(CURVATURE_ENABLED, int(sizing.curvature is not None), choices=[0, 1]),
        _parameter(ABS_ENABLED, int(curvature.absolute_tolerance is not None), choices=[0, 1]),
        _parameter(ABS_TOL, curvature.absolute_tolerance or .01, min=0),
        _parameter(REL_ENABLED, int(curvature.relative_tolerance is not None), choices=[0, 1]),
        _parameter(REL_TOL, curvature.relative_tolerance or .001, min=0),
        _parameter(CURV_ITERATIONS, curvature.max_iterations, min=0, step=1),
        _parameter(CURV_SAMPLING, curvature.sampling_nodes, min=3, step=1),
        _parameter(CURV_VERIFY, curvature.verification_nodes, min=3, step=1),
        _parameter(CURV_FEEDBACK, curvature.feedback, choices=['entity', 'local']),
    ]
    gmsh.onelab.set(json.dumps(parameters, ensure_ascii=False))
    update_visibility()


def visibility_signature():
    return (tuple(gmsh.onelab.getString(KIND)), *(tuple(gmsh.onelab.getNumber(name)) for name in
            [CAP_ENABLED, WAVE_ENABLED, FLOOR_ENABLED, SHORT_ENABLED, WIDTH_ENABLED, GAP_ENABLED,
             HOLD_AUTO, TRANSITION_AUTO, CURVATURE_ENABLED, ABS_ENABLED, REL_ENABLED]))


def update_visibility() -> None:
    kind = _string(KIND)
    is_plate, is_ogive = kind == 'plate', kind == 'ogive'
    visibility = {CAD_PATH: kind == 'cad', SHEET_SIGN: kind == 'cad',
                  **{name: is_plate for name in [LENGTH, WIDTH]},
                  **{name: kind != 'cad' for name in ORIGIN},
                  **{name: is_ogive for name in [DIAMETER, OGIVE_LENGTH, THICKNESS]},
                  **{name: kind == shape for shape, (_, _, controls) in NATIVE_SHAPES.items()
                     for name in controls.values()},
                  TARGET: _flag(CAP_ENABLED), FLOOR: _flag(FLOOR_ENABLED),
                  **{name: _flag(WAVE_ENABLED) for name in [FREQUENCY, WAVE_DIV, EPSILON, MU]},
                  FALLBACK: not _flag(CAP_ENABLED) and not _flag(WAVE_ENABLED),
                  SHORT_DIV: _flag(SHORT_ENABLED), WIDTH_DIV: _flag(WIDTH_ENABLED),
                  GAP_DIV: _flag(GAP_ENABLED), HOLD: not _flag(HOLD_AUTO),
                  TRANSITION: not _flag(TRANSITION_AUTO), GROWTH: _flag(TRANSITION_AUTO)}
    visibility.update({name: _flag(CURVATURE_ENABLED) for name in
                       [ABS_ENABLED, REL_ENABLED, CURV_ITERATIONS, CURV_SAMPLING, CURV_VERIFY, CURV_FEEDBACK]})
    visibility.update({ABS_TOL: _flag(CURVATURE_ENABLED) and _flag(ABS_ENABLED),
                       REL_TOL: _flag(CURVATURE_ENABLED) and _flag(REL_ENABLED)})
    for name, visible in visibility.items():
        # Typed values avoid Gmsh's Windows-path escaping bug in its JSON getter.
        value = _string(name) if name in (CAD_PATH, SHEET_SIGN, CURV_FEEDBACK) else _number(name)
        options = {'kind': 'file'} if name == CAD_PATH else {}
        if name == SHEET_SIGN:
            options['choices'] = list(SHEET_DIRECTIONS)
        elif name == CURV_FEEDBACK:
            options['choices'] = ['entity', 'local']
        elif name in (SHORT_DIV, WIDTH_DIV, GAP_DIV):
            options['min'] = 1
        elif name in (ABS_ENABLED, REL_ENABLED):
            options['choices'] = [0, 1]
        elif name in (CURV_ITERATIONS, CURV_SAMPLING, CURV_VERIFY):
            options.update(min=0 if name == CURV_ITERATIONS else 3, step=1)
        elif name == DIHEDRAL_ANGLE:
            options.update(min=0, max=180)
        elif name != CAD_PATH and name not in ORIGIN:
            options['min'] = 0
        gmsh.onelab.set(json.dumps(_parameter(name, value, visible=visible, **options), ensure_ascii=False))


def _string(name):
    values = gmsh.onelab.getString(name)
    if len(values) != 1:
        raise ConfigurationError(f'{name}: 문자열 한 개가 필요합니다')
    return values[0]


def _number(name):
    values = gmsh.onelab.getNumber(name)
    if len(values) != 1 or not math.isfinite(float(values[0])):
        raise ConfigurationError(f'{name}: 유한한 숫자 한 개가 필요합니다')
    return float(values[0])


def _integer(name):
    value = _number(name)
    if not value.is_integer():
        raise ConfigurationError(f'{name}: 정수가 필요합니다')
    return int(value)


def _flag(name):
    value = _integer(name)
    if value not in (0, 1):
        raise ConfigurationError(f'{name}: 0 또는 1이 필요합니다')
    return bool(value)


def read_controls(base: Configuration, base_dir: Path) -> Configuration:
    value = base.to_dict()
    kind = _string(KIND)
    if kind == 'plate':
        geometry = {'kind': 'plate', 'length': _number(LENGTH), 'width': _number(WIDTH),
                    'origin': [_number(name) for name in ORIGIN]}
    elif kind == 'ogive':
        geometry = {'kind': 'ogive', 'diameter': _number(DIAMETER), 'length': _number(OGIVE_LENGTH),
                    'thickness': _number(THICKNESS), 'origin': [_number(name) for name in ORIGIN]}
    elif kind in NATIVE_SHAPES:
        geometry = {'kind': kind, **{key: _number(name) for key, name in NATIVE_SHAPES[kind][2].items()},
                    'origin': [_number(name) for name in ORIGIN]}
    elif kind == 'cad':
        geometry = value['geometry'] if isinstance(base.geometry, CadFile) else {'kind': 'cad'}
        geometry = geometry | {'path': _string(CAD_PATH)}
        direction = _string(SHEET_SIGN)
        if direction not in SHEET_DIRECTIONS:
            raise ConfigurationError('Sheet direction: 지원하지 않는 기준 방향입니다')
        sign = SHEET_DIRECTIONS[direction]
        if sign == 0:
            geometry.pop('sheet_normal', None)
        else:
            geometry['sheet_normal'] = sign
    else:
        raise ConfigurationError('Geometry: ' + ', '.join(GEOMETRY_CHOICES) + ' 중 하나가 필요합니다')
    enabled = _integer(IMPROVE)
    if enabled not in (0, 1):
        raise ConfigurationError('Improve if needed: 0 또는 1이 필요합니다')
    mesh = value['mesh']
    if _flag(CAP_ENABLED):
        mesh['target_size'] = _number(TARGET)
    else:
        mesh.pop('target_size', None)
    if _flag(WAVE_ENABLED):
        mesh['wave'] = {'frequency_hz': _number(FREQUENCY), 'elements_per_wavelength': _number(WAVE_DIV),
                        'relative_permittivity': _number(EPSILON), 'relative_permeability': _number(MU)}
    else:
        mesh.pop('wave', None)
    mesh['fallback_fraction'] = _number(FALLBACK)
    if _flag(FLOOR_ENABLED):
        mesh['minimum_size'] = _number(FLOOR)
    else:
        mesh.pop('minimum_size', None)
    local = mesh.setdefault('local', {})
    for key, control, division in [('short_edges', SHORT_ENABLED, SHORT_DIV),
                                    ('widths', WIDTH_ENABLED, WIDTH_DIV), ('gaps', GAP_ENABLED, GAP_DIV)]:
        rule = local.setdefault(key, {})
        rule.update(enabled=_flag(control), divisions=_number(division))
    local.update(growth_rate=_number(GROWTH), sampling_fraction=_number(SAMPLING))
    for key, automatic, control in [('hold_distance', HOLD_AUTO, HOLD),
                                     ('transition_distance', TRANSITION_AUTO, TRANSITION)]:
        if _flag(automatic):
            local.pop(key, None)
        else:
            local[key] = _number(control)
    if _flag(CURVATURE_ENABLED):
        curvature = {'feedback': _string(CURV_FEEDBACK), 'max_iterations': _integer(CURV_ITERATIONS), 'sampling_nodes': _integer(CURV_SAMPLING),
                     'verification_nodes': _integer(CURV_VERIFY)}
        if _flag(ABS_ENABLED): curvature['absolute_tolerance'] = _number(ABS_TOL)
        if _flag(REL_ENABLED): curvature['relative_tolerance'] = _number(REL_TOL)
        mesh['curvature'] = curvature
    else:
        mesh.pop('curvature', None)
    value.update(geometry=geometry, length_unit=_string(INPUT_UNIT), output_unit=_string(OUTPUT_UNIT),
                 mesh=mesh, output_dir=_string(OUTPUT),
                 improvement={'enabled': bool(enabled), 'max_passes': _integer(PASSES)},
                 generation={'quality_retry': _string(QUALITY_RETRY)})
    return Configuration.from_dict(value, base_dir)


def display_mesh(*, fit=False):
    """Only generation fits the camera; idle and publication preserve the view."""
    gmsh.model.setVisibility(gmsh.model.getEntities(), 1)
    for name, value in {'Mesh.SurfaceEdges': 1, 'Mesh.SurfaceFaces': 1,
                        'Mesh.Points': 0, 'Geometry.Points': 0, 'Geometry.Curves': 0,
                        'Geometry.Surfaces': 0}.items():
        gmsh.option.setNumber(name, value)
    if fit:
        # OCC synchronize has refreshed Gmsh's model bounding box.
        bounds = gmsh.model.getBoundingBox(-1, -1)
        spans = [bounds[i+3]-bounds[i] for i in range(3)]
        # Gmsh projects the unrotated XY box. Account for the Z extent before
        # applying an oblique view, so a long ogive cannot extend off screen.
        dx, dy = [gmsh.option.getNumber('General.Max'+axis)-gmsh.option.getNumber('General.Min'+axis)
                  for axis in 'XY']
        aspect = gmsh.option.getNumber('General.GraphicsHeight')/gmsh.option.getNumber('General.GraphicsWidth')
        scale = .8*min(max(dx, dy/aspect), max(dy, dx*aspect))/math.hypot(*spans)
        gmsh.option.setNumber('General.Trackball', 0)
        for axis, angle in zip('XYZ', (-60, 0, 30)):
            gmsh.option.setNumber('General.Rotation'+axis, angle)
            gmsh.option.setNumber('General.Translation'+axis, 0)
            gmsh.option.setNumber('General.Scale'+axis, scale)
    if gmsh.fltk.isAvailable():
        gmsh.graphics.draw()


@dataclass(frozen=True)
class _QualityView:
    tag: int
    metric: str
    mesh: SurfaceMesh
    surface_faces: float

    def is_present(self):
        return (self.tag in gmsh.view.getTags() and
                gmsh.view.option.getString(self.tag, 'Name') == f'BRL {self.metric}')


class Controller:
    def __init__(self, base: Configuration, base_dir: Path):
        self.base, self.base_dir = base, base_dir
        self.scene: Scene | None = None
        self.last_mesh = None
        self.quality_view: _QualityView | None = None
        self.next_quality_check = 0.
        self.close_requested = False
        install_controls(base)
        self.visible_state = visibility_signature()
        self.kind = _string(KIND)
        self.ui_dirty = False

    def status(self, message: str, path: str = '') -> None:
        for name, value in ((STATUS, message), (NAS_PATH, path)):
            if gmsh.onelab.getString(name) != [value]:
                gmsh.onelab.setString(name, [value])
                self.ui_dirty = True
        size = self.scene.sizing.global_size if self.scene is not None else 0
        if list(gmsh.onelab.getNumber(APPLIED_SIZE)) != [size]:
            gmsh.onelab.setNumber(APPLIED_SIZE, [size])
            self.ui_dirty = True

    def _clear_quality_view(self):
        view = self.quality_view
        if view is None:
            return
        if view.is_present():
            gmsh.view.remove(view.tag)
        self.quality_view = None
        # Avoid coplanar shading while the view is active; restore the user's
        # previous face setting when releasing the overlay.
        if gmsh.option.getNumber('Mesh.SurfaceFaces') == 0:
            gmsh.option.setNumber('Mesh.SurfaceFaces', view.surface_faces)
        self.ui_dirty = True
        if gmsh.fltk.isAvailable():
            gmsh.graphics.draw()

    def _update_quality_view(self):
        path = _string(NAS_PATH)
        try:
            self._clear_quality_view()
            metric = _string(QUALITY_COLORS)
            if metric not in QUALITY_METRICS:
                raise ConfigurationError('지원하지 않는 품질 표시입니다')
            if metric == 'Off':
                self.status('Quality colors off', path)
                return
            if self.scene is None:
                raise MeshBlocked('현재 생성 결과가 없습니다. 먼저 Generate mesh를 실행하세요')
            self.scene.require_current(read_controls(self.base, self.base_dir))
            mesh = snapshot(self.scene.membership)
            surface_faces = gmsh.option.getNumber('Mesh.SurfaceFaces')
            self.quality_view = _QualityView(add_quality_view(mesh, metric), metric, mesh, surface_faces)
            gmsh.option.setNumber('Mesh.SurfaceFaces', 0)
            self.next_quality_check = monotonic() + 1
            if gmsh.fltk.isAvailable():
                gmsh.graphics.draw()
            self.ui_dirty = True
            self.status(f'Quality colors: {metric}', path)
        except Exception as exc:
            self._clear_quality_view()
            self.status(f'Quality colors blocked: {exc}', path)

    def _check_quality_view(self):
        view = self.quality_view
        if view is None:
            return
        try:
            assert_current(view.mesh)
            if view.is_present():
                return
        except MeshBlocked:
            pass
        self._clear_quality_view()
        if getattr(self, 'job', None) is None:
            self.status('Quality colors cleared: mesh or view changed', _string(NAS_PATH))

    def invalidate_if_changed(self, *, deep=True) -> None:
        try:
            kind = _string(KIND)
            if kind != self.kind:
                self.kind = kind
            state = visibility_signature()
            if state != self.visible_state:
                update_visibility()
                self.visible_state = state
                self.ui_dirty = True
            if self.scene is None:
                return
            current = read_controls(self.base, self.base_dir)
            if not self.scene.cad.matches_config(current):
                raise MeshBlocked('설정이 생성 시점과 다릅니다. 다시 생성하세요')
            if not deep:
                if self.quality_view is not None and monotonic() >= self.next_quality_check:
                    self.next_quality_check = monotonic() + 1
                    self._check_quality_view()
                return
            self.scene.require_current(current)
            self._check_quality_view()
            if self.last_mesh is not None:
                try:
                    assert_current(self.last_mesh)
                except MeshBlocked:
                    # Preserve the CAD reference, discard the previous mesh result.
                    self.last_mesh = None
                    self.status('Mesh changed: next action checks the current mesh')
        except Exception as exc:
            self._clear_quality_view()
            self.scene, self.last_mesh = None, None
            self.status(f'Regenerate required: {exc}')

    def _prepare(self, config: Configuration):
        if self.scene is None:
            raise MeshBlocked('현재 생성 결과가 없습니다. 먼저 Generate mesh를 실행하세요')
        self.scene.require_current(config)
        provenance.require_current(self.scene.generation_provenance, config, self.scene.cad.digest)
        result = improve(self.scene.membership, self.scene.contract, config.improvement)
        self.last_mesh = result.mesh
        result.inspection.require_pass()
        return result.mesh

    def perform(self, action: int) -> None:
        if type(action) is not int or action not in ACTIONS:
            raise ConfigurationError('지원하지 않는 Action입니다')
        if action == 5:
            self.close_requested = True
            return
        if action == 6:
            self.status('No isolated job is running')
            return
        if action == 0:
            return
        if action == 7:
            self._update_quality_view()
            return
        self.invalidate_if_changed(deep=False)
        config = read_controls(self.base, self.base_dir)
        self._perform(action, config)

    def _perform(self, action: int, config: Configuration) -> None:
        self.invalidate_if_changed()
        self.status('Working')
        if action in (1, 2, 3):
            self._clear_quality_view()
        if action in (1, 2):
            self.scene, self.last_mesh = None, None
            gmsh.clear()  # This process owns the complete Gmsh session.
            self.scene = generate(config)
            display_mesh(fit=True)
            self.scene, prepared = prepare_generated(self.scene, config, self.status)
            mesh = self.last_mesh = prepared.mesh
            display_mesh()
            if action == 2:
                self.status('Mesh ready: required checks passed')
                return
        elif action == 3:
            self._prepare(config)
            display_mesh()
            self.status('Current mesh checked; improvement completed if needed')
            return
        else:
            if self.scene is None:
                raise MeshBlocked('현재 생성 결과가 없습니다. 먼저 Generate mesh를 실행하세요')
            self.scene.require_current(config)
            mesh = snapshot(self.scene.membership)
        result = publish(mesh, config, self.scene)
        self.last_mesh = mesh
        warning = ''.join(f'; {item}' for item in result.warnings)
        self.status('NAS published' + warning, str(result.nas_path))

    def dispatch(self) -> None:
        """Consume once; failed or idle events never repeat publication."""
        try:
            choice = _string(ACTION)
            if choice not in ACTIONS.values():
                raise ConfigurationError('지원하지 않는 Action입니다')
            action = {label: code for code, label in ACTIONS.items()}[choice]
            if action == 0:
                return
            gmsh.onelab.setString(ACTION, [ACTIONS[0]])
            self.ui_dirty = True
            self.perform(action)
        except Exception as exc:
            gmsh.onelab.setString(ACTION, [ACTIONS[0]])
            self.ui_dirty = True
            self.status(f'Blocked: {exc}; 이번 실행 NAS 없음')


class AsyncController(Controller):
    """The native window pumps events while another process owns numerical work."""
    def __init__(self, base, base_dir):
        super().__init__(base, base_dir)
        self.job = None
        self.cancel_pending = False
        self.transfer = None
        self.transfer_result = None
        self.close_after_cancel = False
        self.cancel_cause = None

    def perform(self, action):
        if type(action) is not int or action not in ACTIONS:
            raise ConfigurationError('지원하지 않는 Action입니다')
        if action == 5:
            self.close_after_cancel = True
            self.cancel()
            if self.job is None:
                self.close_requested = True
            return
        if action == 6:
            self.cancel()
            return
        if self.job is not None:
            self.status('Working: wait for the current action, or Cancel current job')
            return
        if action == 0:
            return
        if action == 7:
            self._update_quality_view()
            return
        from .native_job import NativeJob
        self.invalidate_if_changed(deep=False)
        config = read_controls(self.base, self.base_dir)
        self.job = NativeJob(config, action, self.scene)
        self.status('Working: starting isolated job')

    def _retain_previous_if_current(self):
        """Retain only a previously checked mesh still matching controls and Gmsh."""
        if self.scene is None or self.last_mesh is None:
            self._clear_quality_view()
            self.scene, self.last_mesh = None, None
            return False
        try:
            self.scene.require_current(read_controls(self.base, self.base_dir))
            assert_current(self.last_mesh)
            return True
        except Exception:
            self._clear_quality_view()
            self.scene, self.last_mesh = None, None
            return False

    def _close_job(self, job):
        # Cleanup failure does not undo a published NAS or invalidate a result.
        try:
            job.close()
            return ''
        except Exception as exc:
            return f'; temporary cleanup failed: {exc}'

    def _finish_job(self, job):
        transfer = self.transfer or getattr(job, 'transfer', None)
        if transfer is not None and not transfer.ready():
            self.transfer = transfer
            transfer.cancel()
            self.cancel_pending = True
            self.status('Cancellation pending: NAS transfer is still stopping')
            return False
        cleanup_error = self._close_job(job)
        try:
            stopped = job.process is None or job.process.poll() is not None
        except Exception:
            stopped = False
        if not stopped:
            self.cancel_pending = True
            self.status(gmsh.onelab.getString(STATUS)[0] +
                        '; worker termination not confirmed; retry Cancel' + cleanup_error,
                        gmsh.onelab.getString(NAS_PATH)[0])
            return False
        self.job = None
        self.cancel_pending = False
        if cleanup_error:
            self.status(gmsh.onelab.getString(STATUS)[0] + cleanup_error,
                        gmsh.onelab.getString(NAS_PATH)[0])
        return True

    def poll(self):
        if self.job is None or self.close_requested:
            return
        if self.cancel_pending:
            if self.transfer is not None and self.transfer.ready():
                self.cancel()
                if self.job is None and self.close_after_cancel:
                    self.close_requested = True
            return
        job = self.job
        adopting = False
        published_path = None
        try:
            if self.transfer is not None:
                if not self.transfer.ready():
                    self.status('Working: transferring validated NAS')
                    return
                if read_controls(self.base, self.base_dir) != job.config:
                    raise MeshBlocked('작업 중 설정이 변경됐습니다. 다시 실행하세요')
                self.scene.require_current(job.config)
                assert_current(self.last_mesh)
                provenance.require_current(self.scene.generation_provenance, job.config, self.scene.cad.digest)
                path = self.transfer.commit()
                published_path = path
                message = 'NAS published' + ''.join(f'; {item}' for item in self.transfer_result.get('warnings', ()))
                self.status(message, path)
                self.transfer = self.transfer_result = None
            else:
                result = job.result()
                if result is None:
                    self.status('Working: '+job.phase())
                    return
                if read_controls(self.base, self.base_dir) != job.config:
                    raise MeshBlocked('작업 중 설정이 변경됐습니다. 다시 실행하세요')
                adopting = True  # adopt can clear or mutate the current Gmsh model.
                if job.action != 4:
                    self._clear_quality_view()
                self.scene, self.last_mesh = job.adopt(result, self.scene)
                if job.action != 4:
                    display_mesh(fit=job.action in (1, 2))
                self.transfer = job.start_publication(result)
                if self.transfer is not None:
                    self.transfer_result = result
                    self.status('Working: transferring validated NAS')
                    return
                message = ('Mesh ready: required checks passed' if job.action == 2 else
                           'Current mesh checked; improvement completed if needed')
                message += ''.join(f'; {item}' for item in result.get('warnings', ()))
                self.status(message)
        except Exception as exc:
            warning = ''
            if self.transfer is not None and not self.transfer.ready():
                self.transfer.cancel()
                self.cancel_pending = True
                self.cancel_cause = str(exc)
                if adopting:
                    self.scene, self.last_mesh = None, None
                self.status(f'Blocked: {exc}; NAS transfer cancellation pending')
                return
            if self.transfer is not None:
                self.transfer.cleanup()
                warning = self.transfer.warning
                self.transfer = self.transfer_result = None
            if adopting:
                self.scene, self.last_mesh = None, None
            else:
                self._retain_previous_if_current()
            if published_path is not None:
                self.status(f'NAS published; completion warning: {exc}' + (f'; {warning}' if warning else ''), published_path)
            else:
                self.status(f'Blocked: {exc}; 이번 실행 NAS 없음' + (f'; {warning}' if warning else ''))
        self._finish_job(job)

    def cancel(self):
        if self.job is None:
            return
        if self.transfer is not None:
            self.transfer.cancel()
            if not self.transfer.ready():
                self.cancel_pending = True
                self.status('Cancellation pending: NAS transfer is still stopping')
                return
            self.transfer.cleanup()
            warning = self.transfer.warning
            self.transfer = self.transfer_result = None
        else:
            warning = ''
        job = self.job
        retained = self._retain_previous_if_current()
        message = (f'Blocked: {self.cancel_cause}; 이번 실행 NAS 없음' if self.cancel_cause else
                   ('Cancelled; previous mesh retained' if retained else 'Cancelled; regenerate required'))
        self.cancel_cause = None
        self.status(message + (f'; {warning}' if warning else ''))
        self._finish_job(job)



def launch(config: Configuration, base_dir: Path) -> None:
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('ONELAB/FLTK는 main thread에서 실행해야 합니다')
    if gmsh.isInitialized():
        raise RuntimeError('기존 Gmsh session이 있습니다. 독립 프로세스에서 실행하세요')
    # Native startup enables wavelength sizing; explicit frequency settings win.
    # Materialize it in the base config so invalidation and workers agree.
    if config.sizing.wave is None:
        config = replace(config, sizing=replace(config.sizing, wave=Wave(1e9)))
    gmsh.initialize(readConfigFiles=False)
    controller = None
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        # Job intermediates use their own local cache; do not persist preferences.
        gmsh.option.setNumber('General.SaveOptions', 0)
        controller = AsyncController(config, base_dir)
        gmsh.fltk.initialize()
        gmsh.fltk.openTreeItem('ONELAB')
        while gmsh.fltk.isAvailable() and not controller.close_requested:
            gmsh.fltk.wait(.05)
            if not gmsh.fltk.isAvailable():
                break
            controller.invalidate_if_changed(deep=False)
            controller.dispatch()
            if hasattr(controller, 'poll'):
                controller.poll()
            # update() rebuilds ONELAB widgets; wait() already pumps UI events.
            if controller.ui_dirty and not controller.close_requested:
                gmsh.fltk.update()
                controller.ui_dirty = False
    finally:
        try:
            if controller is not None and hasattr(controller, 'cancel'):
                controller.cancel()
                if controller.job is not None:
                    process = controller.job.process
                    message = (f'worker termination not confirmed (pid={getattr(process, "pid", "unknown")}): '
                               + gmsh.onelab.getString(STATUS)[0])
                    active_error = sys.exc_info()[1]
                    if active_error is not None:
                        active_error.add_note(message)
                    else:
                        raise RuntimeError(message)
        finally:
            gmsh.finalize()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='BRL native ONELAB 표면 메쉬 생성기')
    parser.add_argument('configuration', nargs='?', default='examples/plate.json')
    args = parser.parse_args(argv)
    try:
        source = Path(args.configuration).resolve()
        launch(Configuration.load(source), source.parent)
        return 0
    except Exception as exc:
        print('; '.join([str(exc), *getattr(exc, '__notes__', ())]), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
