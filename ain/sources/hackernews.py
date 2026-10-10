"""Hacker News adapter.

HN is a firehose, so this adapter pulls top/best stories, hydrates them, then
filters by AI-related keywords before they ever reach the scorer. That keeps the
item cap spent on relevant posts instead of whatever is trending.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..http import fetch_json
from ..models import parse_dt
from .base import Source, SourceError

API = "https://hacker-news.firebaseio.com/v0"

DEFAULT_FILTER = [
    "ai", "llm", "gpt", "claude", "gemini", "llama", "mistral", "openai",
    "anthropic", "deepmind", "machine learning", "neural", "transformer",
    "model", "agent", "inference", "rag", "embedding", "diffusion", "pytorch",
    "cuda", "gpu", "training", "dataset", "huggingface", "langchain", "mcp",
    "reasoning", "fine-tune", "finetune", "quantiz", "vector", "prompt",
    "copilot", "chatgpt", "deepseek", "qwen", "whisper", "stable diffusion",
]


class HackerNewsSource(Source):
    type_name = "hackernews"

    def fetch(self) -> list[Item]:
        feed = str(self.config.opt("feed", "topstories"))
        limit = int(self.config.opt("limit", 30))
        scan = int(self.config.opt("scan", 120))
        min_points = int(self.config.opt("min_points", 30))
        keywords = [str(k).lower() for k in self.config.opt("filter_keywords", DEFAULT_FILTER)]
        # HN throttles aggressively (observed 25s+ per item). A hard wall-clock
        # budget keeps one slow source from stalling the whole run: whatever was
        # hydrated in time is used, and the source still reports success.
        budget = float(self.config.opt("budget_seconds", 45))
        per_request = float(self.config.opt("request_timeout", 8))
        deadline = time.monotonic() + budget

        ids = fetch_json(
            f"{API}/{feed}.json", timeout=per_request, retries=1
        )
        if not isinstance(ids, list):
            raise SourceError("unexpected HN response for story list")

        candidates = [int(i) for i in ids[:scan]]

        def hydrate(story_id: int) -> dict | None:
            if time.monotonic() >= deadline:
                return None
            try:
                data = fetch_json(f"{API}/item/{story_id}.json",
                                  timeout=per_request, retries=0)
            except Exception:
                return None
            return data if isinstance(data, dict) else None

        # The pool is interrupted implicitly: hydrate() short-circuits once the
        # deadline passes, so slow responses drain instead of blocking forever.
        with ThreadPoolExecutor(max_workers=int(self.config.opt("workers", 12))) as pool:
            stories = list(pool.map(hydrate, candidates))

        items: list[Item] = []
        for story in stories:
            if not story or story.get("type") != "story" or story.get("dead"):
                continue
            title = str(story.get("title") or "")
            if not title:
                continue

            points = int(story.get("score") or 0)
            if points < min_points:
                continue

            haystack = f"{title} {story.get('text') or ''}".lower()
            if keywords and not any(k in haystack for k in keywords):
                continue

            published = None
            ts = story.get("time")
            if ts:
                dt = parse_dt(int(ts))
                if dt is not None:
                    published = dt.astimezone(timezone.utc).isoformat(timespec="seconds")

            url = story.get("url") or f"https://news.ycombinator.com/item?id={story.get('id')}"
            items.append(
                self.make_item(
                    title=title,
                    url=str(url),
                    summary=f"Hacker News discussion, {points} points, "
                    f"{int(story.get('descendants') or 0)} comments.",
                    published=published,
                    points=points,
                    comments=int(story.get("descendants") or 0),
                    tags=["hackernews"],
                    extra_id=f"hn-{story.get('id')}",
                )
            )
            if len(items) >= limit:
                break

        # Returning whatever we got beats failing: HN throttling is transient.
        return items
