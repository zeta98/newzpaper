"""Fetches recent X/Twitter posts using a Claude agent with web search, instead of
the X API. This avoids needing paid API access -- the agent searches the public web
(site:x.com / site:twitter.com) for the configured accounts and keywords and returns
structured results.

Swap-in for a real X API client later: keep the `fetch_twitter(...) -> list[Article]`
signature and nothing else in the pipeline needs to change.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic
from anthropic import Anthropic
from dateutil import parser as dateparser

from .models import Article

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("NEWZPAPER_MODEL", "claude-sonnet-5")

# web_search results (snippets from up to `max_web_searches` searches) count against
# this response's output tokens alongside the final JSON array. 8000 was too tight and
# risked truncating the JSON mid-array on a busy run; this leaves more headroom.
MAX_TOKENS = 16000

SYSTEM_PROMPT = """\
You are a sports news-gathering and reporting agent, not a copy-paste bot. You \
search the public web for recent posts on X (Twitter) from a given list of \
accounts and keywords, and turn them into short, neutral news items. You have \
access to a web_search tool -- use it to search site:x.com and site:twitter.com \
for the requested accounts and keywords.

Only include posts that are genuinely about the requested topics/regions. Prefer \
original news/updates over generic chatter. Skip anything you cannot find a real \
URL and timestamp for.

Editorial rules -- these matter as much as finding the posts:
- Write like a neutral wire-service reporter, not like the fan or club posting the \
original tweet. If the source is a club or federation's own account (marked \
"(club)" or "(federation)" in the account list below), treat its claims as that \
organization's own statement, not as established fact -- attribute it (e.g. "el \
club informó que...", "según Peñarol...") and strip partisan/promotional language \
(e.g. rewrite "nos robaron el partido" as "el club cuestionó el arbitraje").
- Distinguish confirmed news from rumor/speculation. Transfer talk, injury \
severity, and lineup news are frequently speculative -- if the post itself hedges \
("se rumorea", "trascendió", "podría", unconfirmed by an official source), set \
"status" to "rumor". Only use "status": "confirmed" for things stated as settled \
fact by an official source or corroborated by multiple independent outlets.
- Do not adopt exaggerated or inflammatory language from the original post, even \
when summarizing fan reaction.

When you are done searching, respond with ONLY a JSON array (no prose, no markdown \
fences) where each element has exactly these fields:
  "headline": a short, neutral headline (5-8 words, in Spanish) distinct from the \
body text -- what happened, not the tweet's own wording
  "text": a concise 1-3 sentence body, in Spanish, expanding on the headline with \
attribution per the editorial rules above
  "author": the account handle the post came from, e.g. "@AUFOficial"
  "url": direct link to the post
  "published_at": ISO 8601 timestamp (best estimate if exact time isn't shown, use \
the date at minimum)
  "topic": one of "football", "basketball", "other_sports", "other"
  "region": one of "uruguay", "region", "global"
  "source_type": one of "club", "federation", "journalist", "outlet" -- matches the \
type shown next to the account below, or your best judgment for posts found via \
keyword search rather than a listed account
  "status": "confirmed" or "rumor", per the editorial rules above

If you find nothing for a given account/keyword, simply omit it. Return an empty \
array [] if you find nothing at all.
"""


def _build_user_prompt(sources: dict, window_start: datetime, window_end: datetime) -> str:
    accounts = sources["twitter"]["seed_accounts"]
    keywords = sources["twitter"]["keywords"]

    account_lines = []
    for group, entries in accounts.items():
        formatted = ", ".join(f"{e['handle']} ({e['type']})" for e in entries)
        account_lines.append(f"- {group}: {formatted}")

    return f"""\
Search X/Twitter for posts published between {window_start.date().isoformat()} and \
{window_end.date().isoformat()} (most important: today and yesterday). Also do a \
lighter pass for a handful of noteworthy posts from the last 7 days that might \
otherwise be missed -- but keep that to a small minority of results.

Focus on sports news, especially football (soccer) and basketball, prioritized as:
1. Uruguay (main focus)
2. Rest of South America / region (small share)
3. Global (small share)

Accounts to check (type in parentheses -- see editorial rules for how to use it):
{chr(10).join(account_lines)}

Also search these keywords on X: {', '.join(keywords)}

Return results as the JSON array described in your instructions.
"""


def _extract_json_array(text: str) -> list[dict]:
    """Find and parse every top-level JSON array in `text`, concatenating their
    elements. Tolerates markdown fences and any prose the model adds despite
    being told not to.

    A greedy `\\[.*\\]` regex breaks as soon as trailing text contains its own
    brackets (e.g. "Nota: no encontre nada para [@handle]"), since it always
    matches to the *last* `]` in the string. Stopping at the *first*
    successfully-parsed array is also wrong: an incidental "[]" or similar in
    leading prose (e.g. "Grupos sin novedades: [].") would short-circuit before
    the real array. So instead: scan every `[` in the text, real-parse a JSON
    value from each, and collect elements from every array found. On a
    successful parse, resume scanning *after* it (not one character later) so a
    literal "[" inside a string value (e.g. a score like "[3-2]") is never
    mistaken for a new top-level array. Any non-conforming items this sweeps up
    from a stray/incidental array simply fail their per-item validation in
    fetch_twitter and get dropped there, so collecting broadly here is safe.
    """
    decoder = json.JSONDecoder()
    items: list[dict] = []
    pos = text.find("[")
    while pos != -1:
        try:
            value, end = decoder.raw_decode(text, pos)
        except (json.JSONDecodeError, ValueError):
            pos = text.find("[", pos + 1)
            continue
        if isinstance(value, list):
            items.extend(value)
        pos = text.find("[", end)
    return items


def fetch_twitter(
    sources: dict,
    now: datetime | None = None,
    trailing_days: int = 7,
    max_web_searches: int = 15,
) -> list[Article]:
    """Fetch recent Uruguay/region/global sports posts from X via a search-capable
    Claude agent. Requires ANTHROPIC_API_KEY in the environment.

    Degrades to an empty list (rather than raising) on API-level failures -- missing
    key, rate limits, connection errors, refusals -- since the rest of the pipeline
    and render already handle an empty article set fine, and a fetch outage shouldn't
    take down the whole run.
    """
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=trailing_days)
    user_prompt = _build_user_prompt(sources, window_start, now)
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_web_searches}]

    try:
        client = Anthropic()

        response = client.messages.create(
            model=DEFAULT_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=[{"role": "user", "content": user_prompt}],
        )

        # The web_search server-side loop auto-pauses (stop_reason "pause_turn")
        # after 10 tool iterations. max_web_searches defaults to 15, so this is
        # routinely hit -- resend the turn so the agent can finish, instead of
        # silently working from a truncated/empty response.
        continuations = 0
        while response.stop_reason == "pause_turn" and continuations < 4:
            response = client.messages.create(
                model=DEFAULT_MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=[
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": response.content},
                ],
            )
            continuations += 1

        if response.stop_reason == "pause_turn":
            logger.warning(
                "fetch_twitter: still paused after %d continuations; response may be incomplete",
                continuations,
            )
        elif response.stop_reason == "max_tokens":
            logger.warning(
                "fetch_twitter: response hit max_tokens (%d) -- the JSON array is likely "
                "truncated and will fail to parse; consider raising MAX_TOKENS further",
                MAX_TOKENS,
            )
    except (anthropic.AnthropicError, TypeError) as exc:
        # Most SDK failures (rate limits, connection errors, refusals) raise
        # AnthropicError subclasses, but a missing/invalid ANTHROPIC_API_KEY
        # surfaces as a plain TypeError from the request-signing layer instead
        # (confirmed against anthropic>=0.40.0's header-validation path) -- catch
        # both rather than letting auth misconfiguration crash the whole run.
        logger.error("fetch_twitter: Anthropic API call failed, returning no articles: %s", exc)
        return []

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
                    headline=item.get("headline", ""),
                    source_type=item.get("source_type", "outlet"),
                    status=item.get("status", "confirmed"),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("fetch_twitter: dropped malformed item %r (%s)", item, exc)
            continue

    logger.info(
        "fetch_twitter: extracted %d raw items, kept %d valid articles",
        len(raw_items),
        len(articles),
    )
    return articles
