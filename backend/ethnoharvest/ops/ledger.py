"""Immutable stock ledger.

Every change of material is an event row in ops_stock_event; balances are always computed from events, never
edited. Each operation carries an idempotency key: a retried request returns the original result, and the same
key with a different payload is rejected. Quantities are stored in grams with an explicit basis (fresh or dry);
a lot holds one basis only, so fresh and dry mass are never added together. Drying or cleaning creates a new lot.
Unexplained mass is reported for reconciliation and turned into a task, never interpreted as theft or fraud.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .db import LOCK, OpsError, audit, conn, ensure, loads, nid, rows

UNITS = {"g": 1.0, "kg": 1000.0}
TOLERANCE_LABEL = "assumed operational tolerance (configurable), not a scientific or legal standard"


def tolerance() -> tuple[float, float]:
    """(grams, fraction) for mass-balance gaps. Read from OPS_MASS_TOLERANCE_G / OPS_MASS_TOLERANCE_PCT on each call."""
    from dotenv import dotenv_values
    local = dotenv_values(Path(__file__).resolve().parents[3] / ".env.local")
    get = lambda k, d: os.environ.get(k) or local.get(k) or d
    try:
        g = float(get("OPS_MASS_TOLERANCE_G", "50"))
        pct = float(get("OPS_MASS_TOLERANCE_PCT", "2"))
    except ValueError:
        g, pct = 50.0, 2.0
    return max(0.0, g), max(0.0, pct) / 100


def tolerance_for(mass_g: float) -> float:
    g, frac = tolerance()
    return max(g, frac * mass_g)


def to_grams(qty: float, unit: str) -> float:
    if unit not in UNITS:
        raise OpsError(422, f"unit must be one of {sorted(UNITS)} (got {unit!r})")
    if qty is None or qty < 0 or qty != qty:
        raise OpsError(422, "quantity must be a non-negative number")
    return round(float(qty) * UNITS[unit], 3)


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


def balance(c, lot_id: str) -> dict:
    r = c.execute("SELECT COALESCE(SUM(qty_g),0) q, COALESCE(SUM(reserved_delta_g),0) r FROM ops_stock_event WHERE lot_id=?",
                  (lot_id,)).fetchone()
    q, res = round(r["q"], 3), round(r["r"], 3)
    return {"on_hand_g": q, "reserved_g": res, "available_g": round(q - res, 3)}


def _lot(c, ws: str, lot_id: str) -> dict:
    r = c.execute("SELECT * FROM ops_lot WHERE id=? AND workspace=?", (lot_id, ws)).fetchone()
    if not r:
        raise OpsError(404, "lot not found in this workspace")
    return dict(r)


def _new_lot(c, ws, code, basis, passport_id, species, organ, storage, parent=None, status="active", synthetic=0) -> dict:
    if c.execute("SELECT 1 FROM ops_lot WHERE workspace=? AND code=?", (ws, code)).fetchone():
        raise OpsError(409, f"lot code {code} already exists")
    lid = nid("lot")
    c.execute("INSERT INTO ops_lot VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (lid, ws, passport_id, code, species, organ, basis, status, storage, parent, synthetic, time.time()))
    return _lot(c, ws, lid)


def _event(c, op_id, lot, kind, qty_g, role, reason=None, ref=None, meta=None, reserved_delta=0.0):
    c.execute("INSERT INTO ops_stock_event (op_id, lot_id, kind, qty_g, reserved_delta_g, basis, ts, actor_role, reason, ref, meta) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (op_id, lot["id"], kind, qty_g, reserved_delta, lot["basis"], time.time(), role,
                                                 reason, ref, json.dumps(meta or {}, default=str)))


def _require_available(c, lot, need_g):
    b = balance(c, lot["id"])
    if need_g > b["available_g"] + 1e-6:
        raise OpsError(409, f"insufficient stock in {lot['code']}: requested {need_g:g} g, available {b['available_g']:g} g "
                            f"({b['reserved_g']:g} g reserved)")
    if lot["status"] == "quarantined":
        raise OpsError(409, f"lot {lot['code']} is quarantined; release it after review before moving stock")


def run_op(ws: str, role: str, idem_key: str, kind: str, payload: dict, fn) -> dict:
    """Execute fn(c, op_id) once per idempotency key, atomically."""
    ensure()
    if not idem_key or len(idem_key) > 120:
        raise OpsError(422, "idempotency key required (max 120 chars)")
    dig = _digest({"kind": kind, **payload})
    with LOCK, conn() as c:
        prev = c.execute("SELECT * FROM ops_stock_op WHERE workspace=? AND idem_key=?", (ws, idem_key)).fetchone()
        if prev:
            if prev["payload_digest"] != dig:
                raise OpsError(409, "idempotency key reused with a different request")
            return json.loads(prev["result"]) | {"replayed": True}
        op_id = nid("op")
        result = fn(c, op_id)
        c.execute("INSERT INTO ops_stock_op VALUES (?,?,?,?,?,?,?,?)",
                  (op_id, ws, idem_key, kind, role, time.time(), dig, json.dumps(result, default=str)))
        audit(c, ws, role, "stock_op", op_id, kind, payload)
        return result | {"replayed": False}


# ------------------------------------------------------------------ operations
def receive(ws, role, idem, *, lot_code, basis, qty, unit, passport_id=None, species=None, organ=None, storage=None,
            reason="field collection receipt", ref=None, synthetic=0):
    if basis not in ("fresh", "dry"):
        raise OpsError(422, "basis must be 'fresh' or 'dry'")
    g = to_grams(qty, unit)
    if g <= 0:
        raise OpsError(422, "received quantity must be greater than zero")
    if ws == "demo":
        synthetic = 1  # the demo workspace only ever holds synthetic material

    def fn(c, op_id):
        ex = c.execute("SELECT * FROM ops_lot WHERE workspace=? AND code=?", (ws, lot_code)).fetchone()
        lot = dict(ex) if ex else _new_lot(c, ws, lot_code, basis, passport_id, species, organ, storage, synthetic=synthetic)
        if lot["basis"] != basis:
            raise OpsError(409, f"lot {lot_code} holds {lot['basis']} material; record {basis} material in a separate lot")
        _event(c, op_id, lot, "receive", g, role, reason, ref, {"qty": qty, "unit": unit})
        return {"op_id": op_id, "lot": lot, "received_g": g, "balance": balance(c, lot["id"])}
    return run_op(ws, role, idem, "receive", {"lot": lot_code, "basis": basis, "g": g, "passport": passport_id}, fn)


def process(ws, role, idem, *, in_lot_id, consume_qty, consume_unit, out_lot_code, out_qty, out_unit, out_basis,
            moisture_loss=0.0, rejected=0.0, waste=0.0, loss_unit="kg", method="drying", storage=None):
    cg, og = to_grams(consume_qty, consume_unit), to_grams(out_qty, out_unit)
    mg, rg, wg = (to_grams(x or 0, loss_unit) for x in (moisture_loss, rejected, waste))
    if cg <= 0:
        raise OpsError(422, "processed input must be greater than zero")

    def fn(c, op_id):
        src = _lot(c, ws, in_lot_id)
        _require_available(c, src, cg)
        if out_basis == "fresh" and src["basis"] == "dry":
            raise OpsError(422, "dry material cannot become fresh material")
        out = _new_lot(c, ws, out_lot_code, out_basis, src["passport_id"], src["species"], src["organ"], storage or src["storage"],
                       parent=src["id"], synthetic=src.get("synthetic", 0))
        _event(c, op_id, src, "process_out", -cg, role, f"{method}: input consumed", out["id"])
        if og > 0:
            _event(c, op_id, out, "process_in", og, role, f"{method}: output", src["id"])
        rej = None
        if rg > 0:
            rej = _new_lot(c, ws, f"{out_lot_code}-REJ", out_basis, src["passport_id"], src["species"], src["organ"],
                           "rejected material area", parent=src["id"], status="quarantined",
                           synthetic=src.get("synthetic", 0))
            _event(c, op_id, rej, "process_in", rg, role, f"{method}: rejected material set aside", src["id"])
        unexplained = round(cg - og - mg - rg - wg, 3)
        pid = nid("proc")
        c.execute("INSERT INTO ops_processing VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (pid, ws, src["passport_id"], src["id"], out["id"], rej["id"] if rej else None, cg, og, mg, rg, wg,
                   unexplained, method, time.time()))
        tol = tolerance_for(cg)
        flag = None
        if abs(unexplained) > tol:
            flag = {"unexplained_g": unexplained, "tolerance_g": round(tol, 1), "tolerance_label": TOLERANCE_LABEL,
                    "message": f"{abs(unexplained) / 1000:.2f} kg is not accounted for by the declared output, moisture loss, "
                               f"rejected material or waste. Please record what happened (e.g. weighing error, unrecorded "
                               f"loss, sampling). This is a reconciliation gap, not an accusation. Threshold: {tol / 1000:.2f} kg, an "
                               f"{TOLERANCE_LABEL}."}
            from .tasks import add_task
            add_task(c, ws, src["passport_id"], f"Explain {abs(unexplained) / 1000:.2f} kg unaccounted mass in {src['code']} → {out_lot_code}",
                     flag["message"], kind="reconciliation", phase="processing", blocking=True, owner_role="manager",
                     source=f"ledger:{pid}", dedupe=f"recon:{pid}", lot_id=out["id"])
        return {"op_id": op_id, "processing_id": pid, "in_lot": src["code"], "out_lot": out, "rejected_lot": rej,
                "mass_balance": {"input_g": cg, "output_g": og, "moisture_loss_g": mg, "rejected_g": rg, "waste_g": wg,
                                 "unexplained_g": unexplained, "basis_in": src["basis"], "basis_out": out_basis},
                "reconciliation_flag": flag}
    return run_op(ws, role, idem, "process", {"in": in_lot_id, "c": cg, "out": out_lot_code, "o": og, "m": mg, "r": rg, "w": wg}, fn)


def split(ws, role, idem, *, lot_id, qty, unit, new_code, storage=None):
    g = to_grams(qty, unit)

    def fn(c, op_id):
        src = _lot(c, ws, lot_id)
        _require_available(c, src, g)
        child = _new_lot(c, ws, new_code, src["basis"], src["passport_id"], src["species"], src["organ"], storage or src["storage"], parent=src["id"],
                         synthetic=src.get("synthetic", 0))
        _event(c, op_id, src, "split_out", -g, role, f"split into {new_code}", child["id"])
        _event(c, op_id, child, "split_in", g, role, f"split from {src['code']}", src["id"])
        return {"op_id": op_id, "parent": src["code"], "child": child, "moved_g": g,
                "balances": {src["code"]: balance(c, src["id"]), new_code: balance(c, child["id"])}}
    return run_op(ws, role, idem, "split", {"lot": lot_id, "g": g, "new": new_code}, fn)


def reserve(ws, role, idem, *, lot_id, qty, unit, release=False, ref=None):
    g = to_grams(qty, unit)

    def fn(c, op_id):
        lot = _lot(c, ws, lot_id)
        b = balance(c, lot["id"])
        if release:
            if g > b["reserved_g"] + 1e-6:
                raise OpsError(409, f"cannot release {g:g} g: only {b['reserved_g']:g} g reserved")
            _event(c, op_id, lot, "release", 0, role, "reservation released", ref, reserved_delta=-g)
        else:
            _require_available(c, lot, g)
            _event(c, op_id, lot, "reserve", 0, role, "reserved for shipment/order", ref, reserved_delta=g)
        return {"op_id": op_id, "lot": lot["code"], "balance": balance(c, lot["id"])}
    return run_op(ws, role, idem, "release" if release else "reserve", {"lot": lot_id, "g": g, "ref": ref}, fn)


def set_quarantine(ws, role, idem, *, lot_id, quarantine: bool, reason: str):
    if not reason or len(reason.strip()) < 3:
        raise OpsError(422, "a reason is required")

    def fn(c, op_id):
        lot = _lot(c, ws, lot_id)
        c.execute("UPDATE ops_lot SET status=? WHERE id=?", ("quarantined" if quarantine else "active", lot["id"]))
        _event(c, op_id, lot, "quarantine" if quarantine else "quarantine_release", 0, role, reason)
        return {"op_id": op_id, "lot": lot["code"], "status": "quarantined" if quarantine else "active"}
    return run_op(ws, role, idem, "quarantine", {"lot": lot_id, "q": quarantine, "why": reason}, fn)


def dispatch(ws, role, idem, *, lot_id, qty, unit, shipment_id=None):
    g = to_grams(qty, unit)

    def fn(c, op_id):
        lot = _lot(c, ws, lot_id)
        b = balance(c, lot["id"])
        # dispatch draws on this shipment's own reservation first
        res_here = 0.0
        if shipment_id:
            r = c.execute("SELECT COALESCE(SUM(reserved_delta_g),0) r FROM ops_stock_event WHERE lot_id=? AND ref=?", (lot["id"], shipment_id)).fetchone()
            res_here = max(0.0, r["r"])
        if lot["status"] == "quarantined":
            raise OpsError(409, f"lot {lot['code']} is quarantined; release it after review before moving stock")
        if g > b["available_g"] + min(res_here, g) + 1e-6:
            raise OpsError(409, f"insufficient stock in {lot['code']}: requested {g:g} g, available {b['available_g']:g} g "
                                f"plus {res_here:g} g reserved for this shipment")
        if res_here:
            _event(c, op_id, lot, "release", 0, role, "reservation consumed by dispatch", shipment_id, reserved_delta=-min(res_here, g))
        _event(c, op_id, lot, "dispatch", -g, role, "dispatched", shipment_id)
        return {"op_id": op_id, "lot": lot["code"], "dispatched_g": g, "balance": balance(c, lot["id"])}
    return run_op(ws, role, idem, "dispatch", {"lot": lot_id, "g": g, "ship": shipment_id}, fn)


def adjust(ws, role, idem, *, lot_id, delta_qty, unit, reason):
    if role not in ("manager", "admin"):
        raise OpsError(403, "only a manager or admin can record a stock adjustment")
    if not reason or len(reason.strip()) < 5:
        raise OpsError(422, "an adjustment needs a written reason")
    g = round(float(delta_qty) * UNITS.get(unit, 0), 3) if unit in UNITS else None
    if g is None or g == 0:
        raise OpsError(422, "adjustment must be a non-zero quantity in g or kg")

    def fn(c, op_id):
        lot = _lot(c, ws, lot_id)
        if g < 0:
            _require_available(c, lot, -g)
        _event(c, op_id, lot, "adjust", g, role, reason)
        return {"op_id": op_id, "lot": lot["code"], "adjusted_g": g, "balance": balance(c, lot["id"])}
    return run_op(ws, role, idem, "adjust", {"lot": lot_id, "g": g, "why": reason}, fn)


# ------------------------------------------------------------------ views
def lot_view(c, lot: dict) -> dict:
    return lot | balance(c, lot["id"])


def inventory(ws: str, passport_id: str | None = None) -> dict:
    ensure()
    with conn() as c:
        q = "SELECT * FROM ops_lot WHERE workspace=?" + (" AND passport_id=?" if passport_id else "") + " ORDER BY created"
        lots = [lot_view(c, l) for l in rows(c.execute(q, (ws, passport_id) if passport_id else (ws,)))]
        totals: dict[str, dict] = {}
        for l in lots:
            k = f"{l['species']}|{l['organ']}|{l['basis']}|{l['status']}"
            t = totals.setdefault(k, {"species": l["species"], "organ": l["organ"], "basis": l["basis"], "status": l["status"], "on_hand_g": 0.0, "available_g": 0.0})
            t["on_hand_g"] += l["on_hand_g"]; t["available_g"] += l["available_g"]
        return {"lots": lots, "by_species_organ_basis_status": list(totals.values()),
                "note": "Fresh and dry mass are reported separately and never summed."}


def lot_ledger(ws: str, lot_id: str) -> dict:
    ensure()
    with conn() as c:
        lot = _lot(c, ws, lot_id)
        ev = [loads(e, "meta") for e in rows(c.execute("SELECT * FROM ops_stock_event WHERE lot_id=? ORDER BY seq", (lot_id,)))]
        running, out = 0.0, []
        for e in ev:
            running = round(running + e["qty_g"], 3)
            out.append(e | {"running_g": running})
        return {"lot": lot_view(c, lot), "events": out}


def reconciliation(ws: str, passport_id: str) -> dict:
    """Received vs processed vs on hand vs dispatched for one passport, per basis."""
    ensure()
    with conn() as c:
        proc = rows(c.execute("SELECT * FROM ops_processing WHERE workspace=? AND passport_id=? ORDER BY created", (ws, passport_id)))
        lots = rows(c.execute("SELECT * FROM ops_lot WHERE workspace=? AND passport_id=?", (ws, passport_id)))
        ids = [l["id"] for l in lots] or [""]
        ph = ",".join("?" * len(ids))
        sums = {(r["basis"], r["kind"]): r["g"] for r in c.execute(
            f"SELECT basis, kind, SUM(qty_g) g FROM ops_stock_event WHERE lot_id IN ({ph}) GROUP BY basis, kind", ids)}
        per_basis = {}
        for b in ("fresh", "dry"):
            k = {kind: round(g, 3) for (bb, kind), g in sums.items() if bb == b}
            per_basis[b] = k | {"on_hand_g": round(sum(k.values()), 3)}
        return {"processing": proc, "per_basis": per_basis,
                "unexplained_total_g": round(sum(p["unexplained_g"] or 0 for p in proc), 3)}


# ------------------------------------------------------------------ lineage and recall
def _descendants(c, ws: str, lot_id: str) -> list[dict]:
    """The lot and every lot derived from it (process, split, rejects), breadth-first."""
    out, frontier, seen = [], [lot_id], set()
    while frontier:
        lid = frontier.pop(0)
        if lid in seen:
            continue
        seen.add(lid)
        out.append(_lot(c, ws, lid))
        frontier += [r["id"] for r in c.execute("SELECT id FROM ops_lot WHERE workspace=? AND parent_lot=? ORDER BY created", (ws, lid))]
    return out


def lineage(ws: str, lot_id: str) -> dict:
    """Ancestors up to the received lot, and the full tree below it, with balances and processing masses."""
    ensure()
    with conn() as c:
        lot = _lot(c, ws, lot_id)
        root, guard = lot, 0
        while root["parent_lot"] and guard < 50:
            root, guard = _lot(c, ws, root["parent_lot"]), guard + 1
        nodes = [lot_view(c, l) for l in _descendants(c, ws, root["id"])]
        ids = {n["id"] for n in nodes}
        proc = rows(c.execute("SELECT in_lot, out_lot, rejected_lot, in_g, out_g, moisture_g, rejected_g, waste_g, unexplained_g, method "
                              "FROM ops_processing WHERE workspace=?", (ws,)))
        edges = [{"from": n["parent_lot"], "to": n["id"]} for n in nodes if n["parent_lot"] in ids]
        return {"focus": lot_id, "root": root["id"], "nodes": nodes, "edges": edges,
                "processing": [p for p in proc if p["in_lot"] in ids]}


def trace_hold(ws, role, idem, *, lot_id: str, reason: str):
    """Quarantine a lot and every derived lot that still holds stock, and add a recall task per held lot."""
    if role not in ("manager", "admin", "quality-reviewer"):
        raise OpsError(403, "a trace hold is placed by a manager or quality reviewer")
    if not reason or len(reason.strip()) < 5:
        raise OpsError(422, "a trace hold needs a written reason")
    from .tasks import add_task

    def fn(c, op_id):
        held, skipped = [], []
        for l in _descendants(c, ws, lot_id):
            b = balance(c, l["id"])
            if b["on_hand_g"] <= 0 or l["status"] == "quarantined":
                skipped.append({"lot": l["code"], "why": "already quarantined" if l["status"] == "quarantined" else "no stock on hand"})
                continue
            c.execute("UPDATE ops_lot SET status='quarantined' WHERE id=?", (l["id"],))
            _event(c, op_id, l, "quarantine", 0, role, f"trace hold: {reason}", lot_id)
            add_task(c, ws, l["passport_id"], f"Recall review for lot {l['code']}",
                     f"Placed on trace hold from lot {lot_id}: {reason}. Check where this material went and release only after review.",
                     kind="recall", phase="processing", blocking=True, owner_role="quality-reviewer", source="trace-hold",
                     dedupe=f"recall:{l['id']}", lot_id=l["id"])
            held.append({"lot": l["code"], "on_hand_g": b["on_hand_g"]})
        return {"op_id": op_id, "held": held, "skipped": skipped}
    return run_op(ws, role, idem, "trace_hold", {"lot": lot_id, "why": reason}, fn)
