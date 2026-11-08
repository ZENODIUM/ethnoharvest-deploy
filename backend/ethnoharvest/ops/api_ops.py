"""HarvestOps HTTP routes (/api/ops/*).

Demo access model: the client states its role (X-EH-Role) and workspace (X-EH-Workspace). Every permission is
checked here on the server. This is role separation for a demo workspace, not authentication; real accounts
are required before any real private documents are stored.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import documents, ledger, passport as pp, reports
from .db import ROLES, WORKSPACES, OpsError, ensure
from .tasks import list_tasks, update_task

router = APIRouter(prefix="/api/ops", tags=["harvestops"])


def ctx(role: str | None, ws: str | None) -> tuple[str, str]:
    r = (role or "manager").strip()
    w = (ws or "main").strip()
    if r not in ROLES:
        raise HTTPException(400, f"unknown role {r!r}")
    if w not in WORKSPACES:
        raise HTTPException(400, f"unknown workspace {w!r}")
    ensure()
    return r, w


def call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except OpsError as e:
        raise HTTPException(e.status, str(e))


Role = Header(None, alias="X-EH-Role")
Ws = Header(None, alias="X-EH-Workspace")


class PassportIn(BaseModel):
    species: str = Field(..., min_length=2, max_length=120)
    organ: str | None = Field(None, max_length=40)
    activity: str | None = Field(None, max_length=300)
    region_label: str | None = Field(None, max_length=120)
    region_public: dict | None = None
    jurisdiction: str | None = Field(None, max_length=80)
    private_locality: str | None = Field(None, max_length=300)


class TransitionIn(BaseModel):
    to: str
    note: str | None = Field(None, max_length=600)


class HarvestIn(BaseModel):
    idem: str = Field(..., max_length=120)
    collector: str = Field(..., max_length=80)
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    qty: float = Field(..., gt=0, le=1e7)
    unit: Literal["g", "kg"]
    basis: Literal["fresh", "dry"]
    lot_code: str = Field(..., pattern=r"^[A-Za-z0-9._-]{2,40}$")
    site_ref: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=300)


class ProcessIn(BaseModel):
    idem: str = Field(..., max_length=120)
    in_lot_id: str
    consume_qty: float = Field(..., gt=0)
    consume_unit: Literal["g", "kg"]
    out_lot_code: str = Field(..., pattern=r"^[A-Za-z0-9._-]{2,40}$")
    out_qty: float = Field(..., ge=0)
    out_unit: Literal["g", "kg"]
    out_basis: Literal["fresh", "dry"]
    moisture_loss: float = Field(0, ge=0)
    rejected: float = Field(0, ge=0)
    waste: float = Field(0, ge=0)
    loss_unit: Literal["g", "kg"] = "kg"
    method: str = Field("drying", max_length=60)


class SplitIn(BaseModel):
    idem: str
    lot_id: str
    qty: float = Field(..., gt=0)
    unit: Literal["g", "kg"]
    new_code: str = Field(..., pattern=r"^[A-Za-z0-9._-]{2,40}$")


class QuarantineIn(BaseModel):
    idem: str
    lot_id: str
    quarantine: bool
    reason: str = Field(..., max_length=300)


class TraceHoldIn(BaseModel):
    idem: str
    reason: str = Field(..., max_length=300)


class AdjustIn(BaseModel):
    idem: str
    lot_id: str
    delta_qty: float
    unit: Literal["g", "kg"]
    reason: str = Field(..., max_length=300)


class QualityIn(BaseModel):
    lot_id: str
    analyte: str = Field(..., max_length=80)
    result: float | None
    unit: str = Field(..., max_length=20)
    criterion_op: Literal["<=", "<", ">=", ">"] | None = None
    criterion_value: float | None = None
    criterion_source: str | None = Field(None, max_length=200)


class ShipmentIn(BaseModel):
    idem: str
    lot_id: str
    qty: float = Field(..., gt=0)
    unit: Literal["g", "kg"]
    destination_country: str = Field(..., max_length=60)
    cross_border: bool


class DispatchIn(BaseModel):
    idem: str
    shipment_id: str


class ReviewIn(BaseModel):
    target: Literal["transfer", "evidence", "quality", "document"]
    decision: Literal["approve", "reject", "request-changes"]
    reason: str = Field(..., max_length=600)


class TaskIn(BaseModel):
    status: Literal["open", "in-review", "resolved", "waived"]
    resolution: str | None = Field(None, max_length=600)


ACCESS_NOTE = ("Demo access model: roles are chosen, not signed in. Permissions are checked on the server, but this is not "
               "production security; do not store real private documents.")


@router.get("/meta")
def meta():
    return {"workspaces": WORKSPACES, "roles": ROLES, "flow": pp.FLOW, "side_states": pp.SIDE, "stage_labels": pp.STAGE_LABEL,
            "organs": pp.ORGANS, "not_a_permit": pp.NOT_A_PERMIT, "access_model": ACCESS_NOTE,
            "mass_tolerance": {"grams": ledger.tolerance()[0], "percent": ledger.tolerance()[1] * 100,
                               "label": ledger.TOLERANCE_LABEL}}


@router.get("/overview")
def overview(role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return pp.overview(w, r)


@router.get("/passports")
def passports(role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return {"passports": pp.list_passports(w, r)}


@router.post("/passports")
def create_passport(body: PassportIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(pp.create, w, r, **body.model_dump())


@router.get("/passports/{pid}")
def passport_detail(pid: str, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(pp.detail, w, r, pid)


@router.post("/passports/{pid}/transition")
def passport_transition(pid: str, body: TransitionIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(pp.transition, w, r, pid, body.to, body.note)


@router.post("/passports/{pid}/harvest")
def harvest(pid: str, body: HarvestIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(pp.record_harvest, w, r, pid, **body.model_dump())


@router.post("/passports/{pid}/shipments")
def shipment(pid: str, body: ShipmentIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(pp.create_shipment, w, r, pid, **body.model_dump())


@router.post("/passports/{pid}/review")
def review(pid: str, body: ReviewIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(pp.review, w, r, pid, **body.model_dump())


@router.get("/passports/{pid}/reconciliation")
def reconciliation(pid: str, role: str = Role, ws: str = Ws):
    _, w = ctx(role, ws)
    return call(ledger.reconciliation, w, pid)


def _mgr(r):
    if r not in ("manager", "admin", "quality-reviewer"):
        raise HTTPException(403, "stock movements are recorded by a manager (quality reviewers may quarantine)")


@router.post("/stock/process")
def process(body: ProcessIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    if r not in ("manager", "admin"):
        raise HTTPException(403, "processing is recorded by a manager")
    out = call(ledger.process, w, r, **body.model_dump())
    try:
        from . import workflow
        from .db import conn
        with conn() as c:
            pid = c.execute("SELECT passport_id FROM ops_lot WHERE id=?", (body.in_lot_id,)).fetchone()[0]
        workflow.trigger(w, pid, "batch_processed")
    except Exception:
        pass
    return out


@router.post("/stock/split")
def split(body: SplitIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    if r not in ("manager", "admin"):
        raise HTTPException(403, "lot splits are recorded by a manager")
    return call(ledger.split, w, r, **body.model_dump())


@router.post("/stock/quarantine")
def quarantine(body: QuarantineIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    _mgr(r)
    return call(ledger.set_quarantine, w, r, **body.model_dump())


@router.post("/stock/adjust")
def adjust(body: AdjustIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(ledger.adjust, w, r, **body.model_dump())


@router.post("/stock/dispatch")
def dispatch(body: DispatchIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    if r not in ("manager", "admin"):
        raise HTTPException(403, "dispatch is recorded by a manager")
    from .db import conn
    with conn() as c:
        s = c.execute("SELECT * FROM ops_shipment WHERE id=? AND workspace=?", (body.shipment_id, w)).fetchone()
        if not s:
            raise HTTPException(404, "shipment not found")
        if not c.execute("SELECT 1 FROM ops_review WHERE passport_id=? AND target='transfer' AND decision='approve'", (s["passport_id"],)).fetchone():
            raise HTTPException(409, "an authorised person must record the transfer decision before dispatch")
    out = call(ledger.dispatch, w, r, body.idem, lot_id=s["lot_id"], qty=s["qty_g"], unit="g", shipment_id=s["id"])
    with conn() as c:
        c.execute("UPDATE ops_shipment SET status='dispatched', updated=strftime('%s','now') WHERE id=?", (s["id"],))
    return out


@router.post("/quality")
def quality(body: QualityIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(pp.add_quality_test, w, r, **body.model_dump())


@router.get("/inventory")
def inventory(passport_id: str | None = None, role: str = Role, ws: str = Ws):
    _, w = ctx(role, ws)
    return ledger.inventory(w, passport_id)


@router.get("/lots/{lot_id}/ledger")
def lot_ledger(lot_id: str, role: str = Role, ws: str = Ws):
    _, w = ctx(role, ws)
    return call(ledger.lot_ledger, w, lot_id)


@router.get("/lots/{lot_id}/lineage")
def lot_lineage(lot_id: str, role: str = Role, ws: str = Ws):
    _, w = ctx(role, ws)
    return call(ledger.lineage, w, lot_id)


@router.post("/lots/{lot_id}/trace-hold")
def trace_hold(lot_id: str, body: TraceHoldIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(ledger.trace_hold, w, r, body.idem, lot_id=lot_id, reason=body.reason)


@router.get("/tasks")
def tasks(passport_id: str | None = None, status: str | None = None, role: str = Role, ws: str = Ws):
    _, w = ctx(role, ws)
    return {"tasks": list_tasks(w, passport_id, status)}


@router.patch("/tasks/{tid}")
def task_update(tid: str, body: TaskIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(update_task, w, r, tid, body.status, body.resolution)


class FieldIn(BaseModel):
    value: str = Field(..., max_length=300)
    reason: str = Field(..., min_length=3, max_length=300)


def _size_guard(content_length: int | None = Header(None)):
    """Refuse oversize uploads from the declared length, before the multipart body is parsed."""
    if content_length is not None and content_length > documents.MAX_BYTES + 64 * 1024:
        raise HTTPException(413, "file is larger than 10 MB")


@router.post("/passports/{pid}/documents", dependencies=[Depends(_size_guard)])
def upload_document(pid: str, file: UploadFile = File(...), role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    data = file.file.read(documents.MAX_BYTES + 1)
    if len(data) > documents.MAX_BYTES:
        raise HTTPException(413, "file is larger than 10 MB")
    if file.content_type not in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        raise HTTPException(415, "only PDF files are accepted")
    return call(documents.ingest, w, r, pid, file.filename or "document.pdf", data)


@router.patch("/fields/{fid}")
def correct_field(fid: str, body: FieldIn, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    return call(documents.correct_field, w, r, fid, body.value, body.reason)


@router.get("/documents/{did}/file")
def document_file(did: str, role: str | None = None, ws: str | None = None):
    """Opened in a new tab, so role/workspace arrive as query parameters (same server-side checks)."""
    _, w = ctx(role, ws)
    found = documents.file_path(w, did)
    if not found:
        raise HTTPException(404, "document not found")
    p, name = found
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return FileResponse(p, media_type="application/pdf", headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Disposition": f'inline; filename="{ascii_name}"'})


@router.get("/passports/{pid}/export/{kind}")
def export(pid: str, kind: str, role: str | None = None, ws: str | None = None):
    """Opened as a link, so role/workspace arrive as query parameters; content is built for that role."""
    r, w = ctx(role, ws)
    pdf, name = call(reports.build, w, r, pid, kind)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{name}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


SAMPLES = documents.store.ROOT / "tests" / "fixtures" / "harvestops"


@router.get("/samples")
def samples(role: str = Role, ws: str = Ws):
    ctx(role, ws)
    gt = SAMPLES / "ground_truth.json"
    if not gt.exists():
        return {"packets": [], "note": "run scripts/generate_demo_documents.py"}
    import json
    data = json.loads(gt.read_text(encoding="utf-8"))
    return {"packets": [{"id": p["id"], "story": p["story"], "passport": p["passport"], "expected": p["expected_rules"],
                         "files": [d["file"] for d in p["documents"]]} for p in data["packets"]]}


@router.post("/passports/{pid}/samples/{packet}")
def load_sample(pid: str, packet: str, role: str = Role, ws: str = Ws):
    """Demo workspace only: upload a SYNTHETIC fixture packet into a passport, exactly as if a user uploaded each file."""
    r, w = ctx(role, ws)
    if w != "demo":
        raise HTTPException(403, "synthetic sample packets can only be loaded into the demo workspace")
    import re
    if not re.fullmatch(r"P\d{2}-[a-z\-]+", packet) or not (SAMPLES / "pdfs" / packet).is_dir():
        raise HTTPException(404, "unknown sample packet")
    out = None
    for f in sorted((SAMPLES / "pdfs" / packet).glob("*.pdf")):
        out = call(documents.ingest, w, r, pid, f.name, f.read_bytes())
    return {"loaded": packet, "issues": (out or {}).get("issues", [])}


@router.post("/passports/{pid}/cautions")
def passport_cautions(pid: str, refresh: int = 0, role: str = Role, ws: str = Ws):
    r, w = ctx(role, ws)
    from .cautions import cautions_for
    return call(cautions_for, w, r, pid, bool(refresh))
