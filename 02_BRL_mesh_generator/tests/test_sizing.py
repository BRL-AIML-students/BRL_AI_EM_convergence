from dataclasses import replace
import math

import gmsh
import numpy as np
import pytest

from brl_mesh.config import Configuration
from brl_mesh.engine import mesh_model, publish, run
from brl_mesh.errors import MeshBlocked, ConfigurationError
from brl_mesh.inspection import inspect_mesh
from brl_mesh.model import snapshot
from tests.sizing_support import write_case


def plate(tmp_path, mesh, length=10, width=10):
    return Configuration.from_dict({'schema_version':1,'geometry':{'kind':'plate','length':length,'width':width},
        'mesh':mesh,'output_dir':str(tmp_path/'output')})


def cad(tmp_path, kind, mesh, **kwargs):
    path=write_case(tmp_path/(kind+'.brep'),kind)
    return Configuration.from_dict({'schema_version':1,
        'geometry':{'kind':'cad','path':str(path),'sheet_normal':1},'mesh':mesh,
        'output_dir':str(tmp_path/'output')} | kwargs)


def lengths_by_surface(mesh):
    xyz=mesh.triangles()
    lengths=np.linalg.norm(xyz[:,[1,2,0]]-xyz,axis=2)
    return {int(s):float(np.median(lengths[mesh.surface_tags==s])) for s in np.unique(mesh.surface_tags)}


def test_global_wave_cap_and_fallback_conditions_are_distinct(tmp_path):
    base=plate(tmp_path,{'target_size':100,'wave':{'frequency_hz':1e9}},10,10)
    with mesh_model(base) as scene:
        assert scene.sizing.global_size==pytest.approx(29.9792458)
        assert dict(scene.sizing.sources)=={'user':100,'wave':pytest.approx(29.9792458)}
    no_cap=replace(base,target_size=None)
    with mesh_model(no_cap) as scene:
        assert scene.sizing.sources==(('wave',pytest.approx(29.9792458)),)
    fallback=plate(tmp_path,{'fallback_fraction':.2},10,10)
    with mesh_model(fallback) as scene:
        assert scene.sizing.sources[0][0]=='fallback'
        assert scene.sizing.global_size==pytest.approx(math.sqrt(200)*.2,rel=1e-6)


def test_wave_material_units_and_user_cap_are_applied(tmp_path):
    config=plate(tmp_path,{'target_size':.01,'wave':{'frequency_hz':1e9,'relative_permittivity':4}},100,100)
    config=replace(config,output_unit='m')
    with mesh_model(config) as scene:
        assert dict(scene.sizing.sources)['wave']==pytest.approx(.0149896229)
        assert scene.sizing.global_size==.01
        assert scene.contract.target_size==.01


def test_long_thin_face_uses_actual_width_not_area_or_bbox_axis(tmp_path):
    config=cad(tmp_path,'rotated',{'target_size':1,'local':{'widths':{'enabled':True}}})
    with mesh_model(config) as scene:
        feature=scene.sizing.features[0]
        assert feature.feature.measured==pytest.approx(.6)
        assert feature.feature.size==pytest.approx(.2)
        mesh=snapshot(scene.membership)
        inspect_mesh(mesh,scene.contract).require_pass()
        assert .15<lengths_by_surface(mesh)[1]<.25


def test_feature_independence_changes_real_elements_without_global_min_leak(tmp_path):
    config=cad(tmp_path,'widths',{'target_size':1,'local':{'widths':{'enabled':True}}})
    with mesh_model(config) as scene:
        features=scene.sizing.features
        assert [item.feature.size for item in features]==pytest.approx([.2,.4])
        assert gmsh.option.getNumber('Mesh.MeshSizeMin')==pytest.approx(.2)
        assert gmsh.option.getNumber('Mesh.MeshSizeMax')==1
        mesh=snapshot(scene.membership)
        medians=lengths_by_surface(mesh)
        assert .15<medians[1]<.25 and .3<medians[2]<.5
        assert medians[2]>1.6*medians[1]
        inspect_mesh(mesh,scene.contract).require_pass()
        assert publish(mesh,config,scene).nas_path.is_file()


def test_gap_minimum_distance_builds_actual_box_fields_for_each_pair(tmp_path):
    config=cad(tmp_path,'gaps',{'target_size':1,'local':{'gaps':{'enabled':True}}})
    with mesh_model(config) as scene:
        gaps=scene.sizing.features
        assert [item.feature.measured for item in gaps]==pytest.approx([.6,1.2])
        assert [item.feature.size for item in gaps]==pytest.approx([.2,.4])
        boxes=[binding for binding in scene.sizing.fields if binding.kind=='Box']
        assert len(boxes)==2
        assert [gmsh.model.mesh.field.getNumber(b.tag,'VIn') for b in boxes]==pytest.approx([.2,.4])
        assert scene.sizing.fields[-1].kind=='Min'
        mesh=snapshot(scene.membership)
        medians=lengths_by_surface(mesh)
        assert medians[1]<.25 and medians[2]<.25
        assert medians[3]>.3 and medians[4]>.3
        assert scene.contract.boundary.expected_components==4
        assert np.unique(mesh.coordinates[:,2])==pytest.approx([0,.6,1.2])
        inspect_mesh(mesh,scene.contract).require_pass()
        publish(mesh,config,scene)


def test_shared_boundary_is_not_gap_and_declared_shared_pair_is_rejected(tmp_path):
    config=cad(tmp_path,'adjacent',{'target_size':.5,'local':{'gaps':{'enabled':True}}})
    with mesh_model(config) as scene:
        assert not scene.sizing.features
        assert scene.contract.boundary.expected_components==1
    value=config.to_dict(); value['mesh']['local']['gaps']['pairs']=[[1,2]]
    with pytest.raises(ConfigurationError,match='공유 연결'):
        with mesh_model(Configuration.from_dict(value)):pass


def test_bbox_overlap_is_only_candidate_not_actual_gap(tmp_path):
    config=cad(tmp_path,'false_bbox',{'target_size':.25,'local':{'gaps':{'enabled':True}}})
    with mesh_model(config) as scene:
        assert not scene.sizing.features


def test_disconnected_contact_and_failed_distance_are_incomplete(tmp_path,monkeypatch):
    config=cad(tmp_path,'contact',{'target_size':.5,'local':{'gaps':{'enabled':True}}})
    with pytest.raises(MeshBlocked,match='gap_contact_or_ambiguous'):
        with mesh_model(config):pass
    config=cad(tmp_path,'gaps',{'target_size':1,'local':{'gaps':{'enabled':True}}})
    monkeypatch.setattr(gmsh.model.occ,'getDistance',lambda *args:(-1,0,0,0,0,0,0))
    with pytest.raises(MeshBlocked,match='gap_measurement_incomplete'):
        with mesh_model(config):pass
    assert not config.output_dir.exists()


@pytest.mark.parametrize('kind',['concave','hole','cylinder','disk'])
def test_width_unsupported_geometry_never_becomes_success(tmp_path,kind):
    config=cad(tmp_path,kind,{'target_size':1,'local':{'widths':{'enabled':True}}})
    with pytest.raises(MeshBlocked,match='width_unsupported'):
        with mesh_model(config):pass
    assert not config.output_dir.exists()


def test_short_edges_get_individual_lengths_and_seams_are_excluded(tmp_path):
    config=plate(tmp_path,{'target_size':1,'local':{'short_edges':{'enabled':True}}},.6,4)
    with mesh_model(config) as scene:
        assert len(scene.sizing.features)==2
        assert [f.feature.measured for f in scene.sizing.features]==pytest.approx([.6,.6])
        assert [f.feature.size for f in scene.sizing.features]==pytest.approx([.2,.2])
        inspect_mesh(snapshot(scene.membership),scene.contract).require_pass()
    config=cad(tmp_path,'cylinder',{'target_size':1,'local':{'short_edges':{'enabled':True}}})
    with mesh_model(config) as scene:
        assert not scene.sizing.features  # .2-long CAD seam is not a physical short edge.


def test_manual_box_and_curve_have_real_spatial_effect(tmp_path):
    config=plate(tmp_path,{'target_size':1,'local':{'hold_distance':.3,
        'curves':[{'entity':1,'size':.2}],
        'boxes':[{'bounds':[4,4,-.1,6,6,.1],'size':.3}]}})
    with mesh_model(config) as scene:
        assert {f.feature.kind for f in scene.sizing.features}=={'manual_curve','manual_box'}
        mesh=snapshot(scene.membership);xyz=mesh.triangles();centroids=xyz.mean(axis=1)
        edges=np.linalg.norm(xyz[:,[1,2,0]]-xyz,axis=2).mean(axis=1)
        assert np.median(edges[centroids[:,1]<.25])<.3
        assert np.median(edges[centroids[:,1]>9])>.7
        inside=np.all((centroids[:,:2]>4.2)&(centroids[:,:2]<5.8),axis=1)
        assert np.median(edges[inside])<.4
        inspect_mesh(mesh,scene.contract).require_pass()


def test_hold_and_transition_are_separate_applied_controls(tmp_path):
    config=plate(tmp_path,{'target_size':3,'local':{'hold_distance':.4,'growth_rate':.3,
                     'curves':[{'entity':1,'size':.2}]}})
    with mesh_model(config) as scene:
        item=scene.sizing.features[0]
        assert item.hold==.4 and item.transition==pytest.approx(9.333333333333)
        threshold=next(b for b in scene.sizing.fields if b.kind=='Threshold')
        assert gmsh.model.mesh.field.getNumber(threshold.tag,'DistMin')==.4
        assert gmsh.model.mesh.field.getNumber(threshold.tag,'DistMax')==pytest.approx(9.733333333333)
        assert scene.sizing.nominal_sizes([[5,0,0],[5,.4,0],[5,5.0666666667,0],[5,10,0]])==pytest.approx([.2,.2,1.6,3])


@pytest.mark.parametrize('kind',['width','gap','global'])
def test_minimum_floor_conflicts_block_before_meshing(tmp_path,monkeypatch,kind):
    if kind=='gap':config=cad(tmp_path,'gaps',{'target_size':1,'minimum_size':.3,'local':{'gaps':{'enabled':True}}})
    elif kind=='width':config=plate(tmp_path,{'target_size':1,'minimum_size':.3,'local':{'widths':{'enabled':True}}},10,.6)
    else:config=plate(tmp_path,{'target_size':.2,'minimum_size':.3})
    monkeypatch.setattr(gmsh.model.mesh,'generate',lambda *args:pytest.fail('must block before meshing'))
    with pytest.raises(MeshBlocked,match='minimum_size_conflict'):
        with mesh_model(config):pass
    assert not config.output_dir.exists()


@pytest.mark.parametrize('limit,value,pattern',[('max_sampling',64,'sampling_incomplete'),
    ('max_pair_tests',1,'feature_measurement_incomplete'),('max_features',1,'feature_measurement_incomplete')])
def test_measurement_limits_do_not_silently_relax_requests(tmp_path,limit,value,pattern):
    config=cad(tmp_path,'widths',{'target_size':1,'local':{'widths':{'enabled':True},limit:value}})
    with pytest.raises(MeshBlocked,match=pattern):
        with mesh_model(config):pass


@pytest.mark.parametrize('mutation',['parameter','option','addition','removal',
                                     'distance_list','restriction_list','restriction_embedded'])
def test_native_field_changes_require_regeneration(tmp_path,mutation):
    config=plate(tmp_path,{'target_size':1,'local':{'widths':{'enabled':True}}},10,.6)
    with mesh_model(config) as scene:
        mesh=snapshot(scene.membership)
        tag=next(b.tag for b in scene.sizing.fields if b.kind=='Threshold')
        if mutation=='parameter':gmsh.model.mesh.field.setNumber(tag,'SizeMin',.5)
        elif mutation=='option':gmsh.option.setNumber('Mesh.MeshSizeMin',.5)
        elif mutation=='addition':gmsh.model.mesh.field.add('MathEval')
        elif mutation=='removal':gmsh.model.mesh.field.remove(tag)
        elif mutation=='distance_list':
            tag=next(b.tag for b in scene.sizing.fields if b.kind=='Distance')
            gmsh.model.mesh.field.setNumbers(tag,'SurfacesList',[1])
        else:
            tag=next(b.tag for b in scene.sizing.fields if b.kind=='Restrict')
            if mutation=='restriction_list':gmsh.model.mesh.field.setNumbers(tag,'CurvesList',[1])
            else:gmsh.model.mesh.field.setNumber(tag,'IncludeEmbedded',0)
        with pytest.raises(MeshBlocked,match='size_(field|options)_changed'):
            publish(mesh,config,scene)
    assert not config.output_dir.exists()


def test_missing_curve_projection_blocks_local_audit(tmp_path,monkeypatch):
    config=plate(tmp_path,{'target_size':1,'local':{'curves':[{'entity':1,'size':.2}]}})
    with mesh_model(config) as scene:
        original=gmsh.model.getClosestPoint
        def missing(dim,*args):
            if dim==1:raise RuntimeError('curve projection unavailable')
            return original(dim,*args)
        monkeypatch.setattr(gmsh.model,'getClosestPoint',missing)
        with pytest.raises(MeshBlocked,match='local_size_incomplete'):
            publish(snapshot(scene.membership),config,scene)


def test_sampling_doubling_is_stable_on_actual_curved_boundary(tmp_path):
    config=cad(tmp_path,'disk',{'target_size':2,'local':{'short_edges':{'enabled':True,'divisions':12}}})
    measurements=[]
    for fraction in [.25,.125]:
        value=config.to_dict();value['mesh']['local']['sampling_fraction']=fraction
        with mesh_model(Configuration.from_dict(value)) as scene:
            mesh=snapshot(scene.membership)
            inspect_mesh(mesh,scene.contract).require_pass()
            measurements.append((scene.sizing.features[0].sampling,lengths_by_surface(mesh)[1]))
    assert measurements[1][0]>measurements[0][0]
    assert measurements[1][1]==pytest.approx(measurements[0][1],rel=.1)


def test_curve_parameter_output_does_not_corrupt_continuous_size_audit(tmp_path,monkeypatch):
    config=plate(tmp_path,{'target_size':3,'local':{'hold_distance':.4,
                    'curves':[{'entity':1,'size':.2}]}})
    with mesh_model(config) as scene:
        original=gmsh.model.getClosestPoint
        def undefined_parameters(dim,*args):
            closest,parameters=original(dim,*args)
            if dim==1:parameters=np.full(len(closest)//3,float('nan'))
            return closest,parameters
        monkeypatch.setattr(gmsh.model,'getClosestPoint',undefined_parameters)
        assert scene.sizing.nominal_sizes([[5,0,0],[5,.4,0],[5,5.0666666667,0],[5,10,0]])==pytest.approx([.2,.2,1.6,3])


def test_actual_cli_local_fields_and_floor_conflict_use_minimal_status(tmp_path):
    import json,subprocess,sys
    config=plate(tmp_path,{'target_size':1,'local':{'widths':{'enabled':True}}},10,.6)
    source=tmp_path/'local.json';source.write_text(json.dumps(config.to_dict()),encoding='utf-8')
    completed=subprocess.run([sys.executable,'-B','-X','utf8','-m','brl_mesh',str(source)],
        capture_output=True,text=True,encoding='utf-8',timeout=25)
    assert completed.returncode==0,completed.stderr
    state=json.loads(completed.stdout)
    from pathlib import Path
    assert sorted(p.name for p in Path(state['nas_path']).parent.iterdir())==['mesh.nas']
    old=Path(state['nas_path']).read_bytes()
    value=config.to_dict();value['mesh']['minimum_size']=.3
    source.write_text(json.dumps(value),encoding='utf-8')
    blocked=subprocess.run([sys.executable,'-B','-X','utf8','-m','brl_mesh',str(source)],
        capture_output=True,text=True,encoding='utf-8',timeout=25)
    assert blocked.returncode==2 and not blocked.stdout
    assert 'minimum_size_conflict' in json.loads(blocked.stderr)['reason']
    assert Path(state['nas_path']).read_bytes()==old
    assert len(list(config.output_dir.rglob('mesh.nas')))==1


def test_connected_cad_surfaces_do_not_consume_gap_pair_budget(tmp_path):
    config=cad(tmp_path,'cylinder',{'target_size':1,'local':{'gaps':{'enabled':True},'max_pair_tests':1}})
    with mesh_model(config) as scene:
        assert not scene.sizing.features


def test_local_fields_repeat_coordinates_connectivity_ids_and_pids(tmp_path):
    config=cad(tmp_path,'gaps',{'target_size':1,'local':{'gaps':{'enabled':True}}})
    first,second=run(config),run(config)
    assert first.nas_path!=second.nas_path
    assert first.nas_path.read_bytes()==second.nas_path.read_bytes()


def test_local_real_relocate_keeps_field_and_reduces_local_edge_ratio(tmp_path):
    from brl_mesh.improvement import improve
    from tests.support import distort_interior
    config=plate(tmp_path,{'target_size':.25,'local':{'hold_distance':0,
        'boxes':[{'bounds':[.3,.3,-.01,.7,.7,.01],'size':.125}]}},1,1)
    with mesh_model(config) as scene:
        distort_interior(scene.membership)
        before=snapshot(scene.membership)
        old=inspect_mesh(before,scene.contract)
        assert old.shape.violating_count==2
        result=improve(scene.membership,scene.contract,config.improvement)
        assert result.attempts[0].accepted
        result.inspection.require_pass()
        assert result.mesh.same_structure(before)
        assert result.inspection.local_edge_max_to_target<old.local_edge_max_to_target
        scene.sizing.require_current()


def test_automatic_feature_lengths_use_output_units_once(tmp_path):
    config=cad(tmp_path,'widths',{'target_size':1,'local':{'widths':{'enabled':True}}})
    config=replace(config,output_unit='m',target_size=.001)
    with mesh_model(config) as scene:
        assert [f.feature.size for f in scene.sizing.features]==pytest.approx([.0002,.0004])
        assert scene.sizing.minimum_size==pytest.approx(.0002)
        mesh=snapshot(scene.membership)
        inspect_mesh(mesh,scene.contract).require_pass()
        medians=lengths_by_surface(mesh)
        assert medians[1]<.00025 and medians[2]>.0003


@pytest.mark.parametrize('extension',['step','iges'])
def test_feature_widths_work_after_embedded_unit_cad_import(tmp_path,extension):
    path=write_case(tmp_path/('widths.'+extension),'widths')
    config=Configuration.from_dict({'schema_version':1,'geometry':{'kind':'cad','path':str(path),'sheet_normal':1},
        'length_unit':'cm','output_unit':'mm','mesh':{'target_size':1,'local':{'widths':{'enabled':True}}},
        'output_dir':str(tmp_path/'output')})
    with mesh_model(config) as scene:
        assert sorted(f.feature.size for f in scene.sizing.features)==pytest.approx([.2,.4])
        inspect_mesh(snapshot(scene.membership),scene.contract).require_pass()


def test_native_background_setter_consumes_min_of_all_feature_fields(tmp_path,monkeypatch):
    config=plate(tmp_path,{'target_size':1,'local':{'curves':[{'entity':1,'size':.2}],
        'boxes':[{'bounds':[4,4,-.1,6,6,.1],'size':.3}]}})
    original=gmsh.model.mesh.field.setAsBackgroundMesh
    calls=[]
    def select(tag):
        calls.append(tag)
        return original(tag)
    monkeypatch.setattr(gmsh.model.mesh.field,'setAsBackgroundMesh',select)
    with mesh_model(config) as scene:
        assert calls==[scene.sizing.background]
        root=scene.sizing.fields[-1]
        assert root.kind=='Min'
        leaves=set(map(int,gmsh.model.mesh.field.getNumbers(root.tag,'FieldsList')))
        assert {binding.kind for binding in scene.sizing.fields if binding.tag in leaves}=={'MathEval','Box','Threshold'}


def test_width_budget_blocks_before_dense_geometry_algebra(tmp_path,monkeypatch):
    config=plate(tmp_path,{'target_size':1,'local':{'widths':{'enabled':True},'max_pair_tests':1}})
    monkeypatch.setattr(np.linalg,'svd',lambda *a,**k:pytest.fail('measurement budget must precede dense allocation'))
    with pytest.raises(MeshBlocked,match='feature_measurement_incomplete'):
        with mesh_model(config):pass


def test_field_api_failure_does_not_fallback_or_damage_previous_output(tmp_path,monkeypatch):
    config=plate(tmp_path,{'target_size':1,'local':{'curves':[{'entity':1,'size':.2}]}})
    previous=config.output_dir/'previous'/'mesh.nas';previous.parent.mkdir(parents=True)
    previous.write_bytes(b'previous result')
    monkeypatch.setattr(gmsh.model.mesh.field,'add',lambda *a:(_ for _ in ()).throw(RuntimeError('field unavailable')))
    with pytest.raises(RuntimeError,match='field unavailable'):run(config)
    assert not gmsh.isInitialized()
    assert list(config.output_dir.rglob('mesh.nas'))==[previous]
    assert previous.read_bytes()==b'previous result'
