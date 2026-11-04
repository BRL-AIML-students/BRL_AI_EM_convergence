"""Deterministic generation provenance for a self-contained NAS."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
import subprocess

import gmsh

from . import __version__
from .errors import MeshBlocked

_ROOT = Path(__file__).resolve().parent.parent
_OPTIONS = ('Mesh.Algorithm', 'Mesh.RandomSeed', 'Mesh.ElementOrder', 'Mesh.RecombineAll',
            'Mesh.MeshSizeFromPoints', 'Mesh.MeshSizeFromCurvature', 'Mesh.MeshSizeExtendFromBoundary',
            'General.NumThreads', 'Mesh.MaxNumThreads2D')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def _normalize_config(data):
    # Reuse the strict parser without opening the source CAD file.
    from .config import Configuration
    candidate = json.loads(canonical(data))
    original_path = None
    if candidate['geometry'].get('kind') == 'cad':
        original_path = candidate['geometry'].get('path')
        if not isinstance(original_path, str) or not original_path.strip():
            raise ValueError('CAD path')
        suffix = Path(original_path).suffix.lower()
        if suffix not in {'.step', '.stp', '.iges', '.igs', '.brep'}:
            raise ValueError('CAD path suffix')
        candidate['geometry']['path'] = str(_ROOT / ('_provenance_cad' + suffix))
    parsed = Configuration._from_dict({**candidate, 'output_dir': str(_ROOT)}, check_cad_file=False)
    normalized = parsed.to_dict()
    normalized.pop('output_dir')
    if original_path is not None:
        normalized['geometry']['path'] = original_path
    return normalized


def effective_config(config):
    data = config.to_dict()
    data.pop('output_dir')
    return _normalize_config(data)


def source_hash():
    """Hash relative names and bytes of all direct brl_mesh/*.py source files."""
    digest = hashlib.sha256()
    for path in sorted((_ROOT / 'brl_mesh').glob('*.py')):
        name = path.relative_to(_ROOT).as_posix().encode('utf-8')
        content = path.read_bytes()
        for value in (name, content):
            digest.update(len(value).to_bytes(8, 'big'))
            digest.update(value)
    return digest.hexdigest()


def git_state():
    try:
        def git(*args):
            return subprocess.run(['git', '-C', str(_ROOT), *args], check=True, capture_output=True,
                                  text=True, encoding='utf-8', timeout=5).stdout.strip()
        return {'base_commit': git('rev-parse', 'HEAD'),
                'git_status_scope': 'brl_mesh tracked and unignored untracked files',
                'brl_mesh_dirty': bool(git('status', '--porcelain', '--untracked-files=all', '--', 'brl_mesh'))}
    except (OSError, subprocess.SubprocessError):
        return {'base_commit': None, 'git_status_scope': 'unavailable', 'brl_mesh_dirty': None}


def validate_schema(data):
    def valid_hash(value, lengths=(64,)):
        return isinstance(value, str) and len(value) in lengths and re.fullmatch('[0-9a-f]+', value) is not None
    try:
        if type(data) is not dict or set(data) != {'schema', 'effective_config', 'cad_source_sha256',
                'source', 'generator_version', 'gmsh_version', 'configured_options',
                'actual_algorithm', 'actual_threads', 'improvement_history'}:
            raise ValueError('provenance keys')
        if type(data['schema']) is not int or data['schema'] != 3:
            raise ValueError('provenance schema')
        config = data['effective_config']
        if (type(config) is not dict or set(config) != {'schema_version', 'geometry', 'length_unit',
                'output_unit', 'mesh', 'improvement', 'generation'} or type(config['schema_version']) is not int
                or config['schema_version'] != 1 or any(type(config[key]) is not dict
                for key in ('geometry', 'mesh', 'improvement', 'generation'))
                or any(type(config[key]) is not str for key in ('length_unit', 'output_unit'))):
            raise ValueError('effective config')
        if canonical(_normalize_config(config)) != canonical(config):
            raise ValueError('noncanonical effective config')
        if data['cad_source_sha256'] is not None and not valid_hash(data['cad_source_sha256']):
            raise ValueError('CAD digest')
        source = data['source']
        if (type(source) is not dict or set(source) != {'scope', 'sha256', 'base_commit',
                'git_status_scope', 'brl_mesh_dirty'} or source['scope'] !=
                'direct brl_mesh/*.py; length-prefixed relative paths and bytes'
                or not valid_hash(source['sha256'])
                or (source['base_commit'] is not None and not valid_hash(source['base_commit'], (40, 64)))
                or source['git_status_scope'] not in ('unavailable', 'brl_mesh tracked and unignored untracked files')
                or (source['brl_mesh_dirty'] is not None and type(source['brl_mesh_dirty']) is not bool)):
            raise ValueError('source identity')
        if any(type(data[key]) is not str or not data[key] for key in ('generator_version', 'gmsh_version')):
            raise ValueError('version')
        options = data['configured_options']
        if type(options) is not dict or set(options) != set(_OPTIONS) or any(
                type(value) not in (int, float) or not math.isfinite(value) for value in options.values()):
            raise ValueError('configured options')
        algorithm = options['Mesh.Algorithm']
        if algorithm not in (6, 5) or (algorithm == 5 and config['generation']['quality_retry'] != 'delaunay'):
            raise ValueError('configured algorithm requires explicit quality retry')
        if any(data[key] is not None for key in ('actual_algorithm', 'actual_threads', 'improvement_history')):
            raise ValueError('unknown actual values')
        canonical(data)
    except (TypeError, KeyError, ValueError) as exc:
        raise MeshBlocked(f'지원하지 않거나 손상된 provenance schema: {exc}') from exc
    return data


def capture(config, cad_digest):
    data = {'schema': 3, 'effective_config': effective_config(config), 'cad_source_sha256': cad_digest,
            'source': {'scope': 'direct brl_mesh/*.py; length-prefixed relative paths and bytes',
                       'sha256': source_hash(), **git_state()},
            'generator_version': __version__, 'gmsh_version': gmsh.__version__,
            'configured_options': {name: gmsh.option.getNumber(name) for name in _OPTIONS},
            'actual_algorithm': None, 'actual_threads': None, 'improvement_history': None}
    validate_schema(data)
    return canonical(data)


def require_current(data, config, cad_digest):
    if not isinstance(data, str):
        raise MeshBlocked('생성 시점 provenance가 없습니다. 다시 생성하세요')
    try:
        original = data
        data = validate_schema(json.loads(data))
        if canonical(data) != original:
            raise ValueError('noncanonical generation reference')
    except Exception as exc:
        raise MeshBlocked(f'생성 provenance가 유효하지 않습니다: {exc}') from exc
    try:
        if (set(data['configured_options']) != set(_OPTIONS)
                or data['effective_config'] != effective_config(config) or data['cad_source_sha256'] != cad_digest
                or data['source']['sha256'] != source_hash() or data['generator_version'] != __version__
                or data['gmsh_version'] != gmsh.__version__
                or any(gmsh.option.getNumber(name) != value for name, value in data['configured_options'].items())):
            raise MeshBlocked('생성 provenance의 설정·CAD·코드 또는 실행 옵션이 변경됐습니다. 다시 생성하세요')
        canonical(data)
        return data
    except MeshBlocked:
        raise
    except Exception as exc:
        raise MeshBlocked(f'생성 provenance를 검증하지 못했습니다: {exc}') from exc


def restore_generation_algorithm(data, config, cad_digest):
    """Restore only the requested algorithm across owned worker mesh transfer.

    All remaining reference/config/source/options must still match. Failed
    validation restores the previous algorithm and never adopts the mesh.
    """
    old = gmsh.option.getNumber('Mesh.Algorithm')
    try:
        parsed = validate_schema(json.loads(data))
        if canonical(parsed) != data:
            raise ValueError('noncanonical generation reference')
        gmsh.option.setNumber('Mesh.Algorithm', parsed['configured_options']['Mesh.Algorithm'])
        return require_current(data, config, cad_digest)
    except Exception as exc:
        gmsh.option.setNumber('Mesh.Algorithm', old)
        if isinstance(exc, MeshBlocked):
            raise
        raise MeshBlocked(f'생성 알고리즘 참조를 복원하지 못했습니다: {exc}') from exc
