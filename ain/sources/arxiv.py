"""arXiv adapter - talks to the official Atom API rather than the RSS mirror.

The API allows category filters, keyword search and a result cap, which lets
you keep the firehose narrow (cs.AI alone publishes hundreds of papers a day).
"""

from __future__ import annotations

from ..http import build_query, fetch_text
from .base import Source, SourceError, parse_feed

API = "https://export.arxiv.org/api/query"


class ArxivSource(Source):
    type_name = "arxiv"

    def fetch(self) -> list[Item]:
        categories: list[str] = list(self.config.opt("categories", []) or [])
        query: str = str(self.config.opt("query", "") or "")
        limit = int(self.config.opt("limit", 40))
        sort_by = str(self.config.opt("sort_by", "submittedDate"))

        clauses: list[str] = []
        if categories:
            clauses.append("(" + " OR ".join(f"cat:{c}" for c in categories) + ")")
        if query:
            clauses.append(f"({query})")
        search = " AND ".join(clauses) if clauses else "cat:cs.AI"

        url = build_query(
            API,
            {
                "search_query": search,
                "sortBy": sort_by,
                "sortOrder": "descending",
                "max_results": limit,
                "start": 0,
            },
        )
        text = fetch_text(
            url,
            timeout=float(self.config.opt("timeout", 40)),
            retries=int(self.config.opt("retries", 2)),
        )

        items: list[Item] = []
        for entry in parse_feed(text):
            if not entry.title:
                continue
            items.append(
                self.make_item(
                    title=entry.title,
                    url=entry.link,
                    summary=entry.summary,
                    published=entry.published,
                    authors=entry.authors,
                    tags=entry.tags,
                    extra_id=entry.link,
                )
            )
        if not items:
            raise SourceError("arXiv returned no entries")
        return items
