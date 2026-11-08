"""Evidence Eligibility Engine: deterministic decisions about which computations
are enabled for a species x region x task, with transparent missing requirements.

No LLM or JEV output can change these decisions.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from . import compadre, harvest as hv

ROOT = Path(__file__).resolve().parents[2]
CLEAN = ROOT / "data" / "clean"

TASKS = ["demographic_projection", "harvest_comparison", "rotation_extrapolation", "hypothetical_harvest",
         "local_quota", "habitat_model", "phenology_window", "survey_planning", "evidence_planning"]

LOCAL_QUOTA_REQUIREMENTS = {
    "local_stage_counts": "Stage-structured counts of the local population (permanent plots, >=2 censuses)",
    "harvest_yield": "Measured harvestable organ yield per plant/area at the site",
    "post_harvest_recovery": "Monitored survival/regrowth of harvested plants at the site (matched unharvested controls)",
    "identity_verified": "Voucher-verified species identity (e.g. Nardostachys jatamansi vs Valeriana jatamansi)",
    "site_rights": "Documented collection rights / permits and community consent (FPIC) for the site",
    "expert_threshold": "Expert-agreed sustainability threshold and monitoring interval",
}


# Medicinal use documented in the harvest literature but missing from the ethnobotany databases behind the crosswalk.
# Each entry needs a published source. Experiments read the parquet directly, so their counts are unchanged.
CURATED_MEDICINAL = {
    "Garcinia lucida": {"source": "Curated literature: Guedje et al. 2003, For Ecol Manage 177:231-241; Guedje et al. 2007, "
                                  "For Ecol Manage 240:1-12",
                        "uses": "Bark and seeds traded for medicinal use and palm-wine processing (Cameroon, Gabon, Equatorial Guinea)"},
}


@lru_cache(maxsize=1)
def crosswalk() -> pd.DataFrame:
    cw = pd.read_parquet(CLEAN / "medicinal_crosswalk.parquet")
    for sp, c in CURATED_MEDICINAL.items():
        m = (cw.SpeciesAccepted == sp) & ~cw.medicinal_documented
        cw.loc[m, ["medicinal_documented", "med_sources", "example_uses", "n_med_references"]] = [True, c["source"], c["uses"], 1]
    return cw


@lru_cache(maxsize=1)
def phenobs_species() -> set[str]:
    p = ROOT / "data" / "raw" / "phenobs" / "Phenology_stages_2019_2023.csv"
    df = pd.read_csv(p, sep=";", encoding="utf-8-sig")
    df = df[pd.to_numeric(df.FlPeak, errors="coerce").notna()]
    g = df.groupby("Species").Botanic_Garden.nunique()
    return set(g[g >= 1].index)


def preset_matrices(species: str) -> pd.DataFrame:
    """QC-passing matrices usable as Simulate presets (unmanipulated means/pooled preferred)."""
    md = compadre.metadata()
    s = md[(md.SpeciesAccepted == species) & ~md.qc_A_has_na & ~md.qc_negative & ~md.qc_U_survival_gt1]
    order = {"Mean": 0, "Pooled": 1, "Individual": 2}
    s = s.assign(_o=s.MatrixComposite.astype(object).map(order).fillna(3),
                 _t=(s.MatrixTreatment.astype(object).fillna("") != "Unmanipulated").astype(int))
    return s.sort_values(["_t", "_o", "MatrixStartYear"])


def assess(species: str, task: str | None = None, region: dict | None = None,
           local_evidence: dict | None = None, occurrence_count: int | None = None) -> dict:
    """Return eligibility for one task (or all tasks)."""
    local_evidence = local_evidence or {}
    cw = crosswalk()
    row = cw[cw.SpeciesAccepted == species]
    in_compadre = len(row) > 0
    presets = preset_matrices(species) if in_compadre else pd.DataFrame()
    split_ok = bool(len(presets) and presets.qc_split_available.any())
    studies = [s for s in hv.STUDIES if s["species"] == species]
    medicinal = bool(in_compadre and row.medicinal_documented.iloc[0])
    out: dict[str, dict] = {}

    def put(t, status, reasons, missing=None, tier=None, enables=None):
        out[t] = {"task": t, "status": status, "reasons": reasons, "missing": missing or [], "tier": tier,
                  "enables": enables or []}

    # demographic projection
    if len(presets):
        put("demographic_projection", "enabled",
            [f"{len(presets)} QC-passing COMPADRE matrices ({presets.StudyID.nunique()} studies)"],
            tier="published-model")
    elif in_compadre:
        put("demographic_projection", "blocked", ["COMPADRE matrices exist but all fail QC (NA / survival>1)"],
            ["a QC-passing matrix"])
    else:
        put("demographic_projection", "blocked", ["species has no COMPADRE v6.26.3.0 matrix"],
            ["stage-structured demographic census (>=2 years, marked plants)"])

    # harvest comparison (Tier A)
    tier_a = [s for s in studies if s["tier"] == "A"]
    if tier_a:
        put("harvest_comparison", "enabled",
            [f"{s['citation'].split('(')[0].strip()} ({s['design']}, organ: {s['organ']})" for s in tier_a],
            tier="A", enables=[s["id"] for s in tier_a])
    else:
        put("harvest_comparison", "blocked", ["no audited harvest-treatment matrices for this species"],
            ["matched harvested vs unharvested demographic study"], tier="C")

    # rotation extrapolation
    exp = [s for s in tier_a if s["design"] == "experimental"]
    if exp:
        put("rotation_extrapolation", "enabled-with-caveats",
            ["experimental harvest + control matrices in same population; repeated-harvest response is assumed (E06)"],
            tier="A-extrapolated", enables=[s["id"] for s in exp])
    else:
        put("rotation_extrapolation", "blocked",
            ["needs an experimental harvest treatment with a same-population control"],
            ["experimental harvest with controls and >=2 post-harvest censuses"])

    # hypothetical (Tier B)
    if split_ok:
        put("hypothetical_harvest", "enabled-with-caveats",
            ["survival/fecundity split available; counterfactual removal is a mathematical assumption",
             "E05 back-test: generic removal models mis-predicted the Nardostachys experiment (MAE 0.068): show as sensitivity range only"],
            tier="B")
    else:
        put("hypothetical_harvest", "blocked", ["no matrix with a valid U/F split"], ["QC-passing U/F matrices"])

    # local quota - never enabled without the full local evidence set
    missing = [k for k in LOCAL_QUOTA_REQUIREMENTS if not local_evidence.get(k)]
    if not missing:
        status = "conditional field assessment eligible"
        put("local_quota", "enabled-with-caveats", ["all local evidence declared; requires human/expert approval"],
            tier="conditional")
    else:
        status = "study-backed scenario only" if tier_a else "cannot estimate safe local rate"
        put("local_quota", "blocked",
            ["Not estimable from the available evidence: COMPADRE matrices describe studied populations, not this site's stock."],
            [LOCAL_QUOTA_REQUIREMENTS[k] for k in missing], tier="C")
    out["local_quota"]["answer_status"] = status

    # habitat model
    if occurrence_count is None:
        put("habitat_model", "unknown", ["occurrence data not yet fetched for this region"], ["fetch GBIF occurrences"])
    elif occurrence_count >= 100:
        put("habitat_model", "enabled-with-caveats",
            [f"{occurrence_count} cleaned occurrences; spatial block CV required, suitability != abundance"])
    else:
        put("habitat_model", "blocked", [f"only {occurrence_count} cleaned occurrences (<100)"],
            [">=100 cleaned, de-duplicated, wild occurrences with coordinate uncertainty <=10 km"])

    # phenology window (PhenObs, botanical gardens)
    if species in phenobs_species():
        put("phenology_window", "enabled-with-caveats", ["PhenObs botanical-garden records (not wild populations; E08)"])
    else:
        put("phenology_window", "blocked", ["species not monitored in PhenObs 2019-2023"],
            ["flowering monitoring across >=3 sites/years"])

    put("survey_planning", "enabled" if region else "unknown",
        ["planning grid + environmental representation (always available for a valid region)"] if region
        else ["choose a region on the globe"])
    put("evidence_planning", "enabled", ["ranks missing measurements by the decisions they would unlock"])

    summary = {
        "species": species, "in_compadre": in_compadre, "medicinal_documented": medicinal,
        "overall_tier": "A" if tier_a else ("B" if split_ok else "C"),
        "quota_answer": status, "tasks": out if task is None else {task: out[task]},
        "rule_version": "eligibility-1.0",
    }
    return summary
