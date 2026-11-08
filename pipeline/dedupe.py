"""Step 2: merge new items into the rolling 48-hour store and remove duplicates.

Duplicate = same canonical URL, or same outlet with title similarity >= 0.9.
The first-seen copy is kept.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .fetch import item_id

WINDOW_HOURS = 48
TITLE_SIMILARITY = 0.9

TRACKING_PARAMS = {
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "cmpid", "ocid",
    "smid", "smtyp", "taid", "ito", "ref", "ref_src", "rss", "feed", "src",
    "traffic_source", "cid", "ns_mchannel", "ns_source", "ns_campaign",
}
TRACKING_PREFIXES = ("utm_", "at_", "itm_", "pk_", "mtm_")

_NONWORD = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def norm_title(t: str) -> str:
    return _WS.sub(" ", _NONWORD.sub(" ", t.lower())).strip()


def similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, norm_title(a), norm_title(b)).ratio() >= TITLE_SIMILARITY


def parse_iso(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def merge(existing: list[dict], new: list[dict], now: float) -> tuple[list[dict], dict]:
    """Returns (kept items, stats). Existing items keep priority over new ones."""
    cutoff = now - WINDOW_HOURS * 3600
    kept: list[dict] = []
    by_url: set[str] = set()
    titles_by_outlet: dict[str, list[str]] = {}
    stats = {"existing": 0, "added": 0, "dup_url": 0, "dup_title": 0, "expired": 0}
    now_iso = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for source, batch in (("existing", existing), ("new", new)):
        for it in batch:
            if parse_iso(it["published"]) < cutoff:
                stats["expired"] += 1
                continue
            curl = it.get("canonical_url") or canonical_url(it["url"])
            if curl in by_url:
                stats["dup_url"] += 1
                continue
            seen_titles = titles_by_outlet.setdefault(it["outlet_id"], [])
            if any(similar(it["title"], t) for t in seen_titles):
                stats["dup_title"] += 1
                continue
            item = dict(it)
            item["canonical_url"] = curl
            item.setdefault("id", item_id(curl))
            item.setdefault("first_seen", now_iso)
            by_url.add(curl)
            seen_titles.append(it["title"])
            kept.append(item)
            stats["existing" if source == "existing" else "added"] += 1
    return kept, stats


def find_duplicates(items: list[dict]) -> list[tuple[str, str, str]]:
    """Independent check used by tests and the gate: (reason, id_a, id_b)."""
    dups = []
    seen_url: dict[str, str] = {}
    for it in items:
        curl = canonical_url(it["url"])
        if curl in seen_url:
            dups.append(("url", seen_url[curl], it["id"]))
        seen_url[curl] = it["id"]
    by_outlet: dict[str, list[dict]] = {}
    for it in items:
        by_outlet.setdefault(it["outlet_id"], []).append(it)
    for group in by_outlet.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if similar(a["title"], b["title"]):
                    dups.append(("title", a["id"], b["id"]))
    return dups
