"""Configurable gates must reach improvement, regeneration and final publication."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

import convert_cad_to_nastran_surface_mesh as converter
from brl_mesh.mesh_quality_settings import QualitySettings, parse_quality_settings
from brl_mesh.mesh_generator_configuration import Configuration
from brl_mesh.mesh_generator_errors import ConfigurationError, MeshBlocked
from brl_mesh.surface_mesh_generation import mesh_model, publish, prepare_generated
from brl_mesh.surface_mesh_snapshot import snapshot
from brl_mesh.mesh_node_relocation import improve
import brl_mesh.mesh_contract_inspection as inspection

from tests.test_convert_cad_to_nastran_surface_mesh import cads, settings


@pytest.mark.parametrize('value', [
    {'unknown': True}, {'icn_enabled': 1}, {'aspect_ratio_enabled': 'off'},
    {'minimum_angle_enabled': None}, {'radius_ratio_enabled': []},
    {'icn_minimum': -.1}, {'icn_minimum': 1.1}, {'icn_minimum': True},
    {'aspect_ratio_maximum': .9}, {'minimum_angle_degrees': -1},
    {'minimum_angle_degrees': 61}, {'radius_ratio_minimum': float('nan')},
    {'icn_enabled': False, 'icn_minimum': 2},
])
def test_invalid_quality_settings_are_rejected_even_when_disabled(value):
    with pytest.raises(ConfigurationError):
        parse_quality_settings(value)


def test_quality_roundtrip_and_strict_unknown_keys(config):
    data = config.to_dict()
    data['quality'] = {'icn_enabled': False, 'radius_ratio_enabled': True,
                       'radius_ratio_minimum': .4, 'aspect_ratio_maximum': 4}
    updated = Configuration.from_dict(data)
    assert Configuration.from_dict(updated.to_dict()) == updated
    assert updated.quality == QualitySettings(icn_enabled=False, radius_ratio_enabled=True,
                                              radius_ratio_minimum=.4, aspect_ratio_maximum=4)


def test_icn_off_never_calls_plugin_in_improvement_or_publication(config, monkeypatch):
    config = replace(config, quality=QualitySettings(icn_enabled=False))
    def forbidden(*args):
        pytest.fail('ICN OFF must not call AnalyseMeshQuality')
    monkeypatch.setattr(inspection, 'read_icn', forbidden)
    with mesh_model(config) as scene:
        scene, result = prepare_generated(scene, config)
        assert not result.inspection.icn
        assert publish(result.mesh, config, scene).nas_path.is_file()


@pytest.mark.parametrize('metric,threshold', [
    ('icn', {'icn_minimum': .9}),
    ('aspect_ratio', {'aspect_ratio_maximum': 1}),
    ('minimum_angle', {'minimum_angle_degrees': 60}),
    ('radius_ratio', {'radius_ratio_enabled': True, 'radius_ratio_minimum': .9}),
])
def test_each_gate_threshold_and_off_switch(config, monkeypatch, metric, threshold):
    monkeypatch.setattr(inspection, 'read_icn', lambda mesh: {int(tag): .5 for tag in mesh.element_ids})
    monkeypatch.setattr(inspection, 'read_radius_ratio', lambda mesh: np.full(len(mesh.element_ids), .5))
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        policy = QualitySettings(**threshold)
        failed = inspection.inspect_mesh(mesh, replace(scene.contract, quality=policy))
        assert failed.violating_count > 0
        with pytest.raises(MeshBlocked):
            failed.require_pass()
        passed = inspection.inspect_mesh(mesh, replace(scene.contract, quality=replace(policy, **{metric+'_enabled': False})))
        passed.require_pass()
        assert passed.violating_count == 0


def test_all_gates_off_keeps_geometry_and_normals_mandatory(config, monkeypatch):
    policy = QualitySettings(icn_enabled=False, aspect_ratio_enabled=False,
                             minimum_angle_enabled=False, radius_ratio_enabled=False)
    config = replace(config, quality=policy)
    with mesh_model(config) as scene:
        contract = replace(scene.contract, geometry_check=lambda mesh: (_ for _ in ()).throw(MeshBlocked('geometry required')))
        with pytest.raises(MeshBlocked, match='geometry required'):
            inspection.inspect_mesh(snapshot(scene.membership), contract).require_pass()


def test_publication_rejects_active_threshold_even_without_improvement(config):
    config = replace(config, quality=QualitySettings(aspect_ratio_maximum=1))
    with mesh_model(config) as scene:
        with pytest.raises(MeshBlocked, match='형상 조건'):
            publish(snapshot(scene.membership), config, scene)


def test_improvement_uses_enabled_metrics_when_icn_off(config, monkeypatch):
    from tests.mesh_test_helpers import distort_interior
    config = replace(config, quality=QualitySettings(icn_enabled=False))
    with mesh_model(config) as scene:
        distort_interior(scene.membership)
        before = inspection.inspect_mesh(snapshot(scene.membership), scene.contract)
        result = improve(scene.membership, scene.contract, config.improvement)
        assert before.violating_count > 0 and result.attempts
        assert result.inspection.violating_count <= before.violating_count
        assert not result.inspection.icn


@pytest.mark.parametrize('options,match', [
    ({'frequency_hz': 1e9}, '지원하지 않는'),
    ({'target_size_enabled': False}, 'mesh_frequency_hz'),
    ({'wavelength_sizing_enabled': False, 'target_size': None, 'mesh_frequency_hz': 1e9}, 'mesh_frequency_hz'),
    ({'local_size_fields_enabled': 0}, 'bool'),
    ({'local_size_fields_enabled': False, 'local': {'growth_rate': -1}}, 'growth_rate'),
    ({'curvature': False, 'curvature_sampling_nodes': 2}, 'sampling_nodes'),
    ({'wavelength_sizing_enabled': False, 'relative_permittivity': None}, 'relative_permittivity'),
    ({'quality': {'icn_enabled': False, 'icn_minimum': -1}}, 'icn_minimum'),
])
def test_invalid_inactive_adapter_settings_do_not_publish(cads, tmp_path, settings, options, match):
    with pytest.raises(converter.ConversionError, match=match):
        converter.convert_cad_to_nas(cads/'plate.brep', tmp_path/'invalid.nas', options=settings, **options)
    assert not list(tmp_path.iterdir())


def test_mesh_only_frequency_is_independent_and_can_be_disabled(cads, tmp_path, settings):
    mom_frequency_hz = 42e9  # Solver state is never passed to the converter.
    result = converter.convert_cad_to_nas(cads/'box.brep', tmp_path/'wave.nas', options=settings,
        target_size=None, mesh_frequency_hz=29979245800, elements_per_wavelength=5)
    assert result.applied_options['mesh']['wave']['mesh_frequency_hz'] == 29979245800
    assert mom_frequency_hz == 42e9
    result = converter.convert_cad_to_nas(cads/'box.brep', tmp_path/'no-wave.nas', options=settings,
        mesh_frequency_hz=29979245800, wavelength_sizing_enabled=False)
    assert 'wave' not in result.applied_options['mesh']
    assert result.applied_options['mesh']['target_size'] == 2


@pytest.mark.parametrize('switch', ['local_size_fields_enabled', 'local_boxes_enabled'])
def test_local_field_switch_preserves_stored_configuration(cads, tmp_path, settings, switch):
    local = {'boxes': [{'bounds': [0, 0, -1, 3, 3, 1], 'size': 1}]}
    result = converter.convert_cad_to_nas(cads/'plate.brep', tmp_path/'mesh.nas', options=settings,
                                          local=local, **{switch: False})
    assert not result.applied_options['mesh'].get('local', {}).get('boxes')
    assert local['boxes'][0]['size'] == 1


def test_editable_options_file_runs_real_cad(cads, tmp_path):
    source = converter.ROOT/'examples/cad_to_nastran_mesh_options.json'
    data = json.loads(source.read_text(encoding='utf-8'))
    assert set(data) == set(converter.DEFAULT_OPTIONS)
    data.update(output_unit='mm', target_size=2, sheet_normal=1, minimum_size_enabled=False)
    data['quality'].update(icn_enabled=False, aspect_ratio_maximum=4, minimum_angle_degrees=15)
    path = tmp_path/'mesh-settings.json'
    path.write_text(json.dumps(data))
    result = converter.convert_cad_to_nas(cads/'plate.brep', tmp_path/'mesh.nas',
                                          options=converter.load_mesh_options(path))
    assert result.applied_options['quality']['icn_enabled'] is False
    assert result.applied_options['quality']['aspect_ratio_maximum'] == 4


def test_import_and_options_loading_do_not_import_gmsh():
    code = ('import sys; from convert_cad_to_nastran_surface_mesh import load_mesh_options; '
            'load_mesh_options("examples/cad_to_nastran_mesh_options.json"); '
            'assert "gmsh" not in sys.modules')
    child = subprocess.run([sys.executable, '-B', '-c', code], cwd=converter.ROOT,
                           capture_output=True, text=True, timeout=15)
    assert child.returncode == 0, child.stderr


def test_separate_quality_file_cli(cads, tmp_path, settings):
    path = tmp_path/'options.json'
    settings['quality'] = {'minimum_angle_degrees': 15}
    path.write_text(json.dumps(settings))
    quality = tmp_path/'quality.json'
    quality.write_text(json.dumps({'icn_enabled': False, 'aspect_ratio_enabled': False}))
    child = subprocess.run([sys.executable, '-B', str(converter.ROOT/'convert_cad_to_nastran_surface_mesh.py'),
        '--cad', str(cads/'plate.brep'), '--nas', str(tmp_path/'mesh.nas'),
        '--options', str(path), '--quality', str(quality), '--wavelength-sizing-enabled', 'off'],
        cwd=tmp_path, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert child.returncode == 0, child.stderr+child.stdout
    result = json.loads(child.stdout)
    assert result['applied_options']['quality']['icn_enabled'] is False
    assert result['applied_options']['quality']['minimum_angle_degrees'] == 15


def test_target_floor_and_manual_curves_can_be_switched_off(cads, tmp_path, settings):
    result = converter.convert_cad_to_nas(cads/'plate.brep', tmp_path/'mesh.nas', options=settings,
        target_size_enabled=False, mesh_frequency_hz=29979245800, elements_per_wavelength=5,
        minimum_size=100, minimum_size_enabled=False, local_curves_enabled=False,
        local={'curves': [{'entity': 999, 'size': .1}]})
    mesh = result.applied_options['mesh']
    assert 'target_size' not in mesh and 'minimum_size' not in mesh
    assert mesh['wave']['mesh_frequency_hz'] == 29979245800
    assert not mesh.get('local', {}).get('curves')


def test_all_quality_gates_off_skips_node_relocation(config, monkeypatch):
    import brl_mesh.mesh_node_relocation as relocation
    policy = QualitySettings(icn_enabled=False, aspect_ratio_enabled=False,
                             minimum_angle_enabled=False, radius_ratio_enabled=False)
    config = replace(config, quality=policy)
    def forbidden(*args, **kwargs):
        pytest.fail('No quality gate is active; node relocation must be skipped')
    monkeypatch.setattr(relocation.gmsh.model.mesh, 'optimize', forbidden)
    with mesh_model(config) as scene:
        result = improve(scene.membership, scene.contract, config.improvement)
        assert not result.attempts


def test_quality_change_requires_regeneration(config):
    with mesh_model(config) as scene:
        changed = replace(config, quality=replace(config.quality, icn_enabled=False))
        with pytest.raises(MeshBlocked, match='다시 생성'):
            publish(snapshot(scene.membership), changed, scene)


def test_old_mesh_frequency_key_is_rejected_in_engine(config):
    data = config.to_dict()
    data['mesh']['wave'] = {'frequency_hz': 1e9}
    with pytest.raises(ConfigurationError, match='frequency_hz'):
        Configuration.from_dict(data)


@pytest.mark.parametrize('threshold,blocked', [(.1, False), (1.0, True)])
def test_real_radius_ratio_gate_controls_nas_publication(cads, tmp_path, settings, threshold, blocked):
    options = {**settings, 'improvement': False,
               'quality': {'radius_ratio_enabled': True, 'radius_ratio_minimum': threshold}}
    if blocked:
        with pytest.raises(converter.ConversionError, match='radius ratio') as error:
            converter.convert_cad_to_nas(cads/'plate.brep', tmp_path/'mesh.nas', options=options)
        assert error.value.result.status == 'blocked'
        assert not list(tmp_path.iterdir())
    else:
        result = converter.convert_cad_to_nas(cads/'plate.brep', tmp_path/'mesh.nas', options=options)
        assert result.nas_path.is_file()
        assert result.applied_options['quality']['radius_ratio_enabled'] is True


def test_quality_retry_works_without_icn(config, monkeypatch):
    from tests.test_mesh_generation_quality_retry import retry_config, distort_first_candidate
    configured = replace(retry_config(config), quality=QualitySettings(icn_enabled=False))
    algorithms = distort_first_candidate(monkeypatch)
    def forbidden(*args):
        pytest.fail('ICN must stay off in the regenerated mesh too')
    monkeypatch.setattr(inspection, 'read_icn', forbidden)
    with mesh_model(configured) as scene:
        scene, result = prepare_generated(scene, configured)
        assert algorithms == [6, 5]
        assert not result.inspection.icn
        assert publish(result.mesh, configured, scene).nas_path.is_file()
