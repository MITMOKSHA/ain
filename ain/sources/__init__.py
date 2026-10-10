"""Source registry: maps a config `type` string to an adapter class."""

from __future__ import annotations

from ..config import SourceConfig
from .arxiv import ArxivSource
from .base import FeedSource, Source, SourceError
from .hackernews import HackerNewsSource
from .html_list import HtmlListSource
from .huggingface import HuggingFaceBlogSource, HuggingFaceModelsSource
from .reddit import RedditSource

REGISTRY: dict[str, type[Source]] = {
    "rss": FeedSource,
    "feed": FeedSource,
    "atom": FeedSource,
    "arxiv": ArxivSource,
    "hackernews": HackerNewsSource,
    "hn": HackerNewsSource,
    "html_list": HtmlListSource,
    "hf_models": HuggingFaceModelsSource,
    "hf_blog": HuggingFaceBlogSource,
    "reddit": RedditSource,
}


def build_source(config: SourceConfig) -> Source:
    cls = REGISTRY.get(config.type)
    if cls is None:
        known = ", ".join(sorted(REGISTRY))
        raise SourceError(f"unknown source type '{config.type}' (known: {known})")
    return cls(config)


__all__ = ["REGISTRY", "build_source", "Source", "SourceError"]
