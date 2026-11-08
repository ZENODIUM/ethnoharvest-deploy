"""Presence-background habitat suitability with spatial-block validation.

Suitability = relative climatic similarity to cleaned presence records. It is NOT
abundance, survival, or a safe-harvest area. A model is only served when it
beats the climate-4 logistic baseline under spatial-block CV and has AUC >= 0.7.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, PolynomialFeatures

from . import spatial as sp

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "data" / "derived" / "habitat"
ALL_BIO = list(range(1, 20))
BASE_BIO = [1, 5, 12, 15]
MIN_PRESENCE = 100
BLOCK_DEG = 5.0


def _features(points, bios):
    wc = sp.worldclim_at(points, tuple(bios))
    X = np.array([[wc[b][i] for b in bios] for i in range(len(points))], dtype=float)
    return X


def collect(name: str, extent: list[float], tile: float = 5.0, per_tile: int = 150, seed: int = 0) -> dict:
    """Spatially stratified presence sample (per tile) + background from the same tiles."""
    w, s, e, n = extent
    rng = np.random.default_rng(seed)
    pres = []
    tiles = []
    y = s
    while y < n:
        x = w
        while x < e:
            tiles.append([x, y, min(x + tile, e), min(y + tile, n)])
            x += tile
        y += tile
    occ_counts = {}
    for t in tiles:
        o = sp.gbif_occurrences(name, sp.parse_region({"bbox": t}), max_records=per_tile)
        if o.get("status") != "available":
            continue
        occ_counts[str(t)] = o["clean_count"]
        pres += [(r["lon"], r["lat"]) for r in o["records"]]
    pres = list(dict.fromkeys((round(a, 3), round(b, 3)) for a, b in pres))
    occupied = [t for t in tiles if occ_counts.get(str(t), 0) > 0]
    bg = []
    for t in occupied:
        k = 3 * max(occ_counts[str(t)], 10)
        xs = rng.uniform(t[0], t[2], k)
        ys = rng.uniform(t[1], t[3], k)
        bg += list(zip(xs, ys))
    return {"presence": pres, "background": bg, "tiles": occupied, "occ_counts": occ_counts}


def _block_ids(points):
    return np.array([f"{math.floor(x / BLOCK_DEG)}_{math.floor(y / BLOCK_DEG)}" for x, y in points])


def _models():
    return {
        "logistic_climate4": (BASE_BIO, lambda: make_pipeline(StandardScaler(), PolynomialFeatures(2), LogisticRegression(max_iter=2000, C=1.0))),
        "logistic_bio19_l2": (ALL_BIO, lambda: make_pipeline(StandardScaler(), PolynomialFeatures(2), LogisticRegression(max_iter=4000, C=0.1))),
        "gbm_bio19": (ALL_BIO, lambda: HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300, random_state=0)),
    }


def evaluate(name: str, extent: list[float], seed: int = 0) -> dict:
    data = collect(name, extent, seed=seed)
    P, B = data["presence"], data["background"]
    res = {"species": name, "extent": extent, "n_presence": len(P), "n_background": len(B),
           "n_tiles": len(data["tiles"]), "block_deg": BLOCK_DEG}
    if len(P) < MIN_PRESENCE:
        res["status"] = "suppressed"
        res["reason"] = f"{len(P)} cleaned presences < {MIN_PRESENCE}: habitat model not defensible"
        return res
    pts = P + B
    y = np.array([1] * len(P) + [0] * len(B))
    Xall = _features(pts, ALL_BIO)
    ok = ~np.isnan(Xall).any(axis=1)
    pts = [p for p, k in zip(pts, ok) if k]
    Xall, y = Xall[ok], y[ok]
    blocks = _block_ids(pts)
    ub = np.unique(blocks)
    rng = np.random.default_rng(seed)
    fold_of_block = dict(zip(ub, rng.permutation(len(ub)) % 5))
    spatial_folds = np.array([fold_of_block[b] for b in blocks])
    random_folds = rng.permutation(len(y)) % 5
    out = {}
    for mname, (bios, make) in _models().items():
        idx = [ALL_BIO.index(b) for b in bios]
        X = Xall[:, idx]
        scores = {}
        for cvname, folds in [("random_cv", random_folds), ("spatial_block_cv", spatial_folds)]:
            aucs, aps = [], []
            for f in range(5):
                tr, te = folds != f, folds == f
                if len(np.unique(y[te])) < 2 or len(np.unique(y[tr])) < 2:
                    continue
                m = make().fit(X[tr], y[tr])
                p = m.predict_proba(X[te])[:, 1]
                aucs.append(roc_auc_score(y[te], p)); aps.append(average_precision_score(y[te], p))
            scores[cvname] = {"auc_mean": float(np.mean(aucs)), "auc_sd": float(np.std(aucs)),
                              "ap_mean": float(np.mean(aps)), "folds": len(aucs)}
        scores["optimism_random_minus_spatial"] = scores["random_cv"]["auc_mean"] - scores["spatial_block_cv"]["auc_mean"]
        out[mname] = scores
    # negative control: shuffled labels, spatial CV, best model family
    ys = rng.permutation(y)
    aucs = []
    for f in range(5):
        tr, te = spatial_folds != f, spatial_folds == f
        if len(np.unique(ys[te])) < 2:
            continue
        m = _models()["gbm_bio19"][1]().fit(Xall[tr], ys[tr])
        aucs.append(roc_auc_score(ys[te], m.predict_proba(Xall[te])[:, 1]))
    res["negative_control_shuffled_auc"] = float(np.mean(aucs))
    res["models"] = out
    best = max(out, key=lambda k: out[k]["spatial_block_cv"]["auc_mean"])
    base = out["logistic_climate4"]["spatial_block_cv"]["auc_mean"]
    res["best_model"] = best
    res["best_beats_baseline_by"] = out[best]["spatial_block_cv"]["auc_mean"] - base
    served = best if out[best]["spatial_block_cv"]["auc_mean"] - base > 0.01 else "logistic_climate4"
    res["served_model"] = served
    res["status"] = "eligible" if out[served]["spatial_block_cv"]["auc_mean"] >= 0.7 else "suppressed"
    if res["status"] == "eligible":
        bios, make = _models()[served]
        m = make().fit(Xall[:, [ALL_BIO.index(b) for b in bios]], y)
        # environmental envelope for extrapolation checks
        Xp = Xall[y == 1][:, [ALL_BIO.index(b) for b in bios]]
        res["envelope"] = {"bios": bios, "min": Xp.min(0).tolist(), "max": Xp.max(0).tolist()}
        MODELS.mkdir(parents=True, exist_ok=True)
        import joblib
        joblib.dump({"model": m, "bios": bios, "meta": res}, MODELS / f"{name.replace(' ', '_')}.joblib")
        (MODELS / f"{name.replace(' ', '_')}.json").write_text(json.dumps(res, default=float, indent=1))
    return res


def predict_cells(name: str, cells: list[dict]) -> dict:
    f = MODELS / f"{name.replace(' ', '_')}.joblib"
    if not f.exists():
        return {"status": "withheld by scientific gate",
                "reason": "no validated habitat model for this species (insufficient cleaned presences or failed spatial CV)"}
    import joblib
    obj = joblib.load(f)
    pts = [tuple(c["center"]) for c in cells]
    X = _features(pts, obj["bios"])
    env = obj["meta"]["envelope"]
    preds = []
    for i, row in enumerate(X):
        if np.isnan(row).any():
            preds.append({"id": cells[i]["id"], "suitability": None, "extrapolation": None})
            continue
        extrap = bool(((row < np.array(env["min"])) | (row > np.array(env["max"]))).any())
        p = float(obj["model"].predict_proba(row.reshape(1, -1))[0, 1])
        preds.append({"id": cells[i]["id"], "suitability": round(p, 3), "extrapolation": extrap})
    m = obj["meta"]
    if all(p["suitability"] is None for p in preds):
        return {"status": "unsupported", "reason": "no land cells with climate data in region", "predictions": preds}
    return {"status": "available", "model": m["served_model"],
            "spatial_cv_auc": m["models"][m["served_model"]]["spatial_block_cv"]["auc_mean"],
            "predictions": preds,
            "caveat": "Relative climatic suitability at 10' resolution from presence-background data; not abundance, survival or a harvest area. Cells outside the training envelope are flagged as extrapolation."}
