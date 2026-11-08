"""Species catalogue and curated case library (embedded across the four pages)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import compadre, eligibility as el, harvest as hv

ROOT = Path(__file__).resolve().parents[2]
SENSITIVE = {"Nardostachys jatamansi", "Panax quinquefolius", "Hydrastis canadensis", "Prunus africana",
             "Dactylorhiza hatagirea", "Cypripedium calceolus", "Aquilaria malaccensis"}

CASES = [
    {"id": "jatamansi", "species": "Nardostachys jatamansi", "title": "Jatamansi rhizome harvest in the Nepal Himalaya",
     "tier": "A", "study": "nardostachys-ghimire2008",
     "problem": "Rhizomes of this CITES Appendix II, IUCN Critically Endangered alpine herb are dug for Tibetan, Ayurvedic and export markets.",
     "design": "Experimental single harvest (0–75% of rhizomes, Sept 1998) on rocky-outcrop subplots; unharvested meadow population; censuses 1999–2002.",
     "known": "Population growth falls monotonically with harvest intensity; harvest acts through growth and survival (plants shrink), not seed output.",
     "limits": "One site, one harvest event, multi-year mean matrices in COMPADRE; no local stock or yield data for any other site.",
     "next": "Permanent-plot stage counts and post-harvest recovery monitoring at the site of interest.",
     "region": {"bbox": [82.4, 28.9, 83.2, 29.5]}, "camera": [82.8, 29.15, 90000]},
    {"id": "khaya", "species": "Khaya senegalensis", "title": "African mahogany bark and foliage harvest in Benin",
     "tier": "A", "study": "khaya-gaoue2010",
     "problem": "Bark is stripped for medicine and branches lopped for cattle fodder across West African savannas.",
     "design": "Observational: six high-harvest vs six low-harvest populations in two ecoregions, 2004–2006.",
     "known": "Harvested populations have slightly lower lambda on average, but the 6-vs-6 difference is not significant in our re-analysis (E04).",
     "limits": "Harvest is confounded with site and ecoregion; bark and foliage harvest act together.",
     "next": "Matched harvest experiment separating bark from foliage removal.",
     "region": {"bbox": [1.4, 9.0, 3.2, 11.8]}, "camera": [2.3, 10.4, 400000]},
    {"id": "arnica", "species": "Arnica montana", "title": "Arnica habitat in the European Alps",
     "tier": "C", "study": None,
     "problem": "Flower heads are wild-collected for topical preparations; grassland abandonment and fertilisation shrink habitat.",
     "design": "No COMPADRE matrix for A. montana (only A. angustifolia); GBIF presences pass the habitat-model gate (spatial-block AUC 0.75, E10).",
     "known": "Climate suitability can be mapped at 10' resolution with spatial validation; no demographic or harvest model exists in our data.",
     "limits": "Suitability is not abundance or a harvest area; demographic simulation and harvest scenarios are unavailable (Tier C).",
     "next": "Survey under-sampled environmental strata (Plan) and a flower-head removal experiment.",
     "region": {"bbox": [9, 46.5, 13, 48.5]}, "camera": [11, 47.5, 350000]},
    {"id": "primula", "species": "Primula veris", "title": "Cowslip flowering calendar from botanical gardens",
     "tier": "B", "study": None,
     "problem": "Cowslip flowers and roots are collected for cough remedies; when to monitor flowering matters for field surveys.",
     "design": "PhenObs botanical-garden network 2019–2023 (separate from demography); COMPADRE matrices without harvest.",
     "known": "Across gardens, species identity explains most peak-flowering variance (E08); the European habitat model failed the spatial-CV gate (AUC 0.64).",
     "limits": "Garden plants are not wild populations; phenology says nothing about harvest tolerance.",
     "next": "Wild flowering monitoring at candidate collection sites.",
     "region": {"bbox": [9, 47, 12, 49]}, "camera": [10.5, 48, 300000]},
    # Added 2026-11-07 after running each through the whole pipeline (CASE_STUDY_VALIDATION.md).
    {"id": "ginseng", "species": "Panax quinquefolius", "title": "American ginseng root: how the harvester behaves matters",
     "tier": "A", "study": "panax-vandervoort2006",
     "problem": "Wild roots are dug for the ginseng trade; state rules set a minimum plant size and a harvest season.",
     "design": "Modelled: three harvester types simulated on field-measured West Virginia matrices (1998–2000). The treatments are model scenarios, not observed plots.",
     "known": "Growth rate λ 1.039 without harvest, 0.852 with non-compliant harvest, 0.959 with rule-compliant harvest and 1.041 with steward harvest (later season, self-limited, seed planted). The authors conclude state rules alone are not adequate.",
     "limits": "One population and modelled harvest; behaviour of real harvesters at your site is unknown. CITES Appendix II.",
     "next": "Record harvester practice (season, plant size, seed planting) per collection and monitor plots before and after.",
     "region": {"bbox": [-82.6, 37.2, -77.7, 40.6]}, "camera": [-80.2, 38.9, 500000]},
    {"id": "prunus", "species": "Prunus africana", "title": "African cherry bark on Mount Oku, Cameroon",
     "tier": "A", "study": "prunus-stewart2001",
     "problem": "Bark is stripped for prostate-remedy extracts; the species is CITES Appendix II with export quotas.",
     "design": "Observational: one unharvested plot vs four plots harvested once or twice a year, 1997–1999 (PhD thesis matrices).",
     "known": "The thesis reports λ below 1 in harvested plots, and 6 of 8 single-year harvested matrices are below 1. The multi-year mean matrices put harvested plots at 0.966–1.025 against 0.985 for the single control, so no clear contrast is visible in them.",
     "limits": "One control plot, grey literature, 1997–99 only; a later forest-wide harvest (2005/06) is outside these data.",
     "next": "Bark-recovery and tree-survival monitoring per stripping method (e.g. opposite quarters).",
     "region": {"bbox": [10.2, 6.0, 10.8, 6.4]}, "camera": [10.5, 6.2, 80000]},
    {"id": "frankincense", "species": "Boswellia papyrifera", "title": "Frankincense resin tapping in Ethiopia",
     "tier": "A", "study": "boswellia-groenendijk2012",
     "problem": "Stems are tapped for frankincense; stands are declining across the dry woodlands.",
     "design": "Observational: tapped vs untapped populations (Metema, Adi Arkay).",
     "known": "Both decline (λ 0.962 tapped, 0.954 untapped). The authors attribute decline to blocked regeneration and adult mortality (fire, grazing, beetles), not mainly to tapping; tapping reduces seed production (Rijkers 2006).",
     "limits": "Two population matrices; tapping intensity not resolved; regeneration drivers act alongside.",
     "next": "Count seedlings and saplings and record fire and grazing alongside tapping intensity.",
     "region": {"bbox": [35.8, 12.4, 38.4, 14.0]}, "camera": [37.1, 13.2, 350000]},
    {"id": "amla", "species": "Phyllanthus emblica", "title": "Amla fruit harvest in South India: a disputed result",
     "tier": "A", "study": "phyllanthus-ticktin2012",
     "problem": "Fruit is collected for Ayurvedic medicine; harvest was banned at the study site in 2006.",
     "design": "Observational, 10-year monitoring with mistletoe and Lantana as co-drivers; harvest matrices (1999–2006) precede the unharvested ones (2006–09).",
     "known": "The authors find fruit harvest has little effect on stochastic growth and mistletoe drives decline; Prasad et al. (2014) dispute this. The simple contrast here (λ 0.930 harvested vs 0.976 after the ban) is the before/after comparison in dispute.",
     "limits": "Harvest and period are confounded; the app cannot settle the dispute.",
     "next": "Same-period harvested and unharvested plots, with mistletoe load recorded per tree.",
     "region": {"bbox": [76.9, 11.7, 77.4, 12.2]}, "camera": [77.15, 11.95, 80000]},
    {"id": "colchicum", "species": "Colchicum autumnale", "title": "Meadow saffron: timing of leaf and flower removal",
     "tier": "B", "study": "colchicum-winter2014-cut",
     "problem": "A colchicine-bearing grassland plant; the experiment cut it to control a toxic weed, not to collect medicine.",
     "design": "Randomised cutting experiment in Austria and Germany, 2008–2011, against plots cut in June (usual practice).",
     "known": "Early-May cutting lowered λ to 0.78 (vs 1.00 Austria, 0.95 Germany); repeated May cutting to 0.63. Autumn flower removal did not (λ 1.01). Timing of leaf removal matters more than flower removal.",
     "limits": "Weed-control purpose; the cut removes leaves, not the medicinal seeds or corms. Used as evidence about removal timing only.",
     "next": "If seeds or corms are collected, a removal experiment on those parts.",
     "region": {"bbox": [9.0, 47.0, 16.0, 50.0]}, "camera": [12.5, 48.3, 600000]},
    {"id": "garcinia", "species": "Garcinia lucida", "title": "Garcinia bark in Cameroon: stable λ, shrinking harvestable stock",
     "tier": "A", "study": "garcinia-guedje2007",
     "problem": "Bark and seeds are traded for medicine and palm-wine processing; collectors debark, ring-bark or fell trees.",
     "design": "Modelled: matrix models for each local practice, built from a two-year field study (1997–1999) in South Cameroon.",
     "known": "λ is 1.063 without harvest and 1.056–1.060 under every practice, so population growth hardly differs. The authors show the stock of harvestable trees still falls to about half in 20 years under annual partial debarking and below 4% under annual ring-barking or felling.",
     "limits": "One area and two years; the harvestable-stock projection is in the paper, not computed here. λ alone would hide the damage.",
     "next": "Track the number of bark-producing trees and their bark regrowth, not only population size.",
     "region": {"bbox": [10.3, 2.6, 11.2, 3.3]}, "camera": [10.75, 2.95, 120000]},
]


@lru_cache(maxsize=1)
def catalog() -> list[dict]:
    cw = el.crosswalk()
    md = compadre.metadata()
    lam = pd.read_parquet(ROOT / "data" / "clean" / "compadre_lambda.parquet")[["MatrixID", "lambda"]]
    md = md.merge(lam, on="MatrixID", how="left")
    harvest_sp = {s["species"] for s in hv.STUDIES}
    tier_a_sp = {s["species"] for s in hv.STUDIES if s["tier"] == "A"}
    pheno = el.phenobs_species()
    habitat = {p.stem.replace("_", " ") for p in (ROOT / "data" / "derived" / "habitat").glob("*.joblib")}
    out = []
    for _, r in cw[cw.medicinal_documented].iterrows():
        sub = md[md.SpeciesAccepted == r.SpeciesAccepted]
        pts = sub[["Lat", "Lon"]].dropna().drop_duplicates()
        sens = r.SpeciesAccepted in SENSITIVE
        locs = [{"lat": round(float(a), 1 if sens else 3), "lon": round(float(b), 1 if sens else 3)} for a, b in pts.values[:30]]
        common = sub.CommonName.dropna()
        out.append({"name": r.SpeciesAccepted, "family": r.family, "organism_type": r.organism_type,
                    "common_name": str(common.iloc[0]) if len(common) else None,
                    "n_matrices": int(r.n_matrices), "n_studies": int(sub.StudyID.nunique()),
                    "n_populations": int(r.n_populations), "median_lambda": _f(sub["lambda"].median()),
                    "harvest_study": r.SpeciesAccepted in harvest_sp, "phenobs": r.SpeciesAccepted in pheno,
                    "habitat_model": r.SpeciesAccepted in habitat, "medicinal_sources": r.med_sources,
                    "n_med_references": int(r.n_med_references), "example_uses": r.example_uses,
                    "matched_via_synonym": bool(r.matched_via_synonym), "sensitive": sens,
                    "compadre_locations": locs,
                    "tier": "A" if r.SpeciesAccepted in tier_a_sp else ("B" if len(el.preset_matrices(r.SpeciesAccepted)) else "C")})
    return out


def _f(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 4)


def search(q: str, limit: int = 20) -> list[dict]:
    q = (q or "").strip().lower()
    cat = catalog()
    if not q:
        pri = {c["species"]: i for i, c in enumerate(CASES)}
        return sorted(cat, key=lambda c: (pri.get(c["name"], 99), -c["n_matrices"]))[:limit]

    def score(c):
        n = c["name"].lower()
        cn = (c["common_name"] or "").lower()
        if n == q:
            return 0
        if n.startswith(q):
            return 1
        if q in n:
            return 2
        if q in cn:
            return 3
        if q in (c["family"] or "").lower():
            return 4
        return 9
    hits = [c for c in cat if score(c) < 9]
    return sorted(hits, key=lambda c: (score(c), -c["n_matrices"]))[:limit]


def species_profile(name: str) -> dict | None:
    c = next((x for x in catalog() if x["name"].lower() == name.lower()), None)
    if not c:
        return None
    pres = el.preset_matrices(c["name"])
    mats = [{"matrix_id": int(r.MatrixID), "population": r.MatrixPopulation, "treatment": r.MatrixTreatment,
             "composite": r.MatrixComposite, "years": f"{r.MatrixStartYear}–{r.MatrixEndYear}", "dim": int(r.MatrixDimension),
             "study_id": r.StudyID, "split": bool(r.qc_split_available)} for r in pres.head(40).itertuples()]
    studies = [{"id": s["id"], "design": s["design"], "organ": s["organ"], "citation": s["citation"], "tier": s["tier"]}
               for s in hv.STUDIES if s["species"] == c["name"]]
    elig = el.assess(c["name"])
    return {**c, "preset_matrices": mats, "harvest_studies": studies, "eligibility": elig,
            "cases": [k["id"] for k in CASES if k["species"] == c["name"]]}


def studies_index() -> list[dict]:
    md = compadre.metadata()
    cw = el.crosswalk()
    med = set(cw[cw.medicinal_documented].SpeciesAccepted)
    sub = md[md.SpeciesAccepted.isin(med)]
    g = sub.groupby(["StudyID", "SpeciesAccepted"]).agg(
        n=("MatrixID", "size"), authors=("Authors", "first"), year=("YearPublication", "first"), journal=("Journal", "first"),
        doi=("DOI_ISBN", "first"), country=("Country", "first"),
        treatments=("MatrixTreatment", lambda s: sorted(set(map(str, s)))[:6])).reset_index()
    return [{"study_id": r.StudyID, "species": r.SpeciesAccepted, "n_matrices": int(r.n), "authors": r.authors,
             "year": _s(r.year), "journal": _s(r.journal), "doi": _s(r.doi), "country": _s(r.country),
             "treatments": r.treatments, "audited_harvest": any(s["study"] == r.StudyID and s["species"] == r.SpeciesAccepted for s in hv.STUDIES)}
            for r in g.itertuples()]


def _s(x):
    return None if pd.isna(x) else str(x)
