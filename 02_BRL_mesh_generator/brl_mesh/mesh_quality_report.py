"""Offline report for the exact inspected and independently validated NAS mesh."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
import platform
import numpy as np
import gmsh
from . import __version__


def write_report(path, mesh, inspection, config, cad_sha256, nas_sha256, nas_name="mesh.nas"):
    policy = inspection.shape.settings
    definitions = [
        ('ICN', policy.icn_enabled, policy.icn_minimum, 'min', [inspection.icn[int(i)] for i in mesh.element_ids] if policy.icn_enabled else None),
        ('IGE', policy.ige_enabled, policy.ige_minimum, 'min', [inspection.ige[int(i)] for i in mesh.element_ids] if policy.ige_enabled else None),
        ('Aspect ratio', policy.aspect_ratio_enabled, policy.aspect_ratio_maximum, 'max', inspection.shape.aspect_ratios if policy.aspect_ratio_enabled else None),
        ('최소각 (°)', policy.minimum_angle_enabled, policy.minimum_angle_degrees, 'min', inspection.shape.minimum_angles if policy.minimum_angle_enabled else None),
        ('Radius ratio', policy.radius_ratio_enabled, policy.radius_ratio_minimum, 'min', inspection.radius_ratios if policy.radius_ratio_enabled else None),
    ]
    union = np.zeros(len(mesh.element_ids), dtype=bool)
    summaries, rows, charts = {}, [], []
    for name, enabled, threshold, direction, values in definitions:
        if not enabled:
            summaries[name] = {'enabled': False, 'threshold': threshold, 'evaluated': False}
            rows.append(f'<tr><th>{html.escape(name)}</th><td colspan="7">비활성 · 평가하지 않음</td></tr>')
            continue
        values = np.asarray(values, dtype=float)
        if len(values) != len(mesh.element_ids) or not np.isfinite(values).all():
            raise ValueError(f'{name} 품질 측정이 불완전합니다')
        bad = values < threshold if direction == 'min' else values > threshold
        union |= bad
        summaries[name] = {'enabled': True, 'evaluated': True, 'threshold': threshold,
            'direction': direction, 'minimum': float(values.min()), 'mean': float(values.mean()),
            'maximum': float(values.max()), 'pass_percent': float(100 * np.mean(~bad)), 'violating_count': int(bad.sum())}
        item = summaries[name]
        rows.append(f'<tr><th>{html.escape(name)}</th><td>{threshold:g}</td><td>{'이상' if direction == 'min' else '이하'}</td><td>{item["minimum"]:.6g}</td><td>{item["mean"]:.6g}</td><td>{item["maximum"]:.6g}</td><td>{item["pass_percent"]:.2f}%</td><td>{item["violating_count"]}</td></tr>')
        lo, hi = min(float(values.min()), threshold), max(float(values.max()), threshold)
        if hi == lo: lo, hi = lo - 0.5, hi + 0.5
        counts, edges = np.histogram(values, bins=20, range=(lo, hi))
        peak = max(int(counts.max()), 1)
        bars = ''.join(f'<rect x="{i*20}" y="{100-90*int(c)/peak:.2f}" width="19" height="{90*int(c)/peak:.2f}"/>' for i,c in enumerate(counts))
        x = 400 * (threshold-lo)/(hi-lo)
        charts.append(f'<section><h3>{html.escape(name)}</h3><svg viewBox="0 0 400 110" role="img" aria-label="{html.escape(name)} 분포, 빨간 선은 기준값 {threshold:g}">{bars}<line x1="{x:.2f}" x2="{x:.2f}" y1="0" y2="100" stroke="#b42318" stroke-width="2"/></svg><p>범위 {lo:.6g} ~ {hi:.6g}; 빨간 선: 기준 {threshold:g}</p></section>')
    bad_rows = []
    for index in np.flatnonzero(union):
        violations = []
        all_values = []
        for name, enabled, threshold, direction, values in definitions:
            if enabled:
                value = float(values[index])
                all_values.append(f'{name}: {value:.6g}')
                if (value < threshold if direction == 'min' else value > threshold):
                    violations.append(name)
            else:
                all_values.append(f'{name}: 평가하지 않음')
        bad_rows.append(f'<tr data-metrics="{html.escape("|".join(violations), quote=True)}"><td>{int(mesh.element_ids[index])}</td><td>{html.escape(", ".join(violations))}</td><td>{html.escape(", ".join(all_values))}</td></tr>')
    summary = {'element_count': len(mesh.element_ids), 'violating_count': int(union.sum()), 'metrics': summaries, 'nas_sha256': nas_sha256, 'cad_sha256': cad_sha256}
    config_text = html.escape(json.dumps(config.to_dict(), ensure_ascii=False, indent=2, default=str))
    metadata = html.escape(json.dumps({'생성 시각 UTC': datetime.now(timezone.utc).isoformat(), '입력 CAD': config.to_dict()['geometry'].get('path', '내장 형상'), '출력 NAS': nas_name, 'CAD SHA-256': cad_sha256, 'NAS SHA-256': nas_sha256, 'BRL': __version__, 'Python': platform.python_version(), 'Gmsh': gmsh.__version__, 'NumPy': np.__version__}, ensure_ascii=False, indent=2))
    document = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>메쉬 품질 보고서</title><style>*,*::before,*::after{box-sizing:border-box}html,body{width:100%%;min-width:0}body{overflow-wrap:anywhere;font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:auto;padding:1rem;color:#182230}table{border-collapse:collapse;width:100%%}.stats-table{min-width:700px}.stats-table td,.stats-table th{white-space:nowrap}td,th{border:1px solid #98a2b3;padding:.4rem;text-align:left}svg{width:100%%;max-width:min(100%%,600px);height:auto;fill:#4179aa}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f7;padding:1rem}input{font:inherit;padding:.4rem;max-width:95%%}.scroll{overflow:auto;max-width:100%%;min-width:0}@media print{input{display:none}section{break-inside:avoid}}</style></head><body><h1>메쉬 품질 보고서</h1><nav><a href="#stats">통계</a> · <a href="#hist">분포</a> · <a href="#bad">위반 요소</a> · <a href="#meta">설정 및 출처</a></nav><p>생성 완료 · 품질 상태: %s · 노드 %d개 · 삼각형 %d개 중 기준 위반 요소 %d개 (%s), 통과 %s (여러 기준의 합집합). 품질 기준은 전자기 해석 정확도 보증이 아닙니다.</p><h2 id="stats">품질 통계</h2><p>Radius ratio는 Gmsh 내장 gamma 지표입니다.</p><div class="scroll"><table class="stats-table"><thead><tr><th>지표</th><th>기준</th><th>방향</th><th>최소</th><th>평균</th><th>최대</th><th>통과율</th><th>위반 수</th></tr></thead><tbody>%s</tbody></table></div><h2 id="hist">분포</h2>%s<h2 id="bad">기준 위반 요소</h2><label for="filter">요소 ID 또는 지표 검색</label> <input id="filter" type="search"> <label for="metric">위반 지표</label> <select id="metric"><option value="">전체</option><option>ICN</option><option>IGE</option><option>Aspect ratio</option><option>최소각 (°)</option><option>Radius ratio</option></select><div class="scroll"><table><thead><tr><th>NAS 요소 ID</th><th>위반 지표</th><th>활성 지표 값</th></tr></thead><tbody id="badrows">%s</tbody></table></div><h2 id="meta">설정 및 출처</h2><pre>%s</pre><pre>%s</pre><script>function filterRows(){const q=document.getElementById('filter').value.toLowerCase(),m=document.getElementById('metric').value;for(const r of document.querySelectorAll('#badrows tr'))r.hidden=!r.textContent.toLowerCase().includes(q)||(m&&!r.dataset.metrics.split('|').includes(m))}document.getElementById('filter').addEventListener('input',filterRows);document.getElementById('metric').addEventListener('change',filterRows);</script></body></html>''' % (('평가하지 않음 (활성 지표 없음)' if not any(d[1] for d in definitions) else ('기준 위반' if union.any() else '활성 기준 통과')), len(mesh.node_ids), len(mesh.element_ids),int(union.sum()), (f'{100*float(union.mean()):.2f}%' if any(d[1] for d in definitions) else '평가하지 않음'), (f'{100*(1-float(union.mean())):.2f}%' if any(d[1] for d in definitions) else '평가하지 않음'),''.join(rows),''.join(charts),''.join(bad_rows),metadata,config_text)
    path.write_text(document, encoding='utf-8')
    return summary
