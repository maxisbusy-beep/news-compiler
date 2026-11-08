"""Gate helper: pick 20 stories for Max to hand-check and report ID stability.

Usage: python -m pipeline.tools.preview_stories DATA_DIR [PREV_GROUPS_JSON]
Prints a JSON block between ===REVIEW-BEGIN=== and ===REVIEW-END===:
the 10 largest stories plus 10 random stories with 3+ outlets.
Headlines and links only (no descriptions).
"""
import json
import random
import sys
from pathlib import Path


def main():
    data = Path(sys.argv[1])
    groups = json.loads((data / "groups.json").read_text(encoding="utf-8"))["stories"]
    items = {i["id"]: i for i in json.loads((data / "raw.json").read_text(encoding="utf-8"))["items"]}
    outlets = {o["id"]: o for o in json.loads(Path("pipeline/outlets.json").read_text(encoding="utf-8"))}

    def n_outlets(s):
        return len({items[i]["outlet_id"] for i in s["item_ids"]})

    print(f"stories (2+ outlets): {len(groups)}; with 3+ outlets: {sum(n_outlets(s) >= 3 for s in groups)}")
    sizes = sorted((n_outlets(s) for s in groups), reverse=True)
    print("largest by outlet count:", sizes[:15])

    if len(sys.argv) > 2:
        prev = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["stories"]
        prev_by_item = {i: s["id"] for s in prev for i in s["item_ids"]}
        kept = changed = 0
        for s in groups:
            old = {prev_by_item[i] for i in s["item_ids"] if i in prev_by_item}
            if not old:
                continue
            kept += s["id"] in old
            changed += s["id"] not in old
        print(f"ID stability vs previous run: {kept} stories kept their ID, {changed} changed")

    by_size = sorted(groups, key=n_outlets, reverse=True)
    top = by_size[:10]
    rest = [s for s in by_size[10:] if n_outlets(s) >= 3]
    random.Random(42).shuffle(rest)
    pick = top + rest[:10]
    review = []
    for s in pick:
        rows = []
        for i in s["item_ids"]:
            it = items[i]
            o = outlets.get(it["outlet_id"], {})
            rows.append({"outlet": o.get("name", it["outlet_id"]), "lean": o.get("lean"),
                         "title": it["title"], "title_en": it.get("title_en", it["title"]),
                         "url": it["url"]})
        rows.sort(key=lambda r: ["left", "lean_left", "center", "lean_right", "right"].index(r["lean"] or "center"))
        review.append({"id": s["id"], "outlets": n_outlets(s), "headlines": rows,
                       "pick": "largest" if s in top else "random"})
    print("===REVIEW-BEGIN===")
    print(json.dumps(review, ensure_ascii=False))
    print("===REVIEW-END===")


if __name__ == "__main__":
    main()
