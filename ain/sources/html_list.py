"""Generic HTML listing-page adapter.

Vendor blogs without RSS (Anthropic, Meta AI) all render a list of article links
with a date nearby. Rather than write one brittle scraper per site, this adapter
takes a link-path pattern plus a date pattern and extracts both from the raw
HTML. It is intentionally conservative: if nothing matches it raises, so the
source shows up as failed instead of silently contributing junk.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ..html import to_text
from ..http import fetch_text
from .base import Source, SourceError

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_human_date(text: str) -> str | None:
    """Parse 'Sep 23, 2026' / 'September 23, 2026' / ISO dates."""
    text = to_text(text).strip()
    if not text:
        return None

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
            return dt.isoformat(timespec="seconds")
        except ValueError:
            return None

    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    if m:
        month = _MONTHS.get(m.group(1)[:3].lower())
        if month:
            try:
                dt = datetime(int(m.group(3)), month, int(m.group(2)), tzinfo=timezone.utc)
                return dt.isoformat(timespec="seconds")
            except ValueError:
                return None

    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", text)
    if m:
        month = _MONTHS.get(m.group(2)[:3].lower())
        if month:
            try:
                dt = datetime(int(m.group(3)), month, int(m.group(1)), tzinfo=timezone.utc)
                return dt.isoformat(timespec="seconds")
            except ValueError:
                return None
    return None


class HtmlListSource(Source):
    type_name = "html_list"

    def fetch(self) -> list[Item]:
        if not self.config.url:
            raise SourceError(f"source '{self.id}' has no url")

        pattern = str(self.config.opt("link_pattern", ""))
        if not pattern:
            raise SourceError(f"source '{self.id}' needs link_pattern")

        limit = int(self.config.opt("limit", 20))
        drop = [str(d).lower() for d in self.config.opt("exclude", []) or []]
        date_window = int(self.config.opt("date_window", 600))

        text = fetch_text(self.config.url, timeout=30, retries=2)
        link_re = re.compile(pattern, re.I)

        items: list[Item] = []
        seen: set[str] = set()

        for match in link_re.finditer(text):
            href = match.group("href") if "href" in (match.groupdict() or {}) else match.group(1)
            if not href:
                continue
            from urllib.parse import urljoin

            url = urljoin(self.config.url, href)
            if url in seen:
                continue
            seen.add(url)

            # Anchor text is the title when the regex captured it.
            title = ""
            groups = match.groupdict() or {}
            if groups.get("title"):
                title = to_text(groups["title"])
            if not title:
                # Fall back to the nearest following text run.
                tail = text[match.end(): match.end() + 400]
                title = to_text(re.sub(r"^[^>]*>", "", tail))[:180].strip()
            if not title or len(title) < 8:
                continue
            if any(d in title.lower() or d in url.lower() for d in drop):
                continue

            # Date: prefer one captured in the regex, else look just before the link.
            published = None
            if groups.get("date"):
                published = parse_human_date(groups["date"])
            if not published:
                window = text[max(0, match.start() - date_window): match.start()]
                published = parse_human_date(window[-260:])

            items.append(
                self.make_item(
                    title=title,
                    url=url,
                    summary=title,
                    published=published,
                    tags=[self.config.category],
                    extra_id=url,
                )
            )
            if len(items) >= limit:
                break

        if not items:
            raise SourceError(
                f"no entries matched link_pattern on {self.config.url} "
                "(page layout probably changed)"
            )
        return items
