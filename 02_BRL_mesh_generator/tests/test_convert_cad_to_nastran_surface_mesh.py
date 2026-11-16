"""Real CAD/engine integration plus batch and publication failure contracts."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

import convert_cad_to_nastran_surface_mesh as adapter


def write_cases(directory):
    import gmsh
    directory = Path(directory)
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        for kind in ('plate', 'disk', 'sphere', 'box', 'mixed', 'gaps'):
            gmsh.model.add(kind)
            if kind == 'plate':
                gmsh.model.occ.addRectangle(0, 0, 0, 10, 6)
            elif kind == 'disk':
                gmsh.model.occ.addDisk(0, 0, 0, 5, 5)
            elif kind == 'sphere':
                gmsh.model.occ.addSphere(0, 0, 0, 5)
            elif kind == 'box':
                gmsh.model.occ.addBox(0, 0, 0, 10, 10, 10)
            elif kind == 'mixed':
                gmsh.model.occ.addRectangle(0, 0, 0, 10, 6)
                gmsh.model.occ.addDisk(30, 0, 0, 5, 5)
            else:
                gmsh.model.occ.addRectangle(0, 0, 0, 10, 6)
                gmsh.model.occ.addRectangle(0, 0, 2, 10, 6)
            gmsh.model.occ.synchronize()
            gmsh.write(str(directory / (kind + '.brep')))
            if kind == 'plate':
                gmsh.write(str(directory / 'plate.step'))
                gmsh.write(str(directory / 'plate.iges'))
            gmsh.model.remove()
    finally:
        gmsh.finalize()


@pytest.fixture(scope='module')
def cads(tmp_path_factory):
    path = tmp_path_factory.mktemp('cad-adapter')
    subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c',
                    'from tests.test_convert_cad_to_nastran_surface_mesh import write_cases; import sys; write_cases(sys.argv[1])',
                    str(path)], cwd=adapter.ROOT, check=True, capture_output=True, timeout=30)
    return path


@pytest.fixture
def settings():
    return {'length_unit': 'mm', 'output_unit': 'mm', 'target_size': 2,
            'sheet_normal': 1}


def convert(cads, tmp_path, settings, kind='plate', **overrides):
    return adapter.convert_cad_to_nas(cads / (kind + '.brep'), tmp_path / (kind + '.nas'),
                                     options=settings, **overrides)


def cards(path):
    return [line for line in path.read_text(encoding='ascii').splitlines() if not line.startswith('$')]


@pytest.mark.parametrize('kind,curvature,widths', [
    ('plate', False, True), ('disk', True, False), ('sphere', True, False), ('box', False, True),
])
def test_auto_detects_curved_boundary_and_surface(cads, tmp_path, settings, kind, curvature, widths):
    result = convert(cads, tmp_path, settings, kind)
    mesh = result.applied_options['mesh']
    assert result.status == 'ok' and result.nas_path.is_file()
    assert result.node_count > 0 and result.triangle_count > 0
    assert ('curvature' in mesh) is curvature
    assert mesh.get('local', {}).get('widths', {}).get('enabled', False) is widths
    if curvature:
        assert mesh['curvature']['absolute_tolerance'] == pytest.approx(.04)
    assert list(tmp_path.iterdir()) == [result.nas_path]


def test_auto_widths_in_mixed_cad_and_explicit_overrides(cads, tmp_path, settings):
    result = convert(cads, tmp_path, settings, 'mixed', curvature=False)
    mesh = result.applied_options['mesh']
    assert mesh['local']['widths']['entities'] == [1]
    assert 'curvature' not in mesh
    assert result.warnings


def test_absolute_relative_tolerances_and_local_controls_pass_through(cads, tmp_path, settings):
    result = convert(cads, tmp_path, settings, 'disk', curvature=True,
                     curvature_absolute_tolerance=.1, curvature_relative_tolerance=.02,
                     curvature_feedback='local',
                     local={'short_edges': {'enabled': False, 'divisions': 5},
                            'growth_rate': .2, 'boxes': [{'bounds': [-1, -1, -1, 1, 1, 1], 'size': 1}]})
    mesh = result.applied_options['mesh']
    assert mesh['curvature']['absolute_tolerance'] == .1
    assert mesh['curvature']['relative_tolerance'] == .02
    assert mesh['curvature']['feedback'] == 'local'
    assert not mesh['local']['short_edges']['enabled']
    assert mesh['local']['short_edges']['divisions'] == 5
    assert mesh['local']['growth_rate'] == .2


def test_wave_size_units_and_nas_match_direct_engine(cads, tmp_path, settings):
    from brl_mesh.mesh_generator_configuration import Configuration
    from brl_mesh.surface_mesh_generation import run
    result = adapter.convert_cad_to_nas(cads / 'box.brep', tmp_path / 'box.nas',
        options=settings, output_unit='m', target_size=None, mesh_frequency_hz=29979245800,
        elements_per_wavelength=5)
    applied = result.applied_options
    assert applied['output_unit'] == 'm'
    assert 'target_size' not in applied['mesh']
    direct = run(Configuration.from_dict({**applied, 'output_dir': str(tmp_path / 'direct')}))
    assert cards(result.nas_path) == cards(direct.nas_path)
    from pyNastran.bdf.bdf import BDF
    reader = BDF(debug=False)
    reader.read_bdf(str(result.nas_path), xref=False, punch=True)
    assert max(node.xyz[0] for node in reader.nodes.values()) == pytest.approx(.01)


@pytest.mark.parametrize('extension', ['step', 'iges'])
def test_embedded_units_do_not_require_length_unit(cads, tmp_path, extension):
    result = adapter.convert_cad_to_nas(cads / ('plate.' + extension), tmp_path / 'plate.nas',
                                       target_size=.002, sheet_normal=1)
    assert result.nas_path.is_file()


def test_gaps_enabled_without_merging_components(cads, tmp_path, settings):
    result = convert(cads, tmp_path, settings, 'gaps', gaps=True,
                     separated_surfaces=[[1, 2]], protected_gap=1.5)
    assert result.applied_options['geometry']['protected_gap'] == 1.5
    assert result.applied_options['mesh']['local']['gaps']['enabled']


@pytest.mark.parametrize('overrides,match', [
    ({'target_size': None}, 'target_size'),
    ({'target_size': True}, 'target_size'),
    ({'curvature': 'yes'}, 'curvature'),
    ({'unknown': True}, 'options'),
    ({'length_unit': None}, 'BREP'),
    ({'sheet_normal': None}, '기준 방향'),
    ({'curvature_absolute_tolerance': -1}, 'curvature_absolute_tolerance'),
    ({'curvature_max_iterations': True}, 'max_iterations'),
    ({'widths': True, 'local': {'widths': {'entities': [99]}}}, 'widths'),
])
def test_invalid_inputs_never_publish(cads, tmp_path, settings, overrides, match):
    with pytest.raises(adapter.ConversionError, match=match):
        convert(cads, tmp_path, settings, **overrides)
    assert not list(tmp_path.iterdir())


def test_explicit_width_on_unsupported_shape_fails(cads, tmp_path, settings):
    with pytest.raises(adapter.ConversionError, match='width_unsupported') as error:
        convert(cads, tmp_path, settings, 'disk', widths=True)
    assert error.value.result.status == 'blocked'
    assert not list(tmp_path.iterdir())


def test_existing_output_is_preserved(cads, tmp_path, settings):
    output = tmp_path / 'plate.nas'
    output.write_text('previous', encoding='ascii')
    with pytest.raises(adapter.ConversionError, match='덮어쓰지'):
        convert(cads, tmp_path, settings)
    assert output.read_text() == 'previous'


def test_timeout_and_worker_crash_leave_no_output(cads, tmp_path, settings, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], .01)
    monkeypatch.setattr(adapter.subprocess, 'run', timeout)
    with pytest.raises(adapter.ConversionError):
        convert(cads, tmp_path, settings)
    monkeypatch.setattr(adapter.subprocess, 'run', lambda *a, **k:
                        subprocess.CompletedProcess(a[0], 9, stdout='', stderr='worker crash'))
    with pytest.raises(adapter.ConversionError, match='worker crash'):
        convert(cads, tmp_path, settings)
    assert not list(tmp_path.iterdir())


def test_transfer_failure_removes_only_current_output(tmp_path, monkeypatch):
    source, target = tmp_path / 'source.nas', tmp_path / 'target.nas'
    source.write_text('verified NAS')
    previous = tmp_path / 'previous.nas'
    previous.write_text('previous')
    def fail(inp, out):
        out.write(b'partial')
        raise OSError('transfer interrupted')
    monkeypatch.setattr(adapter.shutil, 'copyfileobj', fail)
    with pytest.raises(OSError, match='interrupted'):
        adapter._copy_final(source, target)
    assert not target.exists() and previous.read_text() == 'previous'


def test_batch_failure_isolation_and_options_override(cads, tmp_path, settings):
    jobs = [adapter.ConversionJob(cads / 'missing.step', tmp_path / 'missing.nas'),
            adapter.ConversionJob(cads / 'plate.brep', tmp_path / 'plate.nas', {'target_size': 1})]
    results = list(adapter.convert_many(jobs, default_options=settings))
    assert [r.status for r in results] == ['error', 'ok']
    assert results[0].nas_path is None
    assert results[1].applied_options['mesh']['target_size'] == 1
    assert settings['target_size'] == 2
    assert len(list(tmp_path.iterdir())) == 1


def test_batch_recovers_after_native_mesh_block_then_runs_multiple_successes(cads, tmp_path, settings):
    before = {p: adapter._digest(p) for p in cads.iterdir()}
    jobs = [adapter.ConversionJob(cads / 'disk.brep', tmp_path / 'blocked.nas', {'widths': True}),
            adapter.ConversionJob(cads / 'sphere.brep', tmp_path / 'sphere.nas'),
            adapter.ConversionJob(cads / 'plate.brep', tmp_path / 'plate.nas', {'curvature': False})]
    results = list(adapter.convert_many(jobs, default_options=settings))
    assert [r.status for r in results] == ['blocked', 'ok', 'ok']
    assert {p.name for p in tmp_path.iterdir()} == {'sphere.nas', 'plate.nas'}
    assert all(adapter._digest(path) == value for path, value in before.items())


def test_curvature_minimum_size_conflict_is_not_silently_relaxed(cads, tmp_path, settings):
    with pytest.raises(adapter.ConversionError, match='curvature_') as error:
        convert(cads, tmp_path, settings, 'disk', curvature_absolute_tolerance=.00001, minimum_size=2)
    assert error.value.result.status == 'blocked' and not list(tmp_path.iterdir())


def test_batch_stop_and_duplicate_output_preflight(cads, tmp_path, settings, monkeypatch):
    jobs = [adapter.ConversionJob(cads / 'missing.step', tmp_path / 'same.nas'),
            adapter.ConversionJob(cads / 'plate.brep', tmp_path / 'other.nas')]
    with pytest.raises(adapter.ConversionError):
        list(adapter.convert_many(jobs, default_options=settings, continue_on_error=False))
    called = []
    monkeypatch.setattr(adapter, 'convert_cad_to_nas', lambda *a, **k: called.append(True))
    with pytest.raises(ValueError, match='중복'):
        list(adapter.convert_many([jobs[0], replace(jobs[1], nas_path=jobs[0].nas_path)]))
    assert not called and not list(tmp_path.iterdir())


def test_directory_mapping_preserves_extension_and_relative_path(tmp_path):
    source = tmp_path / 'source'
    (source / 'sub').mkdir(parents=True)
    for name in ('a.step', 'a.igs', 'ignore.txt', 'sub/b.BREP'):
        (source / name).write_text('input')
    jobs = adapter.jobs_from_directory(source, tmp_path / 'out', recursive=True)
    assert {Path(j.nas_path).relative_to(tmp_path / 'out').as_posix() for j in jobs} == {
        'a.step.nas', 'a.igs.nas', 'sub/b.BREP.nas'}


def test_cli_json_lines_paths_options_and_exit_codes(cads, tmp_path, settings):
    options = tmp_path / 'options.json'
    options.write_text(json.dumps(settings))
    jobs = tmp_path / 'jobs.json'
    jobs.write_text(json.dumps({'default_options': {}, 'jobs': [
        {'cad_path': str(cads / 'missing.step'), 'nas_path': 'missing.nas'},
        {'cad_path': str(cads / 'plate.brep'), 'nas_path': '한글 폴더/plate.nas'},
    ]}), encoding='utf-8')
    child = subprocess.run([sys.executable, '-B', str(adapter.ROOT / 'convert_cad_to_nastran_surface_mesh.py'),
                            '--jobs', str(jobs), '--options', str(options)],
                           cwd=tmp_path, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert child.returncode == 1, child.stderr
    results = [json.loads(line) for line in child.stdout.splitlines()]
    assert [r['status'] for r in results] == ['error', 'ok']
    assert Path(results[1]['nas_path']) == tmp_path / '한글 폴더' / 'plate.nas'
    assert not child.stderr


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / 'options.json'
    path.write_text('{"gaps":false,"gaps":true}')
    with pytest.raises(ValueError, match='중복'):
        adapter._load_json(path)


@pytest.mark.parametrize('argv', [[], ['--unknown'], ['--cad', 'a.step', '--curvature', 'yes']])
def test_cli_argument_errors_are_json_errors_not_mesh_blocks(argv, capsys):
    assert adapter.main(argv) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'error' and result['nas_path'] is None


def test_actual_timeout_can_be_followed_by_another_job(cads, tmp_path, settings):
    with pytest.raises(adapter.ConversionError):
        adapter.convert_cad_to_nas(cads / 'plate.brep', tmp_path / 'timeout.nas',
                                   options=settings, timeout=.05)
    result = convert(cads, tmp_path, settings)
    assert result.status == 'ok' and not (tmp_path / 'timeout.nas').exists()


def test_worker_does_not_mutate_or_finalize_callers_gmsh(cads, tmp_path, settings):
    import gmsh
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.model.add('MoM-owned-model')
        gmsh.model.occ.addPoint(1, 2, 3)
        gmsh.model.occ.synchronize()
        before = gmsh.model.getEntities()
        convert(cads, tmp_path, settings)
        assert gmsh.isInitialized() and gmsh.model.getCurrent() == 'MoM-owned-model'
        assert gmsh.model.getEntities() == before
    finally:
        gmsh.finalize()


def test_launcher_preserves_callers_relative_paths(cads, tmp_path):
    child = subprocess.run(['cmd', '/d', '/c', str(adapter.ROOT / 'run_cad_to_nastran_surface_mesh.bat'),
                            '--cad', 'plate.step', '--nas', str(tmp_path / 'launcher.nas'),
                            '--target-size', '.002', '--sheet-normal', '1'],
                           cwd=cads, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert child.returncode == 0, child.stderr + child.stdout
    result = json.loads(child.stdout)
    assert Path(result['nas_path']).is_file()


def test_relocated_distribution_runs_example_and_keeps_only_allowlisted_files(tmp_path):
    from tools.package_cad_to_nastran_mesh_converter import build
    output = build(tmp_path / 'package.zip')
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert not any(part in namestr for namestr in names for part in
                       ('.venv', '.cache', '.tools', '__pycache__', '.git/', 'outputs/'))
        assert archive.read('CAD_to_NAS/brl_mesh/surface_mesh_generation.py') == (adapter.ROOT / 'brl_mesh/surface_mesh_generation.py').read_bytes()
        archive.extractall(tmp_path / 'Other install path')
    relocated = tmp_path / 'Other install path' / 'CAD_to_NAS'
    child = subprocess.run([sys.executable, '-B', str(relocated / 'convert_cad_to_nastran_surface_mesh.py'),
                            '--jobs', str(relocated / 'examples/cad_to_nastran_conversion_jobs.json')],
                           cwd=tmp_path, capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert child.returncode == 0, child.stderr + child.stdout
    result = json.loads(child.stdout)
    assert Path(result['nas_path']).is_relative_to(relocated)
    assert Path(result['nas_path']).is_file()
    assert result['status'] == 'ok'


def test_korean_cad_and_output_paths_work_with_ascii_install(cads, tmp_path, settings):
    source = tmp_path / '한글 CAD' / '입력 판.step'
    source.parent.mkdir()
    source.write_bytes((cads / 'plate.step').read_bytes())
    result = adapter.convert_cad_to_nas(source, tmp_path / '한글 NAS' / '출력 판.nas', options=settings)
    assert result.nas_path.is_file()


def test_unicode_install_path_has_actionable_error(cads, tmp_path, settings, monkeypatch):
    monkeypatch.setattr(adapter, 'ROOT', tmp_path / '한글 설치')
    with pytest.raises(adapter.ConversionError, match='설치 경로'):
        convert(cads, tmp_path, settings)
