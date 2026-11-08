"""SQLite persistence: runs, execution events, JEV decisions, scenarios, plans."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "app.sqlite3"
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, kind TEXT, label TEXT, status TEXT, created REAL, finished REAL,
  inputs TEXT, outputs TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts REAL, node TEXT, state TEXT,
  payload TEXT);
CREATE INDEX IF NOT EXISTS ev_run ON events(run_id, seq);
CREATE TABLE IF NOT EXISTS jev_decisions (id TEXT PRIMARY KEY, run_id TEXT, ts REAL, question TEXT, input_digest TEXT,
  input_fields TEXT, model TEXT, criteria TEXT, choice TEXT, confidence REAL, probabilities TEXT, accepted INTEGER,
  fallback TEXT, action TEXT, latency_ms REAL);
CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, kind TEXT, name TEXT, created REAL, updated REAL, body TEXT);
"""


def conn() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, check_same_thread=False, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    with _lock, conn() as c:
        c.executescript(SCHEMA)


def new_id(prefix: str) -> str:
    return f"{prefix}_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"


def create_run(kind: str, label: str, inputs: dict) -> str:
    rid = new_id("run")
    with _lock, conn() as c:
        c.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                  (rid, kind, label, "running", time.time(), None, json.dumps(inputs, default=str), None, None))
    return rid


def finish_run(rid: str, status: str, outputs: dict | None = None, error: str | None = None) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE runs SET status=?, finished=?, outputs=?, error=? WHERE id=?",
                  (status, time.time(), json.dumps(outputs, default=str) if outputs is not None else None, error, rid))


def add_event(rid: str, node: str, state: str, payload: dict) -> int:
    with _lock, conn() as c:
        cur = c.execute("INSERT INTO events (run_id, ts, node, state, payload) VALUES (?,?,?,?,?)",
                        (rid, time.time(), node, state, json.dumps(payload, default=str)))
        return cur.lastrowid


def events(rid: str, after: int = 0) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM events WHERE run_id=? AND seq>? ORDER BY seq", (rid, after)).fetchall()
    return [{"seq": r["seq"], "ts": r["ts"], "node": r["node"], "state": r["state"], "payload": json.loads(r["payload"])}
            for r in rows]


def get_run(rid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("inputs", "outputs"):
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def list_runs(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT id, kind, label, status, created, finished FROM runs ORDER BY created DESC LIMIT ?",
                         (limit,)).fetchall()
    return [dict(r) for r in rows]


def add_jev(rec: dict) -> None:
    with _lock, conn() as c:
        c.execute("INSERT INTO jev_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (new_id("jev"), rec.get("run_id"), time.time(), rec["question"], rec["input_digest"],
                   json.dumps(rec.get("input_fields")), rec.get("model"), json.dumps(rec.get("criteria")),
                   rec.get("choice"), rec.get("confidence"), json.dumps(rec.get("probabilities")),
                   int(bool(rec.get("accepted"))), rec.get("fallback"), rec.get("action"), rec.get("latency_ms")))


def jev_for_run(rid: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM jev_decisions WHERE run_id=? ORDER BY ts", (rid,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("input_fields", "criteria", "probabilities"):
            d[k] = json.loads(d[k]) if d[k] else None
        out.append(d)
    return out


# generic saved items (scenarios, plans, projects)
def save_item(kind: str, name: str, body: dict, item_id: str | None = None) -> dict:
    now = time.time()
    iid = item_id or new_id(kind[:4])
    with _lock, conn() as c:
        ex = c.execute("SELECT created FROM items WHERE id=?", (iid,)).fetchone()
        created = ex["created"] if ex else now
        c.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?)", (iid, kind, name, created, now, json.dumps(body, default=str)))
    return {"id": iid, "kind": kind, "name": name, "created": created, "updated": now, "body": body}


def list_items(kind: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM items WHERE kind=? ORDER BY created", (kind,)).fetchall()
    return [{**dict(r), "body": json.loads(r["body"])} for r in rows]


def get_item(iid: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
    return {**dict(r), "body": json.loads(r["body"])} if r else None


def delete_item(iid: str) -> None:
    with _lock, conn() as c:
        c.execute("DELETE FROM items WHERE id=?", (iid,))
