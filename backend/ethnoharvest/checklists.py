"""Name check (WCVP/POWO + World Flora Online) and WCVP native range, precomputed by scripts/checklists.py.

Read-only at runtime: data/clean/checklists.json and the simplified TDWG level-3 regions shipped to the
frontend (frontend/public/geo/wgsrpd_l3.json). A species not in the file is reported as "not checked",
never as "not native".
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "data" / "clean" / "checklists.json"
L3 = ROOT / "frontend" / "public" / "geo" / "wgsrpd_l3.json"


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {"meta": {}, "species": {}}


def _key(name: str) -> str:
    p = (name or "").split()
    return " ".join(p[:2]).capitalize() if len(p) >= 2 else ""


def meta() -> dict:
    return _data().get("meta", {})


def species(name: str) -> dict | None:
    r = _data()["species"].get(_key(name))
    return (r | {"sources": meta().get("sources")}) if r else None


@lru_cache(maxsize=1)
def _regions():
    from shapely.geometry import shape
    from shapely.strtree import STRtree
    gj = json.loads(L3.read_text(encoding="utf-8"))
    codes = [f["properties"]["code"] for f in gj["features"]]
    names = {f["properties"]["code"]: f["properties"]["name"] for f in gj["features"]}
    geoms = [shape(f["geometry"]) for f in gj["features"]]
    return STRtree(geoms), geoms, codes, names


def region_overlap(name: str | None, bounds: list[float]) -> dict:
    """Which TDWG level-3 regions a study region touches, and how each is listed for the species in WCVP."""
    src = {"name": "WCVP native range (Kew) on TDWG level-3 regions", "url": "https://powo.science.kew.org/"}
    if not name:
        return {"status": "not applicable", "reason": "no species selected", "source": src}
    s = species(name)
    if not s or not s["wcvp"].get("accepted_id"):
        return {"status": "unavailable", "reason": "species not matched in WCVP", "source": src}
    if not L3.exists():
        return {"status": "unavailable", "reason": "region boundaries not built (scripts/checklists.py)", "source": src}
    from shapely.geometry import box
    tree, geoms, codes, names = _regions()
    b = box(*bounds)
    hit = [codes[i] for i in tree.query(b) if geoms[i].intersects(b)]
    w = s["wcvp"]
    label = {c: ("native" if c in w["native_l3"] else "introduced" if c in w["introduced_l3"]
                 else "extinct" if c in w["extinct_l3"] else "doubtful" if c in w["doubtful_l3"] else "not recorded")
             for c in hit}
    if not hit:
        verdict = "outside all TDWG regions (sea?)"
    elif any(v == "native" for v in label.values()):
        verdict = "native"
    elif any(v == "introduced" for v in label.values()):
        verdict = "introduced"
    else:
        verdict = "not recorded"
    return {"status": "available", "verdict": verdict, "regions": [{"code": c, "name": names.get(c), "listed": label[c]} for c in hit],
            "n_native_regions": len(w["native_l3"]), "source": src,
            "note": "Checklist range at botanical-country scale (coarse). 'Not recorded' is not proof of absence."}
