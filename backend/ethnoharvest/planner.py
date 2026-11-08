"""Constrained research/conservation planning (PuLP + CBC) with transparent baselines.

Costs are ASSUMED planning units unless the user supplies verified costs. An exact
optimum is the best plan under the stated objective, not proof of field impact.
"""
from __future__ import annotations

import json
import math
from datetime import date

import numpy as np
import pulp

from . import eligibility as el

SOLVER_VERSION = f"PuLP {pulp.__version__} / CBC"


# ------------------------------------------------------------------ planning units
def planning_units(context: dict, suitability: dict | None, cost_params: dict | None = None) -> list[dict]:
    cp = {"base": 1.0, "per_km_elev_above_1500": 0.6, **(cost_params or {})}
    cells = [dict(c) for c in context["grid"] if c.get("bio1") is not None]
    occ = context["layers"].get("occurrences", {})
    recs = occ.get("records", []) if occ.get("status") == "available" else []
    pred = {p["id"]: p for p in (suitability or {}).get("predictions", [])} if suitability and suitability.get("status") == "available" else {}
    this_year = date.today().year
    for c in cells:
        w, s, e, n = c["bounds"]
        inside = [r for r in recs if w <= r["lon"] < e and s <= r["lat"] < n]
        c["n_records"] = len(inside)
        c["last_record_year"] = max([r["year"] for r in inside if r["year"]], default=None)
        c["years_since_record"] = (this_year - c["last_record_year"]) if c["last_record_year"] else None
        p = pred.get(c["id"], {})
        c["suitability"] = p.get("suitability")
        c["extrapolation"] = p.get("extrapolation")
        elev = c.get("elevation_m") or 0
        c["cost"] = round(cp["base"] + cp["per_km_elev_above_1500"] * max(0.0, elev - 1500) / 1000, 3)
        c["cost_basis"] = "assumed: base + elevation access penalty (not observed logistics)"
    return cells


def _env_matrix(cells):
    X = np.array([[c["bio1"], c["bio12"], c["bio15"] or 0, c.get("elevation_m") or 0] for c in cells], float)
    sd = X.std(0)
    sd[sd == 0] = 1
    return (X - X.mean(0)) / sd


def _kmeans(X, k, seed=0, iters=50):
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((X[:, None] - C[None]) ** 2).sum(-1), 1)
        newC = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
        if np.allclose(newC, C):
            break
        C = newC
    return lab


def survey_benefit(c) -> tuple[float, list[str]]:
    reasons = []
    b = 0.0
    if c["n_records"] == 0:
        b += 1.0; reasons.append("no GBIF record in cell (survey gap)")
    else:
        b += 0.3; reasons.append(f"{c['n_records']} existing record(s)")
    if c.get("suitability") is not None:
        u = 4 * c["suitability"] * (1 - c["suitability"])
        b += 0.8 * u + 0.4 * c["suitability"]
        reasons.append(f"model suitability {c['suitability']:.2f} (uncertainty term {u:.2f})")
        if c.get("extrapolation"):
            reasons.append("outside training envelope (extrapolation)")
    else:
        b += 0.5; reasons.append("no validated habitat model: neutral prior")
    return round(b, 4), reasons


# ------------------------------------------------------------------ intent 1: survey
def plan_survey(cells: list[dict], budget: float, k_strata: int | None = None, seed: int = 0,
                spread: bool = True) -> dict:
    if not cells:
        return {"status": "infeasible", "reason": "no planning units with climate data"}
    X = _env_matrix(cells)
    k = k_strata or max(2, min(8, len(cells) // 4))
    strata = _kmeans(X, k, seed)
    for c, s in zip(cells, strata):
        c["stratum"] = int(s)
        c["benefit"], c["reasons"] = survey_benefit(c)
    W = 10.0  # strata coverage dominates point benefit
    prob = pulp.LpProblem("survey", pulp.LpMaximize)
    x = {c["id"]: pulp.LpVariable(f"x_{c['id']}", cat="Binary") for c in cells}
    z = {s: pulp.LpVariable(f"z_{s}", cat="Binary") for s in range(k)}
    prob += W * pulp.lpSum(z.values()) + pulp.lpSum(c["benefit"] * x[c["id"]] for c in cells)
    prob += pulp.lpSum(c["cost"] * x[c["id"]] for c in cells) <= budget
    for s in range(k):
        prob += z[s] <= pulp.lpSum(x[c["id"]] for c in cells if c["stratum"] == s)
    if spread:  # no two selected cells share an edge -> spatial spread
        size = cells[0]["bounds"][2] - cells[0]["bounds"][0]
        pos = {c["id"]: (round(c["center"][0] / size), round(c["center"][1] / size)) for c in cells}
        inv = {v: k_ for k_, v in pos.items()}
        for cid, (i, j) in pos.items():
            for di, dj in ((1, 0), (0, 1)):
                nb = inv.get((i + di, j + dj))
                if nb:
                    prob += x[cid] + x[nb] <= 1
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=20))
    sel = [c["id"] for c in cells if (x[c["id"]].value() or 0) > 0.5]
    return _score(cells, sel, X, budget) | {"method": "ILP (CBC)", "status": pulp.LpStatus[prob.status],
                                             "k_strata": k, "objective": pulp.value(prob.objective)}


def _score(cells, sel, X, budget):
    idx = {c["id"]: i for i, c in enumerate(cells)}
    chosen = [cells[idx[s]] for s in sel]
    cov = len({c["stratum"] for c in chosen})
    k = len({c["stratum"] for c in cells})
    if sel:
        S = X[[idx[s] for s in sel]]
        d = np.sqrt(((X[:, None] - S[None]) ** 2).sum(-1)).min(1)
        env_cov = float(d.mean())
    else:
        env_cov = float("nan")
    return {"selected": sel, "n_selected": len(sel), "strata_covered": cov, "strata_total": k,
            "total_benefit": round(sum(c["benefit"] for c in chosen), 3),
            "cost_used": round(sum(c["cost"] for c in chosen), 3), "budget": budget,
            "mean_env_distance_to_nearest_selected": round(env_cov, 4),
            "constraint_satisfied": sum(c["cost"] for c in chosen) <= budget + 1e-9}


def _neighbours(cells):
    size = cells[0]["bounds"][2] - cells[0]["bounds"][0]
    pos = {c["id"]: (round(c["center"][0] / size), round(c["center"][1] / size)) for c in cells}
    inv = {v: k for k, v in pos.items()}
    return {cid: {inv[(i + di, j + dj)] for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)) if (i + di, j + dj) in inv}
            for cid, (i, j) in pos.items()}


def baseline_greedy(cells, budget, X):
    """Same feasibility rules as the ILP (budget + no adjacent cells)."""
    nb = _neighbours(cells)
    chosen, covered, spent, blocked = [], set(), 0.0, set()
    rem = list(cells)
    while True:
        best, bv = None, -1
        for c in rem:
            if spent + c["cost"] > budget or c["id"] in blocked:
                continue
            v = (c["benefit"] + (10.0 if c["stratum"] not in covered else 0)) / c["cost"]
            if v > bv:
                best, bv = c, v
        if not best:
            break
        chosen.append(best["id"]); covered.add(best["stratum"]); spent += best["cost"]; rem.remove(best)
        blocked |= nb[best["id"]]
    return _score(cells, chosen, X, budget) | {"method": "greedy (benefit+new-stratum bonus per cost)"}


def baseline_random(cells, budget, X, draws=200, seed=0):
    rng = np.random.default_rng(seed)
    nb = _neighbours(cells)
    res = []
    for _ in range(draws):
        order = rng.permutation(len(cells))
        sel, spent, blocked = [], 0.0, set()
        for i in order:
            if spent + cells[i]["cost"] <= budget and cells[i]["id"] not in blocked:
                sel.append(cells[i]["id"]); spent += cells[i]["cost"]; blocked |= nb[cells[i]["id"]]
        res.append(_score(cells, sel, X, budget))
    return {"method": f"random (mean of {draws} seeded draws)",
            "strata_covered": float(np.mean([r["strata_covered"] for r in res])),
            "strata_total": res[0]["strata_total"],
            "total_benefit": float(np.mean([r["total_benefit"] for r in res])),
            "mean_env_distance_to_nearest_selected": float(np.nanmean([r["mean_env_distance_to_nearest_selected"] for r in res])),
            "n_selected": float(np.mean([r["n_selected"] for r in res])), "budget": budget, "constraint_satisfied": True}


def baseline_top_suitability(cells, budget, X):
    if all(c.get("suitability") is None for c in cells):
        return {"method": "top-suitability", "status": "unavailable", "reason": "no validated habitat model"}
    nb = _neighbours(cells)
    sel, spent, blocked = [], 0.0, set()
    for c in sorted(cells, key=lambda c: -(c.get("suitability") or 0)):
        if spent + c["cost"] <= budget and c["id"] not in blocked:
            sel.append(c["id"]); spent += c["cost"]; blocked |= nb[c["id"]]
    return _score(cells, sel, X, budget) | {"method": "top-suitability (highest predicted suitability first)"}


def survey_with_baselines(cells, budget, seed=0):
    opt = plan_survey(cells, budget, seed=seed)
    X = _env_matrix(cells)
    return {"optimal": opt, "baselines": {"greedy": baseline_greedy(cells, budget, X),
                                          "random": baseline_random(cells, budget, X, seed=seed),
                                          "top_suitability": baseline_top_suitability(cells, budget, X)},
            "cells": cells, "solver": SOLVER_VERSION, "seed": seed,
            "objective_definition": "maximise 10 x (environmental strata covered) + sum(cell survey benefit); budget on assumed cost units; no adjacent cells",
            "caveat": "Expected research utility under stated assumptions; not a guaranteed field outcome."}


# ------------------------------------------------------------------ intent 2: re-verify known populations
def plan_reverification(cells, budget, stale_years: int = 15):
    cand = [c for c in cells if c["n_records"] > 0]
    if not cand:
        return {"status": "infeasible", "reason": "no known occurrence cells in region (absence of records is not absence)"}
    for c in cand:
        age = c["years_since_record"] if c["years_since_record"] is not None else 50
        c["reverify_value"] = round(min(age, 60) / stale_years, 3)
        c["reverify_reason"] = f"last record {c['last_record_year'] or 'undated'}; {c['n_records']} record(s)"
    prob = pulp.LpProblem("reverify", pulp.LpMaximize)
    x = {c["id"]: pulp.LpVariable(f"x_{c['id']}", cat="Binary") for c in cand}
    prob += pulp.lpSum(c["reverify_value"] * x[c["id"]] for c in cand)
    prob += pulp.lpSum(c["cost"] * x[c["id"]] for c in cand) <= budget
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=10))
    sel = [c["id"] for c in cand if (x[c["id"]].value() or 0) > 0.5]
    return {"method": "ILP knapsack", "status": pulp.LpStatus[prob.status], "selected": sel,
            "candidates": [{k: c[k] for k in ("id", "center", "n_records", "last_record_year", "reverify_value", "cost", "reverify_reason")} for c in cand],
            "objective_definition": f"maximise staleness value (years since last record / {stale_years}) within budget",
            "caveat": "Screens which known populations most need re-verification. Records are presence-only; stale records are not evidence of decline."}


# ------------------------------------------------------------------ intent 3: evidence to collect next
# Base costs are assumed person-days for a short-lived herb; multi-year items are scaled up for long-lived plants.
EVIDENCE_ITEMS = {
    "matched_harvest_experiment": {"label": "Matched harvest experiment (harvested vs control plots, >=2 censuses)", "cost": 40, "multi_year": True},
    "local_stage_counts": {"label": "Local stage-structured population census (permanent plots)", "cost": 12, "multi_year": True},
    "post_harvest_recovery": {"label": "Post-harvest recovery monitoring with unharvested controls", "cost": 20, "multi_year": True},
    "harvest_yield": {"label": "Organ yield measurements per plant/area", "cost": 6},
    "identity_verified": {"label": "Voucher-verified species identity", "cost": 2},
    "site_rights": {"label": "Collection rights, permits and community consent (FPIC)", "cost": 4},
    "expert_threshold": {"label": "Expert-agreed sustainability threshold & monitoring interval", "cost": 3},
    "occurrence_records_check": {"label": "Download and clean existing GBIF occurrence records", "cost": 1},
    "occurrence_survey": {"label": "Georeferenced occurrence survey (>=100 wild records)", "cost": 10},
    "phenology_monitoring": {"label": "Flowering phenology monitoring across >=3 sites/years", "cost": 8},
    "targeted_vital_rate": {"label": "Measure the life process this harvest hits", "cost": 10, "multi_year": True},
    "regeneration_survey": {"label": "Seedling and sapling counts around harvested plants", "cost": 5},
    "trade_volume_records": {"label": "Trade and collection volume records (traders, CITES database)", "cost": 3},
}

DECISIONS = {
    "local_quota": {"requires": ["local_stage_counts", "harvest_yield", "post_harvest_recovery", "identity_verified", "site_rights", "expert_threshold"],
                    "label": "Conditional local harvest-quota assessment"},
    "harvest_comparison": {"requires": ["matched_harvest_experiment"], "label": "Study-backed harvest comparison (Tier A)"},
    "rotation_extrapolation": {"requires": ["matched_harvest_experiment", "post_harvest_recovery"], "label": "Rotation / rest-interval analysis"},
    "habitat_model": {"requires": ["occurrence_survey"], "label": "Validated habitat-suitability model"},
    "phenology_window": {"requires": ["phenology_monitoring"], "label": "Flowering monitoring window"},
    "process_sensitivity": {"requires": ["targeted_vital_rate"], "label": "Local check of the life process the harvest hits"},
    "regeneration_status": {"requires": ["regeneration_survey"], "label": "Is the population replacing harvested plants?"},
    "trade_pressure": {"requires": ["trade_volume_records"], "label": "How much is taken and traded"},
    "identity_assurance": {"requires": ["identity_verified"], "label": "Material is the right species"},
}

# Harvested part for case species that have no audited harvest study.
CURATED_ORGAN = {"Arnica montana": "flower", "Primula veris": "flower", "Echinacea purpurea": "root"}
CURATED_GROWTH = {"Arnica montana": "Herbaceous perennial"}  # not in the COMPADRE crosswalk
# Look-alikes documented in the case notes, in addition to the document synonym table.
LOOKALIKES = {"Nardostachys jatamansi": ["Valeriana jatamansi"], "Arnica montana": ["Arnica chamissonis"],
              "Panax quinquefolius": ["Panax ginseng"], "Primula veris": ["Primula elatior"]}
# How lethal harvesting each part usually is to the individual (a descriptive weight, not a measured rate).
ORGAN_PRESSURE = {"root": 1.0, "whole": 1.0, "bark": 0.8, "resin": 0.5, "leaf": 0.4, "flower": 0.3, "fruit": 0.3}
TARGET_LABEL = {
    "root": "Survival and regrowth of plants after digging (marked plants, 2 seasons)",
    "whole": "Survival and resprouting of plants after cutting or uprooting",
    "bark": "Survival and bark regrowth of stripped trees (marked trees)",
    "resin": "Flowering, fruit and seed set on tapped vs untapped trees",
    "leaf": "Leaf regrowth and survival after leaf cutting",
    "flower": "Seed set and seedling recruitment where flowers are picked",
    "fruit": "Seedling recruitment where fruit is collected",
}
MIN_RELEVANCE = 0.5  # decision weights below this are reported but not planned for
# Long-lived plants take more years (so more person-days) to show a demographic response.
LIFESPAN_FACTOR = {"Tree": 1.8, "Palm": 1.6, "Shrub": 1.3, "Liana": 1.3, "Succulent": 1.2}


def decision_uncertainty(species: str) -> dict:
    """How uncertain is the 'is harvest at h sustainable (lambda>=1)?' decision under Tier-B model variants?"""
    from . import compadre, demography as dm
    pres = el.preset_matrices(species)
    pres = pres[pres.qc_split_available]
    if pres.empty:
        return {"status": "no matrix", "flip_probability": 1.0}
    M = compadre.matrices(int(pres.MatrixID.iloc[0]))
    n = M["A"].shape[0]
    variants = {"lethal_all_post_first": list(range(1, n)), "lethal_largest": [n - 1]}
    flips = []
    rows = []
    for h in (0.1, 0.25, 0.5):
        lams = {k: dm.eig_analysis(dm.hypothetical_removal(M["U"], M["F"], M["C"], st, h))["lambda"] for k, st in variants.items()}
        verdicts = {v >= 1 for v in lams.values()}
        flips.append(len(verdicts) > 1)
        rows.append({"intensity": h, "lambda_by_variant": {k: round(v, 4) for k, v in lams.items()}, "models_disagree": len(verdicts) > 1})
    return {"status": "ok", "matrix_id": int(pres.MatrixID.iloc[0]), "rows": rows, "flip_probability": float(np.mean(flips))}


def _cites_cached(species: str) -> dict | None:
    """CITES status from the local Species+ cache only; the planner never calls the network."""
    from . import spatial
    f = spatial.CACHE / "speciesplus" / f"{spatial._key(species)}.json"
    try:
        return json.loads(f.read_text(encoding="utf8")) if f.exists() else None
    except (OSError, ValueError):
        return None


def species_context(species: str, organ: str | None = None, occurrence_count: int | None = None) -> dict:
    """Facts about this species that change which measurements are worth most. All from local data."""
    from . import harvest as hv, methods
    from .ops.documents import SYNONYMS
    cw = el.crosswalk()
    row = cw[cw.SpeciesAccepted == species]
    growth = str(row.organism_type.iloc[0]) if len(row) else CURATED_GROWTH.get(species)
    studies = [s for s in hv.STUDIES if s["species"] == species]
    organ = organ or (studies[0]["organ"] if studies else CURATED_ORGAN.get(species))
    oid = methods.organ_id(organ)
    sens = None
    if organ:
        try:
            from .evidence_agent import matrix_sensitivity
            s = matrix_sensitivity(species, organ)
            if s.get("status") == "ok":
                sens = {"share": s["share_mean"], "process": s["process"], "basis": s["basis"], "matrices": s["matrices"]}
        except Exception:  # noqa: BLE001 - sensitivity is optional context
            sens = None
    cites = _cites_cached(species) or {}
    look = sorted({k.capitalize() for k, v in SYNONYMS.items() if v == species} | set(LOOKALIKES.get(species, [])))
    return {"species": species, "growth_form": growth, "organ": organ, "organ_id": oid,
            "pressure": ORGAN_PRESSURE.get(oid, 0.5), "lifespan_factor": LIFESPAN_FACTOR.get(growth or "", 1.0),
            "medicinal": bool(len(row) and row.medicinal_documented.iloc[0]),
            "n_matrices": int(len(el.preset_matrices(species))) if len(row) else 0,
            "study_designs": sorted({s["design"] for s in studies}), "studies": [s["id"] for s in studies],
            "sensitivity": sens, "cites_listed": cites.get("listed"), "cites_appendices": cites.get("appendices"),
            "lookalikes": look, "phenobs": species in el.phenobs_species(), "occurrence_count": occurrence_count}


def _values(ctx: dict, elig: dict, du: dict) -> tuple[dict, dict]:
    """Decision weights for this species, each with the reason it has that weight."""
    p, oid, sens, flip = ctx["pressure"], ctx["organ_id"], ctx["sensitivity"], du.get("flip_probability", 1.0)
    traded = bool(ctx["cites_listed"]) or ctx["medicinal"]
    part = oid or "unknown part"
    v, why = {}, {}
    v["harvest_comparison"] = 1.0 + 2.0 * flip * p
    why["harvest_comparison"] = f"no harvest study yet; generic models disagree in {flip:.0%} of tested intensities ({part} harvest)"
    v["local_quota"] = 3.0 * (1 + 0.5 * p) if traded else 2.0
    why["local_quota"] = (f"traded plant, {part} harvest: a site-level answer is the most requested one" if traded
                          else "no documented trade")
    v["rotation_extrapolation"] = 1.5 * ctx["lifespan_factor"]
    why["rotation_extrapolation"] = f"rest intervals matter more the longer a {(ctx['growth_form'] or 'plant').lower()} lives"
    occ = ctx["occurrence_count"]
    v["habitat_model"] = 0.6 if occ is None else (1.2 if occ < 100 else 0.4)
    why["habitat_model"] = ("records not checked yet: download existing ones before any field survey" if occ is None
                            else f"{occ} cleaned records")
    flowering = oid in ("flower", "fruit", "resin")
    v["phenology_window"] = 1.6 if flowering else 0.3
    why["phenology_window"] = (f"{part} harvest depends on when the plant flowers and fruits" if flowering
                               else f"{part} harvest does not depend on flowering time")
    if sens:
        v["process_sensitivity"] = 1.0 + 4.0 * sens["share"]
        why["process_sensitivity"] = f"{sens['share']:.0%} of population growth depends on {sens['process']}, which {part} harvest hits"
    else:
        v["process_sensitivity"] = 1.0 if oid else 0.0
        why["process_sensitivity"] = "no matrix sensitivity for this part; neutral weight" if oid else "harvested part unknown"
    regen = oid in ("bark", "fruit", "resin") or ctx["growth_form"] in ("Tree", "Palm", "Shrub")
    v["regeneration_status"] = 2.0 if regen else 0.8
    why["regeneration_status"] = ("long-lived or seed-limited: recruitment decides whether harvested plants are replaced" if regen
                                  else "short-lived herb: recruitment shows up in a stage census")
    v["trade_pressure"] = 1.8 if ctx["cites_listed"] else (0.6 + 0.6 * p if ctx["medicinal"] else 0.3)
    why["trade_pressure"] = (f"CITES Appendix {', '.join(ctx['cites_appendices'] or ['?'])}: trade volume is recorded and decision-relevant"
                             if ctx["cites_listed"] else "documented medicinal use" if ctx["medicinal"] else "no documented trade")
    v["identity_assurance"] = 1.5 if ctx["lookalikes"] else 0.2
    why["identity_assurance"] = (f"confused with or traded as {', '.join(ctx['lookalikes'])}" if ctx["lookalikes"]
                                 else "no known look-alike in our tables")
    for d in DECISIONS:
        if elig.get(d, {}).get("status") in ("enabled", "enabled-with-caveats"):  # already unlocked: worth nothing extra
            v[d], why[d] = 0.0, "already possible with the evidence in the app"
        elif v[d] < MIN_RELEVANCE:  # spend no budget on decisions that barely matter for this species
            v[d], why[d] = 0.0, f"low priority for this species: {why[d]}"
    # An observational or modelled harvest study shows association, not cause: an experiment still adds something.
    if v["harvest_comparison"] == 0 and ctx["study_designs"] and "experimental" not in ctx["study_designs"]:
        v["harvest_comparison"] = round(0.8 + p, 3)
        why["harvest_comparison"] = (f"existing study is {'/'.join(ctx['study_designs'])}: a matched experiment would show cause, "
                                     "not only association")
    return {d: round(x, 3) for d, x in v.items()}, why


def _items(ctx: dict, have: dict) -> dict:
    out = {}
    for k, it in EVIDENCE_ITEMS.items():
        if have.get(k):
            continue
        it = dict(it)
        if it.pop("multi_year", False):
            it["cost"] = round(it["cost"] * ctx["lifespan_factor"])
        if k == "targeted_vital_rate" and ctx["organ_id"] in TARGET_LABEL:
            it["label"] = TARGET_LABEL[ctx["organ_id"]]
        out[k] = it
    return out


def plan_evidence(species: str, budget: float, have: dict | None = None, occurrence_count: int | None = None,
                  organ: str | None = None) -> dict:
    have = dict(have or {})
    ctx = species_context(species, organ, occurrence_count)
    elig = el.assess(species, local_evidence=have, occurrence_count=occurrence_count)["tasks"]
    du = decision_uncertainty(species)
    value, why = _values(ctx, elig, du)
    items = _items(ctx, have)
    reqs = {d: list(DECISIONS[d]["requires"]) for d in DECISIONS}
    if occurrence_count is None:  # check the records that already exist first: it is nearly free
        reqs["habitat_model"] = ["occurrence_records_check"]
    else:
        items.pop("occurrence_records_check", None)
    prob = pulp.LpProblem("evidence", pulp.LpMaximize)
    x = {k: pulp.LpVariable(f"x_{k}", cat="Binary") for k in items}
    u = {d: pulp.LpVariable(f"u_{d}", cat="Binary") for d in DECISIONS if value[d] > 0}
    prob += pulp.lpSum(value[d] * u[d] for d in u) - 0.001 * pulp.lpSum(items[k]["cost"] * x[k] for k in items)
    prob += pulp.lpSum(items[k]["cost"] * x[k] for k in items) <= budget
    for d in u:
        for req in reqs[d]:
            if req in x:
                prob += u[d] <= x[req]
            elif not have.get(req):
                prob += u[d] == 0
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=10))
    sel = [k for k in items if (x[k].value() or 0) > 0.5]
    unlocked = [d for d in u if (u[d].value() or 0) > 0.5]
    # greedy baseline: pick items by (sum of values of decisions they appear in)/cost, ignoring complementarity
    score = {k: sum(value[d] for d in u if k in reqs[d]) / items[k]["cost"] for k in items}
    g, spent = [], 0.0
    for k in sorted(items, key=lambda k: -score[k]):
        if score[k] > 0 and spent + items[k]["cost"] <= budget:
            g.append(k); spent += items[k]["cost"]
    g_unlocked = [d for d in u if all((r in g) or have.get(r) for r in reqs[d])]
    item_why = {k: [why[d] for d in u if k in reqs[d]] for k in items}
    return {"species": species, "budget": budget, "budget_unit": "assumed person-days", "context": ctx,
            "decision_values": value, "decision_uncertainty": du,
            "optimal": {"items": sel, "unlocks": unlocked, "value": round(sum(value[d] for d in unlocked), 3),
                        "cost": sum(items[k]["cost"] for k in sel)},
            "greedy_baseline": {"items": g, "unlocks": g_unlocked, "value": round(sum(value[d] for d in g_unlocked), 3),
                                "cost": spent},
            "items": [{"id": k, **items[k], "selected": k in sel, "why": item_why[k],
                       "unlocks_if_complete": [d for d in DECISIONS if k in reqs[d]]} for k in items],
            "decisions": {d: {**DECISIONS[d], "requires": reqs[d], "value": value[d], "why": why[d], "unlocked": d in unlocked,
                              "currently": elig.get(d, {}).get("status", "not assessed")} for d in DECISIONS},
            "solver": SOLVER_VERSION,
            "caveat": ("Costs are assumed person-days, scaled up for long-lived plants. Decision weights are explicit modelling choices "
                       "built from this species' harvested part, life form, matrix sensitivity, trade status and look-alikes. "
                       "They rank what to measure next; they do not say whether harvest is safe.")}
