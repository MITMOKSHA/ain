"""Tiny stdlib HTTP helper: browser-ish headers, retries, transparent gzip.

A desktop user-agent matters here: several vendor sites (OpenAI in particular)
return 403 to requests that look like a bare script.
"""

from __future__ import annotations

import gzip
import io
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class HttpError(RuntimeError):
    pass


def _decode_body(raw: bytes, encoding: str | None) -> bytes:
    enc = (encoding or "").lower()
    if enc == "gzip":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    if enc == "deflate":
        try:
            return zlib.decompress(raw)
        except zlib.error:
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                return raw
    # Some servers send gzip bytes without advertising the encoding.
    if raw[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(raw)
        except OSError:
            return raw
    return raw


def fetch(
    url: str,
    *,
    timeout: float = 25.0,
    retries: int = 2,
    user_agent: str = DEFAULT_UA,
    headers: dict[str, str] | None = None,
) -> bytes:
    """GET `url` and return the decoded body bytes.

    Retries transient failures with a short, capped backoff. Raises HttpError
    with a human-readable reason once retries are exhausted.
    """
    hdrs = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, "
        "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if headers:
        hdrs.update(headers)

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers=hdrs, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return _decode_body(raw, resp.headers.get("Content-Encoding"))
        except urllib.error.HTTPError as exc:
            last_err = exc
            # 4xx other than 429 will not fix themselves; fail fast.
            if exc.code < 500 and exc.code != 429:
                raise HttpError(f"HTTP {exc.code} {exc.reason} for {url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, io.UnsupportedOperation) as exc:
            last_err = exc
        except Exception as exc:  # pragma: no cover - defensive
            last_err = exc

        if attempt < retries:
            time.sleep(min(1.5 * (attempt + 1), 4.0))

    raise HttpError(f"failed after {retries + 1} attempt(s): {last_err} ({url})")


def fetch_text(url: str, **kwargs) -> str:
    raw = fetch(url, **kwargs)
    # Feeds declare their own encoding; utf-8 with replacement is the pragmatic
    # default and avoids raising on a stray byte.
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def fetch_json(url: str, **kwargs):
    import json

    text = fetch_text(url, **kwargs)
    return json.loads(text)


def build_query(base: str, params: dict[str, object]) -> str:
    return f"{base}?{urllib.parse.urlencode(params)}"
