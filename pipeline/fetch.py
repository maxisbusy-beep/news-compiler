"""Step 1: fetch every enabled outlet's feeds.

Sends conditional GET headers from the previous run, retries once, and never
lets one broken feed fail the run. Returns raw items plus per-feed health and
the updated conditional-GET state.
"""
from __future__ import annotations

import hashlib
import html
import re
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

import feedparser
import requests

BOT_UA = "NewsCompiler/1.0 (+https://maxisbusy-beep.github.io/news-compiler)"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
TIMEOUT = 15
SUMMARY_MAX = 500  # characters of RSS description kept as model input (never shown)

Getter = Callable[..., "requests.Response"]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(_TAG.sub(" ", s))
    return _WS.sub(" ", s).strip()


def strip_source_suffix(title: str, source: str | None) -> str:
    """Google News titles end in ' - <Source>'; drop that suffix."""
    if source and title.endswith(f" - {source}"):
        return title[: -len(source) - 3].rstrip()
    if " - " in title:
        return title.rsplit(" - ", 1)[0].rstrip()
    return title


def entry_time(entry) -> float | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return float(timegm(t))
    return None


def item_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def get_with_retry(get: Getter, url: str, headers: dict) -> requests.Response:
    """One retry on network errors and 5xx responses."""
    last_exc: Exception | None = None
    for _ in range(2):
        try:
            r = get(url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last_exc = exc
            continue
        if r.status_code >= 500:
            last_exc = None
            continue
        return r
    if last_exc:
        raise last_exc
    return r  # last 5xx response


def parse_items(content: bytes, outlet: dict, feed_url: str, now: float) -> list[dict]:
    parsed = feedparser.parse(content)
    items = []
    for e in parsed.entries:
        link = (e.get("link") or "").strip()
        title = clean_text(e.get("title"))
        if not link or not title:
            continue
        if outlet.get("via_google_news"):
            src = (e.get("source") or {}).get("title")
            title = strip_source_suffix(title, src)
        ts = entry_time(e)
        if ts is None or ts > now:
            ts = now  # missing or future timestamps are clamped to fetch time
        items.append({
            "outlet_id": outlet["id"],
            "title": title,
            "url": link,
            "published": iso(ts),
            "summary": clean_text(e.get("summary"))[:SUMMARY_MAX],
            "language": outlet["language"],
            "feed": feed_url,
        })
    return items


def fetch_feed(outlet: dict, feed_url: str, prev: dict, now: float, get: Getter) -> tuple[list[dict], dict, dict]:
    """Returns (items, health, conditional_state) for one feed."""
    ua = BROWSER_UA if outlet.get("fetch_ua") == "browser" else BOT_UA
    headers = {"User-Agent": ua}
    if prev.get("etag"):
        headers["If-None-Match"] = prev["etag"]
    if prev.get("last_modified"):
        headers["If-Modified-Since"] = prev["last_modified"]

    health = {"outlet_id": outlet["id"], "feed": feed_url, "checked": iso(now),
              "last_success": prev.get("last_success")}
    try:
        r = get_with_retry(get, feed_url, headers)
    except Exception as exc:  # noqa: BLE001 - a feed must never fail the run
        health.update(status="error", http=None, items=0, error=type(exc).__name__)
        return [], health, prev

    if r.status_code == 304:
        health.update(status="not_modified", http=304, items=0, error=None, last_success=iso(now))
        return [], health, {**prev, "last_success": iso(now)}
    if r.status_code != 200:
        health.update(status="error", http=r.status_code, items=0, error=f"HTTP {r.status_code}")
        return [], health, prev

    try:
        items = parse_items(r.content, outlet, feed_url, now)
    except Exception as exc:  # noqa: BLE001
        health.update(status="error", http=200, items=0, error=f"parse: {type(exc).__name__}")
        return [], health, prev

    if not items:
        health.update(status="empty", http=200, items=0, error="no items")
        return [], health, prev

    state = {
        "etag": r.headers.get("ETag"),
        "last_modified": r.headers.get("Last-Modified"),
        "last_success": iso(now),
    }
    health.update(status="ok", http=200, items=len(items), error=None, last_success=iso(now))
    return items, health, state


def fetch_all(outlets: list[dict], feed_state: dict, now: float,
              get: Getter = requests.get, workers: int = 12) -> tuple[list[dict], list[dict], dict]:
    jobs = [(o, url) for o in outlets if o["enabled"] for url in o["feeds"]]

    def one(job):
        o, url = job
        return fetch_feed(o, url, feed_state.get(url, {}), now, get)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))

    items, health, new_state = [], [], {}
    for (o, url), (its, h, st) in zip(jobs, results):
        items.extend(its)
        health.append(h)
        new_state[url] = st
    return items, health, new_state
