"""Source adapter base class + a tolerant RSS/Atom parser.

Feeds in the wild are messy. This parser handles RSS 2.0, Atom 1.0 and the
common namespace extensions (content:encoded, dc:date, media:*) rather than
assuming one shape.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import SourceConfig
from ..html import first_sentences, to_text
from ..http import HttpError, fetch_text
from ..models import Item, make_id, parse_dt

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
    "arxiv": "http://arxiv.org/schemas/atom",
}


class SourceError(RuntimeError):
    pass


@dataclass
class FeedEntry:
    title: str = ""
    link: str = ""
    summary: str = ""
    published: str | None = None
    authors: list[str] = None  # type: ignore[assignment]
    tags: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.authors is None:
            self.authors = []
        if self.tags is None:
            self.tags = []


class Source:
    """Base class. Subclasses implement `fetch`."""

    type_name = "base"

    def __init__(self, config: SourceConfig):
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def name(self) -> str:
        return self.config.name

    def fetch(self) -> list[Item]:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- helpers ---------------------------------------------------------
    def make_item(
        self,
        *,
        title: str,
        url: str,
        summary: str = "",
        published: str | None = None,
        authors: list[str] | None = None,
        tags: list[str] | None = None,
        points: int | None = None,
        comments: int | None = None,
        stars: int | None = None,
        extra_id: str = "",
    ) -> Item:
        title = clean_title(title)
        return Item(
            id=make_id(self.id, extra_id or url or title),
            title=title,
            url=url,
            source_id=self.id,
            source_name=self.name,
            category=self.config.category,
            source_weight=self.config.weight,
            published_at=published,
            summary=summary,
            authors=authors or [],
            tags=tags or [],
            points=points,
            comments=comments,
            stars=stars,
        )


_TITLE_JUNK_RE = re.compile(r"\s+")


def clean_title(title: str) -> str:
    title = to_text(title or "")
    title = _TITLE_JUNK_RE.sub(" ", title).strip()
    return title


# ---------------------------------------------------------------------------
# Feed parsing
# ---------------------------------------------------------------------------

def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return "".join(node.itertext()).strip()


def _find(node: ET.Element, *tags: str) -> ET.Element | None:
    """First matching child among `tags`.

    Note: never write `node.find(a) or node.find(b)` - an ElementTree Element is
    falsy when it has no children, so a valid leaf element would be skipped.
    """
    for tag in tags:
        found = node.find(tag, NS)
        if found is not None:
            return found
    return None


def _entry_link(entry: ET.Element) -> str:
    # Atom: <link href=... rel="alternate">
    best = ""
    for link in entry.findall("atom:link", NS) + entry.findall("link"):
        href = link.get("href")
        if not href:
            continue
        rel = (link.get("rel") or "alternate").lower()
        if rel == "alternate":
            return href.strip()
        if not best:
            best = href.strip()
    if best:
        return best

    # RSS: <link>http://...</link>
    for tag in ("link", "atom:link"):
        node = entry.find(tag, NS)
        if node is not None:
            value = _text(node) or (node.get("href") or "")
            if value:
                return value.strip()

    # Fallback: <guid isPermaLink="true">
    guid = entry.find("guid")
    if guid is not None:
        value = _text(guid)
        if value.startswith("http"):
            return value
    return ""


def _entry_summary(entry: ET.Element) -> str:
    for tag in ("content:encoded", "atom:summary", "summary", "description",
                "atom:content", "content"):
        node = entry.find(tag, NS)
        if node is not None:
            raw = _text(node)
            if raw:
                return first_sentences(to_text(raw, keep_newlines=False))
    return ""


def _entry_published(entry: ET.Element) -> str | None:
    for tag in ("atom:published", "published", "pubDate", "atom:updated",
                "updated", "dc:date"):
        node = entry.find(tag, NS)
        if node is not None:
            dt = parse_dt(_text(node))
            if dt is not None:
                return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    return None


def _entry_authors(entry: ET.Element) -> list[str]:
    out: list[str] = []
    for node in entry.findall("atom:author", NS) + entry.findall("author"):
        name_node = _find(node, "atom:name", "name")
        name = _text(name_node) if name_node is not None else _text(node)
        name = to_text(name).strip()
        if name:
            out.append(name)
    return out


def _entry_tags(entry: ET.Element) -> list[str]:
    out: list[str] = []
    for node in entry.findall("category"):
        term = node.get("term") or _text(node)
        term = (term or "").strip()
        if term:
            out.append(term)
    return out


def parse_feed(xml_text: str) -> list[FeedEntry]:
    """Parse RSS 2.0 or Atom into FeedEntry objects."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceError(f"malformed XML feed: {exc}") from exc

    tag = root.tag.split("}")[-1].lower()
    if tag == "feed":  # Atom
        nodes = root.findall("atom:entry", NS) or root.findall("entry")
    elif tag == "rss":
        channel = root.find("channel")
        nodes = channel.findall("item") if channel is not None else []
    elif tag == "rdf":  # RSS 1.0
        nodes = root.findall("item")
    else:
        # Unknown wrapper; try both shapes.
        nodes = root.findall(".//item") or root.findall(".//atom:entry", NS)
        if not nodes:
            raise SourceError(f"unsupported feed root element: {tag}")

    entries: list[FeedEntry] = []
    for node in nodes:
        link = _entry_link(node)
        title = clean_title(_text(_find(node, "atom:title", "title")))
        if not title and not link:
            continue
        entries.append(
            FeedEntry(
                title=title,
                link=link,
                summary=_entry_summary(node),
                published=_entry_published(node),
                authors=_entry_authors(node),
                tags=_entry_tags(node),
            )
        )
    return entries


class FeedSource(Source):
    """Any RSS/Atom feed."""

    type_name = "rss"

    def fetch(self) -> list[Item]:
        if not self.config.url:
            raise SourceError(f"source '{self.id}' has no url")
        text = fetch_text(
            self.config.url,
            timeout=float(self.config.opt("timeout", 25)),
            retries=int(self.config.opt("retries", 2)),
        )
        limit = int(self.config.opt("limit", 40))
        items: list[Item] = []
        for entry in parse_feed(text)[:limit]:
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
        return items
