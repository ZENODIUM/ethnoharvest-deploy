"""Actionable tasks created from evidence gaps, document issues and reconciliation gaps."""
from __future__ import annotations

import time

from .db import LOCK, OpsError, audit, conn, ensure, nid, rows

STATUSES = ("open", "in-review", "resolved", "waived")


def add_task(c, ws, passport_id, title, detail, *, kind, phase, blocking=False, owner_role="manager", source="system",
             dedupe=None, due=None, lot_id=None) -> str | None:
    """Insert once per (passport, dedupe key); returns the new id or None if it already existed."""
    dk = dedupe or f"{kind}:{title}"
    if c.execute("SELECT 1 FROM ops_task WHERE workspace=? AND passport_id IS ? AND dedupe=?", (ws, passport_id, dk)).fetchone():
        return None
    tid = nid("task")
    now = time.time()
    c.execute("INSERT INTO ops_task VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (tid, ws, passport_id, lot_id, title, detail, kind, phase, int(blocking), "open", owner_role, due, source, dk, None, now, now))
    audit(c, ws, "system", "task", tid, "create", {"title": title, "source": source})
    return tid


def list_tasks(ws: str, passport_id: str | None = None, status: str | None = None) -> list[dict]:
    ensure()
    q, a = "SELECT * FROM ops_task WHERE workspace=?", [ws]
    if passport_id:
        q += " AND passport_id=?"; a.append(passport_id)
    if status:
        q += " AND status=?"; a.append(status)
    with conn() as c:
        return rows(c.execute(q + " ORDER BY blocking DESC, created", a))


def update_task(ws: str, role: str, tid: str, status: str, resolution: str | None) -> dict:
    ensure()
    if status not in STATUSES:
        raise OpsError(422, f"status must be one of {STATUSES}")
    with LOCK, conn() as c:
        t = c.execute("SELECT * FROM ops_task WHERE id=? AND workspace=?", (tid, ws)).fetchone()
        if not t:
            raise OpsError(404, "task not found")
        if status == "waived":
            if role not in ("manager", "admin"):
                raise OpsError(403, "only a manager or admin may waive a task")
            if not resolution or len(resolution.strip()) < 5:
                raise OpsError(422, "waiving a task needs a written reason")
        elif role not in (t["owner_role"], "manager", "admin"):
            raise OpsError(403, f"this task is assigned to the {t['owner_role']} role")
        if status == "resolved" and (not resolution or len(resolution.strip()) < 3):
            raise OpsError(422, "say how the task was resolved")
        c.execute("UPDATE ops_task SET status=?, resolution=?, updated=? WHERE id=?", (status, resolution, time.time(), tid))
        audit(c, ws, role, "task", tid, f"status:{status}", {"from": t["status"], "resolution": resolution})
        return dict(c.execute("SELECT * FROM ops_task WHERE id=?", (tid,)).fetchone())
