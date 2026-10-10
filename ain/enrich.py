"""Parallel full-text enrichment for selected items.

Fetching every item's article would mean 250+ requests per run. Only the items
that actually made the report are enriched, which keeps a run fast while making
the report itself readable.

Trade-off worth knowing: scoring still uses the feed teaser, not the full body.
Enriching before scoring would mean downloading everything, so relevance is
judged on the teaser and the body is used for reading (and for LLM summaries).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .content import fetch_article
from .models import Item

log = logging.getLogger(__name__)

# Sources whose pages are JS-rendered shells with no real body; following them
# wastes requests. They still contribute their feed teaser.
SKIP_HOSTS = (
    "news.ycombinator.com",
    "arxiv.org",
)


def _worth_fetching(item: Item) -> bool:
    if not item.url or not item.url.startswith("http"):
        return False
    if any(host in item.url for host in SKIP_HOSTS):
        return False
    # Already have a substantial body (e.g. feed carried full content).
    if len(item.content or "") > 800:
        return False
    return True


def reuse_archived(items: list[Item], archived: dict[str, Item]) -> dict[str, int]:
    """Copy previously fetched bodies/concepts onto freshly fetched items.

    Feed items are rebuilt from scratch every run, so without this step the same
    article would be re-downloaded (and, with --llm, re-billed) on every run for
    as long as it stays in the report window. Matching is by stable content id.
    """
    stats = {"content": 0, "concepts": 0}
    for item in items:
        old = archived.get(item.id)
        if old is None:
            continue
        if old.content and not item.content:
            item.content = old.content
            item.content_strategy = old.content_strategy
            stats["content"] += 1
        if old.concepts and not item.concepts:
            item.concepts = old.concepts
            item.topics = old.topics
            item.level = old.level
            if old.summary:
                item.summary = old.summary
            stats["concepts"] += 1
    return stats


def _effective_length(text: str) -> int:
    """Length in 'information units': CJK characters carry ~2x a Latin char.

    Measured on real extracts rather than assumed: Chinese text conveys roughly
    twice the meaning per character, so a flat character threshold would discard
    good CJK extracts while accepting thin English ones.
    """
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    other = len(text) - cjk
    return cjk * 2 + other


# Absolute floor only: below this, an extract is noise regardless of strategy.
MIN_UNITS = {
    "meta-description": 60,
    "default": 200,
}


def _accepts(result, item: Item) -> bool:
    """Decide whether an extract improves on what the feed already provided.

    The primary test is relative, not a magic number: does the extracted body
    carry more information than the teaser we already have? A meta description
    that beats a useless feed teaser (InfoQ sends "点击查看原文>") is worth
    keeping even though it is short by article-body standards.
    """
    if _effective_length(result.text) < MIN_UNITS.get(result.strategy, MIN_UNITS["default"]):
        return False
    existing = _effective_length(item.summary or "")
    if result.strategy == "meta-description":
        # Must be a clear improvement, not a marginal one.
        return _effective_length(result.text) > existing * 1.3
    return True


def enrich(
    items: list[Item],
    *,
    max_workers: int = 6,
    timeout: float = 25.0,
    max_chars: int = 6000,
) -> dict[str, int]:
    """Fetch and attach article bodies. Returns a small stats dict.

    Never raises: a failed article just keeps its feed teaser.
    """
    targets = [i for i in items if _worth_fetching(i)]
    stats = {"targets": len(targets), "ok": 0, "failed": 0,
             "skipped": len(items) - len(targets), "teaser_only": 0}
    if not targets:
        return stats

    def work(item: Item) -> tuple[Item, object]:
        return item, fetch_article(item.url, timeout=timeout, max_chars=max_chars)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(work, i) for i in targets]
        for future in as_completed(futures):
            try:
                item, result = future.result()
            except Exception as exc:  # defensive; work() already swallows
                log.debug("content enrichment failed: %s", exc)
                stats["failed"] += 1
                continue

            if result is None or not _accepts(result, item):
                stats["failed"] += 1
                continue

            item.content = result.text
            item.content_strategy = result.strategy
            stats["ok"] += 1
            if result.strategy == "meta-description":
                stats["teaser_only"] += 1

    return stats
