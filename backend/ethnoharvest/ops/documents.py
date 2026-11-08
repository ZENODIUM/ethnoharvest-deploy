"""HarvestOps document intake: validate → extract text (layout) → classify → extract fields with provenance → normalise →
cross-document rules → issues and tasks.

Honesty rules
- A readable document is not an authentic document. Only the issuer can confirm validity; every document carries that note.
- Image-only pages are never guessed: without an OCR engine the document is marked `needs-ocr` and a review task is created.
- Optional LLM extraction (Groq) only fills fields the rules missed, receives extracted text (never the file), and a value is
  kept only if it appears verbatim in that text. Disable with OPS_LLM_EXTRACTION=0.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import unicodedata
from datetime import date, datetime

from .. import store
from .db import LOCK, OpsError, audit, conn, ensure, loads, nid, rows

DOC_DIR = store.ROOT / "data" / "ops_documents"
MAX_BYTES = 10 * 1024 * 1024
MAX_PAGES = 40
ISSUER_NOTE = "not verified with the issuer: EthnoHarvest can read this document but cannot confirm it is genuine or valid"
EXTRACTOR = "rules-1.0"

# ------------------------------------------------------------------ vocabularies
KIND_KEYWORDS = {
    "collection_plan": ["collection plan", "plan de collecte"],
    "authorisation": ["collection authorisation", "collection authorization", "autorisation de collecte", "collection permit"],
    "id_sheet": ["species identification", "identification sheet"],
    "weigh_in": ["weigh-in slip", "weigh in slip", "weighbridge", "bordereau de pesee"],
    "drying_log": ["drying log", "registre de sechage"],
    "batch_statement": ["batch and custody", "custody statement", "batch statement"],
    "coa": ["certificate of analysis", "certificat d'analyse"],
    "invoice": ["packing list", "invoice", "facture"],
    "monitoring": ["monitoring sheet", "fiche de suivi"],
}
KIND_LABEL = {"collection_plan": "collection plan", "authorisation": "authorisation", "id_sheet": "identification sheet",
              "weigh_in": "weigh-in slip", "drying_log": "drying log", "batch_statement": "batch statement", "coa": "lab certificate",
              "invoice": "invoice / packing list", "monitoring": "monitoring sheet", "unknown": "unclassified"}
ALIASES = {
    "document_id": ["document no", "document number", "doc no", "slip no", "permit no", "certificate no", "invoice no", "n° du document",
                    "numero du document"],
    "issuer": ["issued by", "issuer", "delivre par"],
    "species": ["species", "scientific name", "espece", "nom scientifique"],
    "organ": ["plant part", "harvested part", "part collected", "partie recoltee", "organe"],
    "authorised_quantity": ["authorised quantity", "authorized quantity", "maximum quantity", "quantite autorisee"],
    "planned_quantity": ["planned quantity", "quantite prevue"],
    "quantity": ["net weight", "quantity", "quantite", "poids net"],
    "valid_from": ["valid from", "valable du", "valide du"],
    "valid_until": ["valid until", "expiry date", "expires on", "valable jusqu'au", "valide jusqu'au"],
    "collection_date": ["collection date", "date of collection", "date de collecte"],
    "area": ["collection area", "zone de collecte", "area", "site"],
    "jurisdiction": ["country", "jurisdiction", "pays"],
    "collector": ["collector", "collected by", "collecteur"],
    "lot_code": ["lot code", "batch no", "batch code", "numero de lot", "lot"],
    "input_lot": ["input lot"], "output_lot": ["output lot"], "fresh_input": ["fresh input"], "dry_output": ["dry output"],
    "moisture_loss": ["water loss", "moisture loss"], "rejected": ["rejected material"], "waste": ["waste"],
    "destination_country": ["destination country", "pays de destination"], "consignee": ["consignee", "destinataire"],
    "voucher_id": ["voucher no", "voucher"], "identified_by": ["identified by"],
    "monitoring_date": ["monitoring date"], "plants_counted": ["plants counted"],
}
EXPECTED = {
    "collection_plan": ["document_id", "species", "organ", "area", "planned_quantity", "collection_date"],
    "authorisation": ["document_id", "issuer", "species", "organ", "authorised_quantity", "valid_from", "valid_until", "area"],
    "id_sheet": ["species", "organ", "voucher_id"],
    "weigh_in": ["document_id", "species", "organ", "collection_date", "quantity", "lot_code"],
    "drying_log": ["input_lot", "output_lot", "fresh_input", "dry_output", "moisture_loss"],
    "batch_statement": ["lot_code", "quantity", "species"],
    "coa": ["lot_code"],
    "invoice": ["lot_code", "quantity", "destination_country"],
    "monitoring": ["species", "area", "monitoring_date"],
}
# documented synonyms only (accepted name on the right)
SYNONYMS = {"nardostachys grandiflora": "Nardostachys jatamansi", "pygeum africanum": "Prunus africana",
            "boswellia floribunda": "Boswellia papyrifera"}
ORGAN_ALIASES = {"rhizomes": "rhizome", "roots and rhizomes": "rhizome", "roots": "root", "racine": "root", "racines": "root",
                 "ecorce": "bark", "stem bark": "bark", "leaves": "leaf", "foliage": "leaf", "feuille": "leaf", "feuilles": "leaf",
                 "gum resin": "resin", "oleo-gum resin": "resin", "frankincense": "resin", "resine": "resin", "fruits": "fruit",
                 "seeds": "seed", "flowers": "flower", "whole plant": "whole plant"}
QUANTITY_FIELDS = {"quantity", "authorised_quantity", "planned_quantity", "fresh_input", "dry_output", "moisture_loss", "rejected", "waste"}
DATE_FIELDS = {"valid_from", "valid_until", "collection_date", "monitoring_date"}
LOT_FIELDS = {"lot_code", "input_lot", "output_lot"}
MONTHS = {m: i + 1 for i, ms in enumerate([("jan", "janv"), ("feb", "fev", "fevr"), ("mar", "mars"), ("apr", "avr"), ("may", "mai"),
                                            ("jun", "juin"), ("jul", "juil"), ("aug", "aou", "aout"), ("sep", "sept"), ("oct",),
                                            ("nov",), ("dec",)]) for m in ms}


def fold(s: str) -> str:
    """lower-case, strip accents (keeps °), collapse spaces"""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("’", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


_ALIAS = sorted(((fold(a), k) for k, al in ALIASES.items() for a in al), key=lambda x: -len(x[0]))


# ------------------------------------------------------------------ normalisers (shared by rules and the benchmark)
def parse_quantity(v: str | None) -> tuple[float, str | None] | None:
    if not v:
        return None
    m = re.search(r"([\d][\d.,\s]*)\s*(kg|kilograms?|kilogrammes?|g|grams?|grammes?|t|tonnes?)\b\s*(fresh|dry|frais|fraiche|sec|seche)?", fold(v))
    if not m:
        return None
    num = float(m.group(1).replace(" ", "").replace(",", "."))
    unit = m.group(2)
    g = num * (1000 if unit.startswith("k") else 1_000_000 if unit.startswith("t") else 1)
    basis = {"frais": "fresh", "fraiche": "fresh", "sec": "dry", "seche": "dry"}.get(m.group(3) or "", m.group(3))
    return g, basis


def parse_date(v: str | None) -> str | None:
    if not v:
        return None
    s = fold(v)
    if m := re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", s):  # year-first; slash form added after the held-out run
        y, mo, d = map(int, m.groups())
    elif m := re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", s):  # day-first, as on the documents we expect
        d, mo, y = map(int, m.groups())
    elif m := re.search(r"\b(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})\b", s):
        d, mon, y = int(m.group(1)), m.group(2), int(m.group(3))
        mo = MONTHS.get(mon[:4]) or MONTHS.get(mon[:3])
        if not mo:
            return None
    elif m := re.search(r"\b([a-z]+)\s+(\d{1,2}),?\s+(\d{4})\b", s):
        mo, d, y = MONTHS.get(m.group(1)[:3]), int(m.group(2)), int(m.group(3))
        if not mo:
            return None
    else:
        return None
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def species_name(v: str | None) -> tuple[str | None, bool]:
    """→ (accepted binomial, was_synonym)"""
    if not v:
        return None, False
    words = re.findall(r"[A-Za-z][a-z\-]+", v)
    if len(words) < 2:
        return None, False
    bi = f"{words[0].lower()} {words[1].lower()}"
    if bi in SYNONYMS:
        return SYNONYMS[bi], True
    return bi[0].upper() + bi[1:], False


def organ_name(v: str | None) -> str | None:
    if not v:
        return None
    s = fold(v).split("(")[0].strip()
    return ORGAN_ALIASES.get(s, s.rstrip("s") if s.endswith("s") and s[:-1] in ORGAN_ALIASES.values() else s)


def organ_parts(v: str | None) -> set[str]:
    return {organ_name(p) for p in re.split(r"\+|,| and | et ", v or "") if organ_name(p)}


def normalise(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if name in QUANTITY_FIELDS:
        q = parse_quantity(value)
        return f"{q[0]:g} g{(' ' + q[1]) if q[1] else ''}" if q else None
    if name in DATE_FIELDS:
        return parse_date(value)
    if name == "species":
        return species_name(value)[0]
    if name == "organ":
        return organ_name(value)
    if name in LOT_FIELDS or name == "document_id":
        return re.sub(r"\s+", "", value).upper()
    if name in ("area", "jurisdiction", "destination_country"):
        return fold(value)
    if name.startswith("qc:"):
        f = fold(value)
        if f in ("not tested", "missing", "n/a", "-", ""):
            return "not tested"
        m = re.search(r"[\d.,]+", f)
        return f"{float(m.group(0).replace(',', '.')):g}" if m else None
    if name.startswith("limit:"):
        m = re.search(r"(<=|>=|<|>|≤|≥)\s*([\d.,]+)", value)
        return f"{m.group(1).replace('≤', '<=').replace('≥', '>=')} {float(m.group(2).replace(',', '.')):g}" if m else None
    return re.sub(r"\s+", " ", value).strip()


# ------------------------------------------------------------------ PDF reading
def validate(data: bytes, filename: str) -> None:
    if len(data) > MAX_BYTES:
        raise OpsError(413, "file is larger than 10 MB")
    if not data.startswith(b"%PDF-"):
        raise OpsError(415, "only PDF files are accepted")


def safe_name(filename: str | None) -> str:
    base = re.split(r"[\\/]", filename or "")[-1]
    base = re.sub(r"[^\w\-. ()]", "_", base).strip(" .")[:120]
    return base if base.lower().endswith(".pdf") else (base or "document") + ".pdf"


def _axis_aligned(o) -> bool:
    if o.get("object_type") != "char":
        return True
    m = o.get("matrix") or (1, 0, 0, 1, 0, 0)
    return abs(m[1]) < 1e-3 and abs(m[2]) < 1e-3  # rotated text is a stamp or watermark, not a field


def read_pdf(data: bytes) -> dict:
    """→ {pages: [{n, text, lines, image_only}], encrypted, error}"""
    import pdfplumber
    if re.search(rb"/Encrypt\s", data[-4096:]) or re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data):
        return {"pages": [], "encrypted": True, "error": "the PDF is password-protected or encrypted; upload an unprotected copy"}
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 - any parser failure means the file is unreadable
        name = type(e).__name__
        if "Password" in name or "Encrypt" in name:
            return {"pages": [], "encrypted": True, "error": "the PDF is password-protected or encrypted; upload an unprotected copy"}
        return {"pages": [], "error": f"cannot be opened as a PDF ({name})"}
    out = []
    try:
        if len(pdf.pages) > MAX_PAGES:
            return {"pages": [], "error": f"more than {MAX_PAGES} pages"}
        for i, pg in enumerate(pdf.pages):
            text = pg.filter(_axis_aligned).extract_text() or ""
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            content = [ln for ln in lines if "SYNTHETIC DEMO" not in ln.upper()]
            out.append({"n": i + 1, "text": text, "lines": lines, "image_only": not content and bool(pg.images)})
    except Exception as e:  # noqa: BLE001
        return {"pages": out, "error": f"damaged PDF structure ({type(e).__name__})"}
    finally:
        pdf.close()
    if not out:
        return {"pages": [], "error": "the PDF has no pages"}
    return {"pages": out, "error": None}


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


def classify(pages: list[dict]) -> tuple[str, float]:
    text = fold(" \n ".join(p["text"] for p in pages))
    titles = fold(" \n ".join(" ".join(p["lines"][:3]) for p in pages))
    best, score = "unknown", 0.0
    for kind, kws in KIND_KEYWORDS.items():
        s = sum(2.0 if kw in titles else 1.0 if kw in text else 0 for kw in kws)
        if s > score:
            best, score = kind, s
    return best, (0.95 if score >= 2 else 0.6 if score else 0.0)


COA_ROW = re.compile(r"^(?P<a>[A-Za-z][A-Za-z \-]+?)\s+(?P<r>not tested|missing|n/a|[\d.,]+\s*%?)\s+(?P<l>(?:<=|>=|<|>|≤|≥)\s*[\d.,]+\s*%?)$", re.I)


def extract_fields(pages: list[dict]) -> list[dict]:
    found: dict[str, dict] = {}
    for p in pages:
        for ln in p["lines"]:
            if "SYNTHETIC DEMO" in ln.upper():
                continue
            if ":" in ln:
                left, right = ln.split(":", 1)
                key = fold(left)
                for alias, name in _ALIAS:
                    if key == alias:
                        val = right.strip()
                        if val and name not in found:
                            found[name] = {"name": name, "value": val, "page": p["n"], "snippet": ln[:200], "confidence": 0.95, "method": EXTRACTOR}
                        break
                continue
            if m := COA_ROW.match(ln):
                a = fold(m.group("a"))
                found.setdefault(f"qc:{a}", {"name": f"qc:{a}", "value": m.group("r").strip(), "page": p["n"], "snippet": ln[:200],
                                             "confidence": 0.9, "method": EXTRACTOR})
                found.setdefault(f"limit:{a}", {"name": f"limit:{a}", "value": m.group("l").strip(), "page": p["n"], "snippet": ln[:200],
                                                "confidence": 0.9, "method": EXTRACTOR})
    out = []
    for f in found.values():
        f["normalised"] = normalise(f["name"], f["value"])
        if f["normalised"] is None and f["name"] in QUANTITY_FIELDS | DATE_FIELDS:
            f["confidence"] = 0.5  # read but could not be interpreted
        out.append(f)
    return out


def llm_fill(kind: str, pages: list[dict], fields: list[dict]) -> list[dict]:
    """Ask Groq only for expected fields the rules missed; keep a value only if it occurs verbatim in the page text."""
    if os.environ.get("OPS_LLM_EXTRACTION", "1") == "0":
        return []
    from .. import providers
    if not providers.configured().get("groq"):
        return []
    have = {f["name"] for f in fields}
    missing = [n for n in EXPECTED.get(kind, []) if n not in have]
    if not missing:
        return []
    text = "\n".join(f"[page {p['n']}]\n" + "\n".join(ln for ln in p["lines"] if "SYNTHETIC DEMO" not in ln.upper()) for p in pages)[:6000]
    try:
        r = providers.llm_json("You extract fields from a harvest/trade document. Copy values exactly as written. Use null when absent.",
                                f"Fields wanted: {', '.join(missing)}\n\nDocument text:\n{text}",
                                '{"fields": {"<name>": {"value": "<exact text or null>", "page": <int or null>}}}', max_tokens=500)
    except Exception:  # noqa: BLE001 - extraction falls back to rules only
        return []
    out = []
    for name, v in (r["data"].get("fields") or {}).items():
        val = (v or {}).get("value") if isinstance(v, dict) else None
        if name not in missing or not isinstance(val, str) or not val.strip():
            continue
        page = next((p for p in pages if val.strip() in p["text"]), None)
        if not page:  # not grounded in the text: discard
            continue
        snippet = next((ln for ln in page["lines"] if val.strip() in ln), val)[:200]
        out.append({"name": name, "value": val.strip(), "page": page["n"], "snippet": snippet, "confidence": 0.6,
                    "method": f"llm-grounded:{r.get('model')}", "normalised": normalise(name, val.strip())})
    return out


def analyse(data: bytes, use_llm: bool = True) -> dict:
    """Pure analysis of one PDF (no database). Used by ingest and by the benchmark."""
    t0 = time.time()
    rd = read_pdf(data)
    synthetic = any("SYNTHETIC DEMO" in p["text"].upper() for p in rd["pages"])
    if rd["error"]:
        return {"status": "rejected", "reason": rd["error"], "kind": "unknown", "kind_confidence": 0.0, "fields": [], "pages": len(rd["pages"]),
                "synthetic_marked": synthetic, "latency_ms": round((time.time() - t0) * 1000, 1)}
    pages = rd["pages"]
    if pages and all(p["image_only"] for p in pages):
        status = "needs-ocr"
        reason = "image-only scan" + ("" if ocr_available() else "; no OCR engine is installed, so nothing was guessed")
        return {"status": status, "reason": reason, "kind": "unknown", "kind_confidence": 0.0, "fields": [], "pages": len(pages),
                "synthetic_marked": synthetic, "latency_ms": round((time.time() - t0) * 1000, 1)}
    kind, kc = classify(pages)
    fields = extract_fields(pages)
    if use_llm:
        fields += llm_fill(kind, pages, fields)
    missing = [n for n in EXPECTED.get(kind, []) if n not in {f["name"] for f in fields}]
    return {"status": "extracted" if kind != "unknown" else "needs-review", "reason": None, "kind": kind, "kind_confidence": kc,
            "fields": fields, "missing_expected": missing, "pages": len(pages), "synthetic_marked": synthetic,
            "latency_ms": round((time.time() - t0) * 1000, 1)}


# ------------------------------------------------------------------ cross-document rules (pure)
def _ev(doc, f):
    return {"doc": doc["filename"], "field": f["name"], "value": f.get("value"), "page": f.get("page"), "snippet": f.get("snippet")}


def _cmp(op, a, b):
    return {"<=": a <= b, "<": a < b, ">=": a >= b, ">": a > b}[op]


def cross_check(ctx: dict, docs: list[dict], known_lots: set[str] | None = None, cites_listed: bool | None = None) -> list[dict]:
    """ctx: passport {species (accepted), organ, jurisdiction}. docs: [{filename, kind, status, sha256, fields: {name: field}}]."""
    issues: list[dict] = []

    def add(rule, severity, category, message, evidence):
        issues.append({"rule": rule, "severity": severity, "category": category, "message": message, "evidence": evidence})

    known_lots = {x.upper() for x in (known_lots or set())}
    for d in docs:
        if d["status"] == "rejected":
            add("document_unreadable", "review", "Unreadable file", f"{d['filename']} could not be read ({d.get('reason') or 'damaged'}). "
                "Upload a clean copy; nothing from it was used.", [{"doc": d["filename"]}])
        elif d["status"] == "needs-ocr":
            add("needs_ocr", "review", "Needs a person to read it", f"{d['filename']} is an image-only scan. No text was extracted and nothing "
                "was guessed; enter its values by hand or upload a text PDF.", [{"doc": d["filename"]}])
    live = [d for d in docs if d["status"] not in ("rejected", "needs-ocr")]
    F = lambda d, n: d["fields"].get(n)  # noqa: E731
    for d in live:
        miss = [n for n in EXPECTED.get(d["kind"], []) if not (F(d, n) or {}).get("value")]
        if miss:
            add("fields_not_found", "review", "Fields not found", f"{d['filename']}: could not find {', '.join(m.replace('_', ' ') for m in miss)}. "
                "Checks that need these values were skipped, not passed; enter them by hand.", [{"doc": d["filename"], "field": m} for m in miss])

    # species
    accepted = species_name(ctx.get("species"))[0]
    for d in live:
        f = F(d, "species")
        if not f or not f.get("value"):
            continue
        name, syn = species_name(f["value"])
        if name and accepted and name != accepted:
            add("species_mismatch", "mismatch", "Species", f"{d['filename']} names {f['value']}, not {accepted}.", [_ev(d, f)])
        elif syn:
            add("species_synonym", "consistent", "Species", f"{d['filename']} uses the synonym {f['value']} for {accepted}; confirm the "
                "issuer means the same plant.", [_ev(d, f)])
    # organ
    want = organ_parts(ctx.get("organ"))
    for d in live:
        f = F(d, "organ")
        if f and f.get("value") and want and organ_name(f["value"]) not in want:
            add("organ_mismatch", "mismatch", "Harvested part", f"{d['filename']} records {f['value']}; this passport covers {ctx.get('organ')}.", [_ev(d, f)])
    # authorisation window and quantity
    auths = [d for d in live if d["kind"] == "authorisation"]
    weighs, seen = [], set()
    for d in live:
        if d["kind"] == "weigh_in":
            key = (F(d, "document_id") or {}).get("normalised") or d.get("sha256")
            if key in seen:
                continue
            seen.add(key)
            weighs.append(d)
    for a in auths:
        vf, vu = (F(a, "valid_from") or {}).get("normalised"), (F(a, "valid_until") or {}).get("normalised")
        for d in [x for x in live if x["kind"] in ("weigh_in", "collection_plan")]:
            f = F(d, "collection_date")
            dt = (f or {}).get("normalised")
            if dt and ((vf and dt < vf) or (vu and dt > vu)):
                add("date_outside_authorisation", "mismatch", "Authorisation dates",
                    f"{d['filename']} is dated {dt}, outside the authorisation window {vf or '?'} to {vu or '?'} in {a['filename']}.",
                    [_ev(d, f)] + [_ev(a, x) for x in (F(a, "valid_from"), F(a, "valid_until")) if x])
        aq = parse_quantity((F(a, "authorised_quantity") or {}).get("value"))
        if aq and weighs:
            qs = [(d, F(d, "quantity"), parse_quantity((F(d, "quantity") or {}).get("value"))) for d in weighs]
            same = [(d, f, q) for d, f, q in qs if q and (q[1] or "fresh") == (aq[1] or "fresh")]
            total = sum(q[0] for _, _, q in same)
            if total > aq[0] * 1.0001:
                add("quantity_exceeds_authorised", "mismatch", "Quantity",
                    f"Weigh-in slips total {total / 1000:g} kg {aq[1] or ''}, above the {aq[0] / 1000:g} kg authorised in {a['filename']}.",
                    [_ev(d, f) for d, f, _ in same] + [_ev(a, F(a, "authorised_quantity"))])
        # area
        aa = F(a, "area")
        for d in [x for x in live if x["kind"] in ("collection_plan", "monitoring")]:
            f = F(d, "area")
            if aa and f and aa.get("normalised") and f.get("normalised") and aa["normalised"] != f["normalised"]:
                add("area_mismatch", "mismatch", "Collection area", f"{d['filename']} names {f['value']}; {a['filename']} authorises {aa['value']}.",
                    [_ev(d, f), _ev(a, aa)])
    # lot traceability
    produced = set(known_lots)
    for d in live:
        if d["kind"] == "weigh_in" and F(d, "lot_code"):
            produced.add(F(d, "lot_code")["normalised"])
        if d["kind"] == "drying_log":
            for n in ("input_lot", "output_lot"):
                if F(d, n):
                    produced.add(F(d, n)["normalised"])
    if produced:
        for d in live:
            if d["kind"] in ("batch_statement", "coa", "invoice") and F(d, "lot_code"):
                f = F(d, "lot_code")
                if f["normalised"] not in produced and not (d["kind"] != "batch_statement" and any(
                        x["kind"] == "batch_statement" and (F(x, "lot_code") or {}).get("normalised") == f["normalised"] and
                        (F(x, "lot_code") or {}).get("normalised") in produced for x in live)):
                    add("lot_not_traceable", "mismatch", "Lot / batch", f"{d['filename']} refers to lot {f['value']}, which no collection, "
                        "drying record or ledger lot produced.", [_ev(d, f)])
    # duplicates
    by_key: dict = {}
    for d in live:
        idf = (F(d, "document_id") or {}).get("normalised")
        for key in filter(None, [d.get("sha256") and ("sha", d["sha256"]), idf and (d["kind"], idf)]):
            by_key.setdefault(key, []).append(d)
    dup_seen = set()
    for key, ds in by_key.items():
        names = tuple(sorted(x["filename"] for x in ds))
        if len(ds) > 1 and names not in dup_seen:
            dup_seen.add(names)
            add("duplicate_document", "mismatch", "Duplicate record", f"{', '.join(names)} are the same record ({key[1][:16]}); count it once.",
                [{"doc": x["filename"], "field": "document_id", "value": (F(x, "document_id") or {}).get("value")} for x in ds])
    # drying mass balance
    for d in live:
        if d["kind"] != "drying_log":
            continue
        q = {n: parse_quantity((F(d, n) or {}).get("value")) for n in ("fresh_input", "dry_output", "moisture_loss", "rejected", "waste")}
        if q["fresh_input"] and q["dry_output"]:
            gap = q["fresh_input"][0] - sum(q[n][0] for n in ("dry_output", "moisture_loss", "rejected", "waste") if q[n])
            from .ledger import tolerance_for
            tol = tolerance_for(q["fresh_input"][0])
            if abs(gap) > tol:
                add("mass_balance_gap", "review", "Mass balance", f"{d['filename']}: {gap / 1000:.2f} kg is not explained by output, water loss, "
                    "rejected material or waste. Record what happened; this is a reconciliation gap, not an accusation.",
                    [_ev(d, F(d, n)) for n in q if F(d, n)])
    # lab results
    for d in live:
        for name, f in d["fields"].items():
            if not name.startswith("qc:"):
                continue
            a = name[3:]
            lim = d["fields"].get(f"limit:{a}")
            if f.get("normalised") == "not tested":
                add("coa_missing_result", "missing", "Lab result", f"{d['filename']}: no result for {a} although a limit is documented.",
                    [_ev(d, f)] + ([_ev(d, lim)] if lim else []))
            elif lim and lim.get("normalised") and f.get("normalised"):
                op, val = lim["normalised"].split(" ")
                if not _cmp(op, float(f["normalised"]), float(val)):
                    add("coa_out_of_range", "mismatch", "Lab result", f"{d['filename']}: {a} {f['value']} is outside the documented limit {lim['value']}. "
                        "A quality reviewer decides what happens to the lot.", [_ev(d, f), _ev(d, lim)])
    # cross-border trade of a CITES-listed plant
    for d in live:
        f = F(d, "destination_country")
        if f and f.get("normalised") and ctx.get("jurisdiction") and f["normalised"] != fold(ctx["jurisdiction"]):
            if cites_listed is not False:
                add("cites_cross_border", "jurisdiction", "CITES / export", f"{d['filename']} ships to {f['value']} from {ctx['jurisdiction']}. "
                    + ("The species is CITES-listed: confirm export/import documents with the CITES Management Authority."
                       if cites_listed else "CITES status is unknown: check before export."), [_ev(d, f)])
    return issues


# ------------------------------------------------------------------ persistence
ISSUE_TASK = {  # rule → (blocking, phase, owner)
    "species_mismatch": (True, "planned", "scientific-reviewer"), "organ_mismatch": (True, "planned", "manager"),
    "date_outside_authorisation": (True, "planned", "manager"), "quantity_exceeds_authorised": (True, "collected", "manager"),
    "area_mismatch": (True, "planned", "manager"), "lot_not_traceable": (True, "quality-review", "manager"),
    "duplicate_document": (True, "processing", "manager"), "mass_balance_gap": (False, "processing", "manager"),
    "coa_out_of_range": (True, "ready-for-authorised-human-review", "quality-reviewer"),
    "coa_missing_result": (True, "ready-for-authorised-human-review", "quality-reviewer"),
    "cites_cross_border": (True, "transferred", "manager"), "needs_ocr": (False, "planned", "manager"),
    "document_unreadable": (False, "planned", "manager"), "fields_not_found": (False, "planned", "manager"),
}


def _doc_rows(c, ws, pid):
    docs = []
    for d in rows(c.execute("SELECT * FROM ops_document WHERE workspace=? AND passport_id=? ORDER BY created", (ws, pid))):
        fs = rows(c.execute("SELECT * FROM ops_field WHERE document_id=?", (d["id"],)))
        ex = json.loads(d["extraction"] or "{}")
        docs.append({**d, "kind": d["doc_kind"], "reason": ex.get("reason"), "fields": {f["name"]: f for f in fs}})
    return docs


def recheck(c, ws: str, role: str, pid: str) -> list[dict]:
    from .tasks import add_task
    p = c.execute("SELECT * FROM ops_passport WHERE workspace=? AND id=?", (ws, pid)).fetchone()
    if not p:
        raise OpsError(404, "passport not found")
    p = dict(p)
    pf = json.loads(p["prefill"] or "{}")
    cites = (pf.get("cites") or {}).get("value") or {}
    listed = cites.get("listed") if cites.get("status") == "available" else None
    lots = {r[0] for r in c.execute("SELECT code FROM ops_lot WHERE workspace=? AND passport_id=?", (ws, pid))}
    docs = _doc_rows(c, ws, pid)
    issues = cross_check({"species": p["accepted_name"], "organ": p["organ"], "jurisdiction": p["jurisdiction"]}, docs, lots, listed)
    now = time.time()
    c.execute("DELETE FROM ops_issue WHERE workspace=? AND passport_id=?", (ws, pid))
    keep = set()
    for i in issues:
        dk = hashlib.sha1(json.dumps([i["rule"], i["message"]]).encode()).hexdigest()[:16]
        c.execute("INSERT OR IGNORE INTO ops_issue VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (nid("iss"), ws, pid, i["rule"], i["severity"], i["category"], i["message"], json.dumps(i["evidence"]), "open", dk, now, now))
        if i["severity"] != "consistent" and i["rule"] in ISSUE_TASK:
            if i["rule"] == "cites_cross_border" and c.execute(
                    "SELECT 1 FROM ops_task WHERE workspace=? AND passport_id=? AND dedupe='cites:screen'", (ws, pid)).fetchone():
                continue  # the passport already carries its CITES screening task
            blocking, phase, owner = ISSUE_TASK[i["rule"]]
            first = re.split(r"(?<=[a-z0-9%)])\. ", i["message"], maxsplit=1)[0].rstrip(".")
            add_task(c, ws, pid, f"{i['category']}: {first[:110]}", i["message"], kind="document", phase=phase, blocking=blocking,
                     owner_role=owner, source=f"document-check:{i['rule']}", dedupe=f"doc:{dk}")
            c.execute("UPDATE ops_task SET status='open', resolution=NULL, updated=? WHERE workspace=? AND passport_id=? AND dedupe=? "
                      "AND resolution LIKE 'cleared automatically%'", (now, ws, pid, f"doc:{dk}"))
            keep.add(f"doc:{dk}")
    # issues that disappeared (e.g. after a correction) close their open tasks automatically, with a note
    for t in rows(c.execute("SELECT id, dedupe FROM ops_task WHERE workspace=? AND passport_id=? AND kind='document' AND status IN ('open','in-review')",
                            (ws, pid))):
        if t["dedupe"] not in keep:
            c.execute("UPDATE ops_task SET status='resolved', resolution=?, updated=? WHERE id=?",
                      ("cleared automatically: the cross-document check no longer finds this issue", now, t["id"]))
    audit(c, ws, role, "passport", pid, "document_check", {"issues": len(issues)})
    return issues


def ingest(ws: str, role: str, pid: str, filename: str, data: bytes) -> dict:
    ensure()
    if role not in ("collector", "manager", "quality-reviewer", "admin"):
        raise OpsError(403, "this role cannot upload documents")
    validate(data, filename)
    filename = safe_name(filename)
    sha = hashlib.sha256(data).hexdigest()
    with conn() as c:
        p = c.execute("SELECT synthetic FROM ops_passport WHERE workspace=? AND id=?", (ws, pid)).fetchone()
        if not p:
            raise OpsError(404, "passport not found")
    a = analyse(data)
    DOC_DIR.mkdir(parents=True, exist_ok=True)
    path = DOC_DIR / f"{sha}.pdf"
    if not path.exists():
        path.write_bytes(data)
    did = nid("doc")
    now = time.time()
    with LOCK, conn() as c:
        ver = (c.execute("SELECT MAX(version) FROM ops_document WHERE workspace=? AND passport_id=? AND filename=?", (ws, pid, filename)).fetchone()[0] or 0) + 1
        lot = next((f["normalised"] for f in a["fields"] if f["name"] == "lot_code"), None)
        c.execute("INSERT INTO ops_document VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (did, ws, pid, lot, filename, sha, "application/pdf", len(data), a["pages"], a["kind"], a["kind_confidence"], role,
                   "workspace", a["status"], ISSUER_NOTE, int(a["synthetic_marked"]),
                   json.dumps({"reason": a.get("reason"), "missing_expected": a.get("missing_expected", [])}),
                   EXTRACTOR, a["latency_ms"], ver, path.name, now))
        for f in a["fields"]:
            c.execute("INSERT INTO ops_field VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (nid("fld"), did, f["name"], f["value"], f["normalised"], f["value"], f["page"], f["snippet"], f["confidence"],
                       f["method"], "extracted", None, now))
        c.execute("INSERT INTO ops_passport_event VALUES (?,?,?,?,?,?,?,?,?)",
                  (nid("pev"), pid, now, role, "document", None, None, f"{filename} read as {KIND_LABEL.get(a['kind'], a['kind'])} ({a['status']})", None))
        audit(c, ws, role, "document", did, "upload", {"filename": filename, "sha256": sha, "kind": a["kind"], "status": a["status"]})
        issues = recheck(c, ws, role, pid)
    from .passport import _trigger
    _trigger(ws, pid, "document_uploaded")
    return {"document": document(ws, did), "issues": issues}


def document(ws: str, did: str) -> dict:
    with conn() as c:
        d = c.execute("SELECT * FROM ops_document WHERE workspace=? AND id=?", (ws, did)).fetchone()
        if not d:
            raise OpsError(404, "document not found")
        d = loads(dict(d), "extraction")
        d["extraction"] = {**(d["extraction"] or {}), "fields": rows(c.execute("SELECT * FROM ops_field WHERE document_id=? ORDER BY page, name", (did,)))}
        d.pop("stored_path", None)
        return d


def correct_field(ws: str, role: str, fid: str, value: str, reason: str) -> dict:
    ensure()
    if role not in ("manager", "quality-reviewer", "scientific-reviewer", "admin"):
        raise OpsError(403, "only reviewers or managers correct extracted fields")
    if not (reason or "").strip():
        raise OpsError(422, "a reason is required for a correction")
    with LOCK, conn() as c:
        f = c.execute("SELECT f.*, d.workspace, d.passport_id FROM ops_field f JOIN ops_document d ON d.id=f.document_id WHERE f.id=?", (fid,)).fetchone()
        if not f or f["workspace"] != ws:
            raise OpsError(404, "field not found")
        now = time.time()
        c.execute("INSERT INTO ops_field_correction VALUES (?,?,?,?,?,?,?)", (nid("cor"), fid, f["value"], value, role, reason, now))
        c.execute("UPDATE ops_field SET value=?, normalised=?, status='corrected', corrected_by=?, method=?, confidence=1.0, updated=? WHERE id=?",
                  (value, normalise(f["name"], value), role, "reviewer-corrected", now, fid))
        audit(c, ws, role, "field", fid, "correct", {"from": f["value"], "to": value, "reason": reason})
        issues = recheck(c, ws, role, f["passport_id"])
    return {"field_id": fid, "issues": issues}


def file_path(ws: str, did: str):
    """Path of a stored upload in this workspace, or None. Stored names are content hashes, so no user text reaches the path."""
    with conn() as c:
        d = c.execute("SELECT stored_path, filename FROM ops_document WHERE workspace=? AND id=?", (ws, did)).fetchone()
    if not d or not re.fullmatch(r"[0-9a-f]{64}\.pdf", d["stored_path"] or ""):
        return None
    p = DOC_DIR / d["stored_path"]
    return (p, safe_name(d["filename"])) if p.exists() else None


def _today() -> str:
    return datetime.now().date().isoformat()
