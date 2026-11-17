"""Headless CAD -> Nastran surface mesh using explicit mesh-only settings.

Use convert_cad_to_nas for one job, convert_many for a stream of jobs, or the
command line for integration with a solver in another language/environment.
Only the worker imports Gmsh. Each CAD owns a fresh subprocess and Gmsh session.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable, Iterator, Mapping

from brl_mesh.mesh_quality_settings import QualitySettings, parse_quality_settings
from brl_mesh.mesh_size_settings import parse_sizing

ROOT = Path(__file__).resolve().parent
CAD_SUFFIXES = frozenset({'.step', '.stp', '.iges', '.igs', '.brep'})
PROTOCOL = 'BRL_CAD_RESULT '
# 변환 시 호출자가 덮어쓸 수 있는 기본 설정입니다.
DEFAULT_OPTIONS = {

    # 단위와 전역 크기
    # CAD 입력 길이 단위
    'length_unit': None,
    # NAS 출력 길이 단위
    'output_unit': 'm',
    # 전역 목표 크기
    'target_size': None,
    # 독립 메쉬 주파수 (Hz)
    'mesh_frequency_hz': None,
    # 파장당 요소 수
    'elements_per_wavelength': 10,
    # 상대 유전율
    'relative_permittivity': 1,
    # 상대 투자율
    'relative_permeability': 1,
    # 최소 크기
    'minimum_size': None,

    # 국소 크기 및 곡률
    # 짧은 경계 크기 제어
    'short_edges': 'auto',
    # 폭 기반 크기 제어
    'widths': 'auto',
    # gap 기반 크기 제어
    'gaps': False,
    # 국소 크기 규칙
    'local': {},
    # 곡률 크기 제어
    'curvature': 'auto',
    # 곡률 절대 허용 편차
    'curvature_absolute_tolerance': None,
    # 곡률 상대 허용 편차
    'curvature_relative_tolerance': None,
    # 자동 곡률 허용 편차 비율
    'curvature_tolerance_ratio': .02,
    # 곡률 보정 최대 반복
    'curvature_max_iterations': 3,
    # 곡률 표본 수
    'curvature_sampling_nodes': 10,
    # 곡률 검증 표본 수
    'curvature_verification_nodes': 19,
    # 곡률 피드백 범위
    'curvature_feedback': 'entity',
    # 개선과 형상 경계
    # 노드 개선 활성화
    'improvement': True,
    # 개선 최대 반복
    'max_passes': 3,
    # 품질 위반 시 재생성 방법
    'quality_retry': 'none',
    # 기본 sheet 법선 방향
    'sheet_normal': None,
    # surface별 sheet 법선 방향
    'sheet_normals': {},
    # 분리 surface 지정
    'separated_surfaces': [],
    # 보호 gap
    'protected_gap': None,

    # 크기 제어 활성화
    # 목표 크기 활성화
    'target_size_enabled': True,
    # 파장 크기 활성화
    'wavelength_sizing_enabled': True,
    # 최소 크기 활성화
    'minimum_size_enabled': True,
    # 국소 크기장 활성화
    'local_size_fields_enabled': True,
    # 곡선 크기장 활성화
    'local_curves_enabled': True,
    # 상자 크기장 활성화
    'local_boxes_enabled': True,

    # 독립 품질 지표별 활성화와 기준
    'quality': {
        # ICN 측정 활성화
        'icn_enabled': True,
        # ICN 하한 (이상)
        'icn_minimum': 0.0,
        # IGE 측정 활성화 (기본 OFF)
        'ige_enabled': False,
        # IGE 하한: 0은 중립 기준이며 측정값의 양수 유효성은 별도 검사
        'ige_minimum': 0.0,
        # 종횡비 측정 활성화
        'aspect_ratio_enabled': True,
        # 종횡비 상한 (이하)
        'aspect_ratio_maximum': 3.0,
        # 최소각 측정 활성화
        'minimum_angle_enabled': True,
        # 최소각 하한 (도, 이상)
        'minimum_angle_degrees': 20.0,
        # Radius ratio (Gmsh 내장 gamma) 측정 활성화
        'radius_ratio_enabled': False,
        # Radius ratio 하한 (이상)
        'radius_ratio_minimum': 0.5,
    },
}


def _merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'JSON 키 중복: {key}')
        result[key] = value
    return result


def _load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=_unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def load_mesh_options(path):
    """Read a strict JSON options object; job/CAD validation happens at conversion."""
    return _options(_load_json(path))


def _options(value):
    if not isinstance(value, Mapping) or set(value) - set(DEFAULT_OPTIONS):
        raise ValueError('options: 지원하지 않는 키 또는 object가 아닌 입력입니다')
    result = _merge(DEFAULT_OPTIONS, value)
    for name in ('target_size_enabled', 'wavelength_sizing_enabled', 'minimum_size_enabled',
                 'local_size_fields_enabled', 'local_curves_enabled', 'local_boxes_enabled'):
        if type(result[name]) is not bool:
            raise ValueError(f'{name}: bool이 필요합니다')
    for name in ('curvature', 'short_edges', 'widths', 'gaps'):
        v = result[name]
        if type(v) is not bool and v != 'auto':
            raise ValueError(f'{name}: True, False 또는 "auto"가 필요합니다')
    for name in ('target_size', 'mesh_frequency_hz', 'elements_per_wavelength',
                 'relative_permittivity', 'relative_permeability', 'minimum_size',
                 'curvature_absolute_tolerance', 'curvature_relative_tolerance',
                 'curvature_tolerance_ratio'):
        v = result[name]
        if v is not None and (type(v) not in (int, float) or not math.isfinite(v) or v <= 0):
            raise ValueError(f'{name}: 양의 유한한 숫자가 필요합니다')
    if not (result['target_size_enabled'] and result['target_size'] is not None) and not (
            result['wavelength_sizing_enabled'] and result['mesh_frequency_hz'] is not None):
        raise ValueError('target_size 또는 활성 mesh_frequency_hz가 필요합니다. MoM 주파수를 읽거나 추측하지 않습니다')
    if result['curvature_tolerance_ratio'] is None:
        raise ValueError('curvature_tolerance_ratio는 양수여야 합니다')
    if result['curvature_relative_tolerance'] is not None and result['curvature_relative_tolerance'] >= 1:
        raise ValueError('curvature_relative_tolerance: 1보다 작아야 합니다')
    if not isinstance(result['local'], dict):
        raise ValueError('local: object가 필요합니다')
    parse_quality_settings(result['quality'])
    # Validate stored controls even when switched off; no Gmsh import is needed.
    from brl_mesh.mesh_generator_configuration import Improvement, Generation, _unit
    Improvement(result['improvement'], result['max_passes'])
    Generation(result['quality_retry'])
    _unit(result['output_unit'], 'output_unit')
    if result['length_unit'] is not None:
        _unit(result['length_unit'], 'length_unit')
    validation = {'local': deepcopy(result['local']),
                  'wave': {'mesh_frequency_hz': result['mesh_frequency_hz'] or 1.0,
                           **{name: result[name] for name in ('elements_per_wavelength',
                              'relative_permittivity', 'relative_permeability')}},
                  'curvature': {name: result['curvature_' + name] for name in
                      ('max_iterations', 'sampling_nodes', 'verification_nodes', 'feedback')}}
    tolerances = {name: result['curvature_' + name] for name in
                  ('absolute_tolerance', 'relative_tolerance') if result['curvature_' + name] is not None}
    validation['curvature'].update(tolerances or {'absolute_tolerance': 1.0})
    parse_sizing(validation)
    return result


@dataclass(frozen=True)
class ConversionJob:
    cad_path: str | Path
    nas_path: str | Path
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ConversionResult:
    status: str
    cad_path: Path
    requested_nas_path: Path
    nas_path: Path | None = None
    node_count: int = 0
    triangle_count: int = 0
    applied_options: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    reason: str | None = None
    quality_report_path: Path | None = None
    quality_summary: dict | None = None

    @property
    def exit_code(self):
        return {'ok': 0, 'error': 1, 'blocked': 2}[self.status]

    def to_dict(self):
        value = asdict(self)
        for key in ('cad_path', 'requested_nas_path', 'nas_path', 'quality_report_path'):
            value[key] = str(value[key]) if value[key] is not None else None
        return value


class ConversionError(RuntimeError):
    def __init__(self, result: ConversionResult):
        self.result = result
        super().__init__(result.reason)


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _copy_final(source, target):
    """Exclusive final-file transfer; readers must wait for a successful result.

    Do all generation/validation in local staging. A failed transfer removes only
    the file opened here, provided its filesystem identity has not changed.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    identity = None
    try:
        with source.open('rb') as inp, target.open('xb') as out:
            stat = os.fstat(out.fileno())
            identity = (stat.st_dev, stat.st_ino)
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        if _digest(source) != _digest(target):
            raise RuntimeError('최종 NAS 전송 SHA-256이 일치하지 않습니다')
    except BaseException:
        if identity is not None:
            try:
                stat = target.stat()
                if (stat.st_dev, stat.st_ino) == identity:
                    target.unlink()
            except FileNotFoundError:
                pass
        raise


def convert_cad_to_nas(cad_path, nas_path, *, options=None, timeout=None,
                       python_executable=None, **overrides) -> ConversionResult:
    """Convert one CAD or raise ConversionError. Lengths use output_unit.

    BREP requires length_unit. Open sheets require sheet_normal/sheet_normals.
    The child interpreter must have this package's pinned dependencies; it can
    differ from the MoM interpreter. Existing output files are never replaced.
    """
    source, target = Path(cad_path).resolve(), Path(nas_path).resolve()
    try:
        if os.name == 'nt' and not str(ROOT).isascii():
            raise ValueError('Windows 배포 설치 경로는 영문/숫자 경로를 사용하세요 '
                             '(예: C:\\BRL_CAD_to_NAS). 현재 Gmsh의 내부 field 파일 저장은 한글 설치 경로를 지원하지 않습니다')
        if options is not None and not isinstance(options, Mapping):
            raise ValueError('options: object가 필요합니다')
        settings = _options(_merge(dict(options or {}), overrides))
        if source.suffix.lower() not in CAD_SUFFIXES or not source.is_file():
            raise ValueError('존재하는 STEP/IGES/BREP CAD 파일이 필요합니다')
        if source.suffix.lower() == '.brep' and settings['length_unit'] is None:
            raise ValueError('BREP에는 length_unit을 명시해야 합니다')
        if target.suffix.lower() != '.nas' or target == source:
            raise ValueError('출력에는 입력과 다른 .nas 파일 경로가 필요합니다')
        report_target = target.with_name(target.stem + '_quality.html')
        for destination in (target, report_target):
            if destination.exists():
                raise FileExistsError(f'기존 출력을 덮어쓰지 않습니다: {destination}')
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError('timeout: 양의 유한한 초 단위 값이 필요합니다')
        cache = ROOT / '.cache' / 'cad-to-nas'
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='job-', dir=cache, ignore_cleanup_errors=True) as temp:
            stage = Path(temp)
            request = stage / 'request.json'
            request.write_text(json.dumps({'cad_path': str(source), 'nas_path': str(target), 'options': settings},
                                          ensure_ascii=True, allow_nan=False), encoding='utf-8')
            child = subprocess.run(
                [str(python_executable or sys.executable), '-B', '-X', 'utf8',
                 str(Path(__file__).resolve()), '--_worker', str(request)],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                errors='replace', timeout=timeout)
            records = [line[len(PROTOCOL):] for line in child.stdout.splitlines() if line.startswith(PROTOCOL)]
            if len(records) != 1 or child.returncode not in (0, 1, 2):
                raise RuntimeError(f'변환 worker가 완료 결과를 반환하지 않았습니다 (exit={child.returncode}): '
                                   + child.stderr[-2000:])
            data = json.loads(records[0])
            status = {0: 'ok', 1: 'error', 2: 'blocked'}[child.returncode]
            if data.get('status') != status:
                raise RuntimeError('변환 worker 상태/종료 코드 불일치')
            if status != 'ok':
                raise ConversionError(ConversionResult(status, source, target, reason=data['reason']))
            generated = Path(data['nas_path']).resolve()
            if not generated.is_relative_to(stage) or not generated.is_file():
                raise RuntimeError('worker의 로컬 NAS 경로가 유효하지 않습니다')
            if _digest(generated) != data['nas_sha256']:
                raise RuntimeError('worker 완료 후 로컬 NAS가 변경됐습니다')
            generated_report = Path(data['quality_report_path']).resolve()
            if not generated_report.is_relative_to(stage) or not generated_report.is_file():
                raise RuntimeError('worker의 로컬 보고서 경로가 유효하지 않습니다')
            if _digest(generated_report) != data['quality_report_sha256']:
                raise RuntimeError('worker 완료 후 보고서가 변경됐습니다')
            _copy_final(generated, target)
            identity = target.stat()
            try:
                _copy_final(generated_report, report_target)
            except BaseException:
                try:
                    current = target.stat()
                    if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) == (identity.st_dev, identity.st_ino, identity.st_size, identity.st_mtime_ns):
                        target.unlink()
                except FileNotFoundError:
                    pass
                raise
            result = ConversionResult('ok', source, target, target, data['node_count'],
                                      data['triangle_count'], data['applied_options'], tuple(data['warnings']),
                                      quality_report_path=report_target, quality_summary=data['quality_summary'])
        if stage.exists():
            result = replace(result, warnings=(*result.warnings, f'로컬 임시 폴더 정리 미완료: {stage}'))
        return result
    except ConversionError:
        raise
    except Exception as exc:
        raise ConversionError(ConversionResult('error', source, target, reason=str(exc))) from exc


def _job(value):
    if isinstance(value, ConversionJob):
        return value
    if not isinstance(value, Mapping) or set(value) - {'cad_path', 'nas_path', 'options'}:
        raise ValueError('job: cad_path, nas_path, options만 지원합니다')
    if not {'cad_path', 'nas_path'} <= set(value):
        raise ValueError('job: cad_path와 nas_path가 필요합니다')
    return ConversionJob(**value)


def convert_many(jobs: Iterable[ConversionJob | Mapping], *, default_options=None,
                 continue_on_error=True, timeout=None, python_executable=None) -> Iterator[ConversionResult]:
    """Sequential result stream. Check every output collision before the first job."""
    if type(continue_on_error) is not bool:
        raise ValueError('continue_on_error: bool이 필요합니다')
    prepared = [_job(job) for job in jobs]
    paths = [Path(job.nas_path).resolve() for job in prepared]
    targets = [os.path.normcase(str(p)) for path in paths for p in (path, path.with_name(path.stem + '_quality.html'))]
    if len(set(targets)) != len(targets):
        raise ValueError('여러 CAD의 NAS 출력 경로가 중복됩니다')
    for job in prepared:
        try:
            if not isinstance(job.options, Mapping) or (default_options is not None and not isinstance(default_options, Mapping)):
                raise ValueError('공통/개별 options에는 object가 필요합니다')
            result = convert_cad_to_nas(job.cad_path, job.nas_path,
                                       options=_merge(dict(default_options or {}), job.options),
                                       timeout=timeout, python_executable=python_executable)
        except ConversionError as exc:
            if not continue_on_error:
                raise
            result = exc.result
        except ValueError as exc:
            result = ConversionResult('error', Path(job.cad_path).resolve(),
                                      Path(job.nas_path).resolve(), reason=str(exc))
            if not continue_on_error:
                raise ConversionError(result) from exc
        yield result


def jobs_from_directory(input_dir, output_dir, *, recursive=False) -> list[ConversionJob]:
    """Preserve relative directories and original extension (a.step.nas/a.igs.nas)."""
    source, target = Path(input_dir).resolve(), Path(output_dir).resolve()
    if not source.is_dir():
        raise ValueError(f'CAD 입력 폴더가 없습니다: {source}')
    paths = source.rglob('*') if recursive else source.iterdir()
    return [ConversionJob(path, target / path.relative_to(source).with_name(path.name + '.nas'))
            for path in sorted(paths) if path.is_file() and path.suffix.lower() in CAD_SUFFIXES]


def _resolve_configuration(source, settings, output_dir):
    """Inspect one owned CAD session, then freeze explicit engine configuration."""
    import gmsh
    from brl_mesh.cad_geometry_import import build_geometry
    from brl_mesh.mesh_generator_configuration import Configuration
    from brl_mesh.mesh_generator_errors import MeshBlocked
    from brl_mesh.cad_feature_size_rules import polygon_width, surface_curves
    from brl_mesh.mesh_size_fields import resolve_global
    from brl_mesh.mesh_size_settings import parse_sizing

    geometry = {'kind': 'cad', 'path': str(source)}
    for name in ('sheet_normal', 'sheet_normals', 'separated_surfaces', 'protected_gap'):
        if settings[name] is not None:
            geometry[name] = settings[name]
    mesh = {'local': deepcopy(settings['local'])}
    if settings['target_size_enabled'] and settings['target_size'] is not None:
        mesh['target_size'] = settings['target_size']
    if settings['minimum_size_enabled'] and settings['minimum_size'] is not None:
        mesh['minimum_size'] = settings['minimum_size']
    if settings['wavelength_sizing_enabled'] and settings['mesh_frequency_hz'] is not None:
        mesh['wave'] = {name: settings[name] for name in
                        ('elements_per_wavelength', 'relative_permittivity', 'relative_permeability')}
        mesh['wave']['mesh_frequency_hz'] = settings['mesh_frequency_hz']
    data = {'schema_version': 1, 'geometry': geometry, 'length_unit': settings['length_unit'] or 'mm',
            'output_unit': settings['output_unit'], 'mesh': mesh, 'output_dir': str(output_dir),
            'improvement': {'enabled': settings['improvement'], 'max_passes': settings['max_passes']},
            'generation': {'quality_retry': settings['quality_retry']}, 'quality': deepcopy(settings['quality'])}
    # Validate even inactive curvature settings instead of silently discarding typos.
    curvature = {name: settings['curvature_' + name] for name in
                 ('max_iterations', 'sampling_nodes', 'verification_nodes', 'feedback')}
    for name in ('absolute_tolerance', 'relative_tolerance'):
        if settings['curvature_' + name] is not None:
            curvature[name] = settings['curvature_' + name]
    parse_sizing({'curvature': curvature if any(k.endswith('tolerance') for k in curvature)
                  else {**curvature, 'absolute_tolerance': 1}})
    validation_mesh = {'local': deepcopy(settings['local'])}
    if settings['minimum_size'] is not None:
        validation_mesh['minimum_size'] = settings['minimum_size']
    parse_sizing(validation_mesh)
    if not settings['local_curves_enabled']:
        mesh['local']['curves'] = []
    if not settings['local_boxes_enabled']:
        mesh['local']['boxes'] = []
    if not settings['local_size_fields_enabled']:
        mesh['local'] = {}
    preliminary = Configuration.from_dict(data)
    warnings = []
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        build_geometry(preliminary)
        h, _ = resolve_global(preliminary)
        curved = any(gmsh.model.getType(2, tag) != 'Plane' for _, tag in gmsh.model.getEntities(2))
        curved = curved or any(gmsh.model.getType(1, tag) != 'Line'
                               and gmsh.model.occ.getMass(1, tag) > 0
                               for _, tag in gmsh.model.getEntities(1))
        if settings['curvature'] is True or (settings['curvature'] == 'auto' and curved):
            if not any(k.endswith('tolerance') for k in curvature):
                curvature['absolute_tolerance'] = h * settings['curvature_tolerance_ratio']
            mesh['curvature'] = curvature
        local = mesh['local']
        for name in ('short_edges', 'widths', 'gaps'):
            rule = local.setdefault(name, {})
            if not isinstance(rule, dict):
                raise ValueError(f'local.{name}: object가 필요합니다')
            auto = 'enabled' not in rule and settings[name] == 'auto'
            enabled = rule.get('enabled', settings[name] is True or auto)
            if not settings['local_size_fields_enabled']:
                rule['enabled'] = False
                continue
            if name == 'short_edges' and auto and 'entities' not in rule:
                # Match the existing curvature engine's OCC pole classification.
                # Keep real tiny edges as requests (and their precision failures).
                mapping, seams = surface_curves()
                magnitude = max(abs(v) for _, face in gmsh.model.getEntities(2)
                                for v in gmsh.model.getBoundingBox(2, face))
                precision = 128 * sys.float_info.epsilon * max(magnitude, h)
                chosen, poles = [], []
                for tag in sorted({edge for edges in mapping.values() for edge in edges} - seams):
                    length = gmsh.model.occ.getMass(1, tag)
                    if length == 0 or (0 < length <= precision and gmsh.model.getType(1, tag) == 'Unknown'
                                       and not gmsh.model.getBoundary([(1, tag)], oriented=False)):
                        poles.append(tag)
                    else:
                        chosen.append(tag)
                rule['entities'] = chosen
                enabled = bool(chosen)
                if poles:
                    warnings.append(f'short_edges auto: OCC 퇴화 pole 제외 {poles}')
            if name == 'widths' and auto and 'entities' not in rule:
                chosen, skipped = [], []
                for _, tag in gmsh.model.getEntities(2):
                    try:
                        polygon_width(tag)
                        chosen.append(tag)
                    except MeshBlocked as exc:
                        if not str(exc).startswith('width_unsupported:'):
                            raise
                        skipped.append(tag)
                rule['entities'] = chosen
                enabled = bool(chosen)
                if skipped:
                    warnings.append(f'widths auto: 지원하지 않는 surface 제외 {skipped}')
            rule['enabled'] = enabled
        return Configuration.from_dict(data), warnings
    finally:
        gmsh.finalize()


def _worker(request_path):
    try:
        from brl_mesh.surface_mesh_generation import run
        from brl_mesh.mesh_generator_errors import MeshBlocked
        request = _load_json(request_path)
        source = Path(request['cad_path'])
        settings = _options(request['options'])
        before = _digest(source)
        config, warnings = _resolve_configuration(source, settings, Path(request_path).parent / 'generated')
        if _digest(source) != before:
            raise MeshBlocked('CAD가 자동 옵션 분석 중 변경됐습니다')
        result = run(config, report_nas_name=request['nas_path'])
        if _digest(source) != before:
            raise MeshBlocked('CAD가 변환 중 변경됐습니다')
        applied = config.to_dict()
        applied.pop('output_dir')
        payload = {'status': 'ok', 'nas_path': str(result.nas_path),
                   'nas_sha256': _digest(result.nas_path), 'node_count': result.node_count,
                   'triangle_count': result.triangle_count, 'applied_options': applied,
                   'warnings': [*warnings, *result.warnings],
                   'quality_report_path': str(result.quality_report_path),
                   'quality_report_sha256': _digest(result.quality_report_path),
                   'quality_summary': result.quality_summary}
        code = 0
    except Exception as exc:
        # Missing runtime dependencies also get a structured error.
        code = 2 if any(cls.__name__ == 'MeshBlocked' for cls in type(exc).__mro__) else 1
        payload = {'status': 'blocked' if code == 2 else 'error',
                   'reason': '; '.join([str(exc), *getattr(exc, '__notes__', ())])}
    print(PROTOCOL + json.dumps(payload, ensure_ascii=True, allow_nan=False))
    return code


def _switch(value):
    return {'on': True, 'off': False, 'auto': 'auto'}[value]


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = _ArgumentParser(description='CAD -> 검증된 NAS (단일/순차 일괄 변환)')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--cad', type=Path)
    group.add_argument('--input-dir', type=Path)
    group.add_argument('--jobs', type=Path, help='default_options/jobs JSON; 경로는 JSON 폴더 기준')
    parser.add_argument('--nas', type=Path)
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--recursive', action='store_true')
    parser.add_argument('--options', type=Path, help='공통 options JSON')
    parser.add_argument('--stop-on-error', action='store_true')
    parser.add_argument('--timeout', type=float)
    for name in ('curvature', 'short-edges', 'widths', 'gaps'):
        parser.add_argument('--' + name, choices=('on', 'off', 'auto'))
    for name in ('target-size', 'mesh-frequency-hz', 'curvature-absolute-tolerance', 'curvature-tolerance-ratio'):
        parser.add_argument('--' + name, type=float)
    for name in ('target-size-enabled', 'wavelength-sizing-enabled', 'minimum-size-enabled',
                 'local-size-fields-enabled', 'local-curves-enabled', 'local-boxes-enabled', 'improvement'):
        parser.add_argument('--' + name, choices=('on', 'off'))
    parser.add_argument('--quality', dest='quality_file', type=Path,
                        help='quality object JSON; --options.quality보다 우선')
    parser.add_argument('--length-unit' , choices=('m', 'cm', 'mm', 'um'))
    parser.add_argument('--output-unit', choices=('m', 'cm', 'mm', 'um'))
    parser.add_argument('--sheet-normal', type=int, choices=(-1, 1))
    try:
        args = parser.parse_args(argv)
        options = _load_json(args.options) if args.options else {}
        if not isinstance(options, dict):
            raise ValueError('--options에는 options object가 필요합니다')
        for name in DEFAULT_OPTIONS:
            value = getattr(args, name, None)
            if value is not None:
                options[name] = _switch(value) if name in ('curvature', 'short_edges', 'widths', 'gaps', 'improvement') or name.endswith('_enabled') else value
        if args.quality_file:
            quality = _load_json(args.quality_file)
            parse_quality_settings(quality)
            options['quality'] = _merge(options.get('quality', {}), quality)
        if args.jobs:
            if args.nas or args.output_dir or args.recursive:
                raise ValueError('--jobs와 --nas/--output-dir/--recursive는 함께 사용할 수 없습니다')
            data = _load_json(args.jobs)
            if not isinstance(data, dict) or set(data) - {'default_options', 'jobs'} or not isinstance(data.get('jobs'), list):
                raise ValueError('--jobs: default_options와 jobs 배열을 사용하세요')
            base = args.jobs.resolve().parent
            jobs = []
            for row in data['jobs']:
                job = _job(row)
                jobs.append(replace(job, cad_path=base / job.cad_path, nas_path=base / job.nas_path))
            options = _merge(data.get('default_options', {}), options)
        elif args.cad:
            if not args.nas or args.output_dir or args.recursive:
                raise ValueError('--cad에는 --nas가 필요하며 --output-dir/--recursive는 사용할 수 없습니다')
            jobs = [ConversionJob(args.cad, args.nas)]
        else:
            if not args.output_dir or args.nas:
                raise ValueError('--input-dir에는 --output-dir가 필요하며 --nas는 사용할 수 없습니다')
            jobs = jobs_from_directory(args.input_dir, args.output_dir, recursive=args.recursive)
        if not jobs:
            raise ValueError('처리할 CAD가 없습니다')
        code = 0
        for result in convert_many(jobs, default_options=options, continue_on_error=not args.stop_on_error,
                                   timeout=args.timeout):
            print(json.dumps(result.to_dict(), ensure_ascii=True, allow_nan=False), flush=True)
            if result.exit_code:
                code = 1 if result.exit_code == 1 or code == 1 else 2
        return code
    except ConversionError as exc:
        print(json.dumps(exc.result.to_dict(), ensure_ascii=True), flush=True)
        return exc.result.exit_code
    except Exception as exc:
        print(json.dumps({'status': 'error', 'nas_path': None, 'reason': str(exc)}, ensure_ascii=True))
        return 1


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    if len(sys.argv) == 3 and sys.argv[1] == '--_worker':
        raise SystemExit(_worker(Path(sys.argv[2])))
    raise SystemExit(main())
