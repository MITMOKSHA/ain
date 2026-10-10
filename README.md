<div align="center">

# ain

**A personal AI-trends learning agent — fetch, rank, summarize, and turn news into concepts you can actually use.**

Fetch from 10 sources → score by your interests → pull full article text → optionally extract
transferable technical concepts with an LLM → read it all in a local web UI.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#design-decisions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[中文文档](README.zh-CN.md) · [Quick start](#quick-start) · [Features](#features) · [How it works](#how-it-works) · [Configuration](#configuration)

</div>

---

## Why this exists

Staying current in AI means reading a firehose. Two things usually go wrong:

1. **You drown.** Hundreds of papers and posts a day; no time to triage.
2. **You learn nothing.** Even when you read, you get *events* ("X released model Y"),
   not *transferable knowledge* ("why mode dropping makes an LLM's confidence score untrustworthy").

`ain` addresses both. Rule-based scoring handles triage — deterministic, free, and explainable
(every item shows which keywords matched). An optional LLM stage handles the part rules cannot do:
extracting the engineering concepts worth remembering.

> **Design principle:** the LLM never decides *what you see*, only *how it's explained*.
> Ranking must be reproducible — the same data must produce the same order tomorrow.

## Features

- **10 sources out of the box** — arXiv (cs.AI/LG/CL/CV), OpenAI, DeepMind, Google AI, Anthropic,
  Hacker News, plus four Chinese tech outlets (量子位 / 新智元 / InfoQ 中文 / Solidot).
- **Full article text** — most feeds carry only a teaser (InfoQ literally sends `点击查看原文>`).
  `ain` follows the link and extracts the body via a four-stage fallback cascade.
- **Transparent scoring** — keyword weights × freshness decay + source weight + engagement.
  Every score is explained; no black box.
- **Concept cards (optional)** — `{"name", "what", "how"}` per article: what it is, what problem it
  solves, and how to use it in practice.
- **Knowledge topics** — items clustered by technical theme across days and sources, not just by date.
- **Local web UI** — browse, search, filter, expand full text. Three views: Archive / Daily digest / Topics.
- **Token accounting** — a local ledger reports exactly what each run cost.
- **Zero dependencies** — standard library only. No `pip install`, no database, no build step.

## Quick start

```bash
git clone https://github.com/<you>/ain.git
cd ain

python3 -m ain fetch     # fetch and rank
python3 -m ain serve     # http://127.0.0.1:8848
```

That's the whole setup. **Python 3.11+ and nothing else.**

Prefer clicking? Open the web UI and press **获取最新 / Fetch latest**.

> **Fresh clone is empty by design.** The archive (`data/`) is gitignored, so your first run starts
> from zero. Nothing is broken.

## Features in detail

### Three views, three questions

| View | Question it answers | URL |
| --- | --- | --- |
| **Archive** (default) | "Where was that thing I saw last week?" — full history, searchable | `/` |
| **Daily digest** | "What's worth reading today?" — the curated set from the last run | `/` → toggle |
| **Topics** | "How does this field actually fit together?" — clustered by theme | `/knowledge` |

### Concept cards (requires an LLM)

Without an LLM you get titles, rule-based summaries, and keyword-clustered topics — useful, but
strictly "what happened". With one configured, each item gains cards like:

> **Mode dropping (RLHF)** — RLHF training makes a model prefer safe, common answers, discarding the
> tails of the distribution. Its stated confidence stops reflecting real uncertainty.
> **In practice:** don't treat fluent, confident phrasing as a confidence signal; use explicit
> scores plus thresholds to route between auto-execute / human-review / reject.

That kind of distillation cannot be done with regexes. It is the one part of this project that
genuinely needs a model.

## How it works

```
 10 sources ──► normalize ──► dedupe ──► score ──► select ──► full text ──► concepts ──► store
   adapters      Item         title+URL   rules     top-N      cascade      (LLM)       JSONL
                              fingerprint  +decay   +caps      fallback     optional
```

**Scoring formula** (all from config, no model involved):

```
relevance  = Σ(keyword weight × 1.6 if in title else 1.0)  + category boost
             ×1.25 if ≥5 distinct keywords matched        (breadth bonus)
freshness  = 0.5 ^ (age_hours / half_life_hours)
score      = relevance × freshness + source_bonus + engagement_bonus
```

A real example, fully traced:

```
Item: "GPT-6.1 Sol" [新智元]

  strong  openai   3.0 × 1.0 (body only)   +3.00
  strong  gpt      3.0 × 1.6 (title hit)   +4.80
  strong  chatgpt  3.0 × 1.0               +3.00
  strong  codex    3.0 × 1.0               +3.00
  medium  api      1.5 × 1.0               +1.50
                                 relevance = 15.30
  category boost (cn)                      +1.50  → 16.80
  breadth bonus (5 distinct keywords)      ×1.25  → 21.00
  freshness: 16.2h old, 60h half-life      ×0.829 → 17.41
  source weight (1.2−1.0)×1.5              +0.30
                                           ───────
                                     score = 17.71
```

Because ranking is pure arithmetic, it is reproducible and debuggable. There is no nondeterminism
in what you see.

## Installation

None. `ain` is stdlib-only:

```bash
git clone https://github.com/<you>/ain.git && cd ain
python3 -m ain doctor    # environment self-check
```

Python **3.11+** is required (`tomllib`). If you also want the optional `ain` console script:

```bash
pip install -e .    # optional, provides the `ain` command
```

## Usage

| Command | Purpose |
| --- | --- |
| `python3 -m ain fetch` | Fetch, rank, extract text, record the digest |
| `python3 -m ain fetch --llm` | Same, plus LLM concept extraction (needs a key) |
| `python3 -m ain serve` | Start the web UI |
| `python3 -m ain sources` | Connectivity check per source |
| `python3 -m ain query "rag"` | Search the archive |
| `python3 -m ain usage` | LLM token spend and cost estimate |
| `python3 -m ain enrich` | Backfill concept cards onto older archive items |
| `python3 -m ain doctor` | Environment self-check |
| `python3 -m ain show` | Print the latest Markdown report (if exported) |

Useful flags:

```bash
python3 -m ain fetch -n 50                    # keep up to 50 items
python3 -m ain fetch --sources arxiv-cs-ai    # debug one source (won't replace the digest)
python3 -m ain fetch --dry-run                # preview without writing
python3 -m ain fetch --no-content             # skip full-text fetching (faster)
python3 -m ain fetch --llm                    # enable concept extraction
python3 -m ain fetch --markdown               # also export a Markdown report
```

## Configuration

Two files, no code changes needed. Both are plain TOML with inline comments.

### `config/interests.toml` — what ranks highest

| Key | Meaning |
| --- | --- |
| `strong` | High-value keywords (big score boost) |
| `medium` | Related keywords (moderate boost) |
| `negative` | Noise to penalize (recruiting, ads, podcast promos) |
| `cn_strong` / `cn_medium` | **Chinese keywords, configured separately** |

> **Why Chinese keywords are a separate list:** English keywords cannot match Chinese titles.
> "大模型推理加速" contains no English token, so an English-only keyword list scores it `0` and the
> relevance gate drops it — silently discarding every Chinese source you added.
> Chinese has no word separators, so these match by **substring**, not word boundary. Avoid very
> short terms (`模型` would match almost everything).

```toml
[scoring]
half_life_hours = 60.0   # freshness half-life; larger = less "recency bias"
top_n = 30               # max items per digest
per_source_cap = 12      # no single source may dominate
min_score = 1.5          # cutoff for entering the digest
strong_weight = 3.0
medium_weight = 1.5
negative_weight = -4.0
max_age_days = 21.0
```

### `config/sources.toml` — where content comes from

```toml
[[source]]
id = "arxiv-cs-ai"       # stable id
type = "arxiv"           # adapter
name = "arXiv cs.AI"     # display name
category = "paper"       # paper|vendor|cn|release|community|news|other
weight = 1.3             # higher = more likely to surface
enabled = true
limit = 80
```

Available `type` values: `rss` (aliases `feed`, `atom`), `arxiv`, `hackernews` (alias `hn`),
`html_list` (for sites without a feed), `hf_models`, `hf_blog`, `reddit`.

**The `keep_all` flag** — curated sources (OpenAI/Anthropic/DeepMind blogs, Chinese outlets)
publish rarely and are relevant by definition. Marking them `keep_all = true` skips both the
keyword gate and the score cutoff. Without it you get real failures: *"Gemini 4 Argon released"*
was silently dropped because its title happened to contain no keyword from the list.
Do **not** set this on firehose sources (HN, arXiv).

### `config/settings.toml` — output toggles

```toml
[output]
write_markdown = false   # Markdown export is off by default; the web UI is primary
```

### Enabling the LLM stage (optional)

Put your key in a `.env` at the repo root (gitignored). Copy `.env.example` to start:

```bash
cp .env.example .env
```

```bash
# Any OpenAI-compatible endpoint works
AIN_LLM_API_KEY=sk-...
AIN_LLM_BASE_URL=https://api.deepseek.com/v1
AIN_LLM_MODEL=deepseek-chat
```

> **Precedence: real environment variables override `.env`.** So a one-off override works:
> `AIN_LLM_MODEL=xxx python3 -m ain fetch --llm`.

Works with OpenAI, DeepSeek, Moonshot, Qwen, or a local vLLM/Ollama server. Two gotchas already handled:

- **Streaming-only backends** (e.g. Tencent's copilot gateway) — `ain` retries with `stream: true`
  and reassembles the SSE chunks automatically.
- **JSON wrapped in ` ```json ` fences** — the parser strips code fences and surrounding prose.

Without a key, `--llm` degrades gracefully to rule-based summaries. The fetch never fails.

## Cost

**Items already carrying concept cards are never re-sent to the model** (matched by content id),
so you only pay for genuinely new items.

Measured on a 253-item archive:

| Operation | Spend |
| --- | --- |
| `fetch --llm`, 30 items (only 2 new) | 1 call, 723 in / 216 out ≈ **$0.0002** |
| `fetch --llm`, 30 items (8 new) | 2 calls, 2,724 in / 1,958 out ≈ **$0.0016** |
| `enrich` backfilling 217 items (one-off) | 37 calls, 35k in / 55k out ≈ **$0.04** |

Roughly **a few dollars per month** for daily use. The one-off backfill dominates the total.

```bash
python3 -m ain usage            # summary
python3 -m ain usage -v         # per-day breakdown
python3 -m ain usage --price-in 0.3 --price-out 1.2   # different provider/pricing
```

> Prices default to DeepSeek off-peak. **This is an estimate, not a bill.** Many gateways expose no
> balance API (verified: `/credits`, `/balance`, `/usage` all 404), so `ain` keeps a local ledger in
> `data/usage.jsonl`. Usage of the same key elsewhere is not counted.

## Scheduling

**macOS (launchd)** — use the generator, which writes absolute paths for the current checkout:

```bash
sh scripts/install-launchd.sh                   # 08:30 and 20:30 daily
sh scripts/install-launchd.sh --hours "9" --minute 0
sh scripts/install-launchd.sh --uninstall
```

**cron:**

```bash
0 9 * * * /bin/sh /path/to/ain/scripts/daily.sh
```

`daily.sh` derives the project root from its own location, so it survives moving or cloning elsewhere.

**GitHub Actions** — included as `.github/workflows/daily.yml`. Useful if `huggingface.co` or
`reddit.com` are unreachable from your network: GitHub's runners can reach them. Add
`AIN_LLM_API_KEY` as a repository secret (optional — without it, runs are rule-based and free),
and set `enabled = true` on the sources you want.

## Adding a source

Create an adapter and register it. For a standard feed, no code is needed at all:

```toml
[[source]]
id = "my-blog"
type = "rss"
name = "My Blog"
url = "https://example.com/feed.xml"
category = "vendor"
weight = 1.2
```

For a custom adapter, subclass `Source` and add one line to `ain/sources/__init__.py:REGISTRY`.

## Project layout

```
ain/
  cli.py              command-line entry point
  pipeline.py         fetch → dedupe → score → full text → concepts
  web.py              web server (stdlib http.server) + JSON API
  web/index.html      Archive / Daily digest view
  web/knowledge.html  Topics view
  scorer.py           rule-based ranking (deterministic)
  content.py          article extraction (JSON-LD → container → <p> → meta)
  enrich.py           concurrent full-text fetch + archive reuse
  summarize.py        rule-based summary + LLM concept extraction
  env.py              .env loader (stdlib; env vars win)
  report.py           Markdown export (off by default)
  store.py            JSONL archive + cross-process lock + search + token ledger
  config.py           config loading
  http.py             HTTP with retries and gzip
  html.py             HTML → text, extractive summaries
  models.py           Item model
  sources/            per-source adapters
config/
  sources.toml        source list          ← edit often
  interests.toml      interest profile     ← edit often
  settings.toml       output toggles
scripts/
  daily.sh            scheduled-run entry point
  install-launchd.sh  generate a launchd agent for this checkout
.github/workflows/
  daily.yml           GitHub Actions schedule
data/items.jsonl      archive with bodies and concept cards (generated)
data/runs.jsonl       per-run record incl. selected_ids (digest source of truth)
data/usage.jsonl      LLM token ledger (generated)
```

## Design decisions

1. **Zero dependencies.** Chosen after measuring a 25-second PyPI round trip on the target network.
   The cost is maintaining our own RSS parser — which handles RSS 2.0, Atom, RSS 1.0 and common
   namespace extensions.
2. **Rules rank, the LLM explains.** Ranking must be reproducible and auditable; prose does not.
3. **The LLM is not on the critical path.** Missing key, failed call, timeout — all degrade to
   rule-based summaries. A fetch never dies because a model was unavailable.
4. **Full text only for selected items.** Fetching bodies for everything would mean 250+ requests
   per run; fetching the top ~40 keeps a run in the minutes range.
5. **Archive reuse.** Bodies and concept cards are keyed by content id, so re-runs neither
   re-download nor re-bill.
6. **Failure isolation.** A dead source affects only itself. Exit code is non-zero only if
   *every* source failed.
7. **Cross-process lock.** A scheduled run and a manual run cannot interleave writes to
   `items.jsonl`. The lock self-reclaims if a run dies.
8. **The archive keeps everything; the digest shows the top N.** Anything not in today's digest is
   still searchable later.

## Known limitations

- **JS-rendered pages yield no body.** Sites like 新智元 only expose `og:description`
  (~70–110 chars). Fixing this needs a headless browser, which conflicts with zero dependencies.
- **Extraction is heuristic.** A site redesign can degrade one source to its meta description.
  Degradation is graceful; nothing crashes.
- **Scoring uses the feed teaser, not the body** (bodies are fetched after scoring). Keywords that
  appear only in the body do not affect relevance — the direct consequence of fetching only top-N.
- **arXiv uses abstracts, not PDFs.** Sufficient for relevance; PDFs would need extra dependencies.
- **Concept quality depends on the model.** A cheap model may produce shallow cards. The prompt
  lives in `ain/summarize.py:SYSTEM_PROMPT`.
- **`POST /api/fetch` has no authentication.** It binds to `127.0.0.1` by default, which is safe
  locally. **Before exposing it publicly, add authentication** — otherwise anyone can trigger runs
  repeatedly and, with an LLM key configured, spend your money.

## Troubleshooting

```bash
python3 -m ain doctor        # environment self-check
python3 -m ain sources       # which sources are failing
tail -50 logs/fetch.log      # scheduled-run log
```

| Symptom | Fix |
| --- | --- |
| Digest is too short | Lower `min_score`, or raise `top_n` in `config/interests.toml` |
| A topic you care about never appears | Add keywords to `keywords.strong` |
| A source keeps failing | Set `enabled = false` for it in `config/sources.toml` |
| "another ain process is running" | One really is; if not, delete `data/.lock` |
| Everything is English | Configure an LLM — it also writes Chinese summaries for English items |

## Contributing

Issues and pull requests are welcome. The most valuable contributions are **new source adapters**
and **keyword list improvements**. If you add a source, please note in the PR whether it worked
from a mainland-China network.

The project is deliberately dependency-free. PRs adding a third-party runtime dependency will
generally be declined unless there's a strong reason.

## License

[MIT](LICENSE)
