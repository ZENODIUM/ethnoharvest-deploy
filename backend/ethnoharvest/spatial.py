"""Spatial acquisition & analysis for Explore/Plan.

Every function returns values with source, resolution and status. Nothing is
filled in when a provider fails; the layer gets status 'source temporarily
unavailable' instead. Results are cached on disk keyed by inputs.
"""
from __future__ import annotations

import os

import hashlib
import json
import math
import time
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
from shapely import geometry, validation
from shapely.geometry import shape, mapping, Point, box

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "cache"
WC_DIR = ROOT / "data" / "raw" / "worldclim" / "wc2.1_10m_bio"
WC_RES = 1 / 6  # 10 arc-minutes in degrees
MAX_AREA_KM2 = 2_500_000

BIOCLIM = {1: ("Annual mean temperature", "°C"), 4: ("Temperature seasonality (SD×100)", "°C×100"),
           5: ("Max temperature of warmest month", "°C"), 6: ("Min temperature of coldest month", "°C"),
           12: ("Annual precipitation", "mm"), 15: ("Precipitation seasonality (CV)", "%"),
           16: ("Precipitation of wettest quarter", "mm"), 17: ("Precipitation of driest quarter", "mm")}

SOURCES = {
    "gbif": {"name": "GBIF occurrence search API", "url": "https://www.gbif.org/", "licence": "per-record (CC0/CC-BY/CC-BY-NC)"},
    "worldclim": {"name": "WorldClim 2.1 bioclim, 10 arc-min, 1970-2000 normals", "url": "https://www.worldclim.org/data/worldclim21.html",
                  "citation": "Fick & Hijmans (2017) Int J Climatol 37:4302", "resolution": "10' (~18.5 km at equator)"},
    "power": {"name": "NASA POWER climatology (MERRA-2/CERES), 1981-2010 era", "url": "https://power.larc.nasa.gov/",
              "resolution": "0.5° x 0.625°"},
    "elevation": {"name": "Copernicus GLO-90 DEM via Open-Meteo elevation API", "url": "https://open-meteo.com/en/docs/elevation-api",
                  "resolution": "90 m"},
    "soil": {"name": "ISRIC SoilGrids 2.0", "url": "https://isric.org/explore/soilgrids", "resolution": "250 m"},
    "speciesplus": {"name": "CITES Species+ API", "url": "https://speciesplus.net/"},
    "firms": {"name": "NASA FIRMS active fire (VIIRS 375 m, NOAA-20, NOAA-21, Suomi-NPP; near real time)",
              "url": "https://firms.modaps.eosdis.nasa.gov/", "resolution": "375 m pixel",
              "citation": "NASA FIRMS, doi:10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002"},
}
FIRMS_SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT")
FIRE_DISPLAY_MAX = 2000
FIRMS_DAYS = 5  # FIRMS area API accepts 1-5 days


def _key(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _cached(kind: str, key: str, fn, ttl_days: float = 30):
    d = CACHE / kind
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{key}.json"
    if f.exists() and (time.time() - f.stat().st_mtime) < ttl_days * 86400:
        out = json.loads(f.read_text(encoding="utf8"))
        out["_cache"] = {"hit": True, "retrieved_utc": out.get("_retrieved_utc")}
        return out
    out = fn()
    out["_retrieved_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if out.get("status") in ("available", "ok"):
        f.write_text(json.dumps(out, default=str), encoding="utf8")
    out["_cache"] = {"hit": False, "retrieved_utc": out["_retrieved_utc"]}
    return out


# ------------------------------------------------------------------ geometry
def parse_region(region: dict) -> dict:
    """Accepts {'bbox':[w,s,e,n]} | GeoJSON geometry | {'point':[lon,lat],'radius_km':r}. Validates."""
    if "bbox" in region:
        w, s, e, n = map(float, region["bbox"])
        if w >= e or s >= n:
            raise ValueError("bbox must be [west, south, east, north] with west<east and south<north (antimeridian crossing unsupported)")
        geom = box(w, s, e, n)
    elif "point" in region:
        lon, lat = map(float, region["point"])
        r = float(region.get("radius_km", 25)) / 111.0
        geom = Point(lon, lat).buffer(r, 32)
    else:
        geom = shape(region.get("geometry", region))
    issues = []
    if not geom.is_valid:
        issues.append(f"invalid geometry repaired: {validation.explain_validity(geom)}")
        geom = validation.make_valid(geom)
    minx, miny, maxx, maxy = geom.bounds
    if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
        raise ValueError("coordinates outside WGS84 bounds")
    lat0 = (miny + maxy) / 2
    area = geom.area * (111.32 ** 2) * math.cos(math.radians(lat0))
    if area > MAX_AREA_KM2:
        raise ValueError(f"region too large ({area:,.0f} km² > {MAX_AREA_KM2:,} km²); choose a smaller area")
    if area < 1:
        issues.append("very small region: analyses limited by source resolution (WorldClim 10' cells ≈ 340 km²)")
    return {"geometry": geom, "geojson": mapping(geom), "bounds": [minx, miny, maxx, maxy], "area_km2": area,
            "issues": issues, "centroid": [geom.centroid.x, geom.centroid.y]}


def planning_grid(reg: dict, max_cells: int = 400) -> list[dict]:
    """Square cells no finer than WorldClim's native resolution; clipped to region."""
    minx, miny, maxx, maxy = reg["bounds"]
    span = max(maxx - minx, maxy - miny)
    size = max(WC_RES, span / math.sqrt(max_cells))
    size = math.ceil(size / WC_RES) * WC_RES  # multiple of native cell
    x0 = math.floor(minx / WC_RES) * WC_RES
    y0 = math.floor(miny / WC_RES) * WC_RES
    cells = []
    y = y0
    while y < maxy:
        x = x0
        while x < maxx:
            c = box(x, y, x + size, y + size)
            if c.intersects(reg["geometry"]):
                frac = c.intersection(reg["geometry"]).area / c.area
                cells.append({"id": f"c{len(cells)}", "bounds": [round(x, 5), round(y, 5), round(x + size, 5), round(y + size, 5)],
                              "center": [round(x + size / 2, 5), round(y + size / 2, 5)], "in_region_fraction": round(frac, 3)})
            x += size
        y += size
    return cells[: max_cells * 2]


# ------------------------------------------------------------------ WorldClim
@lru_cache(maxsize=32)
def _wc(var: int):
    import rasterio
    f = WC_DIR / f"wc2.1_10m_bio_{var}.tif"
    ds = rasterio.open(f)
    return ds, ds.read(1, masked=True)


def worldclim_at(points: list[tuple[float, float]], variables=tuple(BIOCLIM)) -> dict[int, list]:
    out = {}
    for v in variables:
        ds, arr = _wc(v)
        vals = []
        for lon, lat in points:
            r, c = ds.index(lon, lat)
            if 0 <= r < arr.shape[0] and 0 <= c < arr.shape[1] and not arr.mask[r, c]:
                vals.append(round(float(arr[r, c]), 3))
            else:
                vals.append(None)
        out[v] = vals
    return out


def worldclim_region(reg: dict) -> dict:
    import rasterio.features
    import rasterio.windows
    stats = {}
    for v, (label, unit) in BIOCLIM.items():
        ds, arr = _wc(v)
        win = rasterio.windows.from_bounds(*reg["bounds"], transform=ds.transform).round_offsets().round_lengths()
        win = rasterio.windows.Window(max(win.col_off, 0), max(win.row_off, 0), max(win.width, 1), max(win.height, 1))
        sub = ds.read(1, window=win, masked=True)
        tr = ds.window_transform(win)
        mask = rasterio.features.geometry_mask([reg["geojson"]], sub.shape, tr, invert=True, all_touched=True)
        vals = sub[mask & ~np.ma.getmaskarray(sub)].compressed() if np.ma.isMaskedArray(sub) else sub[mask]
        if vals.size == 0:
            stats[v] = {"label": label, "unit": unit, "status": "unsupported", "reason": "no land cells (ocean/no data)"}
            continue
        stats[v] = {"label": label, "unit": unit, "status": "available", "n_cells": int(vals.size),
                    "mean": round(float(vals.mean()), 2), "min": round(float(vals.min()), 2),
                    "max": round(float(vals.max()), 2), "p10": round(float(np.percentile(vals, 10)), 2),
                    "p90": round(float(np.percentile(vals, 90)), 2)}
    any_ok = any(v.get("status") == "available" for v in stats.values())
    return {"status": "available" if any_ok else "unsupported", "source": SOURCES["worldclim"], "variables": stats,
            **({} if any_ok else {"reason": "no WorldClim land cells in region (ocean or no-data)"})}


# ------------------------------------------------------------------ remote providers
def _http(method, url, attempts: int = 3, **kw):
    last = None
    for a in range(attempts):
        try:
            r = httpx.request(method, url, timeout=kw.pop("timeout", 30), **kw)
            if r.status_code == 429:
                time.sleep(1.5 * (a + 1))
                continue
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: PERF203
            last = e
            time.sleep(0.6 * (a + 1))
    raise RuntimeError(str(last)[:200])


def power_climatology(lon: float, lat: float) -> dict:
    def fetch():
        try:
            r = _http("GET", "https://power.larc.nasa.gov/api/temporal/climatology/point",
                      params={"parameters": "T2M,T2M_MAX,T2M_MIN,PRECTOTCORR", "community": "AG",
                              "longitude": round(lon, 4), "latitude": round(lat, 4), "format": "JSON"}, timeout=60)
            p = r.json()["properties"]["parameter"]
            months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
            return {"status": "available", "source": SOURCES["power"], "point": [lon, lat],
                    "monthly": {k: [p[k][m] for m in months] for k in p},
                    "annual": {k: p[k]["ANN"] for k in p},
                    "units": {"T2M": "°C", "T2M_MAX": "°C", "T2M_MIN": "°C", "PRECTOTCORR": "mm/day"}}
        except Exception as e:
            return {"status": "source temporarily unavailable", "source": SOURCES["power"], "error": str(e)}
    return _cached("power", _key(round(lon, 2), round(lat, 2)), fetch)


def elevation(points: list[tuple[float, float]]) -> dict:
    def fetch():
        try:
            vals = []
            for i in range(0, len(points), 100):
                chunk = points[i:i + 100]
                r = _http("GET", "https://api.open-meteo.com/v1/elevation",
                          params={"latitude": ",".join(f"{p[1]:.4f}" for p in chunk),
                                  "longitude": ",".join(f"{p[0]:.4f}" for p in chunk)})
                vals += r.json()["elevation"]
            return {"status": "available", "source": SOURCES["elevation"], "values": vals}
        except Exception as e:
            return {"status": "source temporarily unavailable", "source": SOURCES["elevation"], "error": str(e)}
    return _cached("elevation", _key([(round(a, 4), round(b, 4)) for a, b in points]), fetch)


def soil(lon: float, lat: float) -> dict:
    """SoilGrids REST is paused by ISRIC (verified timeout 2026-11-07); attempt once, report honestly."""
    def fetch():
        try:
            r = _http("GET", "https://rest.isric.org/soilgrids/v2.0/properties/query",
                      params={"lon": lon, "lat": lat, "property": ["phh2o", "soc", "clay"], "depth": ["0-5cm", "15-30cm"],
                              "value": "mean"}, timeout=8, attempts=1)
            return {"status": "available", "source": SOURCES["soil"], "data": r.json()}
        except Exception as e:
            return {"status": "source temporarily unavailable", "source": SOURCES["soil"],
                    "reason": "ISRIC SoilGrids REST API is paused/unresponsive; WCS route pending integration", "error": str(e)}
    return _cached("soil", _key(round(lon, 2), round(lat, 2)), fetch, ttl_days=1)


def gbif_taxon_key(name: str) -> int | None:
    r = _http("GET", "https://api.gbif.org/v1/species/match", params={"name": name, "kingdom": "Plantae"})
    d = r.json()
    return d.get("acceptedUsageKey") or d.get("usageKey")


BAD_ISSUES = {"ZERO_COORDINATE", "COORDINATE_INVALID", "COORDINATE_OUT_OF_RANGE", "COUNTRY_COORDINATE_MISMATCH",
              "PRESUMED_SWAPPED_COORDINATE", "PRESUMED_NEGATED_LATITUDE", "PRESUMED_NEGATED_LONGITUDE"}


def gbif_occurrences(name: str, reg: dict | None = None, max_records: int = 3000, sensitive: bool = False) -> dict:
    """Fetch + clean GBIF occurrences. Sensitive species are generalised to 0.1° (~11 km)."""
    bounds = reg["bounds"] if reg else None
    wkt = reg["geometry"].simplify(0.01).wkt if reg else None

    def fetch():
        try:
            key = gbif_taxon_key(name)
            if not key:
                return {"status": "unsupported", "reason": "name not resolved in GBIF backbone"}
            recs, off, total = [], 0, None
            while off < max_records:
                params = {"taxonKey": key, "hasCoordinate": "true", "limit": 300, "offset": off,
                          "occurrenceStatus": "PRESENT"}
                if wkt:
                    params["geometry"] = wkt
                d = _http("GET", "https://api.gbif.org/v1/occurrence/search", params=params, timeout=45).json()
                total = d.get("count", 0)
                recs += d.get("results", [])
                if d.get("endOfRecords", True):
                    break
                off += 300
            return {"status": "available", "taxon_key": key, "total_count": total, "raw": [
                {k: r.get(k) for k in ("key", "decimalLatitude", "decimalLongitude", "coordinateUncertaintyInMeters",
                                       "year", "basisOfRecord", "establishmentMeans", "countryCode", "issues",
                                       "datasetKey", "license", "institutionCode")} for r in recs]}
        except Exception as e:
            return {"status": "source temporarily unavailable", "error": str(e)}
    data = _cached("gbif", _key(name, bounds, max_records), fetch, ttl_days=14)
    if data.get("status") != "available":
        return data | {"source": SOURCES["gbif"]}
    flags = {"no_coordinate": 0, "uncertainty_gt_10km": 0, "issue_flag": 0, "cultivated_or_specimen": 0,
             "duplicate": 0, "fossil": 0}
    seen, clean = set(), []
    for r in data["raw"]:
        lat, lon = r.get("decimalLatitude"), r.get("decimalLongitude")
        if lat is None or lon is None:
            flags["no_coordinate"] += 1; continue
        if (r.get("coordinateUncertaintyInMeters") or 0) > 10000:
            flags["uncertainty_gt_10km"] += 1; continue
        if set(r.get("issues") or []) & BAD_ISSUES:
            flags["issue_flag"] += 1; continue
        if r.get("basisOfRecord") == "FOSSIL_SPECIMEN":
            flags["fossil"] += 1; continue
        if r.get("basisOfRecord") == "LIVING_SPECIMEN" or (r.get("establishmentMeans") or "").upper() in ("MANAGED", "INTRODUCED", "CULTIVATED"):
            flags["cultivated_or_specimen"] += 1; continue
        k = (round(lat, 3), round(lon, 3), r.get("year"))
        if k in seen:
            flags["duplicate"] += 1; continue
        seen.add(k)
        if sensitive:
            lat, lon = round(lat, 1), round(lon, 1)
        clean.append({"id": r["key"], "lat": lat, "lon": lon, "year": r.get("year"), "basis": r.get("basisOfRecord"),
                      "uncertainty_m": r.get("coordinateUncertaintyInMeters"), "country": r.get("countryCode"),
                      "license": r.get("license"), "gbif_url": f"https://www.gbif.org/occurrence/{r['key']}"})
    years = [c["year"] for c in clean if c["year"]]
    return {"status": "available", "source": SOURCES["gbif"], "taxon_key": data["taxon_key"],
            "total_in_gbif": data["total_count"], "fetched": len(data["raw"]), "clean_count": len(clean),
            "excluded": flags, "records": clean, "privacy": "generalised to 0.1°" if sensitive else "public precision",
            "year_range": [min(years), max(years)] if years else None,
            "truncated": data["total_count"] > len(data["raw"]), "_cache": data.get("_cache"),
            "caveat": "Presence records only: absence of records is not absence; records are not abundance."}


def cites_status(name: str) -> dict:
    from dotenv import dotenv_values
    tok = os.environ.get("SPECIESPLUS_TOKEN") or dotenv_values(ROOT / ".env.local").get("SPECIESPLUS_TOKEN")
    if not tok:
        return {"status": "pending", "reason": "Species+ token not configured"}

    def fetch():
        try:
            r = _http("GET", "https://api.speciesplus.net/api/v1/taxon_concepts", params={"name": name},
                      headers={"X-Authentication-Token": tok}, timeout=30)
            tcs = r.json().get("taxon_concepts", [])
            if not tcs:
                return {"status": "available", "listed": False, "note": "no Species+ record (not CITES-listed or name mismatch)"}
            tc = tcs[0]
            return {"status": "available", "listed": bool(tc.get("cites_listings")), "name": tc.get("full_name"),
                    "appendices": sorted({l.get("appendix") for l in tc.get("cites_listings", [])}),
                    "annotation": [l.get("annotation") for l in tc.get("cites_listings", []) if l.get("annotation")],
                    "url": f"https://speciesplus.net/species#/taxon_concepts/{tc.get('id')}/legal"}
        except Exception as e:
            return {"status": "source temporarily unavailable", "error": str(e)}
    out = _cached("speciesplus", _key(name), fetch, ttl_days=30)
    out["source"] = SOURCES["speciesplus"]
    out["caveat"] = "CITES regulates international trade; it does not grant or deny local harvesting permission."
    return out


def active_fire(bounds, days: int = FIRMS_DAYS) -> dict:
    """VIIRS active-fire detections in the region's bounding box over the last `days` days (NASA FIRMS area API).
    Zero detections is an observation, not missing data, but non-detection does not mean no fire (cloud, overpass timing)."""
    from dotenv import dotenv_values
    key = os.environ.get("NASA_FIRMS_MAP_KEY") or dotenv_values(ROOT / ".env.local").get("NASA_FIRMS_MAP_KEY")
    if not key:
        return {"status": "pending", "reason": "NASA FIRMS map key not available"}
    w, s, e, n = (round(float(v), 4) for v in bounds)

    def fetch():
        import csv
        import io
        recs, failed = [], []
        for src in FIRMS_SOURCES:
            try:
                r = httpx.get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{src}/{w},{s},{e},{n}/{days}", timeout=40)
                r.raise_for_status()
                if not r.text.startswith("latitude"):
                    raise RuntimeError("unexpected FIRMS response")
            except Exception:
                failed.append(src)  # never echo the URL: it contains the map key
                continue
            for row in csv.DictReader(io.StringIO(r.text)):
                recs.append({"lat": float(row["latitude"]), "lon": float(row["longitude"]), "date": row["acq_date"],
                             "time": row["acq_time"], "confidence": row.get("confidence"), "frp_mw": _fnum(row.get("frp")),
                             "satellite": row.get("satellite"), "daynight": row.get("daynight")})
        if len(failed) == len(FIRMS_SOURCES):
            return {"status": "unavailable", "reason": "NASA FIRMS request failed"}
        recs.sort(key=lambda x: (x["date"], x["time"]), reverse=True)
        return {"status": "available", "source": SOURCES["firms"], "days": days,
                "sources_queried": [x for x in FIRMS_SOURCES if x not in failed],
                "count": len(recs), "detections": recs,
                "caveat": "Satellite thermal anomalies (wildfire, agricultural or other burning). Non-detection does not prove "
                          "absence of fire (cloud cover, overpass timing, small or understory fires)."}
    return _cached("firms", _key(w, s, e, n, days, time.strftime("%Y%m%d%H")), fetch, ttl_days=3 / 24)


def _fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def region_context(name: str | None, region: dict, sensitive: bool = False) -> dict:
    """Full Explore analysis for a species x region. Layers report their own status."""
    reg = parse_region(region)
    lon, lat = reg["centroid"]
    cells = planning_grid(reg, max_cells=144)
    pts = [tuple(c["center"]) for c in cells]
    from concurrent.futures import ThreadPoolExecutor
    ex = ThreadPoolExecutor(6)
    f_el = ex.submit(elevation, pts)
    f_pw = ex.submit(power_climatology, lon, lat)
    f_so = ex.submit(soil, lon, lat)
    f_oc = ex.submit(gbif_occurrences, name, reg, 3000, sensitive) if name else None
    f_ci = ex.submit(cites_status, name) if name else None
    f_fi = ex.submit(active_fire, reg["bounds"])
    wc = worldclim_at(pts, (1, 12, 15))
    el = f_el.result()
    for i, c in enumerate(cells):
        c["bio1"], c["bio12"], c["bio15"] = wc[1][i], wc[12][i], wc[15][i]
        c["elevation_m"] = el["values"][i] if el.get("status") == "available" else None
    fire = dict(f_fi.result())
    if fire.get("status") == "available":
        # per-cell counts use every detection; only the list sent to the browser is capped
        for c in cells:
            bw, bs, be, bn = c["bounds"]
            c["fire_detections"] = sum(1 for d in fire["detections"] if bw <= d["lon"] < be and bs <= d["lat"] < bn)
        fire["truncated"] = len(fire["detections"]) > FIRE_DISPLAY_MAX
        fire["detections"] = fire["detections"][:FIRE_DISPLAY_MAX]
    layers = {
        "climate_normals": worldclim_region(reg),
        "monthly_climatology": f_pw.result(),
        "elevation": {k: v for k, v in el.items() if k != "values"} | {
            "summary": _summ([c["elevation_m"] for c in cells])} if el.get("status") == "available" else el,
        "soil": f_so.result(),
        "land_cover": {"status": "display-only", "source": {"name": "ESA WorldCover 10 m 2021 (WMS tiles)",
                                                            "url": "https://esa-worldcover.org/"},
                       "reason": "rendered as imagery on the globe; per-region class statistics not computed in this build"},
        "tree_cover_loss": {"status": "display-only", "source": {"name": "Hansen/UMD Global Forest Change (GFW tiles)",
                                                                 "url": "https://glad.umd.edu/dataset/global-2010-tree-cover-10-m"},
                            "reason": "imagery overlay only; loss is not medicinal-plant loss"},
        "protected_areas": {"status": "pending", "reason": "Protected Planet API token not available; WDPA statistics not computed"},
        "fire": fire,
        "iucn": {"status": "pending", "reason": "IUCN Red List API token not available"},
    }
    from . import checklists
    layers["native_range"] = checklists.region_overlap(name, reg["bounds"])
    if name:
        layers["occurrences"] = f_oc.result()
        layers["cites"] = f_ci.result()
    ex.shutdown(wait=False)
    return {"region": {"bounds": reg["bounds"], "area_km2": round(reg["area_km2"], 1), "centroid": reg["centroid"],
                       "issues": reg["issues"], "geojson": reg["geojson"]},
            "grid": cells, "grid_resolution_deg": cells[0]["bounds"][2] - cells[0]["bounds"][0] if cells else None,
            "layers": layers}


def _summ(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    return {"min": float(min(v)), "max": float(max(v)), "mean": round(float(np.mean(v)), 1), "n": len(v)}
