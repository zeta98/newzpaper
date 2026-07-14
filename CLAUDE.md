# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A news-aggregation workflow that fetches sports news (Uruguay football/basketball
as the main focus, with a smaller share of South American region and global
coverage) and renders it into a multi-page, multi-section markdown "newspaper."
There is no test suite or linter configured yet — verify changes with the
commands below.

## Commands

```bash
# setup
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
export $(cat .env | xargs)

# run the full workflow (writes output/*.md, prints combined markdown to stdout)
python run.py

# syntax-check after edits (no test suite exists; this is the closest to a build step)
python3 -m py_compile run.py src/newzpaper/*.py
```

There's no unit test harness. When verifying pipeline/render logic without
hitting the live API, write a throwaway script that constructs `Article`
objects directly and runs them through `run_pipeline` → `build_pages` →
`combine_markdown` (all pure, no network calls) — this is the pattern used
during development to validate changes offline.

## Architecture

Three-stage pipeline wired together by `run.py`: **fetch → pipeline → render**.
Everything downstream of fetch operates on the `Article` dataclass
(`src/newzpaper/models.py`), which is the seam for adding new sources.

1. **Fetch** (`src/newzpaper/agent_fetch.py`) — `fetch_twitter()` calls the
   Anthropic Messages API with the server-side `web_search_20250305` tool to
   search X/Twitter for the accounts/keywords in `config/sources.yaml`, instead
   of using the paid X API. The model is instructed to return a JSON array as
   its final text; `_extract_json_array()` scans for and concatenates *every*
   top-level JSON array in the response text (not just the first) because the
   model may emit incidental arrays (e.g. an empty `[]` in leading prose)
   before the real one — do not simplify this back to "grab the first array,"
   that was tried and is a known regression. The web_search tool's server-side
   loop auto-pauses (`stop_reason == "pause_turn"`) after 10 tool iterations;
   since `max_web_searches` defaults to 15, `fetch_twitter()` resends the
   turn (original prompt + paused `response.content` as the assistant turn) up
   to 4 times to let it finish, rather than silently working from a truncated
   response. This part of the code has never been exercised against the live
   API in development (no key was available) — treat it as higher-risk than
   the rest when debugging fetch issues.

2. **Pipeline** (`src/newzpaper/pipeline.py`) — pure functions, no I/O.
   `run_pipeline()` runs `normalize()` (fixes tz-naive `published_at` **in
   place**, coerces unknown topic/region ids to the config's fallback) before
   `dedup()`, because `dedup()` sorts by `published_at` and a naive/aware
   datetime mix raises `TypeError` — don't reorder these. `dedup()` uses
   `SequenceMatcher` text similarity (O(n²), fine at this project's scale) to
   drop near-duplicate posts about the same story. `bucket_by_time()` splits
   into `primary` (today + yesterday) and a small capped `trailing` catch-up
   window (up to 7 days back); anything older is dropped. Both buckets are
   then sorted by region weight → topic priority → recency, using weights
   pulled from `config/topics.yaml`.

3. **Render** (`src/newzpaper/render.py`) — builds `index.md`, one page per
   region (`uruguay.md`, `region.md`, `global.md`), and `last-week.md`, plus a
   `combine_markdown()` that concatenates them in `PAGE_ORDER`. Page/section
   titles are derived from `config/topics.yaml` labels (via `_label()`), not
   hardcoded — keep it that way so config edits don't require code changes.

### Config-driven extensibility

- `config/sources.yaml` — X accounts (grouped) and keywords for the fetcher.
  Add sources by editing this file only.
- `config/topics.yaml` — `categories` (topics, with `priority`), `regions`
  (with `weight`), and `time_windows` (`primary_days`, `trailing_days`,
  `trailing_max_items`). Drives classification fallback, sort order, and
  page/section labels throughout `pipeline.py` and `render.py`.
- Adding a new source **platform** (RSS, another API, etc.): write a fetcher
  function returning `list[Article]`, then merge its output with
  `fetch_twitter(...)`'s in `run.py` before `run_pipeline()` — nothing else
  needs to change.
