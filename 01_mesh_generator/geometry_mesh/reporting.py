from __future__ import annotations

from html import escape
import json
import math
from pathlib import Path
from typing import Any


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key,item in value.items()}
    if isinstance(value, (list,tuple)):
        return [json_safe(item) for item in value]
    return value


def write_json(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(json_safe(report), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_html(path: Path, report: dict[str, Any]) -> None:
    report = json_safe(report)
    scores = report["assessment"]["scores"]
    cards = []
    for name, item in scores.items():
        coverage = item["coverage"]
        score = "—" if item["score"] is None else f'{item["score"]:.1f}'
        reason = item["not_assessed_reason"] or item["rationale"]
        recommendations = " ".join(item["recommendations"]) or "No corrective action recommended."
        cards.append(
            f'<article class="card"><h2>{escape(name.replace("_", " "))}</h2>'
            f'<div class="score {escape(coverage)}">{score}</div><p>{escape(coverage)}</p>'
            f'<p><strong>{escape(item["status_band"])}</strong> · {escape(reason)}</p><p>{escape(recommendations)}</p><details><summary>metrics and element IDs</summary>'
            f'<pre>{escape(json.dumps({"metrics": item["metrics"], "problem_element_ids": item["problem_element_ids"]}, ensure_ascii=False, indent=2))}</pre></details></article>'
        )
    gates = report["assessment"]["fatal_gates"]
    gate_html = "<p class='ok'>No fatal gate was triggered.</p>" if not gates else f"<pre class='bad'>{escape(json.dumps(gates, ensure_ascii=False, indent=2))}</pre>"
    embedded = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Surface mesh quality report</title><style>
:root{{--ink:#19202a;--muted:#647184;--paper:#f3f6f8;--card:#fff;--accent:#16697a;--bad:#9b2226}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}
main{{max-width:1120px;margin:auto;padding:32px 20px}}h1{{margin-bottom:4px}}.meta{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin:24px 0}}
.card,section{{background:var(--card);border:1px solid #dce3e8;border-radius:12px;padding:18px;box-shadow:0 2px 10px #18222d0b}}
.card h2{{font-size:17px;margin:0}}.score{{font-size:38px;font-weight:750;color:var(--accent)}}.not_assessed{{color:var(--muted)}}
pre{{white-space:pre-wrap;word-break:break-word;background:#eef2f4;padding:12px;border-radius:8px;max-height:430px;overflow:auto}}.ok{{color:#27734b}}.bad{{color:var(--bad)}}
@media print{{body{{background:white}}.card,section{{box-shadow:none;break-inside:avoid}}details{{display:block}}}}
</style></head><body><main><h1>Surface mesh quality report</h1>
<p class="meta">Run {escape(report['run_id'])} · status {escape(report['status'])} · profile {escape(report['score_profile']['profile_version'])}</p>
<section><h2>Fatal gates</h2>{gate_html}</section><div class="grid">{''.join(cards)}</div>
<section><h2>Raw report</h2><details><summary>Show complete machine-readable evidence</summary><pre id="raw"></pre></details></section>
<script id="report-data" type="application/json">{embedded}</script><script>const d=JSON.parse(document.getElementById('report-data').textContent);document.getElementById('raw').textContent=JSON.stringify(d,null,2);</script>
</main></body></html>"""
    path.write_text(html, encoding="utf-8", newline="\n")
