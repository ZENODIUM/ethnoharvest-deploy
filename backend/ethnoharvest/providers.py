"""External AI/literature providers: JEV (TypeSafe System One), Groq, Gemini (fallback), Europe PMC, OpenAlex.

Keys are read server-side from .env.local / environment and never returned to
clients or written to logs. Every call returns latency and a sanitized record.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
_ENV = {**dotenv_values(ROOT / ".env.local"), **{k: v for k, v in os.environ.items() if k.endswith(("_KEY", "_MODEL", "_TOKEN"))}}
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_THRESHOLD = 0.85


def configured() -> dict:
    return {"jev": bool(_ENV.get("JEV_API_KEY")), "groq": bool(_ENV.get("GROQ_API_KEY")),
            "gemini": bool(_ENV.get("GEMINI_API_KEY")), "tavily": bool(_ENV.get("TAVILY_API_KEY")), "speciesplus": bool(_ENV.get("SPECIESPLUS_TOKEN")),
            "cesium": bool(_ENV.get("CESIUM_API_KEY")), "firms": bool(_ENV.get("NASA_FIRMS_MAP_KEY")), "groq_model": _ENV.get("GROQ_MODEL", "openai/gpt-oss-20b")}


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class ProviderError(RuntimeError):
    pass


def jev_choice(state: dict, instructions: str, criteria: dict[str, str], simulate_low_confidence: bool = False) -> dict:
    """Bounded JEV `choice`. Raises ProviderError when unavailable (caller must use a documented fallback)."""
    key = _ENV.get("JEV_API_KEY")
    if not key:
        raise ProviderError("JEV key not configured")
    t0 = time.time()
    try:
        r = httpx.post(JEV_URL, headers={"Authorization": f"Bearer {key}"}, timeout=25,
                       json={"model": "jev-latest", "state": state,
                             "questions": {"q": {"type": "choice", "instructions": instructions, "criteria": criteria}}})
    except httpx.HTTPError as e:
        raise ProviderError(f"JEV network error: {type(e).__name__}") from None
    lat = (time.time() - t0) * 1000
    if r.status_code != 200:
        raise ProviderError(f"JEV HTTP {r.status_code}")
    d = r.json()
    a = (d.get("answers") or {}).get("q") or {}
    if a.get("choice") not in criteria:
        raise ProviderError("JEV returned an invalid choice")
    conf = float(a.get("confidence", 0))
    if simulate_low_confidence:  # test hook: deterministic fault injection, labelled in trace
        conf = min(conf, 0.42)
    return {"choice": a["choice"], "confidence": conf, "probabilities": a.get("probabilities"),
            "model": d.get("model", "jev"), "latency_ms": round(lat, 1), "accepted": conf >= JEV_THRESHOLD,
            "threshold": JEV_THRESHOLD, "usage": d.get("usage")}


def groq_json(system: str, user: str, schema_hint: str, max_tokens: int = 900) -> dict:
    key = _ENV.get("GROQ_API_KEY")
    if not key:
        raise ProviderError("Groq key not configured")
    t0 = time.time()
    body = {"model": _ENV.get("GROQ_MODEL", "openai/gpt-oss-20b"), "temperature": 0.1,
            "max_tokens": max_tokens, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system + "\nRespond ONLY with JSON: " + schema_hint},
                         {"role": "user", "content": user}]}
    for attempt in range(3):
        try:
            r = httpx.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, timeout=45,
                           json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"Groq network error: {type(e).__name__}") from None
        if r.status_code == 200:
            break
        try:
            code = (r.json().get("error") or {}).get("code") or ""
        except ValueError:
            code = ""
        if attempt < 2 and r.status_code == 429:
            try:
                wait = float(r.headers.get("retry-after", "2"))
            except ValueError:
                wait = 2.0
            time.sleep(min(8.0, max(1.0, wait)))
            continue
        if attempt < 2 and code == "json_validate_failed":
            body["max_tokens"] = min(4000, body["max_tokens"] * 2)  # reasoning models can run out of room for the JSON
            continue
        raise ProviderError(f"Groq HTTP {r.status_code}{' ' + str(code)[:40] if code else ''}")
    d = r.json()
    txt = d["choices"][0]["message"].get("content") or "{}"
    try:
        out = json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise ProviderError("Groq returned non-JSON")
        out = json.loads(m.group(0))
    return {"data": out, "model": d.get("model"), "latency_ms": round((time.time() - t0) * 1000, 1),
            "usage": d.get("usage")}


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def gemini_json(system: str, user: str, schema_hint: str, max_tokens: int = 900) -> dict:
    """Gemini JSON call. The key goes in a header, never in the URL, so errors cannot echo it."""
    key = _ENV.get("GEMINI_API_KEY")
    if not key:
        raise ProviderError("Gemini key not configured")
    model = _ENV.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    t0 = time.time()
    body = {"systemInstruction": {"parts": [{"text": system + "\nRespond ONLY with JSON: " + schema_hint}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1, "maxOutputTokens": max(256, max_tokens)}}
    for attempt in range(3):
        try:
            r = httpx.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=45)
        except httpx.HTTPError as e:
            raise ProviderError(f"Gemini network error: {type(e).__name__}") from None
        if r.status_code == 200:
            break
        if attempt < 2 and r.status_code in (429, 500, 503):
            time.sleep(2 * (attempt + 1))
            continue
        raise ProviderError(f"Gemini HTTP {r.status_code}")
    d = r.json()
    try:
        txt = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise ProviderError("Gemini returned no content") from None
    try:
        out = json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise ProviderError("Gemini returned non-JSON")
        out = json.loads(m.group(0))
    return {"data": out, "model": f"gemini:{model}", "latency_ms": round((time.time() - t0) * 1000, 1),
            "usage": d.get("usageMetadata"), "provider": "gemini"}


def gemini_image(prompt: str, image: bytes, mime: str, model: str | None = None) -> dict:
    """Image-to-image edit with a Gemini image model (used to mark harvested parts on a botanical illustration).
    The key goes in a header; errors never echo it. Returns the first image part of the reply."""
    import base64
    key = _ENV.get("GEMINI_API_KEY")
    if not key:
        raise ProviderError("Gemini key not configured")
    model = model or _ENV.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
    t0 = time.time()
    body = {"contents": [{"role": "user", "parts": [{"text": prompt},
                                                     {"inlineData": {"mimeType": mime, "data": base64.b64encode(image).decode()}}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"], "temperature": 0.2}}
    for attempt in range(3):
        try:
            r = httpx.post(GEMINI_URL.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=180)
        except httpx.HTTPError as e:
            raise ProviderError(f"Gemini network error: {type(e).__name__}") from None
        if r.status_code == 200:
            break
        if attempt < 2 and r.status_code in (429, 500, 503):
            time.sleep(4 * (attempt + 1))
            continue
        raise ProviderError(f"Gemini HTTP {r.status_code}")
    d = r.json()
    parts = ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    img = next((p["inlineData"] for p in parts if p.get("inlineData", {}).get("data")), None)
    if not img:
        raise ProviderError("Gemini returned no image")
    note = " ".join(p.get("text", "") for p in parts if p.get("text"))[:400]
    return {"image": base64.b64decode(img["data"]), "mime": img.get("mimeType", "image/png"), "model": f"gemini:{model}",
            "note": note, "latency_ms": round((time.time() - t0) * 1000, 1), "provider": "gemini"}


def llm_json(system: str, user: str, schema_hint: str, max_tokens: int = 900, prefer: str = "groq") -> dict:
    """Groq first, Gemini on any Groq failure (or the reverse with prefer='gemini'). Raises only if both fail."""
    order = [groq_json, gemini_json] if prefer == "groq" else [gemini_json, groq_json]
    errors = []
    for fn in order:
        try:
            out = fn(system, user, schema_hint, max_tokens)
            out.setdefault("provider", "groq" if fn is groq_json else "gemini")
            if errors:
                out["fallback_from"] = errors
            return out
        except ProviderError as e:
            errors.append(str(e))
    raise ProviderError(" / ".join(errors))


def openalex(query: str, n: int = 8) -> dict:
    """OpenAlex works search (open, no key; shared daily budget). Abstracts rebuilt from inverted index."""
    t0 = time.time()
    q = re.sub(r'["()*]|\bAND\b|\bOR\b', " ", query)
    q = re.sub(r"\s+", " ", q).strip()
    try:
        r = httpx.get("https://api.openalex.org/works", timeout=30,
                      params={"search": q, "per-page": n, "select": "id,doi,title,publication_year,abstract_inverted_index,authorships,primary_location,open_access"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderError(f"OpenAlex unavailable: {type(e).__name__}") from None
    d = r.json()
    recs = []
    for w in d.get("results", []):
        inv = w.get("abstract_inverted_index") or {}
        pos = sorted((p, word) for word, ps in inv.items() for p in ps)
        recs.append({"id": w["id"].rsplit("/", 1)[-1], "source": "OpenAlex", "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                     "title": w.get("title") or "", "year": w.get("publication_year"),
                     "journal": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
                     "authors": ", ".join(a["author"]["display_name"] for a in (w.get("authorships") or [])[:4]),
                     "abstract": " ".join(wd for _, wd in pos)[:1800],
                     "url": w.get("doi") or w["id"], "open_access": (w.get("open_access") or {}).get("is_oa")})
    return {"hit_count": d.get("meta", {}).get("count", 0), "records": recs, "query": q,
            "latency_ms": round((time.time() - t0) * 1000, 1), "provider": "OpenAlex"}


def europepmc(query: str, n: int = 8, simple_query: str | None = None) -> dict:
    """Live search with retries; on outage serve the last successful snapshot, clearly labelled."""
    t0 = time.time()
    cache = ROOT / "data" / "cache" / "europepmc"
    cache.mkdir(parents=True, exist_ok=True)
    cf = cache / f"{digest([query, n])}.json"
    d, err = None, None
    for q, timeout in [(query, 10)]:
        try:
            r = httpx.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                          params={"query": q, "format": "json", "pageSize": n, "resultType": "core"}, timeout=timeout)
            r.raise_for_status()
            d = r.json()
            break
        except httpx.HTTPError as e:
            err = type(e).__name__
    mode = "live"
    if d is None:
        try:
            alt = openalex(simple_query or query, n)
            alt["mode"] = f"live OpenAlex fallback (Europe PMC unavailable: {err})"
            return alt
        except ProviderError:
            pass
        if not cf.exists():
            raise ProviderError(f"Europe PMC unavailable: {err}")
        snap = json.loads(cf.read_text(encoding="utf8"))
        d, mode = snap["data"], f"cached snapshot from {snap['retrieved_utc']} (live service unavailable: {err})"
    else:
        cf.write_text(json.dumps({"retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "data": d}), encoding="utf8")
    recs = []
    for x in d.get("resultList", {}).get("result", []):
        recs.append({"id": x.get("id"), "source": x.get("source"), "pmid": x.get("pmid"), "doi": x.get("doi"),
                     "title": re.sub("<[^>]+>", "", x.get("title", "")), "year": x.get("pubYear"),
                     "journal": (x.get("journalInfo") or {}).get("journal", {}).get("title"),
                     "authors": x.get("authorString", "")[:160],
                     "abstract": re.sub("<[^>]+>", "", x.get("abstractText", "") or "")[:1800],
                     "url": f"https://europepmc.org/article/{x.get('source')}/{x.get('id')}",
                     "open_access": x.get("isOpenAccess") == "Y"})
    return {"hit_count": d.get("hitCount", 0), "records": recs, "latency_ms": round((time.time() - t0) * 1000, 1),
            "query": query, "mode": mode}
