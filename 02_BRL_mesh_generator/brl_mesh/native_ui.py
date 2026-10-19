"""Native ONELAB controls; all numeric work belongs to the shared engine."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import threading

import gmsh

from .config import CadFile, Configuration, Plate
from .engine import Scene, generate, publish
from .errors import ConfigurationError, MeshBlocked
from .improvement import improve
from .model import snapshot
from .sizing_config import Wave, Curvature
from .resources import resource_scope

PREFIX = 'BRL/'
ACTION = PREFIX + '00 Action'
STATUS = PREFIX + '01 Status'
NAS_PATH = PREFIX + '02 NAS path'
KIND = PREFIX + '10 Geometry'
CAD_PATH = PREFIX + '11 CAD file'
LENGTH = PREFIX + '12 Plate length'
WIDTH = PREFIX + '13 Plate width'
ORIGIN = [PREFIX + f'14 Origin {axis}' for axis in 'XYZ']
INPUT_UNIT = PREFIX + '20 Length unit (plate and BREP)'
OUTPUT_UNIT = PREFIX + '21 Output unit'
TARGET = PREFIX + '22 Target size (output unit)'
SHEET_SIGN = PREFIX + '23 Sheet direction'
IMPROVE = PREFIX + '30 Improve if needed'
PASSES = PREFIX + '31 Maximum improvement passes'
OUTPUT = PREFIX + '40 Output folder'
APPLIED_SIZE = PREFIX + '03 Applied global size'
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
RESOURCE_CONTROLS = {key: PREFIX+'Resources/'+label for key, label in {
    'max_nodes': 'Maximum nodes', 'max_triangles': 'Maximum triangles',
    'max_memory_mb': 'Process memory limit MiB', 'max_seconds': 'Work time limit seconds',
    'max_projection_samples': 'Maximum projection samples'}.items()}
ACTIONS = {0: 'Idle', 1: 'Generate + publish NAS', 2: 'Generate mesh',
           3: 'Improve current mesh', 4: 'Publish current mesh', 5: 'Close'}
SHEET_DIRECTIONS = {'Not specified': 0, 'CAD normal +': 1, 'CAD normal -': -1}


def _parameter(name, value, **options):
    return {'type': 'string' if isinstance(value, str) else 'number',
            'name': name, 'values': [value], **options}


def install_controls(config: Configuration) -> None:
    is_plate = isinstance(config.geometry, Plate)
    plate = config.geometry if is_plate else Plate(100, 60, (0, 0, 0))
    cad = config.geometry if not is_plate else None
    sizing, local = config.sizing, config.sizing.local
    wave = sizing.wave or Wave(1e9)
    curvature = sizing.curvature or Curvature(absolute_tolerance=.01)
    parameters = [
        _parameter(ACTION, ACTIONS[0], choices=list(ACTIONS.values())),
        _parameter(STATUS, 'Ready: choose an Action', readOnly=True),
        _parameter(NAS_PATH, '', readOnly=True),
        _parameter(KIND, 'plate' if is_plate else 'cad', choices=['plate', 'cad']),
        _parameter(CAD_PATH, cad.path.as_posix() if cad else '', kind='file'),
        _parameter(LENGTH, plate.length, min=0), _parameter(WIDTH, plate.width, min=0),
        *[_parameter(name, value) for name, value in zip(ORIGIN, plate.origin)],
        _parameter(INPUT_UNIT, config.length_unit, choices=['m', 'cm', 'mm', 'um']),
        _parameter(OUTPUT_UNIT, config.output_unit, choices=['m', 'cm', 'mm', 'um']),
        _parameter(TARGET, config.target_size if config.target_size is not None else 1, min=0),
        _parameter(SHEET_SIGN, {v: k for k, v in SHEET_DIRECTIONS.items()}[
                       cad.sheet_normal if cad and cad.sheet_normal else (1 if is_plate else 0)],
                   choices=list(SHEET_DIRECTIONS)),
        _parameter(IMPROVE, int(config.improvement.enabled), choices=[0, 1]),
        _parameter(PASSES, config.improvement.max_passes, min=0, max=10, step=1),
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
        _parameter(WIDTH_ENABLED, int(local.widths.enabled), choices=[0, 1]),
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
        _parameter(CURV_ITERATIONS, curvature.max_iterations, min=0, max=10, step=1),
        _parameter(CURV_SAMPLING, curvature.sampling_nodes, min=3, max=100, step=1),
        _parameter(CURV_VERIFY, curvature.verification_nodes, min=3, max=100, step=1),
        *[_parameter(name, getattr(config.resources, key), min=1 if key not in
                     ('max_seconds', 'max_memory_mb') else 0)
          for key, name in RESOURCE_CONTROLS.items()],
    ]
    gmsh.onelab.set(json.dumps(parameters, ensure_ascii=False))
    update_visibility()


def visibility_signature():
    return (tuple(gmsh.onelab.getString(KIND)), *(tuple(gmsh.onelab.getNumber(name)) for name in
            [CAP_ENABLED, WAVE_ENABLED, FLOOR_ENABLED, SHORT_ENABLED, WIDTH_ENABLED, GAP_ENABLED,
             HOLD_AUTO, TRANSITION_AUTO, CURVATURE_ENABLED, ABS_ENABLED, REL_ENABLED]))


def update_visibility() -> None:
    is_plate = gmsh.onelab.getString(KIND) == ['plate']
    visibility = {CAD_PATH: not is_plate, SHEET_SIGN: not is_plate,
                  **{name: is_plate for name in [LENGTH, WIDTH, *ORIGIN]},
                  TARGET: _flag(CAP_ENABLED), FLOOR: _flag(FLOOR_ENABLED),
                  **{name: _flag(WAVE_ENABLED) for name in [FREQUENCY, WAVE_DIV, EPSILON, MU]},
                  FALLBACK: not _flag(CAP_ENABLED) and not _flag(WAVE_ENABLED),
                  SHORT_DIV: _flag(SHORT_ENABLED), WIDTH_DIV: _flag(WIDTH_ENABLED),
                  GAP_DIV: _flag(GAP_ENABLED), HOLD: not _flag(HOLD_AUTO),
                  TRANSITION: not _flag(TRANSITION_AUTO), GROWTH: _flag(TRANSITION_AUTO)}
    visibility.update({name: _flag(CURVATURE_ENABLED) for name in
                       [ABS_ENABLED, REL_ENABLED, CURV_ITERATIONS, CURV_SAMPLING, CURV_VERIFY]})
    visibility.update({ABS_TOL: _flag(CURVATURE_ENABLED) and _flag(ABS_ENABLED),
                       REL_TOL: _flag(CURVATURE_ENABLED) and _flag(REL_ENABLED)})
    for name, visible in visibility.items():
        # Typed values avoid Gmsh's Windows-path escaping bug in its JSON getter.
        value = _string(name) if name in (CAD_PATH, SHEET_SIGN) else _number(name)
        options = {'kind': 'file'} if name == CAD_PATH else {}
        if name == SHEET_SIGN:
            options['choices'] = list(SHEET_DIRECTIONS)
        elif name in (SHORT_DIV, WIDTH_DIV, GAP_DIV):
            options['min'] = 1
        elif name in (ABS_ENABLED, REL_ENABLED):
            options['choices'] = [0, 1]
        elif name in (CURV_ITERATIONS, CURV_SAMPLING, CURV_VERIFY):
            options.update(min=0 if name == CURV_ITERATIONS else 3,
                           max=10 if name == CURV_ITERATIONS else 100, step=1)
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
        raise ConfigurationError('Geometry: plate 또는 cad가 필요합니다')
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
        curvature = {'max_iterations': _integer(CURV_ITERATIONS), 'sampling_nodes': _integer(CURV_SAMPLING),
                     'verification_nodes': _integer(CURV_VERIFY)}
        if _flag(ABS_ENABLED): curvature['absolute_tolerance'] = _number(ABS_TOL)
        if _flag(REL_ENABLED): curvature['relative_tolerance'] = _number(REL_TOL)
        mesh['curvature'] = curvature
    else:
        mesh.pop('curvature', None)
    resources = {key: (_number(name) if key in ('max_seconds', 'max_memory_mb') else _integer(name))
                 for key, name in RESOURCE_CONTROLS.items()}
    value.update(geometry=geometry, length_unit=_string(INPUT_UNIT), output_unit=_string(OUTPUT_UNIT),
                 mesh=mesh, resources=resources, output_dir=_string(OUTPUT),
                 improvement={'enabled': bool(enabled), 'max_passes': _integer(PASSES)})
    return Configuration.from_dict(value, base_dir)


class Controller:
    def __init__(self, base: Configuration, base_dir: Path):
        self.base, self.base_dir = base, base_dir
        self.scene: Scene | None = None
        self.last_mesh = None
        self.close_requested = False
        install_controls(base)
        self.visible_state = visibility_signature()

    def status(self, message: str, path: str = '') -> None:
        gmsh.onelab.setString(STATUS, [message])
        gmsh.onelab.setString(NAS_PATH, [path])
        gmsh.onelab.setNumber(APPLIED_SIZE, [self.scene.sizing.global_size if self.scene is not None else 0])

    def invalidate_if_changed(self) -> None:
        try:
            state = visibility_signature()
            if state != self.visible_state:
                update_visibility()
                self.visible_state = state
            if self.scene is None:
                return
            self.scene.require_current(read_controls(self.base, self.base_dir))
            if self.last_mesh is not None:
                from .model import assert_current
                try:
                    assert_current(self.last_mesh)
                except MeshBlocked:
                    # Preserve the CAD reference, discard the previous mesh result.
                    self.last_mesh = None
                    self.status('Mesh changed: next action checks the current mesh')
        except Exception as exc:
            self.scene, self.last_mesh = None, None
            self.status(f'Regenerate required: {exc}')

    def _prepare(self, config: Configuration):
        if self.scene is None:
            raise MeshBlocked('현재 생성 결과가 없습니다. 먼저 Generate mesh를 실행하세요')
        self.scene.require_current(config)
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
        if action == 0:
            return
        config = read_controls(self.base, self.base_dir)
        with resource_scope(config.resources):
            self._perform(action, config)

    def _perform(self, action: int, config: Configuration) -> None:
        self.invalidate_if_changed()
        self.status('Working')
        if action in (1, 2):
            self.scene, self.last_mesh = None, None
            gmsh.clear()  # This process owns the complete Gmsh session.
            self.scene = generate(config)
            mesh = self._prepare(config)
            if action == 2:
                self.status('Mesh ready: required checks passed')
                return
        elif action == 3:
            self._prepare(config)
            self.status('Current mesh checked; improvement completed if needed')
            return
        else:
            if self.scene is None:
                raise MeshBlocked('현재 생성 결과가 없습니다. 먼저 Generate mesh를 실행하세요')
            self.scene.require_current(config)
            mesh = snapshot(self.scene.membership)
        result = publish(mesh, config, self.scene)
        self.last_mesh = mesh
        self.status('NAS published', str(result.nas_path))

    def dispatch(self) -> None:
        """Consume once; failed or idle events never repeat publication."""
        try:
            choice = _string(ACTION)
            if choice not in ACTIONS.values():
                raise ConfigurationError('지원하지 않는 Action입니다')
            action = {label: code for code, label in ACTIONS.items()}[choice]
            gmsh.onelab.setString(ACTION, [ACTIONS[0]])
            self.perform(action)
        except Exception as exc:
            gmsh.onelab.setString(ACTION, [ACTIONS[0]])
            self.status(f'Blocked: {exc}')


def launch(config: Configuration, base_dir: Path) -> None:
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('ONELAB/FLTK는 main thread에서 실행해야 합니다')
    if gmsh.isInitialized():
        raise RuntimeError('기존 Gmsh session이 있습니다. 독립 프로세스에서 실행하세요')
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        # Keep all intermediates in memory; do not persist native preferences.
        gmsh.option.setNumber('General.SaveOptions', 0)
        controller = Controller(config, base_dir)
        gmsh.fltk.initialize()
        gmsh.fltk.openTreeItem('ONELAB')
        while gmsh.fltk.isAvailable() and not controller.close_requested:
            gmsh.fltk.wait(.2)
            if not gmsh.fltk.isAvailable():
                break
            controller.invalidate_if_changed()
            controller.dispatch()
            if not controller.close_requested:
                gmsh.fltk.update()
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
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
