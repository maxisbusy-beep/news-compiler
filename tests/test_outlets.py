"""Phase 2: outlets.json schema, icons and balance."""
import json
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUTLETS = json.loads((ROOT / "pipeline" / "outlets.json").read_text(encoding="utf-8"))

LEANS = {"left", "lean_left", "center", "lean_right", "right"}
REGIONS = {"us", "europe", "middle_east", "asia", "africa", "americas", "oceania", "global"}
TAGS = {"state_funded", "public_broadcaster"}
REQUIRED = {
    "id": str, "name": str, "feeds": list, "region": str, "country": str,
    "language": str, "lean": str, "lean_source": str, "lean_source_url": str,
    "tags": list, "paywall": bool, "wire": bool, "enabled": bool,
}
OPTIONAL = {"via_google_news": bool}


@pytest.mark.parametrize("o", OUTLETS, ids=lambda o: o.get("id", "?"))
def test_schema(o):
    for key, typ in REQUIRED.items():
        assert key in o, f"missing {key}"
        assert isinstance(o[key], typ), f"{key} should be {typ.__name__}"
    assert set(o) <= set(REQUIRED) | set(OPTIONAL), f"unknown keys {set(o) - set(REQUIRED) - set(OPTIONAL)}"
    assert o["lean"] in LEANS
    assert o["region"] in REGIONS
    assert set(o["tags"]) <= TAGS
    assert o["lean_source"] in {"AllSides", "Media Bias/Fact Check", "Ad Fontes"}
    assert o["lean_source_url"].startswith("https://")
    assert len(o["language"]) == 2 and len(o["country"]) == 2
    assert o["feeds"], "at least one feed"
    assert all(f.startswith(("https://", "http://")) for f in o["feeds"])


def test_ids_unique():
    ids = [o["id"] for o in OUTLETS]
    assert len(ids) == len(set(ids))


def test_wire_outlets():
    assert {o["id"] for o in OUTLETS if o["wire"]} == {"ap", "reuters", "dw"}


@pytest.mark.parametrize("o", [o for o in OUTLETS if o["enabled"]], ids=lambda o: o["id"])
def test_enabled_outlet_has_icon(o):
    icon = ROOT / "site" / "icons" / f"{o['id']}.png"
    assert icon.is_file(), f"no icon for {o['id']}"
    assert icon.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(icon).convert("RGBA")
    alpha = img.getchannel("A")
    visible = sum(1 for a in alpha.getdata() if a > 40)
    assert visible >= 0.1 * img.size[0] * img.size[1], f"{o['id']} icon is blank"


def test_at_least_35_enabled():
    assert sum(o["enabled"] for o in OUTLETS) >= 35


def test_every_side_present_overall():
    sides = Counter(o["lean"] for o in OUTLETS if o["enabled"])
    for lean in LEANS:
        assert sides[lean] > 0, f"no enabled {lean} outlet"
