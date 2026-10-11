"""Configuration loading: sources + interest profile.

Everything lives in TOML files under `config/` so you can tune the agent
without touching Python. `tomllib` is stdlib in 3.11+, so no dependency.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------
# Defaults. If a config file is missing or a key is absent, these apply, so the
# agent always runs out of the box.
# --------------------------------------------------------------------------

DEFAULT_STRONG = [
    "llm", "large language model", "transformer", "inference", "serving",
    "quantization", "quantized", "distillation", "fine-tuning", "finetuning",
    "lora", "rlhf", "dpo", "rag", "retrieval-augmented", "embedding",
    "vector database", "agent", "agentic", "tool use", "function calling",
    "evals", "evaluation benchmark", "benchmark", "context window",
    "kv cache", "attention", "mixture of experts", "moe", "speculative decoding",
    "vllm", "tensorrt", "cuda", "triton", "gpu", "throughput", "latency",
    "scaling law", "pretraining", "post-training", "open weights", "open-source model",
    "multimodal", "vision-language", "diffusion", "reinforcement learning",
    "reasoning model", "chain-of-thought", "distributed training", "checkpoint",
    "mcp", "model context protocol", "prompt engineering", "guardrails",
]

DEFAULT_MEDIUM = [
    "artificial intelligence", "machine learning", "deep learning", "neural network",
    "model", "dataset", "training", "inference cost", "api", "sdk", "framework",
    "open source", "release", "research", "paper", "safety", "alignment",
    "interpretability", "hallucination", "robustness", "privacy", "regulation",
    "robotics", "speech", "code generation", "copilot", "productivity",
]

DEFAULT_NEGATIVE = [
    "webinar", "register now", "sponsored", "podcast episode", "hiring",
    "we are hiring", "job opening", "giveaway", "black friday", "discount",
    "crypto", "nft", "stock price", "price prediction",
]


DEFAULT_CN_STRONG = [
    "大模型", "大语言模型", "语言模型", "多模态", "具身智能", "世界模型",
    "智能体", "推理", "微调", "蒸馏", "量化", "部署", "训练", "预训练",
    "神经网络", "深度学习", "机器学习", "人工智能", "生成式", "对齐",
    "评测", "基准", "算力", "显存", "推理加速", "开源模型", "开源",
    "检索增强", "向量数据库", "提示词", "上下文", "幻觉", "扩散模型",
    "自动驾驶", "机器人", "芯片", "国产", "端侧",
]

DEFAULT_CN_MEDIUM = [
    "模型", "算法", "数据集", "论文", "研究", "发布", "技术", "架构",
    "性能", "效率", "优化", "应用", "产品", "融资", "创业",
]

# Domain gate: the topic this agent actually tracks. With `require = true` an
# item must match one of these to be kept at all - unlike the keyword weights
# above, which merely reorder whatever came in. Kept deliberately narrow and
# unambiguous: "agent" in an RL paper is a different sense of the word, which is
# why the arXiv sources also narrow at the query level.
DEFAULT_DOMAIN = [
    "agent", "agents", "agentic", "multi-agent", "multiagent", "subagent",
    "sub-agent", "tool use", "tool-use", "tool calling", "function calling",
    "function-calling", "toolformer", "mcp", "model context protocol",
    "mcp server", "mcp client", "a2a", "agent2agent", "agent protocol",
    "agent skills", "coding agent", "code agent", "claude code", "codex",
    "computer use", "computer-use", "browser agent", "browser-use", "gui agent",
    "agent trajectory", "agent orchestration", "workflow orchestration",
    "context engineering", "agent memory", "long-term memory", "memory bank",
    "task decomposition", "self-reflection", "human-in-the-loop",
    "sandboxing", "prompt injection", "tool poisoning", "agent security",
    "agent safety", "agent evaluation", "agent evals", "agent benchmark",
    "gaia", "webarena", "osworld", "tau-bench", "swe-bench", "terminal-bench",
    "langgraph", "langchain", "llamaindex", "crewai", "autogen",
    "semantic kernel", "pydantic ai", "harness", "agent harness",
    "multi-agent system", "multi-agent systems",
    "智能体", "多智能体", "自主智能体", "代码智能体", "编程智能体", "浏览器智能体",
    "工具调用", "函数调用", "上下文工程", "上下文管理", "智能体框架",
    "工作流编排", "任务分解", "沙箱", "长期记忆", "提示注入", "权限管理",
]


@dataclass
class DomainGate:
    """Hard topical gate: keep only items that match at least one domain term.

    Distinct from keyword weighting on purpose. Weights decide ordering and can
    be dominated by source weight or engagement; this decides inclusion, and it
    applies to every source including `keep_all` curated blogs - otherwise a
    first-party blog whose output is mostly non-Agent would flood the report.
    """

    enabled: bool = False
    keywords: list[str] = field(default_factory=lambda: list(DEFAULT_DOMAIN))


@dataclass
class SourceConfig:
    id: str
    type: str
    name: str = ""
    url: str = ""
    category: str = "other"
    weight: float = 1.0
    enabled: bool = True
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.id

    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)


@dataclass
class ScoringConfig:
    half_life_hours: float = 48.0
    top_n: int = 30
    per_source_cap: int = 8
    min_score: float = 0.0
    strong_weight: float = 3.0
    medium_weight: float = 1.5
    negative_weight: float = -3.0
    max_age_days: float = 30.0


@dataclass
class Interests:
    strong: list[str] = field(default_factory=lambda: list(DEFAULT_STRONG))
    medium: list[str] = field(default_factory=lambda: list(DEFAULT_MEDIUM))
    negative: list[str] = field(default_factory=lambda: list(DEFAULT_NEGATIVE))
    # Chinese terms are matched as plain substrings, not word-boundary regex:
    # CJK text has no spaces, so \b style boundaries do not apply. Keeping them
    # in a separate list lets the scorer use the right strategy for each.
    cn_strong: list[str] = field(default_factory=lambda: list(DEFAULT_CN_STRONG))
    cn_medium: list[str] = field(default_factory=lambda: list(DEFAULT_CN_MEDIUM))
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    # Extra per-category boosts, e.g. {"paper": 1.5, "release": 2.0}
    category_boost: dict[str, float] = field(default_factory=dict)
    domain: DomainGate = field(default_factory=DomainGate)


@dataclass
class Config:
    root: Path
    sources: list[SourceConfig]
    interests: Interests
    reports_dir: Path
    data_dir: Path
    # Markdown export is off by default: the web UI is the primary interface and
    # reads the same archive. Kept as a switch (not deleted) so the export can be
    # re-enabled for sharing or GitHub browsing.
    write_markdown: bool = False

    @property
    def enabled_sources(self) -> list[SourceConfig]:
        return [s for s in self.sources if s.enabled]

    def source(self, source_id: str) -> SourceConfig | None:
        for s in self.sources:
            if s.id == source_id:
                return s
        return None


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_sources(path: Path) -> list[SourceConfig]:
    raw = _read_toml(path)
    entries = raw.get("source", [])
    if isinstance(entries, dict):  # single [[source]] written as [source]
        entries = [entries]

    out: list[SourceConfig] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("id") or "").strip()
        stype = str(entry.get("type") or "").strip()
        if not sid or not stype:
            continue
        if sid in seen:
            raise ValueError(f"duplicate source id in {path}: {sid}")
        seen.add(sid)

        reserved = {"id", "type", "name", "url", "category", "weight", "enabled"}
        options = {k: v for k, v in entry.items() if k not in reserved}
        out.append(
            SourceConfig(
                id=sid,
                type=stype,
                name=str(entry.get("name") or sid),
                url=str(entry.get("url") or ""),
                category=str(entry.get("category") or "other"),
                weight=float(entry.get("weight", 1.0)),
                enabled=bool(entry.get("enabled", True)),
                options=options,
            )
        )
    return out


def load_interests(path: Path) -> Interests:
    raw = _read_toml(path)
    keywords = raw.get("keywords", {}) or {}
    scoring_raw = raw.get("scoring", {}) or {}

    scoring = ScoringConfig()
    for key, value in scoring_raw.items():
        if hasattr(scoring, key):
            current = getattr(scoring, key)
            try:
                setattr(scoring, key, type(current)(value))
            except (TypeError, ValueError):
                pass

    def kw(name: str, fallback: list[str]) -> list[str]:
        values = keywords.get(name)
        if not values:
            return list(fallback)
        return [str(v).lower() for v in values if str(v).strip()]

    boost = raw.get("category_boost", {}) or {}

    def cn_kw(name: str, fallback: list[str]) -> list[str]:
        values = keywords.get(name)
        if not values:
            return list(fallback)
        return [str(v).strip() for v in values if str(v).strip()]

    # Domain gate. Its terms are folded into the strong list so a domain match
    # always carries strong-keyword weight when ranking - declaring five domain
    # terms in two places that could drift apart would be a config trap.
    domain_raw = raw.get("domain", {}) or {}
    domain_terms = [str(v).strip() for v in (domain_raw.get("keywords") or []) if str(v).strip()]
    domain_enabled = bool(domain_raw.get("require", bool(domain_terms)))

    strong = kw("strong", DEFAULT_STRONG)
    for term in domain_terms:
        low = term.lower()
        if low and low not in strong:
            strong.append(low)

    return Interests(
        strong=strong,
        medium=kw("medium", DEFAULT_MEDIUM),
        negative=kw("negative", DEFAULT_NEGATIVE),
        cn_strong=cn_kw("cn_strong", DEFAULT_CN_STRONG),
        cn_medium=cn_kw("cn_medium", DEFAULT_CN_MEDIUM),
        scoring=scoring,
        category_boost={str(k): float(v) for k, v in boost.items()},
        domain=DomainGate(
            enabled=domain_enabled,
            keywords=domain_terms or list(DEFAULT_DOMAIN),
        ),
    )


def load_config(root: Path | str) -> Config:
    root = Path(root).resolve()

    # Load .env before anything reads credentials. Real env vars take
    # precedence, so `AIN_LLM_API_KEY=x python3 -m ain fetch` still wins.
    from .env import load_dotenv

    load_dotenv(root)

    sources = load_sources(root / "config" / "sources.toml")
    if not sources:
        from .defaults import DEFAULT_SOURCES

        sources = DEFAULT_SOURCES
    interests = load_interests(root / "config" / "interests.toml")

    # Optional config/settings.toml for output toggles.
    settings = _read_toml(root / "config" / "settings.toml")
    output = settings.get("output", {}) or {}
    write_md = bool(output.get("write_markdown", False))

    return Config(
        root=root,
        sources=sources,
        interests=interests,
        reports_dir=root / "reports",
        data_dir=root / "data",
        write_markdown=write_md,
    )
