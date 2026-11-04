"""Explicit quality-only regeneration, independent of relocation and publication."""
from dataclasses import replace
import json
from pathlib import Path

import gmsh
import numpy as np
import pytest

from brl_mesh import engine, native_job, native_ui as ui, provenance
from brl_mesh.config import Configuration, Generation, Improvement
from brl_mesh.errors import ConfigurationError, MeshBlocked
from brl_mesh.model import snapshot
from tests.support import distort_interior


def retry_config(config):
    return replace(config, generation=Generation('delaunay'), improvement=Improvement(False, 0))


def distort_first_candidate(monkeypatch):
    original = engine._generate_candidate
    algorithms = []
    def candidate(config, reference, sizing, curvature):
        algorithm = gmsh.option.getNumber('Mesh.Algorithm')
        algorithms.append(algorithm)
        scene = original(config, reference, sizing, curvature)
        if algorithm == 6:
            distort_interior(scene.membership)
        return scene
    monkeypatch.setattr(engine, '_generate_candidate', candidate)
    return algorithms


@pytest.mark.parametrize('value', [None, [], True, {'unknown': 'none'}, {'quality_retry': True},
                                   {'quality_retry': 5}, {'quality_retry': 'automatic'}])
def test_generation_retry_schema_is_strict(config, value):
    with pytest.raises(ConfigurationError):
        Configuration.from_dict(config.to_dict() | {'generation': value})


@pytest.mark.parametrize('mode', ['none', 'delaunay'])
def test_generation_retry_config_and_native_controls_round_trip(config, mode):
    configured = replace(config, generation=Generation(mode))
    assert Configuration.from_dict(configured.to_dict()) == configured
    gmsh.initialize(readConfigFiles=False)
    try:
        ui.install_controls(configured)
        assert json.loads(gmsh.onelab.get(ui.QUALITY_RETRY))['choices'] == ['none', 'delaunay']
        assert ui.read_controls(configured, config.output_dir.parent) == configured
    finally:
        gmsh.finalize()


def test_omitted_retry_is_none_and_same_mesh_as_explicit_none(config):
    value = config.to_dict()
    value.pop('generation')
    assert Configuration.from_dict(value).generation == Generation('none')
    results = []
    for candidate in (Configuration.from_dict(value), config):
        with engine.mesh_model(candidate) as scene:
            scene, prepared = engine.prepare_generated(scene, candidate)
            results.append(prepared.mesh)
            assert json.loads(scene.generation_provenance)['configured_options']['Mesh.Algorithm'] == 6
    assert results[0].same_structure(results[1])
    assert np.array_equal(results[0].coordinates, results[1].coordinates)


def test_shape_only_failure_retries_once_and_publishes_independent_nas(config, monkeypatch):
    configured = retry_config(config)
    algorithms = distort_first_candidate(monkeypatch)
    with engine.mesh_model(configured) as scene:
        scene, prepared = engine.prepare_generated(scene, configured)
        assert algorithms == [6, 5]
        assert not prepared.inspection.issues and prepared.inspection.shape.violating_count == 0
        metadata = provenance.require_current(scene.generation_provenance, configured, scene.cad.digest)
        assert metadata['schema'] == 3
        assert metadata['configured_options']['Mesh.Algorithm'] == 5
        assert metadata['effective_config']['generation'] == {'quality_retry': 'delaunay'}
        assert metadata['actual_algorithm'] is None
        assert engine.publish(prepared.mesh, configured, scene).nas_path.exists()


def test_cli_run_uses_same_shape_retry(config, monkeypatch):
    algorithms = distort_first_candidate(monkeypatch)
    assert engine.run(retry_config(config)).nas_path.exists()
    assert algorithms == [6, 5]


def test_passing_opt_in_does_not_generate_alternate(config, monkeypatch):
    original = engine._generate_candidate
    algorithms = []
    def candidate(*args):
        algorithms.append(gmsh.option.getNumber('Mesh.Algorithm'))
        return original(*args)
    monkeypatch.setattr(engine, '_generate_candidate', candidate)
    engine.run(retry_config(config))
    assert algorithms == [6]


def test_default_none_does_not_retry_shape_failure(config, monkeypatch):
    algorithms = distort_first_candidate(monkeypatch)
    with pytest.raises(MeshBlocked, match='AR'):
        engine.run(replace(config, improvement=Improvement(False, 0)))
    assert algorithms == [6]
    assert not list(config.output_dir.rglob('*.nas'))


def test_second_shape_failure_stops_without_third_candidate(config, monkeypatch):
    original = engine._generate_candidate
    algorithms = []
    def candidate(config, reference, sizing, curvature):
        algorithms.append(gmsh.option.getNumber('Mesh.Algorithm'))
        scene = original(config, reference, sizing, curvature)
        distort_interior(scene.membership)
        return scene
    monkeypatch.setattr(engine, '_generate_candidate', candidate)
    with pytest.raises(MeshBlocked, match='AR'):
        engine.run(retry_config(config))
    assert algorithms == [6, 5]
    assert not list(config.output_dir.rglob('*.nas'))


@pytest.mark.parametrize('failure', ['generate', 'improve', 'nonshape'])
def test_exception_or_nonshape_failure_never_retries(config, monkeypatch, failure):
    original = engine._generate_candidate
    algorithms = []
    def candidate(*args):
        algorithms.append(gmsh.option.getNumber('Mesh.Algorithm'))
        if failure == 'generate':
            raise RuntimeError('ambiguous mesher failure')
        return original(*args)
    monkeypatch.setattr(engine, '_generate_candidate', candidate)
    if failure == 'improve':
        monkeypatch.setattr(engine, 'improve', lambda *_: (_ for _ in ()).throw(MeshBlocked('rollback failure')))
    elif failure == 'nonshape':
        original_improve = engine.improve
        def bad_contract(membership, contract, settings):
            # Independently check a deliberately wrong expected component count.
            boundary = replace(contract.boundary, expected_components=2)
            return original_improve(membership, replace(contract, boundary=boundary), settings)
        monkeypatch.setattr(engine, 'improve', bad_contract)
    with pytest.raises((MeshBlocked, RuntimeError)):
        engine.run(retry_config(config))
    assert algorithms == [6]
    assert not list(config.output_dir.rglob('*.nas'))


def test_retry_uses_fresh_curvature_plan_and_preserves_fields(config, monkeypatch):
    from brl_mesh.sizing_config import Curvature
    configured = retry_config(config)
    configured = replace(configured, sizing=replace(configured.sizing, curvature=Curvature(.01, feedback='local')))
    value = configured.to_dict()
    value['mesh'].setdefault('local', {})['boxes'] = [{'bounds': [.2, .2, -.1, .8, .8, .1], 'size': .2}]
    configured = Configuration.from_dict(value)
    original = engine._generate_candidate
    plans, fields = [], []
    def candidate(config, reference, sizing, curvature):
        plans.append(curvature)
        fields.append((sizing, tuple(gmsh.model.mesh.field.list())))
        assert curvature._patches == {} and curvature._feedback is None
        scene = original(config, reference, sizing, curvature)
        if len(plans) == 1:
            distort_interior(scene.membership)
            # A failed candidate's feedback/cache must not reach the next plan.
            curvature.iterations = 123
            curvature._patches[-1] = [object()]
            curvature._feedback = object()
        return scene
    monkeypatch.setattr(engine, '_generate_candidate', candidate)
    engine.run(configured)
    assert len(plans) == 2 and plans[0] is not plans[1]
    assert plans[1].iterations != 123
    assert fields[0] == fields[1] and fields[0][1]


def request_current(root, config, scene, action):
    root.mkdir()
    mesh = snapshot(scene.membership)
    native_job.save_mesh(root / 'input.msh')
    native_job.write_json(root / 'request.json', dict(config=config.to_dict(), action=action,
        signature=native_job.canonical(scene.cad.signature), digest=scene.cad.digest,
        boundary=native_job.canonical(scene.fixed_boundary), mesh_digest=native_job.mesh_digest(mesh),
        generation_provenance=scene.generation_provenance))


def test_worker_retry_adoption_and_current_actions_preserve_algorithm_five(config, tmp_path, monkeypatch):
    configured = retry_config(config)
    algorithms = distort_first_candidate(monkeypatch)
    root = tmp_path / 'generate-job'
    root.mkdir()
    native_job.write_json(root / 'request.json', {'config': configured.to_dict(), 'action': 2})
    gmsh.initialize(readConfigFiles=False)
    try:
        result = native_job.execute(root)
        assert algorithms == [6, 5]
        job = native_job.NativeJob.__new__(native_job.NativeJob)
        job.config, job.action, job.root = configured, 2, root
        scene, mesh = job.adopt(result, None)
        assert gmsh.option.getNumber('Mesh.Algorithm') == 5
        assert json.loads(scene.generation_provenance)['configured_options']['Mesh.Algorithm'] == 5
        for action in (3, 4):
            current_root = tmp_path / f'current-{action}'
            request_current(current_root, configured, scene, action)
            gmsh.clear()  # Model a fresh owned worker, rather than an existing parent.
            current = native_job.execute(current_root)
            assert current['generation_provenance'] == result['generation_provenance']
            assert gmsh.option.getNumber('Mesh.Algorithm') == 5
            # Reconstruct a parent scene for the next current action.
            job.root = root
            scene, mesh = job.adopt(result, None)
        assert algorithms == [6, 5]  # Current actions never remesh.
    finally:
        gmsh.finalize()


@pytest.mark.parametrize('option', ['Mesh.Algorithm', 'General.NumThreads'])
def test_current_job_dispatch_rejects_changed_generation_options(config, monkeypatch, option):
    with engine.mesh_model(config) as scene:
        old = gmsh.option.getNumber(option)
        gmsh.option.setNumber(option, old+1)
        launched = []
        monkeypatch.setattr(native_job.subprocess, 'Popen', lambda *_a, **_k: launched.append(True))
        try:
            with pytest.raises(MeshBlocked, match='provenance'):
                native_job.NativeJob(config, 4, scene)
            assert not launched
        finally:
            gmsh.option.setNumber(option, old)


def test_provenance_five_requires_opt_in_and_restore_rejects_other_option_changes(config):
    with engine.mesh_model(config) as scene:
        data = json.loads(scene.generation_provenance)
        data['configured_options']['Mesh.Algorithm'] = 5
        with pytest.raises(MeshBlocked, match='schema'):
            provenance.validate_schema(data)
        with pytest.raises(MeshBlocked, match='provenance'):
            provenance.restore_generation_algorithm(provenance.canonical(data), config, None)
        assert gmsh.option.getNumber('Mesh.Algorithm') == 6
        old = gmsh.option.getNumber('General.NumThreads')
        gmsh.option.setNumber('General.NumThreads', old+1)
        try:
            with pytest.raises(MeshBlocked, match='provenance'):
                provenance.restore_generation_algorithm(scene.generation_provenance, config, None)
            assert gmsh.option.getNumber('Mesh.Algorithm') == 6
        finally:
            gmsh.option.setNumber('General.NumThreads', old)

@pytest.mark.parametrize('option', ['Mesh.Algorithm', 'General.NumThreads'])
def test_current_job_adoption_rejects_changed_parent_generation_options(config, tmp_path, option):
    with engine.mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        job = native_job.NativeJob.__new__(native_job.NativeJob)
        job.config, job.action, job.root, job.original = config, 3, tmp_path, mesh
        result = dict(generation_provenance=scene.generation_provenance,
                      mesh_digest=native_job.mesh_digest(mesh))
        old = gmsh.option.getNumber(option)
        gmsh.option.setNumber(option, old+1)
        try:
            with pytest.raises(MeshBlocked, match='provenance'):
                job.adopt(result, scene)
        finally:
            gmsh.option.setNumber(option, old)


def test_retry_control_change_requires_regeneration(config):
    gmsh.initialize(readConfigFiles=False)
    try:
        controller = ui.Controller(config, config.output_dir.parent)
        controller.perform(2)
        assert controller.scene is not None
        gmsh.onelab.setString(ui.QUALITY_RETRY, ['delaunay'])
        controller.invalidate_if_changed()
        assert controller.scene is None
        assert ui.read_controls(config, config.output_dir.parent).generation == Generation('delaunay')
    finally:
        gmsh.finalize()


def test_retry_clear_failure_blocks_without_generating_alternate(config, monkeypatch):
    algorithms = distort_first_candidate(monkeypatch)
    def fail_clear(*_a, **_k):
        raise RuntimeError('cannot clear failed candidate')
    monkeypatch.setattr(gmsh.model.mesh, 'clear', fail_clear)
    with pytest.raises(RuntimeError, match='cannot clear'):
        engine.run(retry_config(config))
    assert algorithms == [6]
    assert not list(config.output_dir.rglob('*.nas'))


def test_retry_does_not_hide_field_change_after_inspection(config, monkeypatch):
    algorithms = distort_first_candidate(monkeypatch)
    original = engine.improve
    def changed_field(*args):
        result = original(*args)
        field = gmsh.model.mesh.field.add('MathEval')
        gmsh.model.mesh.field.setString(field, 'F', '.1')
        return result
    monkeypatch.setattr(engine, 'improve', changed_field)
    with pytest.raises(MeshBlocked, match='size_field_changed'):
        engine.run(retry_config(config))
    assert algorithms == [6]
    assert not list(config.output_dir.rglob('*.nas'))


def test_provenance_schema_one_is_explicitly_unsupported(config):
    with engine.mesh_model(config) as scene:
        data = json.loads(scene.generation_provenance)
        data['schema'] = 1
        with pytest.raises(MeshBlocked, match='schema'):
            provenance.validate_schema(data)

@pytest.mark.parametrize('option', ['Mesh.Algorithm', 'General.NumThreads'])
def test_synchronous_current_improve_rejects_changed_generation_options(config, option):
    gmsh.initialize(readConfigFiles=False)
    try:
        controller = ui.Controller(config, config.output_dir.parent)
        controller.perform(2)
        old = gmsh.option.getNumber(option)
        gmsh.option.setNumber(option, old+1)
        try:
            with pytest.raises(MeshBlocked, match='provenance'):
                controller.perform(3)
        finally:
            gmsh.option.setNumber(option, old)
    finally:
        gmsh.finalize()
