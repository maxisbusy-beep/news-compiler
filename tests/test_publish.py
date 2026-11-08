import json

import pytest

from pipeline import publish


def write_work(tmp_path, story_extra=None, item_extra=None):
    item = {"outlet_id": "bbc", "title": "T", "title_en": "T", "url": "https://x", "published": "2026-11-08T10:00:00Z"}
    item.update(item_extra or {})
    story = {"id": "s1", "country": "UK", "headline": "H", "headline_source": "model", "summary": "", "region": "europe",
             "first_seen": "a", "updated": "b", "counts": {}, "blindspot": None, "items": [item]}
    story.update(story_extra or {})
    work = tmp_path / "work"; work.mkdir()
    (work / "stories.json").write_text(json.dumps({"generated_at": "x", "stories": [story]}))
    (work / "health.json").write_text(json.dumps({"generated_at": "x", "feeds": [
        {"outlet_id": "bbc", "feed": "f", "status": "ok", "items": 1, "error": None, "checked": "x",
         "last_success": "x", "secret_debug": "drop me"}]}))
    return work


def test_publish_writes_public_files(tmp_path):
    work = write_work(tmp_path)
    site = tmp_path / "site"
    out = publish.publish(work, site)
    assert out["stories"] == 1
    health = json.loads((site / "data" / "health.json").read_text())
    assert "secret_debug" not in health["feeds"][0]
    outlets = json.loads((site / "data" / "outlets.json").read_text())
    assert all(set(o) == set(publish.OUTLET_KEYS) for o in outlets)
    assert all("feeds" not in o for o in outlets)


def test_publish_refuses_rss_descriptions(tmp_path):
    work = write_work(tmp_path, item_extra={"summary": "RSS description text"})
    with pytest.raises(SystemExit, match="failed validation"):
        publish.publish(work, tmp_path / "site")
