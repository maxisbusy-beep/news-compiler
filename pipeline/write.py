"""Step 5: neutral headline, summary and region for each story.

A small open-source model (GGUF, run on CPU with llama-cpp-python) reads up
to 10 of a story's headlines and returns JSON constrained by a schema:
{belongs, headline, summary, region}. checks.py vets the output; anything
that fails falls back to a wire-service headline, then to the source
headline closest to the story's centre.

Generation is capped per run (MAX_GEN_PER_RUN and a time budget); stories
beyond the cap keep their last headline or use the fallback, and stay queued.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from typing import Callable

import numpy as np

from . import checks, countries, regions
from .translate import MODELS_DIR, english

# name -> (Hugging Face repo, GGUF file). Licenses: Qwen research license,
# Llama 3.2 community license, Gemma terms of use (all allow personal use).
MODELS = {
    "qwen2.5-3b": ("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf"),
    "llama3.2-3b": ("bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-Q4_K_M.gguf"),
    "gemma3-4b": ("unsloth/gemma-3-4b-it-GGUF", "gemma-3-4b-it-Q4_K_M.gguf"),
}
DEFAULT_MODEL = os.environ.get("NC_MODEL", "llama3.2-3b")  # Max's pick at the Phase 5 gate

MAX_GEN_PER_RUN = 20
TIME_BUDGET_S = 600          # stop starting new generations after this long
GEN_MIN_OUTLETS = 3          # stories shown by default; smaller ones use the fallback
REGEN_GROWTH = 1.5           # regenerate when outlet count grows 50% since last attempt
SAMPLE_SIZE = 10
DESC_CHARS = 160
WIRE_ORDER = ("ap", "reuters", "dw")
LEAN_ORDER = ("left", "lean_left", "center", "lean_right", "right")
REGIONS = ["us", "europe", "middle_east", "asia", "africa", "americas", "oceania", "global"]

SCHEMA = {
    "type": "object",
    "properties": {
        "belongs": {"type": "array", "items": {"type": "integer"}},
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "region": {"type": "string", "enum": REGIONS},
        "country": {"type": "string"},
    },
    "required": ["belongs", "headline", "summary", "region", "country"],
}

PROMPT = """You write neutral, factual news headlines, like a wire service.

Below are numbered headlines from different news outlets that may all be about one news event.

Return JSON with:
- "belongs": the numbers of the items about the same main event as most items. Leave out items about a different event.
- "headline": one neutral, factual headline for that main event.
  * At most 90 characters, plain present tense.
  * Only facts reported by at least two items. Use a number only if at least two items give the same number.
  * Attribute disputed claims to whoever made them ("X says ..."). If the items say "police say", "officials say" or "Houthis say", keep that attribution.
  * Be specific: say who did what, and where. Not "Russia targets Ukraine with airstrikes" but what was hit and the result.
  * Name a place only if at least two items name it.
  * Name the main people, places or organizations involved.
  * No news outlet names. No opinion or emotional words (such as slams, chaos, radical, shocking, disaster, regime).
- "summary": 2 or 3 short sentences of facts that at least two items agree on. Same rules as the headline.
- "region": where the event happens: one of us, europe, middle_east, asia, africa, americas, oceania, global.
- "country": the one country where the event mainly happens, as a short name (USA, UK, Germany, Israel, Gaza, Egypt, Japan ...). Use "World" if it truly spans many countries. Do not repeat the country at the start of the headline.

Items:
{items}
"""

LlmFn = Callable[[str], str]   # prompt -> raw JSON text


# --- model -------------------------------------------------------------------

def model_path(name: str) -> str:
    from huggingface_hub import hf_hub_download

    repo, filename = MODELS[name]
    return hf_hub_download(repo, filename, cache_dir=str(MODELS_DIR / "gguf"))


class LlamaWriter:
    def __init__(self, name: str = DEFAULT_MODEL, threads: int | None = None):
        from llama_cpp import Llama

        self.name = name
        self.llm = Llama(model_path=model_path(name), n_ctx=2048,
                         n_threads=threads or os.cpu_count() or 4, verbose=False)

    def __call__(self, prompt: str) -> str:
        res = self.llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object", "schema": SCHEMA},
            temperature=0.2, max_tokens=320,
        )
        return res["choices"][0]["message"]["content"] or ""


# --- prompt ------------------------------------------------------------------

def sample_items(story_items: list[dict], outlets: dict) -> list[dict]:
    """Up to SAMPLE_SIZE items, one per outlet, wire first, spread across leans."""
    by_outlet: dict[str, dict] = {}
    for it in sorted(story_items, key=lambda i: i["published"], reverse=True):
        by_outlet.setdefault(it["outlet_id"], it)
    picked = [by_outlet[w] for w in WIRE_ORDER if w in by_outlet]
    buckets = {lean: [] for lean in LEAN_ORDER}
    for oid, it in by_outlet.items():
        if oid not in WIRE_ORDER:
            buckets[outlets.get(oid, {}).get("lean", "center")].append(it)
    while len(picked) < SAMPLE_SIZE and any(buckets.values()):
        for lean in LEAN_ORDER:
            if buckets[lean] and len(picked) < SAMPLE_SIZE:
                picked.append(buckets[lean].pop(0))
    return picked


def build_prompt(sample: list[dict]) -> str:
    lines = []
    for n, it in enumerate(sample):
        line = f"[{n}] {english(it)}"
        desc = it.get("summary", "") if it.get("language", "en") == "en" else ""
        if desc and desc.lower() not in english(it).lower():
            line += f" | {desc[:DESC_CHARS]}"
        lines.append(line)
    return PROMPT.format(items="\n".join(lines))


def parse_output(text: str, n_items: int) -> dict | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    belongs = data.get("belongs")
    if not isinstance(belongs, list):
        belongs = list(range(n_items))
    belongs = sorted({b for b in belongs if isinstance(b, int) and 0 <= b < n_items})
    out = {
        "belongs": belongs,
        "headline": data.get("headline") if isinstance(data.get("headline"), str) else "",
        "summary": data.get("summary") if isinstance(data.get("summary"), str) else "",
        "region": data.get("region") if data.get("region") in REGIONS else None,
        "country": data.get("country") if isinstance(data.get("country"), str) else None,
    }
    return out


def strip_country_prefix(headline: str) -> str:
    """The app shows the country label itself; drop "USA - " / "Israel: " if the model added one."""
    m = re.match(r"^([A-Z][\w .'’]{1,30}?)\s*[-–—:|]\s+(.*)$", headline)
    if m and countries.normalize(m.group(1)):
        return m.group(2)
    return headline


# --- fallback ----------------------------------------------------------------

def fallback_headline(story_items: list[dict], centroid: np.ndarray | None,
                      vec_of: dict[str, np.ndarray]) -> tuple[str, str]:
    for w in WIRE_ORDER:
        wire = [it for it in story_items if it["outlet_id"] == w]
        if wire:
            it = max(wire, key=lambda i: i["published"])
            return english(it), f"wire:{w}"
    best = story_items[0]
    if centroid is not None:
        scored = [(float(vec_of[i["id"]] @ centroid), i) for i in story_items if i["id"] in vec_of]
        if scored:
            best = max(scored, key=lambda x: x[0])[1]
    return english(best), "nearest"


def majority_region(story_items: list[dict], outlets: dict) -> str:
    regions = Counter(outlets.get(i["outlet_id"], {}).get("region") for i in story_items)
    regions.pop("global", None); regions.pop(None, None)
    return regions.most_common(1)[0][0] if regions else "global"


# --- one story ---------------------------------------------------------------

def generate(story_items: list[dict], outlets: dict, llm: LlmFn,
             centroid=None, vec_of=None) -> dict:
    """Returns {headline, headline_source, summary, region, rejected, fails, error}."""
    vec_of = vec_of or {}
    sample = sample_items(story_items, outlets)
    result = {"rejected": [], "fails": [], "error": None}
    try:
        raw = llm(build_prompt(sample))
        parsed = parse_output(raw, len(sample))
        if parsed is None:
            result["error"] = "bad_json"
    except Exception as exc:  # noqa: BLE001 - a model problem never stops the run
        parsed, result["error"] = None, f"{type(exc).__name__}: {exc}"[:200]

    kept = story_items
    if parsed:
        rejected = {sample[i]["id"] for i in range(len(sample)) if i not in parsed["belongs"]}
        remaining = [it for it in story_items if it["id"] not in rejected]
        if len({it["outlet_id"] for it in remaining}) >= 2 and len(rejected) <= len(sample) // 2:
            kept = remaining
            result["rejected"] = sorted(rejected)

    sources = [english(it) for it in kept]
    headline = ""
    if parsed:
        headline = strip_country_prefix(" ".join(parsed["headline"].split()))
        result["fails"] = checks.check_headline(headline, sources)
    if parsed and not result["fails"]:
        result["headline"], result["headline_source"] = headline, "model"
    else:
        result["headline"], result["headline_source"] = fallback_headline(kept, centroid, vec_of)

    summary = " ".join((parsed or {}).get("summary", "").split())
    sum_sources = [english(it) for it in sample] + [it.get("summary", "") for it in sample]
    result["summary"] = summary if summary and not checks.check_summary(summary, sum_sources) else ""
    titles = [english(it) for it in kept]
    result["country"] = countries.resolve_country((parsed or {}).get("country"), titles)
    result["region"] = (countries.region_of(result["country"])
                        or regions.resolve_region((parsed or {}).get("region"), titles, majority_region(kept, outlets)))
    return result


# --- all stories ---------------------------------------------------------------

def blindspot(counts: dict) -> str | None:
    """SPEC: >= 5 outlets; left share of partisan outlets >= 0.85 -> the right is
    ignoring it ("right"); <= 0.15 -> "left". Center outlets are not counted."""
    if sum(counts.values()) < 5:
        return None
    left = counts.get("left", 0) + counts.get("lean_left", 0)
    right = counts.get("right", 0) + counts.get("lean_right", 0)
    if left + right == 0:
        return None
    share = left / (left + right)
    return "right" if share >= 0.85 else "left" if share <= 0.15 else None


def lean_counts(story_items: list[dict], outlets: dict) -> dict:
    c = Counter()
    for oid in {it["outlet_id"] for it in story_items}:
        c[outlets.get(oid, {}).get("lean", "center")] += 1
    return {lean: c.get(lean, 0) for lean in LEAN_ORDER}


def write_all(stories: list[dict], items: list[dict], outlets_list: list[dict], state: dict,
              llm: LlmFn | Callable[[], LlmFn] | None, vec_of: dict, now_iso: str,
              cap: int = MAX_GEN_PER_RUN, time_budget: float = TIME_BUDGET_S) -> tuple[list[dict], dict, dict]:
    """Returns (stories for stories.json, new gen state, stats).

    `llm` may be a factory (called once, only if something needs generating) so
    the model is not loaded on runs with nothing new.
    """
    outlets = {o["id"]: o for o in outlets_list}
    by_id = {it["id"]: it for it in items}
    prev_gen = state.get("gen", {})
    new_gen: dict[str, dict] = {}
    stats = {"generated": 0, "model_headlines": 0, "fallbacks": 0, "errors": 0,
             "queued": 0, "gen_seconds": 0.0, "fail_reasons": Counter()}

    prepared = []
    for s in stories:
        g = prev_gen.get(s["id"], {})
        rejected = set(g.get("rejected", []))
        its = [by_id[i] for i in s["item_ids"] if i in by_id and i not in rejected]
        if len({it["outlet_id"] for it in its}) < 2:
            its = [by_id[i] for i in s["item_ids"] if i in by_id]
        n_out = len({it["outlet_id"] for it in its})
        tried = g.get("tried_outlets")
        needs = n_out >= GEN_MIN_OUTLETS and (tried is None or n_out >= REGEN_GROWTH * tried)
        prepared.append((s, its, n_out, needs, g))

    queue = sorted((p for p in prepared if p[3]), key=lambda p: -p[2])
    to_generate = {p[0]["id"] for p in queue[:cap]}
    model = None
    started = time.time()
    out = []
    for s, its, n_out, needs, g in prepared:
        sid = s["id"]
        entry = dict(g)
        if sid in to_generate and time.time() - started < time_budget:
            if model is None:
                model = load_model(llm)
                stats["model_error"] = getattr(model, "load_error", None)
            t0 = time.time()
            r = generate(its, outlets, model, s.get("centroid"), vec_of)
            stats["gen_seconds"] += time.time() - t0
            stats["generated"] += 1
            stats["model_headlines"] += r["headline_source"] == "model"
            stats["fallbacks"] += r["headline_source"] != "model"
            stats["errors"] += r["error"] is not None
            stats["fail_reasons"].update(r["fails"])
            entry = {"headline": r["headline"], "headline_source": r["headline_source"],
                     "summary": r["summary"], "region": r["region"], "country": r["country"],
                     "rejected": r["rejected"],
                     "tried_outlets": n_out, "fails": r["fails"], "error": r["error"]}
            rejected = set(r["rejected"])
            its = [it for it in its if it["id"] not in rejected]
        elif not entry.get("headline"):
            stats["queued"] += needs
            h, src = fallback_headline(its, s.get("centroid"), vec_of)
            titles = [english(it) for it in its]
            country = countries.resolve_country(None, titles)
            entry = {"headline": h, "headline_source": src, "summary": "", "country": country,
                     "region": countries.region_of(country)
                     or regions.resolve_region(None, titles, majority_region(its, outlets)),
                     "rejected": [], "tried_outlets": None}
        else:
            stats["queued"] += needs
        if "country" not in entry:  # stored before country labels existed
            entry["country"] = countries.resolve_country(None, [english(it) for it in its])
        new_gen[sid] = entry
        out.append({
            "id": sid,
            "country": entry["country"],
            "headline": entry["headline"],
            "headline_source": entry["headline_source"],
            "summary": entry.get("summary", ""),
            "region": entry.get("region") or majority_region(its, outlets),
            "first_seen": s["first_seen"],
            "updated": s["updated"],
            "counts": (counts := lean_counts(its, outlets)),
            "blindspot": blindspot(counts),
            "items": [{"outlet_id": it["outlet_id"], "title": it["title"], "title_en": english(it),
                       "url": it["url"], "published": it["published"]}
                      for it in sorted(its, key=lambda i: i["published"])],
        })
    stats["gen_seconds"] = round(stats["gen_seconds"], 1)
    stats["fail_reasons"] = dict(stats["fail_reasons"])
    return out, new_gen, stats


def load_model(llm):
    """Resolve a factory into a model; a model that fails to load becomes a
    stand-in that raises, so every story falls back and the run continues."""
    if not (callable(llm) and getattr(llm, "is_factory", False)):
        return llm
    try:
        return llm()
    except Exception as exc:  # noqa: BLE001
        msg = f"{type(exc).__name__}: {exc}"[:200]

        def broken(prompt):
            raise RuntimeError(f"model unavailable: {msg}")
        broken.load_error = msg
        return broken


def model_factory(name: str = DEFAULT_MODEL):
    def make():
        return LlamaWriter(name)
    make.is_factory = True
    return make
