"""Harvest Passports: an evolving internal case record from preparation to transfer.

Not a permit, FairWild certificate, validated harvest quota, or assurance of legal compliance or product safety.
Prefilled facts come from the science engine and public sources and are labelled with their provenance;
everything only the user can know (dates, quantities, documents, buyers, private sites) is user-supplied.
"""
from __future__ import annotations

import json
import time

from .. import catalog, eligibility as el, media, spatial, taxonomy
from . import ledger
from .db import LOCK, OpsError, audit, conn, ensure, loads, nid, rows
from .tasks import add_task, list_tasks

NOT_A_PERMIT = ("A Harvest Passport is an internal evidence and traceability record. It is not a government permit, "
                "a FairWild certificate, a validated local harvest quota, or an assurance of legal compliance or product safety.")

FLOW = ["draft", "evidence-review", "planned", "collected", "processing", "quality-review",
        "ready-for-authorised-human-review", "transferred", "closed"]
SIDE = ["blocked", "needs-review", "quarantined"]
TRANSITIONS = {
    ("draft", "evidence-review"): ("collector", "manager", "admin"),
    ("evidence-review", "planned"): ("manager", "scientific-reviewer", "admin"),
    ("planned", "collected"): ("collector", "manager", "admin"),
    ("collected", "processing"): ("manager", "admin"),
    ("processing", "quality-review"): ("manager", "quality-reviewer", "admin"),
    ("quality-review", "ready-for-authorised-human-review"): ("quality-reviewer", "admin"),
    ("ready-for-authorised-human-review", "transferred"): ("manager", "admin"),
    ("transferred", "closed"): ("manager", "admin"),
}
STAGE_LABEL = {
    "draft": "Draft", "evidence-review": "Evidence review", "planned": "Planned", "collected": "Collected",
    "processing": "Processing", "quality-review": "Quality review",
    "ready-for-authorised-human-review": "Ready for authorised human review", "transferred": "Transferred", "closed": "Closed",
    "blocked": "Blocked", "needs-review": "Needs review", "quarantined": "Quarantined",
}
ORGANS = ["rhizome", "root", "bark", "leaf", "flower", "fruit", "seed", "resin", "whole plant", "stem", "bulb/tuber"]

EVIDENCE_TASKS = {
    "identity_verified": ("Verify species identity with a voucher specimen", "scientific-reviewer", True, "planned",
                          "Look-alike and synonym confusion is common in medicinal plant trade (e.g. Nardostachys jatamansi vs "
                          "Valeriana jatamansi). A voucher checked by a botanist is needed before collection is planned."),
    "site_rights": ("Confirm collection rights and community consent (FPIC) for the site", "manager", True, "planned",
                    "Record who holds rights to the land and resource, and the consent of the community whose resource or "
                    "knowledge is involved. EthnoHarvest cannot verify rights; a person must."),
    "local_stage_counts": ("Count plants by life stage on permanent plots at the site", "scientific-reviewer", False, "planned",
                           "Published models describe other populations. Without local stage counts there is no basis for any "
                           "site-specific harvest amount."),
    "harvest_yield": ("Measure harvestable yield per plant at the site", "collector", False, "planned",
                      "Needed to relate a harvested mass to the number of plants affected."),
    "post_harvest_recovery": ("Set up monitoring of harvested and unharvested plants", "scientific-reviewer", False, "transferred",
                              "Survival and regrowth after harvest, compared with untouched controls, over several years."),
    "expert_threshold": ("Agree a local review threshold with a qualified ecologist", "scientific-reviewer", False, "planned",
                         "Any local harvest limit must come from site evidence and expert review, not from this software."),
}


def _visible(p: dict, role: str) -> dict:
    p = loads(dict(p), "prefill", "fields", "region_public")
    if role not in ("manager", "admin"):
        p["private_locality"] = "restricted (visible to managers)" if p.get("private_locality") else None
    p["status_label"] = STAGE_LABEL.get(p["status"], p["status"])
    return p


def _get(c, ws: str, pid: str) -> dict:
    r = c.execute("SELECT * FROM ops_passport WHERE id=? AND workspace=?", (pid, ws)).fetchone()
    if not r:
        raise OpsError(404, "passport not found in this workspace")
    return dict(r)


def _event(c, pid, role, kind, frm=None, to=None, note=None, data=None):
    c.execute("INSERT INTO ops_passport_event VALUES (?,?,?,?,?,?,?,?,?)",
              (nid("pev"), pid, time.time(), role, kind, frm, to, note, json.dumps(data or {}, default=str)))


def prefill(species: str, organ: str | None, region_label: str | None) -> dict:
    """Everything knowable from public sources, each value tagged with provenance."""
    prof = catalog.species_profile(species)
    try:
        tx = taxonomy.resolve(species)
    except Exception:
        tx = {}
    accepted = tx.get("accepted") or (prof or {}).get("name") or species
    studies = (prof or {}).get("harvest_studies") or []
    organ_src = "user-supplied"
    if not organ and studies:
        organ, organ_src = studies[0]["organ"], f"documented organ in {studies[0]['id']}"
    a = el.assess(accepted, region={"provided": True} if region_label else None)
    try:
        cites = spatial.cites_status(accepted)
        cites = {k: cites.get(k) for k in ("status", "listed", "appendices", "annotation", "url", "caveat")}
    except Exception as e:
        cites = {"status": "unavailable", "reason": type(e).__name__}
    try:
        img = media.species_image(accepted)
        photo = {k: img.get(k) for k in ("status", "url", "licence", "attribution", "attribution_url", "source", "reason")}
    except Exception:
        photo = {"status": "none", "reason": "photo service unavailable"}
    tag = lambda v, prov, src=None: {"value": v, "provenance": prov, "source": src}  # noqa: E731
    return {
        "accepted_name": tag(accepted, "prefilled-source", "GBIF backbone + COMPADRE 6.26.3.0"),
        "family": tag((prof or {}).get("family"), "prefilled-source", "COMPADRE"),
        "growth_form": tag((prof or {}).get("organism_type"), "prefilled-source", "COMPADRE OrganismType"),
        "organ": tag(organ, "prefilled-source" if organ_src != "user-supplied" else "user-supplied", organ_src),
        "evidence_tier": tag(a["overall_tier"], "prefilled-source", "eligibility-1.0 (deterministic rules)"),
        "quota_answer": tag(a["quota_answer"], "prefilled-source", "eligibility-1.0: no local quota without site evidence"),
        "studies": tag([{k: s[k] for k in ("id", "design", "organ", "citation")} for s in studies], "prefilled-source", "audited COMPADRE harvest studies"),
        "cites": tag(cites, "prefilled-source", "CITES Species+ (trade listing, not collection permission)"),
        "photo": tag(photo, "prefilled-source", photo.get("source")),
        "missing_local_evidence": tag(a["tasks"]["local_quota"]["missing"], "prefilled-source", "eligibility-1.0"),
        "in_catalog": bool(prof),
    }


def create(ws: str, role: str, *, species: str, organ: str | None, activity: str | None, region_label: str | None,
           region_public: dict | None, jurisdiction: str | None, private_locality: str | None = None, synthetic: bool = False) -> dict:
    ensure()
    if role not in ("collector", "manager", "admin"):
        raise OpsError(403, "only collectors, managers or admins open passports")
    if ws == "demo" and not synthetic:
        synthetic = True  # the demo workspace only ever holds synthetic material
    pf = prefill(species, organ, region_label)
    organ = pf["organ"]["value"]
    pid = nid("hp")
    now = time.time()
    with LOCK, conn() as c:
        n = c.execute("SELECT COUNT(*) FROM ops_passport WHERE workspace=?", (ws,)).fetchone()[0] + 1
        code = f"{'DEMO-' if synthetic else ''}EH-{1000 + n}"
        fields = {"activity": {"value": activity, "provenance": "user-supplied"}, "jurisdiction": {"value": jurisdiction, "provenance": "user-supplied"},
                  "region": {"value": region_label, "provenance": "user-supplied"}}
        c.execute("INSERT INTO ops_passport VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, ws, code, species, pf["accepted_name"]["value"], None, organ, activity, region_label,
                   json.dumps(region_public) if region_public else None, private_locality, jurisdiction, "draft", None,
                   json.dumps(pf, default=str), json.dumps(fields), int(synthetic), now, now))
        _event(c, pid, role, "created", None, "draft", "passport opened with prefilled scientific context")
        for key, (title, owner, blocking, phase, why) in EVIDENCE_TASKS.items():
            add_task(c, ws, pid, title, why, kind="evidence", phase=phase, blocking=blocking, owner_role=owner,
                     source="eligibility-1.0 local evidence gap", dedupe=f"ev:{key}")
        add_task(c, ws, pid, "Upload the collection authorisation and confirm it with the issuing authority",
                 "EthnoHarvest can read a document and check dates, species, organ and quantities against your records, but "
                 "only the issuing authority can confirm that a permit is genuine and valid.", kind="authorisation",
                 phase="planned", blocking=True, owner_role="manager", source="HarvestOps preparation checklist", dedupe="auth:upload")
        if pf["cites"]["value"].get("listed"):
            add_task(c, ws, pid, "Screen CITES applicability before any cross-border trade",
                     f"Listed in CITES Appendix {', '.join(pf['cites']['value'].get('appendices') or []) or '?'}. Whether a permit is needed "
                     "depends on the product type, annotation and countries; confirm with the CITES Management Authority.",
                     kind="regulatory", phase="transferred", blocking=True, owner_role="manager", source="CITES Species+", dedupe="cites:screen")
        audit(c, ws, role, "passport", pid, "create", {"species": species, "organ": organ, "synthetic": synthetic})
    _trigger(ws, pid, "passport_created")
    return detail(ws, role, pid)


def _trigger(ws, pid, event):
    """Hand the event to the HarvestOps agent workflow if it is available (Phase 5)."""
    try:
        from . import workflow
        workflow.trigger(ws, pid, event)
    except ImportError:
        pass


def _blocking_open(c, ws, pid, target):
    idx = FLOW.index(target)
    out = []
    for t in rows(c.execute("SELECT * FROM ops_task WHERE workspace=? AND passport_id=? AND blocking=1 AND status IN ('open','in-review')", (ws, pid))):
        if t["phase"] in FLOW and FLOW.index(t["phase"]) <= idx:
            out.append(t)
    return out


def transition(ws: str, role: str, pid: str, to: str, note: str | None = None) -> dict:
    ensure()
    with LOCK, conn() as c:
        p = _get(c, ws, pid)
        frm = p["status"]
        if to in SIDE:
            if not note or len(note.strip()) < 5:
                raise OpsError(422, f"moving to {to} needs a written reason")
            if to == "quarantined" and role not in ("quality-reviewer", "manager", "admin"):
                raise OpsError(403, "quarantine is set by a quality reviewer or manager")
            c.execute("UPDATE ops_passport SET status=?, prev_status=?, updated=? WHERE id=?", (to, frm if frm not in SIDE else p["prev_status"], time.time(), pid))
            _event(c, pid, role, "status", frm, to, note)
            audit(c, ws, role, "passport", pid, f"status:{to}", {"from": frm, "note": note})
            return detail(ws, role, pid, c=c)
        if frm in SIDE:
            if role not in ("manager", "admin"):
                raise OpsError(403, "a manager resumes a blocked, quarantined or needs-review passport")
            if to != p["prev_status"]:
                raise OpsError(409, f"resume to the previous stage ({p['prev_status']}) first")
            c.execute("UPDATE ops_passport SET status=?, prev_status=NULL, updated=? WHERE id=?", (to, time.time(), pid))
            _event(c, pid, role, "status", frm, to, note or "resumed")
            audit(c, ws, role, "passport", pid, f"status:{to}", {"from": frm})
            return detail(ws, role, pid, c=c)
        allowed = TRANSITIONS.get((frm, to))
        if not allowed:
            raise OpsError(409, f"cannot move from {STAGE_LABEL.get(frm, frm)} to {STAGE_LABEL.get(to, to)}")
        if role not in allowed:
            raise OpsError(403, f"{role} cannot move a passport to {STAGE_LABEL[to]} (allowed: {', '.join(allowed)})")
        block = _blocking_open(c, ws, pid, to)
        if block:
            raise OpsError(409, "resolve or waive first: " + "; ".join(t["title"] for t in block[:4]))
        guard = _guard(c, ws, pid, to)
        if guard:
            raise OpsError(409, guard)
        c.execute("UPDATE ops_passport SET status=?, updated=? WHERE id=?", (to, time.time(), pid))
        _event(c, pid, role, "status", frm, to, note)
        audit(c, ws, role, "passport", pid, f"status:{to}", {"from": frm, "note": note})
        return detail(ws, role, pid, c=c)


def _guard(c, ws, pid, to) -> str | None:
    q = lambda sql: c.execute(sql, (ws, pid)).fetchone()[0]  # noqa: E731
    if to == "collected" and not q("SELECT COUNT(*) FROM ops_harvest_event WHERE workspace=? AND passport_id=?"):
        return "record at least one collection event first"
    if to == "quality-review" and not q("SELECT COUNT(*) FROM ops_processing WHERE workspace=? AND passport_id=?"):
        return "record the processing (e.g. drying) of the collected material first"
    if to == "ready-for-authorised-human-review":
        if not q("SELECT COUNT(*) FROM ops_quality_test t JOIN ops_lot l ON l.id=t.lot_id WHERE l.workspace=? AND l.passport_id=?"):
            return "link at least one laboratory result to a lot first"
    if to == "transferred":
        if not q("SELECT COUNT(*) FROM ops_shipment WHERE workspace=? AND passport_id=?"):
            return "prepare a shipment first"
        if not q("SELECT COUNT(*) FROM ops_review WHERE workspace=? AND passport_id=? AND target='transfer' AND decision='approve'"):
            return "an authorised person must record their transfer decision first"
    return None


# ------------------------------------------------------------------ field operations
def _plus_months(date: str, months: int) -> str | None:
    try:
        y, m, d = (int(x) for x in str(date)[:10].split("-"))
    except ValueError:
        return None
    y, m = y + (m - 1 + months) // 12, (m - 1 + months) % 12 + 1
    return f"{y:04d}-{m:02d}-{min(d, 28):02d}"


def exceptions(ws: str, queue: list[dict], lots: list[dict], codes: dict[str, str]) -> list[dict]:
    """Everything that needs a person, most severe first: open document issues, blocking or overdue tasks, lots on hold."""
    today = time.strftime("%Y-%m-%d")
    out = []
    with conn() as c:
        for i in rows(c.execute("SELECT id, passport_id, severity, message FROM ops_issue WHERE workspace=? AND status='open'", (ws,))):
            out.append({"kind": "document issue", "severity": 3 if i.get("severity") == "mismatch" else 2,
                        "title": i.get("message") or "document issue", "passport_id": i["passport_id"], "ref": i["id"]})
    for t in queue:
        overdue = bool(t.get("due")) and t["due"] < today
        if t["blocking"] or overdue:
            out.append({"kind": "overdue task" if overdue else "blocking task", "severity": 3 if t["blocking"] else 2, "title": t["title"],
                        "passport_id": t["passport_id"], "ref": t["id"], "due": t.get("due")})
    for l in lots:
        if l["status"] == "quarantined":
            out.append({"kind": "lot on hold", "severity": 3, "title": f"Lot {l['code']} is on hold", "passport_id": l.get("passport_id"), "ref": l["id"]})
    for e in out:
        e["passport"] = codes.get(e["passport_id"] or "", None)
    return sorted(out, key=lambda e: -e["severity"])


def record_harvest(ws, role, pid, *, idem, collector, date, qty, unit, basis, lot_code, site_ref=None, note=None):
    if role not in ("collector", "manager", "admin"):
        raise OpsError(403, "collection events are recorded by collectors or managers")
    ensure()
    with conn() as c:
        p = _get(c, ws, pid)
    r = ledger.receive(ws, role, idem, lot_code=lot_code, basis=basis, qty=qty, unit=unit, passport_id=pid, species=p["accepted_name"],
                       organ=p["organ"], storage="collection point", reason=f"collected by {collector} on {date}", synthetic=p["synthetic"])
    if not r.get("replayed"):
        with LOCK, conn() as c:
            c.execute("INSERT INTO ops_harvest_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (nid("hev"), ws, pid, r["lot"]["id"], collector, date, r["received_g"], qty, unit, basis, site_ref, note, p["synthetic"], time.time()))
            _event(c, pid, role, "harvest", note=f"{qty} {unit} {basis} {p['organ']} received into {lot_code}")
            from .tasks import add_task
            add_task(c, ws, pid, "Regeneration check at this collection site",
                     f"Revisit the site of {lot_code} and count seedlings, regrowth and survivors of harvested plants. The 12-month due date is a "
                     "scheduling default, not a recovery interval.", kind="monitoring", phase="monitor", owner_role="collector",
                     source="harvest follow-up", dedupe=f"regen:{lot_code}", due=_plus_months(date, 12))
    _trigger(ws, pid, "harvest_recorded")
    return r


QUALITY_OPS = {"<=": lambda a, b: a <= b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, ">": lambda a, b: a > b}


def add_quality_test(ws, role, *, lot_id, analyte, result, unit, criterion_op=None, criterion_value=None, criterion_source=None, source_doc=None):
    if role not in ("quality-reviewer", "manager", "admin"):
        raise OpsError(403, "laboratory results are linked by a quality reviewer or manager")
    ensure()
    if criterion_op and criterion_op not in QUALITY_OPS:
        raise OpsError(422, f"criterion operator must be one of {list(QUALITY_OPS)}")
    with LOCK, conn() as c:
        lot = c.execute("SELECT * FROM ops_lot WHERE id=? AND workspace=?", (lot_id, ws)).fetchone()
        if not lot:
            raise OpsError(404, "lot not found")
        if result is None:
            outcome = "missing-result"
        elif criterion_op is None or criterion_value is None:
            outcome = "no-documented-criterion"
        else:
            outcome = "within-criterion" if QUALITY_OPS[criterion_op](float(result), float(criterion_value)) else "outside-criterion"
        crit = f"{criterion_op} {criterion_value} {unit}" if criterion_op else None
        tid = nid("qt")
        c.execute("INSERT INTO ops_quality_test VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (tid, ws, lot_id, analyte, result, None, unit, crit, criterion_source, outcome, source_doc, time.time()))
        if outcome != "within-criterion":
            msg = {"outside-criterion": f"{analyte} = {result} {unit} is outside the documented criterion ({crit}; source: {criterion_source or 'not given'}).",
                   "missing-result": f"No result reported for {analyte}.",
                   "no-documented-criterion": f"{analyte} = {result} {unit}, but no acceptance criterion is documented, so it cannot be judged."}[outcome]
            add_task(c, ws, lot["passport_id"], f"Quality review: {analyte} for lot {lot['code']}", msg + " A quality reviewer decides; "
                     "EthnoHarvest does not certify safety or quality.", kind="quality", phase="ready-for-authorised-human-review",
                     blocking=True, owner_role="quality-reviewer", source=f"quality_test:{tid}", dedupe=f"qt:{lot_id}:{analyte}", lot_id=lot_id)
        audit(c, ws, role, "quality_test", tid, "create", {"lot": lot["code"], "analyte": analyte, "outcome": outcome})
        pid = lot["passport_id"]
    _trigger(ws, pid, "lab_result")
    return {"id": tid, "outcome": outcome, "criterion": crit}


def create_shipment(ws, role, pid, *, idem, lot_id, qty, unit, destination_country, cross_border: bool):
    if role not in ("manager", "admin"):
        raise OpsError(403, "shipments are prepared by a manager")
    ensure()
    sid = nid("shp")
    r = ledger.reserve(ws, role, idem, lot_id=lot_id, qty=qty, unit=unit, ref=sid)
    if r.get("replayed"):
        return r
    with LOCK, conn() as c:
        p = _get(c, ws, pid)
        open_tasks = rows(c.execute("SELECT title, kind FROM ops_task WHERE workspace=? AND passport_id=? AND status IN ('open','in-review')", (ws, pid)))
        lot = c.execute("SELECT * FROM ops_lot WHERE id=?", (lot_id,)).fetchone()
        checklist = [
            {"item": "Lot is not quarantined", "ok": lot["status"] != "quarantined"},
            {"item": "Species identity verified (voucher)", "ok": not any("identity" in t["title"] for t in open_tasks)},
            {"item": "Collection authorisation confirmed with issuer", "ok": not any(t["kind"] == "authorisation" for t in open_tasks)},
            {"item": "Quality review complete", "ok": not any(t["kind"] == "quality" for t in open_tasks)},
            {"item": "Reconciliation gaps explained", "ok": not any(t["kind"] == "reconciliation" for t in open_tasks)},
        ]
        pf = json.loads(p["prefill"] or "{}")
        listed = (pf.get("cites", {}).get("value") or {}).get("listed")
        if cross_border:
            checklist.append({"item": "CITES applicability screened (cross-border)", "ok": not any(t["kind"] == "regulatory" for t in open_tasks),
                              "note": "listed species" if listed else "not listed per Species+; confirm product scope"})
            if listed:
                add_task(c, ws, pid, "Screen CITES applicability before any cross-border trade",
                         "Cross-border shipment of a CITES-listed species. Check the annotation for this product type and confirm "
                         "requirements with the Management Authorities of both countries.", kind="regulatory", phase="transferred",
                         blocking=True, owner_role="manager", source="shipment", dedupe="cites:screen")
        c.execute("INSERT INTO ops_shipment VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, ws, pid, lot_id, r["balance"]["reserved_g"], destination_country, int(cross_border), "prepared",
                   json.dumps(checklist), time.time(), time.time()))
        _event(c, pid, role, "shipment", note=f"shipment prepared to {destination_country}; stock reserved")
        audit(c, ws, role, "shipment", sid, "create", {"lot": lot_id, "qty": qty, "unit": unit})
    _trigger(ws, pid, "shipment_proposed")
    return {"shipment_id": sid, "checklist": checklist, "reservation": r}


def review(ws, role, pid, *, target, decision, reason):
    if target == "transfer" and role not in ("manager", "admin"):
        raise OpsError(403, "the transfer decision is recorded by an authorised manager")
    if decision not in ("approve", "reject", "request-changes"):
        raise OpsError(422, "decision must be approve, reject or request-changes")
    if not reason or len(reason.strip()) < 5:
        raise OpsError(422, "a review decision needs a written reason")
    ensure()
    with LOCK, conn() as c:
        _get(c, ws, pid)
        rid = nid("rev")
        c.execute("INSERT INTO ops_review VALUES (?,?,?,?,?,?,?,?)", (rid, ws, pid, target, decision, reason, role, time.time()))
        _event(c, pid, role, "review", note=f"{target}: {decision} ({reason})")
        audit(c, ws, role, "review", rid, decision, {"target": target})
    return {"id": rid, "note": "Recorded as an internal human decision. It is not a permit or an official approval."}


# ------------------------------------------------------------------ views
def _with_fields(c, d: dict) -> dict:
    d["extraction"] = {**(d.get("extraction") or {}), "fields": rows(c.execute(
        "SELECT * FROM ops_field WHERE document_id=? ORDER BY page, name", (d["id"],)))}
    return d


def detail(ws: str, role: str, pid: str, c=None) -> dict:
    ensure()
    own = c is None
    c = c or conn()
    try:
        p = _visible(_get(c, ws, pid), role)
        tasks = rows(c.execute("SELECT * FROM ops_task WHERE workspace=? AND passport_id=? ORDER BY blocking DESC, created", (ws, pid)))
        open_t = [t for t in tasks if t["status"] in ("open", "in-review")]
        nxt = sorted(open_t, key=lambda t: (FLOW.index(t["phase"]) if t["phase"] in FLOW else 99, -t["blocking"]))[:3]
        lots = [ledger.lot_view(c, l) for l in rows(c.execute("SELECT * FROM ops_lot WHERE workspace=? AND passport_id=? ORDER BY created", (ws, pid)))]
        lot_ids = [l["id"] for l in lots] or [""]
        ph = ",".join("?" * len(lot_ids))
        out = p | {
            "flow": [{"id": s, "label": STAGE_LABEL[s], "state": ("done" if FLOW.index(s) < FLOW.index(p["status"]) else "current" if s == p["status"] else "todo")
                      if p["status"] in FLOW else ("current" if s == p["prev_status"] else "todo")} for s in FLOW],
            "allowed_next": [to for (frm, to), roles in TRANSITIONS.items() if frm == p["status"] and role in roles],
            "events": [loads(e, "data") for e in rows(c.execute("SELECT * FROM ops_passport_event WHERE passport_id=? ORDER BY ts", (pid,)))],
            "tasks": tasks, "next_actions": nxt, "lots": lots,
            "harvest_events": rows(c.execute("SELECT * FROM ops_harvest_event WHERE workspace=? AND passport_id=? ORDER BY created", (ws, pid))),
            "processing": rows(c.execute("SELECT * FROM ops_processing WHERE workspace=? AND passport_id=? ORDER BY created", (ws, pid))),
            "quality_tests": rows(c.execute(f"SELECT * FROM ops_quality_test WHERE lot_id IN ({ph}) ORDER BY created", lot_ids)),
            "shipments": [loads(s, "checklist") for s in rows(c.execute("SELECT * FROM ops_shipment WHERE workspace=? AND passport_id=?", (ws, pid)))],
            "reviews": rows(c.execute("SELECT * FROM ops_review WHERE workspace=? AND passport_id=? ORDER BY ts", (ws, pid))),
            "documents": [_with_fields(c, loads(d, "extraction")) for d in rows(c.execute(
                "SELECT id, filename, sha256, doc_kind, kind_confidence, status, pages, created, synthetic_marked, issuer_verification, version, extraction "
                "FROM ops_document WHERE workspace=? AND passport_id=? ORDER BY created DESC", (ws, pid)))],
            "issues": [loads(i, "evidence") for i in rows(c.execute("SELECT * FROM ops_issue WHERE workspace=? AND passport_id=? ORDER BY created", (ws, pid)))],
            "not_a_permit": NOT_A_PERMIT,
        }
        out["audit_trail"] = [loads(a, "data") for a in rows(c.execute(
            "SELECT * FROM ops_audit WHERE workspace=? AND (entity_id=? OR data LIKE ?) ORDER BY seq DESC LIMIT 40", (ws, pid, f'%{pid}%')))]
        return out
    finally:
        if own:
            c.close()


def list_passports(ws: str, role: str) -> list[dict]:
    ensure()
    with conn() as c:
        ps = [_visible(p, role) for p in rows(c.execute("SELECT * FROM ops_passport WHERE workspace=? ORDER BY updated DESC", (ws,)))]
        for p in ps:
            p["open_tasks"] = c.execute("SELECT COUNT(*) FROM ops_task WHERE passport_id=? AND status IN ('open','in-review')", (p["id"],)).fetchone()[0]
            p["open_issues"] = c.execute("SELECT COUNT(*) FROM ops_issue WHERE passport_id=? AND status='open'", (p["id"],)).fetchone()[0]
            p.pop("prefill", None)
        return ps


def overview(ws: str, role: str) -> dict:
    ensure()
    ps = list_passports(ws, role)
    queue = [t for t in list_tasks(ws) if t["status"] in ("open", "in-review")]
    mine = [t for t in queue if t["owner_role"] == role]
    inv = ledger.inventory(ws)
    with conn() as c:
        recent = [loads(a, "data") for a in rows(c.execute("SELECT * FROM ops_audit WHERE workspace=? ORDER BY seq DESC LIMIT 15", (ws,)))]
        expiring = rows(c.execute(
            "SELECT f.value, f.normalised, d.filename, d.passport_id FROM ops_field f JOIN ops_document d ON d.id=f.document_id "
            "WHERE d.workspace=? AND f.name='expiry_date' ORDER BY f.normalised", (ws,)))
    today = time.strftime("%Y-%m-%d")
    for t in queue:
        t["overdue"] = bool(t.get("due")) and t["due"] < today
    exc = exceptions(ws, queue, inv["lots"], {p["id"]: f"{p['code']} · {p['accepted_name']}" for p in ps})
    return {"passports": ps, "queue": queue[:40], "my_tasks": mine[:20], "inventory": inv, "recent": recent, "expiries": expiring,
            "exceptions": exc[:30],
            "counts": {"overdue": sum(t["overdue"] for t in queue), "exceptions": len(exc), "active_passports": sum(p["status"] not in ("closed",) for p in ps), "open_tasks": len(queue),
                       "blocking": sum(t["blocking"] for t in queue), "lots": len(inv["lots"]),
                       "quarantined_lots": sum(l["status"] == "quarantined" for l in inv["lots"])}}
