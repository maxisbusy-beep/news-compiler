"""Phase 2 helper: probe candidate RSS feeds and fetch outlet icons.

Runs in GitHub Actions (news sites are reachable there). For each outlet it
tries every candidate feed, then a Google News site-search feed as a last
resort, and records status, item count and freshness. It also downloads a
64 px PNG icon per outlet.

Usage: python pipeline/tools/probe_feeds.py <candidates.json> <out_dir>
Writes <out_dir>/report.json and <out_dir>/icons/<id>.png, and appends a
Markdown table to $GITHUB_STEP_SUMMARY when set.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from calendar import timegm
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser
import requests
from PIL import Image

UA = "NewsCompiler/1.0 (+https://maxisbusy-beep.github.io/news-compiler)"
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
TIMEOUT = 15
FRESH_HOURS = 48
MIN_ITEMS = 5


def google_news_feed(domain: str) -> str:
    return (
        "https://news.google.com/rss/search?q=site:"
        f"{domain}+when:2d&hl=en-US&gl=US&ceid=US:en"
    )


def entry_time(entry) -> float | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return float(timegm(t))
    return None


def probe_feed(url: str) -> dict:
    result = {"url": url, "ok": False}
    for ua in (UA, BROWSER_UA):
        try:
            r = requests.get(url, headers={"User-Agent": ua}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            result.update(status=None, error=type(exc).__name__)
            continue
        result.update(status=r.status_code, ua="bot" if ua == UA else "browser")
        if r.status_code != 200:
            result["error"] = f"HTTP {r.status_code}"
            continue
        parsed = feedparser.parse(r.content)
        entries = parsed.entries
        times = [t for t in (entry_time(e) for e in entries) if t]
        newest_h = (time.time() - max(times)) / 3600 if times else None
        result.update(
            items=len(entries),
            newest_hours=round(newest_h, 1) if newest_h is not None else None,
            dated=len(times),
            language=parsed.feed.get("language"),
            title=parsed.feed.get("title"),
            sample=[e.get("title", "")[:120] for e in entries[:3]],
            error=None,
        )
        fresh = newest_h is not None and newest_h <= FRESH_HOURS
        result["ok"] = len(entries) >= MIN_ITEMS and fresh
        if result["ok"]:
            return result
        result["error"] = (
            f"{len(entries)} items, newest {result['newest_hours']} h"
        )
    return result


class IconLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        rel = (a.get("rel") or "").lower()
        if "icon" in rel and a.get("href"):
            self.links.append((rel, a["href"]))


def to_png(data: bytes) -> bytes | None:
    try:
        img = Image.open(io.BytesIO(data))
        if getattr(img, "n_frames", 1) > 1 or img.format == "ICO":
            # ICO files hold several sizes; pick the largest.
            sizes = sorted(getattr(img, "ico", None).sizes()) if img.format == "ICO" else []
            if sizes:
                img.size = sizes[-1]
                img.load()
        img = img.convert("RGBA")
        if min(img.size) < 16:
            return None
        img.thumbnail((64, 64), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()
    except Exception:
        return None


def fetch_icon(domain: str) -> tuple[bytes | None, str | None]:
    base = f"https://{domain}/"
    candidates: list[str] = []
    try:
        r = requests.get(base, headers={"User-Agent": BROWSER_UA}, timeout=TIMEOUT)
        if r.ok:
            p = IconLinks()
            p.feed(r.text[:300_000])
            # apple-touch-icon first (larger), then other icons
            ranked = sorted(p.links, key=lambda x: 0 if "apple" in x[0] else 1)
            candidates += [urljoin(r.url, href) for _, href in ranked]
    except requests.RequestException:
        pass
    candidates += [urljoin(base, "apple-touch-icon.png"), urljoin(base, "favicon.ico")]
    seen = set()
    for url in candidates:
        if url in seen or url.startswith("data:") or url.endswith(".svg"):
            continue
        seen.add(url)
        try:
            r = requests.get(url, headers={"User-Agent": BROWSER_UA}, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if r.ok and r.content:
            png = to_png(r.content)
            if png:
                return png, url
    return None, None


def main(cand_path: str, out_dir: str) -> int:
    outlets = json.load(open(cand_path, encoding="utf-8"))
    os.makedirs(os.path.join(out_dir, "icons"), exist_ok=True)
    report = []
    for o in outlets:
        tries = [probe_feed(u) for u in o["feeds"]]
        working = [t for t in tries if t["ok"]]
        via_google = False
        if not working:
            g = probe_feed(google_news_feed(o["domain"]))
            tries.append(g)
            if g["ok"]:
                working = [g]
                via_google = True
        png, icon_src = fetch_icon(o["domain"])
        if png:
            with open(os.path.join(out_dir, "icons", f"{o['id']}.png"), "wb") as f:
                f.write(png)
        report.append({
            "id": o["id"],
            "domain": o["domain"],
            "chosen": [t["url"] for t in working],
            "via_google_news": via_google,
            "icon": icon_src,
            "tries": tries,
        })
        print(o["id"], "OK" if working else "FAIL", "google" if via_google else "", "icon" if png else "no-icon", flush=True)

    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("| Outlet | Feed | Items | Newest (h) | Icon |\n|---|---|---|---|---|\n")
            for r in report:
                best = next((t for t in r["tries"] if t["ok"]), r["tries"][-1])
                feed = ("Google News" if r["via_google_news"] else ("ok" if r["chosen"] else best.get("error")))
                f.write(f"| {r['id']} | {feed} | {best.get('items','')} | {best.get('newest_hours','')} | {'yes' if r['icon'] else 'no'} |\n")
    ok = sum(1 for r in report if r["chosen"])
    print(f"\n{ok}/{len(report)} outlets have a working feed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
