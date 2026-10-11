"""Append-only JSONL store plus run bookkeeping.

The store is deliberately boring: one JSON object per line, keyed by a stable
content id. Re-running the agent merges instead of duplicating, so you can run
it as often as you like.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import Item, iso, utcnow


class LockBusy(RuntimeError):
    """Raised when another ain process already holds the run lock."""


@contextmanager
def run_lock(data_dir: Path, *, stale_after: float = 1800.0, wait: float = 0.0):
    """Cross-process lock so a cron fetch and a manual fetch never interleave.

    Two concurrent writers would otherwise race on items.jsonl (last writer wins,
    silently dropping the other run's updates). `stale_after` reclaims the lock if
    a previous run died without cleaning up.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".lock"
    deadline = time.monotonic() + wait
    acquired = False

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {iso(utcnow())}".encode())
            os.close(fd)
            acquired = True
            break
        except FileExistsError:
            # Reclaim a lock left behind by a crashed run.
            try:
                age = time.time() - lock_path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > stale_after:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise LockBusy(
                    f"另一个 ain 进程正在运行（锁文件 {lock_path}）。"
                    "如果你确定没有进程在跑，删掉它即可。"
                )
            time.sleep(0.5)

    try:
        yield
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except OSError:
                pass


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.items_path = self.data_dir / "items.jsonl"
        self.runs_path = self.data_dir / "runs.jsonl"
        # Append-only token ledger. The provider here exposes no balance or
        # usage API, so local accounting is the only way to answer "how much
        # have I spent".
        self.usage_path = self.data_dir / "usage.jsonl"
        self._items: dict[str, Item] | None = None

    # ---------------------------------------------------------------- items
    def load(self) -> dict[str, Item]:
        if self._items is not None:
            return self._items

        items: dict[str, Item] = {}
        if self.items_path.exists():
            with self.items_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        item = Item.from_dict(data)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        # A corrupt line should never take down the whole archive.
                        continue
                    items[item.id] = item
        self._items = items
        return items

    def merge(self, new_items: list[Item]) -> tuple[int, int]:
        """Merge items in. Returns (added, updated).

        Existing rows keep their original `fetched_at` but pick up fresher
        engagement numbers and any newly computed score/summary.
        """
        items = self.load()
        added = updated = 0

        for item in new_items:
            existing = items.get(item.id)
            if existing is None:
                items[item.id] = item
                added += 1
                continue

            changed = False
            if item.points is not None and item.points != existing.points:
                existing.points = item.points
                changed = True
            if item.comments is not None and item.comments != existing.comments:
                existing.comments = item.comments
                changed = True
            if item.stars is not None and item.stars != existing.stars:
                existing.stars = item.stars
                changed = True
            if item.summary and item.summary != existing.summary:
                existing.summary = item.summary
                changed = True
            if item.score and item.score != existing.score:
                existing.score = item.score
                existing.matched_keywords = item.matched_keywords
                existing.reasons = item.reasons
                changed = True
            # Enrichment output. Without these the fetched article bodies and
            # LLM learning cards would be recomputed (and re-billed) every run
            # and never survive into the archive.
            if item.content and item.content != existing.content:
                existing.content = item.content
                existing.content_strategy = item.content_strategy
                changed = True
            if item.concepts and item.concepts != existing.concepts:
                existing.concepts = item.concepts
                changed = True
            if item.topics and item.topics != existing.topics:
                existing.topics = item.topics
                changed = True
            if item.level and item.level != existing.level:
                existing.level = item.level
                changed = True
            if changed:
                updated += 1

        self.save()
        return added, updated

    def save(self) -> None:
        items = self.load()
        ordered = sorted(
            items.values(),
            key=lambda i: (i.published_at or i.fetched_at or ""),
            reverse=True,
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            self.items_path,
            "\n".join(item.to_json() for item in ordered) + ("\n" if ordered else ""),
        )

    def prune(self, keep) -> tuple[int, int]:
        """Drop items for which `keep(item)` is false. Returns (kept, removed).

        Needed because the archive accumulates rows written before the domain
        gate existed (or under a different config). Hiding them in the UI alone
        would leave stale rows feeding the search box and the topic threads.
        """
        items = self.load()
        removed = [item_id for item_id, item in items.items() if not keep(item)]
        for item_id in removed:
            del items[item_id]
        if removed:
            self.save()
        return len(items), len(removed)

    # ----------------------------------------------------------------- runs
    def record_run(self, record: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        record = {"ts": iso(utcnow()), **record}
        with self.runs_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_runs(self, limit: int = 200) -> list[dict]:
        """Run records, newest first. Corrupt lines are skipped."""
        if not self.runs_path.exists():
            return []
        records: list[dict] = []
        try:
            with self.runs_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return list(reversed(records[-limit:]))

    # --------------------------------------------------------------- usage
    def record_usage(self, record: dict) -> None:
        """Append one token-usage entry.

        Written even when a run is otherwise a no-op, because LLM spend happens
        regardless of whether new items were archived.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        entry = {"ts": iso(utcnow()), **record}
        with self.usage_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_usage(self, limit: int = 10000) -> list[dict]:
        """Usage entries, oldest first. Corrupt lines are skipped."""
        if not self.usage_path.exists():
            return []
        out: list[dict] = []
        try:
            with self.usage_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return out[-limit:]

    def usage_summary(self) -> dict:
        """Aggregate the ledger: totals, by day, by model, by operation."""
        entries = self.read_usage()
        totals = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        by_day: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        by_op: dict[str, dict] = {}

        def bump(bucket: dict, key: str, entry: dict) -> None:
            row = bucket.setdefault(key, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
            row["calls"] += int(entry.get("calls") or 0)
            row["prompt_tokens"] += int(entry.get("prompt_tokens") or 0)
            row["completion_tokens"] += int(entry.get("completion_tokens") or 0)

        for entry in entries:
            for key in totals:
                totals[key] += int(entry.get(key) or 0)
            ts = str(entry.get("ts") or "")
            bump(by_day, ts[:10] or "?", entry)
            bump(by_model, str(entry.get("model") or "?"), entry)
            bump(by_op, str(entry.get("op") or "fetch"), entry)

        return {
            "entries": len(entries),
            "totals": totals,
            "by_day": dict(sorted(by_day.items())),
            "by_model": by_model,
            "by_op": by_op,
            "first": entries[0].get("ts") if entries else None,
            "last": entries[-1].get("ts") if entries else None,
        }

    def last_seen(self, source_id: str) -> datetime | None:
        """Most recent successful fetch time for a source, if recorded."""
        if not self.runs_path.exists():
            return None
        latest: datetime | None = None
        with self.runs_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ok = rec.get("ok_sources") or []
                if source_id not in ok:
                    continue
                ts = rec.get("ts")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts)
                except ValueError:
                    continue
                if latest is None or dt > latest:
                    latest = dt
        return latest


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _term_pattern(term: str) -> "re.Pattern[str]":
    """Word-boundary pattern for a search term.

    Plain substring matching gives false positives on short terms: searching
    "rag" would also match "average". Terms containing punctuation (e.g. "c++",
    "gpt-4") fall back to literal matching since \\b does not apply.
    """
    import re

    if not term:
        return re.compile(r"$^")  # never matches
    if re.fullmatch(r"[a-z0-9_]+", term):
        return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")
    return re.compile(re.escape(term))


def search_items(items: list[Item], query: str) -> list[Item]:
    """AND-match all whitespace-separated terms across the searchable fields."""
    terms = [t for t in (query or "").lower().split() if t]
    if not terms:
        return list(items)

    patterns = [_term_pattern(t) for t in terms]
    out: list[Item] = []
    for item in items:
        haystack = " ".join([
            item.title,
            item.summary,
            item.source_name,
            item.category,
            " ".join(item.matched_keywords),
            " ".join(item.authors),
        ]).lower()
        if all(p.search(haystack) for p in patterns):
            out.append(item)
    return out
