import gmsh
import numpy as np
import pytest

from brl_mesh.engine import plate_model
from brl_mesh.errors import MeshBlocked
from brl_mesh.model import snapshot
from brl_mesh.quality import read_icn


def test_plugin_maps_sparse_element_ids_and_preserves_views_visibility(square):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.model.add('sparse')
        gmsh.model.addDiscreteEntity(2, 7)
        gmsh.model.mesh.addNodes(2, 7, square.node_ids, square.coordinates.ravel())
        gmsh.model.mesh.addElementsByType(7, 2, square.element_ids, square.connectivity.ravel())
        retained = gmsh.view.add('unrelated user view')
        gmsh.model.mesh.setVisibility([100], 0)
        before_visibility = gmsh.model.mesh.getVisibility(square.element_ids)
        values = read_icn(square)
        assert set(values) == {100, 200}
        assert all(np.isfinite(list(values.values())))
        assert set(gmsh.view.getTags()) == {retained}
        assert np.array_equal(gmsh.model.mesh.getVisibility(square.element_ids), before_visibility)
        # Recompute after moving a node: no stale cached values.
        gmsh.model.mesh.setNode(20, [0.5, 0, 0], [])
        changed = read_icn(snapshot({7: 1}))
        assert changed[100] != pytest.approx(values[100])
    finally:
        gmsh.finalize()


def test_plugin_failure_cleans_only_its_views(config, monkeypatch):
    with plate_model(config) as membership:
        mesh = snapshot(membership)
        retained = gmsh.view.add('keep')
        before_visibility = gmsh.model.mesh.getVisibility(mesh.element_ids)
        original = gmsh.view.getModelData
        def missing_id(*args, **kwargs):
            kind, ids, values, time, components = original(*args, **kwargs)
            return kind, ids[:-1], values[:-1], time, components
        monkeypatch.setattr(gmsh.view, 'getModelData', missing_id)
        with pytest.raises(MeshBlocked, match='element ID'):
            read_icn(mesh)
        assert set(gmsh.view.getTags()) == {retained}
        assert np.array_equal(gmsh.model.mesh.getVisibility(mesh.element_ids), before_visibility)
