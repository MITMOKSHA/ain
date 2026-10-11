# Fallback source list, used only if config/sources.toml is missing.
# Narrow on purpose: this agent tracks the Agent/智能体 domain, and the domain
# gate in config/interests.toml filters everything these sources return.

from __future__ import annotations

from .config import SourceConfig

_RAW = [
    ("arxiv-agents", "arxiv", "arXiv · Agent 方向", "paper", 1.6),
    ("anthropic-engineering", "html_list", "Anthropic Engineering", "vendor", 1.6),
    ("langchain-blog", "rss", "LangChain Blog", "vendor", 1.4),
    ("openai-news", "rss", "OpenAI News", "vendor", 1.5),
    ("deepmind-blog", "rss", "Google DeepMind", "vendor", 1.4),
    ("hn-ai", "hackernews", "Hacker News (Agent)", "community", 1.0),
]


class _Cfg(SourceConfig):
    pass


def _build() -> list[SourceConfig]:
    out: list[SourceConfig] = []
    for sid, stype, name, category, weight in _RAW:
        options = {}
        if stype == "arxiv":
            options = {
                "categories": ["cs.AI", "cs.CL", "cs.SE", "cs.MA"],
                "query": '(abs:"LLM agent" OR abs:"agentic" OR abs:"tool use" '
                         'OR abs:"function calling" OR abs:"multi-agent")',
                "limit": 60,
            }
        elif stype == "html_list":
            options = {
                "url": "https://www.anthropic.com/engineering",
                "link_pattern": 'href="(?P<href>/engineering/[A-Za-z0-9\\-]+)"[^>]*>'
                                '.*?<h[23][^>]*>(?P<title>[^<]{8,200})</h[23]>',
            }
        elif stype == "rss":
            urls = {
                "openai-news": "https://openai.com/news/rss.xml",
                "deepmind-blog": "https://deepmind.google/blog/rss.xml",
                "langchain-blog": "https://blog.langchain.com/rss.xml",
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
