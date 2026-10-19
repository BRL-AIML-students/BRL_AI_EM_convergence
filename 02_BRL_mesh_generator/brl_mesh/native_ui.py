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
        _parameter(TARGET, config.target_size, min=0),
        _parameter(SHEET_SIGN, {v: k for k, v in SHEET_DIRECTIONS.items()}[
                       cad.sheet_normal if cad and cad.sheet_normal else (1 if is_plate else 0)],
                   choices=list(SHEET_DIRECTIONS)),
        _parameter(IMPROVE, int(config.improvement.enabled), choices=[0, 1]),
        _parameter(PASSES, config.improvement.max_passes, min=0, max=10, step=1),
        _parameter(OUTPUT, config.output_dir.as_posix()),
    ]
    gmsh.onelab.set(json.dumps(parameters, ensure_ascii=False))
    update_visibility()


def update_visibility() -> None:
    is_plate = gmsh.onelab.getString(KIND) == ['plate']
    for name in [CAD_PATH, SHEET_SIGN, LENGTH, WIDTH, *ORIGIN]:
        visible = not is_plate if name in (CAD_PATH, SHEET_SIGN) else is_plate
        # Gmsh's JSON getter does not escape Windows backslashes reliably.
        # Read values through the typed API and update known metadata directly.
        value = _string(name) if name in (CAD_PATH, SHEET_SIGN) else _number(name)
        options = {'kind': 'file'} if name == CAD_PATH else {}
        if name == SHEET_SIGN:
            options['choices'] = list(SHEET_DIRECTIONS)
        if name in (LENGTH, WIDTH):
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
    value.update(geometry=geometry, length_unit=_string(INPUT_UNIT), output_unit=_string(OUTPUT_UNIT),
                 mesh={'target_size': _number(TARGET)}, output_dir=_string(OUTPUT),
                 improvement={'enabled': bool(enabled), 'max_passes': _integer(PASSES)})
    return Configuration.from_dict(value, base_dir)


class Controller:
    def __init__(self, base: Configuration, base_dir: Path):
        self.base, self.base_dir = base, base_dir
        self.scene: Scene | None = None
        self.last_mesh = None
        self.close_requested = False
        install_controls(base)
        self.visible_kind = gmsh.onelab.getString(KIND)

    def status(self, message: str, path: str = '') -> None:
        gmsh.onelab.setString(STATUS, [message])
        gmsh.onelab.setString(NAS_PATH, [path])

    def invalidate_if_changed(self) -> None:
        kind = gmsh.onelab.getString(KIND)
        if kind != self.visible_kind:
            update_visibility()
            self.visible_kind = kind
        if self.scene is None:
            return
        try:
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
