"""Phase 5 gate: up to 20 model-written headlines next to the outlets' own.

Usage: python -m pipeline.tools.preview_headlines DATA_DIR
Prints a JSON block between ===HEADLINES-BEGIN=== and ===HEADLINES-END===.
"""
import json
import sys
from collections import Counter
from pathlib import Path


def main():
    data = Path(sys.argv[1])
    stories = json.loads((data / "stories.json").read_text(encoding="utf-8"))["stories"]
    outlets = {o["id"]: o for o in json.loads(Path("pipeline/outlets.json").read_text(encoding="utf-8"))}
    sources = Counter(s["headline_source"].split(":")[0] for s in stories)
    print("headline sources across all stories:", dict(sources))
    state = json.loads((data / "state.json").read_text(encoding="utf-8"))
    tried = [g for g in state.get("gen", {}).values() if g.get("tried_outlets")]
    fails = Counter(f for g in tried for f in g.get("fails") or [])
    print(f"model attempts so far: {len(tried)}; rejected by checker: {sum(1 for g in tried if g.get('fails'))}; reasons: {dict(fails)}")
    picked = [s for s in stories if s["headline_source"] == "model"][:20]
    out = []
    for s in picked:
        items = sorted(s["items"], key=lambda i: ["left", "lean_left", "center", "lean_right", "right"].index(outlets[i["outlet_id"]]["lean"]))
        out.append({
            "headline": s["headline"], "summary": s["summary"], "region": s["region"],
            "outlets": sum(s["counts"].values()),
            "sources": [{"outlet": outlets[i["outlet_id"]]["name"], "lean": outlets[i["outlet_id"]]["lean"],
                         "title_en": i["title_en"], "url": i["url"]} for i in items],
        })
    print("===HEADLINES-BEGIN===")
    print(json.dumps(out, ensure_ascii=False))
    print("===HEADLINES-END===")


if __name__ == "__main__":
    main()
