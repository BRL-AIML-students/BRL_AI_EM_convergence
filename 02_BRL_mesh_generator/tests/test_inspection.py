from dataclasses import replace

import gmsh
import numpy as np
import pytest

from brl_mesh.engine import mesh_model, publish
from brl_mesh.checks import measure_shape
from brl_mesh.normals import inspect_normals
from brl_mesh.preservation import measure_geometry
from brl_mesh.errors import MeshBlocked
from brl_mesh.inspection import MeshContract, cad_boundary_intent, inspect_mesh
from brl_mesh.model import snapshot
from brl_mesh.quality import read_icn
from tools.quality_policy_probe import run_probe
from tests.support import cad_mesh


def test_icn_single_threshold_cannot_reproduce_retained_policy():
    result = run_probe()
    assert result['cases'] == 104
    assert result['accepted_low_icn']['icn'] < result['rejected_high_icn']['icn']
    assert not result['single_icn_cutoff_preserves_policy']
    assert result['degenerate_preflight_blocked']


def test_stale_snapshot_never_gets_new_metrics_or_published(config):
    with mesh_model(config) as scene:
        membership = scene.membership
        mesh = snapshot(membership)
        nodes, xyz, _ = gmsh.model.mesh.getNodes(2, next(iter(membership)))
        node, point = int(nodes[0]), xyz[:3]
        gmsh.model.mesh.setNode(node, (point + [.001, 0, 0]).tolist(), [])
        with pytest.raises(MeshBlocked, match='snapshot'):
            read_icn(mesh)
        with pytest.raises(MeshBlocked, match='snapshot'):
            publish(mesh, config, scene)
    assert not config.output_dir.exists()


def test_missing_boundary_intent_and_plugin_failure_block(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        mesh = snapshot(membership)
        contract = scene.contract
        incomplete = replace(contract, boundary=replace(contract.boundary, expected_edges=None))
        with pytest.raises(MeshBlocked, match='boundary_intent_missing'):
            inspect_mesh(mesh, incomplete).require_pass()
        monkeypatch.setattr(gmsh.plugin, 'run', lambda *_: (_ for _ in ()).throw(RuntimeError('plugin failed')))
        with pytest.raises(MeshBlocked, match='quality_incomplete'):
            inspect_mesh(mesh, contract).require_pass()


@pytest.mark.parametrize('kind', ['box', 'sphere'])
def test_full_closed_solid_contract(kind):
    with cad_mesh(kind) as membership:
        contract = MeshContract(cad_boundary_intent(1), {}, .35)
        result = inspect_mesh(snapshot(membership), contract)
        result.require_pass()
        assert result.geometry.volume_relative_error_max is not None
        if kind == 'box':
            assert result.geometry.area_relative_error_max < 1e-12
            assert result.geometry.volume_relative_error_max < 1e-12


def test_shared_triangle_calculation_matches_standalone_measurements(config):
    with mesh_model(config) as scene:
        mesh=snapshot(scene.membership)
        expected_shape=measure_shape(mesh)
        expected_normals=inspect_normals(mesh,scene.contract.sheet_signs)
        expected_geometry=measure_geometry(mesh)
        actual=inspect_mesh(mesh,scene.contract)
        np.testing.assert_array_equal(actual.shape.aspect_ratios,expected_shape.aspect_ratios)
        np.testing.assert_array_equal(actual.shape.minimum_angles,expected_shape.minimum_angles)
        assert actual.normals==expected_normals
        assert actual.geometry==expected_geometry


def test_inspection_does_not_reuse_arrays_after_input_mutation(config):
    with mesh_model(config) as scene:
        mesh=snapshot(scene.membership)
        before=inspect_mesh(mesh,scene.contract)
        node=int(gmsh.model.mesh.getNodes(2,next(iter(scene.membership)))[0][0])
        index=int(np.searchsorted(mesh.node_ids,node))
        mesh.coordinates[index,0]+=.001
        with pytest.raises(MeshBlocked,match='snapshot'):
            inspect_mesh(mesh,scene.contract)
        point=mesh.coordinates[index]
        gmsh.model.mesh.setNode(node,point.tolist(),
            gmsh.model.getParametrization(2,next(iter(scene.membership)),point.tolist()).tolist())
        after=inspect_mesh(mesh,scene.contract)
        assert not np.array_equal(before.shape.aspect_ratios,after.shape.aspect_ratios)
        np.testing.assert_array_equal(after.shape.aspect_ratios,measure_shape(mesh).aspect_ratios)


def test_quality_rechecks_current_mesh_after_contract_callback(config,monkeypatch):
    with mesh_model(config) as scene:
        mesh=snapshot(scene.membership)
        node=int(gmsh.model.mesh.getNodes(2,next(iter(scene.membership)))[0][0])
        point=mesh.coordinates[np.searchsorted(mesh.node_ids,node)]+[.001,0,0]
        def mutate(_):
            gmsh.model.mesh.setNode(node,point.tolist(),[])
        monkeypatch.setattr(gmsh.plugin,'run',lambda *_:pytest.fail('must reject stale snapshot before ICN'))
        result=inspect_mesh(mesh,replace(scene.contract,geometry_check=mutate))
        assert [issue.code for issue in result.issues]==['quality_incomplete']
        assert 'snapshot' in result.issues[0].message
