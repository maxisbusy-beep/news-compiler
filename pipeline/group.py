"""Step 4: group headlines into stories.

- Each headline becomes a vector from a multilingual sentence-embedding model
  (paraphrase-multilingual-MiniLM-L12-v2, ONNX via fastembed). For translated
  headlines the original and English vectors are averaged.
- Headlines are clustered with average-linkage agglomerative clustering on
  cosine distance, cut at GROUP_THRESHOLD (tuned on tests/fixtures/labeled_headlines.json).
- A cluster with headlines from at least 2 distinct outlets is a story.
- Story IDs stay stable across runs: a cluster takes the ID most of its
  previously-seen headlines had; failing that, the ID of the previous story
  whose centroid is closest (cosine >= MATCH_SIMILARITY); otherwise a new ID.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np

from .translate import MODELS_DIR, english

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
GROUP_THRESHOLD = 0.45     # cosine distance; tuned in Phase 4 (see tools/tune_threshold.py)
MATCH_SIMILARITY = 0.80    # centroid similarity needed to inherit a previous story's ID
MIN_OUTLETS = 2

EmbedFn = Callable[[list[str]], np.ndarray]

_model = None


def fastembed_embed(texts: list[str]) -> np.ndarray:
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(MODEL_NAME, cache_dir=str(MODELS_DIR / "fastembed"))
    return np.asarray(list(_model.embed(texts, batch_size=64)), dtype=np.float32)


def normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.where(n == 0, 1, n)


def text_key(it: dict) -> str:
    return hashlib.sha1(f"{it['title']}|{english(it)}".encode("utf-8")).hexdigest()[:20]


def item_vectors(items: list[dict], embed: EmbedFn, cache: dict[str, np.ndarray]) -> np.ndarray:
    """One unit vector per item, using and filling `cache` (key -> vector)."""
    need = [it for it in items if text_key(it) not in cache]
    if need:
        texts, owners = [], []
        for idx, it in enumerate(need):
            texts.append(it["title"]); owners.append(idx)
            if english(it) != it["title"]:
                texts.append(english(it)); owners.append(idx)
        vecs = normalize(embed(texts))
        sums = np.zeros((len(need), vecs.shape[1]), dtype=np.float32)
        for row, idx in zip(vecs, owners):
            sums[idx] += row
        for it, v in zip(need, normalize(sums)):
            cache[text_key(it)] = v
    return np.stack([cache[text_key(it)] for it in items]) if items else np.zeros((0, 384), np.float32)


def cluster_labels(vectors: np.ndarray, threshold: float = GROUP_THRESHOLD) -> np.ndarray:
    n = len(vectors)
    if n == 0:
        return np.zeros(0, dtype=int)
    if n == 1:
        return np.zeros(1, dtype=int)
    from sklearn.cluster import AgglomerativeClustering

    model = AgglomerativeClustering(
        n_clusters=None, metric="cosine", linkage="average", distance_threshold=threshold
    )
    return model.fit_predict(vectors)


def new_story_id(item_ids: list[str]) -> str:
    return "s_" + hashlib.sha1(min(item_ids).encode()).hexdigest()[:12]


def build_stories(items: list[dict], vectors: np.ndarray, prev_state: dict,
                  threshold: float = GROUP_THRESHOLD) -> tuple[list[dict], dict, dict]:
    """Returns (stories, new_state_part, stats).

    stories: [{id, item_ids, first_seen, updated, centroid}] for clusters with
    >= MIN_OUTLETS distinct outlets, largest first.
    """
    labels = cluster_labels(vectors, threshold)
    groups: dict[int, list[int]] = {}
    for idx, lab in enumerate(labels):
        groups.setdefault(int(lab), []).append(idx)

    candidates = [
        g for g in groups.values()
        if len({items[i]["outlet_id"] for i in g}) >= MIN_OUTLETS
    ]
    candidates.sort(key=lambda g: (-len({items[i]["outlet_id"] for i in g}), -len(g)))

    prev_map: dict[str, str] = prev_state.get("item_story", {})
    prev_stories: dict[str, dict] = prev_state.get("stories", {})
    prev_ids = list(prev_stories)
    prev_centroids = (
        normalize(np.asarray([prev_stories[s]["centroid"] for s in prev_ids], dtype=np.float32))
        if prev_ids else None
    )

    taken: set[str] = set()
    stories, item_story = [], {}
    stats = {"stories": 0, "kept_by_items": 0, "kept_by_centroid": 0, "new": 0, "clusters": len(groups)}
    for g in candidates:
        ids = [items[i]["id"] for i in g]
        centroid = normalize(vectors[g].mean(axis=0))
        sid = None
        votes = Counter(prev_map[i] for i in ids if i in prev_map and prev_map[i] not in taken)
        if votes:
            best, n = votes.most_common(1)[0]
            known = sum(1 for i in ids if i in prev_map)
            if n * 2 >= known:
                sid = best
                stats["kept_by_items"] += 1
        if sid is None and prev_centroids is not None:
            sims = prev_centroids @ centroid
            for j in np.argsort(-sims):
                if sims[j] < MATCH_SIMILARITY:
                    break
                if prev_ids[j] not in taken:
                    sid = prev_ids[j]
                    stats["kept_by_centroid"] += 1
                    break
        if sid is None or sid in taken:
            sid = new_story_id(ids)
            stats["new"] += 1
        taken.add(sid)
        first_seen = min(items[i]["first_seen"] for i in g)
        if sid in prev_stories:
            first_seen = min(first_seen, prev_stories[sid]["first_seen"])
        stories.append({
            "id": sid,
            "item_ids": ids,
            "first_seen": first_seen,
            "updated": max(items[i]["first_seen"] for i in g),
            "centroid": centroid,
        })
        for i in ids:
            item_story[i] = sid
    stats["stories"] = len(stories)

    new_state = {
        "item_story": item_story,
        "stories": {
            s["id"]: {"centroid": [round(float(x), 4) for x in s["centroid"]],
                      "first_seen": s["first_seen"]}
            for s in stories
        },
    }
    return stories, new_state, stats


# --- embedding cache on disk (private working data) -------------------------

def load_cache(path: Path) -> dict[str, np.ndarray]:
    try:
        z = np.load(path, allow_pickle=False)
        return {k: v.astype(np.float32) for k, v in zip(z["keys"], z["vecs"])}
    except (FileNotFoundError, KeyError, ValueError, OSError):
        return {}


def save_cache(path: Path, cache: dict[str, np.ndarray], keep: set[str]) -> None:
    keys = [k for k in cache if k in keep]
    if not keys:
        return
    vecs = np.stack([cache[k] for k in keys]).astype(np.float16)
    tmp = path.with_name(path.stem + ".tmp.npz")
    np.savez_compressed(tmp, keys=np.asarray(keys), vecs=vecs)
    tmp.replace(path)
