"""Phase 5 gate: compare candidate models on the same live stories.

Usage: python -m pipeline.tools.bench_models DATA_DIR [model ...]
Prints per-model pass rate and speed, then a JSON block between
===BENCH-BEGIN=== / ===BENCH-END=== with every model's output per story
(headlines and links only) for Max to rate.
"""
import json
import random
import sys
import time
from pathlib import Path

from pipeline import checks, write
from pipeline.translate import english

N_TOP, N_RANDOM = 5, 5


def pick_stories(data: Path):
    groups = json.loads((data / "groups.json").read_text(encoding="utf-8"))["stories"]
    items = {i["id"]: i for i in json.loads((data / "raw.json").read_text(encoding="utf-8"))["items"]}
    def n_out(s):
        return len({items[i]["outlet_id"] for i in s["item_ids"] if i in items})
    big = sorted((s for s in groups if n_out(s) >= write.GEN_MIN_OUTLETS), key=n_out, reverse=True)
    rest = big[N_TOP:]
    random.Random(7).shuffle(rest)
    chosen = big[:N_TOP] + rest[:N_RANDOM]
    return [[items[i] for i in s["item_ids"] if i in items] for s in chosen]


def main():
    data = Path(sys.argv[1])
    names = sys.argv[2:] or list(write.MODELS)
    outlets = {o["id"]: o for o in json.loads(Path("pipeline/outlets.json").read_text(encoding="utf-8"))}
    stories = pick_stories(data)
    results = {"stories": [], "models": {}}
    for its in stories:
        sample = write.sample_items(its, outlets)
        results["stories"].append({
            "outlets": len({i["outlet_id"] for i in its}),
            "sources": [{"outlet": outlets[i["outlet_id"]]["name"], "lean": outlets[i["outlet_id"]]["lean"],
                         "title_en": english(i), "url": i["url"]} for i in sample],
            "outputs": {},
        })

    for name in names:
        t0 = time.time()
        try:
            model = write.LlamaWriter(name)
        except Exception as exc:  # noqa: BLE001
            results["models"][name] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            print(f"{name}: failed to load: {exc}", flush=True)
            continue
        load_s = time.time() - t0
        times, passed, valid, sum_ok = [], 0, 0, 0
        for st, its in zip(results["stories"], stories):
            sample = write.sample_items(its, outlets)
            t1 = time.time()
            try:
                raw = model(write.build_prompt(sample))
            except Exception as exc:  # noqa: BLE001
                raw = ""
                print(f"  {name} error: {exc}", flush=True)
            secs = time.time() - t1
            times.append(secs)
            parsed = write.parse_output(raw, len(sample))
            entry = {"seconds": round(secs, 1), "valid_json": parsed is not None}
            if parsed:
                valid += 1
                sources = [english(i) for i in its]
                fails = checks.check_headline(parsed["headline"], sources)
                sfails = checks.check_summary(parsed["summary"], [english(i) for i in sample] + [i.get("summary", "") for i in sample])
                passed += not fails
                sum_ok += not sfails
                entry.update(headline=parsed["headline"], fails=fails, summary=parsed["summary"],
                             summary_fails=sfails, region=parsed["region"],
                             dropped=len(sample) - len(parsed["belongs"]))
            st["outputs"][name] = entry
            print(f"  {name} {secs:5.1f}s {'PASS' if parsed and not entry['fails'] else 'fail'} | {entry.get('headline', raw[:80])}", flush=True)
        n = len(stories)
        results["models"][name] = {
            "load_s": round(load_s, 1),
            "avg_s": round(sum(times) / n, 1), "max_s": round(max(times), 1),
            "headline_pass": f"{passed}/{n}", "summary_pass": f"{sum_ok}/{n}", "valid_json": f"{valid}/{n}",
        }
        print(f"{name}: {results['models'][name]}", flush=True)
        del model

    print("\n===BENCH-BEGIN===")
    print(json.dumps(results, ensure_ascii=False))
    print("===BENCH-END===")


if __name__ == "__main__":
    main()
