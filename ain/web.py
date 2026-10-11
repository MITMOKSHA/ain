"""Local web UI: browse, filter and search the item archive.

Built on http.server so there is nothing to install and no database. It reads
the same data/items.jsonl the CLI writes, so `ain fetch` and the UI always agree.

    python -m ain serve          # http://127.0.0.1:8848
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Config
from .models import Item
from .scorer import Scorer
from .store import Store, search_items

WEB_DIR = Path(__file__).resolve().parent / "web"

# Keywords too generic to make useful topics - every item matches them, so they
# would produce one giant meaningless bucket. Kept broad on purpose: with the
# domain gate on, everything here is already an Agent story, so a "大语言模型"
# thread would swallow the whole report instead of partitioning it.
_GENERIC_KEYWORDS = {
    "model", "models", "research", "paper", "training", "release", "open source",
    "artificial intelligence", "machine learning", "deep learning", "neural network",
    "technology", "data", "dataset", "ai", "startup", "funding", "product",
    "模型", "算法", "论文", "研究", "发布", "技术", "应用", "产品",
    # Vendor names say who shipped it, not what it is about - useless as threads
    # now that Agent is the only domain.
    "openai", "anthropic", "claude", "gemini", "deepmind", "gpt", "deepseek",
    "qwen", "llama", "mistral", "gemma", "grok",
    "llm", "large language model", "foundation model", "大语言模型", "大模型",
    "agent", "agents", "agentic", "智能体",
}

# Canonical topic names, so synonyms collapse into one thread instead of
# fragmenting the page into near-duplicate topics. Every entry is an Agent
# engineering sub-domain, which is what the report now contains.
_TOPIC_ALIASES = {
    # --- 工具调用与协议 ---
    "tool use": "工具调用与 MCP",
    "tool-use": "工具调用与 MCP",
    "tool calling": "工具调用与 MCP",
    "tool-calling": "工具调用与 MCP",
    "function calling": "工具调用与 MCP",
    "function-calling": "工具调用与 MCP",
    "toolformer": "工具调用与 MCP",
    "mcp": "工具调用与 MCP",
    "model context protocol": "工具调用与 MCP",
    "mcp server": "工具调用与 MCP",
    "mcp client": "工具调用与 MCP",
    "a2a": "Agent 互操作协议",
    "agent2agent": "Agent 互操作协议",
    "agent protocol": "Agent 互操作协议",
    "工具调用": "工具调用与 MCP",
    "函数调用": "工具调用与 MCP",

    # --- 上下文工程与记忆 ---
    "context engineering": "上下文工程",
    "context management": "上下文工程",
    "上下文工程": "上下文工程",
    "上下文管理": "上下文工程",
    "agent memory": "记忆与状态",
    "long-term memory": "记忆与状态",
    "memory bank": "记忆与状态",
    "长期记忆": "记忆与状态",
    "prompt caching": "上下文工程",

    # --- 规划与推理 ---
    "planning": "规划与任务分解",
    "task decomposition": "规划与任务分解",
    "self-reflection": "规划与任务分解",
    "self-critique": "规划与任务分解",
    "任务分解": "规划与任务分解",

    # --- 编排与框架 ---
    "orchestration": "Agent 编排与框架",
    "orchestrator": "Agent 编排与框架",
    "agent orchestration": "Agent 编排与框架",
    "agent workflow": "Agent 编排与框架",
    "workflow orchestration": "Agent 编排与框架",
    "agent framework": "Agent 编排与框架",
    "agent sdk": "Agent 编排与框架",
    "agents sdk": "Agent 编排与框架",
    "langgraph": "Agent 编排与框架",
    "langchain": "Agent 编排与框架",
    "llamaindex": "Agent 编排与框架",
    "crewai": "Agent 编排与框架",
    "autogen": "Agent 编排与框架",
    "semantic kernel": "Agent 编排与框架",
    "pydantic ai": "Agent 编排与框架",
    "智能体框架": "Agent 编排与框架",
    "工作流编排": "Agent 编排与框架",

    # --- 编码 Agent ---
    "coding agent": "编码 Agent",
    "code agent": "编码 Agent",
    "claude code": "编码 Agent",
    "codex": "编码 Agent",
    "cursor": "编码 Agent",
    "windsurf": "编码 Agent",
    "devin": "编码 Agent",
    "openhands": "编码 Agent",
    "aider": "编码 Agent",
    "copilot": "编码 Agent",
    "swe-bench": "编码 Agent",
    "swebench": "编码 Agent",
    "terminal-bench": "编码 Agent",
    "代码智能体": "编码 Agent",
    "编程智能体": "编码 Agent",

    # --- 计算机操作 / 浏览器 Agent ---
    "computer use": "计算机操作 Agent",
    "computer-use": "计算机操作 Agent",
    "browser agent": "计算机操作 Agent",
    "browser-use": "计算机操作 Agent",
    "web agent": "计算机操作 Agent",
    "gui agent": "计算机操作 Agent",
    "desktop agent": "计算机操作 Agent",
    "浏览器智能体": "计算机操作 Agent",

    # --- 多智能体 ---
    "multi-agent": "多智能体协作",
    "multiagent": "多智能体协作",
    "multi-agent system": "多智能体协作",
    "multi-agent systems": "多智能体协作",
    "subagent": "多智能体协作",
    "sub-agent": "多智能体协作",
    "handoff": "多智能体协作",
    "多智能体": "多智能体协作",

    # --- 执行环境、权限与安全 ---
    "sandbox": "沙箱与执行环境",
    "sandboxing": "沙箱与执行环境",
    "code execution": "沙箱与执行环境",
    "execution environment": "沙箱与执行环境",
    "permission": "沙箱与执行环境",
    "沙箱": "沙箱与执行环境",
    "权限管理": "沙箱与执行环境",
    "prompt injection": "Agent 安全",
    "tool poisoning": "Agent 安全",
    "agent security": "Agent 安全",
    "agent safety": "Agent 安全",
    "guardrails": "Agent 安全",
    "human-in-the-loop": "Agent 安全",
    "human in the loop": "Agent 安全",
    "提示注入": "Agent 安全",

    # --- 评测 ---
    "agent evaluation": "Agent 评测",
    "agent evals": "Agent 评测",
    "agent benchmark": "Agent 评测",
    "agentic benchmark": "Agent 评测",
    "gaia": "Agent 评测",
    "webarena": "Agent 评测",
    "osworld": "Agent 评测",
    "os-world": "Agent 评测",
    "tau-bench": "Agent 评测",
    "taubench": "Agent 评测",
    "agent trajectory": "Agent 评测",
    "evals": "Agent 评测",
    "evaluation": "Agent 评测",
    "benchmark": "Agent 评测",
    "评测": "Agent 评测",
    "基准": "Agent 评测",

    # --- 技能与运行时 ---
    "agent skills": "Agent 技能与运行时",
    "skills": "Agent 技能与运行时",
    "harness": "Agent 技能与运行时",
    "agent harness": "Agent 技能与运行时",
    "scaffolding": "Agent 技能与运行时",
    "agent scaffold": "Agent 技能与运行时",
    "agent runtime": "Agent 技能与运行时",
    "agent loop": "Agent 技能与运行时",
}


def canonical_topic(keyword: str) -> str | None:
    """Map a matched keyword to a canonical topic name, or None if too generic."""
    kw = keyword.strip().lower()
    if not kw or kw in _GENERIC_KEYWORDS:
        return None
    return _TOPIC_ALIASES.get(kw)


# Catch-all topic names that carry no information once Agent is the only domain.
# The prompt forbids them, but a topic page that renders one giant "AI Agent"
# bucket is exactly the failure this guard exists to prevent.
_CATCH_ALL_TOPICS = {
    "ai agent", "ai agents", "agent", "agents", "agentic", "agentic ai",
    "ai", "llm", "large language model", "foundation model", "model",
    "大模型", "大语言模型", "语言模型", "智能体", "人工智能", "agent 技术",
    "agent 与工具调用", "通用", "其他", "综合",
}


def is_usable_topic(name: str) -> bool:
    """False for empty or catch-all LLM topic names."""
    n = (name or "").strip().lower()
    return bool(n) and n not in _CATCH_ALL_TOPICS


# LLM-coined topics drift: the same idea comes back as "Agent 评测" one day and
# "评测基准" the next, which splits one knowledge thread into two. These are
# folded onto the canonical names above. Only exact names are mapped, so an
# unrecognised new topic still passes through untouched.
#
# Keys are matched against a lowercased name, so any key containing Latin
# letters must be written lowercase or it will silently never match.
_CANONICAL_BY_SYNONYM = {
    "企业安全与权限": "Agent 安全",
    "安全与权限": "Agent 安全",
    "权限与安全": "Agent 安全",
    "评测基准": "Agent 评测",
    "评测与方法": "Agent 评测",
    "评估与基准": "Agent 评测",
    "多智能体学习": "多智能体协作",
    "多智能体系统": "多智能体协作",
    "多模型编排": "Agent 编排与框架",
    "任务型 agent": "Agent 编排与框架",
    "任务型智能体": "Agent 编排与框架",
    "agent 平台架构": "Agent 编排与框架",
    "智能体平台": "Agent 编排与框架",
    "闭环执行": "Agent 技能与运行时",
    "上下文与记忆": "上下文工程",
    "记忆与上下文": "上下文工程",
    "工具与协议": "工具调用与 MCP",
    "mcp 与工具": "工具调用与 MCP",
    "代码智能体": "编码 Agent",
    "编程智能体": "编码 Agent",
    "计算机操作": "计算机操作 Agent",
    "浏览器自动化": "计算机操作 Agent",
    "agent 评测": "Agent 评测",
    "agent 安全": "Agent 安全",
    "agent 编排": "Agent 编排与框架",
    "agent 技能": "Agent 技能与运行时",
    "多智能体": "多智能体协作",
    "编码 agent": "编码 Agent",
}


def normalize_topic(name: str) -> str:
    """Fold a known LLM topic synonym onto its canonical name."""
    n = (name or "").strip()
    if not n:
        return ""
    return _CANONICAL_BY_SYNONYM.get(n.lower(), n)


def _item_payload(item: Item) -> dict:
    dt = item.published_dt
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "category": item.category,
        "summary": item.summary,
        "published_at": item.published_at,
        "published_display": dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "",
        "published_date": dt.astimezone().strftime("%Y-%m-%d") if dt else "",
        "age_hours": item.age_hours(),
        "score": item.score,
        "points": item.points,
        "comments": item.comments,
        "stars": item.stars,
        "authors": item.authors[:6],
        "tags": item.tags[:8],
        "matched_keywords": item.matched_keywords[:12],
        "why": next((r[4:] for r in item.reasons if r.startswith("why:")), ""),
        # Learning layer (LLM stage)
        "concepts": item.concepts[:3],
        "topics": item.topics,
        "level": item.level,
        "has_content": bool(item.content),
        "content_chars": len(item.content or ""),
    }


class FetchRunner:
    """Runs `ain fetch` once at a time in a background thread.

    The store is not concurrency-safe, so overlapping fetches are refused rather
    than allowed to race on items.jsonl.
    """

    def __init__(self, config: Config):
        self.config = config
        self._lock = threading.Lock()
        self._state: dict = {"running": False, "started_at": None, "finished_at": None,
                             "result": None, "error": None}

    @property
    def running(self) -> bool:
        return bool(self._state["running"])

    def state(self) -> dict:
        return dict(self._state)

    def start(self, use_llm: bool = False) -> tuple[bool, str]:
        if self.running:
            return False, "已经有一次抓取在进行中"
        thread = threading.Thread(target=self._run, args=(use_llm,), daemon=True)
        thread.start()
        return True, "已开始抓取"

    def _run(self, use_llm: bool) -> None:
        from .pipeline import run as pipeline_run

        with self._lock:
            self._state.update(
                running=True, started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                finished_at=None, result=None, error=None,
            )
            try:
                result = pipeline_run(self.config, use_llm=use_llm)
                self._state["result"] = {
                    "ok_sources": result.ok_sources,
                    "failed": {r.source_id: r.error for r in result.failed_sources},
                    "selected": len(result.items),
                    "added": result.added,
                    "updated": result.updated,
                    "duplicates": result.duplicates,
                    "summarizer": result.summarizer_mode,
                    # Surfaced so the UI can report what this click cost.
                    "llm_usage": result.llm_usage,
                    "llm_skipped": result.llm_skipped,
                }
                # Markdown export only when explicitly enabled; the UI reads the
                # archive directly, so the file is optional.
                if self.config.write_markdown:
                    from .report import write_report

                    write_report(
                        result.items,
                        self.config.reports_dir,
                        source_results=result.source_results,
                        duplicates=result.duplicates,
                        summarizer_mode=result.summarizer_mode,
                    )
            except Exception as exc:
                self._state["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                self._state["running"] = False
                self._state["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


class Api:
    """Query logic over the archive. Kept separate from HTTP for easy testing."""

    def __init__(self, config: Config):
        self.config = config
        self.store = Store(config.data_dir)
        self.fetcher = FetchRunner(config)
        # Same hard gate the pipeline uses, so the archive view cannot disagree
        # with the digest about what counts as an Agent story.
        self.scorer = Scorer(config.interests)
        self.domain_exempt = {
            s.id for s in config.sources if s.opt("domain_exempt", False)
        }

    def _in_domain(self, item: Item) -> bool:
        return item.source_id in self.domain_exempt or self.scorer.in_domain(item)

    def reload(self) -> None:
        self.store._items = None  # force re-read so new fetches show up

    def items(self, params: dict[str, list[str]]) -> dict:
        self.reload()
        all_items = list(self.store.load().values())
        # Rows predating the Agent gate (or written by an older config) are
        # hidden here rather than shown and silently confusing the reader.
        all_items = [i for i in all_items if self._in_domain(i)]

        def first(key: str, default: str = "") -> str:
            values = params.get(key) or []
            return values[0].strip() if values else default

        query = first("q").lower()
        source = first("source")
        category = first("category")
        days = first("days", "7")
        sort = first("sort", "score")
        try:
            limit = min(max(int(first("limit", "200")), 1), 2000)
        except ValueError:
            limit = 200

        items = all_items

        # Date window. `days=0` means everything.
        try:
            day_count = float(days)
        except ValueError:
            day_count = 7.0
        if day_count > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=day_count)
            items = [
                i for i in items
                if (i.published_dt or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
            ]

        if query:
            items = search_items(items, query)

        if source:
            items = [i for i in items if i.source_id == source]
        if category:
            items = [i for i in items if i.category == category]

        if sort == "newest":
            items.sort(key=lambda i: (i.published_at or "", i.score), reverse=True)
        elif sort == "oldest":
            items.sort(key=lambda i: (i.published_at or "9999", i.score))
        else:
            items.sort(key=lambda i: (i.score, i.published_at or ""), reverse=True)

        total = len(items)
        items = items[:limit]

        # Facets computed over the filtered set, so the UI can show live counts.
        by_category: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for i in all_items:
            by_category[i.category] = by_category.get(i.category, 0) + 1
            by_source[i.source_id] = by_source.get(i.source_id, 0) + 1

        return {
            "items": [_item_payload(i) for i in items],
            "total": total,
            "returned": len(items),
            "facets": {
                "category": by_category,
                "source": by_source,
                "sources": [
                    {"id": s.id, "name": s.name, "category": s.category, "enabled": s.enabled}
                    for s in self.config.sources
                ],
            },
            "archive_size": len(all_items),
        }

    def item_content(self, params: dict[str, list[str]]) -> dict:
        """Full article body for one item, loaded on demand.

        Bodies average ~5KB, so bundling them into the list response would push
        a 200-item payload past 1MB. The list only advertises `has_content`; the
        UI fetches the body when the reader expands an item.
        """
        self.reload()
        item_id = (params.get("id") or [""])[0].strip()
        if not item_id:
            return {"error": "缺少 id 参数"}
        item = self.store.load().get(item_id)
        if item is None:
            return {"error": "找不到该条目（可能已不在归档）"}
        return {
            "id": item.id,
            "content": item.content or "",
            "strategy": item.content_strategy,
            "chars": len(item.content or ""),
            "url": item.url,
        }

    def digest(self, params: dict[str, list[str]]) -> dict:
        """The curated set from a run - what the Markdown report showed.

        Items are resolved from the ids recorded in runs.jsonl. Selection cannot
        be recomputed later because scores decay with time, so the run record is
        the source of truth.
        """
        self.reload()
        # Filtered for the same reason as items(): a pre-gate run recorded
        # selected_ids that are no longer in scope, and the digest should not
        # resurrect them.
        items = {i.id: i for i in self.store.load().values() if self._in_domain(i)}

        def first(key: str, default: str = "") -> str:
            values = params.get(key) or []
            return values[0].strip() if values else default

        # Partial runs (e.g. `fetch --sources X -n 3`) are recorded for history
        # but excluded from the digest, so a debug run cannot replace today's
        # curated set. Explicitly requested run indices still resolve below.
        all_runs = self.store.read_runs(limit=200)
        runs = [r for r in all_runs
                if r.get("selected_ids") and not r.get("partial")]
        if not runs:
            # Older runs predate selected_ids; fall back to a live ranking so the
            # page still works on an archive recorded before this feature.
            fallback = self.items({**params, "limit": [first("limit", "40")]})
            return {
                "ts": None,
                "items": fallback["items"],
                "total": fallback["total"],
                "source": "live-ranking",
                "fallback_reason": "归档里还没有带 selected_ids 的运行记录",
            }

        which = first("run")
        run = runs[0] if which in ("", "latest", "0") else None
        if run is None:
            try:
                run = runs[int(which)]
            except (ValueError, IndexError):
                run = runs[0]

        chosen = [items[i] for i in run.get("selected_ids", []) if i in items]
        missing = len(run.get("selected_ids", [])) - len(chosen)

        return {
            "ts": run.get("ts"),
            "items": [_item_payload(i) for i in chosen],
            "total": len(chosen),
            "missing": missing,
            "source": "run-record",
            "stats": {
                "ok_sources": run.get("ok_sources", []),
                "failed": run.get("failed", {}),
                "added": run.get("added"),
                "updated": run.get("updated"),
                "summarizer": run.get("summarizer"),
                "content": run.get("content", {}),
            },
            "runs": [
                {"ts": r.get("ts"), "selected": len(r.get("selected_ids", []))}
                for r in runs[:30]
            ],
        }

    def topics(self, params: dict[str, list[str]]) -> dict:
        """Knowledge threads: items grouped by technical topic rather than date.

        Uses LLM-assigned `topics` when present. Without an LLM key nothing has
        topics yet, so it falls back to canonicalising matched keywords - which
        makes the page useful immediately and upgrades automatically once the
        LLM stage is enabled.
        """
        self.reload()
        items = [i for i in self.store.load().values() if self._in_domain(i)]

        def first(key: str, default: str = "") -> str:
            values = params.get(key) or []
            return values[0].strip() if values else default

        try:
            days = float(first("days", "30"))
        except ValueError:
            days = 30.0
        if days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            items = [
                i for i in items
                if (i.published_dt or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
            ]

        threads: dict[str, list[Item]] = {}
        used_llm = False

        for item in items:
            names: list[str] = []
            if item.topics:
                names = []
                for t in item.topics:
                    if not is_usable_topic(t):
                        continue
                    n = normalize_topic(t)
                    if n and n not in names:
                        names.append(n)
                used_llm = True
            else:
                for kw in item.matched_keywords:
                    name = canonical_topic(kw)
                    if name and name not in names:
                        names.append(name)
            for name in names[:4]:
                threads.setdefault(name, []).append(item)

        out = []
        for name, group in threads.items():
            group.sort(key=lambda i: (i.score, i.published_at or ""), reverse=True)
            out.append({
                "topic": name,
                "count": len(group),
                "sources": len({i.source_id for i in group}),
                # Concepts tie the thread together when the LLM has run.
                "concepts": [c for i in group for c in i.concepts][:8],
                "items": [_item_payload(i) for i in group[:12]],
            })

        # Most-covered topics first, but a topic needs at least 2 items to be a
        # "thread" rather than a single article.
        out.sort(key=lambda t: (-t["count"], t["topic"]))
        return {
            "threads": [t for t in out if t["count"] >= 2],
            "single": [t for t in out if t["count"] < 2][:20],
            "mode": "llm" if used_llm else "keyword",
            "total_items": len(items),
        }

    def stats(self) -> dict:
        self.reload()
        # Counted over in-domain rows only, so the headline archive size matches
        # what the list view can actually show.
        items = [i for i in self.store.load().values() if self._in_domain(i)]
        now = datetime.now(timezone.utc)

        def count_since(days: float) -> int:
            cutoff = now - timedelta(days=days)
            return sum(
                1 for i in items
                if (i.published_dt or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
            )

        runs = []
        if self.store.runs_path.exists():
            for line in self.store.runs_path.read_text(encoding="utf-8").splitlines()[-10:]:
                try:
                    runs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return {
            "archive_size": len(items),
            "last_24h": count_since(1),
            "last_7d": count_since(7),
            "last_30d": count_since(30),
            "runs": list(reversed(runs)),
            "fetch": self.fetcher.state(),
            "usage": self.store.usage_summary(),
        }


class Handler(BaseHTTPRequestHandler):
    config: Config
    api: Api
    server_version = "ain"

    def log_message(self, fmt, *args):  # quieter default logging
        pass

    # ------------------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _html(self, text: str, status: int = 200) -> None:
        self._send(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        try:
            if route == "/api/fetch":
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    body = {}
                ok, message = self.api.fetcher.start(use_llm=bool(body.get("llm")))
                self._json({"ok": ok, "message": message,
                            "state": self.api.fetcher.state()},
                           status=202 if ok else 409)
            else:
                self._json({"error": "not found", "path": route}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
        params = parse_qs(parsed.query)

        try:
            if route == "/":
                index = WEB_DIR / "index.html"
                if not index.exists():
                    self._html("<h1>ain</h1><p>web/index.html missing</p>", 500)
                    return
                self._html(index.read_text(encoding="utf-8"))
            elif route == "/api/items":
                self._json(self.api.items(params))
            elif route == "/api/digest":
                self._json(self.api.digest(params))
            elif route == "/api/content":
                self._json(self.api.item_content(params))
            elif route == "/api/topics":
                self._json(self.api.topics(params))
            elif route == "/knowledge":
                page = WEB_DIR / "knowledge.html"
                if not page.exists():
                    self._html("<h1>ain</h1><p>web/knowledge.html missing</p>", 500)
                    return
                self._html(page.read_text(encoding="utf-8"))
            elif route == "/api/stats":
                self._json(self.api.stats())
            elif route == "/api/fetch":
                self._json(self.api.fetcher.state())
            elif route == "/health":
                self._json({"ok": True})
            else:
                self._json({"error": "not found", "path": route}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:  # surface errors as JSON instead of a hang
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)


def serve(config: Config, host: str = "127.0.0.1", port: int = 8848) -> None:
    api = Api(config)

    class BoundHandler(Handler):
        pass

    BoundHandler.config = config
    BoundHandler.api = api

    httpd = ThreadingHTTPServer((host, port), BoundHandler)
    url = f"http://{host}:{port}"
    print(f"ain web → {url}")
    print(f"归档: {api.store.items_path}  (Ctrl-C 停止)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
