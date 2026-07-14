#!/usr/bin/env python3
"""Entrypoint: fetch -> pipeline -> render, writes markdown pages to output/ and
prints the combined markdown to stdout.

Usage:
    export ANTHROPIC_API_KEY=...
    python run.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from newzpaper.agent_fetch import fetch_twitter  # noqa: E402
from newzpaper.config import load_sources, load_topics  # noqa: E402
from newzpaper.pipeline import run_pipeline  # noqa: E402
from newzpaper.render import build_pages, combine_markdown  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main() -> str:
    sources = load_sources()
    topics = load_topics()
    now = datetime.now(timezone.utc)

    articles = fetch_twitter(sources, now=now, trailing_days=topics["time_windows"]["trailing_days"])
    buckets = run_pipeline(articles, topics, now=now)
    pages = build_pages(buckets, topics, now=now)

    OUTPUT_DIR.mkdir(exist_ok=True)
    for filename, content in pages.items():
        (OUTPUT_DIR / filename).write_text(content, encoding="utf-8")

    combined = combine_markdown(pages)
    print(combined)
    return combined


if __name__ == "__main__":
    main()
