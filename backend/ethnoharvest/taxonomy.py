"""Taxonomic resolution + medicinal-use crosswalk.

Resolves every COMPADRE accepted taxon against the GBIF Backbone Taxonomy
(accepted usage + synonyms; cached per name under data/raw/gbif_taxonomy/),
then matches binomials from two open medicinal-use sources:
  * USDA Dr. Duke ETHNOBOT (public domain)  -- documented ethnobotanical uses
  * Herbolario (GBIF, CC-BY)                 -- literature medicinal-use records
A species is `medicinal_documented` when >=1 source reports a medicinal use.
`medicinal_strength` counts independent references. Medicinal use is NOT
evidence of efficacy.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "raw" / "gbif_taxonomy_v2"
CLEAN = ROOT / "data" / "clean"
GBIF = "https://api.gbif.org/v1"

# Duke activities that are not medicinal uses (kept out of the medicinal flag)
NON_MEDICINAL = re.compile(
    r"^(food|fodder|forage|dye|fiber|fibre|timber|fuel|firewood|ornamental|beverage|spice|condiment|"
    r"fish ?poison|piscicide|insecticide|pesticide|insectifuge|rodenticide|arrow poison|poison|tannin|"
    r"cosmetic|perfume|soap|gum|resin|wax|oil|honey|masticatory|fence|hedge|shade|toy|rope|basket|"
    r"broom|thatch|smoke|snuff|tobacco|incense|ritual|magic|charm|vegetable|fruit|nut|famine food|"
    r"potherb|tea|salad|sweetener|bait|mordant|ink|paper|varnish|lacquer|glue|tan)\b",
    re.I,
)


def norm(name: str | None) -> str:
    if not isinstance(name, str):
        return ""
    parts = re.sub(r"[^A-Za-z\- ]", " ", name).split()
    return " ".join(p.lower() for p in parts[:2]) if len(parts) >= 2 else ""


def _get(url: str, params: dict | None = None) -> dict | list:
    for attempt in range(5):
        try:
            r = httpx.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            time.sleep(1 + attempt)
    raise RuntimeError(f"GBIF request failed: {url}")


def resolve(name: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (re.sub(r"\W+", "_", name) + ".json")
    if f.exists():
        return json.loads(f.read_text())
    m = _get(f"{GBIF}/species/match", {"name": name, "kingdom": "Plantae", "strict": "false"})
    key = m.get("acceptedUsageKey") or m.get("usageKey")
    syn = []
    accepted = m.get("species") or m.get("scientificName")
    if key:
        acc = _get(f"{GBIF}/species/{key}")
        accepted = acc.get("species") or acc.get("canonicalName") or accepted
        off, end = 0, False
        while not end and off < 1000:
            page = _get(f"{GBIF}/species/{key}/synonyms", {"limit": 200, "offset": off})
            # keep true synonyms only: pro-parte and misapplied names cause false medicinal matches
            syn += [s.get("canonicalName") for s in page.get("results", [])
                    if s.get("canonicalName") and s.get("taxonomicStatus") in ("SYNONYM", "HOMOTYPIC_SYNONYM", "HETEROTYPIC_SYNONYM")
                    and s.get("rank") in ("SPECIES", "SUBSPECIES", "VARIETY")]
            end, off = page.get("endOfRecords", True), off + 200
    out = {"query": name, "matchType": m.get("matchType"), "confidence": m.get("confidence"),
           "status": m.get("status"), "gbif_key": key, "accepted": accepted,
           "family": m.get("family"), "synonyms": sorted(set(syn))}
    f.write_text(json.dumps(out))
    return out


def synonym_is_safe(syn: str, accepted_key) -> bool:
    """Reject a synonym binomial if GBIF treats it as an accepted name of a different taxon."""
    r = resolve_name_only(syn)
    return not (r.get("status") == "ACCEPTED" and r.get("usageKey") not in (None, accepted_key))


def resolve_name_only(name: str) -> dict:
    f = CACHE / ("_m_" + re.sub(r"\W+", "_", name) + ".json")
    if f.exists():
        return json.loads(f.read_text())
    m = _get(f"{GBIF}/species/match", {"name": name, "kingdom": "Plantae", "strict": "true"})
    out = {"status": m.get("status"), "usageKey": m.get("usageKey"), "matchType": m.get("matchType")}
    f.write_text(json.dumps(out))
    return out


# Curated medicinal-use citations for taxa the open checklists miss (each must cite a primary/pharmacopoeial source)
CURATED = [
    {"binomial": "prunus africana", "use": "Bark: benign prostatic hyperplasia (Cortex Pruni africanae)",
     "reference": "WHO monographs on selected medicinal plants, Vol. 2 (2002): Cortex Pruni Africanae"},
    {"binomial": "khaya senegalensis", "use": "Bark: fever/malaria and other ethnomedicinal uses (Benin)",
     "reference": "Gaoue OG, Ticktin T (2007) Biol Conserv 137:424-436 (harvest of bark and foliage for medicine/fodder)"},
]


# Manual review (2026-11-07) of all 25 synonym-only matches: these GBIF heterotypic synonyms
# refer to broader/different species concepts, so the medicinal record cannot be attributed.
SYNONYM_REJECT = {
    "Molinia caerulea": {"phragmites communis"},
    "Betula nana": {"betula alba"},
    "Betula pubescens var. pumila": {"betula alba"},
    "Actaea cordifolia": {"cimicifuga racemosa"},
    "Mammillaria gaumeri": {"mammillaria heyderi"},
    "Opuntia rastrera": {"opuntia lindheimeri"},
    "Scorzonera humilis": {"scorzonera hispanica"},
    "Vincetoxicum rossicum": {"cynanchum vincetoxicum", "vincetoxicum officinale"},
    "Platanthera macrophylla": {"habenaria orbiculata"},
    "Phytelephas seemannii": {"phytelephas macrocarpa"},
    "Taraxacum erythrospermum": {"taraxacum laevigatum"},
}


def medicinal_sources() -> pd.DataFrame:
    """Long table: binomial(normalised) -> source, use, reference."""
    raw = ROOT / "data" / "raw"
    duke = pd.read_csv(raw / "duke" / "ETHNOBOT.csv", dtype=str, encoding="latin1")
    duke = duke.assign(binomial=duke["TAXON"].map(norm), use=duke["ACTIVITY"].fillna(""),
                       reference=duke["REFERENCE"].fillna("Duke"), country=duke["COUNTRY"].fillna(""),
                       source="USDA Duke ETHNOBOT")
    duke["medicinal"] = ~duke["use"].str.strip().str.match(NON_MEDICINAL)
    herb = pd.read_csv(raw / "herbolario" / "herbolario.csv", dtype=str, encoding="utf-8-sig")
    use_col = "diseaseTypeUse" if "diseaseTypeUse" in herb.columns else herb.columns[0]
    herb = herb.assign(binomial=herb["scientificName"].map(norm),
                       use=herb[use_col].fillna("") + "; " + herb.get("specificDiseaseTypeUse", pd.Series("", index=herb.index)).fillna(""),
                       reference=herb["associatedReferences"].fillna("Herbolario"),
                       country=herb["countryCode"].fillna(""), source="Herbolario (GBIF)", medicinal=True)
    cur = pd.DataFrame(CURATED).assign(source="Curated citation", country="", medicinal=True)
    cols = ["binomial", "source", "use", "reference", "country", "medicinal"]
    return pd.concat([duke[cols], herb[cols], cur[cols]], ignore_index=True).query("binomial != ''")


def build_crosswalk() -> pd.DataFrame:
    from .compadre import metadata

    md = metadata()
    names = sorted(md["SpeciesAccepted"].dropna().unique())
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(resolve, names))
    med = medicinal_sources()
    med_med = med[med["medicinal"]]
    by_bin = med_med.groupby("binomial")
    rows = []
    for name, r in zip(names, res):
        variants = {norm(name), norm(r.get("accepted"))} | {norm(s) for s in r.get("synonyms", [])}
        variants.discard("")
        own = {norm(name), norm(r.get("accepted"))}
        cand = med_med[med_med["binomial"].isin(variants)]
        safe = {b for b in set(cand["binomial"]) if b in own or synonym_is_safe(b, r.get("gbif_key"))}
        safe -= SYNONYM_REJECT.get(name, set())
        hits = cand[cand["binomial"].isin(safe)]
        sub = md[md["SpeciesAccepted"] == name]
        rows.append({
            "SpeciesAccepted": name,
            "gbif_key": r.get("gbif_key"), "gbif_accepted": r.get("accepted"),
            "gbif_match": r.get("matchType"), "gbif_status": r.get("status"),
            "family": sub["Family"].iloc[0], "organism_type": sub["OrganismType"].iloc[0],
            "n_synonyms": len(r.get("synonyms", [])),
            "matched_names": "|".join(sorted(set(hits["binomial"]))),
            "matched_via_synonym": bool(len(hits) and not (set(hits["binomial"]) & {norm(name)})),
            "medicinal_documented": bool(len(hits)),
            "n_med_records": int(len(hits)),
            "n_med_references": int(hits["reference"].nunique()),
            "med_sources": "|".join(sorted(set(hits["source"]))),
            "example_uses": "; ".join(list(dict.fromkeys(hits["use"].str.strip()))[:8])[:400],
            "n_matrices": len(sub),
            "n_studies": sub["DOI_ISBN"].fillna(sub["Authors"]).nunique(),
            "n_populations": sub["MatrixPopulation"].nunique(),
            "treatments": "|".join(sorted(set(sub["MatrixTreatment"].dropna().astype(str))))[:500],
        })
    cw = pd.DataFrame(rows)
    CLEAN.mkdir(parents=True, exist_ok=True)
    cw.to_parquet(CLEAN / "medicinal_crosswalk.parquet", index=False)
    cw.to_csv(CLEAN / "medicinal_crosswalk.csv", index=False)
    return cw


if __name__ == "__main__":
    cw = build_crosswalk()
    m = cw[cw.medicinal_documented]
    print({"compadre_taxa": len(cw), "medicinal_taxa": len(m),
           "medicinal_strong(>=2 refs)": int((m.n_med_references >= 2).sum()),
           "via_synonym_only": int(m.matched_via_synonym.sum()),
           "medicinal_matrices": int(m.n_matrices.sum()), "medicinal_studies": int(m.n_studies.sum())})
