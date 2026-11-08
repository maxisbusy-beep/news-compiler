"""Phase 4: translation and grouping."""
import json
from pathlib import Path

import numpy as np

from pipeline import group, translate
from pipeline.tools import tune_threshold

from .conftest import fake_embed, fake_translate, requires_models

# Locked after tuning on the fixture with the real model (see SPEC, Phase 4).
LOCKED_F1 = 0.887  # fixture pairwise F1 at GROUP_THRESHOLD 0.425 (precision 0.983, recall 0.808)


def item(i, outlet, title, lang="en", first_seen="2026-11-08T10:00:00Z"):
    return {"id": f"i{i}", "outlet_id": outlet, "title": title, "language": lang,
            "first_seen": first_seen}


# --- translation -------------------------------------------------------------

def test_translate_keeps_original_and_skips_done_items():
    items = [item(1, "a", "Hallo Welt", "de"), item(2, "b", "Hello"), item(3, "c", "Bonjour", "fr"),
             item(4, "d", "Salut", "fr")]
    items[2].update(title_en="Hello (already)", tv=translate.TRANSLATION_VERSION)
    items[3].update(title_en="▁old▁output", tv=1)  # older translation version: redone
    stats = translate.translate_items(items, fake_translate)
    assert items[0]["title"] == "Hallo Welt" and items[0]["title_en"] == "[de] Hallo Welt"
    assert items[1]["title_en"] == "Hello"
    assert items[2]["title_en"] == "Hello (already)"
    assert items[3]["title_en"] == "[fr] Salut"
    assert stats["translated"] == 2 and stats["already"] == 1


def test_translate_failure_is_not_fatal_and_retried_later():
    def broken(lang, titles):
        raise RuntimeError("model download failed")

    items = [item(1, "a", "Hallo Welt", "de")]
    stats = translate.translate_items(items, broken)
    assert "title_en" not in items[0]  # left for the next run
    assert stats["failed_langs"] and stats["failed_langs"][0].startswith("de:")
    translate.translate_items(items, fake_translate)
    assert items[0]["title_en"] == "[de] Hallo Welt"


# --- grouping logic (stand-in embedder) ---------------------------------------

STORY_A = ["Storm floods coastal towns overnight", "Coastal towns flooded by overnight storm",
           "Overnight storm floods coastal towns"]
STORY_B = ["Parliament approves new budget plan", "Budget plan approved by parliament"]


def base_items():
    its = [item(i, f"o{i}", t) for i, t in enumerate(STORY_A)]
    its += [item(10 + i, f"p{i}", t) for i, t in enumerate(STORY_B)]
    its.append(item(20, "q", "Zoo welcomes baby giraffe"))
    its.append(item(21, "o0", "Coastal storm floods towns overnight again"))  # same outlet as A[0]
    for it in its:
        it["title_en"] = it["title"]
    return its


def test_clusters_need_two_outlets():
    its = base_items()
    vecs = group.item_vectors(its, fake_embed, {})
    stories, _, stats = group.build_stories(its, vecs, {}, threshold=0.6)
    sizes = sorted(len(s["item_ids"]) for s in stories)
    assert sizes == [2, 4]  # budget story, storm story (incl. second o0 item); giraffe is not a story
    assert stats["new"] == 2


def test_story_ids_stable_across_runs_and_growth():
    its = base_items()
    vecs = group.item_vectors(its, fake_embed, {})
    s1, st1, _ = group.build_stories(its, vecs, {}, threshold=0.6)
    s2, st2, stats2 = group.build_stories(its, vecs, st1, threshold=0.6)
    assert {s["id"] for s in s1} == {s["id"] for s in s2}
    assert stats2["new"] == 0
    # a new headline joins the storm story without changing its ID
    its.append(item(30, "z", "Overnight storm floods towns on the coast"))
    its[-1]["title_en"] = its[-1]["title"]
    vecs = group.item_vectors(its, fake_embed, {})
    s3, _, stats3 = group.build_stories(its, vecs, st2, threshold=0.6)
    storm_id = next(s["id"] for s in s1 if "i0" in s["item_ids"])
    storm3 = next(s for s in s3 if "i0" in s["item_ids"])
    assert storm3["id"] == storm_id and "i30" in storm3["item_ids"]
    assert stats3["new"] == 0


def test_story_id_kept_by_centroid_when_items_all_replaced():
    its = base_items()
    vecs = group.item_vectors(its, fake_embed, {})
    s1, st1, _ = group.build_stories(its, vecs, {}, threshold=0.6)
    budget_id = next(s["id"] for s in s1 if "i10" in s["item_ids"])
    fresh = [item(40, "x1", "Parliament approves budget plan"), item(41, "x2", "New budget plan approved")]
    for it in fresh:
        it["title_en"] = it["title"]
    vecs = group.item_vectors(fresh, fake_embed, {})
    s2, _, stats = group.build_stories(fresh, vecs, st1, threshold=0.6)
    assert s2[0]["id"] == budget_id and stats["kept_by_centroid"] == 1


def test_story_ids_never_collide_when_headline_moves():
    """Regression (Phase 5 gate run): a headline that seeded story X's ID moves to
    a new cluster; the new cluster must not reuse X's ID while X lives on."""
    its = base_items()
    vecs = group.item_vectors(its, fake_embed, {})
    s1, st1, _ = group.build_stories(its, vecs, {}, threshold=0.6)
    storm = next(s for s in s1 if "i0" in s["item_ids"])
    assert storm["id"] == group.new_story_id(storm["item_ids"])
    # i0 now heads a separate cluster with a fresh outlet; the rest of the storm story stays put
    moved = dict(its[0], title="Zoo giraffe celebrates birthday", title_en="Zoo giraffe celebrates birthday")
    extra = item(50, "zz", "Zoo giraffe celebrates birthday"); extra["title_en"] = extra["title"]
    its2 = [moved] + its[1:] + [extra]
    vecs2 = group.item_vectors(its2, fake_embed, {})
    s2, _, _ = group.build_stories(its2, vecs2, st1, threshold=0.6)
    ids = [s["id"] for s in s2]
    assert len(ids) == len(set(ids)), ids
    assert next(s for s in s2 if "i1" in s["item_ids"])["id"] == storm["id"]


def test_translated_items_use_both_texts():
    a = item(1, "a", "Erdbeben", "de"); a["title_en"] = "Earthquake"
    cache = {}
    v = group.item_vectors([a], fake_embed, cache)
    expect = group.normalize(group.normalize(fake_embed(["Erdbeben"]))[0] + group.normalize(fake_embed(["Earthquake"]))[0])
    assert np.allclose(v[0], expect, atol=1e-6)
    assert len(cache) == 1


def test_embedding_cache_roundtrip(tmp_path):
    its = base_items()
    cache = {}
    group.item_vectors(its, fake_embed, cache)
    path = tmp_path / "emb.npz"
    group.save_cache(path, cache, {group.text_key(it) for it in its[:3]})
    loaded = group.load_cache(path)
    assert set(loaded) == {group.text_key(it) for it in its[:3]}
    calls = []
    group.item_vectors(its[:3], lambda t: calls.append(t) or fake_embed(t), loaded)
    assert calls == []  # all served from cache


# --- real models (CI only) ------------------------------------------------------

@requires_models
def test_argos_translates_fixture_languages():
    out_de = translate.argos_translate("de", ["Schweres Erdbeben erschüttert Osttürkei"])
    out_fr = translate.argos_translate("fr", ["Le gouvernement survit à une motion de censure"])
    assert "earthquake" in out_de[0].lower() or "quake" in out_de[0].lower()
    assert "government" in out_fr[0].lower()
    assert "▁" not in out_de[0] + out_fr[0]


@requires_models
def test_fixture_clustering_regression():
    rows, items = tune_threshold.load_fixture()
    vectors = group.item_vectors(items, group.fastembed_embed, {})
    m, _ = tune_threshold.evaluate(vectors, [r["label"] for r in rows], group.GROUP_THRESHOLD)
    print("fixture metrics at GROUP_THRESHOLD:", m)
    assert m["f1"] >= LOCKED_F1 - 0.02
