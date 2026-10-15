"""실제 평판·파일·ONELAB 흐름을 사용하는 실험 및 비교 검증."""
from copy import deepcopy
import json
from pathlib import Path

import gmsh
import numpy as np
import pytest

from geometry_mesh.experiments import (plate_preset, compare_meshes, compare_runs, load_run,
                                       catalog, indexed, file_hash)
from geometry_mesh.meshdata import snapshot
from geometry_mesh.native_ui import Controller, parameters, read_configuration, ACTION
from geometry_mesh.pipeline import run, initialize


@pytest.fixture(scope="module")
def real_runs(tmp_path_factory):
    root=tmp_path_factory.mktemp("real_plate")
    cfg=plate_preset(str(root))
    a=run(cfg); b=run(cfg)
    cfg["mesh"]["target_size"]=5
    c=run(cfg)
    return root,a,b,c


def test_real_repeated_generation_and_length_change(real_runs):
    root,a,b,c=real_runs
    ab=compare_runs(a["output_directory"],b["output_directory"])
    assert ab["same_mesh"] is True
    assert ab["experiment_kind"]=="same_inputs_repeat"
    assert ab["input_differences"]==[] and ab["effective_differences"]==[]
    assert ab["counts"]["unique_matches"]==ab["counts"]["nodes_A"]
    ac=compare_runs(a["output_directory"],c["output_directory"])
    assert ac["same_mesh"] is False
    assert ac["input_differences"]==[{"setting":"mesh.target_size","A":3,"B":5}]
    assert ac["counts"]["triangles_A"]>ac["counts"]["triangles_B"]
    assert ac["distributions"]["edge_length"]["A"]["median"]<ac["distributions"]["edge_length"]["B"]["median"]
    assert Path(ac["html"]).exists()
    for result in (a,b,c):
        folder=Path(result["output_directory"])
        assert result["status"]=="complete"
        assert (folder/result["artifacts"]["nas"]).exists()
        assert result["experiment"]["gmsh_minSICN"]["summary"]["count"]==result["assessment"]["raw_metrics"]["triangle_count"]
        assert result["sizing"]["applied_options"]["Mesh.RandomSeed"]==1
        assert result["sizing"]["gmsh_defaults"]["Mesh.Algorithm"]==6
        assert result["sizing"]["timings"]["geometry_and_mesh_seconds"]>0
    assert len({a["output_directory"],b["output_directory"],c["output_directory"]})==3


def test_actual_msh_renumber_and_shuffle_is_equal(real_runs,tmp_path):
    _,a,_,_=real_runs
    path=tmp_path/"same_mesh.msh"
    initialize()
    try:
        gmsh.open(str(Path(a["output_directory"])/"diagnostic.msh"))
        original=snapshot({t:i+1 for i,(_,t) in enumerate(gmsh.model.getEntities(2))})
        gmsh.option.setNumber("Mesh.MshFileVersion",2.2)
        gmsh.option.setNumber("Mesh.Binary",0)
        gmsh.write(str(path))
        lines=path.read_text().splitlines()
        ns=lines.index("$Nodes"); count=int(lines[ns+1]); nodes=[row.split() for row in lines[ns+2:ns+2+count]]
        remap={int(row[0]):10000+13*i for i,row in enumerate(reversed(nodes))}
        lines[ns+2:ns+2+count]=[" ".join([str(remap[int(row[0])])]+row[1:]) for row in reversed(nodes)]
        es=lines.index("$Elements"); count=int(lines[es+1]); elements=[row.split() for row in lines[es+2:es+2+count]]
        new=[]
        for i,row in enumerate(reversed(elements)):
            start=3+int(row[2])
            new.append(" ".join([str(90000+17*i)]+row[1:start]+[str(remap[int(n)]) for n in row[start:]]))
        lines[es+2:es+2+count]=new
        path.write_text("\n".join(lines)+"\n")
        gmsh.clear();gmsh.open(str(path))
        changed=snapshot({t:i+1 for i,(_,t) in enumerate(gmsh.model.getEntities(2))})
        assert not np.array_equal(original["node_ids"],changed["node_ids"])
        result=compare_meshes(original,changed)
        assert result["same_mesh"] is True
        assert result["counts"]["common_triangles"]==len(original["element_ids"])
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


def square():
    return {"node_ids":np.array([11,22,33,44]),"coordinates":np.array([[0.,0,0],[1,0,0],[1,1,0],[0,1,0]]),
            "element_ids":np.array([31,47]),"connectivity":np.array([[11,22,33],[11,33,44]])}


def test_connectivity_difference_with_identical_nodes():
    a=square();b=deepcopy(a)
    b["connectivity"]=np.array([[11,22,44],[22,33,44]])
    r=compare_meshes(a,b)
    assert r["node_set_equal"] is True and r["connectivity_equal"] is False
    assert r["counts"]["absent_A"]==0 and r["counts"]["common_triangles"]==0
    assert len(r["visual"]["shared_edges_A"])==4


def test_units_vertex_order_and_cell_boundary_tolerance():
    a=square();b=deepcopy(a)
    b["coordinates"]/=1000
    b["connectivity"]=b["connectivity"][::-1,::-1]
    assert compare_meshes(a,b,unit_b="m")["same_mesh"] is True
    # Across a rounding/cell boundary, but Euclidean distance is within tolerance.
    a["coordinates"][:,0]+=.99e-4;b=deepcopy(a);b["coordinates"][:,0]+=.02e-4
    assert compare_meshes(a,b,tolerance=1e-4)["same_mesh"] is True
    b["coordinates"][:,0]+=.001
    assert compare_meshes(a,b,tolerance=1e-4)["node_set_equal"] is False


def test_ambiguous_correspondence_is_not_displacement():
    a=square()
    r=compare_meshes(a,a,tolerance=2)
    assert r["same_mesh"] is None and r["node_set_equal"] is None and r["connectivity_equal"] is None
    assert r["counts"]["unique_matches"]==0 and r["counts"]["ambiguous_A"]==4
    with pytest.raises(ValueError,match="positive"):
        compare_meshes(a,a,tolerance=0)


@pytest.mark.parametrize("corruption",["duplicate_ids","nonfinite","missing_node","degenerate"])
def test_corrupt_arrays_rejected(corruption):
    a=square()
    if corruption=="duplicate_ids":a["node_ids"][0]=22
    elif corruption=="nonfinite":a["coordinates"][0,0]=np.nan
    elif corruption=="missing_node":a["connectivity"][0,0]=999
    else:a["coordinates"][0]=a["coordinates"][1]
    with pytest.raises(ValueError,match="corrupt"):
        indexed(a)


def test_low_shape_quality_preserved_and_corrupt_file_excluded(tmp_path):
    cfg=plate_preset(str(tmp_path));cfg["quality"]["max_aspect_ratio"]=1.01
    result=run(cfg);folder=Path(result["output_directory"])
    assert result["experiment"]["mesh_state"]=="quality_warning"
    assert result["status"]=="invalid" and result["artifacts"]["nas"] is None
    assert compare_runs(folder,folder)["same_mesh"] is True
    (folder/"diagnostic.msh").write_text("broken")
    with pytest.raises(ValueError,match="hash mismatch"):load_run(folder)
    assert catalog(tmp_path)[0]["state"]=="corrupt_file"


def test_seed_change_is_separate_experiment(real_runs):
    root,a,_,_=real_runs
    cfg=plate_preset(str(root));cfg["mesh"]["random_seed"]=2
    b=run(cfg)
    result=compare_runs(a["output_directory"],b["output_directory"])
    assert result["experiment_kind"]=="seed_change"
    assert result["input_differences"]==[{"setting":"mesh.random_seed","A":1,"B":2}]
    # A seed change is not a promise of a different mesh.
    assert result["same_mesh"] in {True,False,None}


def test_native_full_plate_workflow_preserves_history_and_export(tmp_path,monkeypatch):
    monkeypatch.setattr("geometry_mesh.native_ui.webbrowser.open",lambda url:True)
    initialize()
    try:
        cfg=plate_preset(str(tmp_path));gmsh.onelab.set(json.dumps(parameters(cfg)))
        controller=Controller(cfg)
        controller.perform(6)
        assert read_configuration(controller.base)["geometry"]["parameters"]["length"]==40
        with pytest.raises(ValueError,match="Select Experiment/Run A"):
            controller.perform(8)
        controller.perform(1)
        a=gmsh.onelab.getString("BRL/Experiment/Run A")[0]
        assert a
        with pytest.raises(ValueError,match="Select Experiment/Run B"):
            controller.perform(8)
        hash_a=file_hash(Path(a)/"diagnostic.msh")
        # Repeat ignores unsaved edits and restores exactly the saved A settings.
        gmsh.onelab.setNumber("BRL/Mesh/Fixed size (0 auto)",[9])
        controller.perform(7)
        b=gmsh.onelab.getString("BRL/Experiment/Run B")[0]
        assert a!=b and controller.perform(8)["same_mesh"] is True
        controller.perform(10)
        gmsh.onelab.setNumber("BRL/Mesh/Fixed size (0 auto)",[5])
        controller.perform(1)
        changed=controller.perform(8)
        assert changed["same_mesh"] is False
        assert changed["input_differences"]==[{"setting":"mesh.target_size","A":3.,"B":5.}]
        assert file_hash(Path(a)/"diagnostic.msh")==hash_a
        export=controller.perform(4)
        assert export["status"]=="complete" and Path(export["output_directory"],export["artifacts"]["nas"]).exists()
        # New controller can discover all previous runs without in-memory history.
        reopened=Controller(cfg);assert len(reopened.perform(9)["runs"])==4
        assert gmsh.onelab.getString("BRL/Experiment/Comparison HTML")[0].endswith("comparison.html")
        action=json.loads(gmsh.onelab.get(ACTION))
        assert action["valueLabels"]["7 - Repeat A as new B"]==7
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


def test_generation_failure_recorded_without_overwriting(tmp_path,monkeypatch):
    initialize()
    try:
        cfg=plate_preset(str(tmp_path));gmsh.onelab.set(json.dumps(parameters(cfg)));c=Controller(cfg)
        c.perform(1);a=gmsh.onelab.getString("BRL/Experiment/Run A")[0]
        def failure(context):raise RuntimeError("실패 보존 검증")
        monkeypatch.setattr("geometry_mesh.native_ui.generate",failure)
        with pytest.raises(RuntimeError,match="실패 보존 검증"):c.perform(1)
        assert {r["state"] for r in catalog(tmp_path)}=={"valid","generation_failed"}
        assert load_run(a)[0]["experiment"]["mesh_state"]=="valid"
    finally:
        gmsh.logger.stop()
        gmsh.finalize()
