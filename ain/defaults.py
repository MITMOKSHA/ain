# Fallback source list, used only if config/sources.toml is missing.

from __future__ import annotations

from .config import SourceConfig

_RAW = [
    ("arxiv-cs-ai", "arxiv", "arXiv cs.AI", "paper", 1.2),
    ("openai-news", "rss", "OpenAI News", "vendor", 1.5),
    ("deepmind-blog", "rss", "Google DeepMind", "vendor", 1.4),
    ("google-ai-blog", "rss", "Google AI Blog", "vendor", 1.2),
    ("hn-ai", "hackernews", "Hacker News (AI)", "community", 1.0),
]


class _Cfg(SourceConfig):
    pass


def _build() -> list[SourceConfig]:
    out: list[SourceConfig] = []
    for sid, stype, name, category, weight in _RAW:
        options = {}
        if stype == "arxiv":
            options = {"categories": ["cs.AI", "cs.LG", "cs.CL"], "limit": 60}
        elif stype == "rss":
            urls = {
                "openai-news": "https://openai.com/news/rss.xml",
                "deepmind-blog": "https://deepmind.google/blog/rss.xml",
                "google-ai-blog": "https://blog.google/technology/ai/rss/",
            }
            options = {"url": urls.get(sid, "")}
        out.append(
            SourceConfig(
                id=sid,
                type=stype,
                name=name,
                url=options.pop("url", ""),
                category=category,
                weight=weight,
                options=options,
            )
        )
    return out


DEFAULT_SOURCES: list[SourceConfig] = _build()
