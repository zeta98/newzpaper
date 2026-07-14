from __future__ import annotations

from datetime import datetime

from .models import Article

PAGE_ORDER = ["index", "uruguay", "region", "global", "last-week"]


def _label(items: list[dict], item_id: str) -> str:
    for item in items:
        if item["id"] == item_id:
            return item["label"]
    return item_id


def _article_line(a: Article) -> str:
    stamp = a.published_at.strftime("%Y-%m-%d %H:%M")
    return f"- **{a.text}** — [{a.author}]({a.url}) · {stamp}"


def _section_for_topic(articles: list[Article], topic_id: str, topics_config: dict) -> str:
    items = [a for a in articles if a.topic == topic_id]
    if not items:
        return ""
    label = _label(topics_config["categories"], topic_id)
    lines = [f"### {label}", ""]
    lines.extend(_article_line(a) for a in items)
    lines.append("")
    return "\n".join(lines)


def _region_page(articles: list[Article], region_id: str, topics_config: dict, title: str) -> str:
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
        for a in top:
            stamp = a.published_at.strftime("%Y-%m-%d %H:%M")
            lines.append(
                f"- [{region_labels.get(a.region, a.region)}] **{a.text}** — [{a.author}]({a.url}) · {stamp}"
            )
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
    now = now or datetime.utcnow()
    primary = buckets["primary"]

    return {
        "index.md": _index_page(buckets, topics_config, now),
        "uruguay.md": _region_page(primary, "uruguay", topics_config, "Uruguay"),
        "region.md": _region_page(primary, "region", topics_config, "Región (Sudamérica)"),
        "global.md": _region_page(primary, "global", topics_config, "Global"),
        "last-week.md": _last_week_page(buckets),
    }


def combine_markdown(pages: dict[str, str]) -> str:
    ordered_files = [f"{name}.md" for name in PAGE_ORDER]
    parts = []
    for filename in ordered_files:
        if filename in pages:
            parts.append(pages[filename])
    return "\n\n---\n\n".join(part.rstrip() for part in parts) + "\n"
