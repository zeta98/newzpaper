from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import Article

PAGE_ORDER = ["index", "uruguay", "region", "global", "last-week"]

# Escapes markdown control characters in untrusted (LLM/web-sourced) text before
# it's interpolated into bold/link syntax, so a post's text can't break out of its
# formatting or inject new markdown structure (e.g. a fake link) into the page.
_MD_ESCAPE_RE = re.compile(r"([\\`*_\[\]])")

_SOURCE_TYPE_NOTE = {
    "club": "fuente: el club",
    "federation": "fuente: la federación",
}


def _escape_md(text: str) -> str:
    return _MD_ESCAPE_RE.sub(r"\\\1", text or "")


def _safe_url(url: str) -> str | None:
    """Only http(s) URLs are rendered as clickable links; anything else (a
    javascript: scheme, a malformed value) is untrusted web-search output and is
    dropped rather than linked.
    """
    if url and (url.startswith("http://") or url.startswith("https://")):
        return url
    return None


def _label(items: list[dict], item_id: str) -> str:
    for item in items:
        if item["id"] == item_id:
            return item["label"]
    return item_id


def _byline(a: Article) -> str:
    author = _escape_md(a.author)
    url = _safe_url(a.url)
    return f"[{author}]({url})" if url else author


def _tags(a: Article, *, region_label: str | None = None) -> list[str]:
    tags = []
    if region_label:
        tags.append(f"[{region_label}]")
    if a.status == "rumor":
        tags.append("*rumor*")
    note = _SOURCE_TYPE_NOTE.get(a.source_type)
    if note:
        tags.append(f"_{note}_")
    return tags


def _article_line(a: Article) -> str:
    stamp = a.published_at.strftime("%Y-%m-%d %H:%M")
    headline = _escape_md(a.headline)
    text = _escape_md(a.text)
    tag_str = " ".join(_tags(a))
    tag_str = f" {tag_str}" if tag_str else ""
    body = f" — {text}" if text and text != headline else ""
    return f"- **{headline}**{tag_str}{body} — {_byline(a)} · {stamp}"


def _section_for_topic(articles: list[Article], topic_id: str, topics_config: dict) -> str:
    items = [a for a in articles if a.topic == topic_id]
    if not items:
        return ""
    label = _label(topics_config["categories"], topic_id)
    lines = [f"### {label}", ""]
    lines.extend(_article_line(a) for a in items)
    lines.append("")
    return "\n".join(lines)


def _region_page(articles: list[Article], region_id: str, topics_config: dict) -> str:
    title = _label(topics_config["regions"], region_id)
    region_articles = [a for a in articles if a.region == region_id]
    lines = [f"# {title}", ""]
    if not region_articles:
        lines.append("_Sin novedades en esta franja horaria._")
        return "\n".join(lines) + "\n"

    for category in topics_config["categories"]:
        section = _section_for_topic(region_articles, category["id"], topics_config)
        if section:
            lines.append(section)

    return "\n".join(lines).rstrip() + "\n"


def _lead_story(a: Article, region_labels: dict) -> str:
    stamp = a.published_at.strftime("%Y-%m-%d %H:%M")
    headline = _escape_md(a.headline)
    text = _escape_md(a.text)
    tag_str = " · ".join(_tags(a, region_label=region_labels.get(a.region, a.region)))

    lines = [f"## {headline}", "", tag_str, ""]
    if text and text != headline:
        lines.append(text)
        lines.append("")
    lines.append(f"{_byline(a)} · {stamp}")
    return "\n".join(lines)


def _index_line(a: Article, region_labels: dict) -> str:
    stamp = a.published_at.strftime("%Y-%m-%d %H:%M")
    headline = _escape_md(a.headline)
    tag_str = " ".join(_tags(a, region_label=region_labels.get(a.region, a.region)))
    tag_str = f" {tag_str}" if tag_str else ""
    return f"- **{headline}**{tag_str} — {_byline(a)} · {stamp}"


def _index_page(buckets: dict[str, list[Article]], topics_config: dict, now: datetime) -> str:
    primary = buckets["primary"]
    lines = [
        "# Newzpaper",
        "",
        f"_Actualizado: {now.strftime('%Y-%m-%d %H:%M UTC')}_",
        "",
        "Secciones: [Uruguay](uruguay.md) · [Región](region.md) · [Global](global.md) · [Última semana](last-week.md)",
        "",
        "## Titulares de hoy y ayer",
        "",
    ]
    top = primary[:10]
    if not top:
        lines.append("_Sin novedades por el momento._")
    else:
        region_labels = {r["id"]: r["label"] for r in topics_config["regions"]}
        lead, rest = top[0], top[1:]
        lines.append(_lead_story(lead, region_labels))
        if rest:
            lines.append("")
            lines.append("### Más titulares")
            lines.append("")
            lines.extend(_index_line(a, region_labels) for a in rest)
    lines.append("")
    return "\n".join(lines)


def _last_week_page(buckets: dict[str, list[Article]]) -> str:
    lines = ["# Última semana — no te lo pierdas", ""]
    trailing = buckets["trailing"]
    if not trailing:
        lines.append("_Nada relevante para destacar de los últimos días._")
        return "\n".join(lines) + "\n"
    lines.extend(_article_line(a) for a in trailing)
    lines.append("")
    return "\n".join(lines)


def build_pages(buckets: dict[str, list[Article]], topics_config: dict, now: datetime | None = None) -> dict[str, str]:
    now = now or datetime.now(timezone.utc)
    primary = buckets["primary"]

    return {
        "index.md": _index_page(buckets, topics_config, now),
        "uruguay.md": _region_page(primary, "uruguay", topics_config),
        "region.md": _region_page(primary, "region", topics_config),
        "global.md": _region_page(primary, "global", topics_config),
        "last-week.md": _last_week_page(buckets),
    }


def combine_markdown(pages: dict[str, str]) -> str:
    ordered_files = [f"{name}.md" for name in PAGE_ORDER]
    parts = []
    for filename in ordered_files:
        if filename in pages:
            parts.append(pages[filename])
    return "\n\n---\n\n".join(part.rstrip() for part in parts) + "\n"
