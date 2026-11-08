"""Step 3: translate non-English titles to English.

Uses Argos Translate's offline packages (de->en, fr->en) but drives the
CTranslate2 model directly in batches, which is much faster than translating
headlines one at a time and avoids Argos's sentence-splitting dependency
(headlines are single sentences). Originals are kept; the English goes in
`title_en`. Items that already have `title_en` are not translated again.
"""
from __future__ import annotations

import io
import json
import os
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

INDEX_URL = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
MODELS_DIR = Path(os.environ.get("NC_MODELS_DIR", Path.home() / ".cache" / "news-compiler"))

TranslateFn = Callable[[str, list[str]], list[str]]  # (lang, titles) -> english titles

# Bump when translation output changes, so stored translations are redone.
TRANSLATION_VERSION = 2


def package_dir(lang: str) -> Path:
    return MODELS_DIR / "argos" / f"{lang}_en"


def ensure_package(lang: str) -> Path:
    """Download and unpack the Argos lang->en package once; cached afterwards."""
    dest = package_dir(lang)
    if (dest / "sentencepiece.model").exists():
        return dest
    with urllib.request.urlopen(INDEX_URL, timeout=30) as r:
        index = json.load(r)
    pkgs = [p for p in index if p["from_code"] == lang and p["to_code"] == "en"]
    if not pkgs:
        raise RuntimeError(f"no Argos package for {lang}->en")
    pkg = max(pkgs, key=lambda p: [int(x) for x in p["package_version"].split(".")])
    data = None
    errors = []
    for link in pkg["links"]:
        try:
            req = urllib.request.Request(link, headers={"User-Agent": "argos-translate/1.9 (news-compiler)"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            break
        except OSError as exc:
            errors.append(f"{link}: {exc}")
    if data is None:
        raise RuntimeError(f"could not download Argos package {lang}->en: {errors}")
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.infolist():
            parts = Path(member.filename).parts[1:]  # drop the package's top folder
            if not parts or member.is_dir():
                continue
            target = dest.joinpath(*parts)
            if not str(target.resolve()).startswith(str(dest.resolve())):
                raise RuntimeError("unsafe path in package")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(member))
    if not (dest / "sentencepiece.model").exists():
        raise RuntimeError(f"Argos {lang}->en package has no sentencepiece model")
    return dest


class ArgosTranslator:
    """Batch translator for one source language."""

    def __init__(self, lang: str):
        import ctranslate2
        import sentencepiece as spm

        d = ensure_package(lang)
        self.sp = spm.SentencePieceProcessor(model_file=str(d / "sentencepiece.model"))
        self.model = ctranslate2.Translator(str(d / "model"), device="cpu")

    def __call__(self, titles: list[str]) -> list[str]:
        if not titles:
            return []
        tokens = [self.sp.encode(t, out_type=str) for t in titles]
        results = self.model.translate_batch(
            tokens, beam_size=2, max_batch_size=64, replace_unknowns=True, max_decoding_length=96
        )
        # Join pieces ourselves (as Argos does): some packages' output pieces
        # are not all in the source sentencepiece vocabulary, so sp.decode
        # would leave the "▁" word markers in the text.
        return [" ".join("".join(r.hypotheses[0]).replace("▁", " ").split()) for r in results]


_translators: dict[str, ArgosTranslator] = {}


def argos_translate(lang: str, titles: list[str]) -> list[str]:
    if lang not in _translators:
        _translators[lang] = ArgosTranslator(lang)
    return _translators[lang](titles)


def translate_items(items: list[dict], translate: TranslateFn = argos_translate) -> dict:
    """Fill `title_en` in place. English items get title_en = title.

    A language whose model fails to load leaves its items untranslated
    (title_en = title) for this run and is retried next run.
    """
    stats = {"translated": 0, "already": 0, "failed_langs": []}
    todo: dict[str, list[dict]] = {}
    for it in items:
        if it.get("language", "en") == "en":
            it["title_en"] = it["title"]
            continue
        if it.get("title_en") and it.get("tv") == TRANSLATION_VERSION:
            stats["already"] += 1
            continue
        todo.setdefault(it["language"], []).append(it)
    for lang, group in todo.items():
        try:
            out = translate(lang, [it["title"] for it in group])
        except Exception as exc:  # noqa: BLE001 - never fail the run on a model problem
            stats["failed_langs"].append(f"{lang}: {type(exc).__name__}: {exc}"[:200])
            continue  # leave title_en unset so the next run retries
        for it, en in zip(group, out):
            it["title_en"] = en or it["title"]
            it["tv"] = TRANSLATION_VERSION
            stats["translated"] += 1
    return stats


def english(it: dict) -> str:
    return it.get("title_en") or it["title"]
