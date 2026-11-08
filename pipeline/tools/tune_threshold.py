"""Tune GROUP_THRESHOLD on the hand-labeled fixture with the real models.

Usage: python -m pipeline.tools.tune_threshold
Prints pairwise precision/recall/F1 and adjusted Rand index per threshold,
and the clusters at the current GROUP_THRESHOLD.
"""
import json
from itertools import combinations
from pathlib import Path

import numpy as np

from pipeline import group, translate

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "labeled_headlines.json"


def load_fixture(translate_fn=translate.argos_translate):
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    items = [{"id": f"f{i}", "title": r["title"], "language": r["lang"]} for i, r in enumerate(rows)]
    translate.translate_items(items, translate_fn)
    return rows, items


def pair_scores(labels_true, labels_pred):
    tp = fp = fn = 0
    for i, j in combinations(range(len(labels_true)), 2):
        same_t = labels_true[i] == labels_true[j]
        same_p = labels_pred[i] == labels_pred[j]
        tp += same_t and same_p
        fp += (not same_t) and same_p
        fn += same_t and not same_p
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1


def evaluate(vectors, truth, threshold):
    from sklearn.metrics import adjusted_rand_score

    pred = group.cluster_labels(vectors, threshold)
    p, r, f1 = pair_scores(truth, list(pred))
    return {"threshold": threshold, "precision": round(p, 3), "recall": round(r, 3),
            "f1": round(f1, 3), "ari": round(adjusted_rand_score(truth, pred), 3)}, pred


def main():
    rows, items = load_fixture()
    for r, it in zip(rows, items):
        if r["lang"] != "en":
            print(f"  [{r['lang']}] {r['title']}\n       -> {it['title_en']}")
    vectors = group.item_vectors(items, group.fastembed_embed, {})
    truth = [r["label"] for r in rows]
    print("\nthreshold  precision  recall   f1     ari")
    best = None
    for t in np.round(np.arange(0.20, 0.71, 0.025), 3):
        m, _ = evaluate(vectors, truth, float(t))
        print(f"  {t:.3f}     {m['precision']:.3f}    {m['recall']:.3f}  {m['f1']:.3f}  {m['ari']:.3f}")
        if best is None or m["f1"] > best["f1"]:
            best = m
    print(f"\nbest: {best}")
    m, pred = evaluate(vectors, truth, group.GROUP_THRESHOLD)
    print(f"current GROUP_THRESHOLD {group.GROUP_THRESHOLD}: {m}")
    clusters = {}
    for lab, r in zip(pred, rows):
        clusters.setdefault(int(lab), []).append(r)
    for members in sorted(clusters.values(), key=len, reverse=True):
        labels = {x["label"] for x in members}
        flag = "" if len(labels) == 1 else "  <-- MIXED"
        print(f"\n[{len(members)}]{flag}")
        for x in members:
            print(f"   {x['label']:18} {x['title'][:80]}")


if __name__ == "__main__":
    main()
