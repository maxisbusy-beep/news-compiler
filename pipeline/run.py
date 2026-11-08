"""Pipeline orchestrator. Phase 3 runs steps 1-2 (fetch, dedupe).

Usage: python -m pipeline.run --data-dir DIR [--outlets pipeline/outlets.json]

DIR holds the private working files carried between runs (raw.json with RSS
descriptions, state.json) plus health.json. Writes all three back to DIR and
appends a feed health table to $GITHUB_STEP_SUMMARY when set.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from . import dedupe, fetch

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def health_table(health: list[dict], outlets: list[dict]) -> str:
    names = {o["id"]: o["name"] for o in outlets}
    by_outlet: dict[str, list[dict]] = {}
    for h in health:
        by_outlet.setdefault(h["outlet_id"], []).append(h)
    lines = ["| Outlet | Status | New items | Error |", "|---|---|---|---|"]
    for oid in sorted(by_outlet, key=lambda k: names.get(k, k)):
        hs = by_outlet[oid]
        statuses = {h["status"] for h in hs}
        status = "ok" if "ok" in statuses else ("not modified" if "not_modified" in statuses else hs[0]["status"])
        errs = "; ".join(h["error"] for h in hs if h.get("error") and h["status"] == "error")
        lines.append(f"| {names.get(oid, oid)} | {status} | {sum(h['items'] for h in hs)} | {errs} |")
    return "\n".join(lines)


def run(data_dir: Path, outlets_path: Path, now: float | None = None, get=None) -> dict:
    now = now if now is not None else time.time()
    data_dir.mkdir(parents=True, exist_ok=True)
    outlets = load_json(outlets_path, [])
    state = load_json(data_dir / "state.json", {})
    existing = load_json(data_dir / "raw.json", {}).get("items", [])

    kwargs = {"get": get} if get else {}
    new_items, health, feed_state = fetch.fetch_all(outlets, state.get("feeds", {}), now, **kwargs)
    items, stats = dedupe.merge(existing, new_items, now)

    state["feeds"] = feed_state
    write_json(data_dir / "raw.json", {"generated_at": fetch.iso(now), "items": items})
    write_json(data_dir / "state.json", state)
    write_json(data_dir / "health.json", {"generated_at": fetch.iso(now), "feeds": health})

    summary = {
        "items": len(items),
        "fetched": len(new_items),
        **stats,
        "feeds_ok": sum(h["status"] == "ok" for h in health),
        "feeds_not_modified": sum(h["status"] == "not_modified" for h in health),
        "feeds_failed": sum(h["status"] in ("error", "empty") for h in health),
        "feeds_total": len(health),
    }
    out = os.environ.get("GITHUB_STEP_SUMMARY")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"### Run at {fetch.iso(now)}\n\n```\n{json.dumps(summary, indent=1)}\n```\n\n")
            f.write(health_table(health, outlets) + "\n\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--outlets", default=ROOT / "pipeline" / "outlets.json", type=Path)
    args = ap.parse_args()
    print(json.dumps(run(args.data_dir, args.outlets), indent=1))


if __name__ == "__main__":
    main()
