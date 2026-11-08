"""HarvestOps agent subgraph, recorded on the shared run store so the Evidence page can trace it.

Each run declares only the nodes that actually executed for that event (no decorative nodes), and every node's timing and
outputs are measured. Research runs do real work inside the nodes. Document and stock events are processed synchronously
inside the HTTP request; their runs record the measured results of that processing (marked `recorded_from: request`).
Set OPS_WORKFLOW=0 to disable (tests).
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback

from .. import store
from .db import LOCK, conn, rows

NODES = {
    "trigger": ("Event received", []),
    "taxonomy_match": ("Taxonomy and synonym match", ["trigger"]),
    "organ_specific_research": ("Organ-specific evidence (studies, guidance, literature)", ["taxonomy_match"]),
    "regulation_retrieve": ("Listings and jurisdiction rules", ["taxonomy_match"]),
    "science_gate": ("Science gate (eligibility-1.0)", ["organ_specific_research"]),
    "document_ingest": ("Document intake and validation", ["trigger"]),
    "extract": ("Field extraction with provenance", ["document_ingest"]),
    "cross_document_check": ("Cross-document checks", ["extract"]),
    "inventory_reconcile": ("Inventory reconciliation", ["trigger"]),
    "create_tasks": ("Create or close tasks", []),
    "human_review": ("Human review queue", ["create_tasks"]),
    "report": ("Passport updated", ["human_review"]),
    "agent_report": ("Evidence report", ["regulation_retrieve"]),
}


def _agent_nodes():
    from ..evidence_agent import COMPONENTS
    for c in COMPONENTS:
        NODES.setdefault(c["id"], (c["label"], c["after"][:1]))


def _last(pipe: list[str]) -> str:
    for n in ("jev_review_route", "conflict_check", "claim_verify", "extract_claims", "jev_triage", "retrieve"):
        if n in pipe:
            return n
    return pipe[-1]


def _define(rid: str, ids: list[str], parents_override: dict | None = None):
    defs = []
    for n in ids:
        label, parents = NODES[n]
        parents = (parents_override or {}).get(n, parents)
        defs.append({"id": n, "label": label, "parents": [x for x in parents if x in ids]})
    store.add_event(rid, "_graph", "definition", {"nodes": defs, "subgraph": "harvestops"})
    for n in ids:
        store.add_event(rid, n, "queued", {})


class Step:
    def __init__(self, rid, node, inputs=None):
        self.rid, self.node, self.inputs = rid, node, inputs or {}

    def __enter__(self):
        self.t0 = time.time()
        store.add_event(self.rid, self.node, "running", {"inputs": self.inputs})
        self.out, self.state, self.extra = {}, "completed", {}
        return self

    def __exit__(self, et, ev, tb):
        dur = round((time.time() - self.t0) * 1000, 1)
        if et:
            store.add_event(self.rid, self.node, "failed", {"outputs": {}, "duration_ms": dur, "error": f"{et.__name__}: {str(ev)[:300]}",
                                                            "traceback": "".join(traceback.format_tb(tb))[-600:]})
            return False
        store.add_event(self.rid, self.node, self.state, {"outputs": self.out, "duration_ms": dur, **self.extra})
        return False


def _pending_review(ws, pid) -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM ops_task WHERE workspace=? AND passport_id=? AND status IN ('open','in-review')", (ws, pid)).fetchone()[0]


def run_research(ws: str, p: dict, key: str) -> dict:
    """Research for one passport: taxonomy → organ evidence + regulations → science gate → tasks → review → report."""
    from . import cautions as C
    from .tasks import add_task
    pid = p["id"]
    rid = store.create_run("harvestops", f"{p['code']} · research · {p['accepted_name']} {p['organ']}",
                           {"passport_id": pid, "event": "research", "species": p["accepted_name"], "organ": p["organ"],
                            "jurisdiction": p["jurisdiction"], "workspace": ws})
    from .. import evidence_agent as EA
    _agent_nodes()
    agent_on = os.environ.get("OPS_LITERATURE", "1") != "0"
    agent_ids = EA.normalise_pipeline(None)[0] if agent_on else []
    ids = ["trigger", "taxonomy_match", "organ_specific_research", "regulation_retrieve", "science_gate",
           *agent_ids, "create_tasks", "human_review", "report"]
    _define(rid, ids, {**EA.graph_parents(agent_ids),
                       "create_tasks": ["science_gate", "regulation_retrieve", _last(agent_ids) if agent_ids else "science_gate"]})
    pf = json.loads(p["prefill"] or "{}")
    body = None
    try:
        with Step(rid, "trigger", {"event": "research", "passport": p["code"]}) as s:
            s.out = {"passport": p["code"], "species": p["species"], "organ": p["organ"], "jurisdiction": p["jurisdiction"]}
        with Step(rid, "taxonomy_match", {"name": p["species"]}) as s:
            from .documents import SYNONYMS, organ_parts
            syn = [k for k, v in SYNONYMS.items() if v == p["accepted_name"]]
            for x in pf.get("synonyms", {}).get("value") or []:
                if x not in syn:
                    syn.append(x)
            s.out = {"accepted": p["accepted_name"], "known_synonyms": syn, "organ_parts": sorted(organ_parts(p["organ"])),
                     "source": (pf.get("accepted_name") or {}).get("source")}
        with Step(rid, "organ_specific_research", {"species": p["accepted_name"], "organ": p["organ"]}) as s:
            ev = C.study_cards(p["accepted_name"], p["organ"]) + C.guidance_cards(p["accepted_name"], p["organ"])
            s.out = {"cards": [{"issue": c["issue"], "evidence_kind": c["evidence_kind"]} for c in ev]}
        with Step(rid, "regulation_retrieve", {"jurisdiction": p["jurisdiction"], "cites": (pf.get("cites") or {}).get("value", {}).get("status")}) as s:
            reg = C.regulation_cards(p["accepted_name"], p["organ"], p["jurisdiction"], (pf.get("cites") or {}).get("value"))
            s.out = {"cards": [{"issue": c["issue"], "evidence_kind": c["evidence_kind"], "scope": c["scope"]} for c in reg]}
        with Step(rid, "science_gate", {"ruleset": "eligibility-1.0"}) as s:
            s.out = {"quota_answer": (pf.get("quota_answer") or {}).get("value"), "evidence_tier": (pf.get("evidence_tier") or {}).get("value"),
                     "missing_local_evidence": len((pf.get("missing_local_evidence") or {}).get("value") or []),
                     "note": "Cautions never produce a harvest limit; the gate is unchanged by research results."}
        agent, note = None, "literature agent disabled"
        if agent_on:
            from .. import evidence_agent
            agent = evidence_agent.run(p["accepted_name"], p["organ"], syn, run_id=rid,
                                       step=lambda node, inputs=None: Step(rid, node, inputs))
            ev += C.agent_cards(agent, p["organ"])
            note = f"{agent['retrieval']['retrieved']} records searched, {agent['triage']['jev_calls']} read by JEV"
        order = C.ORDER
        cards = sorted(ev + reg, key=lambda c: order.index(c["evidence_kind"]))
        with Step(rid, "create_tasks", {"cards": len(cards)}) as s:
            created = []
            with LOCK, conn() as c:
                for cd in cards:
                    if cd["evidence_kind"] == "requires-authority-confirmation":
                        t = add_task(c, ws, pid, f"Confirm with the authority: {cd['issue']}", cd["recommended_next"], kind="regulatory",
                                     phase="planned", blocking=False, owner_role="manager", source=f"cautions:{cd['id']}", dedupe=f"caution:{cd['id']}")
                        if t:
                            created.append(cd["issue"])
                    if cd["evidence_kind"] == "needs-review":
                        t = add_task(c, ws, pid, f"Read and confirm: {cd['issue']}", cd["recommended_next"], kind="evidence",
                                     phase="evidence-review", blocking=False, owner_role="scientific-reviewer", source=f"cautions:{cd['id']}",
                                     dedupe=f"caution:{cd['id']}")
                        if t:
                            created.append("expert review of AI findings")
            s.out = {"tasks_created": created}
        with Step(rid, "human_review", {}) as s:
            s.out = {"cards_awaiting_expert_review": len(cards), "open_tasks": _pending_review(ws, pid)}
        body = {"status": "ok", "ruleset": C.RULESET, "cards": cards, "literature": note, "generated": time.time(),
                "agent": C.agent_summary(agent)}
        with Step(rid, "report", {}) as s:
            s.out = {"cards": len(cards), "by_kind": {k: sum(c["evidence_kind"] == k for c in cards) for k in order if any(c["evidence_kind"] == k for c in cards)}}
        C.save(key, p["accepted_name"], p["organ"], p["jurisdiction"], body, rid)
        store.finish_run(rid, "completed", {"passport_id": pid, "cards": len(cards)})
    except Exception as e:  # noqa: BLE001
        store.finish_run(rid, "failed", error=f"{type(e).__name__}: {e}")
        return {"status": f"research failed: {type(e).__name__}", "cards": [], "run_id": rid}
    return {**body, "run_id": rid, "cached": False}


def record_documents(ws: str, pid: str, event: str):
    """Trace for a document upload: the work already ran in the request; this run records its measured results."""
    with conn() as c:
        p = dict(c.execute("SELECT code, accepted_name FROM ops_passport WHERE id=?", (pid,)).fetchone())
        d = c.execute("SELECT * FROM ops_document WHERE workspace=? AND passport_id=? ORDER BY created DESC LIMIT 1", (ws, pid)).fetchone()
        d = dict(d) if d else None
        fields = rows(c.execute("SELECT name, method, confidence, page FROM ops_field WHERE document_id=?", (d["id"],))) if d else []
        issues = rows(c.execute("SELECT rule, severity FROM ops_issue WHERE workspace=? AND passport_id=?", (ws, pid)))
        tasks = rows(c.execute("SELECT title, status FROM ops_task WHERE workspace=? AND passport_id=? AND kind='document'", (ws, pid)))
    rid = store.create_run("harvestops", f"{p['code']} · document · {d['filename'] if d else '?'}",
                           {"passport_id": pid, "event": event, "workspace": ws, "recorded_from": "request"})
    ids = ["trigger", "document_ingest", "extract", "cross_document_check", "create_tasks", "human_review", "report"]
    _define(rid, ids, {"create_tasks": ["cross_document_check"]})
    note = {"recorded_from": "request"}
    with Step(rid, "trigger", {"event": event}) as s:
        s.out = {"passport": p["code"]}
    with Step(rid, "document_ingest", {"filename": d and d["filename"]}) as s:
        s.out = {"sha256": d and d["sha256"][:16], "status": d and d["status"], "pages": d and d["pages"], "synthetic_marked": d and d["synthetic_marked"]}
        s.extra = {**note, "measured_ms": d and d["latency_ms"]}
    with Step(rid, "extract", {"kind": d and d["doc_kind"]}) as s:
        s.out = {"fields": len(fields), "methods": sorted({f["method"] for f in fields}), "kind": d and d["doc_kind"]}
        s.extra = note
        if d and d["status"] in ("needs-ocr", "rejected"):
            s.state = "blocked"
    with Step(rid, "cross_document_check", {"documents": "all on passport"}) as s:
        s.out = {"issues": [f"{i['rule']} ({i['severity']})" for i in issues]}
        s.extra = note
    with Step(rid, "create_tasks", {}) as s:
        s.out = {"document_tasks": [f"{t['title'][:80]} [{t['status']}]" for t in tasks]}
        s.extra = note
    with Step(rid, "human_review", {}) as s:
        s.out = {"open_tasks": _pending_review(ws, pid), "note": "Every finding waits for a person; nothing is auto-approved."}
    with Step(rid, "report", {}) as s:
        s.out = {"issues": len(issues)}
    store.finish_run(rid, "completed", {"passport_id": pid, "issues": len(issues)})


def record_stock(ws: str, pid: str, event: str):
    from .ledger import reconciliation
    with conn() as c:
        p = dict(c.execute("SELECT code FROM ops_passport WHERE id=?", (pid,)).fetchone())
    rid = store.create_run("harvestops", f"{p['code']} · {event.replace('_', ' ')}", {"passport_id": pid, "event": event, "workspace": ws})
    ids = ["trigger", "inventory_reconcile", "create_tasks", "human_review", "report"]
    _define(rid, ids, {"create_tasks": ["inventory_reconcile"]})
    with Step(rid, "trigger", {"event": event}) as s:
        s.out = {"passport": p["code"]}
    with Step(rid, "inventory_reconcile", {}) as s:
        r = reconciliation(ws, pid)
        s.out = {"unexplained_total_kg": round(r.get("unexplained_total_g", 0) / 1000, 3), "per_basis": r.get("per_basis")}
    with Step(rid, "create_tasks", {}) as s:
        with conn() as c:
            s.out = {"open_reconciliation_tasks": c.execute("SELECT COUNT(*) FROM ops_task WHERE workspace=? AND passport_id=? AND kind='reconciliation' "
                                                             "AND status IN ('open','in-review')", (ws, pid)).fetchone()[0]}
    with Step(rid, "human_review", {}) as s:
        s.out = {"open_tasks": _pending_review(ws, pid)}
    with Step(rid, "report", {}) as s:
        s.out = {"ok": True}
    store.finish_run(rid, "completed", {"passport_id": pid})


def _run_safely(fn, *a):
    try:
        fn(*a)
    except Exception:  # noqa: BLE001 - tracing must never break the operation that triggered it
        pass


def trigger(ws: str, pid: str, event: str):
    if os.environ.get("OPS_WORKFLOW", "1") == "0":
        return
    if event == "passport_created":
        def research():
            from .cautions import cautions_for
            cautions_for(ws, "manager", pid, refresh=False)
        threading.Thread(target=_run_safely, args=(research,), daemon=True).start()
    elif event == "document_uploaded":
        _run_safely(record_documents, ws, pid, event)
    elif event in ("harvest_recorded", "batch_processed"):
        _run_safely(record_stock, ws, pid, event)


def start_evidence_run(species: str, organ: str, jurisdiction: str | None = None, inject: set | None = None,
                       pipeline: list[str] | None = None) -> str:
    """Standalone Harvest Evidence Agent run (no passport): used by the Evidence page workflow builder and Harvest Methods.

    `pipeline` is the list of optional components the user kept in the builder (None = all). Returns the run id at once;
    the agent runs in a background thread and its events stream over SSE.
    """
    from .. import evidence_agent, taxonomy
    from . import cautions as C
    from .documents import SYNONYMS
    _agent_nodes()
    pipe, notes = evidence_agent.normalise_pipeline(pipeline)
    rid = store.create_run("harvestops", f"Evidence agent · {species} · {organ}",
                           {"event": "evidence-agent", "species": species, "organ": organ, "jurisdiction": jurisdiction,
                            "inject": sorted(inject or []), "pipeline": pipe, "pipeline_notes": notes})
    ids = ["trigger", "taxonomy_match", *pipe, "regulation_retrieve", "agent_report"]
    _define(rid, ids, {**evidence_agent.graph_parents(pipe), "regulation_retrieve": ["taxonomy_match"],
                       "agent_report": [_last(pipe), "regulation_retrieve", *(["stochastic_lambda"] if "stochastic_lambda" in pipe else []),
                                        *[c for c in pipe if c in evidence_agent.CONTEXT_IDS]]})

    def work():
        try:
            with Step(rid, "trigger", {"species": species, "organ": organ, "jurisdiction": jurisdiction}) as s:
                s.out = {"event": "evidence-agent"}
            with Step(rid, "taxonomy_match", {"name": species}) as s:
                try:
                    t = taxonomy.resolve(species) or {}
                except Exception:  # noqa: BLE001
                    t = {}
                accepted = t.get("accepted") or species
                syn = [k for k, v in SYNONYMS.items() if v == accepted]
                s.out = {"accepted": accepted, "status": t.get("status"), "synonyms": syn}
            agent = evidence_agent.run(accepted, organ, syn, run_id=rid, step=lambda node, inputs=None: Step(rid, node, inputs),
                                       inject=inject or set(), pipeline=pipe)
            with Step(rid, "regulation_retrieve", {"jurisdiction": jurisdiction}) as s:
                from .. import spatial
                try:
                    cites = spatial.cites_status(accepted)
                except Exception:  # noqa: BLE001
                    cites = {"status": "error", "reason": "lookup failed"}
                reg = C.regulation_cards(accepted, organ, jurisdiction, cites)
                s.out = {"cards": [{"issue": c["issue"], "evidence_kind": c["evidence_kind"]} for c in reg]}
            cards = sorted(C.agent_cards(agent, organ) + C.study_cards(accepted, organ) + reg, key=lambda c: C.ORDER.index(c["evidence_kind"]))
            with Step(rid, "agent_report", {}) as s:
                s.out = {"cards": len(cards), "findings": len(agent["findings"])}
            store.finish_run(rid, "completed", {"agent": C.agent_summary(agent), "findings": agent["findings"], "cards": cards,
                                                "triage": agent["triage"]["items"], "sensitivity": agent["sensitivity"],
                                                "stochastic": agent["stochastic"], "verification": agent["verification"],
                                                "context": agent.get("context", {}), "pipeline": pipe, "pipeline_notes": notes})
        except Exception as e:  # noqa: BLE001
            store.finish_run(rid, "failed", error=f"{type(e).__name__}: {str(e)[:200]}")

    threading.Thread(target=work, daemon=True).start()
    return rid
