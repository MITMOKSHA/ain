"""Minimal dependency-free HTML helpers.

Vendor blogs (Anthropic, Meta, ...) do not all ship RSS, so a few sources parse
their listing pages. These helpers keep that parsing honest: strip scripts and
styles first, then tags, then unescape entities.
"""

from __future__ import annotations

import html as _html
import re

_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</(p|div|li|h[1-6]|tr|section|article)\s*>", re.I)
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n\s*\n+")


def to_text(markup: str, *, keep_newlines: bool = False) -> str:
    """Convert an HTML fragment to readable plain text."""
    if not markup:
        return ""
    text = _SCRIPT_RE.sub(" ", markup)
    if keep_newlines:
        text = _BR_RE.sub("\n", text)
        text = _BLOCK_RE.sub("\n", text)
    else:
        text = _BLOCK_RE.sub(" ", text)
        text = _BR_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text)
    if keep_newlines:
        text = _NL_RE.sub("\n", text)
        return "\n".join(line.strip() for line in text.splitlines()).strip()
    return text.strip()


def first_sentences(text: str, *, max_chars: int = 320, max_sentences: int = 2) -> str:
    """A crude extractive summary: leading sentences, hard-capped on length."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    if len(text) <= max_chars:
        return text

    out: list[str] = []
    buf = ""
    for chunk in re.split(r"(?<=[.!?])\s+", text):
        if not chunk:
            continue
        candidate = f"{buf} {chunk}".strip() if buf else chunk
        if len(candidate) > max_chars and out:
            break
        buf = candidate
        out.append(buf)
        buf = ""
        if len(out) >= max_sentences:
            break

    result = buf or (out[-1] if out else text)
    result = " ".join(result.split())
    if len(result) > max_chars:
        result = result[: max_chars - 1].rstrip(" ,;:") + "…"
    return result


def absolutize(base: str, href: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base, href)
