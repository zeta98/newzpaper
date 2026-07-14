# newzpaper

Fetches recent sports news (mainly Uruguayan football & basketball, with a smaller
share of regional and global coverage) and aggregates it into a multi-page,
multi-section markdown "newspaper."

## How it works

1. **Fetch** (`src/newzpaper/agent_fetch.py`) — a Claude agent with the `web_search`
   tool searches X/Twitter for the accounts and keywords in `config/sources.yaml`
   and returns structured posts (author, url, text, timestamp, topic, region). This
   is used instead of the X API so no paid API access is required.
2. **Pipeline** (`src/newzpaper/pipeline.py`) — normalizes topic/region values,
   drops near-duplicate posts about the same story, buckets articles into
   "primary" (today + yesterday) and a small "trailing" catch-up window (up to 7
   days back, capped at 5 items), and sorts everything so Uruguay + football/
   basketball surface first.
3. **Render** (`src/newzpaper/render.py`) — builds one markdown page per
   region (`uruguay.md`, `region.md`, `global.md`), a `last-week.md` catch-up
   digest, and an `index.md` overview linking them together. Also returns the
   whole thing combined into a single markdown string.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY
export $(cat .env | xargs)
```

## Run

```bash
python run.py
```

Writes `output/index.md`, `output/uruguay.md`, `output/region.md`,
`output/global.md`, `output/last-week.md`, and prints the combined markdown to
stdout (this is also returned by `main()` if you import `run.py` as a module).

## Adding sources

- **More X accounts/keywords**: edit `config/sources.yaml` — no code changes.
- **A new topic/region weighting**: edit `config/topics.yaml` — categories and
  regions there drive both classification fallback and page/section layout.
- **A whole new platform** (RSS, a news API, a specific outlet): add a fetcher
  module under `src/newzpaper/` that returns `list[Article]` (see
  `models.py`), then merge its output with `fetch_twitter(...)`'s in `run.py`
  before calling `run_pipeline`. Nothing downstream needs to change.

## Notes / next steps

- Currently a standalone script — run it manually, or wire it into cron/GitHub
  Actions/etc. later once the source mix and output format feel right.
- The agent-based fetch is non-deterministic and rate/cost-bound by web search
  usage (`max_web_searches` in `fetch_twitter`); tune as needed.
