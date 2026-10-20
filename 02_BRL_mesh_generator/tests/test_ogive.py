from dataclasses import replace
import math

import gmsh
import numpy as np
import pytest

from brl_mesh.config import Configuration
from brl_mesh.cad import build_geometry
from brl_mesh.curvature import project
from brl_mesh.engine import mesh_model, run
from brl_mesh.errors import ConfigurationError
from brl_mesh.inspection import inspect_mesh
from brl_mesh.model import snapshot
from brl_mesh import native_ui as ui
from tests.sizing_support import write_case
from tests.curvature_support import write_curved


def ogive(tmp_path, t=0, **geometry):
    return Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'ogive', 'diameter': 2, 'length': 3, 'thickness': t} | geometry,
        'mesh': {'target_size': .7 if t == 0 else .15, 'curvature': {'absolute_tolerance': .02}},
        'output_dir': str(tmp_path/'outputs')})


@pytest.mark.parametrize('t', [0, .2])
def test_native_ogive_actual_geometry_and_nas(tmp_path, t):
    config = ogive(tmp_path, t)
    assert Configuration.from_dict(config.to_dict()) == config
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        inspection = inspect_mesh(mesh, scene.contract)
        inspection.require_pass()
        assert inspection.deviation_ratio_max <= 1
        assert len(gmsh.model.getEntities(3)) == (1 if t else 0)
        assert len(scene.cad.sheet_signs) == (0 if t else 2)
        assert scene.cad.components == 1
        # Construction center/axis helper entities must not pollute model bounds.
        assert gmsh.model.getBoundingBox(-1, -1) == pytest.approx((-1, -1, 0, 1, 1, 3), abs=2e-7)
        if t == 0:
            assert np.hypot(np.linalg.norm(mesh.coordinates[:, :2], axis=1)+4,
                            mesh.coordinates[:, 2]) == pytest.approx(5)
            expected = 2*math.pi*(-4*5*math.asin(3/5)+5*3)
            assert sum(gmsh.model.occ.getMass(2, tag) for _, tag in gmsh.model.getEntities(2)) == pytest.approx(expected)
            xyz = mesh.triangles().mean(axis=1)
            radial = np.linalg.norm(xyz[:, :2], axis=1)
            normal = np.cross(mesh.triangles()[:, 1]-mesh.triangles()[:, 0],
                              mesh.triangles()[:, 2]-mesh.triangles()[:, 0])
            outward = np.column_stack(((radial+4)*xyz[:, 0]/radial,
                                       (radial+4)*xyz[:, 1]/radial, xyz[:, 2]))
            assert np.all(np.einsum('ij,ij->i', normal, outward) > 0)
        else:
            # Independent cross-section quadrature of outer minus offset inner.
            abscissa, weights = np.polynomial.legendre.leggauss(128)
            def volume(radius, height):
                z = (abscissa+1)*height/2
                r = np.sqrt(radius**2-z**2)-4
                return math.pi*height/2*np.dot(weights, r*r)
            expected = volume(5, 3)-volume(4.8, math.sqrt(.8*8.8))
            tag = gmsh.model.getEntities(3)[0][1]
            assert gmsh.model.occ.getMass(3, tag) == pytest.approx(expected, rel=1e-9)
    result = run(config)
    assert {p.name for p in result.nas_path.parent.iterdir()} == {'mesh.nas'}


@pytest.mark.parametrize('unit,scale', [('mm', 1), ('m', .001)])
@pytest.mark.parametrize('t', [0, .2])
def test_native_ogive_units_and_origin(tmp_path, unit, scale, t):
    config = replace(ogive(tmp_path, t, origin=[10, 20, 30]), output_unit=unit)
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        reference = build_geometry(config)
        assert gmsh.model.getBoundingBox(-1, -1) == pytest.approx(np.array([9, 19, 30, 11, 21, 33])*scale, abs=2e-7)
        assert reference.components == 1
    finally:
        gmsh.finalize()


@pytest.mark.parametrize('change', [{'diameter': 0}, {'diameter': True}, {'length': .9}, {'length': 1}, {'thickness': -1},
    {'thickness': 1}, {'thickness': float('nan')}, {'origin': [1, 2]}, {'D': 2},
    {'length': 1e200}, {'diameter': 1e-200}, {'origin': [1e18, 0, 0]}, {'thickness': 1e-16}])
def test_ogive_rejects_undefined_or_unrepresentable_geometry(tmp_path, change):
    with pytest.raises(ConfigurationError):
        ogive(tmp_path, **change)


def test_positive_thickness_underflow_cannot_change_solid_to_sheet(tmp_path):
    value = ogive(tmp_path).to_dict()
    value['geometry']['thickness'] = 5e-324
    value.update(length_unit='um', output_unit='m')
    with pytest.raises(ConfigurationError, match='두께.*소실'):
        Configuration.from_dict(value)


def test_ogive_onelab_roundtrip_native_cad_switch_and_invalidation(tmp_path):
    config = ogive(tmp_path)
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        controller = ui.Controller(config, tmp_path)
        assert ui.read_controls(config, tmp_path) == config
        gmsh.onelab.setString(ui.ACTION, [ui.ACTIONS[2]])
        controller.dispatch()
        assert controller.scene is not None
        gmsh.onelab.setNumber(ui.THICKNESS, [.2])
        controller.invalidate_if_changed()
        assert controller.scene is None
        assert ui.read_controls(config, tmp_path).geometry.thickness == .2
        gmsh.onelab.setString(ui.KIND, ['plate'])
        assert ui.read_controls(config, tmp_path).geometry.length == 100
    finally:
        gmsh.finalize()


def test_trimmed_plane_projection_measures_hole_and_outer_boundary(tmp_path):
    path = write_case(tmp_path/'hole.brep', 'hole')
    config = Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'cad', 'path': str(path), 'sheet_normal': 1}, 'mesh': {'target_size': .5}})
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        reference = build_geometry(config)
        face = next(iter(reference.membership))
        points = np.array([[1.6, 2, 0], [5, 2, 0], [1, 1, 0]])
        projected, _ = project(2, face, points)
        assert np.linalg.norm(projected-points, axis=1) == pytest.approx([.1, 1, 0], abs=1e-9)
    finally:
        gmsh.finalize()


def test_complex_imported_fillet_repeats_coordinates_connectivity_and_pid(tmp_path):
    path = write_curved(tmp_path/'fillet.brep', 'fillet')
    config = Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'cad', 'path': str(path)},
        'mesh': {'target_size': .15, 'curvature': {'absolute_tolerance': .01}},
        'output_dir': str(tmp_path/'outputs')})
    first, second = run(config), run(config)
    assert first.nas_path != second.nas_path
    assert first.nas_path.read_bytes() == second.nas_path.read_bytes()
    # The revised curvature feedback refines the eight failing faces once.
    assert first.triangle_count == 4256
    assert {int(line.split(',')[2]) for line in first.nas_path.read_text().splitlines()
            if line.startswith('CTRIA3,')} == set(range(1, 27))
    assert {p.name for folder in config.output_dir.iterdir() for p in folder.iterdir()} == {'mesh.nas'}
