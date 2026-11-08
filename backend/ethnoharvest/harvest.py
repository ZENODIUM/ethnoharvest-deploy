"""Audited registry of medicinal-plant harvest studies in COMPADRE v6.26.3.0
and the comparison engine used by Simulate (Tier A).

Each study entry was built by inspecting COMPADRE metadata (MatrixTreatment,
MatrixPopulation, years, composite type), the Crossref title, and - for the
flagship and Khaya - the full paper (see docs/research/LITERATURE_DOSSIER.md).
`design` states what kind of contrast a comparison really is:
  experimental     - harvest applied as a treatment with controls in the same population
  observational    - harvested vs unharvested populations (site differences confounded)
  modelled         - treatment matrices are published model scenarios, not observed
  uncontrolled     - no comparable control in the study
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from . import compadre, demography as dm

STUDIES: list[dict] = [
    {
        "id": "nardostachys-ghimire2008",
        "species": "Nardostachys jatamansi", "synonym_in_paper": "Nardostachys grandiflora",
        "study": "10.1111/j.1365-2664.2007.01375.x",
        "citation": "Ghimire SK, Gimenez O, Pradel R, McKey D, Aumeeruddy-Thomas Y (2008) J Appl Ecol 45:41-51",
        "organ": "rhizome", "product": "medicinal/aromatic rhizome (spikenard, jatamansi)",
        "site": "Shey-Phoksundo National Park, Dolpa, Nepal", "habitat": "alpine rocky outcrop; alpine meadow",
        "design": "experimental",
        "control_ids": [244455], "treatment_ids": [244456, 244457, 244458, 244459],
        "intensity": {244455: 0, 244456: 10, 244457: 25, 244458: 50, 244459: 75},
        "reference_ids": [244454],
        "notes": "Single rhizome harvest (Sept 1998) at 0/10/25/50/75% in outcrop subplots by local amchi; "
                 "COMPADRE stores 1999-2002 mean matrices. Meadow (244454) is an unharvested population in a "
                 "different habitat, not a control for outcrop treatments. COMPADRE altitude (4805 m) differs from "
                 "paper (3800-4200 m): metadata discrepancy logged.",
        "tier": "A",
    },
    {
        "id": "khaya-gaoue2010",
        "species": "Khaya senegalensis", "study": "10.1111/j.1523-1739.2009.01345.x",
        "citation": "Gaoue OG, Ticktin T (2010) Conserv Biol 24:605-614",
        "organ": "bark + foliage", "product": "bark (medicine), foliage (cattle fodder)",
        "site": "Benin (Sudanian & Sudano-Guinean regions)", "habitat": "savanna / dry forest",
        "design": "observational",
        "control_ids": [247595, 247598, 247601, 247604, 247607, 247610],
        "treatment_ids": [247614, 247617, 247620, 247623, 247626, 247629],
        "notes": "Six high-harvest vs six low-harvest populations (population-level mean matrices 2004-2006). "
                 "Harvest status is not randomised: ecoregion and site differences are confounded.",
        "tier": "A",
    },
    {
        "id": "khaya-gaoue2013",
        "species": "Khaya senegalensis", "study": "10.1111/1365-2745.12140",
        "citation": "Gaoue OG, Horvitz CC, Ticktin T, Steiner UK, Tuljapurkar S (2013) J Ecol 101:1065-1073",
        "organ": "bark + foliage", "product": "bark (medicine), foliage (fodder)",
        "site": "Benin", "habitat": "moist vs dry ecoregion",
        "design": "observational",
        "control_ids": [250249, 250250, 250252, 250255, 250257, 250259],
        "treatment_ids": [250251, 250253, 250254, 250256, 250258, 250260],
        "notes": "Same 12 populations re-censused 2004-2007. Intensity-class matrices (247640-247645) are pooled "
                 "by ecoregion and intensity.",
        "tier": "A",
    },
    {
        "id": "prunus-stewart2001",
        "species": "Prunus africana", "study": "Stewart 2001",
        "citation": "Stewart KM (2001) The commercial bark harvest of the African cherry (Prunus africana) on Mount "
                    "Oku, Cameroon (PhD thesis); matrices as archived in COMPADRE",
        "organ": "bark", "product": "bark (Pygeum extract, prostate remedies)",
        "site": "Mount Oku, Cameroon (per thesis; COMPADRE plot labels only)", "habitat": "montane forest",
        "design": "observational",
        "control_ids": [247846], "treatment_ids": [247850, 247853, 247856, 247859],
        "notes": "One unharvested plot vs four harvested plots (once or twice per year), 1997-1999. No DOI; "
                 "single control plot means the contrast has no replication on the control side. The thesis abstract reports "
                 "lambda below 1 in harvested plots; 6 of 8 single-year harvested matrices here are below 1, but the 1997-99 mean "
                 "matrices used for this comparison are at or above 1 in 3 of 4 plots. A later forest-wide harvest (2005/06) "
                 "is outside these matrices (Stewart 2009, For Ecol Manage 258:1121).",
        "tier": "A",
    },
    {
        "id": "echinacea-hurlburt1999",
        "species": "Echinacea angustifolia", "study": "Hurlburt 1999",
        "citation": "Hurlburt DP (1999) Population ecology and economic botany of Echinacea angustifolia, a native "
                    "prairie medicinal plant (PhD/MSc thesis, Univ. of Kansas); matrices as archived in COMPADRE",
        "organ": "root", "product": "root (Echinacea herbal products)",
        "site": "Natoma & Woodston, Kansas, USA", "habitat": "mixed-grass prairie",
        "design": "observational",
        "control_ids": [242921, 242924], "treatment_ids": [242931, 242934],
        "pairs": [[242921, 242931], [242924, 242934]],
        "notes": "Harvested vs unmanipulated plants within two sites, 1996-1998. Thesis not peer-reviewed.",
        "tier": "A",
    },
    {
        "id": "phyllanthus-ticktin2012",
        "species": "Phyllanthus emblica", "study": "10.1111/j.1365-2664.2012.02156.x",
        "citation": "Ticktin T, Ganesan R, Paramesha M, Setty S (2012) J Appl Ecol 49:774-784",
        "organ": "fruit", "product": "amla fruit (Ayurvedic medicine, Triphala)",
        "site": "Biligiri Rangaswamy Temple Wildlife Sanctuary, India", "habitat": "tropical dry forest",
        "design": "observational",
        "control_ids": [247692], "treatment_ids": [247708],
        "notes": "Fruit-harvest matrices cover 1999-2006 whereas unmanipulated matrices cover 2006-2009: period and "
                 "harvest are confounded. Mistletoe/Lantana co-drivers present. The authors conclude fruit harvest has little "
                 "effect on stochastic growth and mistletoe drives decline; Prasad et al. 2014 (J Appl Ecol 51:642) dispute this, "
                 "and the reply (51:648) attributes the post-ban rise to adult survival. The before/after contrast shown here is "
                 "exactly the comparison in dispute.",
        "tier": "A",
    },
    {
        "id": "boswellia-groenendijk2012",
        "species": "Boswellia papyrifera", "study": "10.1111/j.1365-2664.2011.02078.x",
        "citation": "Groenendijk P, Eshete A, Sterck FJ, Zuidema PA, Bongers F (2012) J Appl Ecol 49:164-173",
        "organ": "resin (stem tapping)", "product": "frankincense (incense, traditional medicine)",
        "site": "Metema & Adi Arkay, Ethiopia", "habitat": "dry woodland",
        "design": "observational",
        "control_ids": [247441], "treatment_ids": [247440],
        "notes": "Tapped vs untapped populations; the paper's conclusion is that both decline because of blocked "
                 "regeneration (grazing, fire), independent of tapping.",
        "tier": "A",
    },
    {
        "id": "sabal-martinez2007",
        "species": "Sabal yapa", "study": "10.1017/S0266467406003877",
        "citation": "see Crossref",
        "organ": "leaf", "product": "thatch (not a medicinal product)",
        "site": "Yucatán Peninsula, Mexico", "habitat": "crop fields vs forest",
        "design": "observational",
        "control_ids": [246380, 246383], "treatment_ids": [246386],
        "notes": "Harvested palms are in crop fields; habitat and harvest fully confounded. Harvested organ is not "
                 "the medicinal organ.",
        "tier": "B",
    },
    # Added 2026-11-07 by the case-study validation (CASE_STUDY_VALIDATION.md). Kept out of E04 (in_e04=False) because
    # E04 was frozen on the eight studies above; adding them would change a reported result post hoc.
    {
        "id": "panax-vandervoort2006",
        "species": "Panax quinquefolius", "study": "10.1016/j.biocon.2006.01.010",
        "citation": "Van der Voort ME, McGraw JB (2006) Effects of harvester behavior on population growth rate affects "
                    "sustainability of ginseng trade. Biol Conserv 130:505-516",
        "organ": "root", "product": "root (American ginseng)",
        "site": "West Virginia, USA (COMPADRE gives no coordinates)", "habitat": "deciduous forest understorey",
        "design": "modelled",
        "control_ids": [244577], "treatment_ids": [244578, 244579, 244580],
        "labels": {244577: "No harvest", 244578: "Non-compliant harvester (ignores size limit and season)",
                   244579: "Compliant harvester (follows state rules)", 244580: "Steward harvester (later season, self-limits, plants seed)"},
        "notes": "Three harvester types simulated on field-measured West Virginia matrices (1998-2000): the treatments are model "
                 "scenarios, not harvests observed in plots. Authors conclude state rules are not adequate to protect wild "
                 "populations and that stewardship (later season, lower intensity, seed planting) can reverse decline.",
        "tier": "A", "in_e04": False,
    },
    {
        "id": "colchicum-winter2014-cut",
        "species": "Colchicum autumnale", "study": "10.1111/1365-2664.12217",
        "citation": "Winter S, Jung LS, Eckstein RL, Otte A, Donath TW, Kriechbaum M (2014) Control of the toxic plant Colchicum "
                    "autumnale in semi-natural grasslands: effects of cutting treatments on demography and diversity. "
                    "J Appl Ecol 51:524-533",
        "organ": "leaf (spring cutting)", "product": "none: cutting was applied to CONTROL a toxic plant, not to collect medicine",
        "site": "Six regions in Austria and Germany", "habitat": "semi-natural grassland",
        "design": "experimental",
        "control_ids": [242523, 242539], "treatment_ids": [242531, 242535, 242543, 242547, 242551],
        "labels": {242523: "June cut (usual practice) · Austria", 242539: "June cut (usual practice) · Germany",
                   242531: "Late-May cut · Austria", 242535: "Early-May cut · Austria", 242543: "Late-May cut · Germany",
                   242547: "Early-May cut · Germany", 242551: "Repeated May cut · Germany"},
        "notes": "Randomised cutting plots, 2008-2011 mean matrices. COMPADRE labels the comparison plots 'Unmanipulated'; the paper "
                 "describes them as cut in June (conventional management). The aim was to reduce a toxic weed, and the cut removes "
                 "leaves, not the medicinal seeds or corms: use as evidence on the timing of leaf removal, not on medicinal collection.",
        "tier": "B", "in_e04": False,
    },
    {
        "id": "colchicum-winter2014-flower",
        "species": "Colchicum autumnale", "study": "10.1111/1365-2664.12217",
        "citation": "Winter S et al. (2014) J Appl Ecol 51:524-533 (flower-removal treatment, Austria)",
        "organ": "flower", "product": "none: flower removal was a weed-control treatment",
        "site": "Austria", "habitat": "semi-natural grassland",
        "design": "experimental",
        "control_ids": [242523], "treatment_ids": [242527],
        "labels": {242523: "June cut (usual practice) · Austria", 242527: "Autumn flower removal · Austria"},
        "notes": "One Austrian flower-removal treatment against the June-cut plots (2008-2011 mean matrices). Single treatment and "
                 "single region; weed-control purpose.",
        "tier": "B", "in_e04": False,
    },
    {
        "id": "garcinia-guedje2007",
        "species": "Garcinia lucida", "study": "10.1016/j.foreco.2006.09.029",
        "citation": "Guedje NM, Zuidema PA, During H, Foahom B, Lejoly J (2007) Tree bark as a non-timber forest product "
                    "[Garcinia lucida]. For Ecol Manage 240:1-12",
        "organ": "bark", "product": "bark and seeds (traded medicine, palm-wine additive)",
        "site": "Nyangong and Ebom, South Cameroon Atlantic forest", "habitat": "lowland evergreen forest",
        "design": "modelled",
        "control_ids": [247569], "treatment_ids": [247570, 247571, 239739, 239740],
        "labels": {247569: "No bark harvest", 247570: "Partial debarking (one side)", 247571: "Ring-barking (whole circumference)",
                   239739: "Felling at 1 m after fruiting", 239740: "Felling at 1 m before fruiting"},
        "notes": "Growth rate hides the damage here: the authors find the stock of harvestable trees falls to about half in 20 years "
                 "under annual partial debarking and below 4% under annual ring-barking or felling, although lambda stays near 1. "
                 "EthnoHarvest does not compute the harvestable stock. Matrix models for three local practices, built from a "
                 "two-year field study (1997-1999); felling matrices have 9 stages, the others 8, so no LTRE is shown for felling.",
        "tier": "A", "in_e04": False,
    },
]

def _apply_crossref_citations() -> None:
    """Replace hand-written citations with Crossref-derived strings (data/clean/citations_crossref.json)."""
    import json
    f = compadre.CLEAN / "citations_crossref.json"
    cites = json.loads(f.read_text(encoding="utf8")) if f.exists() else {}
    for s in STUDIES:
        if s["study"] in cites:
            s["citation"] = cites[s["study"]]
            s["citation_source"] = "Crossref"
        elif s["study"].startswith("10."):
            s["citation_source"] = "entered from the publisher record (DOI resolves); not in the Crossref cache"
        else:
            s["citation_source"] = "COMPADRE metadata (no DOI; thesis/grey literature, not independently verified)"


_apply_crossref_citations()
BY_ID = {s["id"]: s for s in STUDIES}


def _lam(mid: int) -> float:
    return dm.eig_analysis(np.nan_to_num(compadre.matrices(mid)["A"]))["lambda"]


def matrix_card(mid: int) -> dict:
    md = compadre.metadata().set_index("MatrixID").loc[int(mid)]
    M = compadre.matrices(mid)
    A, U, F, C = M["A"], M["U"], M["F"], M["C"]
    val = dm.validate(A, U, F, C)
    e = dm.eig_analysis(np.nan_to_num(A))
    st = compadre.stages(mid)
    out = {
        "matrix_id": int(mid), "species": md["SpeciesAccepted"], "population": md["MatrixPopulation"],
        "treatment": md["MatrixTreatment"], "composite": md["MatrixComposite"],
        "start_year": _s(md["MatrixStartYear"]), "end_year": _s(md["MatrixEndYear"]),
        "study_id": md["StudyID"], "observations": _s(md["Observations"]),
        "lat": _f(md["Lat"]), "lon": _f(md["Lon"]), "altitude": _f(md["Altitude"]), "country": _s(md["Country"]),
        "stages": st["author"] or st["organized"], "stage_classes": st["organized"],
        "A": np.nan_to_num(A).round(6).tolist(), "U": np.nan_to_num(U).round(6).tolist(),
        "F": np.nan_to_num(F).round(6).tolist(), "C": np.nan_to_num(C).round(6).tolist(),
        "validation": val.as_dict(),
        "lambda": e["lambda"], "lambda_power_check": dm.lambda_power(np.nan_to_num(A)),
        "damping_ratio": e["damping_ratio"], "stable_stage": e["stable_stage"].tolist(),
        "reproductive_value": e["reproductive_value"].tolist(),
        "elasticity": dm.elasticity(np.nan_to_num(A)).round(6).tolist(),
    }
    if val.ok and md["qc_split_available"]:
        out["elasticity_by_process"] = dm.elasticity_by_process(A, U, F, C)
        out["life_table"] = dm.life_table_metrics(U, F)
    return out


def _s(x):
    return None if pd.isna(x) else str(x)


def _f(x):
    return None if pd.isna(x) else float(x)


@lru_cache(maxsize=None)
def compare(study_id: str) -> dict:
    """Treatment-vs-control comparison for one audited study."""
    s = BY_ID[study_id]
    ctrl = [_lam(i) for i in s["control_ids"]]
    trt = [_lam(i) for i in s["treatment_ids"]]
    res = {"study": {k: v for k, v in s.items() if k not in ("intensity",)},
           "control_lambdas": dict(zip(map(int, s["control_ids"]), ctrl)),
           "treatment_lambdas": dict(zip(map(int, s["treatment_ids"]), trt)),
           "mean_control": float(np.mean(ctrl)), "mean_treatment": float(np.mean(trt)),
           "delta_mean": float(np.mean(trt) - np.mean(ctrl))}
    # LTRE by process (each treatment vs mean control matrix)
    Cs = [compadre.matrices(i) for i in s["control_ids"]]
    Uc = np.mean([np.nan_to_num(m["U"]) for m in Cs], axis=0)
    Fc = np.mean([np.nan_to_num(m["F"]) for m in Cs], axis=0)
    ltre = {}
    for i in s["treatment_ids"]:
        T = compadre.matrices(i)
        if T["U"].shape != Uc.shape:
            continue
        ltre[int(i)] = dm.ltre_by_process(np.nan_to_num(T["A"]), Uc + Fc, np.nan_to_num(T["U"]),
                                          np.nan_to_num(T["F"]), Uc, Fc)
    res["ltre_by_process"] = ltre
    if len(ctrl) >= 3 and len(trt) >= 3:
        res["permutation_test"] = permutation_test(np.array(trt), np.array(ctrl))
    if "intensity" in s:
        res["dose_response"] = [{"intensity_pct": s["intensity"][i], "matrix_id": i, "lambda": _lam(i)}
                                for i in [*s["control_ids"], *s["treatment_ids"]]]
    return res


def permutation_test(a: np.ndarray, b: np.ndarray, n: int = 20000, seed: int = 1) -> dict:
    """Two-sided exact/Monte-Carlo permutation test on difference of means (populations as units)."""
    rng = np.random.default_rng(seed)
    obs = a.mean() - b.mean()
    pool = np.concatenate([a, b])
    k = len(a)
    diffs = np.empty(n)
    for i in range(n):
        p = rng.permutation(pool)
        diffs[i] = p[:k].mean() - p[k:].mean()
    pval = float((np.abs(diffs) >= abs(obs) - 1e-12).mean())
    # bootstrap CI of the difference
    boots = [rng.choice(a, k).mean() - rng.choice(b, len(b)).mean() for _ in range(5000)]
    return {"observed_difference": float(obs), "p_value": pval, "n_treatment": int(k), "n_control": int(len(b)),
            "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))], "seed": seed,
            "unit": "population mean matrix"}


def all_comparisons() -> list[dict]:
    return [compare(s["id"]) for s in STUDIES]
