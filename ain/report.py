"""Markdown report rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import Item

CATEGORY_LABELS = {
    "paper": "论文 / 研究",
    "vendor": "大厂发布 / 工程博客",
    "community": "社区热帖",
    "release": "开源 / 模型发布",
    "news": "行业动态",
    "cn": "中文资讯",
    "other": "其他",
}

CATEGORY_ORDER = ["vendor", "release", "cn", "paper", "community", "news", "other"]

LEVEL_LABELS = {
    "intro": "入门",
    "intermediate": "进阶",
    "advanced": "深入",
}


def _fmt_date(item: Item) -> str:
    dt = item.published_dt
    if dt is None:
        return "日期未知"
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d %H:%M")


def _age_label(item: Item, now: datetime) -> str:
    hours = item.age_hours(now)
    if hours is None:
        return ""
    if hours < 1:
        return "刚刚"
    if hours < 24:
        return f"{hours:.0f} 小时前"
    return f"{hours / 24:.0f} 天前"


def _short_authors(authors: list[str], limit: int = 3) -> str:
    if not authors:
        return ""
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " 等"


def _why(item: Item) -> str:
    for reason in item.reasons:
        if reason.startswith("why:"):
            return reason[4:].strip()
    return ""


def render_markdown(
    items: list[Item],
    *,
    now: datetime | None = None,
    title: str = "AI 前沿日报",
    source_results=None,
    duplicates: int = 0,
    summarizer_mode: str = "extractive",
) -> str:
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone()
    lines: list[str] = []

    lines.append(f"# {title} · {local_now.strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(
        f"> 生成时间 {local_now.strftime('%Y-%m-%d %H:%M')} · "
        f"共 {len(items)} 条 · 摘要模式 `{summarizer_mode}`"
        + (f" · 去重 {duplicates} 条" if duplicates else "")
    )
    lines.append("")

    if not items:
        lines.append("今天没有筛出达到阈值的条目。可以放宽 `config/interests.toml` 里的打分阈值。")
        lines.append("")
        return "\n".join(lines)

    # ---- 速览 ----
    lines.append("## 速览")
    lines.append("")
    for item in items[:10]:
        date = item.published_dt
        stamp = date.astimezone().strftime("%m-%d") if date else "--"
        lines.append(f"- `{stamp}` **[{item.title}]({item.url})** — {item.source_name}")
    if len(items) > 10:
        lines.append(f"- …其余 {len(items) - 10} 条见下方分类")
    lines.append("")

    # ---- grouped detail ----
    grouped: dict[str, list[Item]] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    ordered = [c for c in CATEGORY_ORDER if c in grouped]
    ordered += [c for c in grouped if c not in CATEGORY_ORDER and c != "other"]
    if "other" in grouped:
        ordered.append("other")

    for category in ordered:
        group = grouped[category]
        label = CATEGORY_LABELS.get(category, category)
        lines.append(f"## {label} ({len(group)})")
        lines.append("")

        for idx, item in enumerate(group, 1):
            lines.append(f"### {idx}. [{item.title}]({item.url})")
            meta = [f"**来源**: {item.source_name}", f"**时间**: {_fmt_date(item)}"]
            age = _age_label(item, now)
            if age:
                meta.append(f"({age})")
            lines.append(" · ".join(meta))

            facts: list[str] = [f"**评分**: {item.score:.2f}"]
            if item.points:
                facts.append(f"**热度**: {item.points} points")
            if item.stars:
                facts.append(f"**stars/likes**: {item.stars}")
            if item.comments:
                facts.append(f"**评论**: {item.comments}")
            authors = _short_authors(item.authors)
            if authors:
                facts.append(f"**作者**: {authors}")
            lines.append(" · ".join(facts))

            why = _why(item)
            if why:
                lines.append(f"> 💡 {why}")

            summary = (item.summary or "").strip()
            if summary and summary != item.title:
                lines.append("")
                lines.append(summary.replace("\n", " ").strip())

            # ---- learning cards (LLM stage) ----
            if item.concepts:
                lines.append("")
                lines.append("**可以学到：**")
                lines.append("")
                for card in item.concepts:
                    name = card.get("name", "")
                    what = card.get("what", "")
                    how = card.get("how", "")
                    lines.append(f"- **{name}** — {what}")
                    if how:
                        lines.append(f"  - 工程上：{how}")

            if item.topics:
                lines.append("")
                lines.append(f"主题: {', '.join(item.topics)}")

            if item.level:
                lines.append(f"难度: {LEVEL_LABELS.get(item.level, item.level)}")

            if item.matched_keywords:
                kws = ", ".join(f"`{k}`" for k in item.matched_keywords[:10])
                lines.append("")
                lines.append(f"命中关键词: {kws}")

            # Show the article body when there is no summary beyond the title,
            # so a report entry is never just a bare link. Skipped when concept
            # cards exist: those are the useful part, and dumping the raw body
            # underneath would just be noise.
            body = (item.content or "").strip()
            thin_summary = not summary or summary == item.title or len(summary) < 60
            if body and thin_summary and not item.concepts:
                lines.append("")
                lines.append("<details><summary>正文节选</summary>")
                lines.append("")
                lines.append(body[:1500].replace("\n", " ").strip())
                lines.append("")
                lines.append("</details>")

            lines.append("")

    # ---- source health ----
    if source_results:
        lines.append("---")
        lines.append("")
        lines.append("## 信源状态")
        lines.append("")
        lines.append("| 信源 | 状态 | 条数 | 说明 |")
        lines.append("| --- | --- | --- | --- |")
        for res in source_results:
            status = "✅" if res.ok else "❌"
            note = "" if res.ok else res.error.replace("|", "/")[:110]
            lines.append(f"| `{res.source_id}` | {status} | {res.count} | {note} |")
        lines.append("")

    return "\n".join(lines)


def write_report(
    items: list[Item],
    reports_dir: Path,
    *,
    now: datetime | None = None,
    title: str = "AI 前沿日报",
    source_results=None,
    duplicates: int = 0,
    summarizer_mode: str = "extractive",
    filename: str | None = None,
) -> Path:
    now = now or datetime.now(timezone.utc)
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    content = render_markdown(
        items,
        now=now,
        title=title,
        source_results=source_results,
        duplicates=duplicates,
        summarizer_mode=summarizer_mode,
    )

    path = reports_dir / (filename or f"{now.astimezone().strftime('%Y-%m-%d')}.md")
    path.write_text(content, encoding="utf-8")
    return path
