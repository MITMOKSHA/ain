"""Core data model shared by every source, the scorer and the report renderer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_dt(value: Any) -> datetime | None:
    """Parse the many date shapes feeds emit. Returns tz-aware UTC or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Heuristic: seconds vs milliseconds since epoch.
        ts = float(value)
        if ts > 1e11:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None

    # Normalise a trailing "Z" and RFC-822 style offsets.
    candidate = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(candidate)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    # RFC 822 / 2822, e.g. "Mon, 03 Feb 2026 10:00:00 GMT" (stdlib email parser
    # is more forgiving than strptime for the long tail of feed formats).
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def make_id(*parts: str) -> str:
    """Stable content id so the same story is never reported twice."""
    digest = hashlib.sha1()
    for part in parts:
        digest.update((part or "").strip().lower().encode("utf-8", "replace"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


@dataclass
class Item:
    """A single piece of discovered content."""

    id: str
    title: str
    url: str
    source_id: str
    source_name: str
    category: str = "other"
    source_weight: float = 1.0

    published_at: str | None = None
    fetched_at: str = field(default_factory=lambda: iso(utcnow()) or "")

    summary: str = ""
    # Full article body, fetched by following the link (see content.py). Kept
    # separate from `summary` so the teaser is never lost if extraction fails.
    content: str = ""
    content_strategy: str = ""
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Engagement signals (different sources expose different ones).
    points: int | None = None
    comments: int | None = None
    stars: int | None = None

    # Populated by the scorer.
    score: float = 0.0
    matched_keywords: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    # Populated by the LLM stage (see summarize.py). `concepts` holds learning
    # cards: [{"name","what","how"}] - technology the reader can actually apply.
    # `topics` groups items across days into knowledge threads.
    concepts: list[dict] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    # Rough audience level for the concepts discussed: intro|intermediate|advanced
    level: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Item":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def published_dt(self) -> datetime | None:
        return parse_dt(self.published_at)

    def age_hours(self, now: datetime | None = None) -> float | None:
        dt = self.published_dt
        if dt is None:
            return None
        now = now or utcnow()
        return (now - dt).total_seconds() / 3600.0
