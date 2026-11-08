"""Licensed species photographs with provenance.

Provider order: local cache -> iNaturalist taxon photos -> GBIF occurrence media -> Wikimedia Commons
(-> Google Programmable Search only if GOOGLE_CSE_KEY and GOOGLE_CSE_ID are configured; otherwise reported pending).

Only openly reusable licences are accepted (CC0, public domain, CC BY, CC BY-SA). Matching is by accepted
scientific name, never by loose string similarity. Thumbnails are downloaded once and served from our own
origin (/api/media/{id}) so the browser never loads arbitrary third-party URLs. If nothing qualifies, the
caller gets status "none" and must show an illustrative model, labelled as such - never a lookalike photo.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path

import httpx

from . import store, taxonomy

ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = ROOT / "data" / "cache" / "media"
TTL_S = 30 * 86400
MAX_BYTES = 2_500_000
UA = {"User-Agent": "EthnoHarvestAI/2.0 (research prototype) python-httpx"}


def _commons_ua() -> dict | None:
    """Wikimedia requires a contact URL or email in the User-Agent; it is configured, never invented."""
    from dotenv import dotenv_values
    contact = dotenv_values(ROOT / ".env.local").get("MEDIA_CONTACT_URL")
    return {"User-Agent": f"EthnoHarvestAI/2.0 ({contact}) python-httpx"} if contact else None
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS species_media (
  id TEXT PRIMARY KEY, query TEXT, accepted_name TEXT, taxon_ref TEXT, source TEXT, photographer TEXT,
  original_url TEXT, attribution_url TEXT, licence TEXT, licence_url TEXT, attribution TEXT, retrieved REAL,
  taxonomic_confidence TEXT, review_status TEXT, cache_path TEXT, mime TEXT, status TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS media_q ON species_media(query);
"""
_init_done = False
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _init():
    global _init_done
    if not _init_done:
        with store.conn() as c:
            c.executescript(SCHEMA)
        _init_done = True


class PendingProvider(RuntimeError):
    pass


def normalise_licence(raw: str | None) -> tuple[str | None, str | None]:
    """Map provider licence strings to (label, url). Returns (None, None) when not openly reusable."""
    if not raw:
        return None, None
    s = raw.strip().lower().replace("_", "-")
    url = re.search(r"creativecommons\.org/(licenses|publicdomain)/([a-z0-9-]+)(?:/(\d\.\d))?", s)
    if url:
        kind, code, ver = url.group(1), url.group(2), url.group(3)
        if kind == "publicdomain":
            if code == "zero":
                return "CC0", "https://creativecommons.org/publicdomain/zero/1.0/"
            return "Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"
    else:
        tok = re.search(r"(cc0|cc[- ]?by(?:[- ](?:sa|nc|nd))*|public[- ]domain|\bpdm\b)(?:[- ](\d[.-]\d))?", s)
        if not tok:
            return None, None
        t = tok.group(1).replace(" ", "-")
        if t == "cc0":
            return "CC0", "https://creativecommons.org/publicdomain/zero/1.0/"
        if t.startswith("public") or t == "pdm":
            return "Public domain", "https://creativecommons.org/publicdomain/mark/1.0/"
        code = re.sub(r"^cc-?", "", t)
        ver = (tok.group(2) or "").replace("-", ".") or None
    parts = code.split("-")
    if parts[0] != "by" or "nc" in parts or "nd" in parts:
        return None, None
    code = "by-sa" if "sa" in parts else "by"
    if not ver:  # the provider gave no version; do not assume one
        return f"CC {code.upper()} (version unspecified)", "https://creativecommons.org/licenses/"
    return f"CC {code.upper()} {ver}", f"https://creativecommons.org/licenses/{code}/{ver}/"


def _accepted(name: str) -> tuple[str, str]:
    try:
        r = taxonomy.resolve(name)
        acc = r.get("accepted") or name
        if len(acc.split()) < 2:  # resolved above species rank (e.g. "Plantae"): never fetch a photo for a higher taxon
            return name, "not resolved to a species"
        conf = "accepted-name match" if r.get("status") in (None, "ACCEPTED", "accepted") else f"resolved via {r.get('status')}"
        return acc, conf
    except Exception:
        return name, "name as entered (taxonomy service unavailable)"


def _same_species(a: str | None, b: str) -> bool:
    if not a:
        return False
    tok = lambda x: re.sub(r"[^a-z ]", " ", x.lower()).split()[:2]  # noqa: E731
    return len(tok(a)) == 2 and tok(a) == tok(b)  # binomial match only


# ------------------------------------------------------------------ providers (each returns candidate dicts)
def _inat(name: str) -> list[dict]:
    r = httpx.get("https://api.inaturalist.org/v1/taxa", params={"q": name, "per_page": 5}, headers=UA, timeout=15)
    r.raise_for_status()
    out = []
    for t in r.json().get("results", []):
        if not _same_species(t.get("name"), name):
            continue
        d = httpx.get(f"https://api.inaturalist.org/v1/taxa/{t['id']}", headers=UA, timeout=15).json()["results"][0]
        photos = [tp["photo"] for tp in d.get("taxon_photos", [])] or ([t["default_photo"]] if t.get("default_photo") else [])
        for p in photos[:8]:
            out.append({"source": "iNaturalist", "taxon_ref": f"inat:{t['id']}", "licence_raw": p.get("license_code"),
                        "image_url": p.get("medium_url") or p.get("url"), "attribution": p.get("attribution"),
                        "photographer": (p.get("attribution") or "").split(",")[0].replace("(c)", "").strip() or None,
                        "attribution_url": f"https://www.inaturalist.org/photos/{p.get('id')}", "matched_name": t.get("name")})
    return out


def _gbif(name: str) -> list[dict]:
    m = httpx.get("https://api.gbif.org/v1/species/match", params={"name": name}, headers=UA, timeout=15).json()
    key = m.get("usageKey") if m.get("matchType") in ("EXACT", "FUZZY") and m.get("rank") in ("SPECIES", "SUBSPECIES", "VARIETY") else None
    if not key or not _same_species(m.get("canonicalName"), name):
        return []
    r = httpx.get("https://api.gbif.org/v1/occurrence/search", headers=UA, timeout=20, params={
        "taxonKey": key, "mediaType": "StillImage", "limit": 10, "license": ["CC0_1_0", "CC_BY_4_0"]})
    out = []
    for o in r.json().get("results", []):
        for md in o.get("media", [])[:1]:
            if md.get("type") != "StillImage" or not md.get("identifier"):
                continue
            out.append({"source": "GBIF", "taxon_ref": f"gbif:{key}", "licence_raw": md.get("license") or o.get("license"),
                        "image_url": md["identifier"], "photographer": md.get("creator") or md.get("rightsHolder"),
                        "attribution": f"{md.get('creator') or md.get('rightsHolder') or 'unknown'} via GBIF occurrence {o.get('key')}",
                        "attribution_url": f"https://www.gbif.org/occurrence/{o.get('key')}", "matched_name": o.get("species")})
    return out


def _commons(name: str) -> list[dict]:
    ua = _commons_ua()
    if not ua:
        raise PendingProvider("pending: set MEDIA_CONTACT_URL (Wikimedia User-Agent policy)")
    r = httpx.get("https://commons.wikimedia.org/w/api.php", headers=ua, timeout=15, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f'"{name}" filetype:bitmap',
        "gsrnamespace": 6, "gsrlimit": 8, "prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": 480})
    out = []
    for p in (r.json().get("query", {}).get("pages", {}) or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        title = p.get("title", "")
        if name.lower() not in title.lower().replace("_", " "):
            continue  # require the binomial in the file title, not just anywhere in the page
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
        out.append({"source": "Wikimedia Commons", "taxon_ref": None,
                    "licence_raw": (meta.get("LicenseShortName") or {}).get("value"),
                    "image_url": ii.get("thumburl") or ii.get("url"), "photographer": artist or None,
                    "attribution": f"{artist or 'unknown author'}, {title.replace('File:', '')}, Wikimedia Commons",
                    "attribution_url": ii.get("descriptionurl"), "matched_name": name})
    return out


PROVIDERS = [("iNaturalist", _inat), ("GBIF", _gbif), ("Wikimedia Commons", _commons)]


def _smaller(url: str) -> str:
    """Ask known hosts for a medium rendition instead of the original."""
    url = re.sub(r"(inaturalist-open-data\.s3\.amazonaws\.com/photos/\d+/)original\.", r"\1medium.", url)
    url = re.sub(r"(static\.inaturalist\.org/photos/\d+/)original\.", r"\1medium.", url)
    return url.replace("bs.plantnet.org/image/o/", "bs.plantnet.org/image/m/")


def _download(url: str) -> tuple[bytes, str]:
    url = _smaller(url or "")
    if not url or not url.startswith("https://"):
        raise ValueError("only https image URLs are fetched")
    with httpx.stream("GET", url, headers=UA, timeout=20, follow_redirects=True) as r:
        r.raise_for_status()
        mime = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if mime not in IMAGE_TYPES:
            raise ValueError(f"not an accepted image type: {mime or 'unknown'}")
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError("image too large")
    return bytes(buf), mime


def _row_public(row) -> dict:
    d = dict(row)
    if d.get("status") == "ok":
        d["url"] = f"/api/media/{d['id']}"
    for k in ("cache_path", "query"):
        d.pop(k, None)
    return d


CURATED_DIR = ROOT / "data" / "curated" / "media"
_curated_cache: dict = {}


def curated() -> dict:
    """Hand-picked images (scripts/curate_apply.py): {"parts": [...], "species": {name: {"photo", "plate"}}}; {} if absent."""
    f = CURATED_DIR / "index.json"
    if not f.exists():
        return {}
    mtime = f.stat().st_mtime
    if _curated_cache.get("mtime") != mtime:
        _curated_cache.update(mtime=mtime, data=json.loads(f.read_text(encoding="utf-8")))
    return _curated_cache["data"]


def curated_public(rec: dict) -> dict:
    return {**rec, "src": f"/api/media/{rec['id']}", "url": f"/api/media/{rec['id']}"}


def _curated_species(q: str) -> dict | None:
    sp = next((v for k, v in curated().get("species", {}).items() if k.lower() == q.lower()), None)
    if sp is None:
        return None
    ph = sp.get("photo")
    if not ph:
        return {"status": "none", "query": q, "accepted_name": q, "cache": "curated",
                "reason": "no openly licensed photo of this exact species was found when images were checked by hand"}
    return {"status": "ok", "id": ph["id"], "url": f"/api/media/{ph['id']}", "accepted_name": q, "source": ph["source"],
            "photographer": ph["creator"], "attribution_url": ph["landing"], "licence": ph["licence"], "licence_url": ph["licence_url"],
            "attribution": f"{ph['title'] or 'Photo'} by {ph['creator']} ({ph['licence']})", "taxonomic_confidence": "checked by eye",
            "review_status": ph["review"], "cache": "curated"}


def species_image(name: str, refresh: bool = False) -> dict:
    """Return one verified, openly licensed photo record for the species, or status 'none' with the reasons."""
    _init()
    q = " ".join(name.split()).strip()
    cur = _curated_species(q)
    if cur:
        return cur
    key = q.lower()
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:  # de-duplicates concurrent requests for the same species
        with store.conn() as c:
            row = c.execute("SELECT * FROM species_media WHERE query=? ORDER BY retrieved DESC LIMIT 1", (key,)).fetchone()
        if row and not refresh and ((row["status"] == "ok" and Path(row["cache_path"] or "").exists())
                                    or (row["status"] != "ok" and time.time() - row["retrieved"] < TTL_S)):
            out = _row_public(row)
            out["cache"] = "hit"
            return out
        accepted, conf = _accepted(q)
        if conf == "not resolved to a species" or len(accepted.split()) < 2:
            return {"status": "none", "query": q, "reason": "name is not resolved to a species, so no photo is shown"}
        tried, rejected = [], 0
        for pname, fn in PROVIDERS:
            try:
                cands = fn(accepted)
                tried.append(f"{pname}: {len(cands)} candidates")
            except PendingProvider as e:
                tried.append(f"{pname}: {e}")
                continue
            except Exception as e:
                tried.append(f"{pname}: unavailable ({type(e).__name__})")
                continue
            for cand in cands:
                lic, lic_url = normalise_licence(cand.get("licence_raw"))
                if not lic or not _same_species(cand.get("matched_name"), accepted):
                    rejected += 1
                    continue
                try:
                    data, mime = _download(cand["image_url"])
                except Exception:
                    rejected += 1
                    continue
                mid = "m_" + hashlib.sha256((cand["image_url"] or "").encode()).hexdigest()[:20]
                MEDIA_DIR.mkdir(parents=True, exist_ok=True)
                path = MEDIA_DIR / f"{mid}{IMAGE_TYPES[mime]}"
                path.write_bytes(data)
                rec = {"id": mid, "query": key, "accepted_name": accepted, "taxon_ref": cand.get("taxon_ref"),
                       "source": pname, "photographer": cand.get("photographer"), "original_url": cand["image_url"],
                       "attribution_url": cand.get("attribution_url"), "licence": lic, "licence_url": lic_url,
                       "attribution": cand.get("attribution"), "retrieved": time.time(),
                       "taxonomic_confidence": conf if pname != "Wikimedia Commons" else f"{conf}; binomial in file title (unreviewed)",
                       "review_status": "auto-accepted (licence and name checks); not expert-reviewed",
                       "cache_path": str(path), "mime": mime, "status": "ok", "reason": None}
                with store.conn() as c:
                    c.execute(f"INSERT OR REPLACE INTO species_media ({','.join(rec)}) VALUES ({','.join('?' * len(rec))})",
                              tuple(rec.values()))
                out = _row_public(rec)
                out["cache"], out["providers_tried"] = "miss", tried
                return out
        reason = f"no openly licensed photo matched the accepted name ({rejected} candidates rejected)"
        rec = {"id": "none_" + hashlib.sha256(key.encode()).hexdigest()[:12], "query": key, "accepted_name": accepted,
               "retrieved": time.time(), "status": "none", "reason": reason, "taxonomic_confidence": conf}
        if any("unavailable" in t for t in tried) and not any("candidates" in t and not t.endswith(": 0 candidates") for t in tried):
            rec["retrieved"] = time.time() - TTL_S + 3600  # provider outage: retry after an hour, not a month
        with store.conn() as c:
            c.execute(f"INSERT OR REPLACE INTO species_media ({','.join(rec)}) VALUES ({','.join('?' * len(rec))})",
                      tuple(rec.values()))
        return {**_row_public(rec), "cache": "miss", "providers_tried": tried,
                "google": "pending (GOOGLE_CSE_KEY / GOOGLE_CSE_ID not configured)"}


def media_file(mid: str) -> tuple[Path, str] | None:
    if re.fullmatch(r"cu-[0-9a-f]{16}", mid):
        p = CURATED_DIR / "files" / f"{mid}.jpg"
        return (p, "image/jpeg") if p.exists() else None
    if not re.fullmatch(r"m_[0-9a-f]{20}", mid):
        return None
    _init()
    with store.conn() as c:
        row = c.execute("SELECT cache_path, mime FROM species_media WHERE id=? AND status='ok'", (mid,)).fetchone()
    if not row or not Path(row["cache_path"]).exists():
        return None
    p = Path(row["cache_path"]).resolve()
    if MEDIA_DIR.resolve() not in p.parents:
        return None
    return p, row["mime"]
