from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_site_placeholder_exists():
    page = ROOT / "site" / "index.html"
    assert page.is_file()
    html = page.read_text(encoding="utf-8")
    assert "<title>News Compiler</title>" in html
    assert 'name="viewport"' in html


def test_repo_layout():
    for rel in ["SPEC.md", "pipeline", "tests", "site/icons", ".github/workflows/pipeline.yml"]:
        assert (ROOT / rel).exists(), rel
