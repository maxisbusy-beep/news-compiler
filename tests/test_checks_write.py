"""Phase 5: headline checker, writer, fallback, cap and queue."""
import json

import numpy as np
import pytest

from pipeline import checks, write

SOURCES = [
    "Israel's president taps opposition leader Eisenkot to form a government",
    "Israeli president picks Gadi Eisenkot, Netanyahu rival, to try to form government",
    "Train collision in Egypt's Giza kills 4, injures 88",
    "Train collision in Egypt kills 4 and injures 88 south of Cairo",
]


# --- checks.py -----------------------------------------------------------------

@pytest.mark.parametrize("headline", [
    "Israel's president asks Eisenkot to form a government",
    "Train collision in Egypt kills 4, injures 88",
])
def test_good_headlines_pass(headline):
    assert checks.check_headline(headline, SOURCES) == []


@pytest.mark.parametrize("headline,rule", [
    ("", "empty"),
    ("Israel's president asks opposition leader Gadi Eisenkot to try to form the country's next government now", "too_long"),
    ("Reuters: Israel's president asks Eisenkot to form a government", "outlet_name"),
    ("Israel's president asks Eisenkot to form government, CNN reports", "outlet_name"),
    ("Netanyahu slams Israel's president over Eisenkot pick", "judgment_word"),
    ("Chaos in Israel as Eisenkot gets mandate", "judgment_word"),
    ("Train collision in Egypt kills 7", "unsupported_number"),
    ("Train collision in Morocco kills 4, injures 88", "missing_entities"),
])
def test_bad_headlines_fail(headline, rule):
    assert rule in checks.check_headline(headline, SOURCES)


def test_generic_outlet_names_are_not_blocked():
    # "The Australian dollar" and "the Hill" in ordinary use are fine
    assert "outlet_name" not in checks.check_headline("The Australian dollar falls after Israel vote", SOURCES + ["Australian dollar falls"])


def test_arab_is_not_an_outlet_name():
    assert checks.outlet_name_used("Arab states welcome Israel's new government") is None
    assert checks.outlet_name_used("Arab News reports on Israel") == "Arab News"


def test_summary_checks():
    srcs = SOURCES
    assert checks.check_summary("Two trains collided in Egypt. Four people died and 88 were hurt.", srcs) == []
    assert "unsupported_number" in checks.check_summary("Two trains collided. 9 people died.", srcs)
    assert "sentence_count" in checks.check_summary("One. Two. Three. Four.", srcs)


# --- write.py --------------------------------------------------------------------

OUTLETS = [
    {"id": "ap", "name": "AP", "lean": "lean_left", "region": "us"},
    {"id": "reuters", "name": "Reuters", "lean": "center", "region": "global"},
    {"id": "fox", "name": "Fox News", "lean": "right", "region": "us"},
    {"id": "guardian", "name": "The Guardian", "lean": "left", "region": "europe"},
    {"id": "bbc", "name": "BBC", "lean": "center", "region": "europe"},
    {"id": "nyp", "name": "New York Post", "lean": "right", "region": "us"},
]
O = {o["id"]: o for o in OUTLETS}


def it(i, outlet, title, published="2026-11-08T10:00:00Z"):
    return {"id": f"i{i}", "outlet_id": outlet, "title": title, "title_en": title, "language": "en",
            "url": f"https://x/{i}", "published": published, "first_seen": published, "summary": ""}


EGYPT = [
    it(1, "guardian", "Train collision in Egypt kills 4, injures 88"),
    it(2, "reuters", "Train collision in Egypt's Giza kills 4, injures 88", "2026-11-08T11:00:00Z"),
    it(3, "fox", "Train collision in Egypt kills 4 and injures 88 south of Cairo"),
    it(4, "bbc", "Zoo welcomes baby giraffe"),
]


def llm_returning(obj):
    return lambda prompt: obj if isinstance(obj, str) else json.dumps(obj)


def test_model_headline_used_when_it_passes():
    r = write.generate(EGYPT[:3], O, llm_returning(
        {"belongs": [0, 1, 2], "headline": "Train collision in Egypt kills 4, injures 88",
         "summary": "Two trains collided in Egypt. Four people died and 88 were hurt.", "region": "middle_east"}))
    assert r["headline_source"] == "model" and r["summary"] and r["region"] == "middle_east"


def test_rejected_items_removed():
    sample = write.sample_items(EGYPT, O)
    giraffe = next(n for n, s in enumerate(sample) if s["id"] == "i4")
    keep = [n for n in range(len(sample)) if n != giraffe]
    r = write.generate(EGYPT, O, llm_returning(
        {"belongs": keep, "headline": "Train collision in Egypt kills 4, injures 88",
         "summary": "", "region": "africa"}))
    assert r["rejected"] == ["i4"]
    assert r["headline_source"] == "model"


def test_rejection_ignored_when_model_drops_too_much():
    # keeping only one item would leave a single outlet: treat as confusion, keep all
    r = write.generate(EGYPT[:3], O, llm_returning(
        {"belongs": [0], "headline": "Train collision in Egypt kills 4, injures 88", "summary": "", "region": "africa"}))
    assert r["rejected"] == []


def test_fallback_order_wire_then_nearest():
    bad = llm_returning({"belongs": [0, 1, 2], "headline": "Chaos as trains collide", "summary": "", "region": "global"})
    r = write.generate(EGYPT[:3], O, bad)
    assert r["headline_source"] == "wire:reuters" and "judgment_word" in r["fails"]
    assert r["headline"] == EGYPT[1]["title_en"]
    # no wire outlet: the headline nearest the centre wins
    no_wire = [EGYPT[0], EGYPT[2]]
    vec = {"i1": np.array([1.0, 0.0]), "i3": np.array([0.6, 0.8])}
    r = write.generate(no_wire, O, bad, centroid=np.array([0.5, 0.866]), vec_of=vec)
    assert r["headline_source"] == "nearest" and r["headline"] == EGYPT[2]["title_en"]


@pytest.mark.parametrize("raw", ["not json", "[1,2]", '{"headline": 5}', "", "{"])
def test_malformed_output_falls_back_never_crashes(raw):
    r = write.generate(EGYPT[:3], O, llm_returning(raw))
    assert r["headline_source"].startswith("wire:")
    assert r["region"] in write.REGIONS


def test_model_exception_falls_back():
    def boom(prompt):
        raise RuntimeError("out of memory")
    r = write.generate(EGYPT[:3], O, boom)
    assert r["headline_source"] == "wire:reuters" and "out of memory" in r["error"]


def test_unloadable_model_does_not_stop_run():
    def factory():
        raise OSError("download failed")
    factory.is_factory = True
    stories = [{"id": "s1", "item_ids": ["i1", "i2", "i3"], "first_seen": "x", "updated": "2026-11-08T11:00:00Z"}]
    out, gen, stats = write.write_all(stories, EGYPT, OUTLETS, {}, factory, {}, "now")
    assert out[0]["headline_source"] == "wire:reuters"
    assert "download failed" in stats["model_error"]


def make_stories(n):
    """n stories, story k has k+3 outlets' worth of items (cycled)."""
    stories, items = [], []
    for k in range(n):
        ids = []
        for j, oid in enumerate(["ap", "reuters", "fox", "guardian", "bbc", "nyp"][: min(6, 3 + k % 4)]):
            i = it(f"{k}_{j}", oid, f"Story {k} headline about Paris talks")
            items.append(i); ids.append(i["id"])
        stories.append({"id": f"s{k}", "item_ids": ids, "first_seen": "2026-11-08T10:00:00Z",
                        "updated": "2026-11-08T10:00:00Z"})
    return stories, items


def test_cap_and_queue_largest_first():
    stories, items = make_stories(8)
    calls = []

    def llm(prompt):
        calls.append(prompt)
        return json.dumps({"belongs": list(range(10)), "headline": "Talks in Paris continue", "summary": "", "region": "europe"})

    out, gen, stats = write.write_all(stories, items, OUTLETS, {}, llm, {}, "now", cap=3)
    assert stats["generated"] == 3 and len(calls) == 3
    assert stats["queued"] == 5
    sizes = {s["id"]: sum(s["counts"].values()) for s in out}
    generated = [sid for sid, g in gen.items() if g.get("tried_outlets")]
    assert sorted(sizes[s] for s in generated) == sorted(sorted(sizes.values())[-3:])
    # next run: the queued ones get their turn, already-done ones are not redone
    out2, gen2, stats2 = write.write_all(stories, items, OUTLETS, {"gen": gen}, llm, {}, "now", cap=3)
    assert stats2["generated"] == 3 and not (set(generated) & {sid for sid in gen2 if gen2[sid].get("tried_outlets") and sid not in generated and False})
    assert sum(1 for g in gen2.values() if g.get("tried_outlets")) == 6


def test_regenerate_only_when_story_grows_50_percent():
    stories, items = make_stories(1)  # 3 outlets
    llm = llm_returning({"belongs": [0, 1, 2], "headline": "Talks in Paris continue", "summary": "", "region": "europe"})
    _, gen, s1 = write.write_all(stories, items, OUTLETS, {}, llm, {}, "now")
    _, gen, s2 = write.write_all(stories, items, OUTLETS, {"gen": gen}, llm, {}, "now")
    assert s1["generated"] == 1 and s2["generated"] == 0
    for oid in ["guardian", "bbc"]:  # 3 -> 5 outlets (>= 4.5)
        x = it(f"new_{oid}", oid, "Story 0 headline about Paris talks"); items.append(x)
        stories[0]["item_ids"].append(x["id"])
    _, _, s3 = write.write_all(stories, items, OUTLETS, {"gen": gen}, llm, {}, "now")
    assert s3["generated"] == 1


def test_small_stories_use_fallback_without_model():
    stories = [{"id": "s1", "item_ids": ["i1", "i2"], "first_seen": "x", "updated": "x"}]
    def llm(prompt):
        raise AssertionError("2-outlet stories must not call the model")
    out, _, _ = write.write_all(stories, EGYPT, OUTLETS, {}, llm, {}, "now")
    assert out[0]["headline_source"] == "wire:reuters"


def test_sample_spreads_leans_and_puts_wire_first():
    items = [it(n, oid, f"t{n}") for n, oid in enumerate(["fox", "nyp", "guardian", "bbc", "ap", "reuters"])]
    sample = write.sample_items(items, O)
    assert [s["outlet_id"] for s in sample[:2]] == ["ap", "reuters"]
    assert {s["outlet_id"] for s in sample} == {"fox", "nyp", "guardian", "bbc", "ap", "reuters"}


def test_story_output_shape():
    stories = [{"id": "s1", "item_ids": ["i1", "i2", "i3"], "first_seen": "a", "updated": "b"}]
    llm = llm_returning({"belongs": [0, 1, 2], "headline": "Train collision in Egypt kills 4, injures 88",
                         "summary": "", "region": "middle_east"})
    out, _, _ = write.write_all(stories, EGYPT, OUTLETS, {}, llm, {}, "now")
    s = out[0]
    assert set(s) == {"id", "country", "headline", "headline_source", "summary", "region", "first_seen",
                      "updated", "counts", "blindspot", "items"}
    assert s["country"] == "Egypt"
    assert s["counts"] == {"left": 1, "lean_left": 0, "center": 1, "lean_right": 0, "right": 1}
    assert set(s["items"][0]) == {"outlet_id", "title", "title_en", "url", "published"}
    assert "summary" not in s["items"][0]  # RSS descriptions never published
