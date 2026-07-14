"""Fetches recent X/Twitter posts using a Claude agent with web search, instead of
the X API. This avoids needing paid API access -- the agent searches the public web
(site:x.com / site:twitter.com) for the configured accounts and keywords and returns
structured results.

Swap-in for a real X API client later: keep the `fetch_twitter(...) -> list[Article]`
signature and nothing else in the pipeline needs to change.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone

from anthropic import Anthropic
from dateutil import parser as dateparser

from .models import Article

DEFAULT_MODEL = os.environ.get("NEWZPAPER_MODEL", "claude-sonnet-5")

SYSTEM_PROMPT = """\
You are a news-gathering agent. You search the public web for recent posts on X \
(Twitter) from a given list of accounts and keywords, and report back structured \
results. You have access to a web_search tool -- use it to search site:x.com and \
site:twitter.com for the requested accounts and keywords.

Only include posts that are genuinely about the requested topics/regions. Prefer \
original news/updates over generic chatter. Skip anything you cannot find a real \
URL and timestamp for.

When you are done searching, respond with ONLY a JSON array (no prose, no markdown \
fences) where each element has exactly these fields:
  "author": the account handle, e.g. "@AUFOficial"
  "url": direct link to the post
  "text": a concise 1-3 sentence summary of the post content, in Spanish
  "published_at": ISO 8601 timestamp (best estimate if exact time isn't shown, use \
the date at minimum)
  "topic": one of "football", "basketball", "other_sports", "other"
  "region": one of "uruguay", "region", "global"

If you find nothing for a given account/keyword, simply omit it. Return an empty \
array [] if you find nothing at all.
"""


def _build_user_prompt(sources: dict, window_start: datetime, window_end: datetime) -> str:
    accounts = sources["twitter"]["seed_accounts"]
    keywords = sources["twitter"]["keywords"]

    account_lines = []
    for group, handles in accounts.items():
        account_lines.append(f"- {group}: {', '.join(handles)}")

    return f"""\
Search X/Twitter for posts published between {window_start.date().isoformat()} and \
{window_end.date().isoformat()} (most important: today and yesterday). Also do a \
lighter pass for a handful of noteworthy posts from the last 7 days that might \
otherwise be missed -- but keep that to a small minority of results.

Focus on sports news, especially football (soccer) and basketball, prioritized as:
1. Uruguay (main focus)
2. Rest of South America / region (small share)
3. Global (small share)

Accounts to check:
{chr(10).join(account_lines)}

Also search these keywords on X: {', '.join(keywords)}

Return results as the JSON array described in your instructions.
"""


def _extract_json_array(text: str) -> list[dict]:
    text = text.strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    return json.loads(match.group(0))


def fetch_twitter(
    sources: dict,
    now: datetime | None = None,
    trailing_days: int = 7,
    max_web_searches: int = 15,
) -> list[Article]:
    """Fetch recent Uruguay/region/global sports posts from X via a search-capable
    Claude agent. Requires ANTHROPIC_API_KEY in the environment.
    """
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=trailing_days)

    client = Anthropic()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_web_searches}],
        messages=[{"role": "user", "content": _build_user_prompt(sources, window_start, now)}],
    )

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    raw_items = _extract_json_array("\n".join(text_parts))

    articles: list[Article] = []
    for item in raw_items:
        try:
            published_at = dateparser.parse(item["published_at"])
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            articles.append(
                Article(
                    source="twitter",
                    author=item.get("author", "unknown"),
                    url=item["url"],
                    text=item["text"],
                    published_at=published_at,
                    topic=item.get("topic", "other"),
                    region=item.get("region", "global"),
                )
            )
        except (KeyError, ValueError, TypeError):
            continue

    return articles
