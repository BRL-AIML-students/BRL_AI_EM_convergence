"""BRL parameters and quality actions inside the native Gmsh ONELAB panel."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading

import gmsh
import numpy as np

from . import config
from .pipeline import _profile, initialize, publish_current
from .session import prepare, generate, current, improve, adopt_current, model_signature
from .meshdata import snapshot

ACTION = "BRL/00 Action (0 idle, 1 generate, 2 inspect, 3 improve, 4 export, 5 close)"


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
    params=[{"type":"number","name":ACTION,"values":[0],"choices":[0,1,2,3,4,5]},
            string("Geometry/Kind",geometry["kind"],["plate","disk","sphere","box","cylinder","cad"]),
            string("Geometry/CAD file",geometry.get("path",""),file=True),
            string("Units/Input",cfg["length_unit"],["m","cm","mm","um"]),
            string("Units/Output",cfg["output_unit"],["m","cm","mm","um"]),
            string("Output/Name",cfg["name"]),string("Output/Folder",cfg["output_dir"]),
            number("Mesh/Scale fraction",cfg["mesh"]["scale_fraction"],1e-6,1),
            number("Mesh/Fixed size (0 auto)",cfg["mesh"]["target_size"] or 0),
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
        required={"plate":["length","width"],"disk":["radius"],"sphere":["radius"],"box":["length","width","height"],"cylinder":["radius","height"]}
        cfg["geometry"]={"kind":kind,"parameters":{name:number("Geometry/"+name) for name in required[kind]}}
        cfg["geometry"]["parameters"]["origin"]=[number("Geometry/Origin "+axis) for axis in "XYZ"]
    for target,name in (("length_unit","Units/Input"),("output_unit","Units/Output"),("name","Output/Name"),("output_dir","Output/Folder")):
        cfg[target]=string(name)
    fixed=number("Mesh/Fixed size (0 auto)")
    cfg["mesh"].update(mode="fixed" if fixed>0 else "auto",target_size=fixed or None,scale_fraction=number("Mesh/Scale fraction"))
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

    def perform(self, action: int) -> dict | None:
        gmsh.onelab.setString("BRL/Result/Output folder",[""])
        cfg=read_configuration(self.base)
        if action==1:
            self.context=prepare(cfg)
            generate(self.context)
            mesh,assessment,self.history=improve(self.context,_profile())
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
        display(mesh,assessment)
        self.last_fingerprint=fingerprint(mesh)
        if action==4:
            report=publish_current(self.context,self.history)
            gmsh.onelab.setString("BRL/Result/Output folder",[report["output_directory"]])
            return report
        return assessment

    def invalidate(self) -> None:
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
    args=parser.parse_args(argv)
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Gmsh native UI must run in the main thread")
    cfg=config.load(args.config) if args.config else config.validate({})
    if cfg["geometry"]["kind"] not in config.PRIMITIVES | {"cad"}:
        raise ValueError("native parameter panel supports primitives/CAD; use CLI for CSG")
    initialize()
    try:
        controller=Controller(cfg)
        gmsh.onelab.set(json.dumps(parameters(cfg)))
        gmsh.fltk.initialize()
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
            if action in {1,2,3,4}:
                gmsh.onelab.setNumber(ACTION,[0])
                try:
                    controller.perform(action)
                except Exception as exc:
                    gmsh.onelab.setString("BRL/Result/Status",["error: "+str(exc)])
                    gmsh.logger.write(str(exc),"error")
                gmsh.fltk.update()
            controller.invalidate()
        return 0
    finally:
        gmsh.logger.stop()
        gmsh.finalize()


if __name__=="__main__":
    raise SystemExit(main())
