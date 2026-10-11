"""Rule-based relevance scoring.

Two independent signals are combined:

  relevance  - how well the title/summary matches your interest keywords
  freshness  - exponential decay on publication age (half-life from config)

Final score = (relevance * freshness) + source_weight_bonus + engagement_bonus

Keyword matching uses word boundaries so "ai" does not match "said", and
multi-word phrases are matched on the raw text.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

from .config import Interests
from .html import to_text
from .models import Item, utcnow


def _is_cjk(term: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in term)


def _compile(keywords: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        if _is_cjk(kw):
            # CJK has no word separators, so lookaround boundaries would never
            # match. Plain substring matching is the correct strategy here.
            pattern = re.compile(re.escape(kw))
        else:
            kw = kw.lower()
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])")
        compiled.append((kw, pattern))
    return compiled


class Scorer:
    def __init__(self, interests: Interests):
        self.interests = interests
        self._strong = _compile(interests.strong)
        self._medium = _compile(interests.medium)
        self._negative = _compile(interests.negative)
        self._cn_strong = _compile(interests.cn_strong)
        self._cn_medium = _compile(interests.cn_medium)
        self._domain = _compile(interests.domain.keywords)
        self.cfg = interests.scoring

    def in_domain(self, item: Item) -> bool:
        """Hard topical gate: is this item about the tracked domain at all?

        Checked against the **title**, not title+summary. That is deliberate and
        was measured: a media recap whose summary happens to mention "Codex" (a
        model roundup) is not an Agent story, while a real Agent story almost
        always says so in its title. Widening this to the summary let through
        roughly a third of the curated-source noise in testing.

        Sources that already narrow at the query level (arXiv, whose query
        matches on the abstract) opt out via `domain_exempt` instead, so they are
        not double-filtered on a field the query already covered.

        Unlike a score threshold this cannot be outvoted by source weight or
        engagement points, which is the whole reason it exists.
        """
        if not self.interests.domain.enabled:
            return True
        text = f"{item.title} {' '.join(item.tags)}".lower()
        return any(pattern.search(text) for _, pattern in self._domain)

    def _match_all(
        self, text: str, title_text: str
    ) -> tuple[float, list[str]]:
        """Score keyword hits. Shared by score() and relevance_only()."""
        matched: list[str] = []
        relevance = 0.0

        for kw, pattern in self._strong:
            if pattern.search(text):
                matched.append(kw)
                # A title hit is worth clearly more than a body-only hit.
                relevance += self.cfg.strong_weight * (1.6 if pattern.search(title_text) else 1.0)

        for kw, pattern in self._medium:
            if pattern.search(text):
                matched.append(kw)
                relevance += self.cfg.medium_weight * (1.4 if pattern.search(title_text) else 1.0)

        # Chinese terms: same weighting, matched by substring.
        for kw, pattern in self._cn_strong:
            if pattern.search(text):
                matched.append(kw)
                relevance += self.cfg.strong_weight * (1.6 if pattern.search(title_text) else 1.0)

        for kw, pattern in self._cn_medium:
            if pattern.search(text):
                matched.append(kw)
                relevance += self.cfg.medium_weight * (1.4 if pattern.search(title_text) else 1.0)

        for kw, pattern in self._negative:
            if pattern.search(text):
                relevance += self.cfg.negative_weight
                matched.append(f"-{kw}")

        return relevance, matched

    def score(self, item: Item, now: datetime | None = None) -> Item:
        now = now or utcnow()
        text = f"{item.title} {item.summary} {' '.join(item.tags)}".lower()
        title_text = item.title.lower()

        relevance, matched = self._match_all(text, title_text)
        reasons: list[str] = []
        for kw in matched:
            if kw.startswith("-"):
                reasons.append(f"penalty:{kw[1:]}")

        # Category boost from config (e.g. papers and releases weigh more).
        boost = self.interests.category_boost.get(item.category, 0.0)
        if boost:
            relevance += boost
            reasons.append(f"category:{item.category}+{boost:g}")

        # Long-tail keyword diversity: many distinct hits is a strong signal.
        # Penalty markers are excluded - they are not relevance evidence.
        positives = [k for k in matched if not k.startswith("-")]
        distinct = len(set(positives))
        if distinct >= 5:
            relevance *= 1.25
            reasons.append(f"breadth:{distinct} terms")

        # ---- freshness ------------------------------------------------
        age = item.age_hours(now)
        if age is None:
            freshness = 0.5  # unknown date: neither rewarded nor buried
            reasons.append("no-date")
        elif age < 0:
            freshness = 1.0  # clock skew / scheduled posts
        else:
            half_life = max(self.cfg.half_life_hours, 1.0)
            freshness = 0.5 ** (age / half_life)
            if age > 24 * self.cfg.max_age_days:
                freshness *= 0.1
                reasons.append(f"stale:{age / 24:.0f}d")

        base = relevance * freshness

        # ---- source weight --------------------------------------------
        # Folded in gently so a high-weight source cannot drown relevance.
        source_bonus = (item.source_weight - 1.0) * 1.5
        if source_bonus:
            reasons.append(f"source:{item.source_name}")

        # ---- engagement -----------------------------------------------
        engagement = 0.0
        if item.points:
            engagement += min(math.log10(max(item.points, 1) + 1) * 1.2, 4.0)
        if item.comments:
            engagement += min(math.log10(max(item.comments, 1) + 1) * 0.6, 2.0)
        if item.stars:
            engagement += min(math.log10(max(item.stars, 1) + 1) * 0.8, 3.0)

        item.score = round(base + source_bonus + engagement, 3)
        item.matched_keywords = sorted(set(positives))
        item.reasons = reasons
        return item

    def score_all(self, items: list[Item], now: datetime | None = None) -> list[Item]:
        now = now or utcnow()
        return [self.score(i, now) for i in items]

    def relevance_only(self, item: Item) -> float:
        """Keyword score without freshness - used for the strict relevance gate."""
        text = f"{item.title} {item.summary} {' '.join(item.tags)}".lower()
        relevance, _ = self._match_all(text, item.title.lower())
        return relevance

    def select(
        self,
        items: list[Item],
        *,
        top_n: int | None = None,
        per_source_cap: int | None = None,
        min_score: float | None = None,
        exempt_sources: set[str] | None = None,
    ) -> list[Item]:
        """Rank and cap, guaranteeing no single source monopolises the report.

        `exempt_sources` (curated first-party blogs) skip the min_score cutoff:
        their output is relevant by definition, and a low score there only
        reflects an older publish date, not irrelevance.
        """
        top_n = top_n if top_n is not None else self.cfg.top_n
        per_source_cap = per_source_cap if per_source_cap is not None else self.cfg.per_source_cap
        min_score = min_score if min_score is not None else self.cfg.min_score
        exempt_sources = exempt_sources or set()

        ranked = sorted(items, key=lambda i: i.score, reverse=True)
        chosen: list[Item] = []
        counts: dict[str, int] = {}

        for item in ranked:
            if item.score <= min_score and item.source_id not in exempt_sources:
                continue
            if counts.get(item.source_id, 0) >= per_source_cap:
                continue
            chosen.append(item)
            counts[item.source_id] = counts.get(item.source_id, 0) + 1
            if len(chosen) >= top_n:
                break
        return chosen
