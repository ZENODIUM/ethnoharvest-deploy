"""Seed the HarvestOps DEMO workspace with SYNTHETIC passports, lots and events.

Everything created here is fictional: collectors, quantities, lab results and destinations are invented to show the
workflow. The demo workspace forces the synthetic flag on every passport and lot. Real public evidence (taxonomy, studies,
CITES listing, photos) is still prefilled from live sources, because that is what the passport would show in practice.

    python scripts/seed_demo_ops.py            # seed if the demo workspace is empty
    python scripts/seed_demo_ops.py --reset    # wipe the demo workspace first
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ethnoharvest import store  # noqa: E402
from backend.ethnoharvest.ops import db, ledger, passport as pp  # noqa: E402
from backend.ethnoharvest.ops.tasks import list_tasks, update_task  # noqa: E402

WS = "demo"


def reset():
    db.ensure()
    with db.LOCK, db.conn() as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ops_%'")]
        for t in tables:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            if "workspace" in cols:
                c.execute(f"DELETE FROM {t} WHERE workspace=?", (WS,))
    # child tables without a workspace column are keyed by passport/lot ids that no longer exist; harmless orphans are
    # removed here so the demo ledger stays clean.
    with db.LOCK, db.conn() as c:
        for t, col, parent in [("ops_passport_event", "passport_id", "ops_passport"), ("ops_stock_event", "lot_id", "ops_lot"),
                               ("ops_field", "document_id", "ops_document"), ("ops_issue", "passport_id", "ops_passport")]:
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
            if col in cols and "workspace" not in cols:
                c.execute(f"DELETE FROM {t} WHERE {col} NOT IN (SELECT id FROM {parent})")


def clear(pid, phase_upto, why):
    order = pp.FLOW
    for t in list_tasks(WS, pid):
        if t["status"] in ("open", "in-review") and t["blocking"] and t["phase"] in order[: order.index(phase_upto) + 1]:
            update_task(WS, "manager", t["id"], "waived" if t["kind"] == "evidence" else "resolved", why)


def seed():
    out = []

    # 1. Jatamansi rhizome, Nepal: processed, with an unexplained drying gap that becomes a reconciliation task.
    p = pp.create(WS, "manager", species="Nardostachys jatamansi", organ="rhizome", activity="rhizome collection for a community forest user group",
                  region_label="Dolpa district, Nepal (synthetic)", region_public=None, jurisdiction="Nepal",
                  private_locality="Synthetic site J-3 (fictional)")
    pid = p["id"]
    pp.transition(WS, "manager", pid, "evidence-review")
    clear(pid, "planned", "SYNTHETIC DEMO: confirmed offline with the user group (fictional)")
    pp.transition(WS, "manager", pid, "planned")
    h = pp.record_harvest(WS, "collector", pid, idem="seed-jat-h1", collector="Collector A (fictional)", date="2026-09-12",
                          qty=80, unit="kg", basis="fresh", lot_code="DEMO-JAT-F1")
    pp.transition(WS, "collector", pid, "collected")
    pp.transition(WS, "manager", pid, "processing")
    ledger.process(WS, "manager", "seed-jat-p1", in_lot_id=h["lot"]["id"], consume_qty=80, consume_unit="kg", out_lot_code="DEMO-JAT-D1",
                   out_qty=21, out_unit="kg", out_basis="dry", moisture_loss=52, rejected=2, waste=1, method="shade drying")
    out.append(("Jatamansi rhizome", pid))

    # 2. Prunus africana bark, Cameroon: lab result within the documented limit, shipment prepared, CITES screening open.
    p = pp.create(WS, "manager", species="Prunus africana", organ="bark", activity="bark stripping on managed quarters",
                  region_label="North-West Region, Cameroon (synthetic)", region_public=None, jurisdiction="Cameroon")
    pid = p["id"]
    pp.transition(WS, "manager", pid, "evidence-review")
    clear(pid, "planned", "SYNTHETIC DEMO: reviewed by the cooperative (fictional)")
    pp.transition(WS, "manager", pid, "planned")
    h = pp.record_harvest(WS, "collector", pid, idem="seed-pru-h1", collector="Collector B (fictional)", date="2026-08-30",
                          qty=120, unit="kg", basis="fresh", lot_code="DEMO-PRU-F1")
    pp.transition(WS, "collector", pid, "collected")
    pp.transition(WS, "manager", pid, "processing")
    d = ledger.process(WS, "manager", "seed-pru-p1", in_lot_id=h["lot"]["id"], consume_qty=120, consume_unit="kg", out_lot_code="DEMO-PRU-D1",
                       out_qty=66, out_unit="kg", out_basis="dry", moisture_loss=50, rejected=3, waste=1, method="sun drying")
    clear(pid, "processing", "SYNTHETIC DEMO")
    pp.transition(WS, "manager", pid, "quality-review")
    pp.add_quality_test(WS, "quality-reviewer", lot_id=d["out_lot"]["id"], analyte="loss on drying", result=9.1, unit="%",
                        criterion_op="<=", criterion_value=12, criterion_source="synthetic buyer specification v1 (fictional)")
    clear(pid, "quality-review", "SYNTHETIC DEMO")
    pp.transition(WS, "quality-reviewer", pid, "ready-for-authorised-human-review")
    pp.create_shipment(WS, "manager", pid, idem="seed-pru-s1", lot_id=d["out_lot"]["id"], qty=40, unit="kg",
                       destination_country="France", cross_border=True)
    out.append(("Prunus bark", pid))

    # 3. Khaya senegalensis bark, Benin: just opened; evidence review in progress.
    p = pp.create(WS, "collector", species="Khaya senegalensis", organ="bark", activity="bark collection from farm-boundary trees",
                  region_label="Borgou department, Benin (synthetic)", region_public=None, jurisdiction="Benin")
    pp.transition(WS, "manager", p["id"], "evidence-review")
    out.append(("Khaya bark", p["id"]))

    # 4. Boswellia papyrifera resin, Ethiopia: lab result outside the documented limit; lot put on hold.
    p = pp.create(WS, "manager", species="Boswellia papyrifera", organ="resin (stem tapping)", activity="frankincense tapping",
                  region_label="Tigray / Amhara lowlands, Ethiopia (synthetic)", region_public=None, jurisdiction="Ethiopia")
    pid = p["id"]
    pp.transition(WS, "manager", pid, "evidence-review")
    clear(pid, "planned", "SYNTHETIC DEMO")
    pp.transition(WS, "manager", pid, "planned")
    h = pp.record_harvest(WS, "collector", pid, idem="seed-bos-h1", collector="Collector C (fictional)", date="2026-10-02",
                          qty=18, unit="kg", basis="fresh", lot_code="DEMO-BOS-F1")
    pp.transition(WS, "collector", pid, "collected")
    pp.transition(WS, "manager", pid, "processing")
    d = ledger.process(WS, "manager", "seed-bos-p1", in_lot_id=h["lot"]["id"], consume_qty=18, consume_unit="kg", out_lot_code="DEMO-BOS-D1",
                       out_qty=16.2, out_unit="kg", out_basis="dry", moisture_loss=1.3, rejected=0.4, waste=0.1, method="air curing and grading")
    clear(pid, "processing", "SYNTHETIC DEMO")
    pp.transition(WS, "manager", pid, "quality-review")
    pp.add_quality_test(WS, "quality-reviewer", lot_id=d["out_lot"]["id"], analyte="foreign matter", result=3.4, unit="%",
                        criterion_op="<=", criterion_value=2, criterion_source="synthetic buyer specification v1 (fictional)")
    ledger.set_quarantine(WS, "quality-reviewer", "seed-bos-q1", lot_id=d["out_lot"]["id"], quarantine=True,
                          reason="SYNTHETIC DEMO: foreign matter above the documented limit; regrade before release")
    out.append(("Boswellia resin", pid))
    return out


if __name__ == "__main__":
    store.init()
    db.ensure()
    if "--reset" in sys.argv:
        reset()
    if pp.list_passports(WS, "manager"):
        print("demo workspace already seeded (use --reset to rebuild)")
        sys.exit(0)
    for name, pid in seed():
        d = pp.detail(WS, "manager", pid)
        print(f"{d['code']:<14} {name:<20} {d['status_label']:<32} open tasks: {sum(t['status'] == 'open' for t in d['tasks'])}")
