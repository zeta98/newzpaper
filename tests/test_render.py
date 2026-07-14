import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from newzpaper.models import Article  # noqa: E402
from newzpaper.render import (  # noqa: E402
    _escape_md,
    _safe_url,
    build_pages,
    combine_markdown,
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


class EscapeMdTests(unittest.TestCase):
    def test_escapes_markdown_control_characters(self):
        self.assertEqual(_escape_md("a*b_c[d]e`f\\g"), r"a\*b\_c\[d\]e\`f\\g")

    def test_plain_text_unaffected(self):
        self.assertEqual(_escape_md("Peñarol venció 2 a 1"), "Peñarol venció 2 a 1")

    def test_none_like_empty_string_is_safe(self):
        self.assertEqual(_escape_md(""), "")


class SafeUrlTests(unittest.TestCase):
    def test_allows_https(self):
        self.assertEqual(_safe_url("https://x.com/a/1"), "https://x.com/a/1")

    def test_allows_http(self):
        self.assertEqual(_safe_url("http://x.com/a/1"), "http://x.com/a/1")

    def test_rejects_javascript_scheme(self):
        self.assertIsNone(_safe_url("javascript:alert(1)"))

    def test_rejects_empty(self):
        self.assertIsNone(_safe_url(""))


class RenderInjectionTests(unittest.TestCase):
    def test_malicious_text_cannot_break_out_of_link_or_bold_syntax(self):
        a = make_article(
            headline="Titular](javascript:alert(1))[",
            text="cuerpo normal",
            author="@author",
        )
        pages = build_pages({"primary": [a], "trailing": []}, TOPICS_CONFIG, now=NOW)
        # the raw unescaped payload must not appear verbatim in any rendered page
        for content in pages.values():
            self.assertNotIn("](javascript:alert(1))[", content)

    def test_javascript_url_is_not_rendered_as_a_clickable_link(self):
        a = make_article(url="javascript:alert(1)")
        pages = build_pages({"primary": [a], "trailing": []}, TOPICS_CONFIG, now=NOW)
        combined = combine_markdown(pages)
        self.assertNotIn("(javascript:alert(1))", combined)


class BuildPagesTests(unittest.TestCase):
    def test_empty_buckets_render_placeholder_text(self):
        pages = build_pages({"primary": [], "trailing": []}, TOPICS_CONFIG, now=NOW)
        self.assertIn("Sin novedades", pages["index.md"])
        self.assertIn("Sin novedades", pages["uruguay.md"])
        self.assertIn("Nada relevante", pages["last-week.md"])

    def test_lead_story_is_the_top_ranked_article(self):
        lead = make_article(headline="Titular principal", region="uruguay", topic="football")
        other = make_article(headline="Otro titular", region="global", topic="football", url="https://x.com/b/1")
        pages = build_pages({"primary": [lead, other], "trailing": []}, TOPICS_CONFIG, now=NOW)
        index = pages["index.md"]
        self.assertIn("## Titular principal", index)
        self.assertIn("Otro titular", index)
        self.assertLess(index.index("Titular principal"), index.index("Otro titular"))

    def test_rumor_and_source_type_badges_appear(self):
        a = make_article(status="rumor", source_type="club")
        pages = build_pages({"primary": [a], "trailing": []}, TOPICS_CONFIG, now=NOW)
        self.assertIn("rumor", pages["uruguay.md"])
        self.assertIn("fuente: el club", pages["uruguay.md"])

    def test_combine_markdown_follows_page_order(self):
        pages = build_pages({"primary": [], "trailing": []}, TOPICS_CONFIG, now=NOW)
        combined = combine_markdown(pages)
        self.assertLess(combined.index("Newzpaper"), combined.index("Uruguay"))
        self.assertLess(combined.index("Última semana"), len(combined))


if __name__ == "__main__":
    unittest.main()
