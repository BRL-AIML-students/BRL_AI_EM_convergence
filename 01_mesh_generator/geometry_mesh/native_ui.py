"""BRL parameters and quality actions inside the native Gmsh ONELAB panel."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import webbrowser

import gmsh
import numpy as np

from . import config
from .pipeline import _profile, initialize, publish_current
from .session import prepare, generate, current, improve, adopt_current, model_signature
from .meshdata import snapshot
from .experiments import plate_preset, catalog, load_run, compare_runs, save_failure

ACTION = "BRL/00 Action"
ACTION_LABELS = {"0":"0 - Idle", "1":"1 - Generate and save", "2":"2 - Inspect", "3":"3 - Improve",
                 "4":"4 - Export current", "5":"5 - Close", "6":"6 - Plate practice preset",
                 "7":"7 - Repeat A as new B", "8":"8 - Compare A and B", "9":"9 - Refresh saved runs",
                 "10":"10 - Load A settings for one-change test"}


def parameters(configuration: dict) -> list[dict]:
    cfg = configuration
    geometry = cfg["geometry"]
    values = geometry.get("parameters", {})
    def string(name, value, choices=None, file=False, readonly=False):
        p = {"type":"string", "name":"BRL/"+name,"values":[str(value)],"readOnly":readonly}
        if choices: p["choices"] = choices
        if file: p["kind"] = "file"
        return p
    def number(name, value, minimum=0, maximum=1e12, choices=None, readonly=False):
        p={"type":"number","name":"BRL/"+name,"values":[float(value)],"min":minimum,"max":maximum,"readOnly":readonly}
        if choices: p["choices"] = choices
        return p
    params=[{"type":"number","name":ACTION,"values":[0],"choices":list(range(11)),"valueLabels":{label:int(value) for value,label in ACTION_LABELS.items()}},
            string("Experiment/Help","6 preset > 1 generate A > 7 repeat A as B > 8 compare",readonly=True),
            string("Experiment/Preset note","40 x 30 mm / h=3 mm: editable practice values, not professor-specified",readonly=True),
            string("Experiment/Run A",""),string("Experiment/Run B",""),
            string("Experiment/Comparison unit","mm",["m","cm","mm","um"]),
            number("Experiment/Coordinate tolerance",1e-8,1e-15),
            string("Experiment/Current input","",readonly=True),
            string("Experiment/Plate dimensions","",readonly=True),
            string("Experiment/Target length","",readonly=True),
            string("Experiment/Seed and algorithm","",readonly=True),
            string("Experiment/Actual result","",readonly=True),
            string("Experiment/Saved runs","",readonly=True),
            string("Experiment/Comparison result","",readonly=True),
            string("Experiment/Comparison HTML","",readonly=True),
            string("Geometry/Kind",geometry["kind"],["plate","disk","sphere","box","cylinder","ogive","cad"]),
            string("Geometry/CAD file",geometry.get("path",""),file=True),
            string("Units/Input",cfg["length_unit"],["m","cm","mm","um"]),
            string("Units/Output",cfg["output_unit"],["m","cm","mm","um"]),
            string("Output/Name",cfg["name"]),string("Output/Folder",cfg["output_dir"]),
            number("Output/Automatic name",int(cfg["naming"]["automatic"]),0,1,[0,1]),
            string("Output/Case",cfg["naming"]["case"]),
            string("Result/NAS name","",readonly=True),
            number("Mesh/Controlled comparison",int(cfg["mesh"]["controlled"]),0,1,[0,1]),
            number("Mesh/Minimum size",cfg["mesh"]["minimum_size"] if cfg["mesh"]["minimum_size"] is not None else .1),
            number("Mesh/Automatic minimum",int(cfg["mesh"]["minimum_size"] is None),0,1,[0,1]),
            number("Mesh/Minimum fraction",cfg["mesh"]["minimum_size_fraction"],1e-12),
            number("Wave/Enabled",int(cfg["mesh"]["wave"]["enabled"]),0,1,[0,1]),
            number("Wave/Frequency GHz",(cfg["mesh"]["wave"]["frequency_hz"] or 1e10)/1e9,1e-12),
            number("Wave/Elements per wavelength",cfg["mesh"]["wave"]["elements_per_wavelength"],1e-12),
            number("Wave/Relative permittivity",cfg["mesh"]["wave"]["relative_permittivity"],1e-12),
            number("Wave/Relative permeability",cfg["mesh"]["wave"]["relative_permeability"],1e-12),
            number("Result/hMin",0,readonly=True),number("Result/hMax",0,readonly=True),
            number("Mesh/Scale fraction",cfg["mesh"]["scale_fraction"],1e-6,1),
            number("Mesh/Fixed size (0 auto)",cfg["mesh"]["target_size"] or 0),
            number("Mesh/Algorithm (0 BRL, 5 Delaunay, 6 Frontal)",cfg["mesh"]["algorithm"] or 0,0,6,[0,5,6]),
            number("Mesh/Random seed",cfg["mesh"]["random_seed"],0,2147483647),
            number("Quality/Maximum AR",cfg["quality"]["max_aspect_ratio"],1,3),
            number("Quality/Minimum angle",cfg["quality"]["min_angle_deg"],20,60),
            number("Quality/Absolute tolerance",cfg["quality"]["topology"]["absolute_tolerance"]),
            number("Quality/Relative tolerance",cfg["quality"]["topology"]["relative_tolerance"],1e-15,.01),
            number("Quality/Protected gap (0 unspecified)",cfg["quality"]["topology"]["protected_gap"] or 0),
            string("Quality/Boundary mode",cfg["quality"]["topology"]["boundary_mode"],["auto","open","closed"]),
            number("Improve/Enabled",int(cfg["mesh"]["improvement"]["enabled"]),0,1,[0,1]),
            number("Improve/Maximum passes",cfg["mesh"]["improvement"]["max_passes"],0,3,[0,1,2,3]),
            string("Improve/Fragment surface tags",",".join(map(str,cfg["mesh"]["improvement"]["fragment_surface_tags"]))),
            string("Result/Status","not inspected",readonly=True),string("Result/Output folder","",readonly=True),
            number("Result/Maximum AR",0,readonly=True),number("Result/Minimum angle",0,readonly=True),
            number("Result/Violating triangles",0,readonly=True),number("Result/T-junctions",0,readonly=True),
            number("Result/Review candidates",0,readonly=True)]
    for name in ("length","width","radius","height"):
        params.append(number("Geometry/"+name,values.get(name,10),1e-12))
    for name,default in (("D",110),("L",200),("t",3)):
        params.append(number("Geometry/"+name,values.get(name,default),0 if name == "t" else 1e-12))
    for axis,value in zip("XYZ",values.get("origin",[0,0,0])):
        params.append(number("Geometry/Origin "+axis,value,-1e12,1e12))
    return params


def read_configuration(base: dict) -> dict:
    cfg=deepcopy(base)
    def number(name): return float(gmsh.onelab.getNumber("BRL/"+name)[0])
    def string(name): return gmsh.onelab.getString("BRL/"+name)[0]
    kind=string("Geometry/Kind")
    if kind=="cad":
        cfg["geometry"]={"kind":"cad","path":str(Path(string("Geometry/CAD file")).expanduser().resolve())}
    else:
        required={"plate":["length","width"],"disk":["radius"],"sphere":["radius"],"box":["length","width","height"],"cylinder":["radius","height"],"ogive":["D","L","t"]}
        cfg["geometry"]={"kind":kind,"parameters":{name:number("Geometry/"+name) for name in required[kind]}}
        cfg["geometry"]["parameters"]["origin"]=[number("Geometry/Origin "+axis) for axis in "XYZ"]
    for target,name in (("length_unit","Units/Input"),("output_unit","Units/Output"),("name","Output/Name"),("output_dir","Output/Folder")):
        cfg[target]=string(name)
    cfg["naming"].update(automatic=bool(number("Output/Automatic name")),case=string("Output/Case"))
    fixed=number("Mesh/Fixed size (0 auto)")
    cfg["mesh"].update(mode="fixed" if fixed>0 else "auto",target_size=fixed or None,scale_fraction=number("Mesh/Scale fraction"))
    algorithm=number("Mesh/Algorithm (0 BRL, 5 Delaunay, 6 Frontal)")
    seed=number("Mesh/Random seed")
    if seed != int(seed) or algorithm != int(algorithm):
        raise ValueError("Algorithm and random seed must be integers")
    cfg["mesh"].update(algorithm=int(algorithm) or None,random_seed=int(seed))
    cfg["mesh"].update(controlled=bool(number("Mesh/Controlled comparison")),minimum_size=None if number("Mesh/Automatic minimum") else number("Mesh/Minimum size"),minimum_size_fraction=number("Mesh/Minimum fraction"))
    cfg["mesh"]["wave"].update(enabled=bool(number("Wave/Enabled")),frequency_hz=number("Wave/Frequency GHz")*1e9,elements_per_wavelength=number("Wave/Elements per wavelength"),relative_permittivity=number("Wave/Relative permittivity"),relative_permeability=number("Wave/Relative permeability"))
    cfg["quality"].update(max_aspect_ratio=number("Quality/Maximum AR"),min_angle_deg=number("Quality/Minimum angle"))
    cfg["quality"]["topology"].update(absolute_tolerance=number("Quality/Absolute tolerance"),relative_tolerance=number("Quality/Relative tolerance"),
                                      protected_gap=number("Quality/Protected gap (0 unspecified)") or None,boundary_mode=string("Quality/Boundary mode"))
    passes=number("Improve/Maximum passes")
    if passes != int(passes): raise ValueError("Maximum passes must be an integer")
    tags=string("Improve/Fragment surface tags").strip()
    cfg["mesh"]["improvement"].update(enabled=bool(number("Improve/Enabled")),max_passes=int(passes),
                                       fragment_surface_tags=[int(t.strip()) for t in tags.split(",")] if tags else [])
    return config.validate(cfg)


def fingerprint(mesh: dict) -> str:
    digest=hashlib.sha256()
    for key in ("node_ids","coordinates","element_ids","connectivity","pids","surface_tags"):
        digest.update(np.ascontiguousarray(mesh[key]).tobytes())
    return digest.hexdigest()


def display(mesh: dict, assessment: dict) -> None:
    for tag in gmsh.view.getTags():
        if gmsh.view.option.getString(int(tag), "Name").startswith("BRL "):
            gmsh.view.remove(int(tag))
    shape=assessment["scores"]["element_shape"]["metrics"]
    records=shape["element_values"]
    view=gmsh.view.add("BRL triangle aspect ratio")
    gmsh.view.addModelData(view,0,gmsh.model.getCurrent(),"ElementData",[r["element_id"] for r in records],[[r["aspect_ratio"] or 0] for r in records])
    gmsh.view.option.setNumber(view,"Visible",0)
    bad=set(assessment["scores"]["element_shape"]["problem_element_ids"])
    bad.update(assessment["scores"]["topology_and_normals"]["problem_element_ids"])
    topo=assessment["scores"]["topology_and_normals"]["metrics"]["conformity"]
    for r in topo.get("t_junctions",[]) + topo.get("proximity_candidates",[]) + topo.get("coincident_nodes",[]) + topo.get("nonmanifold_vertices",[]):
        bad.update(r.get("element_ids",[]))
    view=gmsh.view.add("BRL problem triangles")
    gmsh.view.addModelData(view,0,gmsh.model.getCurrent(),"ElementData",mesh["element_ids"].tolist(),[[int(e in bad)] for e in mesh["element_ids"]])
    gmsh.view.option.setNumber(view,"Visible",1 if bad else 0)
    gmsh.onelab.setString("BRL/Result/Status",[assessment["quality_gate_status"]])
    for name,value in (("Maximum AR",shape["aspect_ratio_max"] or 0),("Minimum angle",shape["minimum_angle_deg"]),
                       ("Violating triangles",shape["violating_element_count"]),("T-junctions",len(topo.get("t_junctions",[]))),
                       ("Review candidates",len(topo.get("proximity_candidates",[])))):
        gmsh.onelab.setNumber("BRL/Result/"+name,[value])


class Controller:
    def __init__(self, configuration: dict):
        self.base=config.validate(configuration)
        self.context=None
        self.last_fingerprint=None
        self.history=[]

    def refresh_runs(self, newest=None) -> list[dict]:
        root=gmsh.onelab.getString("BRL/Output/Folder")[0]
        records=catalog(root)
        choices=[r["path"] for r in records if r["state"] in {"valid","quality_warning"}]
        for side in ("A","B"):
            name="BRL/Experiment/Run "+side
            selected=gmsh.onelab.getString(name)
            value=selected[0] if selected else ""
            if newest and side==("A" if not gmsh.onelab.getString("BRL/Experiment/Run A")[0] else "B"):
                value=newest
                newest=None
            if value not in choices:
                value=""
            gmsh.onelab.set(json.dumps([{"type":"string","name":name,"values":[value],"choices":[""]+choices}]))
        gmsh.onelab.setString("BRL/Experiment/Saved runs",[" | ".join(r["run_id"]+": "+r["state"] for r in records) or "No saved runs"])
        return records

    def set_inputs(self, cfg: dict) -> None:
        # Restore hidden config controls too; a loaded run is the source of truth.
        self.base=config.validate(cfg)
        gmsh.onelab.set(json.dumps([p for p in parameters(self.base) if not p["name"].startswith("BRL/Experiment/")]))
        self.update_input_summary()

    def update_input_summary(self) -> None:
        cfg=read_configuration(self.base)
        p=cfg["geometry"].get("parameters",{})
        dimensions=f'{p.get("length", "-")} x {p.get("width", "-")} {cfg["length_unit"]}' if cfg["geometry"]["kind"]=="plate" else cfg["geometry"]["kind"]
        gmsh.onelab.setString("BRL/Experiment/Plate dimensions",[dimensions])
        gmsh.onelab.setString("BRL/Experiment/Target length",[f'{cfg["mesh"]["target_size"] if cfg["mesh"]["mode"]=="fixed" else "auto"} {cfg["output_unit"]} (target, not actual edge)'])
        gmsh.onelab.setString("BRL/Experiment/Seed and algorithm",[f'{cfg["mesh"]["random_seed"]} / {cfg["mesh"]["algorithm"] or "BRL automatic"}'])
        text=json.dumps({"geometry":cfg["geometry"],"input_unit":cfg["length_unit"],"mesh_size_unit":cfg["output_unit"],
                         "mode":cfg["mesh"]["mode"],"input_target":cfg["mesh"]["target_size"],
                         "controlled":cfg["mesh"]["controlled"],"algorithm":cfg["mesh"]["algorithm"],"seed":cfg["mesh"]["random_seed"]},ensure_ascii=False)
        gmsh.onelab.setString("BRL/Experiment/Current input",[text])

    def experiment_action(self, action: int) -> dict | None:
        if action==6:
            self.set_inputs(plate_preset(gmsh.onelab.getString("BRL/Output/Folder")[0]))
            gmsh.onelab.setString("BRL/Experiment/Actual result",["Practice preset loaded. Action 1 generates and saves a new run."])
            return None
        if action==9:
            return {"runs":self.refresh_runs()}
        a=gmsh.onelab.getString("BRL/Experiment/Run A")[0]
        if not a:
            raise ValueError("Select Experiment/Run A, or use action 1 to generate A first")
        if action in {7,10}:
            report,_=load_run(a)
            cfg=deepcopy(report["configuration"])
            # Keep the currently selected history/output root.
            cfg["output_dir"]=gmsh.onelab.getString("BRL/Output/Folder")[0]
            self.set_inputs(cfg)
            if action==10: return None
            result=self.perform(1)
            gmsh.onelab.setString("BRL/Experiment/Run B",[gmsh.onelab.getString("BRL/Result/Output folder")[0]])
            return result
        b=gmsh.onelab.getString("BRL/Experiment/Run B")[0]
        if not b:
            raise ValueError("Select Experiment/Run B, or use action 7 to repeat A as B")
        result=compare_runs(a,b,gmsh.onelab.getNumber("BRL/Experiment/Coordinate tolerance")[0],
                            gmsh.onelab.getString("BRL/Experiment/Comparison unit")[0],
                            gmsh.onelab.getString("BRL/Output/Folder")[0])
        gmsh.onelab.setString("BRL/Experiment/Comparison HTML",[result["html"]])
        gmsh.onelab.setString("BRL/Experiment/Comparison result",[json.dumps({k:result[k] for k in
                              ("experiment_kind","same_mesh","node_set_equal","connectivity_equal","coordinate_unit","tolerance","counts")})])
        webbrowser.open(Path(result["html"]).as_uri())
        return result

    def perform(self, action: int) -> dict | None:
        if action in {6,7,8,9,10}:
            return self.experiment_action(action)
        gmsh.onelab.setString("BRL/Result/Output folder",[""])
        cfg=read_configuration(self.base)
        self.update_input_summary()
        if action==1:
            self.context=None
            self.last_fingerprint=None
            try:
                started=time.perf_counter()
                self.context=prepare(cfg)
                generate(self.context)
                seconds=time.perf_counter()-started
                started=time.perf_counter()
                mesh,assessment,self.history=improve(self.context,_profile())
                self.context.sizing["timings"]={"geometry_and_mesh_seconds":seconds,"improvement_seconds":time.perf_counter()-started}
            except Exception as exc:
                folder=save_failure(cfg,exc,self.context.sizing if self.context else None)
                gmsh.onelab.setString("BRL/Result/Output folder",[str(folder)])
                gmsh.onelab.setString("BRL/Experiment/Actual result",["generation_failed: "+str(folder)+" / "+str(exc)])
                self.refresh_runs()
                raise
        else:
            if self.context is None or self.context.model_name != gmsh.model.getCurrent() or self.context.model_signature != model_signature():
                self.context=adopt_current(cfg)
                self.history=[]
            elif self.last_fingerprint is None or fingerprint(snapshot(self.context.membership)) != self.last_fingerprint:
                self.history=[]
            original=self.context.configuration
            # Changed geometry, units or sizing cannot be applied to a stale model.
            for key in ("geometry","length_unit","output_unit","mesh"):
                if cfg[key]!=original[key]: raise ValueError("Input settings changed: use action 1 to rebuild")
            self.context.configuration=cfg
            if action==3:
                mesh,assessment,self.history=improve(self.context,_profile())
            else:
                mesh,assessment=current(self.context,_profile())
        gmsh.onelab.setNumber("BRL/Result/hMin",[self.context.sizing.get("minimum_size", -1)])
        gmsh.onelab.setNumber("BRL/Result/hMax",[self.context.sizing["target_size"]])
        display(mesh,assessment)
        self.last_fingerprint=fingerprint(mesh)
        if action in {1,4}:
            report=publish_current(self.context,self.history)
            gmsh.onelab.setString("BRL/Result/Output folder",[report["output_directory"]])
            gmsh.onelab.setString("BRL/Result/NAS name",[report["artifacts"]["nas"] or "발행 보류"])
            stats=report["experiment"].get("distributions",{}).get("edge_length",{})
            gmsh.onelab.setString("BRL/Experiment/Actual result",[json.dumps({"state":report["experiment"]["mesh_state"],
                        "nodes":len(mesh["node_ids"]),"triangles":len(mesh["element_ids"]),"actual_unique_edges":stats,
                        "edge_unit":cfg["output_unit"],"applied_target":self.context.sizing["target_size"],
                        "candidate_rules":self.context.sizing["candidate_rules"],"timings":self.context.sizing.get("timings")})])
            self.refresh_runs(report["output_directory"])
            if action==4: return report
        return assessment

    def invalidate(self) -> None:
        try:
            self.update_input_summary()
        except Exception:
            pass
        if self.context is None or self.last_fingerprint is None: return
        try:
            if gmsh.model.getCurrent()==self.context.model_name and self.context.model_signature==model_signature() and fingerprint(snapshot(self.context.membership))==self.last_fingerprint and read_configuration(self.base)==self.context.configuration:
                return
        except Exception:
            pass
        self.last_fingerprint=None
        status=gmsh.onelab.getString("BRL/Result/Status")
        if not status or not status[0].startswith("error:"):
            gmsh.onelab.setString("BRL/Result/Status",["changed: inspect before use"])
        gmsh.onelab.setString("BRL/Result/Output folder",[""])
        for name in ("Maximum AR","Minimum angle","Violating triangles","T-junctions","Review candidates"):
            gmsh.onelab.setNumber("BRL/Result/"+name,[-1])


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="BRL mesh generation and inspection in native Gmsh UI")
    parser.add_argument("config",nargs="?",type=Path)
    parser.add_argument("--smoke-test",action="store_true",help=argparse.SUPPRESS)
    parser.add_argument("--plate-experiment",action="store_true",help="start with editable 40 x 30 mm, h=3 mm practice preset")
    args=parser.parse_args(argv)
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Gmsh native UI must run in the main thread")
    cfg=config.load(args.config) if args.config else plate_preset() if args.plate_experiment else config.validate({})
    if cfg["geometry"]["kind"] not in config.PRIMITIVES | {"cad"}:
        raise ValueError("native parameter panel supports primitives/CAD; use CLI for CSG")
    initialize()
    try:
        controller=Controller(cfg)
        gmsh.onelab.set(json.dumps(parameters(cfg)))
        controller.update_input_summary()
        controller.refresh_runs()
        gmsh.fltk.initialize()
        gmsh.option.setNumber("General.MenuWidth",480)
        if args.smoke_test:
            controller.perform(1)
            result=controller.perform(4)
            gmsh.fltk.update(); gmsh.fltk.wait(.1)
            print(json.dumps({"status":result["status"],"output_directory":result["output_directory"]}))
            return 0 if result["status"]=="complete" else 2
        gmsh.fltk.update()
        while gmsh.fltk.isAvailable():
            gmsh.fltk.wait(.2)
            value=gmsh.onelab.getNumber(ACTION)
            action=int(value[0]) if value else 0
            if action==5: break
            if action in {1,2,3,4,6,7,8,9,10}:
                gmsh.onelab.setNumber(ACTION,[0])
                try:
                    controller.perform(action)
                except Exception as exc:
                    gmsh.onelab.setString("BRL/Result/Status",["error: "+str(exc)])
                    gmsh.logger.write(str(exc),"error")
                gmsh.fltk.update()
                gmsh.graphics.draw()
            controller.invalidate()
        return 0
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


if __name__=="__main__":
    raise SystemExit(main())
