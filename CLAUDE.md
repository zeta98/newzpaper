# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A news-aggregation workflow that fetches sports news (Uruguay football/basketball
as the main focus, with a smaller share of South American region and global
coverage) and renders it into a multi-page, multi-section markdown "newspaper."
There is no linter configured yet — verify changes with the commands below.

## Commands

```bash
# setup
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
export $(cat .env | xargs)

# run the full workflow (writes output/*.md, prints combined markdown to stdout)
python run.py

# run the test suite (pure functions only -- no network calls, no API key needed)
python3 -m unittest discover -s tests

# syntax-check after edits
python3 -m py_compile run.py src/newzpaper/*.py
```

`tests/` covers `pipeline.py`, `render.py`, and `agent_fetch.py`'s
`_extract_json_array()` with plain `unittest` (no new dependency) since all three
are pure functions with no I/O. Fetch's live-API path (`fetch_twitter()` itself,
past `_extract_json_array`) still has no automated coverage — when verifying that
end-to-end without hitting the live API, write a throwaway script that constructs
`Article` objects directly and runs them through `run_pipeline` → `build_pages` →
`combine_markdown`, same as the existing tests do.

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
   that was tried and is a known regression (covered by `tests/test_agent_fetch.py`).
   The web_search tool's server-side loop auto-pauses (`stop_reason ==
   "pause_turn"`) after 10 tool iterations; since `max_web_searches` defaults
   to 15, `fetch_twitter()` resends the turn (original prompt + paused
   `response.content` as the assistant turn) up to 4 times to let it finish,
   rather than silently working from a truncated response. `MAX_TOKENS` is
   16000 (raised from an earlier 8000, which risked truncating the JSON array
   mid-response since web_search result snippets count against the same
   response's output tokens) — if `stop_reason == "max_tokens"` is still hit,
   it's logged as a warning rather than silently parsed into an empty result.
   The whole API call is wrapped in `except (anthropic.AnthropicError,
   TypeError)`: most SDK failures raise `AnthropicError` subclasses, but a
   missing/invalid `ANTHROPIC_API_KEY` surfaces as a plain `TypeError` from the
   request-signing layer instead — either way, `fetch_twitter()` logs and
   returns `[]` rather than crashing `run.py`. This part of the code has never
   been exercised against the live API in development (no key was available)
   — treat it as higher-risk than the rest when debugging fetch issues, and
   check the logs (`fetch_twitter`'s logger) first.

   `SYSTEM_PROMPT` also carries editorial rules, not just extraction format:
   the agent is told to attribute claims to club/federation accounts rather
   than state them as fact (their handles are tagged `(club)`/`(federation)`
   in the account list built by `_build_user_prompt()`), and to mark
   speculative posts `"status": "rumor"` vs `"status": "confirmed"`. Each
   article also gets a `"headline"` distinct from its `"text"` body, and a
   `"source_type"` (`club`/`federation`/`journalist`/`outlet`).

2. **Pipeline** (`src/newzpaper/pipeline.py`) — pure functions, no I/O.
   `run_pipeline()` runs `normalize()` (fixes tz-naive `published_at` **in
   place**, coerces unknown topic/region/source_type/status values to their
   fallback, and clamps any future-dated `published_at` to `now` so a
   hallucinated/misparsed timestamp can't sort above genuinely-current
   articles) before `dedup()`, because `dedup()` sorts by `published_at` and a
   naive/aware datetime mix raises `TypeError` — don't reorder these.
   `dedup()` uses `SequenceMatcher` text similarity (O(n²), fine at this
   project's scale) to drop near-duplicate posts about the same story.
   `bucket_by_time()` splits into `primary` (today + yesterday) and a small
   capped `trailing` catch-up window (up to 7 days back); anything older is
   dropped. Both buckets are then sorted by region weight → topic priority →
   recency, using weights pulled from `config/topics.yaml`. `source_type`/
   `status` use a fixed vocabulary (`models.VALID_SOURCE_TYPES`/
   `VALID_STATUSES`), unlike topic/region which stay config-driven.

3. **Render** (`src/newzpaper/render.py`) — builds `index.md` (with a
   distinguished lead story plus a flat list for the rest, not a flat top-10),
   one page per region (`uruguay.md`, `region.md`, `global.md`), and
   `last-week.md`, plus a `combine_markdown()` that concatenates them in
   `PAGE_ORDER`. Page/section titles are derived from `config/topics.yaml`
   labels (via `_label()`), not hardcoded — keep it that way so config edits
   don't require code changes. All LLM/web-sourced text (`headline`, `text`,
   `author`) is passed through `_escape_md()` before interpolation into
   markdown bold/link syntax, and `url` through `_safe_url()` (only
   `http(s)://` is rendered as a clickable link) — this content is untrusted
   (arbitrary X post content), so don't remove the escaping to "simplify"
   `_article_line()`. Articles also get inline badges: `*rumor*` when
   `status == "rumor"`, and a `_fuente: el club_`-style note when
   `source_type` is `club`/`federation`, so readers can see when a claim
   traces back to an interested party rather than independent reporting.

### Config-driven extensibility

- `config/sources.yaml` — X accounts (grouped) and keywords for the fetcher.
  Each account is `{handle, type}`, where `type` is one of `club` /
  `federation` / `journalist` / `outlet` and gets passed to the fetch agent
  for attribution (see Fetch above). Add sources by editing this file only —
  but verify a new handle actually exists on X first; a wrong handle doesn't
  error, it just silently returns zero results for that source.
- `config/topics.yaml` — `categories` (topics, with `priority`), `regions`
  (with `weight`), and `time_windows` (`primary_days`, `trailing_days`,
  `trailing_max_items`). Drives classification fallback, sort order, and
  page/section labels throughout `pipeline.py` and `render.py`.
- Adding a new source **platform** (RSS, another API, etc.): write a fetcher
  function returning `list[Article]`, then merge its output with
  `fetch_twitter(...)`'s in `run.py` before `run_pipeline()` — nothing else
  needs to change.
