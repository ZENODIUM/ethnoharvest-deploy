"""Simulation service for the Simulate page. Deterministic; animation seeds never touch values."""
from __future__ import annotations

import numpy as np

from . import compadre, demography as dm, eligibility as el, harvest as hv

E05_BACKTEST = {"mae": 0.068, "worst_bias": -0.226, "experiment": "E05"}


def _n0(A, n0, scale=100.0):
    if n0 is not None and len(n0) == A.shape[0] and sum(n0) > 0:
        return np.asarray(n0, float), "user-declared starting vector (hypothetical unless from a census)"
    w = dm.eig_analysis(A)["stable_stage"]
    return w * scale, "stable stage distribution × 100 (hypothetical; normalised index, not a local stock)"


def _traj(mats, n0, horizon):
    out = [np.asarray(n0, float)]
    for t in range(horizon):
        out.append(np.asarray(mats[t % len(mats)], float) @ out[-1])
    T = np.array(out)
    return {"stages": T.round(4).tolist(), "total": T.sum(1).round(4).tolist(),
            "index": (T.sum(1) / T[0].sum()).round(5).tolist(),
            "proportions": (T / np.maximum(T.sum(1, keepdims=True), 1e-12)).round(4).tolist()}


def synthetic(stage_names: list[str], survival: list[float], growth: list[float], fecundity: float,
              horizon: int = 30, n0=None) -> dict:
    """Educational sandbox for plants with no published matrix. The user supplies every rate; nothing is
    borrowed from COMPADRE or from another species. Output is always labelled synthetic."""
    k = len(stage_names)
    if not 2 <= k <= 5 or len(survival) != k or len(growth) != k - 1:
        raise ValueError("need 2-5 stages, one survival rate per stage and one growth rate per transition")
    if not all(0 <= x <= 1 for x in survival + growth) or not 0 <= fecundity <= 1000:
        raise ValueError("survival and growth must be probabilities in [0, 1]; fecundity in [0, 1000]")
    U = np.zeros((k, k))
    for i in range(k):
        g = growth[i] if i < k - 1 else 0.0
        U[i, i] = survival[i] * (1 - g)
        if i < k - 1:
            U[i + 1, i] = survival[i] * g
    F = np.zeros((k, k))
    F[0, k - 1] = fecundity
    A = U + F
    v0, basis = _n0(A, n0)
    ea = dm.eig_analysis(A)
    return {"mode": "synthetic", "tier": "synthetic", "synthetic": True, "stages": stage_names,
            "A": A.round(6).tolist(), "lambda": float(ea["lambda"]), "n0_basis": basis,
            "trajectory": _traj([A], v0, horizon), "horizon": horizon,
            "label": "SYNTHETIC / EDUCATIONAL: every rate was entered by the user. Not a published model, "
                     "not a prediction for any real population, and not a basis for harvest decisions."}


def projection(matrix_id: int, horizon: int = 30, n0=None) -> dict:
    card = hv.matrix_card(matrix_id)
    A = np.array(card["A"])
    v0, basis = _n0(A, n0)
    return {"mode": "projection", "tier": "published-model", "matrix": _slim(card), "n0_basis": basis,
            "trajectory": _traj([A], v0, horizon), "horizon": horizon,
            "assumptions": ["time-invariant matrix (no density dependence, no environmental stochasticity)",
                            "linear projection describes the studied population, not a local stock forecast",
                            "asymptotic lambda differs from short-term transient growth"]}


def study_comparison(study_id: str, horizon: int = 30, n0=None) -> dict:
    s = hv.BY_ID[study_id]
    comp = hv.compare(study_id)
    ctrl = compadre.matrices(s["control_ids"][0])["A"]
    v0, basis = _n0(ctrl, n0)
    series = []
    for mid in [*s["control_ids"], *s["treatment_ids"]]:
        card = hv.matrix_card(mid)
        A = np.array(card["A"])
        # Matrices with different stage classes (e.g. Garcinia felling, 9 stages vs 8) start from their own stable
        # structure at the same total, so totals stay comparable while stage-level values are not.
        start, own = (v0, False) if A.shape[0] == len(v0) else (_n0(A, None, scale=float(np.sum(v0)))[0], True)
        series.append({"matrix_id": mid, "role": "control" if mid in s["control_ids"] else "treatment",
                       "label": _label(s, mid, card), "lambda": card["lambda"], "own_stage_classes": own,
                       "qc_ok": card["validation"]["ok"], "trajectory": _traj([A], start, horizon),
                       "population": card["population"], "years": f"{card['start_year']}–{card['end_year']}"})
    return {"mode": "study", "tier": "A", "study": {k: v for k, v in s.items() if k != "intensity"},
            "design_caveat": {"experimental": "Randomised harvest treatment with same-population control.",
                              "observational": "Harvested vs unharvested populations differ in site/period too: contrast is not a causal effect estimate.",
                              "modelled": "Harvest treatments are the authors' model scenarios applied to field-measured matrices, not harvests observed in plots.",
                              }.get(s["design"], ""),
            "n0_basis": basis, "series": series, "comparison": {k: v for k, v in comp.items() if k != "study"},
            "horizon": horizon}


def rotation(study_id: str, treatment_id: int, rest_years: int, horizon: int = 40, n0=None) -> dict:
    s = hv.BY_ID[study_id]
    if s["design"] != "experimental":
        raise ValueError("rotation scenarios need an experimental harvest study with a same-population control")
    H = compadre.matrices(treatment_id)["A"]
    C = compadre.matrices(s["control_ids"][0])["A"]
    v0, basis = _n0(C, n0)
    cycle = [H] + [C] * (rest_years - 1)
    lam_cycle = dm.periodic_lambda(H, C, rest_years)
    min_rot = next((r for r in range(1, 101) if dm.periodic_lambda(H, C, r) >= 1.0), None)
    return {"mode": "rotation", "tier": "A-extrapolated", "study_id": study_id, "treatment_id": treatment_id,
            "intensity_pct": s.get("intensity", {}).get(treatment_id), "rest_years": rest_years,
            "annualised_lambda": lam_cycle, "min_rest_years_lambda_ge_1": min_rot,
            "trajectory": _traj(cycle, v0, horizon), "control_trajectory": _traj([C], v0, horizon),
            "single_harvest_recovery": dm.recovery_time(H, C, v0), "n0_basis": basis, "horizon": horizon,
            "assumptions": ["each harvest year reuses the study's 1999–2002 mean treatment matrix; rest years reuse the control mean",
                            "repeated-harvest response was NOT measured in the study (single harvest 1998)",
                            "E06: recovery times from these mean matrices are shorter than the paper's year-specific estimates (5/17/33 y)",
                            "not a permitted rotation, quota or management prescription"]}


def hypothetical(matrix_id: int, stages: list[int], fraction: float, horizon: int = 30, n0=None) -> dict:
    M = compadre.matrices(matrix_id)
    A0 = np.nan_to_num(M["A"])
    A1 = dm.hypothetical_removal(np.nan_to_num(M["U"]), np.nan_to_num(M["F"]), M["C"], stages, fraction)
    v0, basis = _n0(A0, n0)
    l0, l1 = dm.eig_analysis(A0)["lambda"], dm.eig_analysis(A1)["lambda"]
    card = hv.matrix_card(matrix_id)
    return {"mode": "hypothetical", "tier": "B", "matrix": _slim(card), "stages_removed": stages, "fraction": fraction,
            "lambda_baseline": l0, "lambda_scenario": l1, "trajectory_baseline": _traj([A0], v0, horizon),
            "trajectory_scenario": _traj([A1], v0, horizon), "n0_basis": basis, "horizon": horizon,
            "calibration_warning": (f"Back-test E05: generic removal models mis-predicted the Nardostachys experiment "
                                    f"(MAE {E05_BACKTEST['mae']} in lambda; lethal-removal bias {E05_BACKTEST['worst_bias']}). "
                                    "Treat this as a sensitivity illustration, not a harvest-response estimate."),
            "assumptions": ["harvest modelled as lethal removal of a fraction of plants in selected stages each year",
                            "real harvest often removes organs and causes stage regression rather than death",
                            "no evidence that this matrix's population matches any local site"]}


def quota_question(species: str, local_evidence: dict | None = None) -> dict:
    a = el.assess(species, task="local_quota", local_evidence=local_evidence or {})
    q = a["tasks"]["local_quota"]
    return {"species": species, "answer_status": a["quota_answer"], "status": q["status"],
            "message": {"cannot estimate safe local rate": "Not estimable from the available evidence.",
                        "study-backed scenario only": "Published study scenarios can be compared, but they do not give a safe rate for any local site.",
                        "conditional field assessment eligible": "All local evidence is declared: a conditional assessment may be prepared for expert review. It is not a permit."}[a["quota_answer"]],
            "missing": q["missing"], "reasons": q["reasons"], "tier": a["overall_tier"],
            "not_a_permit": "EthnoHarvest never issues harvest permits, legal permissions or quotas."}


def _label(s, mid, card):
    if "intensity" in s and mid in s["intensity"]:
        return f"{s['intensity'][mid]}% rhizome harvest" if s["intensity"][mid] else "0% (control subplots)"
    if mid in s.get("labels", {}):
        return s["labels"][mid]
    return f"{card['treatment']} · {card['population']}"[:80]


def _slim(card):
    return {k: card[k] for k in ("matrix_id", "species", "population", "treatment", "composite", "start_year", "end_year",
                                 "study_id", "stages", "A", "U", "F", "lambda", "lambda_power_check", "damping_ratio",
                                 "stable_stage", "reproductive_value", "elasticity", "validation", "lat", "lon", "country")
            } | {"elasticity_by_process": card.get("elasticity_by_process"), "life_table": card.get("life_table")}
