"""Place/address search via OpenStreetMap Nominatim.

Follows the Nominatim usage policy (https://operations.osmfoundation.org/policies/nominatim/):
- at most one request per ~second for the whole app process (shared lock),
- an identifying User-Agent (not a stock library UA),
- results cached, errors not cached, back-off after throttling/server errors,
- user-triggered searches only (no autocomplete), and a kill switch in the caller.

Never invents coordinates: no match -> empty list.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import NamedTuple, Optional

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "FixItSanDiego/0.1 (+https://github.com/samvit-k/aic-hackathon)"
# San Diego County (approx.): west, north, east, south
VIEWBOX = (-117.60, 33.51, -116.08, 32.53)
CONTEXT_SUFFIX = ", San Diego, California"
MAX_QUERY_CHARS = 200
MAX_RESULTS = 5
MIN_INTERVAL_S = 1.1
CACHE_TTL_S = 24 * 3600
CACHE_MAX_ENTRIES = 256
BACKOFF_S = 60
TIMEOUT_S = 10


class Place(NamedTuple):
    label: str
    lat: float
    lon: float
    kind: str


class GeocodeError(RuntimeError):
    """Service unavailable / throttled / bad response."""


class QueryError(ValueError):
    """The user's search text can't be used."""


_PREFIX_RE = re.compile(
    r"^(?:right\s+|just\s+)?"
    r"(?:outside(?:\s+of)?|in\s+front\s+of|near|next\s+to|across\s+from|behind|beside|by|opposite)"
    r"(?:\s+the)?\s+",
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r"\s+(?:at|near)\s+", re.IGNORECASE)
_HAS_CONTEXT_RE = re.compile(r"san\s+diego|california|\bca\b|\b9[12]\d{3}\b", re.IGNORECASE)

# Shared across all sessions in this process (Streamlit runs one process).
_lock = threading.Lock()
_state = {"last_request": float("-inf"), "suspended_until": float("-inf")}
_cache: dict[str, tuple[float, list[Place]]] = {}
_clock = time.monotonic  # patchable in tests
_sleep = time.sleep


def _normalize(text: str) -> str:
    return " ".join(str(text or "").split())


def _with_context(text: str) -> str:
    return text if _HAS_CONTEXT_RE.search(text) else text + CONTEXT_SUFFIX


def build_queries(text: str) -> list[str]:
    """Turn a natural-language description into at most two Nominatim queries."""
    t = _normalize(text)
    if not t:
        raise QueryError("Enter a place or address to search.")
    if len(t) > MAX_QUERY_CHARS:
        raise QueryError(f"Please shorten the search to {MAX_QUERY_CHARS} characters or fewer.")
    cleaned = _PREFIX_RE.sub("", t).strip(" ,.") or t
    queries = [_with_context(cleaned)]
    parts = _SPLIT_RE.split(cleaned, maxsplit=1)
    if len(parts) == 2:
        head = parts[0].strip(" ,.")
        if head:
            q2 = _with_context(head)
            if q2 not in queries:
                queries.append(q2)
    return queries


def parse_results(data) -> list[Place]:
    """Validate untrusted Nominatim JSON; drop anything malformed or outside the area."""
    if not isinstance(data, list):
        return []
    west, north, east, south = VIEWBOX
    out: list[Place] = []
    for item in data[:20]:
        if not isinstance(item, dict):
            continue
        try:
            lat, lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(lat) and math.isfinite(lon)):
            continue
        if not (south <= lat <= north and west <= lon <= east):
            continue
        label = _normalize(item.get("display_name"))[:200]
        if not label:
            continue
        if any(abs(p.lat - lat) < 1e-4 and abs(p.lon - lon) < 1e-4 for p in out):
            continue
        kind = " ".join(str(item.get(k) or "") for k in ("category", "type")).strip()
        out.append(Place(label, round(lat, 6), round(lon, 6), kind))
        if len(out) >= MAX_RESULTS:
            break
    return out


def _cache_get(key: str) -> Optional[list[Place]]:
    hit = _cache.get(key)
    if hit and _clock() - hit[0] < CACHE_TTL_S:
        return hit[1]
    return None


def _cache_put(key: str, value: list[Place]) -> None:
    if key not in _cache and len(_cache) >= CACHE_MAX_ENTRIES:
        _cache.pop(next(iter(_cache)))
    _cache[key] = (_clock(), value)


def _fetch(query: str, user_agent: str) -> list[Place]:
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": MAX_RESULTS,
        "countrycodes": "us",
        "viewbox": ",".join(str(v) for v in VIEWBOX),
        "bounded": 1,
        "accept-language": "en",
    }
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}",
        headers={"User-Agent": user_agent, "Accept-Language": "en"},
    )
    with _lock:  # serializes all sessions -> app-wide rate limit
        now = _clock()
        if now < _state["suspended_until"]:
            raise GeocodeError("Location search is paused after a service error.")
        wait = _state["last_request"] + MIN_INTERVAL_S - now
        if wait > 0:
            _sleep(wait)
        _state["last_request"] = _clock()
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as resp:
                body = resp.read(1_000_000)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429) or exc.code >= 500:
                _state["suspended_until"] = _clock() + BACKOFF_S
            raise GeocodeError(f"Location search failed (HTTP {exc.code}).") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GeocodeError("Could not reach the location search service.") from None
    try:
        return parse_results(json.loads(body))
    except (ValueError, TypeError):
        raise GeocodeError("The location search service returned an unreadable response.") from None


def search_places(text: str, user_agent: Optional[str] = None) -> list[Place]:
    """Resolve a description to up to five candidate places (possibly none)."""
    ua = (user_agent or "").strip() or DEFAULT_USER_AGENT
    for query in build_queries(text):
        key = query.lower()
        results = _cache_get(key)
        if results is None:
            results = _fetch(query, ua)
            _cache_put(key, results)  # empty results cached too; errors raise before this
        if results:
            return results
    return []
