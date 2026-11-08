"""Annotated botanical illustrations: which parts of the plant are harvested, and what our data says about each.

Hybrid by design. An image model (Gemini) only draws highlights and numbered markers on an openly licensed botanical
plate or photo; every word and number shown next to it comes from our own data (harvest studies, the methods
catalogue, matrix sensitivity, documented uses), so the model can never invent a label or a statistic.

Two tiers:
  curated  data/curated/illustrations/index.json: pre-baked species, marker positions checked by eye.
  dynamic  any other species: generated on request, cached, labelled "not checked".
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

from . import harvest as hv, media, methods

ROOT = Path(__file__).resolve().parents[2]
CURATED = ROOT / "data" / "curated" / "illustrations"
CACHE = ROOT / "data" / "cache" / "illustrations"
NOTE = ("AI-annotated illustration: an image model drew the highlights and numbered markers. Names and figures beside it "
        "come from EthnoHarvest data, not from the model.")
_LOCK = threading.Lock()
_INFLIGHT: dict[str, threading.Event] = {}

# Plain names for the parts a plate usually shows. Harvested parts come first in the marker order.
PART_LABEL = {"root": "Root / rhizome", "bark": "Bark", "resin": "Resin (from the trunk)", "leaf": "Leaves",
              "flower": "Flowers", "fruit": "Fruit / seeds", "whole": "Whole plant"}
CONTEXT_PARTS = {"root": ["leaf", "flower"], "bark": ["leaf", "fruit"], "resin": ["leaf", "flower"], "leaf": ["flower", "fruit"],
                 "flower": ["leaf", "root"], "fruit": ["leaf", "bark"], "whole": ["flower", "root"]}
VISUAL_HINT = {"root": "the underground root or rhizome", "bark": "the bark of the trunk or stem", "resin": "the trunk where resin is tapped",
               "leaf": "the leaves", "flower": "the flowers or flower heads", "fruit": "the fruits or seeds", "whole": "the whole above-ground plant"}


def _slug(species: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", species.lower()).strip("-")


def _organs(species: str) -> tuple[list[str], list[dict]]:
    from .planner import CURATED_ORGAN
    studies = [s for s in hv.STUDIES if s["species"] == species]
    raw = studies[0]["organ"] if studies else CURATED_ORGAN.get(species)
    ids = []
    for piece in re.split(r"\+|,| and ", raw or ""):
        oid = methods.organ_id(piece.strip())
        if oid and oid not in ids:
            ids.append(oid)
    return ids, studies


def _chosen(species: str, organ: str | None) -> str | None:
    """The part the user says is harvested, used only for a plant we hold no harvest data on."""
    if not organ or _organs(species)[0]:
        return None
    oid = organ if organ in methods.ORGAN_BY_ID else methods.organ_id(organ)
    return oid if oid in PART_LABEL else None


def facts(species: str, organ: str | None = None) -> dict:
    """Numbered parts with the facts we hold for each. Only data from the app, each with its basis. For a plant with no
    harvest data, `organ` (the part the user says is harvested) takes the harvested slot and is labelled as their choice."""
    from .eligibility import crosswalk
    from .evidence_agent import matrix_sensitivity
    harvested, studies = _organs(species)
    chosen = _chosen(species, organ)
    if chosen:
        harvested = [chosen]
    parts, n = [], 0
    for oid in harvested:
        n += 1
        o = methods.ORGAN_BY_ID[oid]
        st = next((s for s in studies if oid in [methods.organ_id(p.strip()) for p in re.split(r"\+|,", s["organ"])]), None)
        stats = []
        try:
            sens = matrix_sensitivity(species, o["agent_organ"])
            if sens.get("status") == "ok":
                stats.append({"label": f"Growth that depends on {sens['process']}", "value": f"{sens['share_mean'] * 100:.0f}%",
                              "basis": f"{sens['matrices']} published matrices ({sens['basis']})"})
        except Exception:  # noqa: BLE001 - sensitivity is optional
            pass
        if st:
            stats.append({"label": "Harvest evidence", "value": st["design"], "basis": st["citation"].split("(")[0].strip()})
        parts.append({"n": n, "part": oid, "label": PART_LABEL[oid], "role": "harvested",
                      "product": (st or {}).get("product") or ("part you chose as harvested (no harvest data for this plant)" if chosen
                                                               else "commonly collected part (curated; no harvest study)" if not studies else None),
                      "affects": o["process"], "methods": [m["label"] for m in o["methods"]][:3], "stats": stats})
    for oid in [c for h in harvested[:1] for c in CONTEXT_PARTS.get(h, [])] if harvested else ["leaf", "flower"]:
        if oid in harvested:
            continue
        n += 1
        parts.append({"n": n, "part": oid, "label": PART_LABEL[oid], "role": "context",
                      "product": None, "affects": None, "methods": [], "stats": []})
    cw = crosswalk()
    row = cw[cw.SpeciesAccepted == species]
    uses = str(row.example_uses.iloc[0]) if len(row) and row.example_uses.iloc[0] else None
    return {"species": species, "parts": parts, "chosen_organ": chosen, "known_organ": bool(_organs(species)[0]),
            "uses": [u.strip() for u in re.split(r";", uses)][:6] if uses else [],
            "uses_basis": "documented uses in ethnobotany databases (medicinal crosswalk); not a recommendation"}


def prompt(species: str, parts: list[dict]) -> str:
    marks = "\n".join(f"  {p['n']}. {VISUAL_HINT[p['part']]}" + ("  (harvested part: give it a soft amber highlight)" if p["role"] == "harvested" else "")
                      for p in parts)
    return (f"This is an openly licensed botanical illustration or photograph of {species}. Annotate it for a harvesting guide.\n"
            "Draw a small solid bright-yellow (#FFD21F) circle with a thin black outline and a bold black numeral inside next to each of "
            "these parts, joined to the part by a thin bright-yellow leader line with a thin dark edge, whose end touches that exact part:\n"
            f"{marks}\n"
            "Rules:\n"
            "- This is an overlay only. Do NOT add, redraw, extend, complete, restyle or replace anything in the picture: no new roots, "
            "stems, bark, leaves, flowers or fruit, and no change of drawing style. Every pixel outside the markers, lines and glow stays as it is.\n"
            "- If a listed part is not clearly visible (for example roots in a photo taken above ground, or a trunk on a herbarium twig), "
            "SKIP that numeral entirely. Never point a marker at a different part instead.\n"
            "- Add a soft translucent amber glow over the harvested part(s) only, and only where they are visible.\n"
            "- Write NO words, letters, titles or captions; only the numerals listed.\n"
            "- Place markers in empty space beside the part so they do not cover the plant.")


RECOLOR_PROMPT = (
    "This picture already carries numbered circular markers (dark-green circles with white numerals) joined to plant parts by thin "
    "dark-green leader lines. Recolour ONLY those markers and lines: fill each circle bright yellow (#FFD21F) with a thin black "
    "outline, make each numeral bold black, and make each leader line bright yellow with a thin dark edge. Keep every marker, numeral "
    "and line in exactly the same position, size and shape; do not move, add or remove any. Change nothing else: the plant, the "
    "background and the soft amber glow stay exactly as they are. Write no words.")


def _versioned(iid: str) -> str:
    """URL with the file's modification time, so browsers may cache it for good and still see a recoloured image."""
    f = file(iid)
    return f"/api/illustration/{iid}" + (f"?v={int(f[0].stat().st_mtime)}" if f else "")


def _index() -> dict:
    f = CURATED / "index.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _public(meta: dict, species: str, organ: str | None = None) -> dict:
    out = {k: v for k, v in meta.items() if not k.startswith("_")}
    out["facts"] = facts(species, organ)
    out["note"] = NOTE
    return out


def get(species: str, generate: bool = False, organ: str | None = None) -> dict:
    """Curated first, then the on-disk cache, then (only when generate=True) a new AI annotation of an open-licence source
    image, which is cached for good. `organ` only matters for a plant with no harvest data (the user's chosen part)."""
    cur = next((v for k, v in _index().items() if k.lower() == species.lower() and v.get("checked")), None)
    if cur:
        return _public({**cur, "status": "ok", "tier": "curated", "src": _versioned(cur["id"]),
                        "orig_src": _versioned(cur["orig"])}, species)
    CACHE.mkdir(parents=True, exist_ok=True)
    chosen = _chosen(species, organ)
    key = hashlib.sha256((species.lower() + (f"|{chosen}" if chosen else "")).encode()).hexdigest()[:16]
    mf = CACHE / f"{key}.json"
    if mf.exists():
        return _public(json.loads(mf.read_text(encoding="utf-8")), species, organ)
    if not generate:
        return {"status": "not generated", "species": species, "note": NOTE, "facts": facts(species, organ)}
    with _LOCK:
        ev = _INFLIGHT.get(key)
        mine = ev is None
        if mine:
            ev = _INFLIGHT[key] = threading.Event()
    if not mine:
        ev.wait(240)
        return _public(json.loads(mf.read_text(encoding="utf-8")), species, organ) if mf.exists() else {"status": "busy", "species": species}
    try:
        meta = _generate(species, key, organ)
        if meta.get("status") == "ok":
            mf.write_text(json.dumps(meta), encoding="utf-8")
        return _public(meta, species, organ) if meta.get("status") == "ok" else meta | {"facts": facts(species, organ)}
    finally:
        with _LOCK:
            _INFLIGHT.pop(key, None)
        ev.set()


def _source_image(species: str) -> dict | None:
    """An openly licensed source: the hand-picked plate if there is one, else a Biodiversity Heritage Library plate that Openverse
    finds, else the species photo."""
    plate = next((v.get("plate") for k, v in media.curated().get("species", {}).items() if k.lower() == species.lower()), None)
    if plate:
        found = media.media_file(plate["id"])
        if found:
            return {"bytes": found[0].read_bytes(), "mime": found[1],
                    "source": {"title": plate["title"] or f"Image of {species}", "creator": plate["creator"], "licence": plate["licence"],
                               "landing": plate["landing"], "kind": "hand-picked plate or photo", "id": plate["id"]}}
    try:
        hits = methods.openverse(f"{species} Biodiversity Heritage Library", 6)
    except Exception:  # noqa: BLE001
        hits = []
    for h in hits:
        if species.lower() in (h["title"] or "").lower():  # the full binomial, so a plate of another species in the genus is never used
            try:
                data, mime = media._download(h["thumb"])
                return {"bytes": data, "mime": mime, "source": {"title": h["title"], "creator": h["creator"], "licence": h["licence"],
                                                               "landing": h["landing"], "kind": "botanical plate (search result)"}}
            except Exception:  # noqa: BLE001
                continue
    ph = media.species_image(species)
    if ph.get("status") == "ok":
        found = media.media_file(ph["id"])
        if found:
            path, mime = found
            return {"bytes": Path(path).read_bytes(), "mime": mime,
                    "source": {"title": f"Photo of {species}", "creator": ph.get("photographer"), "licence": ph.get("licence"),
                               "landing": ph.get("attribution_url"), "kind": "photograph"}}
    return None


def _generate(species: str, key: str, organ: str | None = None) -> dict:
    from . import providers
    src = _source_image(species)
    if not src:
        return {"status": "no source", "species": species, "reason": "no openly licensed plate or photo found"}
    f = facts(species, organ)
    try:
        out = providers.gemini_image(prompt(species, f["parts"]), src["bytes"], src["mime"])
    except providers.ProviderError as e:
        return {"status": "unavailable", "species": species, "reason": str(e)}
    ext = ".png" if out["mime"] == "image/png" else ".jpg"
    (CACHE / f"{key}{ext}").write_bytes(out["image"])
    (CACHE / f"{key}.orig").write_bytes(src["bytes"])
    return {"status": "ok", "tier": "dynamic", "checked": False, "id": f"c-{key}", "species": species, "model": out["model"],
            "generated": time.strftime("%Y-%m-%d", time.gmtime()), "source": src["source"], "src": f"/api/illustration/c-{key}",
            "_ext": ext}


def file(iid: str) -> tuple[Path, str] | None:
    """Serve curated (`<slug>`) or cached (`c-<hash>`) images only; ids are validated, never used as raw paths."""
    if re.fullmatch(r"c-[0-9a-f]{16}", iid):
        for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg")):
            p = CACHE / f"{iid[2:]}{ext}"
            if p.exists():
                return p, mime
        return None
    if re.fullmatch(r"[a-z0-9\-]{3,60}(-orig)?", iid):
        for ext, mime in ((".png", "image/png"), (".jpg", "image/jpeg"), (".webp", "image/webp")):
            p = CURATED / f"{iid}{ext}"
            if p.exists():
                return p, mime
    return None
