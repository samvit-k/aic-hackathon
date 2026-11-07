import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geocoding  # noqa: E402
from geocoding import GeocodeError, QueryError, build_queries, parse_results, search_places  # noqa: E402

GEISEL = {"lat": "32.8811394", "lon": "-117.2375708", "display_name": "Geisel Library, San Diego",
          "category": "amenity", "type": "library"}


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeResp:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode()

    def read(self, _n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(geocoding, "_clock", clock)
    monkeypatch.setattr(geocoding, "_sleep", clock.sleep)
    monkeypatch.setattr(geocoding, "_cache", {})
    monkeypatch.setattr(geocoding, "_state",
                        {"last_request": float("-inf"), "suspended_until": float("-inf")})
    return clock


def install(monkeypatch, responses):
    """responses: list of payloads or exceptions, consumed in order. Returns call log."""
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResp(item)

    monkeypatch.setattr(geocoding.urllib.request, "urlopen", fake_urlopen)
    return calls


# ------------------------------ build_queries ------------------------------ #
def test_natural_language_prefix_and_at_split():
    assert build_queries("Outside Geisel Library at UCSD") == [
        "Geisel Library at UCSD, San Diego, California",
        "Geisel Library, San Diego, California",
    ]


@pytest.mark.parametrize("text,expected", [
    ("in front of the Price Center", "Price Center, San Diego, California"),
    ("next to 9500 Gilman Dr", "9500 Gilman Dr, San Diego, California"),
    ("  Third   Avenue,  Chula Vista ", "Third Avenue, Chula Vista, San Diego, California"),
])
def test_cleanup_and_context(text, expected):
    assert build_queries(text)[0] == expected


@pytest.mark.parametrize("text", ["Balboa Park, San Diego", "Main St, Escondido, CA",
                                  "1200 Third Ave 92101", "Pacific Hwy, California"])
def test_context_not_duplicated(text):
    assert build_queries(text) == [text]


@pytest.mark.parametrize("text", ["", "   ", "x" * 201])
def test_bad_queries_rejected(text):
    with pytest.raises(QueryError):
        build_queries(text)


# ------------------------------ parse_results ------------------------------ #
def test_parse_filters_bad_entries():
    data = [
        GEISEL,
        dict(GEISEL, lat="32.88114"),                    # duplicate point
        {"lat": "abc", "lon": "-117.2", "display_name": "bad"},
        {"lat": "40.7", "lon": "-74.0", "display_name": "New York"},  # outside area
        {"lat": "nan", "lon": "-117.2", "display_name": "NaN"},
        {"lat": "32.7", "lon": "-117.1"},                # no label
        "garbage",
    ]
    out = parse_results(data)
    assert len(out) == 1
    assert out[0].label == "Geisel Library, San Diego" and out[0].kind == "amenity library"
    assert out[0].lat == 32.881139


@pytest.mark.parametrize("data", [None, {}, "x", []])
def test_parse_non_list(data):
    assert parse_results(data) == []


# ------------------------------ search_places ------------------------------ #
def test_fallback_query_used_and_user_agent_sent(monkeypatch):
    calls = install(monkeypatch, [[], [GEISEL]])
    out = search_places("Outside Geisel Library at UCSD")
    assert [p.label for p in out] == ["Geisel Library, San Diego"]
    assert len(calls) == 2
    ua = calls[0].get_header("User-agent")
    assert ua.startswith("FixItSanDiego/") and "python" not in ua.lower()
    assert "bounded=1" in calls[0].full_url and "format=jsonv2" in calls[0].full_url


def test_no_match_returns_empty_not_invented(monkeypatch):
    install(monkeypatch, [[]])
    assert search_places("asdkjh qwe zzz") == []


def test_cache_prevents_repeat_requests(monkeypatch):
    calls = install(monkeypatch, [[GEISEL]])
    search_places("Geisel Library")
    search_places("  geisel   library ")
    assert len(calls) == 1


def test_empty_results_cached_too(monkeypatch):
    calls = install(monkeypatch, [[]])
    search_places("nowhere special")
    search_places("nowhere special")
    assert len(calls) == 1


def test_rate_limit_spacing(monkeypatch, fresh_state):
    install(monkeypatch, [[GEISEL], [GEISEL]])
    search_places("Geisel Library")
    search_places("Price Center")
    assert fresh_state.sleeps and fresh_state.sleeps[0] >= 1.0


def test_throttle_triggers_backoff_and_is_not_cached(monkeypatch, fresh_state):
    err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
    calls = install(monkeypatch, [err, [GEISEL]])
    with pytest.raises(GeocodeError):
        search_places("Geisel Library")
    with pytest.raises(GeocodeError):           # suspended: no network call
        search_places("Geisel Library")
    assert len(calls) == 1
    fresh_state.t += geocoding.BACKOFF_S + 1
    assert search_places("Geisel Library")      # error wasn't cached
    assert len(calls) == 2


def test_network_error_raises(monkeypatch):
    install(monkeypatch, [urllib.error.URLError("down")])
    with pytest.raises(GeocodeError):
        search_places("Geisel Library")


def test_custom_user_agent(monkeypatch):
    calls = install(monkeypatch, [[GEISEL]])
    search_places("Geisel Library", user_agent="MyTeamApp/1.0 (+https://example.org)")
    assert calls[0].get_header("User-agent") == "MyTeamApp/1.0 (+https://example.org)"
