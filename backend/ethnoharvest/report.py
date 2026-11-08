"""Reproducible, source-backed assessment report (Markdown + printable HTML)."""
from __future__ import annotations

import html as H
import json
from datetime import datetime, timezone

from . import compadre, harvest as hv


def render(run: dict, events: list[dict], jev: list[dict]) -> tuple[str, str]:
    o = run.get("outputs") or {}
    env = o.get("envelope") or {}
    gate = o.get("gate") or {}
    dem = o.get("demography") or {}
    ex = o.get("explain") or {}
    inp = run.get("inputs") or {}
    sp = env.get("species") or inp.get("species") or "-"
    L = [f"# EthnoHarvest assessment: {sp}", "",
         f"- Run ID: `{run['id']}`  ",
         f"- Created: {datetime.fromtimestamp(run['created'], timezone.utc).isoformat(timespec='seconds')}  ",
         f"- Status: {run['status']}  ",
         f"- COMPADRE version: {compadre.VERSION}; eligibility rules: eligibility-1.0  ",
         f"- Geographic scope: {json.dumps(env.get('geographic_scope', inp.get('region') or 'study-only / not geolocated'))}", "",
         "## Evidence tier and harvest-rate answer", "",
         f"**Tier {gate.get('overall_tier', '?')}** · local harvest rate: **{gate.get('quota_answer', '?')}**", ""]
    for k, v in (gate.get("tasks") or {}).items():
        L.append(f"- `{k}`: {v['status']} - {'; '.join(v['reasons'])}" + (f" (missing: {'; '.join(v['missing'])})" if v["missing"] else ""))
    if dem.get("lambda"):
        L += ["", "## Demographic model", "", f"- Preset matrix {dem.get('preset_matrix')}: λ = {dem['lambda']:.4f} "
              f"(power-iteration check {dem['lambda_power_check']:.4f})"]
        for c in dem.get("comparisons", []):
            if "delta" in c:
                L.append(f"- Study `{c['study']}` ({c['design']}): mean λ control {c['mean_control']:.3f}, harvest {c['mean_treatment']:.3f}, Δ {c['delta']:+.3f}")
                s = hv.BY_ID.get(c["study"])
                if s:
                    L.append(f"  - Source: {s['citation']}")
    if ex.get("summary"):
        L += ["", "## Explanation (LLM, grounded on computed facts)", "", ex["summary"], ""]
        for n in ex.get("next_steps", []):
            L.append(f"- {n}")
        L.append(f"\n_Model: {ex.get('model') or 'template'}; ungrounded numbers flagged: {ex.get('ungrounded_numbers', [])}_")
    if jev:
        L += ["", "## JEV decisions", "", "| question | choice | confidence | accepted | action |", "|---|---|---|---|---|"]
        for j in jev:
            L.append(f"| {j['question']} | {j['choice']} | {j['confidence']:.2f} | {bool(j['accepted'])} | {j['action']} |")
    L += ["", "## Execution trace", "", "| node | state | duration ms | note |", "|---|---|---|---|"]
    for e in events:
        if e["state"] in ("queued", "running", "definition"):
            continue
        p = e["payload"]
        L.append(f"| {e['node']} | {e['state']} | {p.get('duration_ms', '')} | {str(p.get('why') or p.get('error') or '')[:120]} |")
    L += ["", "## Limits", "", "- Matrix projections describe studied populations; they are not forecasts for any local site.",
          "- No output of this report is a harvest permit, legal permission, quota or medicinal-efficacy claim.",
          "- Occurrence records are presence-only; suitability is not abundance.", ""]
    md = "\n".join(L)
    body = []
    for line in L:
        if line.startswith("# "):
            body.append(f"<h1>{H.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{H.escape(line[3:])}</h2>")
        elif line.startswith("|"):
            if set(line.replace("|", "").strip()) <= {"-"}:
                continue
            cells = [H.escape(c.strip()) for c in line.strip("|").split("|")]
            body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        elif line.startswith("- ") or line.startswith("  - "):
            body.append(f"<li>{H.escape(line.lstrip(' -'))}</li>")
        elif line:
            body.append(f"<p>{H.escape(line)}</p>")
    html = ("<!doctype html><meta charset=utf-8><title>EthnoHarvest report</title><style>body{font:15px/1.55 Georgia,serif;"
            "max-width:860px;margin:40px auto;padding:0 20px;color:#1d2a24}h1{font-size:28px}h2{margin-top:32px;border-bottom:1px solid #ccd;}"
            "td{border:1px solid #ccd;padding:4px 8px;font:13px system-ui}li{margin:3px 0}</style>"
            + "\n".join(b if not b.startswith("<tr>") else b for b in body).replace("</p>\n<tr>", "</p><table><tr>")
            + "</table>")
    return md, html
