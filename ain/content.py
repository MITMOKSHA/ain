"""Article full-text extraction.

Most feeds only carry a title plus a one-line teaser - InfoQ's RSS literally
sends "点击查看原文>" as its description. To make the report usable for
learning, the pipeline follows the link and pulls the real body text.

No third-party readability library is used (this project is stdlib-only), so
extraction is a cascade of strategies, most specific first:

  1. JSON-LD `articleBody`            - structured, when present
  2. <article> / main containers      - semantic HTML
  3. <p> density (largest text block)  - the classic heuristic
  4. og:description / meta description - last resort, still real content

Each strategy is scored on length and text quality, and the best candidate wins.
A failure here must never break the run, so callers get None and keep the teaser.
"""

from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass

from .html import to_text

# Tags whose contents are never article body.
_STRIP = re.compile(
    r"<(script|style|noscript|nav|header|footer|aside|form|iframe|svg|button)\b[^>]*>.*?</\1\s*>",
    re.S | re.I,
)
_COMMENT = re.compile(r"<!--.*?-->", re.S)

# Boilerplate that appears in extracted text and should disqualify/trim a block.
_BOILERPLATE = (
    "点击查看原文", "关注我们", "扫码关注", "微信公众号", "版权声明",
    "本站提到的所有注册商标", "京icp", "京公安", "举报电话", "免责声明",
    "subscribe", "cookie", "all rights reserved", "sign up for",
    "advertisement", "follow us on",
)

# Lines that are page furniture rather than article prose. Matched per paragraph
# so a single junk line cannot survive into the body.
_NOISE_LINE = re.compile(
    r"your browser does not support"
    r"|^(read more|learn more|share this|posted in|tags?:)\b"
    r"|^(software engineer|product manager|data scientist|research scientist)\b"
    r"|^your browser"
    r"|图片|图源|编辑：|来源：|作者：|记者：",
    re.I,
)


@dataclass
class Extracted:
    text: str
    strategy: str


def _clean(text: str) -> str:
    text = _html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _meta_description(html: str) -> str:
    """og:description / meta description - often a genuine summary."""
    for pattern in (
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
    ):
        m = re.search(pattern, html, re.I)
        if m:
            value = _clean(m.group(1))
            if len(value) > 40:
                return value
    return ""


def _json_ld_body(html: str) -> str:
    """JSON-LD articleBody, when the site publishes structured data."""
    for m in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            # articleBody may sit at top level or inside @graph.
            candidates = [node]
            if isinstance(node.get("@graph"), list):
                candidates.extend(n for n in node["@graph"] if isinstance(n, dict))
            for cand in candidates:
                body = cand.get("articleBody") or cand.get("text")
                if isinstance(body, str) and len(body) > 200:
                    return _clean(body)
    return ""


def _paragraphs(html: str, container_pattern: str | None = None) -> list[str]:
    """Collect <p> text, optionally restricted to a container regex."""
    scope = html
    if container_pattern:
        m = re.search(container_pattern, html, re.S | re.I)
        if m:
            scope = m.group(0)

    parts: list[str] = []
    for m in re.finditer(r"<p\b[^>]*>(.*?)</p>", scope, re.S | re.I):
        text = to_text(m.group(1))
        if len(text) < 30:
            continue
        low = text.lower()
        if any(b in low for b in _BOILERPLATE):
            continue
        if _NOISE_LINE.search(text):
            continue
        # Skip link-farm paragraphs (many anchors, little prose).
        if text.count("http") > 2:
            continue
        parts.append(text)
    return parts


def _div_text_blocks(html: str) -> list[str]:
    """Fallback for sites that don't use <p>: split text-heavy <div> blocks."""
    parts: list[str] = []
    for m in re.finditer(r"<div\b[^>]*>(.{80,4000}?)</div>", html, re.S | re.I):
        inner = m.group(1)
        if "<div" in inner:  # only leaf-ish blocks
            continue
        text = to_text(inner)
        if len(text) < 120:
            continue
        low = text.lower()
        if any(b in low for b in _BOILERPLATE):
            continue
        parts.append(text)
    return parts


def _score(text: str) -> float:
    """Rank a candidate body. Length matters, but so does prose density."""
    if not text:
        return 0.0
    length = len(text)
    if length < 80:
        return 0.0
    # CJK counts more per character than Latin, so weight both fairly.
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    words = len(re.findall(r"[A-Za-z]{2,}", text))
    units = cjk + words
    # Threshold is deliberately low: a 70-character Chinese meta description is
    # a real summary (CJK packs far more meaning per character than Latin), and
    # it still beats the "点击查看原文>" teaser that some feeds send.
    if units < 20:
        return 0.0
    # Prefer real prose over nav/menu text: many short "sentences" = menu.
    sentences = re.split(r"[。！？.!?\n]", text)
    avg = length / max(len([s for s in sentences if s.strip()]), 1)
    density = min(avg / 40.0, 2.0)
    return units * density


def extract(html: str, *, max_chars: int = 6000) -> Extracted | None:
    """Extract the main article body. Returns None if nothing convincing found."""
    if not html or len(html) < 200:
        return None

    cleaned = _COMMENT.sub(" ", html)
    cleaned = _STRIP.sub(" ", cleaned)

    candidates: list[tuple[str, str]] = []

    body = _json_ld_body(cleaned)
    if body:
        candidates.append((body, "json-ld"))

    # Semantic containers, most specific first.
    for pattern in (
        r"<article\b[^>]*>(.*?)</article>",
        r'<div[^>]+(?:class|id)="[^"]*(?:article-content|post-content|entry-content|rich_media_content|articleContent|content-body)[^"]*"[^>]*>(.*?)</div>',
        r"<main\b[^>]*>(.*?)</main>",
    ):
        m = re.search(pattern, cleaned, re.S | re.I)
        if not m:
            continue
        inner = m.group(1) if m.groups() else m.group(0)
        paras = _paragraphs(inner) or _div_text_blocks(inner)
        if paras:
            candidates.append(("\n\n".join(paras), "container"))

    paras = _paragraphs(cleaned)
    if paras:
        # Join all paragraphs; scoring below compares this against alternatives.
        candidates.append(("\n\n".join(paras), "paragraphs"))

    blocks = _div_text_blocks(cleaned)
    if blocks:
        best = max(blocks, key=len)
        candidates.append((best, "div-block"))

    meta = _meta_description(cleaned)
    if meta:
        candidates.append((meta, "meta-description"))

    if not candidates:
        return None

    text, strategy = max(candidates, key=lambda c: _score(c[0]))
    if _score(text) <= 0:
        # Nothing scored well; a real meta description still beats no content.
        if meta and len(meta) > 50:
            return Extracted(meta[:max_chars], "meta-description")
        return None

    text = _trim_boilerplate(text)
    return Extracted(text[:max_chars], strategy)


def _trim_boilerplate(text: str) -> str:
    """Drop trailing legal/footer noise that survived filtering."""
    cut = len(text)
    for marker in _BOILERPLATE:
        idx = text.lower().find(marker)
        # Only trim if the marker appears in the back half (it's a footer).
        if idx > len(text) * 0.5:
            cut = min(cut, idx)
    return text[:cut].strip()


def fetch_article(url: str, *, timeout: float = 25.0, max_chars: int = 6000) -> Extracted | None:
    """Download and extract. Network/parse failure returns None, never raises."""
    from .http import fetch_text

    try:
        html = fetch_text(url, timeout=timeout, retries=1)
    except Exception:
        return None
    try:
        return extract(html, max_chars=max_chars)
    except Exception:
        return None
