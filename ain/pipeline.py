"""The fetch -> dedupe -> score -> summarize pipeline."""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

from .config import Config
from .enrich import enrich, reuse_archived
from .models import Item, utcnow
from .scorer import Scorer
from .sources import SourceError, build_source
from .store import Store, run_lock
from .summarize import Summarizer

log = logging.getLogger(__name__)


@dataclass
class SourceResult:
    source_id: str
    ok: bool
    count: int = 0
    error: str = ""


@dataclass
class RunResult:
    items: list[Item] = field(default_factory=list)
    all_scored: list[Item] = field(default_factory=list)
    source_results: list[SourceResult] = field(default_factory=list)
    added: int = 0
    updated: int = 0
    duplicates: int = 0
    started_at: datetime = field(default_factory=utcnow)
    summarizer_mode: str = "extractive"
    content_stats: dict = field(default_factory=dict)
    cache_stats: dict = field(default_factory=dict)
    # LLM token usage for this run (empty when the LLM stage is off).
    llm_usage: dict = field(default_factory=dict)
    llm_skipped: int = 0

    @property
    def ok_sources(self) -> list[str]:
        return [r.source_id for r in self.source_results if r.ok]

    @property
    def failed_sources(self) -> list[SourceResult]:
        return [r for r in self.source_results if not r.ok]


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _archived_topics(config: Config, fallback_items: list[Item]) -> list[str]:
    """Topic names already present in the archive, most common first.

    Read from disk so topics persist across runs; if the archive is empty or
    unreadable, fall back to whatever is in this batch.
    """
    from .summarize import collect_topics

    try:
        archived = list(Store(config.data_dir).load().values())
    except Exception:
        archived = []
    topics = collect_topics(archived)
    if not topics:
        topics = collect_topics(fallback_items)
    return topics[:40]


def dedupe(items: list[Item]) -> tuple[list[Item], int]:
    """Drop same-story repeats across sources, keeping the highest-signal copy."""
    by_title: dict[str, Item] = {}
    by_url: dict[str, Item] = {}
    dropped = 0
    result: list[Item] = []

    for item in items:
        key = _normalize_title(item.title)
        url_key = (item.url or "").split("?")[0].rstrip("/")

        existing = by_title.get(key) if key else None
        if existing is None and url_key:
            existing = by_url.get(url_key)

        if existing is not None:
            dropped += 1
            # Prefer the copy with engagement data / a higher source weight.
            if (item.points or 0) > (existing.points or 0):
                result[result.index(existing)] = item
                by_title[key] = item
                by_url[url_key] = item
            continue

        result.append(item)
        if key:
            by_title[key] = item
        if url_key:
            by_url[url_key] = item

    return result, dropped


def run(
    config: Config,
    *,
    use_llm: bool = False,
    top_n: int | None = None,
    per_source_cap: int | None = None,
    min_score: float | None = None,
    only_sources: list[str] | None = None,
    max_workers: int = 6,
    dry_run: bool = False,
    no_content: bool = False,
) -> RunResult:
    sources = config.enabled_sources
    if only_sources:
        wanted = set(only_sources)
        unknown = wanted - {s.id for s in config.sources}
        if unknown:
            raise ValueError(f"unknown source id(s): {', '.join(sorted(unknown))}")
        sources = [s for s in sources if s.id in wanted]

    if not sources:
        raise ValueError("no enabled sources to fetch (check config/sources.toml)")

    result = RunResult()

    # ---- fetch --------------------------------------------------------
    def fetch_one(src_cfg) -> tuple[SourceResult, list[Item]]:
        try:
            found = build_source(src_cfg).fetch()
            return SourceResult(src_cfg.id, True, len(found)), found
        except SourceError as exc:
            return SourceResult(src_cfg.id, False, 0, str(exc)), []
        except Exception as exc:  # adapter bug should not kill the run
            log.debug("source %s raised", src_cfg.id, exc_info=True)
            return SourceResult(src_cfg.id, False, 0, f"{type(exc).__name__}: {exc}"), []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_one, s): s for s in sources}
        for future in as_completed(futures):
            src_result, found = future.result()
            result.source_results.append(src_result)
            if found:
                result.items.extend(found)

    result.source_results.sort(key=lambda r: r.source_id)

    # ---- dedupe -------------------------------------------------------
    merged, result.duplicates = dedupe(result.items)

    # ---- score --------------------------------------------------------
    scorer = Scorer(config.interests)
    scorer.score_all(merged)

    # Relevance gate. Needed for firehoses (HN, arXiv) where an unrelated post
    # could ride source/engagement bonuses into the report. Curated first-party
    # blogs (OpenAI/Anthropic/DeepMind) publish rarely and are relevant by
    # definition, so they opt out via `keep_all = true` - otherwise a major
    # model launch whose title matches no keyword gets silently dropped.
    keep_all = {s.id for s in config.sources if s.opt("keep_all", False)}

    def passes(item: Item) -> bool:
        return item.source_id in keep_all or scorer.relevance_only(item) > 0

    relevant = [i for i in merged if passes(i)]
    result.all_scored = relevant

    selected = scorer.select(
        relevant,
        top_n=top_n,
        per_source_cap=per_source_cap,
        min_score=min_score,
        exempt_sources=keep_all,
    )

    # ---- full text ----------------------------------------------------
    # Only the selected items are enriched: following every link would mean
    # 250+ requests per run. Doing this before summarising lets the LLM read the
    # real article instead of a one-line teaser.
    #
    # Archive reuse comes first: an article already fetched in an earlier run
    # keeps its body and learning cards, so a re-run does not re-download pages
    # or re-pay for LLM calls on unchanged items.
    if not dry_run:
        try:
            result.cache_stats = reuse_archived(selected, Store(config.data_dir).load())
        except Exception as exc:
            log.debug("archive reuse failed: %s", exc)

    if not no_content:
        result.content_stats = enrich(
            selected,
            max_workers=int(os.environ.get("AIN_CONTENT_WORKERS", "6")),
        )

    # ---- summarize ----------------------------------------------------
    summarizer = Summarizer(use_llm=use_llm)
    result.summarizer_mode = summarizer.mode
    # Topics already used in the archive are fed back so the model reuses its
    # own vocabulary across days; that is what lets the topic page aggregate.
    summarizer.summarize(selected, known_topics=_archived_topics(config, merged))
    result.llm_usage = dict(summarizer.usage)
    result.llm_skipped = summarizer.llm_skipped

    result.items = selected

    # ---- persist ------------------------------------------------------
    if not dry_run:
        # The lock is taken only for the write. Fetching happens outside it, so a
        # slow source does not block another process from recording its results.
        with run_lock(config.data_dir, wait=float(os.environ.get("AIN_LOCK_WAIT", "120"))):
            store = Store(config.data_dir)
            result.added, result.updated = store.merge(merged)
            store.record_run(
                {
                    "ok_sources": result.ok_sources,
                    "failed": {r.source_id: r.error for r in result.failed_sources},
                    "fetched": len(result.items),
                    "added": result.added,
                    "updated": result.updated,
                    "selected": len(selected),
                    # The curated set, in report order. Recorded explicitly
                    # because scores decay with time, so "which items were
                    # curated that day" cannot be recomputed after the fact.
                    "selected_ids": [i.id for i in selected],
                    # A run limited to a subset of sources is a debug/partial run
                    # and must not become the headline digest - otherwise
                    # `fetch --sources X -n 3` would silently replace today's
                    # curated set.
                    "partial": bool(only_sources),
                    "summarizer": result.summarizer_mode,
                    "llm_usage": result.llm_usage,
                    "llm_skipped": result.llm_skipped,
                    "content": result.content_stats,
                    "cache": result.cache_stats,
                }
            )
            # Ledger is written outside the items lock scope but still inside the
            # run, so spend is recorded even if nothing new was archived.
            if result.llm_usage.get("calls"):
                store.record_usage(
                    {
                        "op": "fetch",
                        "model": summarizer.model,
                        "calls": result.llm_usage.get("calls", 0),
                        "prompt_tokens": result.llm_usage.get("prompt_tokens", 0),
                        "completion_tokens": result.llm_usage.get("completion_tokens", 0),
                        "items": len(selected),
                        "skipped": result.llm_skipped,
                    }
                )
    return result
