"""Summarisation with a pluggable LLM hook.

Default behaviour needs no network and no API key: it uses the source's own
abstract/description, trimmed to a couple of sentences. If you set
`AIN_LLM_API_KEY` (and optionally AIN_LLM_BASE_URL / AIN_LLM_MODEL), the agent
upgrades to LLM-written Chinese summaries and per-item "why it matters" notes.

Only the standard library is used, so the LLM call is a plain JSON POST to an
OpenAI-compatible /chat/completions endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .html import first_sentences, to_text
from .models import Item

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

# This prompt is the heart of the "learning, not news" goal. A plain summary
# tells you what happened; a concept card tells you what to learn and how to use
# it. The reader is a software engineer, so every field is framed for practice.
SYSTEM_PROMPT = """你是资深 AI 工程讲师，读者是有多年经验、但 AI 基础较薄的软件工程师。

对每条内容，输出 JSON（只输出 JSON，不要解释，不要 markdown 代码块）：
{
  "items": [{
    "id": "<原样返回 id，不要回传其他输入字段>",
    "zh": "<2-3 句中文摘要：做了什么、关键结果/变化是什么>",
    "why": "<一句话：对软件工程师为什么值得关注>",
    "topics": ["<1-3 个稳定的技术主题名，用于跨天聚合>"],
    "level": "intro|intermediate|advanced",
    "concepts": [{
      "name": "<技术概念名，中英皆可，尽量用业内通用叫法>",
      "what": "<1-2 句：这是什么、解决什么问题>",
      "how": "<1-2 句：工程上怎么用、什么场景、有什么坑>"
    }]
  }]
}

要求：
0. 严禁回传输入的 title/text/source 等字段，只输出上面列出的字段。
1. concepts 只提取【可迁移的技术知识】，不要提公司动态、融资、人事。
   例如「模式坍缩」「KV cache 量化」「按置信度设阈值」是好概念；
   「某公司发布了新模型」不是概念。
2. 每条最多 3 个概念，宁缺毋滥。没有值得学的概念就返回空数组。
3. topics 用稳定的短名词，便于聚合。优先复用这些已有主题：
   {existing_topics}
   都不合适时才新建。
4. 不要空话。不要「值得关注」「具有重要意义」这类套话。
5. level 指理解这些概念所需的基础，不是新闻的重要性。
6. 若原文是英文，输出仍用中文，但概念名保留英文术语（如 "KV cache"）。
"""


def _build_system_prompt(existing_topics: list[str]) -> str:
    if existing_topics:
        topics = "、".join(existing_topics[:40])
    else:
        topics = "（暂无，可自行归纳）"
    return SYSTEM_PROMPT.replace("{existing_topics}", topics)


def collect_topics(items: list[Item]) -> list[str]:
    """Gather topic names already in use, most frequent first.

    Fed back into the prompt so the model converges on a shared vocabulary
    instead of minting a new near-duplicate topic for every article.
    """
    counts: dict[str, int] = {}
    for item in items:
        for topic in item.topics:
            topic = topic.strip()
            if topic:
                counts[topic] = counts.get(topic, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


class Summarizer:
    def __init__(self, *, use_llm: bool = False, api_key: str | None = None,
                 base_url: str | None = None, model: str | None = None,
                 timeout: float = 90.0):
        self.api_key = api_key or os.environ.get("AIN_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("AIN_LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("AIN_LLM_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.use_llm = bool(use_llm and self.api_key)
        # Set per run by summarize(); surfaced so a run can report what it spent.
        self.llm_called = 0
        self.llm_skipped = 0
        # Accumulated token usage, so `fetch --llm` can report actual spend.
        self._usage_lock = threading.Lock()
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

        if use_llm and not self.api_key:
            log.warning(
                "LLM summarisation requested but no API key found "
                "(set AIN_LLM_API_KEY); falling back to extractive summaries."
            )

    @property
    def mode(self) -> str:
        return f"llm:{self.model}" if self.use_llm else "extractive"

    # ------------------------------------------------------------------
    def summarize(self, items: list[Item], known_topics: list[str] | None = None) -> list[Item]:
        if not items:
            return items

        # Always produce a baseline summary first, so a failed LLM call still
        # leaves every item with usable text.
        for item in items:
            item.summary = self._extractive(item)

        if not self.use_llm:
            return items

        # Items reused from the archive already carry learning cards. Re-sending
        # them would burn tokens for an identical result, so only new items go
        # to the model.
        pending = [i for i in items if not i.concepts]
        self.llm_skipped = len(items) - len(pending)
        self.llm_called = len(pending)

        if not pending:
            return items

        try:
            self._llm_enrich(pending, known_topics=known_topics or [])
        except Exception as exc:  # never fail the run over summarisation
            log.warning("LLM summarisation failed (%s); keeping extractive text", exc)
        return items

    def _extractive(self, item: Item) -> str:
        # Prefer the fetched article body: for feeds like InfoQ the teaser is
        # literally "点击查看原文>", so the body is the only real content.
        raw = item.content or item.summary or ""
        text = to_text(raw, keep_newlines=False)
        if not text:
            return item.title
        summary = first_sentences(text, max_chars=360, max_sentences=2)
        if summary and summary != item.title:
            return summary
        return item.title

    # ------------------------------------------------------------------
    def _llm_enrich(
        self,
        items: list[Item],
        *,
        known_topics: list[str] | None = None,
        batch_size: int = 6,
    ) -> None:
        # Existing topics are fed back in so the model reuses names instead of
        # inventing a near-synonym per article - that is what makes cross-day
        # aggregation work instead of producing 200 one-off topics.
        existing = list(known_topics or []) + collect_topics(items)
        system_prompt = _build_system_prompt(existing)

        # Batches are smaller than before because each item now sends real body
        # text instead of a one-line teaser.
        batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

        def run(batch: list[Item]) -> None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(
                        {
                            "items": [
                                {
                                    "id": it.id,
                                    "title": it.title,
                                    "source": it.source_name,
                                    # Prefer the full article body; fall back to
                                    # the feed teaser when enrichment failed.
                                    "text": (it.content or it.summary or "")[:6000],
                                }
                                for it in batch
                            ]
                        },
                        ensure_ascii=False,
                    )},
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            }
            data = self._post(payload)

            # Track real spend so a run can report what it cost. Kept in a lock
            # because batches run on a thread pool.
            usage = data.get("usage") or {}
            with self._usage_lock:
                self.usage["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
                self.usage["completion_tokens"] += int(usage.get("completion_tokens") or 0)
                self.usage["calls"] += 1

            content = (
                ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            )
            parsed = _parse_json_loose(content) if content else {}
            by_id = {str(e.get("id")): e for e in (parsed.get("items") or []) if isinstance(e, dict)}

            for item in batch:
                entry = by_id.get(item.id)
                if not entry:
                    continue
                zh = str(entry.get("zh") or "").strip()
                why = str(entry.get("why") or "").strip()
                if zh:
                    item.summary = zh
                if why:
                    item.reasons = [*item.reasons, f"why:{why}"]

                topics = [str(t).strip() for t in (entry.get("topics") or []) if str(t).strip()]
                if topics:
                    item.topics = topics[:4]

                level = str(entry.get("level") or "").strip().lower()
                if level in {"intro", "intermediate", "advanced"}:
                    item.level = level

                cards: list[dict] = []
                for card in (entry.get("concepts") or [])[:3]:
                    if not isinstance(card, dict):
                        continue
                    name = str(card.get("name") or "").strip()
                    if not name:
                        continue
                    cards.append({
                        "name": name,
                        "what": str(card.get("what") or "").strip(),
                        "how": str(card.get("how") or "").strip(),
                    })
                if cards:
                    item.concepts = cards

        # Batches are independent; a couple of workers keeps latency sane.
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(run, batches))

    def _post(self, payload: dict) -> dict:
        """POST to /chat/completions, transparently handling stream-only backends.

        Some gateways (notably Tencent's copilot endpoint that fronts WorkBuddy
        models) reject non-streaming requests outright with
        "Non-stream chat request is currently not supported". So on that specific
        failure we retry with stream=true and reassemble the SSE chunks into the
        same shape a non-streaming response would have.
        """
        try:
            return self._post_once(payload, stream=False)
        except RuntimeError as exc:
            if "stream" not in str(exc).lower():
                raise
            log.debug("backend requires streaming; retrying with stream=true")
            return self._post_stream(payload)

    def _post_once(self, payload: dict, *, stream: bool) -> dict:
        body = dict(payload)
        if stream:
            body["stream"] = True
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "text/event-stream" if stream else "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc

        if not stream:
            return json.loads(raw)
        return _parse_sse(raw)

    def _post_stream(self, payload: dict) -> dict:
        body = dict(payload)
        body["stream"] = True
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        return _parse_sse(raw)


def _strip_code_fence(text: str) -> str:
    """Remove a ```json ... ``` wrapper many models add despite json_object mode.

    Without this the whole batch fails to parse and silently falls back to
    extractive text - which looks like "LLM did nothing" rather than an error.
    """
    t = (text or "").strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_json_loose(text: str) -> dict:
    """Parse a model's JSON reply, tolerating fences and surrounding prose."""
    cleaned = _strip_code_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} span.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"model did not return parseable JSON: {cleaned[:200]!r}")


def _parse_sse(raw: str) -> dict:
    """Reassemble Server-Sent Events into a single chat-completion object.

    Only the fields the caller reads are rebuilt: choices[0].message.content and
    usage. Reasoning tokens (`reasoning_content`) are deliberately ignored - we
    want the final answer, not the model's scratchpad.
    """
    content_parts: list[str] = []
    model = ""
    usage: dict | None = None

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue

        model = chunk.get("model") or model
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            piece = delta.get("content")
            if piece:
                content_parts.append(piece)

    message: dict = {"role": "assistant", "content": "".join(content_parts)}
    out: dict = {"model": model, "choices": [{"index": 0, "message": message}]}
    if usage:
        out["usage"] = usage
    return out
