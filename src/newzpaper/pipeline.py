from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from .models import Article

VALID_TOPICS = {"football", "basketball", "other_sports", "other"}
VALID_REGIONS = {"uruguay", "region", "global"}

DUPLICATE_SIMILARITY_THRESHOLD = 0.82


def normalize(articles: list[Article]) -> list[Article]:
    """Safety net in case the fetcher returns a topic/region outside the known set."""
    for a in articles:
        if a.topic not in VALID_TOPICS:
            a.topic = "other"
        if a.region not in VALID_REGIONS:
            a.region = "global"
    return articles


def dedup(articles: list[Article]) -> list[Article]:
    """Drop near-duplicate posts about the same story, keeping the earliest one."""
    kept: list[Article] = []
    for a in sorted(articles, key=lambda x: x.published_at):
        is_dup = any(
            SequenceMatcher(None, a.text.lower(), k.text.lower()).ratio() >= DUPLICATE_SIMILARITY_THRESHOLD
            for k in kept
        )
        if not is_dup:
            kept.append(a)
    return kept


def bucket_by_time(
    articles: list[Article],
    now: datetime | None = None,
    primary_days: int = 2,
    trailing_days: int = 7,
    trailing_max_items: int = 5,
) -> dict[str, list[Article]]:
    """Split into "primary" (today + yesterday) and a small "trailing" catch-up
    bucket (up to trailing_days ago, capped at trailing_max_items). Anything older
    than trailing_days is dropped.
    """
    now = now or datetime.now(timezone.utc)
    primary_cutoff = now - timedelta(days=primary_days)
    trailing_cutoff = now - timedelta(days=trailing_days)

    primary, trailing = [], []
    for a in articles:
        published_at = a.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if published_at >= primary_cutoff:
            primary.append(a)
        elif published_at >= trailing_cutoff:
            trailing.append(a)

    trailing.sort(key=lambda x: x.published_at, reverse=True)
    return {"primary": primary, "trailing": trailing[:trailing_max_items]}


def priority_key(article: Article, region_weight: dict[str, int], topic_priority: dict[str, int]) -> tuple:
    return (
        -region_weight.get(article.region, 0),
        topic_priority.get(article.topic, 99),
        -article.published_at.timestamp(),
    )


def sort_articles(articles: list[Article], topics_config: dict) -> list[Article]:
    region_weight = {r["id"]: r["weight"] for r in topics_config["regions"]}
    topic_priority = {c["id"]: c["priority"] for c in topics_config["categories"]}
    return sorted(articles, key=lambda a: priority_key(a, region_weight, topic_priority))


def run_pipeline(articles: list[Article], topics_config: dict, now: datetime | None = None) -> dict[str, list[Article]]:
    tw = topics_config["time_windows"]
    articles = normalize(articles)
    articles = dedup(articles)
    buckets = bucket_by_time(
        articles,
        now=now,
        primary_days=tw["primary_days"],
        trailing_days=tw["trailing_days"],
        trailing_max_items=tw["trailing_max_items"],
    )
    buckets["primary"] = sort_articles(buckets["primary"], topics_config)
    buckets["trailing"] = sort_articles(buckets["trailing"], topics_config)
    return buckets
