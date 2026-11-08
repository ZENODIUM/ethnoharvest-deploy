"""COMPADRE ingestion: RData -> clean metadata table + matrix store.

The raw RData (COMPADRE Data User Agreement: no raw redistribution) stays in
data/raw/compadre. We derive:
  data/clean/compadre_metadata.parquet  (one row per MatrixID, all 58 fields + QC flags)
  data/clean/compadre_matrices.npz      (matA/U/F/C per MatrixID, key "<id>_<A|U|F|C>")
"""
from __future__ import annotations

import json
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "compadre" / "COMPADRE_v.6.26.3.0.RData"
CLEAN = ROOT / "data" / "clean"
META = CLEAN / "compadre_metadata.parquet"
MATS = CLEAN / "compadre_matrices.npz"
VERSION = "6.26.3.0"


def _fix_text(s):
    if not isinstance(s, str):
        return s
    # rdata decodes latin1-flagged bytes as utf8; repair common mojibake when possible
    try:
        return s.encode("latin1").decode("utf8")
    except Exception:
        return s


def ingest() -> dict:
    import rdata

    warnings.filterwarnings("ignore")
    parsed = rdata.parser.parse_file(str(RAW))
    c = rdata.conversion.convert(parsed, default_encoding="latin1")["compadre"]
    md: pd.DataFrame = c["metadata"].reset_index(drop=True)
    for col in md.columns:
        if md[col].dtype == object or str(md[col].dtype).startswith("string"):
            md[col] = md[col].map(_fix_text)
    md["MatrixID"] = md["MatrixID"].astype(int)

    arrays: dict[str, np.ndarray] = {}
    qc_rows = []
    for i, m in enumerate(c["mat"]):
        mid = int(md.at[i, "MatrixID"])
        dims = {}
        for k in ("A", "U", "F", "C"):
            arr = np.asarray(m[f"mat{k}"].values, dtype=float)
            arrays[f"{mid}_{k}"] = arr
            dims[k] = arr.shape
        A, U, F, C = (arrays[f"{mid}_{k}"] for k in "AUFC")
        colsum_U = np.nansum(U, axis=0) if U.size else np.array([])
        qc_rows.append({
            "MatrixID": mid,
            "qc_dim": A.shape[0],
            "qc_A_has_na": bool(np.isnan(A).any()),
            "qc_U_has_na": bool(np.isnan(U).any()),
            "qc_F_has_na": bool(np.isnan(F).any()),
            "qc_negative": bool((np.nan_to_num(A) < 0).any()),
            "qc_U_colsum_max": float(np.nanmax(colsum_U)) if colsum_U.size else np.nan,
            "qc_U_survival_gt1": bool((colsum_U > 1.0 + 1e-6).any()) if colsum_U.size else False,
            "qc_A_equals_UFC": bool(np.allclose(np.nan_to_num(A), np.nan_to_num(U + F + C), atol=1e-6)),
            "qc_F_all_zero": bool(np.nansum(F) == 0),
            "qc_split_available": bool(not np.isnan(U).any() and not np.isnan(F).any() and np.nansum(U) > 0),
        })
    mc = c["matrixClass"]
    stage_rows = []
    for i, cls in enumerate(mc):
        mid = int(md.at[i, "MatrixID"])
        df = cls if isinstance(cls, pd.DataFrame) else pd.DataFrame(cls)
        stage_rows.append({"MatrixID": mid,
                           "stages_json": json.dumps({
                               "organized": [str(x) for x in df.get("MatrixClassOrganized", [])],
                               "author": [_fix_text(str(x)) for x in df.get("MatrixClassAuthor", [])],
                           })})
    qc = pd.DataFrame(qc_rows)
    st = pd.DataFrame(stage_rows)
    md = md.merge(qc, on="MatrixID").merge(st, on="MatrixID")
    # stable study key: DOI when present, else authors+year+journal (23% of rows lack DOI)
    fallback = (md["Authors"].fillna("?").astype(str) + " " + md["YearPublication"].fillna("?").astype(str)
                + " " + md["Journal"].fillna("").astype(str)).str.strip()
    md["StudyID"] = md["DOI_ISBN"].astype(object).where(md["DOI_ISBN"].notna(), fallback)
    CLEAN.mkdir(parents=True, exist_ok=True)
    md.to_parquet(META, index=False)
    np.savez_compressed(MATS, **arrays)
    version = {k: str(v) for k, v in c.get("version", {}).items()}
    (CLEAN / "compadre_version.json").write_text(json.dumps(version, indent=2))
    return {"matrices": len(md), "species": md["SpeciesAccepted"].nunique(), "version": version}


@lru_cache(maxsize=1)
def metadata() -> pd.DataFrame:
    return pd.read_parquet(META)


@lru_cache(maxsize=1)
def _store():
    return np.load(MATS)


def matrices(mid: int) -> dict[str, np.ndarray]:
    s = _store()
    return {k: s[f"{int(mid)}_{k}"] for k in "AUFC"}


def stages(mid: int) -> dict:
    row = metadata().set_index("MatrixID").loc[int(mid)]
    return json.loads(row["stages_json"])


if __name__ == "__main__":
    print(json.dumps(ingest(), indent=2))
