"""Harvest Methods: what each harvested plant part and method puts at risk, with open-licence photos and cited sources.

The catalogue is descriptive (which life process a method touches, what to measure). It never states a safe rate,
quota or intensity. Photos come from Openverse (CC0 / CC BY / CC BY-SA only), are cached and served from our origin,
and are labelled as search results that may not show the named species.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

import httpx

from . import media

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache" / "openverse"
TTL = 30 * 86400
OPENVERSE = "https://api.openverse.org/v1/images/"
OPEN_LICENCES = {"cc0": "CC0 1.0", "by": "CC BY", "by-sa": "CC BY-SA", "pdm": "Public Domain Mark"}
PHOTO_NOTE = "Search result · not expert-checked · may not show this species"
_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Event] = {}

REFS = {
    "ticktin-2004": {"title": "Ticktin T (2004) The ecological implications of harvesting non-timber forest products. J Appl Ecol 41:11–21",
                     "url": "https://doi.org/10.1111/j.1365-2664.2004.00859.x"},
    "rijkers-2006": {"title": "Rijkers T et al. (2006) The effect of tapping for frankincense on sexual reproduction in Boswellia papyrifera. "
                              "J Appl Ecol 43:1188–1195", "url": "https://doi.org/10.1111/j.1365-2664.2006.01215.x"},
    "martinez-2015": {"title": "Martínez-Ballesté A, Martorell C (2015) Effects of harvest on the sustainability and leaf productivity of populations "
                               "of two palm species in Maya homegardens. PLoS ONE 10(3):e0120666", "url": "https://doi.org/10.1371/journal.pone.0120666"},
    "cites-pc25-27": {"title": "CITES PC25 Doc. 27: Prunus africana (bark harvest and management)",
                      "url": "https://cites.org/sites/default/files/eng/com/pc/25/E-PC25-27.pdf"},
    "ghimire-2008": {"title": "Ghimire SK et al. (2008) Demographic variation and population viability in a threatened Himalayan medicinal and "
                              "aromatic herb Nardostachys grandiflora: matrix modelling of harvesting effects in two contrasting habitats. "
                              "J Appl Ecol 45:41–51", "url": "https://doi.org/10.1111/j.1365-2664.2007.01375.x"},
    "fairwild-3": {"title": "FairWild Standard Version 3.0 (2023)", "url": "https://www.fairwild.org/s/FairWildStandard-V3-FINAL.pdf"},
}

# process ids match evidence_agent.PART_PROCESSES; text is plain language
ORGANS = [
    {"id": "root", "label": "Roots & rhizomes", "agent_organ": "rhizome", "process": "survival",
     "summary": "Digging up underground parts usually kills the plant or the dug part, so harvest falls directly on survival.",
     "methods": [
         {"id": "whole-dig", "label": "Whole-plant digging", "touches": "survival", "note": "Removes the individual. Effect depends on which sizes are dug.",
          "measure": ["share of plants dug per size class", "seedling and juvenile counts after harvest"]},
         {"id": "partial-rhizome", "label": "Partial rhizome cutting, replanting the crown", "touches": "survival and growth",
          "note": "Leaves part of the rhizome to regrow; regrowth must be checked, not assumed.",
          "measure": ["regrowth of cut plants the next season", "time to reach harvestable size again"]},
     ], "refs": ["ghimire-2008", "ticktin-2004"], "queries": ["rhizome harvesting", "root harvest medicinal plant", "digging roots"]},
    {"id": "bark", "label": "Bark", "agent_organ": "bark", "process": "survival and growth of established plants",
     "summary": "Bark stripping wounds the tree. Large trees carry most of the population's growth, so their survival matters most.",
     "methods": [
         {"id": "panels", "label": "Strip panels from opposite sides", "touches": "survival and growth",
          "note": "CITES guidance for Prunus africana discusses harvesting opposing quarters so the tree can recover between harvests.",
          "measure": ["bark regrowth on the wound", "tree survival after 2–5 years"]},
         {"id": "girdling", "label": "Girdling or full stripping", "touches": "survival", "note": "Removing bark all round the stem usually kills the tree.",
          "measure": ["deaths among stripped trees"]},
         {"id": "felling", "label": "Felling then stripping", "touches": "survival", "note": "Kills the tree; only regeneration replaces it.",
          "measure": ["recruitment of young trees"]},
     ], "refs": ["cites-pc25-27", "ticktin-2004"], "queries": ["bark stripping tree", "bark harvesting", "debarked tree trunk"]},
    {"id": "resin", "label": "Resin & latex (tapping)", "agent_organ": "resin (stem tapping)", "process": "reproduction",
     "summary": "Tapping diverts the tree's resources. In Boswellia, tapped trees produced fewer flowers, fruits and seeds.",
     "methods": [
         {"id": "tapping", "label": "Stem tapping (incisions)", "touches": "reproduction", "note": "Rijkers et al. 2006 found tapping reduced flower, fruit and seed production.",
          "measure": ["flowering and seed set of tapped vs untapped trees", "seedling recruitment"]},
         {"id": "rest", "label": "Resting periods between tapping seasons", "touches": "reproduction", "note": "Whether rest restores seed set must be measured locally.",
          "measure": ["seed set after a rest year"]},
     ], "refs": ["rijkers-2006", "ticktin-2004"], "queries": ["frankincense tapping", "resin tapping tree", "boswellia resin"]},
    {"id": "leaf", "label": "Leaves & fronds", "agent_organ": "leaf", "process": "growth",
     "summary": "Leaf harvest mostly slows growth. A palm study found leaf harvest did not change population growth rate.",
     "methods": [
         {"id": "partial-leaf", "label": "Partial leaf removal, leaving the growing point", "touches": "growth",
          "note": "Martínez-Ballesté & Martorell 2015 report no effect of leaf harvest on λ for Sabal yapa in homegardens.",
          "measure": ["new leaves per plant per year", "share of leaves removed"]},
         {"id": "cut-heart", "label": "Cutting the growing point (palm heart)", "touches": "survival", "note": "Kills single-stemmed palms.",
          "measure": ["deaths among harvested plants"]},
     ], "refs": ["martinez-2015", "ticktin-2004"], "queries": ["palm leaf harvest", "leaf harvesting", "harvesting leaves"]},
    {"id": "flower", "label": "Flowers", "agent_organ": "flower", "process": "reproduction",
     "summary": "Taking flowers removes next year's seed. The cost depends on how much the population relies on seed.",
     "methods": [
         {"id": "pick-flowers", "label": "Picking flower heads", "touches": "reproduction", "note": "Leaving a share of flowers for seed is common practice; the share is not given here.",
          "measure": ["seed set of remaining flowers", "seedling counts"]},
     ], "refs": ["ticktin-2004", "fairwild-3"], "queries": ["flower harvest medicinal", "picking flowers", "arnica flowers harvest"]},
    {"id": "fruit", "label": "Fruits & seeds", "agent_organ": "fruit", "process": "reproduction",
     "summary": "Fruit and seed harvest reduces recruitment. Long-lived plants often depend little on new seedlings; short-lived ones depend a lot.",
     "methods": [
         {"id": "collect-fallen", "label": "Collecting fallen fruit", "touches": "reproduction", "note": "Does not harm the parent, but takes seed out of the system.",
          "measure": ["seedling recruitment in harvested vs unharvested areas"]},
         {"id": "cut-branches", "label": "Cutting branches to reach fruit", "touches": "survival and reproduction", "note": "Damages the parent as well as removing seed.",
          "measure": ["canopy damage", "next year's fruit set"]},
     ], "refs": ["ticktin-2004"], "queries": ["fruit harvesting wild", "seed collection forest", "nut harvesting"]},
    {"id": "whole", "label": "Whole herb", "agent_organ": "whole plant", "process": "survival",
     "summary": "Harvesting the whole above-ground plant or uprooting it falls on survival and, before seeding, on reproduction.",
     "methods": [
         {"id": "uproot", "label": "Uprooting", "touches": "survival", "note": "Removes the individual.", "measure": ["plants remaining per plot"]},
         {"id": "cut-above", "label": "Cutting above ground, leaving roots", "touches": "growth and reproduction", "note": "Perennials may resprout; check it.",
          "measure": ["resprouting next season", "flowering of resprouts"]},
     ], "refs": ["ticktin-2004", "fairwild-3"], "queries": ["wild herb harvesting", "medicinal herb collection", "harvesting herbs"]},
]
ORGAN_BY_ID = {o["id"]: o for o in ORGANS}
_ALIASES = {"rhizome": "root", "roots": "root", "tuber": "root", "bulb/tuber": "root", "leaves": "leaf", "fronds": "leaf", "foliage": "leaf", "seed": "fruit", "seeds": "fruit",
            "whole plant": "whole", "herb": "whole", "resin (stem tapping)": "resin", "latex": "resin", "bark + foliage": "bark", "stem": "bark"}


def organ_id(organ: str | None) -> str | None:
    o = (organ or "").strip().lower()
    if o in ORGAN_BY_ID:
        return o
    if o in _ALIASES:
        return _ALIASES[o]
    for k in ORGAN_BY_ID:
        if k in o:
            return k
    return None


def catalogue() -> dict:
    return {"organs": [{**o, "refs": [{"id": r, **REFS[r]} for r in o["refs"]]} for o in ORGANS], "photo_note": PHOTO_NOTE,
            "disclaimer": "Descriptive only: which life process a method touches and what to measure. No safe rate, quota or permit is implied."}


# ------------------------------------------------------------------------------------------------ Openverse photos
def _clean_query(q: str) -> str:
    return re.sub(r"[^\w\s\-]", " ", q).strip()[:80]


def _key(q: str) -> str:
    return hashlib.sha256(q.lower().encode()).hexdigest()[:20]


def openverse(q: str, n: int = 6) -> list[dict]:
    """Openverse image search restricted to open licences. Returns metadata only; raises httpx errors to the caller."""
    r = httpx.get(OPENVERSE, params={"q": q, "license": ",".join(OPEN_LICENCES), "page_size": n, "mature": "false"},
                  headers=media.UA, timeout=20)
    r.raise_for_status()
    out = []
    for x in r.json().get("results", []):
        lic = (x.get("license") or "").lower()
        if lic not in OPEN_LICENCES or not x.get("thumbnail"):
            continue  # filter again on our side: never trust the query filter alone
        out.append({"id": x["id"], "title": (x.get("title") or "untitled")[:140], "creator": x.get("creator") or "unknown",
                    "licence": f"{OPEN_LICENCES[lic]} {x.get('license_version') or ''}".strip(), "licence_url": x.get("license_url"),
                    "landing": x.get("foreign_landing_url"), "provider": x.get("provider"), "thumb": x["thumbnail"]})
    return out


def photos(q: str, n: int = 6) -> dict:
    """Cached search; images downloaded once and served from /api/methods/photo/{id}. In-flight requests are de-duplicated."""
    q = _clean_query(q)
    if len(q) < 3:
        return {"query": q, "photos": [], "status": "query too short"}
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{_key(q)}.json"
    if f.exists():
        hit = json.loads(f.read_text(encoding="utf-8"))
        if hit.get("photos") or time.time() - f.stat().st_mtime < TTL:  # found photos are kept for good
            return hit
    with _LOCK:
        ev = _INFLIGHT.get(q)
        mine = ev is None
        if mine:
            ev = _INFLIGHT[q] = threading.Event()
    if not mine:
        ev.wait(30)
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"query": q, "photos": [], "status": "busy"}
    try:
        try:
            found = openverse(q, n + 2)
        except httpx.HTTPError as e:
            return {"query": q, "photos": [], "status": f"Openverse unavailable ({type(e).__name__})"}
        kept = []
        for p in found:
            img = CACHE / f"{p['id']}.img"
            if not img.exists():
                try:
                    data, mime = media._download(p["thumb"])
                except Exception:  # noqa: BLE001  - skip images that fail size/type checks
                    continue
                img.write_bytes(data)
                (CACHE / f"{p['id']}.mime").write_text(mime, encoding="utf-8")
            kept.append({k: v for k, v in p.items() if k != "thumb"} | {"src": f"/api/methods/photo/{p['id']}"})
            if len(kept) >= n:
                break
        body = {"query": q, "photos": kept, "status": "ok" if kept else "no open-licence results", "note": PHOTO_NOTE,
                "retrieved": time.strftime("%Y-%m-%d", time.gmtime())}
        f.write_text(json.dumps(body), encoding="utf-8")
        return body
    finally:
        with _LOCK:
            _INFLIGHT.pop(q, None)
        ev.set()


def photo_file(pid: str) -> tuple[Path, str] | None:
    if not re.fullmatch(r"[0-9a-f\-]{36}", pid):
        return None
    img, mime = CACHE / f"{pid}.img", CACHE / f"{pid}.mime"
    if not img.exists() or not mime.exists():
        return None
    m = mime.read_text(encoding="utf-8").strip()
    return (img, m) if m in media.IMAGE_TYPES else None


KIND_LABEL = {"part": "The harvested part", "technique": "Harvesting in practice", "tool": "Tools", "impact": "What harvest leaves behind",
              "processing": "After harvest: drying, sorting, selling", "use": "What the product becomes"}
CURATED_NOTE = "Openly licensed images chosen by eye · not expert-checked · a picture of a related species is labelled as such"


def _curated_group(recs: list[dict], species: str | None) -> list[dict]:
    out = []
    for r in recs:
        same = bool(species and r.get("species") and r["species"].lower() == species.lower())
        out.append(media.curated_public(r) | {"this_species": same,
                                              "shows": r.get("species") or "species not identified"})
    return sorted(out, key=lambda r: (not r["this_species"], list(KIND_LABEL).index(r["kind"])))


def photo_catalogue() -> dict:
    """Every curated part, technique and tool image, grouped by plant part then kind."""
    parts = media.curated().get("parts", [])
    groups = []
    for o in ORGANS:
        recs = [r for r in parts if r["organ"] == o["id"]]
        if recs:
            groups.append({"organ": o["id"], "label": o["label"],
                           "kinds": [{"kind": k, "label": KIND_LABEL[k], "photos": [media.curated_public(r) for r in recs if r["kind"] == k]}
                                     for k in KIND_LABEL if any(r["kind"] == k for r in recs)]})
    return {"groups": groups, "count": len(parts), "note": CURATED_NOTE, "kinds": KIND_LABEL}


def organ_photos(oid: str, species: str | None = None) -> dict:
    """Hand-picked images for the part when we have them; else curated queries plus a live species search with a generic fallback."""
    o = ORGAN_BY_ID.get(oid)
    if not o:
        return {"photos": [], "status": "unknown plant part"}
    cur = [r for r in media.curated().get("parts", []) if r["organ"] == oid]
    if cur:
        photos_ = _curated_group(cur, species)
        return {"photos": photos_, "status": "ok", "basis": "hand-picked images for this harvested part", "curated": True,
                "kinds": KIND_LABEL, "note": CURATED_NOTE}
    if species:
        r = photos(f"{species} {o['agent_organ'].split(' ')[0]}")
        if r["photos"]:
            return {**r, "basis": "species search"}
        species_status = r.get("status")
    else:
        species_status = None
    seen, out = set(), []
    for q in o["queries"]:
        for p in photos(q, 4)["photos"]:
            if p["id"] not in seen:
                seen.add(p["id"]); out.append({**p, "query": q})
    return {"photos": out[:8], "status": "ok" if out else "no open-licence results", "basis": "generic search for this harvested part",
            "species_status": species_status, "note": PHOTO_NOTE}
