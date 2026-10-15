"""실제 Gmsh 실행으로 반복·목표 길이·시드·모양 경고 사례를 보존한다."""
from copy import deepcopy
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import uuid

from .experiments import plate_preset, compare_runs
from .pipeline import run
from .reporting import write_json


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("outputs"))
    args=parser.parse_args(argv)
    root=args.output.resolve()/f'plate_evidence_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{uuid.uuid4().hex[:8]}'
    cfg=plate_preset(str(root));results={}
    for label,changes in (("A",{}),("B_repeat",{}),("C_h5",{"target_size":5}),
                          ("D_seed2",{"random_seed":2}),("E_shape_warning",{}),
                          ("F_auto",{"mode":"auto","scale_fraction":.08})):
        case=deepcopy(cfg);case["mesh"].update(changes)
        if label=="E_shape_warning":case["quality"]["max_aspect_ratio"]=1.01
        result=run(case);results[label]=result
    comparisons={label:compare_runs(results["A"]["output_directory"],results[label]["output_directory"],output_dir=root)
                 for label in results if label!="A"}
    assert comparisons["B_repeat"]["same_mesh"] is True
    assert comparisons["C_h5"]["same_mesh"] is False
    assert results["E_shape_warning"]["experiment"]["mesh_state"]=="quality_warning"
    summary={"runs":{label:{"path":r["output_directory"],"state":r["experiment"]["mesh_state"],
                                  "nodes":r["assessment"]["raw_metrics"]["node_count"],
                                  "triangles":r["assessment"]["raw_metrics"]["triangle_count"],
                                  "target":r["sizing"]["target_size"],
                                  "edges":r["experiment"]["distributions"]["edge_length"],
                                  "sizing_rules":r["sizing"]["candidate_rules"]} for label,r in results.items()},
             "comparisons":{label:{k:c[k] for k in ("same_mesh","node_set_equal","connectivity_equal","counts","html","input_differences","experiment_kind")} for label,c in comparisons.items()}}
    write_json(root/"evidence.json",summary)
    links=''.join(f'<li><a href="{escape(str(Path(c["html"]).relative_to(root)).replace(chr(92),"/"))}">A vs {escape(label)}</a> · same_mesh={c["same_mesh"]}</li>' for label,c in comparisons.items())
    (root/"index.html").write_text('<!doctype html><meta charset="utf-8"><title>BRL 평판 실험 검증</title><main style="font:16px/1.7 system-ui;max-width:960px;margin:40px auto"><h1>실제 Gmsh 평판 실험 검증</h1><p>40×30 mm · A: 목표 길이 3 mm · C: 5 mm · 변경 가능한 실습값입니다.</p><ul>'+links+'</ul><pre style="white-space:pre-wrap">'+escape(json.dumps(summary,ensure_ascii=False,indent=2))+'</pre></main>',encoding='utf-8')
    print(json.dumps({"output_directory":str(root),"runs":summary["runs"]},ensure_ascii=False))


if __name__=="__main__":main()
