# News Compiler: SPEC

Repo: `maxisbusy-beep/news-compiler` (public; free Actions minutes depend on it)
Plan doc: News Compiler Build Plan (Claude Docs)

## How to work this spec

- Build one phase at a time. Each phase lists its **scope**, **files**, **tests** and **gate**.
- Touch only the files a phase names. If something outside scope needs to change, stop and ask.
- Cite file and line numbers when reporting changes.
- Every phase adds tests, and all earlier tests must still pass.
- **Stop at every gate.** Report what was built, test results and anything that needs Max's judgment. Do not start the next phase until Max says go.

## What the app is

A phone-first web app. It groups headlines from about 40 outlets worldwide, left to right, into stories. Each story gets one neutral, factual headline and a 2–3 sentence summary written by a free open-source model. Tapping a story shows every outlet's own headline with its icon and lean, grouped Left → Center → Right.

**Hard constraints**

- **$0 running cost.** No paid APIs and no API keys. Everything runs in GitHub Actions and on GitHub Pages.
- **Headlines and links only.** Never store or display article text or RSS descriptions. RSS descriptions may be used as model input, but are never shown.
- **No server.** The front end is static and reads JSON files.
- **Calm UI.** A feed card shows only: headline, time, outlet count, coverage bar, and at most one tag.

## Architecture

```
GitHub Action (every 30 min, Python 3.12)
  1. fetch     RSS feeds -> raw items          (feedparser, conditional GET)
  2. dedupe    same URL / near-identical title
  3. translate non-English titles -> English  (argostranslate, CTranslate2 on CPU)
  4. group     multilingual embeddings -> clusters -> match to existing stories
  5. write     local LLM: cluster check, neutral headline, summary, region tag
               (llama-cpp-python + GGUF model; fallback = wire headline)
  6. publish   site/ + data/*.json deployed with actions/deploy-pages
GitHub Pages (vanilla HTML/CSS/JS, no build step, PWA)
  feed -> story detail -> outlet article (new tab)
```

**Publishing:** deploy via `actions/upload-pages-artifact` + `actions/deploy-pages`. Don't commit data to the repo every run; that bloats git history.

**Carrying state between runs:** private working data (`raw.json` with RSS descriptions, `state.json` with ETags and centroids) lives in the Actions cache (`actions/cache/restore` + `save`, key `pipeline-work-<run_id>`, restore prefix `pipeline-work-`). It is never committed or published, because RSS descriptions are other outlets' text. Only `stories.json` and `health.json` go to Pages. If the cache is missing, the run starts fresh. (Changed in Phase 3 from downloading state off Pages.)

**Caching:** cache the embedding model, the GGUF model, the Argos language packs and pip packages with `actions/cache`.

**Concurrency:** `concurrency: { group: pipeline, cancel-in-progress: false }`.

## Repo layout

```
SPEC.md
.github/workflows/pipeline.yml
pipeline/
  outlets.json        # source of truth for outlets
  fetch.py  dedupe.py  translate.py  group.py  write.py  publish.py
  checks.py           # neutral-headline checker
  run.py              # orchestrates steps 1-6
  prompts/headline.txt
tests/                # pytest, with fixtures/ of saved feeds
site/
  index.html  app.js  styles.css  manifest.webmanifest  sw.js
  icons/              # outlet favicons, <outlet_id>.png
  data/               # written by the pipeline at build time, not committed
```

## Data formats

**`pipeline/outlets.json`**

```json
[{
  "id": "reuters",
  "name": "Reuters",
  "feeds": ["https://..."],
  "region": "global",
  "country": "UK",
  "language": "en",
  "lean": "center",
  "lean_source": "AllSides",
  "lean_source_url": "https://...",
  "tags": [],
  "paywall": false,
  "wire": true,
  "enabled": true
}]
```

- `lean` is one of `left | lean_left | center | lean_right | right`.
- `region` is one of `us | europe | middle_east | asia | africa | americas | oceania | global`.
- `tags` may include `"state_funded"` or `"public_broadcaster"`.
- `wire: true` marks AP, Reuters and DW. Their headlines are the preferred fallback.
- Optional `via_google_news: true` marks outlets whose feed is a Google News site search (no usable feed of their own). Their titles end in " - <Outlet>", which fetch strips, and their links go through a Google redirect.
- Optional `fetch_ua: "browser"` marks feeds that only answer a browser user agent (approved at the Phase 2 gate; currently CBC).

**`data/stories.json`** (what the app reads)

```json
{
  "generated_at": "ISO-8601",
  "stories": [{
    "id": "s_<stable hash>",
    "headline": "…",
    "headline_source": "model | wire:<outlet_id> | nearest",
    "summary": "…",
    "region": "europe",
    "first_seen": "ISO",
    "updated": "ISO",
    "counts": {"left": 2, "lean_left": 4, "center": 5, "lean_right": 2, "right": 1},
    "blindspot": null,
    "items": [{
      "outlet_id": "bbc",
      "title": "original headline",
      "title_en": "translated or same",
      "url": "https://…",
      "published": "ISO"
    }]
  }]
}
```

- `blindspot` is `null`, `"left"` or `"right"`. The value names the side that is ignoring the story.
- `data/state.json` holds what the next run needs: story centroids (rounded floats), item-to-story map, feed ETags and Last-Modified values, the generation queue, and the last headline outlet count per story.
- `data/health.json` holds, per feed: last status, item count, error, and last success time.

## Rules

**Window and visibility**
- Items older than 48 hours are dropped.
- A story is shown when it has at least 3 distinct outlets. The setting "Show smaller stories" lowers that to 2.

**Stable story IDs**
- A new cluster joins an existing story when the cosine similarity of their centroids is ≥ the threshold tuned in Phase 4. Otherwise it becomes a new story.
- A story expires 48 hours after its last new item.

**When to regenerate a headline**
- On a new story.
- When the outlet count has grown at least 50% since the last generation.
- Otherwise keep the existing headline.

**Generation cap**
- At most `MAX_GEN_PER_RUN` (start at 20) model calls per run.
- Stories beyond the cap show the fallback headline and are queued for the next run, largest stories first.

**Neutral headline rules** (go in the prompt and are enforced in `checks.py`)
- At most 90 characters, plain present tense.
- No outlet names.
- No judgment words. Keep a banned list in `checks.py`, e.g. slams, blasts, destroys, chaos, radical, extremist, shocking, disaster, regime.
- A contested claim must be attributed ("X says…").
- A number may appear only if it appears in at least 2 source headlines.
- At least 2 named entities in the headline must appear in source headlines.

**Fallback**
- If the model output fails `checks.py`, use the first wire outlet's headline (AP, Reuters, DW).
- If no wire outlet covers the story, use the source headline nearest the cluster centroid.
- Record which one was used in `headline_source`.

**Summary**
- 2–3 sentences, only facts present in at least 2 outlets' inputs.
- If the model can't comply, use an empty string; the detail screen then hides the summary.

**Region**
- The model tags the region.
- If the tag is invalid, use the most common region among the outlets, ignoring `global`.

**Blindspot**
- Requires at least 5 outlets.
- left share = (left + lean_left) / (left + lean_left + right + lean_right).
- Share ≥ 0.85 means `"right"` (the right is ignoring it). Share ≤ 0.15 means `"left"`. Center outlets are excluded from the share.

**Feed ranking**
- score = distinct outlets × 0.5^(hours since updated / 6)

**Fetching**
- User-Agent: `NewsCompiler/1.0 (+https://maxisbusy-beep.github.io/news-compiler)`, except outlets with `fetch_ua: "browser"`, which get a standard browser user agent.
- Publication times in the future are clamped to the fetch time (Jerusalem Post's feed runs ahead).
- Send conditional GET headers. Timeout 15 seconds per feed. Retry once.
- A failing feed never fails the run.

## Phases

### Phase 1: Repo and skeleton
- **Scope:** repo structure above, a placeholder `site/index.html`, a Pages deploy workflow triggered manually (`workflow_dispatch`), pytest set up.
- **Tests:** a trivial test so CI runs.
- **Gate:** Max opens the Pages URL on his phone and sees the placeholder.

### Phase 2: Outlet list
- **Scope:** fill `outlets.json` with the 41 outlets from the plan doc.
  - Find each working RSS URL.
  - Check each lean against AllSides (US) or Media Bias/Fact Check / Ad Fontes (non-US). Record source and URL. Flag any that differ from the plan's starting lean.
  - Download favicons to `site/icons/` at 64 px or the nearest size available.
- **Tests:** schema validation for every entry. Every enabled outlet has an icon file.
- **Gate:**
  - At least 35 outlets have a working feed.
  - Lean disagreements are listed for Max to decide.
  - The lean mix is reported per region, and no region is one-sided.

### Phase 3: Fetch and dedupe
- **Scope:** `fetch.py`, `dedupe.py`, `run.py` steps 1–2 writing `raw.json`, and `health.json`.
- **Dedupe rule:** same canonical URL (strip tracking parameters), or the same outlet with title similarity ≥ 0.9.
- **Tests:**
  - With fixture feeds: duplicates removed, and a broken feed is logged without crashing.
  - Conditional-GET headers are stored and sent.
- **Gate:** two live runs back to back produce no duplicate items; feed health table shown.

### Phase 4: Translate and group
- **Scope:**
  - `translate.py` uses Argos packs for every non-English language in `outlets.json` and keeps the originals.
  - `group.py`: embeddings with `paraphrase-multilingual-MiniLM-L12-v2` on the original titles, plus English titles where translated. Agglomerative clustering on cosine distance, story-ID matching against `state.json`, and threshold tuning.
- **Tests:**
  - A fixture set of about 60 hand-labeled headlines.
  - Clustering accuracy on the fixture is reported, and a regression test locks it in.
  - Story IDs stay stable across two runs over the same items.
- **Gate:**
  - Max hand-checks 20 live stories; at least 18 are grouped correctly.
  - Report run time for this step.

### Phase 5: Neutral headlines and summaries
- **Scope:**
  - `write.py` with llama-cpp-python on CPU.
  - Benchmark 2–3 small instruct GGUF models (about 1.5–3B, Q4), e.g. Qwen2.5-3B-Instruct, Llama-3.2-3B-Instruct, Gemma-2-2B-it, or newer equivalents available at build time.
  - One call per story returns JSON: `{belongs: [item indexes], headline, summary, region}`. Items not in `belongs` are removed from the story and regrouped next run.
  - Then `checks.py`, the fallback chain, the generation cap and the queue.
- **Tests:**
  - `checks.py` passes and fails on fixture headlines, including banned words, length, unsupported numbers and missing entities.
  - The fallback order is correct.
  - The cap and queue work.
  - Malformed model JSON leads to fallback, never a crash.
- **Gate:**
  - A comparison table of the candidate models covering pass rate, seconds per story and Max's quality ratings. Max picks one.
  - Max reviews 20 headlines next to their outlet headlines for loaded wording.
  - A full run finishes in under 15 minutes.

### Phase 6: Front end
- **Scope:** `index.html`, `app.js`, `styles.css`, vanilla JS, mobile-first (designed at 375 px wide).
  - **Feed:** cards (headline, relative time, "N outlets", coverage bar, one tag), region chips, an "Updated X min ago" line, and pull to refresh.
  - **Detail:** headline, summary, larger bar with counts per lean, then outlet rows grouped Left → Center → Right. Each row shows icon, name, lean tag, original headline (translated, original on tap), time, and a lock icon if paywalled. Tapping a row opens the article in a new tab.
  - **Dark mode** via `prefers-color-scheme`.
  - Hash routing (`#/s/<id>`) so a story can be linked.
- **Tests:** JSON schema check on `stories.json`. A small Playwright smoke test at 375 px: feed renders, opening a story renders the outlet rows.
- **Gate:** Max uses it one-handed on his phone and approves the look.

### Phase 7: Extras
- **Scope:**
  - Blindspot tag.
  - Search across neutral and outlet headlines.
  - Saved stories (localStorage, wrapped in try/catch; they update while the story still exists).
  - Story timeline on detail (when each outlet first reported).
  - Settings sheet: outlet toggles, "Show smaller stories".
- **Tests:** blindspot math on fixtures; search; saved stories survive reload.
- **Gate:** a feed card still shows only headline, time, count, bar and one tag. Max approves.

### Phase 8: Automation
- **Scope:**
  - Schedule `*/30 * * * *`.
  - PWA (manifest plus a service worker that caches the shell and the last `stories.json`).
  - A hidden `#/health` page reading `health.json`.
  - A monthly keepalive step that commits a timestamp file, so GitHub doesn't disable the schedule after 60 idle days.
  - The workflow emails/notifies only on the failure of 3 runs in a row (GitHub's built-in failure notification is fine).
- **Gate:**
  - Runs unattended for 3 days.
  - Max can install it to his home screen.
  - The health page shows feed status.

## Out of scope (ask before adding)

User accounts, push notifications, comments, any paid service, and showing article text.
