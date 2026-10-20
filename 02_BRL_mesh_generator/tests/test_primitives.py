"""Independent geometry, shared-edge orientation, UI and publication contracts."""
from dataclasses import replace
import json
import math

import gmsh
import numpy as np
import pytest

from brl_mesh import native_ui as ui
from brl_mesh.cad import build_geometry
from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model, run
from brl_mesh.errors import ConfigurationError, MeshBlocked
from brl_mesh.inspection import inspect_mesh
from brl_mesh.model import snapshot


SHAPES = {
    'sphere': {'radius': 1},
    'cube': {'side': 2},
    'cylinder': {'radius': 1, 'height': 2},
    'dihedral': {'length': 2, 'width1': 2, 'width2': 1.5, 'angle_deg': 90},
}


def configuration(tmp_path, kind, **changes):
    return Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': kind, **SHAPES[kind], **changes},
        'mesh': {'target_size': .4}, 'output_dir': str(tmp_path/'output')})


@pytest.mark.parametrize('kind', SHAPES)
@pytest.mark.parametrize('unit,scale', [('mm', 1), ('m', .001)])
def test_primitive_geometry_units_origin_and_exact_measures(tmp_path, kind, unit, scale):
    config = replace(configuration(tmp_path, kind, origin=[10, 20, 30]), output_unit=unit)
    assert Configuration.from_dict(config.to_dict()) == config
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        ref = build_geometry(config)
        bounds = {'sphere': [9, 19, 29, 11, 21, 31], 'cube': [10, 20, 30, 12, 22, 32],
                  'cylinder': [9, 19, 30, 11, 21, 32], 'dihedral': [10, 20, 30, 12, 21.5, 32]}
        assert gmsh.model.getBoundingBox(-1, -1) == pytest.approx(np.array(bounds[kind])*scale, abs=2e-7)
        area = {'sphere': 4*math.pi, 'cube': 24, 'cylinder': 6*math.pi, 'dihedral': 7}[kind]
        assert sum(gmsh.model.occ.getMass(2, tag) for _, tag in gmsh.model.getEntities(2)) == pytest.approx(area*scale**2)
        volumes = gmsh.model.getEntities(3)
        assert len(volumes) == (0 if kind == 'dihedral' else 1)
        if volumes:
            volume = {'sphere': 4*math.pi/3, 'cube': 8, 'cylinder': 2*math.pi}[kind]
            assert gmsh.model.occ.getMass(3, volumes[0][1]) == pytest.approx(volume*scale**3)
        assert ref.components == 1
        assert len(ref.sheet_signs) == (2 if kind == 'dihedral' else 0)
    finally:
        gmsh.finalize()


@pytest.mark.parametrize('angle', [45, 90, 135])
def test_dihedral_shared_hinge_opening_and_winding(tmp_path, angle):
    config = configuration(tmp_path, 'dihedral', angle_deg=angle)
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        inspect_mesh(mesh, scene.contract).require_pass()
        faces = sorted(scene.membership)
        edges = [set(abs(tag) for _, tag in gmsh.model.getBoundary([(2, face)], oriented=False)) for face in faces]
        hinge, = edges[0] & edges[1]
        ids, coords, _ = gmsh.model.mesh.getNodes(1, hinge, includeBoundary=True)
        coords = np.asarray(coords).reshape(-1, 3)
        assert np.max(np.abs(coords[:, :2])) < 1e-12
        assert np.ptp(coords[:, 2]) == pytest.approx(2)
        for face in faces:
            conn = mesh.connectivity[mesh.surface_tags == face]
            assert set(map(int, ids)) <= set(map(int, conn.ravel()))
        rad = math.radians(angle)
        for face, normal in zip(faces, [(0, 1, 0), (math.sin(rad), -math.cos(rad), 0)]):
            xyz = mesh.triangles()[mesh.surface_tags == face]
            cross = np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0])
            assert np.all(cross @ normal > 0)
        far = np.array([1.5*math.cos(rad), 1.5*math.sin(rad), 0])
        assert np.min(np.linalg.norm(mesh.coordinates-far, axis=1)) < 1e-10


@pytest.mark.parametrize('kind', SHAPES)
def test_primitive_nas_repeatability_and_native_ui_roundtrip(tmp_path, kind):
    config = configuration(tmp_path, kind)
    first, second = run(config), run(config)
    assert first.nas_path.read_bytes() == second.nas_path.read_bytes()
    assert {p.name for p in first.nas_path.parent.iterdir()} == {'mesh.nas'}
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        controller = ui.Controller(config, tmp_path)
        assert ui.read_controls(config, tmp_path) == config
        assert gmsh.onelab.getString(ui.KIND) == [kind]
        for shape, (_, _, controls) in ui.NATIVE_SHAPES.items():
            for control in controls.values():
                assert json.loads(gmsh.onelab.get(control))['visible'] == (shape == kind)
        assert not json.loads(gmsh.onelab.get(ui.CAD_PATH))['visible']
        gmsh.onelab.setString(ui.ACTION, [ui.ACTIONS[1]])
        controller.dispatch()
        assert gmsh.onelab.getString(ui.STATUS) == ['NAS published']
        from pathlib import Path
        assert Path(gmsh.onelab.getString(ui.NAS_PATH)[0]).read_bytes() == first.nas_path.read_bytes()
        dimension = next(iter(ui.NATIVE_SHAPES[kind][2].values()))
        gmsh.onelab.setNumber(dimension, [3])
        controller.invalidate_if_changed()
        assert controller.scene is None
        gmsh.onelab.setString(ui.ACTION, [ui.ACTIONS[4]])
        controller.dispatch()
        assert gmsh.onelab.getString(ui.STATUS)[0].startswith('Blocked:')
    finally:
        gmsh.finalize()


@pytest.mark.parametrize('kind,key,value', [
    ('sphere', 'radius', 0), ('sphere', 'radius', True), ('sphere', 'radius', float('nan')),
    ('cube', 'side', -1), ('cylinder', 'height', 0), ('cylinder', 'radius', float('inf')),
    ('dihedral', 'width1', 0), ('dihedral', 'width2', -1), ('dihedral', 'length', True),
    ('dihedral', 'angle_deg', 0), ('dihedral', 'angle_deg', 180), ('dihedral', 'angle_deg', 181),
    ('dihedral', 'angle_deg', True), ('sphere', 'diameter', 2), ('cube', 'width', 3),
    ('cylinder', 'axis', [1, 0, 0]), ('dihedral', 'thickness', .1),
])
def test_primitive_strict_invalid_parameters(tmp_path, kind, key, value):
    with pytest.raises(ConfigurationError):
        configuration(tmp_path, kind, **{key: value})


@pytest.mark.parametrize('kind', SHAPES)
def test_primitive_unrepresentable_origin_and_unit_underflow(tmp_path, kind):
    with pytest.raises(ConfigurationError):
        configuration(tmp_path, kind, origin=[1e18, 0, 0])
    value = configuration(tmp_path, kind).to_dict()
    dimension = next(iter(SHAPES[kind]))
    value['geometry'][dimension] = 5e-324
    value.update(length_unit='um', output_unit='m')
    with pytest.raises(ConfigurationError):
        Configuration.from_dict(value)
