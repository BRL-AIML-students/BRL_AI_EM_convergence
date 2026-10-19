from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import gmsh
import numpy as np
import pytest

from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model, publish, run
from brl_mesh.errors import ConfigurationError, MeshBlocked
from brl_mesh.inspection import inspect_mesh
from brl_mesh.model import snapshot


def write_cad(path, kind='plate'):
    # OCC mixed-format writer state is not part of the importer under test.
    subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c',
        'from tests.test_cad import _write_cad; from pathlib import Path; import sys; '
        '_write_cad(Path(sys.argv[1]), sys.argv[2])', str(path), kind],
        capture_output=True, check=True, timeout=20)
    return path


def _write_cad(path, kind='plate'):
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        if kind == 'plate':
            gmsh.model.occ.addRectangle(100, 200, 300, 1000, 500)
        elif kind == 'box':
            gmsh.model.occ.addBox(100, 200, 300, 1000, 1000, 1000)
        elif kind == 'mixed':
            gmsh.model.occ.addBox(100, 200, 300, 1000, 1000, 1000)
            gmsh.model.occ.addRectangle(2100, 200, 300, 1000, 500)
            a = gmsh.model.occ.addPoint(4100, 200, 300)
            b = gmsh.model.occ.addPoint(5100, 200, 300)
            gmsh.model.occ.addLine(a, b)
            gmsh.model.occ.addPoint(6100, 200, 300)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def cad_config(path, **kwargs):
    geometry = {'kind': 'cad', 'path': path.name} | kwargs.pop('geometry', {})
    return Configuration.from_dict({'schema_version': 1, 'geometry': geometry,
        'length_unit': 'mm', 'output_unit': 'm', 'mesh': {'target_size': .25},
        'output_dir': 'output'} | kwargs, path.parent)


@pytest.mark.parametrize('extension', ['step', 'stp', 'iges', 'igs'])
@pytest.mark.parametrize('unit,scale', [('m', .001), ('cm', .1), ('mm', 1), ('um', 1000)])
def test_embedded_cad_units_are_converted_once(tmp_path, extension, unit, scale):
    path = write_cad(tmp_path / ('plate.' + extension))
    # length_unit applies to BREP/primitives; it must not override embedded units.
    config = cad_config(path, length_unit='cm', output_unit=unit,
                        mesh={'target_size': 250 * scale}, geometry={'sheet_normal': 1})
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        assert mesh.coordinates.min(axis=0) == pytest.approx(np.array([100, 200, 300])*scale)
        assert np.ptp(mesh.coordinates, axis=0) == pytest.approx(np.array([1000, 500, 0])*scale)
        inspect_mesh(mesh, scene.contract).require_pass()


def test_mixed_brep_scales_solid_sheet_curve_point_roots_once(tmp_path):
    path = write_cad(tmp_path / 'mixed.brep', 'mixed')
    config = cad_config(path, geometry={'sheet_normal': 1})
    with mesh_model(config) as scene:
        assert len(scene.membership) == 7
        assert scene.contract.boundary.expected_components == 2
        assert len(scene.contract.sheet_signs) == 1
        assert gmsh.model.occ.getMass(3, 1) == pytest.approx(1)
        sheet = next(iter(scene.contract.sheet_signs))
        assert gmsh.model.occ.getCenterOfMass(2, sheet) == pytest.approx([2.6, .45, .3])
        curves = [(tag, gmsh.model.occ.getCenterOfMass(1, tag)) for _, tag in gmsh.model.getEntities(1)]
        assert any(np.allclose(center, [4.6, .2, .3]) and gmsh.model.occ.getMass(1, tag) == pytest.approx(1)
                   for tag, center in curves)
        points = [gmsh.model.getValue(0, tag, []) for _, tag in gmsh.model.getEntities(0)]
        assert any(np.allclose(point, [6.1, .2, .3]) for point in points)
        mesh = snapshot(scene.membership)
        inspect_mesh(mesh, scene.contract).require_pass()
        result = publish(mesh, config, scene)
        assert result.nas_path.is_file()
        assert set(mesh.pids) == set(scene.membership.values())
        # Independent lower-dimensional CAD entities stay in Gmsh, not surface NAS.
        assert max(mesh.coordinates[:, 0]) == pytest.approx(3.1)


def test_imported_closed_solid_repeats_ids_coordinates_connectivity_and_pids(tmp_path):
    path = write_cad(tmp_path / 'box.step', 'box')
    config = cad_config(path)
    first, second = run(config), run(config)
    assert first.nas_path.read_bytes() == second.nas_path.read_bytes()
    assert sorted(p.name for p in first.nas_path.parent.iterdir()) == ['mesh.nas']


@pytest.mark.parametrize('sign', [-1, 1])
def test_open_sheet_has_explicit_applied_direction_and_flips_are_blocked(tmp_path, sign):
    path = write_cad(tmp_path / 'sheet.brep')
    with pytest.raises(ConfigurationError, match='기준 방향'):
        with mesh_model(cad_config(path)):
            pass
    config = cad_config(path, geometry={'sheet_normal': sign})
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        xyz = mesh.triangles()
        assert np.all(sign * np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0])[:, 2] > 0)
        inspect_mesh(mesh, scene.contract).require_pass()
        gmsh.model.mesh.reverse([(2, next(iter(scene.membership)))])
        with pytest.raises(MeshBlocked, match='inward_normal'):
            publish(snapshot(scene.membership), config, scene)
    assert not config.output_dir.exists()


@pytest.mark.parametrize('change', ['file', 'cad', 'physical', 'settings', 'missing_surface'])
def test_generation_reference_cannot_be_silently_replaced(tmp_path, change):
    path = write_cad(tmp_path / 'box.brep', 'box')
    config = cad_config(path)
    with mesh_model(config) as scene:
        mesh = snapshot(scene.membership)
        current = config
        if change == 'file':
            path.write_bytes(path.read_bytes() + b'\n')
        elif change == 'cad':
            gmsh.model.occ.translate([(3, 1)], .1, 0, 0)
            gmsh.model.occ.synchronize()
        elif change == 'physical':
            gmsh.model.removePhysicalGroups()
        elif change == 'settings':
            current = replace(config, target_size=.3)
        else:
            gmsh.model.mesh.clear([(2, next(iter(scene.membership)))])
        with pytest.raises(MeshBlocked):
            publish(mesh, current, scene)
    assert not config.output_dir.exists()


@pytest.mark.parametrize('changes', [
    {'sheet_normal': True}, {'sheet_normal': 0}, {'sheet_normals': []},
    {'sheet_normals': {'01': 1}}, {'sheet_normals': {'1': False}},
    {'separated_surfaces': [[1, 1]]}, {'separated_surfaces': [[1, True]]},
    {'separated_surfaces': [[1, 2], [2, 1]]}, {'protected_gap': 1},
    {'path': 'missing.brep'}, {'path': True},
])
def test_cad_nested_schema_rejects_invalid_inputs(tmp_path, changes):
    path = write_cad(tmp_path / 'plate.brep')
    with pytest.raises(ConfigurationError):
        cad_config(path, geometry=changes)


@pytest.mark.parametrize('extension', ['step', 'iges', 'brep'])
def test_fresh_cli_import_has_only_state_json_and_correct_units(tmp_path, extension):
    import json
    from pyNastran.bdf.bdf import BDF
    path = write_cad(tmp_path / ('plate.' + extension))
    config = cad_config(path, geometry={'sheet_normal': 1})
    source = tmp_path / 'input.json'
    source.write_text(json.dumps(config.to_dict()), encoding='utf-8')
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-m', 'brl_mesh', str(source)],
                            capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout)
    assert set(state) == {'status', 'nas_path'} and state['status'] == 'ok'
    assert result.stderr == ''
    reader = BDF(debug=False)
    reader.read_bdf(state['nas_path'], xref=False, punch=True)
    xyz = np.array([node.xyz for node in reader.nodes.values()])
    assert xyz.min(axis=0) == pytest.approx([.1, .2, .3])
    assert np.ptp(xyz, axis=0) == pytest.approx([1, .5, 0])


@pytest.mark.parametrize('unit,scale', [('cm', .1), ('mm', 1), ('um', 1000)])
def test_fresh_iges_process_applies_requested_unit_without_prior_cad_import(tmp_path, unit, scale):
    path = write_cad(tmp_path / 'first.iges')
    code = """from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model
from brl_mesh.model import snapshot
import json,sys,numpy as np
c=Configuration.from_dict(json.loads(sys.argv[1]))
with mesh_model(c) as scene:
 m=snapshot(scene.membership)
 np.testing.assert_allclose(np.ptp(m.coordinates,axis=0),[float(sys.argv[2]),float(sys.argv[2])/2,0],atol=1e-8)
"""
    config = cad_config(path, output_unit=unit, mesh={'target_size': 250 * scale}, geometry={'sheet_normal': 1})
    import json
    subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', code, json.dumps(config.to_dict()), str(1000*scale)],
                   capture_output=True, check=True, timeout=20)


def test_brep_unit_conversion_preserves_surface_tags_and_per_face_direction(tmp_path):
    path = write_cad(tmp_path / 'mixed.brep', 'mixed')
    memberships=[]
    for unit, size in [('mm', 250), ('m', .25)]:
        config = cad_config(path, output_unit=unit, mesh={'target_size':size}, geometry={'sheet_normals':{'7':-1}})
        with mesh_model(config) as scene:
            memberships.append(scene.membership)
            assert scene.contract.sheet_signs == {7:-1}
            inspect_mesh(snapshot(scene.membership), scene.contract).require_pass()
    assert memberships == [{tag:tag for tag in range(1,8)}]*2


def test_unicode_path_and_mixed_case_extension_use_explicit_cad_format(tmp_path):
    path = write_cad(tmp_path / 'source.brep')
    folder = tmp_path / '입력 CAD'
    folder.mkdir()
    target = folder / '혼합 판.BrEp'
    target.write_bytes(path.read_bytes())
    config = cad_config(target, geometry={'sheet_normal': 1})
    assert run(config).nas_path.is_file()
