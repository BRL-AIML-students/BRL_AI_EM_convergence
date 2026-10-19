from dataclasses import replace

import gmsh
import numpy as np
import pytest

from brl_mesh.config import Improvement
from brl_mesh.engine import mesh_model, publish
from brl_mesh.errors import MeshBlocked
from brl_mesh.improvement import improve
from brl_mesh.inspection import MeshContract, cad_boundary_intent, inspect_mesh
from brl_mesh.model import snapshot
from tests.support import cad_mesh, distort_interior


def node_state():
    ids, _, _ = gmsh.model.mesh.getNodes()
    return {int(n): gmsh.model.mesh.getNode(int(n)) for n in ids}


def assert_exact_state(before):
    after = node_state()
    assert set(after) == set(before)
    for n, (xyz, param, dim, entity) in before.items():
        assert np.array_equal(after[n][0], xyz)
        assert np.array_equal(after[n][1], param)
        assert after[n][2:] == (dim, entity)


def test_real_relocate_improves_without_changing_structure(config):
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        before = snapshot(membership)
        contract = scene.contract
        old = inspect_mesh(before, contract)
        assert old.shape.violating_count > 0 and not old.issues
        result = improve(membership, contract, Improvement(True, 3))
        result.inspection.require_pass()
        assert result.mesh.same_structure(before)
        assert result.inspection.minimum_icn > old.minimum_icn
        assert result.attempts[0].method == 'Relocate2D' and result.attempts[0].accepted


def test_real_closed_solid_relocation_preserves_area_volume():
    with cad_mesh('box') as membership:
        face = next(iter(membership))
        before = snapshot(membership)
        ids, xyz, _ = gmsh.model.mesh.getNodes(2, face)
        xyz = np.asarray(xyz).reshape(-1, 3)
        node = int(ids[np.argmin(np.linalg.norm(xyz - xyz.mean(axis=0), axis=1))])
        origin = before.coordinates[np.searchsorted(before.node_ids, node)]
        incident = before.connectivity[np.any(before.connectivity == node, axis=1)]
        neighbor = next(int(n) for n in np.unique(incident) if n != node)
        other = before.coordinates[np.searchsorted(before.node_ids, neighbor)]
        point = origin + .85 * (other - origin)
        gmsh.model.mesh.setNode(node, point.tolist(), gmsh.model.getParametrization(2, face, point.tolist()).tolist())
        contract = MeshContract(cad_boundary_intent(1), {}, .35)
        old = inspect_mesh(snapshot(membership), contract)
        assert old.shape.violating_count > 0
        result = improve(membership, contract, Improvement(True, 3))
        result.inspection.require_pass()
        assert result.attempts[0].accepted
        assert result.inspection.geometry.area_relative_error_max < 1e-12
        assert result.inspection.geometry.volume_relative_error_max < 1e-12


def test_second_pass_can_use_real_laplace(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        optimize, calls = gmsh.model.mesh.optimize, []
        def skip_first(method, **kwargs):
            calls.append(method)
            if len(calls) > 1:
                return optimize(method, **kwargs)
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', skip_first)
        result = improve(membership, scene.contract, Improvement(True, 2))
        assert calls == ['Relocate2D', 'Laplace2D']
        assert result.attempts[0].rolled_back
        result.inspection.require_pass()


def test_maximum_passes_are_bounded_when_nothing_improves(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        calls = []
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', lambda method, **kwargs: calls.append(method))
        result = improve(membership, scene.contract, Improvement(True, 3))
        assert len(calls) == 3 and len(result.attempts) == 3
        assert all(a.rolled_back for a in result.attempts)
        with pytest.raises(MeshBlocked):
            result.inspection.require_pass()


@pytest.mark.parametrize('damage', ['worse', 'degenerate', 'off_cad', 'fixed_node'])
def test_bad_candidate_restores_coordinates_parameters_and_classification(config, monkeypatch, damage):
    with mesh_model(config) as scene:
        membership = scene.membership
        node, original, target = distort_interior(membership)
        before = snapshot(membership)
        state = node_state()
        def bad_candidate(*args, **kwargs):
            if damage == 'worse':
                point = original + .95 * (target - original)
            elif damage == 'degenerate':
                point = target
            elif damage == 'off_cad':
                point = state[node][0] + [0, 0, .01]
            else:
                fixed = next(n for n, data in state.items() if data[2] == 0)
                gmsh.model.mesh.setNode(fixed, (state[fixed][0] + [.01, 0, 0]).tolist(), [])
                return
            gmsh.model.mesh.setNode(node, point.tolist(), state[node][1].tolist())
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', bad_candidate)
        result = improve(membership, scene.contract, Improvement(True, 1))
        assert len(result.attempts) == 1 and result.attempts[0].rolled_back
        assert_exact_state(state)
        assert np.array_equal(result.mesh.coordinates, before.coordinates)
        with pytest.raises(MeshBlocked, match='AR'):
            result.inspection.require_pass()


@pytest.mark.parametrize('change', ['connectivity', 'lower_connectivity', 'physical_group', 'entity'])
def test_structure_change_blocks_instead_of_approximating_rollback(config, monkeypatch, change):
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        face = next(iter(membership))
        def change_structure(*args, **kwargs):
            if change == 'connectivity':
                gmsh.model.mesh.reverse([(2, face)])
            elif change == 'lower_connectivity':
                gmsh.model.mesh.reverse([gmsh.model.getEntities(1)[0]])
            elif change == 'physical_group':
                gmsh.model.removePhysicalGroups([(2, 1)])
                gmsh.model.addPhysicalGroup(2, [face], 99)
            else:
                gmsh.model.occ.addPoint(5, 5, 0)
                gmsh.model.occ.synchronize()
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', change_structure)
        with pytest.raises(MeshBlocked, match='연결|PID|entity'):
            improve(membership, scene.contract, Improvement(True, 1))
    assert not config.output_dir.exists()


def test_optimizer_exception_after_partial_move_restores_then_blocks(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        node, _, _ = distort_interior(membership)
        state = node_state()
        def fail(*args, **kwargs):
            gmsh.model.mesh.setNode(node, (state[node][0] + [.001, 0, 0]).tolist(), state[node][1].tolist())
            raise RuntimeError('optimizer interrupted')
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', fail)
        with pytest.raises(MeshBlocked, match='개선 실행 실패'):
            improve(membership, scene.contract, Improvement(True, 1))
        assert_exact_state(state)


def test_failed_rollback_blocks_output(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        node, original, target = distort_interior(membership)
        set_node = gmsh.model.mesh.setNode
        restoring = []
        def bad_candidate(*args, **kwargs):
            set_node(node, (original + .95 * (target - original)).tolist(), [])
            restoring.append(True)
        def fail_restore(*args, **kwargs):
            if restoring:
                raise RuntimeError('node restoration failed')
            return set_node(*args, **kwargs)
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', bad_candidate)
        monkeypatch.setattr(gmsh.model.mesh, 'setNode', fail_restore)
        with pytest.raises(MeshBlocked, match='rollback 실패'):
            improve(membership, scene.contract, Improvement(True, 1))
    assert not config.output_dir.exists()


def test_failed_candidate_measurement_never_publishes_and_cleans_views(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        state = node_state()
        run = gmsh.plugin.run
        calls = []
        retained = gmsh.view.add('user view')
        def interrupted(name):
            calls.append(name)
            if len(calls) == 2:
                raise RuntimeError('candidate ICN unavailable')
            return run(name)
        monkeypatch.setattr(gmsh.plugin, 'run', interrupted)
        result = improve(membership, scene.contract, Improvement(True, 1))
        assert result.attempts[0].rolled_back
        assert_exact_state(state)
        assert set(gmsh.view.getTags()) == {retained}
        with pytest.raises(MeshBlocked):
            publish(result.mesh, config, scene)
    assert not config.output_dir.exists()


def test_topology_incomplete_never_calls_optimizer(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        contract = scene.contract
        contract = replace(contract, boundary=replace(contract.boundary, expected_edges=None))
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', lambda *a, **k: pytest.fail('must not relocate topology failure'))
        with pytest.raises(MeshBlocked, match='boundary_intent_missing'):
            improve(membership, contract, Improvement())


def test_disabled_improvement_keeps_failure_and_is_not_success(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        state = node_state()
        monkeypatch.setattr(gmsh.model.mesh, 'optimize', lambda *a, **k: pytest.fail('improvement is disabled'))
        result = improve(membership, scene.contract, Improvement(False, 3))
        assert not result.attempts
        assert_exact_state(state)
        with pytest.raises(MeshBlocked):
            result.inspection.require_pass()


def test_publication_rechecks_after_an_earlier_success(config):
    with mesh_model(config) as scene:
        membership = scene.membership
        inspect_mesh(snapshot(membership), scene.contract).require_pass()
        gmsh.model.mesh.reverse([(2, next(iter(membership)))])
        with pytest.raises(MeshBlocked, match='inward_normal'):
            publish(snapshot(membership), config, scene)
    assert not config.output_dir.exists()


@pytest.mark.parametrize('metric', ['size', 'local_size', 'gradation', 'centroid', 'node', 'area', 'volume'])
def test_improved_shape_does_not_hide_preservation_regressions(config, monkeypatch, metric):
    import brl_mesh.improvement as module
    with mesh_model(config) as scene:
        membership = scene.membership
        distort_interior(membership)
        state = node_state()
        inspect = module.inspect_mesh
        calls = []
        def degraded_evidence(mesh, contract):
            result = inspect(mesh, contract)
            calls.append(result)
            if len(calls) == 2:
                old = calls[0]
                if metric == 'size':
                    result = replace(result, edge_max_to_target=old.edge_max_to_target * 1.1)
                elif metric == 'local_size':
                    result = replace(result, local_edge_max_to_target=old.local_edge_max_to_target + .1)
                elif metric == 'gradation':
                    result = replace(result, topology=replace(result.topology,
                        adjacent_size_ratio_max=old.topology.adjacent_size_ratio_max * 1.1))
                elif metric == 'centroid':
                    result = replace(result, normals=replace(result.normals, max_centroid_deviation=.1))
                elif metric == 'node':
                    result = replace(result, normals=replace(result.normals, max_node_deviation=.1))
                elif metric == 'area':
                    result = replace(result, geometry=replace(result.geometry, area_relative_error_max=.1))
                else:
                    result = replace(result, geometry=replace(result.geometry, volume_relative_error_max=.1))
            return result
        monkeypatch.setattr(module, 'inspect_mesh', degraded_evidence)
        result = improve(membership, scene.contract, Improvement(True, 1))
        assert result.attempts[0].rolled_back
        assert_exact_state(state)
