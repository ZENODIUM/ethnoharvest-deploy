"""Matrix population model engine (deterministic, numpy/scipy only).

Conventions follow Caswell (2001) Matrix Population Models and the COMPADRE
A = U + F + C decomposition. Column j = stage at time t, row i = stage at t+1.
Every function is pure and seeded where randomness is involved.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

TOL = 1e-9


@dataclass
class Validation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    irreducible: bool | None = None
    primitive: bool | None = None

    def as_dict(self):
        return self.__dict__.copy()


def validate(A: np.ndarray, U: np.ndarray | None = None, F: np.ndarray | None = None,
             C: np.ndarray | None = None) -> Validation:
    v = Validation(ok=True)
    A = np.asarray(A, float)
    if A.ndim != 2 or A.shape[0] != A.shape[1] or A.shape[0] == 0:
        return Validation(False, [f"matrix must be square and non-empty, got shape {A.shape}"])
    if not np.isfinite(A).all():
        v.errors.append("matrix A contains NA/inf entries")
    if (np.nan_to_num(A) < -TOL).any():
        v.errors.append("matrix A has negative entries")
    if np.nansum(A) == 0:
        v.errors.append("matrix A is all zeros")
    if U is not None:
        U = np.asarray(U, float)
        if U.shape != A.shape:
            v.errors.append("U has different dimension from A")
        elif np.isnan(U).any():
            v.warnings.append("U contains NA: survival/fecundity decomposition unavailable")
        else:
            cs = U.sum(axis=0)
            if (cs > 1 + 1e-6).any():
                v.errors.append(f"U column survival > 1 in stages {list(np.where(cs > 1 + 1e-6)[0])} (max {cs.max():.3f})")
            if F is not None and C is not None and not np.isnan(F).any() and not np.isnan(C).any():
                if not np.allclose(A, U + F + C, atol=1e-4):
                    v.warnings.append("A != U + F + C (rounding or inconsistent components)")
    if not v.errors:
        n = A.shape[0]
        M = (A > 0).astype(float)
        R = np.linalg.matrix_power(np.eye(n) + M, n - 1)
        v.irreducible = bool((R > 0).all())
        P = np.linalg.matrix_power(M, (n - 1) ** 2 + 1) if n > 1 else M
        v.primitive = bool((P > 0).all())
        if not v.irreducible:
            v.warnings.append("matrix is reducible (some stages cannot reach others); asymptotic results describe the dominant component only")
        elif not v.primitive:
            v.warnings.append("matrix is imprimitive (periodic); population may oscillate and not converge to stable structure")
    v.ok = not v.errors
    return v


def eig_analysis(A: np.ndarray) -> dict:
    """Dominant eigenvalue, right/left eigenvectors, damping ratio."""
    A = np.asarray(A, float)
    vals, W = np.linalg.eig(A)
    i = int(np.argmax(vals.real))
    lam = float(vals[i].real)
    w = np.abs(W[:, i].real)
    w = w / w.sum()
    valsT, V = np.linalg.eig(A.T)
    j = int(np.argmax(valsT.real))
    v = np.abs(V[:, j].real)
    v = v / v[np.argmax(w > 0)] if v[np.argmax(w > 0)] > 0 else v / v.max()
    mods = np.sort(np.abs(vals))[::-1]
    damping = float(mods[0] / mods[1]) if len(mods) > 1 and mods[1] > TOL else float("inf")
    return {"lambda": lam, "stable_stage": w, "reproductive_value": v, "damping_ratio": damping,
            "eigenvalues": vals}


def lambda_power(A: np.ndarray, iters: int = 20000, tol: float = 1e-13) -> float:
    """Independent check: power iteration (different algorithm from LAPACK eig)."""
    A = np.asarray(A, float)
    x = np.ones(A.shape[0]) / A.shape[0]
    lam = 0.0
    for _ in range(iters):
        y = A @ x
        s = y.sum()
        if s == 0:
            return 0.0
        new = s / x.sum()
        x = y / s
        if abs(new - lam) < tol:
            return float(new)
        lam = new
    return float(lam)


def sensitivity(A: np.ndarray) -> np.ndarray:
    e = eig_analysis(A)
    w, v = e["stable_stage"], e["reproductive_value"]
    return np.outer(v, w) / float(v @ w)


def elasticity(A: np.ndarray) -> np.ndarray:
    lam = eig_analysis(A)["lambda"]
    return sensitivity(A) * np.asarray(A, float) / lam


def elasticity_by_process(A, U, F, C=None) -> dict:
    """Sum elasticities into survival-stasis / progression / retrogression / fecundity / clonality.

    Entries of A are split proportionally to their U/F/C composition.
    """
    A = np.asarray(A, float)
    E = elasticity(A)
    U = np.nan_to_num(np.asarray(U, float))
    F = np.nan_to_num(np.asarray(F, float))
    C = np.zeros_like(A) if C is None else np.nan_to_num(np.asarray(C, float))
    with np.errstate(divide="ignore", invalid="ignore"):
        share = lambda X: np.where(A > 0, X / A, 0.0)
        EU, EF, EC = E * share(U), E * share(F), E * share(C)
    n = A.shape[0]
    tri = np.indices((n, n))
    return {
        "stasis": float(EU[tri[0] == tri[1]].sum()),
        "progression": float(EU[tri[0] > tri[1]].sum()),
        "retrogression": float(EU[tri[0] < tri[1]].sum()),
        "fecundity": float(EF.sum()),
        "clonality": float(EC.sum()),
    }


def project(A: np.ndarray, n0: np.ndarray, years: int) -> np.ndarray:
    """Deterministic projection n(t+1) = A n(t). Returns (years+1, stages)."""
    A = np.asarray(A, float)
    out = np.zeros((years + 1, A.shape[0]))
    out[0] = np.asarray(n0, float)
    for t in range(years):
        out[t + 1] = A @ out[t]
    return out


def project_sequence(mats: list[np.ndarray], n0: np.ndarray) -> np.ndarray:
    """Projection through an explicit sequence of annual matrices (e.g. harvest then recovery)."""
    out = [np.asarray(n0, float)]
    for M in mats:
        out.append(np.asarray(M, float) @ out[-1])
    return np.array(out)


def life_table_metrics(U: np.ndarray, F: np.ndarray) -> dict:
    """Net reproductive rate R0, generation time, life expectancy from the fundamental matrix."""
    U = np.asarray(U, float)
    F = np.asarray(F, float)
    n = U.shape[0]
    if np.isnan(U).any() or np.isnan(F).any():
        return {"R0": None, "generation_time": None, "life_expectancy": None, "note": "U/F not separable"}
    try:
        N = np.linalg.inv(np.eye(n) - U)
    except np.linalg.LinAlgError:
        return {"R0": None, "generation_time": None, "life_expectancy": None, "note": "I-U singular (immortal stage)"}
    R = F @ N
    R0 = float(np.max(np.abs(np.linalg.eigvals(R))))
    lam = eig_analysis(U + F)["lambda"]
    gt = float(np.log(R0) / np.log(lam)) if R0 > 0 and lam > 0 and abs(np.log(lam)) > 1e-9 else None
    first = int(np.argmax(F.sum(axis=0) > 0)) if F.sum() > 0 else 0
    # life expectancy from the first (newborn) stage that receives recruits
    rec = int(np.argmax(F.sum(axis=1) > 0)) if F.sum() > 0 else 0
    return {"R0": R0, "generation_time": gt, "life_expectancy": float(N[:, rec].sum()),
            "first_reproductive_stage": first}


def stochastic_lambda(mats: list[np.ndarray], probs: list[float] | None = None, years: int = 50000,
                      burn: int = 1000, seed: int = 42) -> dict:
    """Tuljapurkar's log stochastic growth rate by simulation with iid environments."""
    rng = np.random.default_rng(seed)
    k = len(mats)
    p = np.ones(k) / k if probs is None else np.asarray(probs) / np.sum(probs)
    n = np.ones(mats[0].shape[0]) / mats[0].shape[0]
    logs = []
    seq = rng.choice(k, size=years, p=p)
    for t, i in enumerate(seq):
        n = mats[i] @ n
        s = n.sum()
        if t >= burn:
            logs.append(np.log(s))
        n = n / s
    logs = np.array(logs)
    se = logs.std(ddof=1) / np.sqrt(len(logs))
    # Tuljapurkar small-noise approximation as a second, analytic estimate
    Abar = sum(pi * M for pi, M in zip(p, mats))
    S = sensitivity(Abar)
    lam1 = eig_analysis(Abar)["lambda"]
    var = sum(pi * float(np.sum(S * (M - Abar)) ** 2) for pi, M in zip(p, mats))
    approx = np.log(lam1) - var / (2 * lam1 ** 2)
    return {"log_lambda_s": float(logs.mean()), "lambda_s": float(np.exp(logs.mean())),
            "se_log": float(se), "tuljapurkar_approx_lambda_s": float(np.exp(approx)),
            "lambda_mean_matrix": lam1, "seed": seed, "years": years}


def ltre_fixed(A_treat: np.ndarray, A_ref: np.ndarray) -> dict:
    """Fixed-design LTRE (Caswell 2001 §10.1): contributions evaluated at midway matrix."""
    A_treat, A_ref = np.asarray(A_treat, float), np.asarray(A_ref, float)
    S = sensitivity((A_treat + A_ref) / 2)
    contrib = (A_treat - A_ref) * S
    lt, lr = eig_analysis(A_treat)["lambda"], eig_analysis(A_ref)["lambda"]
    return {"contributions": contrib, "sum_contributions": float(contrib.sum()),
            "observed_delta_lambda": lt - lr, "approximation_error": float(contrib.sum() - (lt - lr))}


def ltre_by_process(A_treat, A_ref, U_t, F_t, U_r, F_r) -> dict:
    S = sensitivity((np.asarray(A_treat) + np.asarray(A_ref)) / 2)
    dU = (np.asarray(U_t) - np.asarray(U_r)) * S
    dF = (np.asarray(F_t) - np.asarray(F_r)) * S
    n = S.shape[0]
    tri = np.indices((n, n))
    return {"stasis": float(dU[tri[0] == tri[1]].sum()), "progression": float(dU[tri[0] > tri[1]].sum()),
            "retrogression": float(dU[tri[0] < tri[1]].sum()), "fecundity": float(dF.sum())}


def recovery_time(A_harvest: np.ndarray, A_control: np.ndarray, n0: np.ndarray,
                  max_years: int = 200) -> dict:
    """Years after one harvest-year transition until total abundance regains the
    abundance an unharvested trajectory (same n0) would have had at the time of
    harvest's start, i.e. sum(n_t) >= sum(n0). Returns None when never recovered."""
    n = np.asarray(A_harvest, float) @ np.asarray(n0, float)
    target = float(np.sum(n0))
    for t in range(1, max_years + 1):
        if n.sum() >= target:
            return {"years_to_recover_initial_abundance": t, "criterion": "N(t) >= N(0)"}
        n = np.asarray(A_control, float) @ n
    return {"years_to_recover_initial_abundance": None, "criterion": "N(t) >= N(0)", "max_years": max_years}


def periodic_lambda(A_harvest: np.ndarray, A_control: np.ndarray, rotation: int) -> float:
    """Annualised growth rate for a cycle: one harvest-year transition then
    (rotation-1) control-year transitions. lambda_cycle^(1/rotation)."""
    P = np.asarray(A_harvest, float)
    for _ in range(rotation - 1):
        P = np.asarray(A_control, float) @ P
    return float(eig_analysis(P)["lambda"] ** (1.0 / rotation))


def hypothetical_removal(U: np.ndarray, F: np.ndarray, C: np.ndarray | None, stages: list[int],
                         fraction: float) -> np.ndarray:
    """Tier-B counterfactual: remove `fraction` of individuals in `stages` each year
    (lethal whole-plant removal: their survival transitions and fecundity scaled by 1-fraction).
    This is a mathematical assumption, NOT an observed harvest response."""
    if not 0 <= fraction < 1:
        raise ValueError("fraction must be in [0,1)")
    U2 = np.array(U, float)
    F2 = np.array(F, float)
    C2 = np.zeros_like(U2) if C is None else np.nan_to_num(np.array(C, float))
    for s in stages:
        U2[:, s] *= 1 - fraction
        F2[:, s] *= 1 - fraction
        C2[:, s] *= 1 - fraction
    return U2 + F2 + C2
