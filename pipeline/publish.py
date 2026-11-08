"""Step 6: copy the public data into the site before deploy.

Usage: python -m pipeline.publish --data-dir work --site site

Writes site/data/stories.json, site/data/health.json and site/data/outlets.json.
Only public fields leave the private working directory: headlines, links,
times and lean counts. RSS descriptions never do (they stay in raw.json).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORY_KEYS = {"id", "country", "headline", "headline_source", "summary", "region", "first_seen",
              "updated", "counts", "blindspot", "items"}
ITEM_KEYS = {"outlet_id", "title", "title_en", "url", "published"}
HEALTH_KEYS = ("outlet_id", "feed", "status", "items", "error", "checked", "last_success")
OUTLET_KEYS = ("id", "name", "lean", "region", "country", "paywall", "tags", "lean_source", "lean_source_url")


def validate(stories: list[dict]) -> list[str]:
    problems = []
    for s in stories:
        if set(s) != STORY_KEYS:
            problems.append(f"{s.get('id')}: keys {sorted(set(s) ^ STORY_KEYS)}")
        for it in s.get("items", []):
            if set(it) != ITEM_KEYS:
                problems.append(f"{s.get('id')}: item keys {sorted(set(it) ^ ITEM_KEYS)}")
                break
    return problems


def publish(data_dir: Path, site: Path, outlets_path: Path = ROOT / "pipeline" / "outlets.json") -> dict:
    out = site / "data"
    out.mkdir(parents=True, exist_ok=True)
    stories = json.loads((data_dir / "stories.json").read_text(encoding="utf-8"))
    problems = validate(stories["stories"])
    if problems:
        raise SystemExit("stories.json failed validation:\n" + "\n".join(problems[:20]))
    (out / "stories.json").write_text(json.dumps(stories, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    health = json.loads((data_dir / "health.json").read_text(encoding="utf-8"))
    health["feeds"] = [{k: h.get(k) for k in HEALTH_KEYS} for h in health["feeds"]]
    (out / "health.json").write_text(json.dumps(health, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    outlets = json.loads(outlets_path.read_text(encoding="utf-8"))
    public = [{k: o.get(k) for k in OUTLET_KEYS} for o in outlets if o["enabled"]]
    (out / "outlets.json").write_text(json.dumps(public, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return {"stories": len(stories["stories"]), "outlets": len(public), "feeds": len(health["feeds"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--site", default=ROOT / "site", type=Path)
    args = ap.parse_args()
    print(json.dumps(publish(args.data_dir, args.site)))


if __name__ == "__main__":
    sys.exit(main())
