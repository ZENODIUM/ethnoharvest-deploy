"""Species-, organ- and jurisdiction-aware harvest cautions.

Each card says what kind of evidence stands behind it:
  supported-by-study            an audited harvest study of THIS species (numbers computed from its COMPADRE matrices)
  transferred-from-other-species a study on the same harvested part in another species (transferability uncertain)
  practitioner-guidance         NGO / field guidance for this species
  regulatory-listing            CITES listing (live Species+ lookup) or a located legal text
  requires-authority-confirmation reported rules we could not confirm in a primary source, or no source found
  general                       principles from GACP / FairWild that apply to any wild collection
  computed-from-matrices        computed here from COMPADRE matrices (bootstrap sensitivity of population growth to the harvested process)
  ai-found-literature           findings the evidence agent extracted from abstracts, each with a verbatim quote (awaiting review)
  needs-review                  papers the agent could not classify confidently; a person should read them
No card is a permit, a quota or a legal determination; every card awaits expert review until a person marks it.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from .. import harvest
from .db import LOCK, OpsError, conn, ensure
from .documents import fold, organ_parts
from .sources import GENERAL, JURISDICTION_RULES, SOURCES, source

TTL = 7 * 24 * 3600
RULESET = "cautions-1.1"
ORDER = ["supported-by-study", "computed-from-matrices", "practitioner-guidance", "ai-found-literature", "transferred-from-other-species",
         "regulatory-listing", "requires-authority-confirmation", "needs-review", "general"]


def _id(*parts) -> str:
    return "c_" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:10]


def card(issue, why, kind, applicability, uncertainty, nxt, sources, organ, scope) -> dict:
    return {"id": _id(issue, organ, scope), "issue": issue, "why_it_matters": why, "evidence_kind": kind, "applicability": applicability,
            "uncertainty": uncertainty, "recommended_next": nxt, "sources": sources, "organ": organ, "scope": scope,
            "human_review_status": "awaiting expert review", "not_a_permit": True}


def _study_source(s: dict) -> dict:
    doi = s.get("study", "")
    return {"title": s["citation"], "url": f"https://doi.org/{doi}" if doi.startswith("10.") else None, "kind": "study",
            "excerpt": None, "summary": s.get("notes")}


def _lam_summary(s: dict) -> tuple[str, dict]:
    c = harvest.compare(s["id"])
    if c.get("dose_response"):
        pts = sorted(c["dose_response"], key=lambda x: x["intensity_pct"])
        txt = "; ".join(f"{p['intensity_pct']}% harvest: λ {p['lambda']:.3f}" for p in pts)
        return f"Long-term growth rate by harvest intensity ({txt}). λ below 1 means a population that shrinks if conditions persist.", c
    if s.get("labels"):
        lams = {**c["control_lambdas"], **c["treatment_lambdas"]}
        txt = "; ".join(f"{s['labels'][m]}: λ {lams[m]:.3f}" for m in [*s["control_ids"], *s["treatment_ids"]] if m in s["labels"])
        return f"Long-term growth rate by scenario ({txt}). λ below 1 means a population that shrinks if conditions persist.", c
    return (f"Mean long-term growth rate λ {c['mean_treatment']:.3f} in harvested populations vs {c['mean_control']:.3f} in the comparison "
            f"populations (difference {c['delta_mean']:+.3f}; {len(c['treatment_lambdas'])} vs {len(c['control_lambdas'])} matrices)."), c


def study_cards(accepted: str, organ: str) -> list[dict]:
    want = organ_parts(organ)
    out = []
    other: dict[str, list] = {}  # one transferred card per other species, however many of its studies match
    for s in harvest.STUDIES:
        same_species = s["species"] == accepted
        same_organ = bool(want & organ_parts(s["organ"]))
        if not (same_species or same_organ):
            continue
        try:
            why, _ = _lam_summary(s)
        except Exception as e:  # noqa: BLE001 - matrices unavailable: say so rather than invent numbers
            why = f"Numbers could not be computed here ({type(e).__name__}); see the study."
        design = {"experimental": "harvest experiment", "modelled": "modelled harvest scenarios on field-measured matrices"}.get(
            s["design"], "observational comparison (harvest not randomised)")
        if not same_species:
            other.setdefault(s["species"], []).append((s, why))
            continue
        if same_species:
            out.append(card(
                f"Published {design} on {s['organ']} harvest", why,
                "supported-by-study", "same species, same part" if same_organ else f"same species, different part ({s['organ']})",
                "Site-specific: results come from " + s.get("site", "the study site") + (". " + s["notes"][:220] if s.get("notes") else ""),
                "Use it as a scenario in the Studio; local stage counts and recovery measurements are still needed before setting any limit.",
                [_study_source(s)], s["organ"], f"{s['species']} · {s.get('site', '')} · {s['id']}"))
    for sp, items in other.items():
        s0 = items[0][0]
        out.append(card(
            f"Evidence from another species harvested for {s0['organ']}: {sp}",
            " ".join(why for _, why in items) if len(items) == 1 else " ".join(f"Study {i + 1}: {why}" for i, (_, why) in enumerate(items)),
            "transferred-from-other-species", "different species, same part",
            "Different species and site: life history and recovery may differ; treat as a warning sign, not a number for this plant.",
            "Look for a study on this species; until then monitor plots before and after harvest.",
            [_study_source(s) for s, _ in items], s0["organ"], sp))
    return out


def guidance_cards(accepted: str, organ: str) -> list[dict]:
    parts = organ_parts(organ)
    out = []
    if accepted == "Nardostachys jatamansi" and parts & {"rhizome", "root"}:
        out.append(card("Field guidance: leave part of the rhizome and harvest rotationally",
                        SOURCES["ansab-jatamansi"]["summary"], "practitioner-guidance", "same species, same part",
                        "Practitioner guidance, not a measured threshold.", "Record the share of rhizome left and the rotation interval per plot.",
                        [source("ansab-jatamansi")], "rhizome", "Nepal field practice"))
    if accepted == "Khaya senegalensis" and parts & {"leaf", "foliage"}:
        out.append(card("Foliage harvest (pruning) can reduce fruit production", SOURCES["agris-khaya-2008"]["summary"],
                        "supported-by-study", "same species, same part", "Effect differed between regions; observational.",
                        "Record pruning intensity per tree and track fruiting before and after.", [source("agris-khaya-2008")], "leaf", "Benin"))
    return out


def regulation_cards(accepted: str, organ: str, jurisdiction: str | None, cites: dict | None) -> list[dict]:
    out = []
    parts = organ_parts(organ)
    c = cites or {}
    if c.get("status") == "available" and c.get("listed"):
        out.append(card(f"CITES Appendix {', '.join(c.get('appendices') or []) or '?'} listing",
                        "International trade needs CITES documents issued by the exporting country's Management Authority. "
                        + (f"Annotation: {c['annotation']}. " if c.get("annotation") else "") + "The listing does not govern collection itself.",
                        "regulatory-listing", "same species; parts covered depend on the annotation", "Listing status checked live via Species+.",
                        "Before any cross-border shipment, confirm with the CITES Management Authority which documents apply to your product.",
                        [source("speciesplus"), source("cites-appendices")], organ, "international trade"))
    elif c.get("status") != "available":
        out.append(card("CITES status unknown", f"The live CITES lookup was not available ({c.get('reason') or c.get('status')}). Unknown is not "
                        "the same as not listed.", "requires-authority-confirmation", "this species", "Lookup failed.",
                        "Check Species+ manually before trade.", [source("speciesplus")], organ, "international trade"))
    j = fold(jurisdiction or "")
    matched = False
    for r in JURISDICTION_RULES:
        if r["jurisdiction"] != j or (r["species"] and r["species"] != accepted) or (r["organs"] and not parts & set(r["organs"])):
            continue
        matched = True
        kind = "regulatory-listing" if r["status"] == "documented-requirement" else "requires-authority-confirmation"
        out.append(card(r["topic"], r["statement"], kind, f"{jurisdiction}" + (f", {accepted}" if r["species"] else ""),
                        {"documented-requirement": "Legal text located; how it applies to your site must be confirmed.",
                         "reported-requires-confirmation": "Reported by agency and NGO sources; the primary legal text was not verified by us.",
                         "no-credible-source-found": "No official source located yet."}[r["status"]],
                        r["next"], [source(s) for s in r["sources"]], organ, f"{jurisdiction} · rule {r['id']} · status {r['status']}"))
    if jurisdiction and not matched:
        out.append(card(f"No rule recorded for {jurisdiction}", "EthnoHarvest has no verified record of collection or trade rules for this "
                        "jurisdiction, species and part. Absence of a record is not absence of a rule.", "requires-authority-confirmation",
                        jurisdiction, "No source searched for this combination yet.", "Ask the national forestry or environment authority.",
                        [], organ, jurisdiction))
    for g in GENERAL:
        srcs = [source(s) for s in g["sources"]]
        if g.get("excerpt_key"):
            srcs[0]["excerpt"] = SOURCES[g["sources"][0]]["excerpts"][g["excerpt_key"]]
        out.append(card(g["topic"], g["statement"], "general", "any wild collection", "General principle, not specific to this plant.",
                        g["next"], srcs, organ, "general"))
    return out


REVIEW_LABEL = {"publishable_with_caveat": "shown with caveats; awaiting expert review",
                "needs_expert_review": "needs expert review before use", "insufficient": "insufficient evidence"}


def agent_cards(agent: dict | None, organ: str) -> list[dict]:
    """Turn evidence-agent findings into caution cards. Every literature card carries verbatim quotes as proof."""
    if not agent:
        return []
    out = []
    for f in agent["findings"]:
        flags = "; ".join(x["detail"] for x in f["flags"]) or "No conflicts found with the audited studies."
        if f.get("computed"):
            sens = agent["sensitivity"]
            c = card(f"How sensitive this population is to the harvested process ({sens['process']})", f["text"],
                     "computed-from-matrices", sens["basis"], flags + " " + sens["not_a_rate"],
                     "Use this to judge which local measurements matter most (e.g. survival of large plants), not as a harvest limit.",
                     [{"title": p["title"], "url": None, "kind": "computation", "excerpt": p["quote"], "summary": None} for p in f["proof"]],
                     organ, f"matrices: {', '.join(sens['species_used'])}")
        else:
            c = card(f["text"], "Found by the evidence agent: JEV classified the paper, Groq extracted the finding, and the quote below was "
                     "checked word-for-word against the abstract.", "ai-found-literature",
                     "this species" if f["scope"] == "same-species" else "other species (transferability uncertain)", flags,
                     "A scientific reviewer should read the paper(s) and confirm or reject this finding.",
                     [{"title": p["title"], "url": p["url"], "kind": "ai-quoted", "excerpt": p["quote"],
                       "summary": f"JEV/rules label: {p['triage']}" + (f" (JEV confidence {p['jev_confidence']:.2f})" if p.get("jev_confidence") else "")}
                      for p in f["proof"]], organ, f"evidence agent · {f['process']}")
        c["human_review_status"] = REVIEW_LABEL.get(f.get("review"), "awaiting expert review")
        c["review_route"] = {"route": f.get("review"), "by": f.get("review_by"), "jev": f.get("jev_review")}
        out.append(c)
    st = agent.get("stochastic") or {}
    if st.get("status") == "ok" and len(st["groups"]) == 2 and all("stochastic_lambda" in g for g in st["groups"].values()):
        h, u = st["groups"]["harvested"], st["groups"]["unharvested"]
        word = lambda x: "grows" if x > 1.005 else "shrinks" if x < 0.995 else "stays about level"
        c = card("With good and bad years mixed in", f"Simulating 20,000 years that randomly draw from the published matrices, the "
                 f"harvested populations {word(h['stochastic_lambda'])} (λs {h['stochastic_lambda']}) and the unharvested ones "
                 f"{word(u['stochastic_lambda'])} (λs {u['stochastic_lambda']}).", "computed-from-matrices", "this species",
                 st["note"] + f" Only studies with both harvested and unharvested matrices are used ({', '.join(st.get('studies') or [])}); "
                 "within a study, harvested and unharvested plots can still differ in site or period.",
                 "Compare this with local monitoring before drawing conclusions.",
                 [{"title": "COMPADRE v6.26.3.0 matrices (computed here)", "url": None, "kind": "computation",
                   "excerpt": f"{h['matrices']} harvested and {u['matrices']} unharvested same-size matrices, {h['years_simulated']} simulated years.",
                   "summary": None}], organ, "evidence agent · stochastic λ")
        c["human_review_status"] = "computed; awaiting expert review"
        out.append(c)
    unsure = [it for it in agent["triage"]["items"] if it["final"] == "needs_human"]
    if unsure:
        out.append(card(f"{len(unsure)} papers the AI could not classify confidently", "JEV and the keyword rules disagreed, or JEV was "
                        "unsure. They may or may not contain harvest effects.", "needs-review", "search results", "Unread by a person.",
                        "A scientific reviewer should screen these and promote relevant findings.",
                        [{"title": f"{it['title']} ({it.get('year')})", "url": it.get("url"), "kind": "candidate-literature", "excerpt": None,
                          "summary": f"rules: {it['rule']} · JEV: {it.get('jev') or 'n/a'}"} for it in unsure[:12]], organ, "evidence agent"))
    return out


def agent_summary(agent: dict | None) -> dict | None:
    if not agent:
        return None
    return {"queries": agent["queries"], "retrieved": agent["retrieval"]["retrieved"], "triage": agent["triage"]["counts"],
            "triage_mode": agent["triage"]["mode"], "jev_calls": agent["triage"]["jev_calls"], "agreement": agent["triage"]["agreement"],
            "claims": len(agent["claims"]["claims"]), "claims_dropped": agent["claims"]["dropped"], "claims_mode": agent["claims"]["mode"],
            "sensitivity": {k: agent["sensitivity"].get(k) for k in ("status", "basis", "process", "matrices", "share_mean", "share_ci95",
                                                                      "declining_fraction", "groups", "plain")},
            "flags": agent["conflicts"]["flags"], "duration_ms": agent["duration_ms"], "pipeline": agent.get("pipeline"),
            "verification": {k: (agent.get("verification") or {}).get(k) for k in ("checked", "rejected", "partly", "mode")} if agent.get("verification") else None,
            "stochastic": agent.get("stochastic")}


def build(accepted: str, organ: str, jurisdiction: str | None, cites: dict | None, literature: bool = True, agent: dict | None = None) -> dict:
    cards = study_cards(accepted, organ) + guidance_cards(accepted, organ) + regulation_cards(accepted, organ, jurisdiction, cites)
    lit_note = "literature agent skipped"
    if literature and agent is None and os.environ.get("OPS_LITERATURE", "1") != "0":
        from .. import evidence_agent
        agent = evidence_agent.run(accepted, organ)
    if agent:
        cards += agent_cards(agent, organ)
        lit_note = f"{agent['retrieval']['retrieved']} records searched"
    cards.sort(key=lambda c: ORDER.index(c["evidence_kind"]))
    return {"status": "ok", "ruleset": RULESET, "cards": cards, "literature": lit_note, "generated": time.time(), "agent": agent_summary(agent)}


# ------------------------------------------------------------------ cache + passport entry point
def cache_key(accepted, organ, jurisdiction) -> str:
    return "|".join([accepted, ",".join(sorted(organ_parts(organ))), fold(jurisdiction or ""), RULESET])


def cached(key: str) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT body, run_id, created FROM ops_caution_cache WHERE key=?", (key,)).fetchone()
    if r and time.time() - r["created"] < TTL:
        return {**json.loads(r["body"]), "run_id": r["run_id"], "cached": True}
    return None


def save(key, accepted, organ, jurisdiction, body, run_id):
    with LOCK, conn() as c:
        c.execute("INSERT OR REPLACE INTO ops_caution_cache VALUES (?,?,?,?,?,?,?)",
                  (key, accepted, organ, jurisdiction, json.dumps(body), run_id, time.time()))


def cautions_for(ws: str, role: str, pid: str, refresh: bool = False) -> dict:
    ensure()
    with conn() as c:
        p = c.execute("SELECT * FROM ops_passport WHERE workspace=? AND id=?", (ws, pid)).fetchone()
    if not p:
        raise OpsError(404, "passport not found")
    p = dict(p)
    key = cache_key(p["accepted_name"], p["organ"], p["jurisdiction"])
    if not refresh and (hit := cached(key)):
        return hit
    from .workflow import run_research
    return run_research(ws, p, key)
