from copy import deepcopy
import json
from pathlib import Path

import gmsh
import numpy as np
import pytest

from geometry_mesh.config import validate
from geometry_mesh.native_ui import Controller, parameters
from geometry_mesh.pipeline import initialize, _profile, publish_current, run
from geometry_mesh.session import current, prepare, generate, improve


@pytest.fixture
def gmsh_session():
    initialize()
    try:
        yield
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


def cfg(tmp_path):
    return validate({"name":"native","output_dir":str(tmp_path),"geometry":{"kind":"plate","parameters":{"length":10,"width":10}},
                     "mesh":{"local":{"enabled":False},"scale_fraction":.15}})


def test_onelab_generation_export_and_manual_edit_invalidation(gmsh_session,tmp_path):
    configuration=cfg(tmp_path)
    gmsh.onelab.set(json.dumps(parameters(configuration)))
    controller=Controller(configuration)
    assert controller.perform(1)["quality_gate_status"]=="pass"
    report=controller.perform(4)
    assert report["status"]=="complete" and Path(report["output_directory"],'native.nas').exists()
    snapshot,_=current(controller.context,_profile())
    # Move an interior node onto another node; export must inspect the new mesh.
    tri=snapshot["connectivity"][0]
    point=snapshot["coordinates"][np.searchsorted(snapshot["node_ids"],tri[0])]
    gmsh.model.mesh.setNode(int(tri[1]),point.tolist(),[])
    controller.invalidate()
    assert gmsh.onelab.getString('BRL/Result/Status')[0].startswith('changed')
    report=controller.perform(4)
    assert report["status"]=="invalid" and report["artifacts"]["nas"] is None


def test_changed_dimensions_require_rebuild(gmsh_session,tmp_path):
    configuration=cfg(tmp_path)
    gmsh.onelab.set(json.dumps(parameters(configuration)))
    c=Controller(configuration); c.perform(1)
    gmsh.onelab.setNumber('BRL/Geometry/length',[20])
    with pytest.raises(ValueError,match='rebuild'): c.perform(4)
    assert c.perform(1)['quality_gate_status']=='pass'
    assert c.context.geometry['analytic_parameters']['length']==20


def test_loaded_native_model_uses_same_gate(gmsh_session,tmp_path):
    configuration=cfg(tmp_path)
    context=prepare(configuration); generate(context)
    report=publish_current(context)
    path=Path(report['output_directory'])/'diagnostic.msh'
    gmsh.clear(); gmsh.open(str(path))
    gmsh.onelab.set(json.dumps(parameters(configuration)))
    controller=Controller(configuration)
    result=controller.perform(4)
    assert result['status']=='complete'
    assert result['geometry']['source_kind']=='native_current_model'
    assert result['assessment']['scores']['geometry_fidelity']['coverage']=='not_assessed'


def test_improvement_is_bounded_and_rejects_worse_mesh(gmsh_session,tmp_path,monkeypatch):
    configuration=cfg(tmp_path); configuration['quality']['max_aspect_ratio']=1.01
    context=prepare(configuration); generate(context)
    before,_=current(context,_profile())
    calls=[]
    def worsen(method,**kwargs):
        calls.append(method)
        tri=before['connectivity'][0]
        point=before['coordinates'][np.searchsorted(before['node_ids'],tri[0])]
        gmsh.model.mesh.setNode(int(tri[1]),point.tolist(),[])
    monkeypatch.setattr(gmsh.model.mesh,'optimize',worsen)
    after,assessment,history=improve(context,_profile())
    assert len(calls)==3 and all(not x['accepted'] for x in history)
    assert np.array_equal(before['coordinates'],after['coordinates'])
    assert assessment['quality_gate_status']=='fail'


def test_fragment_shared_boundary_and_pid_provenance(tmp_path):
    cad=tmp_path/'two sheets.brep'
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.model.occ.addRectangle(0,0,0,10,10)
        gmsh.model.occ.addRectangle(10,0,0,10,10)
        gmsh.model.occ.synchronize(); gmsh.write(str(cad))
    finally: gmsh.finalize()
    result=run({'name':'joined','output_dir':str(tmp_path),'geometry':{'kind':'cad','path':str(cad)},
                'mesh':{'local':{'enabled':False},'improvement':{'fragment_surface_tags':[1,2]}},'export':{'pid_start':11}})
    assert result['status']=='complete'
    assert {g['pid'] for g in result['surface_groups']}=={11,12}
    assert result['geometry']['fragment']['input_surface_tags']==[1,2]
    components=result['assessment']['scores']['topology_and_normals']['metrics']['conformity']['components']
    assert len(components)==1


def test_conflicting_cap_is_not_silently_ignored(tmp_path):
    with pytest.raises(ValueError,match='conflicts'):
        run({'output_dir':str(tmp_path),'mesh':{'minimum_size_fraction':.5,'user_size_cap':.001}})


def test_real_surface_relocation_improves_sliver(gmsh_session,tmp_path):
    configuration=cfg(tmp_path); configuration['mesh']['scale_fraction']=.1
    context=prepare(configuration); generate(context)
    mesh,_=current(context,_profile())
    node=int(gmsh.model.mesh.getNodes(2,1,includeBoundary=False)[0][0])
    incident=mesh['connectivity'][np.any(mesh['connectivity']==node,axis=1)]
    neighbors=np.unique(incident); neighbors=neighbors[neighbors!=node]
    point=mesh['coordinates'][np.searchsorted(mesh['node_ids'],node)]
    points=mesh['coordinates'][np.searchsorted(mesh['node_ids'],neighbors)]
    nearest=points[np.argmin(np.linalg.norm(points-point,axis=1))]
    gmsh.model.mesh.setNode(node,(.05*point+.95*nearest).tolist(),[])
    _,before=current(context,_profile())
    _,after,history=improve(context,_profile())
    a=before['scores']['element_shape']['metrics']; b=after['scores']['element_shape']['metrics']
    assert a['violating_element_count']>0 and a['aspect_ratio_max']>10
    assert b['violating_element_count']==0 and after['quality_gate_status']=='pass'
    assert any(item['accepted'] for item in history)


def test_raw_size_regression_cannot_hide_in_saturated_score(gmsh_session,tmp_path):
    from geometry_mesh.session import _nonworse
    context=prepare(cfg(tmp_path)); generate(context)
    _,before=current(context,_profile()); after=deepcopy(before)
    assert before['scores']['size_compliance']['score']==100
    after['scores']['size_compliance']['metrics']['edge_max']*=1.01
    assert not _nonworse(before,after)


def test_cad_edit_with_same_tags_invalidates_reference(gmsh_session,tmp_path):
    configuration=cfg(tmp_path)
    gmsh.onelab.set(json.dumps(parameters(configuration)))
    controller=Controller(configuration); controller.perform(1)
    gmsh.model.occ.translate([(2,1)],0,0,1)
    gmsh.model.occ.synchronize(); gmsh.model.mesh.generate(2)
    controller.invalidate()
    assert gmsh.onelab.getString('BRL/Result/Status')[0].startswith('changed')
    with pytest.raises(ValueError,match='CAD or physical'): current(controller.context,_profile())
    result=controller.perform(4)
    assert result['status']=='complete'
    assert result['geometry']['source_kind']=='native_current_model'
    assert result['assessment']['scores']['geometry_fidelity']['coverage']=='not_assessed'
