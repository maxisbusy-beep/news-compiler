"""Phase 3: fetch and dedupe with fixture feeds and a fake HTTP layer."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from pipeline import dedupe, fetch, run

from .conftest import fake_embed, fake_translate

FAKES = {"translate_fn": fake_translate, "embed_fn": fake_embed}

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc).timestamp()

OUTLETS = [
    {"id": "a", "name": "Outlet A", "feeds": ["https://a.example/feed"], "language": "en", "enabled": True},
    {"id": "wire", "name": "Wire News", "feeds": ["https://news.google.com/rss/search?q=site:wire.example"],
     "language": "en", "enabled": True, "via_google_news": True},
    {"id": "broken", "name": "Broken", "feeds": ["https://broken.example/feed"], "language": "en", "enabled": True},
    {"id": "cbc", "name": "Browser Only", "feeds": ["https://ua.example/feed"], "language": "en",
     "enabled": True, "fetch_ua": "browser"},
    {"id": "off", "name": "Disabled", "feeds": ["https://off.example/feed"], "language": "en", "enabled": False},
]


class Resp:
    def __init__(self, status, content=b"", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class FakeWeb:
    """Serves fixtures; honours ETags; records every request."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, headers=None, timeout=None):
        headers = headers or {}
        self.calls.append((url, dict(headers)))
        if "broken" in url:
            raise requests.ConnectionError("down")
        if "off.example" in url:
            raise AssertionError("disabled outlet must not be fetched")
        if "ua.example" in url:
            if "Mozilla" not in headers.get("User-Agent", ""):
                return Resp(403)
            return Resp(200, (FIX / "feed_a.xml").read_bytes().replace(b"outlet-a", b"outlet-ua"))
        if "a.example" in url:
            if headers.get("If-None-Match") == '"v1"':
                return Resp(304)
            return Resp(200, (FIX / "feed_a.xml").read_bytes(), {"ETag": '"v1"'})
        if "google" in url:
            return Resp(200, (FIX / "feed_google.xml").read_bytes())
        return Resp(404)


def test_parse_cleans_titles_and_clamps_time():
    items = fetch.parse_items((FIX / "feed_a.xml").read_bytes(), OUTLETS[0], "f", NOW)
    titles = [i["title"] for i in items]
    assert titles[0] == "Parliament passes budget after long debate"  # HTML stripped
    assert items[0]["summary"] == "Lawmakers approved the budget late on Friday."
    future = next(i for i in items if i["title"] == "Story stamped in the future")
    assert future["published"] == "2026-11-08T12:00:00Z"  # clamped to fetch time


def test_google_suffix_stripped_only_once():
    items = fetch.parse_items((FIX / "feed_google.xml").read_bytes(), OUTLETS[1], "f", NOW)
    assert [i["title"] for i in items] == [
        "Parliament passes budget after long debate",
        "Talks resume - in Geneva",
    ]


def test_canonical_url_strips_tracking():
    a = dedupe.canonical_url("http://www.Outlet-A.example/politics/budget-passes/?utm_source=rss&id=7#top")
    b = dedupe.canonical_url("https://outlet-a.example/politics/budget-passes?id=7")
    assert a == b == "https://outlet-a.example/politics/budget-passes?id=7"


def test_merge_dedupes_and_expires():
    web = FakeWeb()
    items, health, _ = fetch.fetch_all(OUTLETS, {}, NOW, get=web)
    kept, stats = dedupe.merge([], items, NOW)
    a_titles = [k["title"] for k in kept if k["outlet_id"] == "a"]
    # near-identical same-outlet title removed; >48h item expired
    assert "Parliament passes budget after a long debate" not in a_titles
    assert "Old story from three days ago" not in a_titles
    assert stats["dup_title"] >= 1 and stats["expired"] >= 1
    # same title from a different outlet is kept
    assert any(k["outlet_id"] == "wire" and k["title"].startswith("Parliament") for k in kept)
    assert dedupe.find_duplicates(kept) == []


def test_broken_feed_logged_not_fatal():
    web = FakeWeb()
    _, health, state = fetch.fetch_all(OUTLETS, {}, NOW, get=web)
    broken = next(h for h in health if h["outlet_id"] == "broken")
    assert broken["status"] == "error" and broken["error"] == "ConnectionError"
    # retried exactly once
    assert sum(1 for u, _ in web.calls if "broken" in u) == 2
    assert not any("off.example" in u for u, _ in web.calls)


def test_browser_ua_used_only_where_flagged():
    web = FakeWeb()
    _, health, _ = fetch.fetch_all(OUTLETS, {}, NOW, get=web)
    assert next(h for h in health if h["outlet_id"] == "cbc")["status"] == "ok"
    ua_a = next(h for u, h in web.calls if "a.example" in u and "ua." not in u)["User-Agent"]
    assert ua_a == fetch.BOT_UA


def test_conditional_get_stored_and_sent(tmp_path):
    outlets_path = tmp_path / "outlets.json"
    outlets_path.write_text(json.dumps(OUTLETS))
    web1 = FakeWeb()
    run.run(tmp_path, outlets_path, now=NOW, get=web1, **FAKES)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["feeds"]["https://a.example/feed"]["etag"] == '"v1"'

    web2 = FakeWeb()
    s2 = run.run(tmp_path, outlets_path, now=NOW + 1800, get=web2, **FAKES)
    sent = next(h for u, h in web2.calls if u == "https://a.example/feed")
    assert sent["If-None-Match"] == '"v1"'
    health = json.loads((tmp_path / "health.json").read_text())["feeds"]
    assert next(h for h in health if h["outlet_id"] == "a")["status"] == "not_modified"
    # items from the 304 feed are carried forward, not lost
    raw = json.loads((tmp_path / "raw.json").read_text())["items"]
    assert any(i["outlet_id"] == "a" for i in raw)
    assert s2["feeds_not_modified"] == 1


def test_two_runs_no_duplicates(tmp_path):
    outlets_path = tmp_path / "outlets.json"
    outlets_path.write_text(json.dumps(OUTLETS))
    s1 = run.run(tmp_path, outlets_path, now=NOW, get=FakeWeb(), **FAKES)
    raw1 = json.loads((tmp_path / "raw.json").read_text())["items"]
    s2 = run.run(tmp_path, outlets_path, now=NOW + 1800, get=FakeWeb(), **FAKES)
    raw2 = json.loads((tmp_path / "raw.json").read_text())["items"]
    assert s2["added"] == 0
    assert len(raw2) == len(raw1)
    assert {i["id"] for i in raw2} == {i["id"] for i in raw1}
    assert dedupe.find_duplicates(raw2) == []
    # first_seen survives the second run
    assert {i["id"]: i["first_seen"] for i in raw1} == {i["id"]: i["first_seen"] for i in raw2}


def test_real_outlets_file_loads_in_fetch():
    """Every enabled outlet in the real file has what fetch needs."""
    outlets = json.loads((Path(__file__).parents[1] / "pipeline" / "outlets.json").read_text())
    for o in outlets:
        assert {"id", "feeds", "language", "enabled"} <= set(o)
