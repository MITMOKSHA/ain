"""Reddit adapter (r/MachineLearning, r/LocalLLaMA, ...).

Disabled by default: reddit.com blocks most datacenter/direct traffic. Enable it
in config once you have a proxy or use an OAuth token.
"""

from __future__ import annotations

from ..http import fetch_json
from .base import Source, SourceError


class RedditSource(Source):
    type_name = "reddit"

    def fetch(self) -> list[Item]:
        subreddit = str(self.config.opt("subreddit", "MachineLearning"))
        listing = str(self.config.opt("listing", "top"))
        window = str(self.config.opt("time", "day"))
        limit = int(self.config.opt("limit", 25))
        min_score = int(self.config.opt("min_score", 20))

        url = (
            f"https://www.reddit.com/r/{subreddit}/{listing}.json"
            f"?t={window}&limit={limit}"
        )
        headers = {"Accept": "application/json"}
        token = self.config.opt("access_token")
        if token:
            headers["Authorization"] = f"bearer {token}"

        data = fetch_json(url, timeout=30, retries=2, headers=headers)
        if not isinstance(data, dict):
            raise SourceError("unexpected Reddit response")

        children = ((data.get("data") or {}).get("children")) or []
        items: list[Item] = []
        for child in children:
            post = (child or {}).get("data") or {}
            if not isinstance(post, dict) or post.get("stickied"):
                continue
            score = int(post.get("score") or 0)
            if score < min_score:
                continue

            title = str(post.get("title") or "")
            if not title:
                continue

            permalink = f"https://www.reddit.com{post.get('permalink') or ''}"
            body = str(post.get("selftext") or "")[:1200]
            items.append(
                self.make_item(
                    title=title,
                    url=str(post.get("url_overridden_by_dest") or permalink),
                    summary=f"{body}\n\n(Reddit r/{subreddit}, {score} upvotes, "
                    f"{int(post.get('num_comments') or 0)} comments)".strip(),
                    published=_reddit_dt(post.get("created_utc")),
                    points=score,
                    comments=int(post.get("num_comments") or 0),
                    tags=[f"r/{subreddit}", str(post.get("link_flair_text") or "")],
                    extra_id=str(post.get("name") or post.get("id") or permalink),
                )
            )
        return items


def _reddit_dt(value) -> str | None:
    from ..models import parse_dt
    from datetime import timezone

    dt = parse_dt(value)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None
