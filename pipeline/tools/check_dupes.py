"""Gate check: no duplicate items in raw.json; print a short report.

Usage: python -m pipeline.tools.check_dupes DATA_DIR [PREVIOUS_RAW_JSON]
Exits 1 if any duplicate is found.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from pipeline.dedupe import find_duplicates


def main() -> int:
    data = Path(sys.argv[1])
    items = json.loads((data / "raw.json").read_text(encoding="utf-8"))["items"]
    dups = find_duplicates(items)
    per_outlet = Counter(i["outlet_id"] for i in items)
    print(f"items: {len(items)} from {len(per_outlet)} outlets")
    print("fewest items:", per_outlet.most_common()[-5:])
    if len(sys.argv) > 2:
        prev = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["items"]
        prev_ids = {i["id"] for i in prev}
        new = [i for i in items if i["id"] not in prev_ids]
        dropped = prev_ids - {i["id"] for i in items}
        print(f"vs previous run: {len(new)} new items, {len(dropped)} dropped (expired)")
        for i in new[:10]:
            print("   new:", i["outlet_id"], "|", i["title"][:90])
    print(f"duplicates: {len(dups)}")
    for d in dups[:20]:
        print("   ", d)
    return 1 if dups else 0


if __name__ == "__main__":
    sys.exit(main())
