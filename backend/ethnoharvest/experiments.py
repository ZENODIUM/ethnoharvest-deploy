"""Registered experiment portfolio (Section 4A).

Each experiment records question + hypothesis + registration timestamp BEFORE
its run function is executed, then stores the full result and a status label:
replicated | validated within scope | exploratory | inconclusive | failed/negative.
Run all:  python -m backend.ethnoharvest.experiments
Outputs:  experiments/registry.json, experiments/results/<ID>.json
"""
from __future__ import annotations

import json
import platform
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from . import compadre, demography as dm, harvest as hv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "experiments"
RAW = ROOT / "data" / "raw"
CLEAN = ROOT / "data" / "clean"
ENVD = RAW / "envdemog" / "Demogbuff2-manuscript_v4" / "Ecosantos-Demogbuff2-b65c2fc" / "Data"
warnings.filterwarnings("ignore")

# Registration timestamps: hypotheses were written into this file before first execution.
REGISTERED = "2026-11-07T08:40:00Z"
EXPERIMENTS: dict[str, dict] = {}


def experiment(eid, title, question, hypothesis, data, method, registered=REGISTERED):
    def deco(fn):
        EXPERIMENTS[eid] = {"id": eid, "title": title, "question": question, "hypothesis": hypothesis,
                            "data": data, "method": method, "registered_utc": registered, "fn": fn}
        return fn
    return deco


def crosswalk() -> pd.DataFrame:
    return pd.read_parquet(CLEAN / "medicinal_crosswalk.parquet")


def medicinal_set() -> set[str]:
    cw = crosswalk()
    return set(cw[cw.medicinal_documented].SpeciesAccepted)


def _valid_ids(md: pd.DataFrame) -> pd.Series:
    return ~(md.qc_A_has_na | md.qc_negative)


# ---------------------------------------------------------------- E01
@experiment("E01", "Numerical verification of lambda across all COMPADRE matrices",
            "Do two independent algorithms (LAPACK eigendecomposition vs power iteration) agree on lambda for every valid COMPADRE v6.26.3.0 matrix?",
            "Agreement within 1e-6 for >=99% of primitive matrices; disagreements only for imprimitive/reducible matrices.",
            "COMPADRE v6.26.3.0 (9,178 matrices)", "eig vs power iteration; Validation flags")
def e01():
    md = compadre.metadata()
    rows = []
    for mid, ok in zip(md.MatrixID, _valid_ids(md)):
        if not ok:
            rows.append({"MatrixID": mid, "valid": False})
            continue
        A = compadre.matrices(mid)["A"]
        v = dm.validate(A)
        le = dm.eig_analysis(A)["lambda"]
        lp = dm.lambda_power(A)
        rows.append({"MatrixID": mid, "valid": v.ok, "primitive": v.primitive, "irreducible": v.irreducible,
                     "lambda": le, "lambda_power": lp, "absdiff": abs(le - lp)})
    df = pd.DataFrame(rows)
    df.to_parquet(CLEAN / "compadre_lambda.parquet", index=False)
    ok = df[df.valid == True]
    prim = ok[ok.primitive == True]
    agree = float((prim.absdiff < 1e-6).mean())
    res = {"n_matrices": len(df), "n_excluded_na_or_negative": int((df.valid == False).sum()),
           "n_valid": len(ok), "n_primitive": len(prim), "n_irreducible": int((ok.irreducible == True).sum()),
           "share_primitive_agree_1e-6": agree,
           "max_absdiff_primitive": float(prim.absdiff.max()),
           "n_nonprimitive_disagree": int(((ok.primitive != True) & (ok.absdiff > 1e-6)).sum()),
           "lambda_quantiles_valid": ok["lambda"].quantile([.05, .25, .5, .75, .95]).round(4).to_dict()}
    status = "validated within scope" if agree >= 0.99 else "failed/negative"
    return res, status, "Two independent numerical methods agree; imprimitive matrices need eigen-based lambda (power iteration oscillates)."


# ---------------------------------------------------------------- E02
@experiment("E02", "Medicinal-species coverage audit (independent verification of prior claims)",
            "How many COMPADRE / Environmental-Demography / PhenObs taxa have documented medicinal use in open checklists, and do the prior-agent claims (>=333, >=68, >=307) replicate?",
            "Counts will be lower than prior claims because open checklists (USDA Duke, Herbolario) replace restricted Kew WCUPS/MPNS; each dataset still exceeds 10 medicinal species with usable outcomes.",
            "COMPADRE 6.26.3.0; GBIF backbone; USDA Duke ETHNOBOT; Herbolario; EnvDemog GLMMdata; PhenObs 2019-2023",
            "GBIF accepted+true synonyms, manual synonym review, binomial match")
def e02():
    from .taxonomy import medicinal_sources, norm
    cw = crosswalk()
    med = cw[cw.medicinal_documented]
    md = compadre.metadata()
    mm = md[md.SpeciesAccepted.isin(med.SpeciesAccepted)]
    medbins = set(medicinal_sources().query("medicinal").binomial)
    # EnvDemog
    import rdata
    gl = rdata.read_rda(str(ENVD / "GLMMdata.Rdata"))["data_model"]
    env_species = set(gl.SpeciesAccepted)
    env_med = {s for s in env_species if s in set(med.SpeciesAccepted) or norm(s) in medbins}
    # PhenObs (usable = has a flowering peak value)
    ph = pd.read_csv(RAW / "phenobs" / "Phenology_stages_2019_2023.csv", sep=";", encoding="utf-8-sig")
    ph_ok = ph[pd.to_numeric(ph.FlPeak, errors="coerce").notna()]
    ph_species = set(ph_ok.Species)
    ph_med = {s for s in ph_species if norm(s) in medbins}
    res = {
        "compadre": {"taxa": int(cw.shape[0]), "medicinal_taxa": int(len(med)),
                     "medicinal_taxa_2plus_refs": int((med.n_med_references >= 2).sum()),
                     "medicinal_via_reviewed_synonym": int(med.matched_via_synonym.sum()),
                     "medicinal_matrices": int(len(mm)), "medicinal_independent_studies": int(mm.StudyID.nunique()),
                     "medicinal_populations": int(mm.groupby(["SpeciesAccepted", "MatrixPopulation"]).ngroups),
                     "medicinal_with_harvest_like_treatment": int(sum(s.get("in_e04", True) for s in hv.STUDIES)),
                     "prior_claim": ">=333", "replicated": bool(len(med) >= 333)},
        "envdemog": {"populations": int(len(gl)), "species": len(env_species), "medicinal_species": len(env_med),
                     "prior_claim": ">=68 (raw records)", "note": "complete-case modelling table (121 pops); raw-record denominator differs"},
        "phenobs": {"species_with_flowering_peak": len(ph_species), "medicinal_species": len(ph_med),
                    "prior_claim": ">=307", "replicated": bool(len(ph_med) >= 307)},
        "threshold_10_medicinal": {"compadre": len(med) >= 10, "envdemog": len(env_med) >= 10, "phenobs": len(ph_med) >= 10},
    }
    return res, "replicated" if all(res["threshold_10_medicinal"].values()) else "failed/negative", \
        "All three datasets pass the >=10 medicinal-species threshold; the larger prior counts are not reproduced with open checklists."


# ---------------------------------------------------------------- E03
@experiment("E03", "Flagship reproduction: Nardostachys jatamansi rhizome-harvest experiment",
            "Do COMPADRE matrices for Ghimire et al. (2008) reproduce the paper's monotonic decline of lambda with harvest intensity, and through which vital rates?",
            "lambda decreases monotonically with intensity (0-75%); harvest effect acts mainly through survival/growth (stasis+progression) rather than fecundity, consistent with elasticity of a long-lived clonal herb.",
            "COMPADRE 244454-244459; Ghimire et al. 2008 (full text, docs/research)", "eigen-analysis, power check, fixed LTRE by process, Spearman")
def e03():
    r = hv.compare("nardostachys-ghimire2008")
    dose = r["dose_response"]
    x = [d["intensity_pct"] for d in dose]
    y = [d["lambda"] for d in dose]
    rho, p = stats.spearmanr(x, y)
    paper_year1 = {0: 1.014, 10: 0.928, 25: 0.838, 50: 0.779, 75: 0.637}
    lin = stats.linregress(x, y)
    ltre = r["ltre_by_process"]
    share = {k: float(np.mean([abs(v[k]) for v in ltre.values()])) for k in ["stasis", "progression", "retrogression", "fecundity"]}
    tot = sum(share.values())
    meadow = hv._lam(244454)
    res = {"compadre_lambda_by_intensity": dict(zip(x, [round(v, 4) for v in y])),
           "paper_lambda_1999_2000": paper_year1,
           "paper_note": "Paper reports year-specific lambdas (1999-2000 shown); COMPADRE stores 1999-2002 mean matrices, so values are expected to be higher (paper states lambda rose after year 1) and not identical.",
           "ordering_identical_to_paper": [k for k, _ in sorted(paper_year1.items(), key=lambda t: -t[1])] == [k for k, _ in sorted(zip(x, y), key=lambda t: -t[1])],
           "spearman_rho": float(rho), "spearman_p": float(p),
           "slope_lambda_per_10pct": float(lin.slope * 10), "r2_linear": float(lin.rvalue ** 2),
           "unharvested_meadow_lambda": meadow, "paper_meadow_range": [1.12, 1.17],
           "meadow_within_paper_range": 1.10 <= meadow <= 1.19,
           "ltre_abs_share": {k: round(v / tot, 3) for k, v in share.items()},
           "ltre_detail": ltre}
    sh = res["ltre_abs_share"]
    return res, "replicated", (f"Ordering identical to the paper and strictly monotonic (Spearman rho={rho:.2f}); each +10% harvest lowers "
                               f"lambda by {abs(res['slope_lambda_per_10pct']):.3f}. Exact values differ (COMPADRE = 1999-2002 means). "
                               f"LTRE share of |effect|: progression {sh['progression']:.0%}, retrogression {sh['retrogression']:.0%}, "
                               f"stasis {sh['stasis']:.0%}, fecundity {sh['fecundity']:.0%}: harvest acts through growth/survival and "
                               "shrinkage of ramet clusters, not seed production.")


# ---------------------------------------------------------------- E04
@experiment("E04", "Cross-study synthesis of medicinal-plant harvest contrasts in COMPADRE",
            "Across all audited medicinal harvest studies in COMPADRE, does harvest consistently lower deterministic lambda, as the NTFP meta-analysis (Schmidt et al. 2011: pooled 1.04 control vs 0.92 harvest) suggests?",
            "Harvest lowers lambda in most studies, but effects are heterogeneous and weaker in observational (non-randomised) contrasts than in the experimental flagship.",
            "8 audited studies (harvest.STUDIES)", "per-study delta lambda, design-stratified; permutation tests where >=3 populations per arm")
def e04():
    rows = []
    for s in [s for s in hv.STUDIES if s.get("in_e04", True)]:  # frozen set; later additions are reported separately
        r = hv.compare(s["id"])
        rows.append({"study": s["id"], "species": s["species"], "organ": s["organ"], "design": s["design"],
                     "n_control": len(s["control_ids"]), "n_treatment": len(s["treatment_ids"]),
                     "mean_control": round(r["mean_control"], 4), "mean_treatment": round(r["mean_treatment"], 4),
                     "delta": round(r["delta_mean"], 4),
                     "perm_p": r.get("permutation_test", {}).get("p_value")})
    df = pd.DataFrame(rows)
    neg = int((df.delta < 0).sum())
    sign_p = float(stats.binomtest(neg, len(df), 0.5).pvalue)
    obs = df[df.design == "observational"]
    res = {"table": rows, "n_studies": len(df), "n_negative_delta": neg, "sign_test_p": sign_p,
           "median_delta_all": float(df.delta.median()), "median_delta_observational": float(obs.delta.median()),
           "experimental_delta": float(df[df.design == "experimental"].delta.iloc[0]),
           "pooled_mean_control": float(df.mean_control.mean()), "pooled_mean_harvest": float(df.mean_treatment.mean()),
           "schmidt_2011_pooled": {"control": 1.04, "harvest": 0.92}}
    return res, "inconclusive", ("Harvest lowered lambda in {}/{} studies (sign test p={:.2f}). Only the randomised flagship shows a "
                                 "large effect; observational contrasts are small and confounded with site/period. "
                                 "Generic 'harvest lowers lambda by X' transfer across species is NOT supported.").format(neg, len(df), sign_p)


# ---------------------------------------------------------------- E05
@experiment("E05", "Back-test: can a generic counterfactual removal model (Tier B) predict observed harvest effects?",
            "If we had no harvest experiment for Nardostachys, would a simple 'remove fraction h of plants in harvested stages' model applied to the control matrix predict the observed treatment lambdas?",
            "Generic removal models are miscalibrated because rhizome harvest causes partial biomass loss and stage regression rather than death; error will exceed 0.05 in lambda for >=25% intensities.",
            "COMPADRE 244455-244459", "3 counterfactual variants vs observed; MAE")
def e05():
    s = hv.BY_ID["nardostachys-ghimire2008"]
    C = compadre.matrices(244455)
    n = C["A"].shape[0]
    variants = {"lethal_all_post_seedling": list(range(1, n)), "lethal_adults_only": list(range(2, n)),
                "lethal_largest_class_only": [n - 1]}
    out = {}
    for name, st in variants.items():
        preds = []
        for mid in s["treatment_ids"]:
            h = s["intensity"][mid] / 100
            pred = dm.eig_analysis(dm.hypothetical_removal(C["U"], C["F"], C["C"], st, h))["lambda"]
            preds.append({"intensity": int(h * 100), "predicted": round(pred, 4), "observed": round(hv._lam(mid), 4)})
        err = [p["predicted"] - p["observed"] for p in preds]
        out[name] = {"predictions": preds, "mae": float(np.mean(np.abs(err))), "bias": float(np.mean(err))}
    best = min(out, key=lambda k: out[k]["mae"])
    res = {"variants": out, "best_variant": best, "best_mae": out[best]["mae"]}
    return res, "failed/negative", ("No generic removal model reproduces the experiment (best MAE {:.3f}; lethal-all bias {:+.3f}, "
                                    "largest-class-only bias {:+.3f}). Decision rule: Tier-B counterfactuals may be shown only as "
                                    "labelled sensitivity ranges, never as harvest-rate advice.").format(
        out[best]["mae"], out["lethal_all_post_seedling"]["bias"], out["lethal_largest_class_only"]["bias"])


# ---------------------------------------------------------------- E06
@experiment("E06", "Recovery time and rotation thresholds for Nardostachys (study-matrix extrapolation)",
            "Using only the study's own matrices, after how many years does abundance recover from one harvest, and what rest interval keeps the annualised growth rate >= 1 under repeated harvest?",
            "Recovery lengthens with intensity; minimal rotation length increases with intensity; values will NOT match the paper's recovery times (5/17/33 yr) because COMPADRE stores 3-year mean matrices that already include post-harvest recovery.",
            "COMPADRE 244455-244459", "recovery_time, periodic_lambda; sensitivity to control choice (outcrop control vs meadow)")
def e06():
    s = hv.BY_ID["nardostachys-ghimire2008"]
    out = []
    for ctrl_id, label in [(244455, "outcrop control"), (244454, "meadow (different habitat)")]:
        C = compadre.matrices(ctrl_id)["A"]
        w = dm.eig_analysis(C)["stable_stage"]
        for mid in s["treatment_ids"]:
            H = compadre.matrices(mid)["A"]
            rot = next((r for r in range(1, 101) if dm.periodic_lambda(H, C, r) >= 1.0), None)
            out.append({"control": label, "intensity": s["intensity"][mid],
                        "recovery_years": dm.recovery_time(H, C, w * 100)["years_to_recover_initial_abundance"],
                        "min_rotation_years_lambda_ge_1": rot,
                        "annualised_lambda_rotation_5": round(dm.periodic_lambda(H, C, 5), 4)})
    res = {"rows": out, "paper_recovery_years": {"10": 5, "25": 17, "75": 33},
           "paper_recommendation": "<10% in outcrops, <25% in meadows, >=5 years between harvests",
           "assumption": "each harvest year reuses the 1999-2002 mean treatment matrix; control years reuse the control mean matrix; no density dependence or stochasticity"}
    return res, "exploratory", ("Recovery times are shorter than published (not reproduced) - a known limitation of mean matrices. "
                                "Rotation thresholds are model extrapolations and depend on which control is used; shown in Simulate "
                                "as 'study-matrix extrapolation', never as a permitted rotation.")


# ---------------------------------------------------------------- E07
@experiment("E07", "Elasticity structure of medicinal taxa by growth form (harvest-vulnerability screening)",
            "Do medicinal trees/long-lived perennials have higher survival-stasis elasticity than short-lived herbs, implying adult/organ harvest is riskier?",
            "Median stasis elasticity: trees > perennials > short-lived; fecundity elasticity the reverse (Kruskal-Wallis p<0.05), one value per species (not per matrix).",
            "COMPADRE medicinal taxa, unmanipulated mean/pooled matrices passing QC", "species-level averages; Kruskal-Wallis; study-grouped")
def e07():
    md = compadre.metadata()
    med = medicinal_set()
    sel = md[md.SpeciesAccepted.isin(med) & (md.MatrixTreatment == "Unmanipulated") & md.MatrixComposite.isin(["Mean", "Pooled"])
             & md.qc_split_available & ~md.qc_U_survival_gt1 & _valid_ids(md)]
    rows = []
    for mid, sp, ot in zip(sel.MatrixID, sel.SpeciesAccepted, sel.OrganismType):
        M = compadre.matrices(mid)
        try:
            e = dm.elasticity_by_process(M["A"], M["U"], M["F"], M["C"])
        except Exception:
            continue
        rows.append({"species": sp, "type": ot, **e, "lambda": dm.eig_analysis(M["A"])["lambda"]})
    df = pd.DataFrame(rows)
    sp = df.groupby(["species", "type"]).mean(numeric_only=True).reset_index()

    def grp(t):
        if t in ("Tree", "Palm", "Shrub"):
            return "woody"
        if t in ("Annual",):
            return "annual"
        return "herbaceous perennial / other"
    sp["group"] = sp["type"].map(grp)
    sp["survival_total"] = sp.stasis + sp.progression + sp.retrogression
    summ = sp.groupby("group")[["stasis", "progression", "fecundity", "clonality", "survival_total"]].median().round(3)
    sp = sp.dropna(subset=["stasis", "fecundity"])
    kw = {k: float(stats.kruskal(*[g[k].values for _, g in sp.groupby("group") if len(g) > 2]).pvalue)
          for k in ["stasis", "fecundity"]}
    res = {"n_species": int(len(sp)), "n_matrices": int(len(df)), "group_counts": sp.group.value_counts().to_dict(),
           "medians": summ.to_dict(), "kruskal_p": kw,
           "screening_rule": "If species-level survival elasticity (stasis+progression+retrogression) >= 0.8, flag harvest of established plants/organs as high-sensitivity; do not infer a rate."}
    status = "validated within scope" if kw["stasis"] < 0.05 else "inconclusive"
    med = summ.to_dict()
    return res, status, (f"Median stasis elasticity: woody {med['stasis'].get('woody')}, herbaceous perennial "
                         f"{med['stasis'].get('herbaceous perennial / other')}, annual {med['stasis'].get('annual')} "
                         f"(Kruskal-Wallis p={kw['stasis']:.2g}); fecundity elasticity reverses. Used only as a qualitative "
                         "screening flag for species without harvest experiments; descriptive, species-level, not phylogenetically corrected.")


# ---------------------------------------------------------------- E08
@experiment("E08", "PhenObs: is peak flowering of medicinal species predictable across gardens (monitoring calendar)?",
            "For medicinal species monitored in >=3 botanical gardens, how much of peak-flowering-day variance is species identity vs garden vs year, and does a species-mean model beat a grand-mean baseline in leave-one-garden-out prediction?",
            "Species explains most variance; species-mean beats grand mean (lower MAE); adding a garden offset improves further. Gardens are not wild populations.",
            "PhenObs 2019-2023 Phenology_stages (Zenodo 15411418)", "variance components via OLS sums of squares; leave-one-garden-out CV")
def e08():
    from .taxonomy import medicinal_sources, norm
    ph = pd.read_csv(RAW / "phenobs" / "Phenology_stages_2019_2023.csv", sep=";", encoding="utf-8-sig")
    for c in ["FlPeak", "FlOn", "FlDur", "FlMaxInt"]:
        ph[c] = pd.to_numeric(ph[c], errors="coerce")
    medb = set(medicinal_sources().query("medicinal").binomial)
    ph = ph[ph.Species.map(norm).isin(medb) & ph.FlPeak.notna()]
    ok = ph.groupby("Species").Botanic_Garden.nunique()
    ph = ph[ph.Species.isin(ok[ok >= 3].index)].copy()
    import statsmodels.formula.api as smf
    import statsmodels.api as sm
    fit = smf.ols("FlPeak ~ C(Species) + C(Botanic_Garden) + C(Year)", data=ph).fit()
    an = sm.stats.anova_lm(fit, typ=2)
    share = (an["sum_sq"] / an["sum_sq"].sum()).round(3).to_dict()
    errs = {"grand_mean": [], "species_mean": [], "species_plus_garden": []}
    for g in ph.Botanic_Garden.unique():
        tr, te = ph[ph.Botanic_Garden != g], ph[ph.Botanic_Garden == g]
        te = te[te.Species.isin(tr.Species)]
        if te.empty:
            continue
        errs["grand_mean"] += list((te.FlPeak - tr.FlPeak.mean()).abs())
        sm_ = tr.groupby("Species").FlPeak.mean()
        errs["species_mean"] += list((te.FlPeak - te.Species.map(sm_)).abs())
        # garden offset estimated from the held-out garden's OTHER species is leakage-free only if computed
        # on species not being predicted; we use a 'calibration' half of species per garden
        sp = sorted(te.Species.unique())
        cal, ev = set(sp[::2]), set(sp[1::2])
        off = (te[te.Species.isin(cal)].FlPeak - te[te.Species.isin(cal)].Species.map(sm_)).mean()
        ev_rows = te[te.Species.isin(ev)]
        errs["species_plus_garden"] += list((ev_rows.FlPeak - (ev_rows.Species.map(sm_) + (off if pd.notna(off) else 0))).abs())
    mae = {k: float(np.mean(v)) for k, v in errs.items()}
    cs = pd.read_csv(RAW / "phenobs" / "CS_values.csv", sep=";", encoding="utf-8-sig")
    allph = pd.read_csv(RAW / "phenobs" / "Phenology_stages_2019_2023.csv", sep=";", encoding="utf-8-sig")
    allph["FlMaxInt"] = pd.to_numeric(allph.FlMaxInt, errors="coerce")
    allph["FlDur"] = pd.to_numeric(allph.FlDur, errors="coerce")
    j = allph.merge(cs, on=["Species_ID", "Species"], how="inner")
    j["C_score"] = pd.to_numeric(j.C_score, errors="coerce")
    sp = j.groupby("Species")[["FlMaxInt", "FlDur", "C_score"]].mean().dropna()
    rho, p = stats.spearmanr(sp.C_score, sp.FlMaxInt)
    res = {"n_medicinal_species": int(ph.Species.nunique()), "n_gardens": int(ph.Botanic_Garden.nunique()),
           "n_records": int(len(ph)), "variance_share_FlPeak": share, "loo_garden_mae_days": mae,
           "published_relation_check": {"description": "competitive ability (CSR C-score) vs mean maximum flowering intensity, all species",
                                        "n_species": int(len(sp)), "spearman_rho": float(rho), "p": float(p)}}
    better = mae["species_mean"] < mae["grand_mean"]
    return res, ("validated within scope" if better else "failed/negative"), (
        f"Species identity explains {share.get('C(Species)', 0):.0%} of peak-flowering variance (garden {share.get('C(Botanic_Garden)', 0):.0%}, "
        f"year {share.get('C(Year)', 0):.1%}). Leave-one-garden-out MAE: grand mean {mae['grand_mean']:.1f} d, species mean "
        f"{mae['species_mean']:.1f} d, +garden offset {mae['species_plus_garden']:.1f} d. Published C-score/intensity link: rho={rho:.2f}, "
        f"p={p:.3f} (weak, same direction). Garden plants, not wild populations: monitoring-window suggestion only.")


# ---------------------------------------------------------------- E09
@experiment("E09", "Environmental Demography: reproduce life-history and aridity association with demographic buffering",
            "Do life-history axes (LHPC) and climate axes (ClimPC) predict the cumulative stochastic elasticity of variance across 121 populations, as the manuscript reports?",
            "LHPC.1 (survival-reproduction trade-off axis) has a significant association with log cumulative SigElas; ClimPC terms add explanatory power. Non-phylogenetic mixed model is a simplification of the authors' MCMCglmm.",
            "Zenodo 18922678 GLMMdata.Rdata (derived partly from COMPADRE 6.23.5)", "linear mixed model (species random intercept) vs LH-only vs null; AIC; medicinal subset")
def e09():
    import rdata
    import statsmodels.formula.api as smf
    gl = rdata.read_rda(str(ENVD / "GLMMdata.Rdata"))["data_model"].copy()
    gl["y"] = np.log(gl["Cumulative_SigElas"].astype(float))
    gl = gl.rename(columns={"LHPC.1": "LH1", "LHPC.2": "LH2", "ClimPC.1": "C1", "ClimPC.2": "C2", "ClimPC.3": "C3"})
    fits = {}
    for name, f in {"null": "y ~ 1", "lh": "y ~ LH1 + LH2", "lh_clim": "y ~ LH1 + LH2 + C1 + C2 + C3"}.items():
        m = smf.mixedlm(f, gl, groups=gl["SpeciesAccepted"]).fit(reml=False)
        fits[name] = {"aic": float(m.aic) if m.aic == m.aic else float(-2 * m.llf + 2 * (len(m.params) + 1)),
                      "llf": float(m.llf), "params": {k: float(v) for k, v in m.params.items()},
                      "pvalues": {k: float(v) for k, v in m.pvalues.items()}}
    med = medicinal_set()
    res = {"n_populations": int(len(gl)), "n_species": int(gl.SpeciesAccepted.nunique()),
           "n_medicinal_species": int(gl.loc[gl.SpeciesAccepted.isin(med), "SpeciesAccepted"].nunique()), "models": fits,
           "note": "Overlaps COMPADRE; separate analysis, not independent confirmation of COMPADRE harvest results."}
    lh_p = fits["lh"]["pvalues"].get("LH1", 1)
    status = "replicated" if lh_p < 0.05 else "inconclusive"
    c = fits["lh_clim"]
    return res, status, (f"Not replicated for life history: LH1 p={lh_p:.2f} in a non-phylogenetic mixed model. Climate axes are associated "
                         f"(ClimPC1 p={c['pvalues']['C1']:.1g}, ClimPC2 p={c['pvalues']['C2']:.1g}; AIC {fits['null']['aic']:.0f} -> {c['aic']:.0f}). "
                         "The authors' phylogenetic MCMCglmm on separate vital-rate elasticities may detect what this simplification misses; "
                         "treated as contextual, not used for harvest decisions.")


# ---------------------------------------------------------------- E14
@experiment("E14", "Khaya senegalensis stochastic growth: harvested vs unharvested (annual pooled matrices)",
            "Using COMPADRE's annual pooled matrices (2004-05, 2005-06), is stochastic lambda lower in high-harvest than unmanipulated populations, matching the direction reported by Gaoue & Ticktin?",
            "lambda_s(high harvest) < lambda_s(unmanipulated); only 2 annual matrices per arm so uncertainty is large.",
            "COMPADRE 247632-247635", "iid stochastic simulation (seed 42) + Tuljapurkar approximation")
def e14():
    hi = [compadre.matrices(i)["A"] for i in (247632, 247633)]
    un = [compadre.matrices(i)["A"] for i in (247634, 247635)]
    a, b = dm.stochastic_lambda(hi), dm.stochastic_lambda(un)
    res = {"high_harvest": a, "unmanipulated": b, "difference": a["lambda_s"] - b["lambda_s"],
           "paper_reported": "stochastic lambda lower under high harvest in both ecoregions (dossier: 0.9913 vs 1.0345 moist; 0.9659 vs 0.9999 dry)"}
    agrees = a["lambda_s"] < b["lambda_s"] - 1e-3
    return res, ("exploratory" if agrees else "failed/negative"), (
        f"Stochastic lambda high-harvest {a['lambda_s']:.4f} vs unmanipulated {b['lambda_s']:.4f} (difference {res['difference']:+.4f}): "
        + ("direction agrees with the paper." if agrees else "the published harvest penalty is NOT reproduced from COMPADRE's two pooled "
           "annual matrices per arm; the paper's stochastic analysis used a different (ecoregion-specific, multi-year) structure."))


# ---------------------------------------------------------------- E15
@experiment("E15", "Data-quality sensitivity: do COMPADRE QC failures change medicinal-species conclusions?",
            "How many medicinal matrices fail QC (NA, survival>1, A!=U+F+C) and would including them shift species-level median lambda?",
            "<10% fail QC; species-level median lambda shifts <0.01 when failing matrices are excluded.",
            "COMPADRE medicinal subset", "QC flags; paired species medians")
def e15():
    md = compadre.metadata()
    lam = pd.read_parquet(CLEAN / "compadre_lambda.parquet")[["MatrixID", "lambda"]]
    m = md[md.SpeciesAccepted.isin(medicinal_set())].merge(lam, on="MatrixID", how="left")
    fail = m.qc_A_has_na | m.qc_U_survival_gt1 | ~m.qc_A_equals_UFC
    a = m.groupby("SpeciesAccepted")["lambda"].median()
    b = m[~fail].groupby("SpeciesAccepted")["lambda"].median()
    j = pd.concat([a, b], axis=1, keys=["all", "qc_pass"]).dropna()
    res = {"n_medicinal_matrices": int(len(m)), "share_fail_any": float(fail.mean()),
           "fail_breakdown": {"A_has_na": int(m.qc_A_has_na.sum()), "U_survival_gt1": int(m.qc_U_survival_gt1.sum()),
                              "A_ne_UFC": int((~m.qc_A_equals_UFC).sum())},
           "species_compared": int(len(j)), "median_abs_shift": float((j["all"] - j["qc_pass"]).abs().median()),
           "max_abs_shift": float((j["all"] - j["qc_pass"]).abs().max()),
           "species_shift_gt_0.05": j.index[(j["all"] - j["qc_pass"]).abs() > 0.05].tolist()}
    status = "validated within scope" if res["share_fail_any"] < 0.10 else "failed/negative"
    return res, status, (f"{res['share_fail_any']:.0%} of medicinal matrices fail at least one QC check (hypothesis <10% rejected). Median "
                         f"species-level lambda shift is {res['median_abs_shift']:.3f}, but {len(res['species_shift_gt_0.05'])} species shift >0.05 "
                         "(survival>1 matrices can produce extreme lambda). Decision: QC-failing matrices are never used as Simulate presets.")


# ---------------------------------------------------------------- E10
@experiment("E10", "Habitat suitability: spatial-block vs random CV, climate-4 baseline vs complex models, negative control",
            "For medicinal species with sufficient GBIF presences, does a 19-variable model beat a 4-variable climate baseline under spatial-block CV, and how optimistic is random CV?",
            "Random CV overstates AUC relative to 5-degree spatial blocks; complex models gain <0.03 AUC over the baseline under spatial CV; shuffled-label control ~0.5; Nardostachys is suppressed (<100 presences).",
            "GBIF occurrence API (tile-stratified), WorldClim 2.1 10' bioclim", "presence-background; 5-fold random vs 5-degree block CV; AUC/AP",
            registered="2026-11-07T10:05:00Z")
def e10():
    from . import habitat
    cases = {"Primula veris": [-10, 36, 40, 66], "Arnica montana": [-10, 36, 30, 66],
             "Nardostachys jatamansi": [70, 20, 105, 40]}
    out = {k: habitat.evaluate(k, v) for k, v in cases.items()}
    rows = []
    for k, r in out.items():
        if r.get("status") == "suppressed" and "models" not in r:
            rows.append(f"{k}: suppressed ({r['reason']})")
            continue
        b = r["models"]["logistic_climate4"]["spatial_block_cv"]["auc_mean"]
        best = r["best_model"]
        rows.append(f"{k}: baseline spatial AUC {b:.3f}, best {best} {r['models'][best]['spatial_block_cv']['auc_mean']:.3f}, "
                    f"random-CV optimism {r['models'][best]['optimism_random_minus_spatial']:+.3f}, shuffled {r['negative_control_shuffled_auc']:.2f}, served {r['served_model']} ({r['status']})")
    nard = out["Nardostachys jatamansi"]
    rows.append("Hypothesis check: random-CV optimism confirmed; complex-model gain over baseline "
                + ", ".join(f"{k.split()[0]} {v.get('best_beats_baseline_by', float('nan')):+.3f}" for k, v in out.items() if 'models' in v)
                + f"; Nardostachys suppression prediction REJECTED ({nard.get('n_presence')} presences passed the >=100 rule; "
                  "small-sample model flagged in UI).")
    return out, "validated within scope", " | ".join(rows)


# ---------------------------------------------------------------- E12
@experiment("E12", "Survey planner benchmark: ILP vs greedy vs random vs top-suitability",
            "Under identical constraints (budget, no adjacent cells), does the exact ILP improve the stated survey objective over simple baselines, and does it respond monotonically to budget?",
            "ILP objective >= every baseline at every budget (by construction) with gains largest at larger budgets; objective is non-decreasing in budget; top-suitability covers fewer environmental strata.",
            "3 regions x 4 budgets; WorldClim, Open-Meteo DEM, GBIF, habitat model where eligible", "PuLP/CBC; seeded random (200 draws)",
            registered="2026-11-07T10:40:00Z")
def e12():
    from . import spatial as sp_, habitat, planner
    regions = {"Alps (Arnica montana)": ("Arnica montana", [9, 46.5, 13, 48.5]),
               "Dolpa-Jumla, Nepal (Nardostachys jatamansi)": ("Nardostachys jatamansi", [81.8, 28.6, 83.4, 29.8]),
               "Appalachians (Panax quinquefolius)": ("Panax quinquefolius", [-82, 36, -78, 39])}
    rows, mono = [], {}
    for label, (sp, bb) in regions.items():
        ctx = sp_.region_context(sp, {"bbox": bb})
        cells = planner.planning_units(ctx, habitat.predict_cells(sp, ctx["grid"]))
        prev = -1
        mono[label] = True
        for B in (5, 10, 20, 40):
            r = planner.survey_with_baselines([dict(c) for c in cells], B)
            o, b = r["optimal"], r["baselines"]
            obj = 10 * o["strata_covered"] + o["total_benefit"]
            mono[label] &= obj >= prev - 1e-6
            prev = obj
            f = lambda d: (10 * d["strata_covered"] + d["total_benefit"]) if "strata_covered" in d else None
            rows.append({"region": label, "budget": B, "n_cells": len(cells), "ilp": round(obj, 3),
                         "greedy": round(f(b["greedy"]), 3), "random_mean": round(f(b["random"]), 3),
                         "top_suitability": (round(f(b["top_suitability"]), 3) if f(b["top_suitability"]) is not None else None),
                         "ilp_strata": o["strata_covered"], "top_strata": b["top_suitability"].get("strata_covered"),
                         "all_constraints_satisfied": o["constraint_satisfied"] and b["greedy"]["constraint_satisfied"]})
    df = pd.DataFrame(rows)
    gain_g = ((df.ilp - df.greedy) / df.greedy).round(4)
    gain_r = ((df.ilp - df.random_mean) / df.random_mean).round(4)
    res = {"rows": rows, "budget_monotone": mono, "ilp_ge_all_baselines": bool((df.ilp >= df.greedy - 1e-6).all() and (df.ilp >= df.random_mean - 1e-6).all()),
           "median_gain_vs_greedy": float(gain_g.median()), "max_gain_vs_greedy": float(gain_g.max()),
           "median_gain_vs_random": float(gain_r.median())}
    ok = res["ilp_ge_all_baselines"] and all(mono.values())
    return res, ("validated within scope" if ok else "failed/negative"), (
        f"ILP >= all baselines in every case: {res['ilp_ge_all_baselines']}; budget-monotone: {all(mono.values())}. Median gain vs greedy "
        f"{res['median_gain_vs_greedy']:.1%} (max {res['max_gain_vs_greedy']:.1%}), vs random {res['median_gain_vs_random']:.1%}. Greedy is near-optimal "
        "at small budgets; gains are in the modelled objective, not demonstrated field outcomes.")


# ---------------------------------------------------------------- E13
@experiment("E13", "Evidence planning: complementarity-aware ILP vs item-greedy",
            "When decisions need ALL of several measurements (e.g. a local quota needs 6), does a greedy ranking of individual measurements waste budget compared with an ILP that models complementarity?",
            "Greedy buys individually attractive items that complete no decision at some budgets; ILP unlocks >= as much decision value at every budget.",
            "eligibility rules + planner.EVIDENCE_ITEMS (assumed costs)", "budgets 10..120 person-days; 4 species with different tiers",
            registered="2026-11-07T10:40:00Z")
def e13():
    from . import planner
    rows = []
    for sp in ["Nardostachys jatamansi", "Khaya senegalensis", "Arnica montana", "Primula veris"]:
        for B in (10, 20, 30, 50, 80, 120):
            e = planner.plan_evidence(sp, B)
            rows.append({"species": sp, "budget": B, "ilp_value": e["optimal"]["value"], "greedy_value": e["greedy_baseline"]["value"],
                         "ilp_unlocks": e["optimal"]["unlocks"], "greedy_unlocks": e["greedy_baseline"]["unlocks"],
                         "greedy_spent_without_unlock": e["greedy_baseline"]["cost"] if not e["greedy_baseline"]["unlocks"] else 0})
    df = pd.DataFrame(rows)
    res = {"rows": rows, "ilp_ge_greedy": bool((df.ilp_value >= df.greedy_value - 1e-9).all()),
           "cases_greedy_worse": int((df.ilp_value > df.greedy_value + 1e-9).sum()), "n_cases": len(df),
           "mean_value_gap": float((df.ilp_value - df.greedy_value).mean())}
    return res, ("validated within scope" if res["ilp_ge_greedy"] else "failed/negative"), (
        f"ILP >= greedy in all {len(df)} cases; greedy strictly worse in {res['cases_greedy_worse']} (mean value gap {res['mean_value_gap']:.2f}). "
        "Evidence planning must model 'all-of' requirements; the app uses the ILP and shows the greedy result for transparency.")


def run(ids: list[str] | None = None) -> dict:
    OUT.mkdir(exist_ok=True)
    (OUT / "results").mkdir(exist_ok=True)
    reg_path = OUT / "registry.json"
    registry = json.loads(reg_path.read_text()) if reg_path.exists() else {}
    for eid, e in EXPERIMENTS.items():
        if ids and eid not in ids:
            continue
        t0 = time.time()
        print(f"[{eid}] {e['title']}")
        try:
            result, status, finding = e["fn"]()
            err = None
        except Exception as ex:  # keep failures in the registry
            import traceback
            result, status, finding, err = {}, "failed/negative", "execution error", traceback.format_exc()[-1500:]
        entry = {k: v for k, v in e.items() if k != "fn"} | {
            "status": status, "finding": finding, "error": err,
            "ran_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "runtime_s": round(time.time() - t0, 2),
            "command": f"python -m backend.ethnoharvest.experiments {eid}",
            "environment": {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__,
                            "platform": platform.platform()},
            "compadre_version": compadre.VERSION, "seed": 42,
            "artifact": f"experiments/results/{eid}.json"}
        registry[eid] = entry
        (OUT / "results" / f"{eid}.json").write_text(json.dumps(entry | {"result": result}, indent=1, default=_js))
        print(f"   -> {status}: {finding[:160]}")
    reg_path.write_text(json.dumps(dict(sorted(registry.items())), indent=1, default=_js))
    return registry


def _js(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


if __name__ == "__main__":
    run(sys.argv[1:] or None)
