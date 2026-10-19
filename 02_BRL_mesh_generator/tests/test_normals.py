from dataclasses import replace

import gmsh
import numpy as np
import pytest

from brl_mesh.engine import mesh_model
from brl_mesh.model import snapshot
from brl_mesh.normals import inspect_normals
from tests.support import cad_mesh


@pytest.mark.parametrize('kind', ['box', 'sphere'])
def test_solid_normals_and_reversed_winding(kind):
    with cad_mesh(kind) as membership:
        mesh = snapshot(membership)
        assert not inspect_normals(mesh, {}).issues
        flipped = replace(mesh, connectivity=mesh.connectivity[:, ::-1].copy())
        assert 'inward_normal' in {x.code for x in inspect_normals(flipped, {}).issues}


def test_solid_classification_corrects_reversed_cad_parameter_normals(monkeypatch):
    with cad_mesh('box') as membership:
        mesh = snapshot(membership)
        original = gmsh.model.getNormal
        monkeypatch.setattr(gmsh.model, 'getNormal', lambda *args: -original(*args))
        assert not inspect_normals(mesh, {}).issues


def test_open_sheet_requires_explicit_reference_and_checks_direction(config):
    with mesh_model(config) as scene:
        membership = scene.membership
        mesh = snapshot(membership)
        missing = inspect_normals(mesh, {})
        assert any(x.status == 'incomplete' for x in missing.issues)
        assert not inspect_normals(mesh, {surface: 1 for surface in membership}).issues
        assert 'inward_normal' in {x.code for x in inspect_normals(mesh, {surface: -1 for surface in membership}).issues}


def test_projection_failure_is_not_success(config, monkeypatch):
    with mesh_model(config) as scene:
        membership = scene.membership
        def unavailable(*_):
            raise RuntimeError('projection unavailable')
        monkeypatch.setattr(gmsh.model, 'getClosestPoint', unavailable)
        result = inspect_normals(snapshot(membership), {s: 1 for s in membership})
        assert any(x.status == 'incomplete' for x in result.issues)


def test_nodes_off_cad_surface_are_blocked(config):
    with mesh_model(config) as scene:
        membership = scene.membership
        mesh = snapshot(membership)
        xyz = mesh.coordinates.copy()
        xyz[0, 2] += .01
        result = inspect_normals(replace(mesh, coordinates=xyz), {s: 1 for s in membership})
        assert 'off_cad_nodes' in {x.code for x in result.issues}


def test_multiple_solid_owners_are_incomplete():
    with cad_mesh('shared_face') as membership:
        result = inspect_normals(snapshot(membership), {})
        assert any(x.status == 'incomplete' for x in result.issues)
