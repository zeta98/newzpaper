import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from newzpaper.models import Article  # noqa: E402
from newzpaper.pipeline import (  # noqa: E402
    bucket_by_time,
    dedup,
    normalize,
    run_pipeline,
    sort_articles,
)

TOPICS_CONFIG = {
    "categories": [
        {"id": "football", "label": "Fútbol", "priority": 1},
        {"id": "basketball", "label": "Básquetbol", "priority": 2},
        {"id": "other_sports", "label": "Otros deportes", "priority": 3},
        {"id": "other", "label": "Otras noticias", "priority": 4},
    ],
    "regions": [
        {"id": "uruguay", "label": "Uruguay", "weight": 3},
        {"id": "region", "label": "Región", "weight": 2},
        {"id": "global", "label": "Global", "weight": 1},
    ],
    "time_windows": {"primary_days": 2, "trailing_days": 7, "trailing_max_items": 5},
}

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def make_article(**overrides) -> Article:
    defaults = dict(
        source="twitter",
        author="@author",
        url="https://x.com/author/status/1",
        text="Texto de prueba",
        published_at=NOW,
        topic="football",
        region="uruguay",
    )
    defaults.update(overrides)
    return Article(**defaults)


class NormalizeTests(unittest.TestCase):
    def test_coerces_unknown_topic_and_region_to_fallback(self):
        a = make_article(topic="cricket", region="mars")
        normalize([a], TOPICS_CONFIG, now=NOW)
        self.assertEqual(a.topic, "other")
        self.assertEqual(a.region, "global")

    def test_coerces_unknown_source_type_and_status(self):
        a = make_article(source_type="fan_account", status="definitely_true")
        normalize([a], TOPICS_CONFIG, now=NOW)
        self.assertEqual(a.source_type, "outlet")
        self.assertEqual(a.status, "confirmed")

    def test_fixes_tz_naive_datetime(self):
        a = make_article(published_at=datetime(2026, 7, 14, 12, 0))
        normalize([a], TOPICS_CONFIG, now=NOW)
        self.assertIsNotNone(a.published_at.tzinfo)

    def test_clamps_future_dated_article_to_now(self):
        future = NOW + timedelta(days=30)
        a = make_article(published_at=future)
        normalize([a], TOPICS_CONFIG, now=NOW)
        self.assertEqual(a.published_at, NOW)

    def test_leaves_valid_past_dates_untouched(self):
        past = NOW - timedelta(hours=3)
        a = make_article(published_at=past)
        normalize([a], TOPICS_CONFIG, now=NOW)
        self.assertEqual(a.published_at, past)


class DedupTests(unittest.TestCase):
    def test_drops_near_duplicate_text_keeping_earliest(self):
        earlier = make_article(text="Peñarol venció a Nacional por 2 a 1 en el clásico", published_at=NOW)
        later = make_article(
            text="Peñarol venció a Nacional por 2 a 1 en el clasico",
            published_at=NOW + timedelta(minutes=5),
            url="https://x.com/other/status/2",
        )
        kept = dedup([later, earlier])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].published_at, NOW)

    def test_keeps_genuinely_different_articles(self):
        a = make_article(text="Peñarol venció a Nacional por 2 a 1", url="https://x.com/a/1")
        b = make_article(text="La selección uruguaya de básquetbol ganó en Brasil", url="https://x.com/b/1")
        self.assertEqual(len(dedup([a, b])), 2)


class BucketByTimeTests(unittest.TestCase):
    def test_splits_primary_and_trailing(self):
        today = make_article(published_at=NOW)
        last_week = make_article(published_at=NOW - timedelta(days=5))
        too_old = make_article(published_at=NOW - timedelta(days=30))
        buckets = bucket_by_time([today, last_week, too_old], now=NOW, primary_days=2, trailing_days=7)
        self.assertIn(today, buckets["primary"])
        self.assertIn(last_week, buckets["trailing"])
        self.assertNotIn(too_old, buckets["primary"])
        self.assertNotIn(too_old, buckets["trailing"])

    def test_trailing_is_capped_and_sorted_most_recent_first(self):
        articles = [
            make_article(published_at=NOW - timedelta(days=d), url=f"https://x.com/a/{d}")
            for d in range(3, 9)
        ]
        buckets = bucket_by_time(articles, now=NOW, primary_days=2, trailing_days=7, trailing_max_items=2)
        self.assertEqual(len(buckets["trailing"]), 2)
        self.assertTrue(buckets["trailing"][0].published_at > buckets["trailing"][1].published_at)


class SortArticlesTests(unittest.TestCase):
    def test_sorts_by_region_weight_then_topic_priority_then_recency(self):
        uy_football = make_article(region="uruguay", topic="football", published_at=NOW)
        uy_basket = make_article(region="uruguay", topic="basketball", published_at=NOW)
        global_football = make_article(region="global", topic="football", published_at=NOW)
        older_uy_football = make_article(region="uruguay", topic="football", published_at=NOW - timedelta(hours=5))

        ordered = sort_articles([global_football, older_uy_football, uy_basket, uy_football], TOPICS_CONFIG)
        self.assertEqual(
            ordered,
            [uy_football, older_uy_football, uy_basket, global_football],
        )


class RunPipelineTests(unittest.TestCase):
    def test_end_to_end_smoke(self):
        articles = [
            make_article(url="https://x.com/a/1"),
            make_article(url="https://x.com/a/1"),  # exact duplicate url -> different id path but same text
            make_article(region="global", topic="basketball", url="https://x.com/a/2"),
        ]
        buckets = run_pipeline(articles, TOPICS_CONFIG, now=NOW)
        self.assertIn("primary", buckets)
        self.assertIn("trailing", buckets)
        # the near-identical text articles should have been deduped down to one
        self.assertLessEqual(len(buckets["primary"]), 2)


if __name__ == "__main__":
    unittest.main()
