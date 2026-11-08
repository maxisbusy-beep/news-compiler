"""Phase 6-7: browser smoke test at phone width (375 px), against sample data.

Runs where NC_UI_TESTS=1 and Playwright's Chromium is installed (CI job "ui").
"""
import functools
import http.server
import os
import shutil
import socketserver
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("NC_UI_TESTS") != "1", reason="UI tests run in CI (set NC_UI_TESTS=1)")


@pytest.fixture(scope="module")
def site_url(tmp_path_factory):
    www = tmp_path_factory.mktemp("www")
    shutil.copytree(ROOT / "site", www, dirs_exist_ok=True)
    shutil.copytree(ROOT / "tests" / "fixtures" / "site_root" / "data", www / "data", dirs_exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(www))
    handler.log_message = lambda *a: None
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


@pytest.fixture
def page(site_url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 375, "height": 812})
        # Block third-party requests (fonts) so the test only sees app errors.
        ctx.route("**/*", lambda r: r.abort() if "127.0.0.1" not in r.request.url else r.continue_())
        pg = ctx.new_page()
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.goto(site_url)
        yield pg
        browser.close()


def test_feed_renders_cards_with_country_and_bar(page):
    page.wait_for_selector(".story")
    assert page.locator(".story").count() == 20
    first = page.locator(".story").first
    assert first.locator(".country").inner_text() == "Israel"
    assert first.locator(".bar span").count() >= 2
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    assert page.errors == []


def test_open_story_shows_outlet_rows_grouped_left_to_right(page):
    page.wait_for_selector(".story")
    page.locator(".story a").nth(3).click()
    page.wait_for_selector(".row")
    groups = page.locator(".group-title").all_inner_texts()
    order = ["Left", "Lean left", "Center", "Lean right", "Right"]
    seen = [next(o for o in order if g.startswith(o + " (")) for g in groups]
    assert seen == sorted(seen, key=order.index)
    assert page.locator(".row a.title").first.get_attribute("target") == "_blank"
    assert page.errors == []


def test_translated_headline_shows_original_on_tap(page):
    page.wait_for_selector(".story")
    page.locator(".story a").nth(3).click()
    btn = page.locator(".orig-btn").first
    btn.click()
    assert "Polen" in page.locator(".orig").first.inner_text()


def test_region_chip_and_search_filter(page):
    page.wait_for_selector(".story")
    page.click(".chip[data-region=europe]")
    n_eu = page.locator(".story").count()
    assert 0 < n_eu < 20
    page.click(".chip[data-region=all]")
    page.click("#search-btn")
    page.fill("#q", "Krakow")
    page.wait_for_timeout(100)
    assert 1 <= page.locator(".story").count() < 20


def test_saved_stories_survive_reload(page):
    page.wait_for_selector(".story")
    page.locator(".story a").first.click()
    page.click("#save")
    assert page.locator("#save").inner_text() == "Saved"
    page.reload()
    page.goto(page.url.split("#")[0] + "#")
    page.wait_for_selector(".story")
    page.click(".chip[data-region=saved]")
    assert page.locator(".story").count() == 1


def test_hiding_an_outlet_and_smaller_stories(page):
    page.wait_for_selector(".story")
    before = page.locator(".story").first.locator(".meta").inner_text()
    page.goto(page.url.split("#")[0] + "#/settings")
    page.wait_for_selector("[data-outlet=haaretz]")
    page.uncheck("[data-outlet=haaretz]")
    page.check("#smaller")
    page.goto(page.url.split("#")[0] + "#")
    page.wait_for_selector(".story")
    after = page.locator(".story").first.locator(".meta").inner_text()
    assert int(after.split()[0]) == int(before.split()[0]) - 1


def test_health_page(page):
    page.goto(page.url.split("#")[0] + "#/health")
    page.wait_for_selector(".health")
    assert "1 outlet failing" in page.inner_text(".page")
