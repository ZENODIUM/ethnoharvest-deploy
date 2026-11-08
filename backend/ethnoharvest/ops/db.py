"""SQLite schema for HarvestOps, applied as numbered migrations recorded in schema_migrations."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

from .. import store

LOCK = threading.RLock()
WORKSPACES = {"demo": "Demo workspace (synthetic data only)", "main": "My workspace"}
ROLES = ("collector", "manager", "scientific-reviewer", "quality-reviewer", "admin")

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
CREATE TABLE IF NOT EXISTS ops_passport (
  id TEXT PRIMARY KEY, workspace TEXT NOT NULL, code TEXT, species TEXT NOT NULL, accepted_name TEXT, taxon_ref TEXT,
  organ TEXT, activity TEXT, region_label TEXT, region_public TEXT, private_locality TEXT, jurisdiction TEXT,
  status TEXT NOT NULL, prev_status TEXT, prefill TEXT, fields TEXT, synthetic INTEGER NOT NULL DEFAULT 0,
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS ops_passport_event (
  id TEXT PRIMARY KEY, passport_id TEXT NOT NULL, ts REAL, actor_role TEXT, kind TEXT, from_status TEXT, to_status TEXT,
  note TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS ops_task (
  id TEXT PRIMARY KEY, workspace TEXT NOT NULL, passport_id TEXT, lot_id TEXT, title TEXT NOT NULL, detail TEXT, kind TEXT,
  phase TEXT, blocking INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, owner_role TEXT, due TEXT, source TEXT,
  dedupe TEXT, resolution TEXT, created REAL, updated REAL);
CREATE UNIQUE INDEX IF NOT EXISTS ops_task_dedupe ON ops_task(workspace, passport_id, dedupe);
CREATE TABLE IF NOT EXISTS ops_lot (
  id TEXT PRIMARY KEY, workspace TEXT NOT NULL, passport_id TEXT, code TEXT NOT NULL, species TEXT, organ TEXT,
  basis TEXT NOT NULL CHECK (basis IN ('fresh','dry')), status TEXT NOT NULL, storage TEXT, parent_lot TEXT,
  synthetic INTEGER NOT NULL DEFAULT 0, created REAL);
CREATE UNIQUE INDEX IF NOT EXISTS ops_lot_code ON ops_lot(workspace, code);
CREATE TABLE IF NOT EXISTS ops_stock_op (
  id TEXT PRIMARY KEY, workspace TEXT NOT NULL, idem_key TEXT NOT NULL, kind TEXT, actor_role TEXT, ts REAL,
  payload_digest TEXT, result TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS ops_op_idem ON ops_stock_op(workspace, idem_key);
CREATE TABLE IF NOT EXISTS ops_stock_event (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, op_id TEXT NOT NULL, lot_id TEXT NOT NULL, kind TEXT NOT NULL,
  qty_g REAL NOT NULL, reserved_delta_g REAL NOT NULL DEFAULT 0, basis TEXT NOT NULL, ts REAL, actor_role TEXT,
  reason TEXT, ref TEXT, meta TEXT);
CREATE INDEX IF NOT EXISTS ops_ev_lot ON ops_stock_event(lot_id, seq);
CREATE TABLE IF NOT EXISTS ops_harvest_event (
  id TEXT PRIMARY KEY, workspace TEXT, passport_id TEXT, lot_id TEXT, collector TEXT, date TEXT, qty_g REAL,
  qty_original REAL, unit_original TEXT, basis TEXT, site_ref TEXT, note TEXT, synthetic INTEGER, created REAL);
CREATE TABLE IF NOT EXISTS ops_processing (
  id TEXT PRIMARY KEY, workspace TEXT, passport_id TEXT, in_lot TEXT, out_lot TEXT, rejected_lot TEXT, in_g REAL,
  out_g REAL, moisture_g REAL, rejected_g REAL, waste_g REAL, unexplained_g REAL, method TEXT, created REAL);
CREATE TABLE IF NOT EXISTS ops_quality_test (
  id TEXT PRIMARY KEY, workspace TEXT, lot_id TEXT, analyte TEXT, result REAL, result_text TEXT, unit TEXT,
  criterion TEXT, criterion_source TEXT, outcome TEXT, source_doc TEXT, created REAL);
CREATE TABLE IF NOT EXISTS ops_shipment (
  id TEXT PRIMARY KEY, workspace TEXT, passport_id TEXT, lot_id TEXT, qty_g REAL, destination_country TEXT,
  cross_border INTEGER, status TEXT, checklist TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS ops_review (
  id TEXT PRIMARY KEY, workspace TEXT, passport_id TEXT, target TEXT, decision TEXT, reason TEXT, role TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS ops_audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, workspace TEXT, ts REAL, actor_role TEXT, entity TEXT, entity_id TEXT,
  action TEXT, data TEXT);
"""),
    (2, """
CREATE TABLE IF NOT EXISTS ops_document (
  id TEXT PRIMARY KEY, workspace TEXT NOT NULL, passport_id TEXT, lot_code TEXT, filename TEXT, sha256 TEXT NOT NULL,
  mime TEXT, bytes INTEGER, pages INTEGER, doc_kind TEXT, kind_confidence REAL, uploader_role TEXT, visibility TEXT,
  status TEXT, issuer_verification TEXT, synthetic_marked INTEGER, extraction TEXT, extractor TEXT, latency_ms REAL,
  version INTEGER NOT NULL DEFAULT 1, stored_path TEXT, created REAL);
CREATE INDEX IF NOT EXISTS ops_doc_pass ON ops_document(workspace, passport_id);
CREATE TABLE IF NOT EXISTS ops_field (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL, name TEXT NOT NULL, value TEXT, normalised TEXT, original TEXT,
  page INTEGER, snippet TEXT, confidence REAL, method TEXT, status TEXT, corrected_by TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS ops_field_correction (
  id TEXT PRIMARY KEY, field_id TEXT, old_value TEXT, new_value TEXT, role TEXT, reason TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS ops_issue (
  id TEXT PRIMARY KEY, workspace TEXT, passport_id TEXT, rule TEXT, severity TEXT, category TEXT, message TEXT,
  evidence TEXT, status TEXT, dedupe TEXT, created REAL, updated REAL);
CREATE UNIQUE INDEX IF NOT EXISTS ops_issue_dedupe ON ops_issue(workspace, passport_id, dedupe);
"""),
    (3, """
CREATE TABLE IF NOT EXISTS ops_caution_cache (
  key TEXT PRIMARY KEY, species TEXT, organ TEXT, jurisdiction TEXT, body TEXT, run_id TEXT, created REAL);
"""),
]

_ready = False


def conn() -> sqlite3.Connection:
    return store.conn()


def migrate() -> list[int]:
    global _ready
    applied = []
    with LOCK, conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied REAL)")
        done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
        for v, sql in MIGRATIONS:
            if v not in done:
                c.executescript(sql)
                c.execute("INSERT INTO schema_migrations VALUES (?, ?)", (v, time.time()))
                applied.append(v)
    _ready = True
    return applied


def ensure():
    if not _ready:
        migrate()


def nid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def audit(c: sqlite3.Connection, ws: str, role: str, entity: str, eid: str, action: str, data: dict | None = None):
    c.execute("INSERT INTO ops_audit (workspace, ts, actor_role, entity, entity_id, action, data) VALUES (?,?,?,?,?,?,?)",
              (ws, time.time(), role, entity, eid, action, json.dumps(data or {}, default=str)))


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def loads(d: dict, *keys: str) -> dict:
    for k in keys:
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                pass
    return d


class OpsError(Exception):
    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status
