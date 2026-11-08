"""EthnoHarvest AI HTTP API (FastAPI). Run: uvicorn backend.ethnoharvest.api:app --port 8000"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from . import agent, catalog, checklists, compadre, eligibility as el, harvest as hv, media, planner, providers, simulate as sim, spatial, store

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="EthnoHarvest AI", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"],
                   allow_methods=["*"], allow_headers=["*"])
store.init()
from .ops.api_ops import router as ops_router  # noqa: E402
app.include_router(ops_router)

# ------------------------------------------------------------------ rate limiting (expensive endpoints)
_hits: dict[str, deque] = defaultdict(deque)


def limit(request: Request, key: str, n: int = 20, per: float = 60.0):
    ip = request.client.host if request.client else "?"
    q = _hits[f"{ip}:{key}"]
    now = time.time()
    while q and now - q[0] > per:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, f"rate limit: max {n} {key} requests per {int(per)} s")
    q.append(now)


# ------------------------------------------------------------------ models
class Region(BaseModel):
    bbox: list[float] | None = None
    point: list[float] | None = None
    radius_km: float | None = None
    geometry: dict | None = None

    @field_validator("bbox")
    @classmethod
    def _bb(cls, v):
        if v is not None and (len(v) != 4 or v[0] >= v[2] or v[1] >= v[3]):
            raise ValueError("bbox must be [west, south, east, north] with west<east and south<north")
        return v

    def as_dict(self):
        return {k: v for k, v in self.model_dump().items() if v is not None}


class RunRequest(BaseModel):
    species: str | None = None
    region: Region | None = None
    goal: Literal["assess", "geography", "population_demography", "harvest_research", "survey_planning", "literature_review"] = "assess"
    question: str | None = Field(None, max_length=800)
    budget: float = Field(20, ge=1, le=500)
    local_evidence: dict[str, bool] = {}
    inject: list[Literal["provider_failure", "unknown_study", "low_jev_confidence", "unsupported_population_model",
                         "jev_unavailable", "groq_unavailable"]] = []


class SimRequest(BaseModel):
    mode: Literal["projection", "study", "rotation", "hypothetical"]
    matrix_id: int | None = None
    study_id: str | None = None
    treatment_id: int | None = None
    rest_years: int = Field(5, ge=1, le=60)
    stages: list[int] = []
    fraction: float = Field(0.1, ge=0, lt=1)
    horizon: int = Field(30, ge=1, le=200)
    n0: list[float] | None = None


class PlanRequest(BaseModel):
    intent: Literal["survey", "reverify", "evidence"]
    species: str
    region: Region | None = None
    budget: float = Field(20, ge=1, le=500)
    cost_params: dict[str, float] = {}
    have: dict[str, bool] = {}
    organ: str | None = Field(None, max_length=60)


class Item(BaseModel):
    name: str = Field(..., max_length=120)
    body: dict[str, Any]


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    md = compadre.metadata()
    return {"status": "ok", "compadre_version": compadre.VERSION, "matrices": int(len(md)),
            "providers": providers.configured() | {"cesium": providers.configured()["cesium"]},
            "medicinal_taxa": len(catalog.catalog()), "rule_version": "eligibility-1.0"}


@app.get("/api/species")
def species(q: str = "", limit: int = 20):
    return {"results": [{k: v for k, v in c.items() if k != "compadre_locations"} for c in catalog.search(q, min(limit, 100))],
            "total_catalog": len(catalog.catalog())}


@app.get("/api/species/{name}")
def species_detail(name: str):
    p = catalog.species_profile(name)
    if not p:
        # outside COMPADRE: still resolvable, but tier C with explicit gaps
        a = el.assess(name)
        return {"name": name, "in_catalog": False, "eligibility": a, "tier": "C", "checklists": checklists.species(name),
                "note": "Not among the 200 medicinal COMPADRE taxa: demographic and harvest models are unavailable; geography and literature still work."}
    return p | {"in_catalog": True, "checklists": checklists.species(name)}


@app.get("/api/species/{name}/checklists")
def species_checklists(name: str):
    return checklists.species(name) or {"status": "not checked", "reason": "not in the precomputed checklist table (catalogue species only)"}


@app.get("/api/species/{name}/cites")
def species_cites(name: str):
    return spatial.cites_status(name)


@app.get("/api/species/{name}/image")
def species_image(name: str, request: Request):
    if len(name) > 120:
        raise HTTPException(400, "name too long")
    limit(request, "media", 60)
    return media.species_image(name)


@app.get("/api/species/{name}/illustration")
def species_illustration(name: str, request: Request, generate: bool = False, organ: str | None = None):
    """Annotated illustration: curated (checked) for pre-baked species; generated on request (unchecked) for others."""
    from . import illustrations
    if len(name) > 120:
        raise HTTPException(400, "name too long")
    limit(request, "illustration-gen" if generate else "media", 6 if generate else 60)
    return illustrations.get(name.strip(), generate=generate, organ=(organ or "").strip()[:40] or None)


@app.get("/api/illustration/{iid}")
def illustration_bytes(iid: str):
    from . import illustrations
    f = illustrations.file(iid)
    if not f:
        raise HTTPException(404, "no illustration with this id")
    return FileResponse(f[0], media_type=f[1], headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


@app.get("/api/media/{mid}")
def media_bytes(mid: str):
    f = media.media_file(mid)
    if not f:
        raise HTTPException(404, "no cached licensed image with this id")
    return FileResponse(f[0], media_type=f[1], headers={"Cache-Control": "public, max-age=604800",
                                                        "X-Content-Type-Options": "nosniff"})


@app.get("/api/cases")
def cases():
    return {"cases": catalog.CASES}


@app.get("/api/eligibility/{name}")
def eligibility(name: str, occurrence_count: int | None = None, has_region: bool = False):
    return el.assess(name, region={"provided": True} if has_region else None, occurrence_count=occurrence_count)


# ------------------------------------------------------------------ runs (agent + live events)
def _start(req: dict) -> str:
    label = f"{req.get('species') or 'request'} · {req.get('goal')}"
    rid = store.create_run("assessment", label, req)
    threading.Thread(target=agent.run_assessment, args=(req, rid), daemon=True).start()
    return rid


class EvidenceRequest(BaseModel):
    species: str = Field(..., min_length=3, max_length=120)
    organ: str = Field(..., min_length=2, max_length=60)
    jurisdiction: str | None = Field(None, max_length=60)
    inject: list[Literal["low_jev_confidence", "jev_unavailable", "groq_unavailable"]] = []
    pipeline: list[str] | None = Field(None, max_length=30)


@app.get("/api/evidence-agent/components")
def evidence_agent_components():
    from . import evidence_agent as EA
    return {"components": EA.COMPONENTS, "default": EA.DEFAULT_PIPELINE,
            "fixed": [{"id": "taxonomy_match", "label": "Taxonomy and synonym match"}, {"id": "regulation_retrieve", "label": "Listings and jurisdiction rules"},
                      {"id": "report", "label": "Report"}]}


@app.post("/api/evidence-agent")
def evidence_agent_run(body: EvidenceRequest, request: Request):
    """Harvest Evidence Agent for any species x plant part x country; streams on /api/runs/{id}/events."""
    limit(request, "runs", 15)
    from .ops import workflow
    return {"run_id": workflow.start_evidence_run(body.species.strip(), body.organ.strip(), body.jurisdiction, set(body.inject),
                                                 body.pipeline)}


@app.get("/api/methods")
def methods_catalogue():
    from . import methods
    return methods.catalogue()


@app.get("/api/methods/photos")
def methods_photos(request: Request, organ: str = Query(..., max_length=40), species: str | None = Query(None, max_length=120)):
    """Open-licence photos for a harvested part (curated queries), or a live species-specific search with a generic fallback."""
    limit(request, "media", 30)
    from . import methods
    oid = methods.organ_id(organ)
    if not oid:
        raise HTTPException(404, "unknown plant part")
    return methods.organ_photos(oid, species.strip() if species else None)


@app.get("/api/methods/catalogue-photos")
def methods_catalogue_photos():
    """All hand-picked part, technique and tool images, grouped by plant part."""
    from . import methods
    return methods.photo_catalogue()


@app.get("/api/methods/photo/{pid}")
def methods_photo(pid: str):
    from . import methods
    f = methods.photo_file(pid)
    if not f:
        raise HTTPException(404, "photo not cached")
    return FileResponse(f[0], media_type=f[1], headers={"Cache-Control": "public, max-age=604800", "X-Content-Type-Options": "nosniff"})


class MethodsAnalyse(BaseModel):
    species: str = Field(..., min_length=3, max_length=120)
    organ: str = Field(..., min_length=2, max_length=40)
    country: str | None = Field(None, max_length=60)


@app.post("/api/methods/analyse")
def methods_analyse(body: MethodsAnalyse, request: Request):
    """Runs the Harvest Evidence Agent for this species and part; results stream on /api/runs/{id}/events."""
    limit(request, "runs", 15)
    from . import methods
    from .ops import workflow
    oid = methods.organ_id(body.organ)
    if not oid:
        raise HTTPException(404, "unknown plant part")
    return {"run_id": workflow.start_evidence_run(body.species.strip(), methods.ORGAN_BY_ID[oid]["agent_organ"], body.country)}


@app.post("/api/runs")
def create_run(body: RunRequest, request: Request):
    limit(request, "runs", 15)
    req = body.model_dump()
    req["region"] = body.region.as_dict() if body.region else None
    if req["region"]:
        try:
            spatial.parse_region(req["region"])
        except Exception as e:
            raise HTTPException(422, f"invalid region: {e}")
    return {"run_id": _start(req)}


@app.get("/api/runs")
def runs(limit_: int = 50):
    return {"runs": store.list_runs(limit_)}


@app.get("/api/runs/{rid}")
def run(rid: str):
    r = store.get_run(rid)
    if not r:
        raise HTTPException(404, "run not found")
    return r | {"events": store.events(rid), "jev": store.jev_for_run(rid)}


@app.get("/api/runs/{rid}/context")
def run_context(rid: str):
    """Full geo context of a run (grid, layers, occurrences) - recomputed from cache, never stored with secrets."""
    r = store.get_run(rid)
    if not r:
        raise HTTPException(404)
    inp = r["inputs"]
    if not inp.get("region"):
        return {"status": "study-only"}
    from . import habitat
    ctx = spatial.region_context(inp.get("species"), inp["region"], sensitive=True)
    ctx["suitability"] = habitat.predict_cells(inp.get("species"), ctx["grid"]) if inp.get("species") else None
    return ctx


@app.get("/api/runs/{rid}/events")
async def run_events(rid: str, request: Request, after: int = 0):
    if not store.get_run(rid):
        raise HTTPException(404)

    try:  # EventSource reconnects send the last id they saw: resume from there instead of replaying
        resume = int(request.headers.get("last-event-id") or 0)
    except ValueError:
        resume = 0

    async def gen():
        last = max(after, resume)
        idle = 0
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                break
            evs = store.events(rid, last)
            for e in evs:
                last = e["seq"]
                yield f"id: {e['seq']}\nevent: node\ndata: {json.dumps(e, default=str)}\n\n"
            r = store.get_run(rid)
            if r["status"] != "running" and not evs:
                yield f"event: done\ndata: {json.dumps({'status': r['status']})}\n\n"
                break
            idle = 0 if evs else idle + 1
            if idle and idle % 30 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ explore (direct, cached)
@app.post("/api/explore/context")
def explore_context(body: dict, request: Request):
    limit(request, "explore", 30)
    reg = Region(**(body.get("region") or {}))
    from . import habitat
    try:
        ctx = spatial.region_context(body.get("species"), reg.as_dict(), sensitive=True)
    except ValueError as e:
        raise HTTPException(422, str(e))
    if body.get("species"):
        ctx["suitability"] = habitat.predict_cells(body["species"], ctx["grid"])
    return ctx


@app.get("/api/layers")
def layers():
    return {"groups": [
        {"id": "observed", "label": "Observed biodiversity", "layers": [
            {"id": "occurrences", "label": "GBIF occurrences (cleaned)", "kind": "points", "status_source": "occurrences"},
            {"id": "compadre_pops", "label": "COMPADRE study populations", "kind": "points", "status_source": "static"},
            {"id": "native_range", "label": "Native range (WCVP/POWO, TDWG regions)", "kind": "polygons"}]},
        {"id": "habitat", "label": "Habitat & vegetation", "layers": [
            {"id": "suitability", "label": "Climatic suitability (validated models only)", "kind": "grid"},
            {"id": "worldcover", "label": "ESA WorldCover 2021 (display)", "kind": "wms",
             "url": "https://services.terrascope.be/wms/v2", "wms_layer": "WORLDCOVER_2021_MAP",
             "attribution": "© ESA WorldCover project 2021 / Contains modified Copernicus Sentinel data (2021)"}]},
        {"id": "climate", "label": "Climate & hydrology", "layers": [
            {"id": "bio1", "label": "Mean annual temperature (WorldClim 10')", "kind": "grid"},
            {"id": "bio12", "label": "Annual precipitation (WorldClim 10')", "kind": "grid"}]},
        {"id": "terrain", "label": "Terrain & soil", "layers": [
            {"id": "elevation", "label": "Elevation (Copernicus GLO-90 via Open-Meteo)", "kind": "grid"},
            {"id": "soil", "label": "SoilGrids 2.0", "kind": "pending"}]},
        {"id": "disturbance", "label": "Disturbance & conservation", "layers": [
            {"id": "treeloss", "label": "Tree-cover loss 2001–2023 (Hansen/UMD, display)", "kind": "xyz",
             "url": "https://tiles.globalforestwatch.org/umd_tree_cover_loss/v1.11/tcd_30/{z}/{x}/{y}.png",
             "attribution": "Hansen/UMD/Google/USGS/NASA via Global Forest Watch"},
            {"id": "wdpa", "label": "Protected areas (WDPA)", "kind": "pending"},
            {"id": "fire", "label": "Active fire, last 5 days (NASA FIRMS VIIRS)", "kind": "points"}]},
        {"id": "evidence", "label": "Evidence & uncertainty", "layers": [
            {"id": "gaps", "label": "Survey gaps (cells without records)", "kind": "grid"},
            {"id": "extrapolation", "label": "Model extrapolation cells", "kind": "grid"}]},
    ]}


# ------------------------------------------------------------------ simulate
@app.get("/api/matrix/{mid}")
def matrix(mid: int):
    try:
        return hv.matrix_card(mid)
    except KeyError:
        raise HTTPException(404, "matrix not found")


@app.get("/api/studies")
def studies():
    return {"audited": [hv.compare(s["id"]) | {"id": s["id"]} for s in hv.STUDIES], "medicinal_studies": catalog.studies_index()}


@app.post("/api/simulate")
def simulate(body: SimRequest, request: Request):
    limit(request, "simulate", 60)
    t0 = time.time()
    try:
        if body.mode == "projection":
            out = sim.projection(body.matrix_id, body.horizon, body.n0)
        elif body.mode == "study":
            out = sim.study_comparison(body.study_id, body.horizon, body.n0)
        elif body.mode == "rotation":
            out = sim.rotation(body.study_id, body.treatment_id, body.rest_years, body.horizon, body.n0)
        else:
            out = sim.hypothetical(body.matrix_id, body.stages, body.fraction, body.horizon, body.n0)
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, f"simulation not possible: {e}")
    rid = store.create_run("simulation", f"simulate · {body.mode}", body.model_dump())
    store.add_event(rid, "_graph", "definition", {"nodes": [
        {"id": "gate", "label": "Evidence gate", "parents": []}, {"id": "model", "label": "Matrix projection", "parents": ["gate"]},
        {"id": "verify", "label": "Numerical check", "parents": ["model"]}]})
    store.add_event(rid, "gate", "completed", {"outputs": {"tier": out.get("tier")}, "why": f"mode {body.mode} → tier {out.get('tier')}"})
    store.add_event(rid, "model", "completed", {"outputs": {"mode": body.mode}, "duration_ms": round((time.time() - t0) * 1000, 1),
                                                "tool": "numpy eigen-analysis"})
    lam = out.get("matrix", {}).get("lambda")
    chk = out.get("matrix", {}).get("lambda_power_check")
    store.add_event(rid, "verify", "completed", {"outputs": {"lambda_eig": lam, "lambda_power": chk}})
    store.finish_run(rid, "completed", {"tier": out.get("tier")})
    return out | {"run_id": rid, "provenance": {"compadre_version": compadre.VERSION, "engine": "ethnoharvest.demography 1.0",
                                                "computed_ms": round((time.time() - t0) * 1000, 1)}}


class SyntheticRequest(BaseModel):
    stage_names: list[str] = Field(..., min_length=2, max_length=5)
    survival: list[float]
    growth: list[float]
    fecundity: float = Field(..., ge=0, le=1000)
    horizon: int = Field(30, ge=1, le=200)
    n0: list[float] | None = None


@app.post("/api/simulate/synthetic")
def simulate_synthetic(body: SyntheticRequest, request: Request):
    limit(request, "simulate", 60)
    try:
        out = sim.synthetic([s[:40] for s in body.stage_names], body.survival, body.growth, body.fecundity, body.horizon, body.n0)
    except ValueError as e:
        raise HTTPException(422, f"synthetic sandbox: {e}")
    return out


@app.post("/api/quota")
def quota(body: dict):
    return sim.quota_question(body.get("species", ""), body.get("local_evidence") or {})


# ------------------------------------------------------------------ plan
@app.post("/api/plan")
def plan(body: PlanRequest, request: Request):
    limit(request, "plan", 30)
    from . import habitat
    t0 = time.time()
    if body.intent == "evidence":
        out = planner.plan_evidence(body.species, body.budget, body.have, organ=body.organ)
    else:
        if not body.region:
            raise HTTPException(422, "survey/re-verification plans need a region")
        ctx = spatial.region_context(body.species, body.region.as_dict(), sensitive=True)
        suit = habitat.predict_cells(body.species, ctx["grid"])
        cells = planner.planning_units(ctx, suit, body.cost_params)
        out = planner.survey_with_baselines(cells, body.budget) if body.intent == "survey" else \
            planner.plan_reverification(cells, body.budget) | {"cells": cells}
        out["suitability_status"] = suit.get("status")
    rid = store.create_run("plan", f"plan · {body.intent} · {body.species}", body.model_dump())
    store.add_event(rid, "_graph", "definition", {"nodes": [
        {"id": "gate", "label": "Feasibility gate", "parents": []}, {"id": "units", "label": "Planning units", "parents": ["gate"]},
        {"id": "solver", "label": "ILP solver (CBC)", "parents": ["units"]}, {"id": "baselines", "label": "Baselines", "parents": ["units"]},
        {"id": "verify", "label": "Constraint check", "parents": ["solver", "baselines"]}]})
    for n in ("gate", "units", "solver", "baselines", "verify"):
        store.add_event(rid, n, "completed", {"outputs": {}, "tool": planner.SOLVER_VERSION if n == "solver" else None})
    store.finish_run(rid, "completed", {"intent": body.intent})
    return out | {"run_id": rid, "computed_ms": round((time.time() - t0) * 1000, 1), "request": body.model_dump()}


class SweepRequest(BaseModel):
    species: str
    region: Region
    budgets: list[float] = Field([2, 4, 6, 9, 12, 16, 20, 25], min_length=1, max_length=12)
    cost_params: dict[str, float] = {}


@app.post("/api/plan/sweep")
def plan_sweep(body: SweepRequest, request: Request):
    """Survey objective of the ILP and each baseline across budgets; one context build, one rate-limit unit."""
    limit(request, "plan", 30)
    from . import habitat
    if any(b < 1 or b > 500 for b in body.budgets):
        raise HTTPException(422, "budgets must be within 1-500")
    t0 = time.time()
    ctx = spatial.region_context(body.species, body.region.as_dict(), sensitive=True)
    cells = planner.planning_units(ctx, habitat.predict_cells(body.species, ctx["grid"]), body.cost_params)

    def obj(s):
        return None if s.get("status") == "unavailable" else round(10 * s["strata_covered"] + s["total_benefit"], 3)
    rows = []
    for b in sorted(body.budgets):
        r = planner.survey_with_baselines(cells, b)
        rows.append({"budget": b, "ilp": obj(r["optimal"]), **{k: obj(v) for k, v in r["baselines"].items()}})
    return {"rows": rows, "computed_ms": round((time.time() - t0) * 1000, 1)}


# ------------------------------------------------------------------ saved scenarios / plans / projects
@app.get("/api/items/{kind}")
def list_items(kind: Literal["scenario", "plan", "project", "scene"]):
    return {"items": store.list_items(kind)}


@app.post("/api/items/{kind}")
def save(kind: Literal["scenario", "plan", "project", "scene"], body: Item):
    return store.save_item(kind, body.name, body.body)


@app.put("/api/items/{kind}/{iid}")
def update(kind: Literal["scenario", "plan", "project", "scene"], iid: str, body: Item):
    if not store.get_item(iid):
        raise HTTPException(404)
    return store.save_item(kind, body.name, body.body, iid)


@app.delete("/api/items/{kind}/{iid}")
def delete(kind: str, iid: str):
    store.delete_item(iid)
    return {"deleted": iid}


# ------------------------------------------------------------------ evidence & intelligence
@app.get("/api/experiments")
def experiments():
    p = ROOT / "experiments" / "registry.json"
    return json.loads(p.read_text()) if p.exists() else {}


@app.get("/api/experiments/{eid}")
def experiment(eid: str):
    p = ROOT / "experiments" / "results" / f"{eid}.json"
    if not p.exists():
        raise HTTPException(404)
    return json.loads(p.read_text())


@app.get("/api/sources")
def sources():
    man = json.loads((ROOT / "data" / "raw" / "manifest.json").read_text())
    lit = ROOT / "docs" / "research" / "literature_values.json"
    od = ROOT / "docs" / "research" / "open_datasets.json"
    return {"manifest": man, "spatial_sources": spatial.SOURCES,
            "literature_values": json.loads(lit.read_text(encoding="utf8")) if lit.exists() else [],
            "open_datasets": json.loads(od.read_text(encoding="utf8")) if od.exists() else []}


@app.get("/api/report/{rid}", response_class=HTMLResponse)
def report(rid: str, fmt: Literal["html", "md", "json"] = "html"):
    r = store.get_run(rid)
    if not r:
        raise HTTPException(404)
    from .report import render
    md, html = render(r, store.events(rid), store.jev_for_run(rid))
    if fmt == "json":
        return JSONResponse(r | {"events": store.events(rid), "jev": store.jev_for_run(rid)},
                            headers={"Content-Disposition": f'attachment; filename="{rid}.json"'})
    if fmt == "md":
        return PlainTextResponse(md, headers={"Content-Disposition": f'attachment; filename="{rid}.md"'})
    return HTMLResponse(html)


# Hosted deployment: serve the built frontend from the same origin when FRONTEND_DIST is set (hash routing, so no
# SPA fallback is needed). Mounted last so every /api route above wins.
import os as _os  # noqa: E402
if _os.environ.get("FRONTEND_DIST") and Path(_os.environ["FRONTEND_DIST"]).is_dir():
    from fastapi.staticfiles import StaticFiles  # noqa: E402
    app.mount("/", StaticFiles(directory=_os.environ["FRONTEND_DIST"], html=True), name="frontend")
