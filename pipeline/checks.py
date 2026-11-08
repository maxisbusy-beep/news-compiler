"""Neutral-headline checker (SPEC: Neutral headline rules).

check_headline() returns a list of failed rule names; empty means it passes.
check_summary() applies the rules that make sense for a short summary.
Attribution and present tense are asked for in the prompt and reviewed by
Max; they can't be checked reliably with rules.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

MAX_LEN = 90
SUMMARY_MAX_LEN = 420

# Judgment and emotion words. Matched as whole words, case-insensitive.
BANNED = {
    "slam", "slams", "slammed", "blasts", "blasted", "rips", "ripped", "destroys",
    "chaos", "chaotic", "radical", "radicals", "extremist", "extremists",
    "shocking", "shock", "stunning", "stunned", "disaster", "disastrous", "regime",
    "outrage", "outraged", "outrageous", "furious", "fury", "bombshell", "brutal",
    "horrific", "horrifying", "heroic", "thug", "thugs", "lies", "liar", "mocks",
    "mocked", "scathing", "humiliating", "humiliation", "meltdown", "slaughter",
    "massacre", "terrorists", "tyrant", "dictator", "crushes", "crushed", "epic",
    "explosive", "devastating", "catastrophic", "clueless", "insane", "absurd",
}

# Outlet names that are also ordinary words or phrases; not treated as outlet names.
GENERIC_NAMES = {"The Australian", "The Hindu", "The Dispatch", "The Hill"}

# Capitalised words that are not named entities.
NOT_ENTITIES = {
    "The", "A", "An", "In", "On", "At", "As", "After", "Before", "For", "From", "To",
    "Of", "And", "Or", "But", "With", "Without", "Over", "Under", "Amid", "By", "New",
    "Is", "Are", "Was", "Were", "Be", "It", "Its", "This", "That", "These", "Who",
    "What", "Why", "How", "When", "Where", "Says", "Say", "Said", "Up", "Out", "More",
    "First", "Second", "Third", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
    "Nine", "Ten", "Dozens", "Hundreds", "Thousands", "Millions", "At least", "Least",
}

_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][\w'’-]*")
_NUM = re.compile(r"\d+(?:[.,:]\d+)*")


@lru_cache(maxsize=1)
def outlet_names() -> tuple[str, ...]:
    path = Path(__file__).with_name("outlets.json")
    names: set[str] = set()
    for o in json.loads(path.read_text(encoding="utf-8")):
        full = o["name"]
        names.add(full)
        names.update(re.findall(r"\(([^)]+)\)", full))          # "MS NOW (MSNBC)" -> MSNBC
        base = re.sub(r"\s*\([^)]*\)", "", full).strip()
        names.add(base)
        for suffix in (" English", " News", " World"):
            short = base[: -len(suffix)] if base.endswith(suffix) else ""
            if short.isupper():  # "NBC News" -> NBC, but "Arab News" stays whole
                names.add(short)
    names.update({"AP", "Reuters", "AFP", "Fox News", "CNN", "BBC", "NPR", "MSNBC", "Al Jazeera"})
    return tuple(sorted(n for n in names if n and n not in GENERIC_NAMES))


def outlet_name_used(text: str) -> str | None:
    for name in outlet_names():
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text):
            return name
    return None


def banned_word_used(text: str) -> str | None:
    for w in _WORD.findall(text.lower()):
        if w.strip("'’-") in BANNED:
            return w
    return None


def numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in _NUM.findall(text)}


def unsupported_numbers(text: str, sources: list[str], min_sources: int = 2) -> set[str]:
    src_nums = [numbers(s) for s in sources]
    return {n for n in numbers(text) if sum(n in s for s in src_nums) < min_sources}


def entities(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text):
        w = w.strip("'’-").removesuffix("’s").removesuffix("'s")
        if len(w) > 1 and (w[0].isupper() or w.isupper()) and w not in NOT_ENTITIES:
            out.append(w)
    return out


def missing_entities(text: str, sources: list[str]) -> tuple[list[str], list[str]]:
    """Returns (entities found in sources, entities not found)."""
    blob = " ".join(sources).lower()
    ents = list(dict.fromkeys(entities(text)))
    found = [e for e in ents if e.lower() in blob]
    return found, [e for e in ents if e not in found]


def check_headline(headline: str, sources: list[str]) -> list[str]:
    """sources: the story's English source headlines."""
    fails = []
    h = (headline or "").strip()
    if not h:
        return ["empty"]
    if len(h) > MAX_LEN:
        fails.append("too_long")
    if outlet_name_used(h):
        fails.append("outlet_name")
    if banned_word_used(h):
        fails.append("judgment_word")
    if unsupported_numbers(h, sources):
        fails.append("unsupported_number")
    found, _ = missing_entities(h, sources)
    if len(found) < min(2, max(1, len(entities(h)))):
        fails.append("missing_entities")
    return fails


def check_summary(summary: str, sources: list[str]) -> list[str]:
    """sources: titles and descriptions given to the model."""
    fails = []
    s = (summary or "").strip()
    if not s:
        return ["empty"]
    if len(s) > SUMMARY_MAX_LEN:
        fails.append("too_long")
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", s) if x]
    if not 1 <= len(sentences) <= 3:
        fails.append("sentence_count")
    if outlet_name_used(s):
        fails.append("outlet_name")
    if banned_word_used(s):
        fails.append("judgment_word")
    if unsupported_numbers(s, sources):
        fails.append("unsupported_number")
    return fails
