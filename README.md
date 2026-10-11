<div align="center">

# ain

**A personal Agent-domain learning agent — fetch, gate, rank, summarize, and turn news into concepts you can actually use.**

Fetch from 14 sources → drop anything that isn't about agents → score by your interests → pull full
article text → optionally extract transferable agent-engineering concepts with an LLM → read it all
in a local web UI.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#design-decisions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[中文文档](README.zh-CN.md) · [Quick start](#quick-start) · [Features](#features) · [How it works](#how-it-works) · [Configuration](#configuration)

</div>

---

## Why this exists

Staying current in the **Agent** field means reading a firehose. Two things usually go wrong:

1. **You drown.** Hundreds of papers and posts a day; no time to triage — and most of them are about
   AI in general, not about building agents.
2. **You learn nothing.** Even when you read, you get *events* ("X released model Y"),
   not *transferable knowledge* ("why trimming stale tool results matters more than a bigger context
   window").

`ain` addresses both. A hard **domain gate** keeps the firehose pointed at one thing — agents: tool
use, context engineering, memory, orchestration frameworks, coding agents, computer use,
sandboxing/permissions, agent evaluation, multi-agent collaboration. Rule-based scoring then handles
triage — deterministic, free, and explainable (every item shows which keywords matched). An optional
LLM stage handles the part rules cannot do: extracting the engineering concepts worth remembering.

> **Design principle:** the LLM never decides *what you see*, only *how it's explained*.
> Ranking must be reproducible — the same data must produce the same order tomorrow.
> The domain gate reinforces this: inclusion is a rule, not a model judgement.

## Features

- **14 sources out of the box** — arXiv with a targeted Agent query, the Anthropic News and
  Anthropic Engineering blogs, LangChain, Simon Willison, Latent.Space, OpenAI, Google DeepMind,
  Google AI, Hacker News (Agent-filtered), plus four Chinese tech outlets
  (量子位 / 新智元 / InfoQ 中文 / Solidot).
- **A hard domain gate** — every item must match an Agent term in its title (or tags) to be included
  at all; off-topic news is dropped before the digest *and* before the archive.
- **Full article text** — most feeds carry only a teaser (InfoQ literally sends `点击查看原文>`).
  `ain` follows the link and extracts the body via a four-stage fallback cascade.
- **Transparent scoring** — keyword weights × freshness decay + source weight + engagement.
  Every score is explained; no black box.
- **Concept cards (optional)** — `{"name", "what", "how"}` per article: what it is, what problem it
  solves, and how to use it in practice.
- **Knowledge topics** — items clustered by Agent sub-domain (tool calling & MCP, context
  engineering, memory, orchestration, …) across days and sources, not just by date.
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
| **Topics** | "How does this field actually fit together?" — clustered by Agent sub-domain | `/knowledge` |

The page is titled **Agent 前沿**. All four web views (archive list, digest, topics, stats) apply the
same domain gate as the pipeline, so out-of-domain rows left over from an older archive are hidden
even before you run `prune`.

### Concept cards (requires an LLM)

Without an LLM you get titles, rule-based summaries, and keyword-clustered topics — useful, but
strictly "what happened". With one configured, each item gains cards like:

> **Context compression** — A long agent run fills the context window with tool output until the
> model loses sight of the original task. Compressing or trimming stale tool results between steps
> keeps the goal in view.
> **In practice:** summarize or discard tool output you no longer need instead of appending it
> verbatim; keep the first user turn and the most recent steps uncompressed.

That kind of distillation cannot be done with regexes. It is the one part of this project that
genuinely needs a model.

### Knowledge topics (Agent sub-domains)

Topic names are canonical and Agent-specific — *工具调用与 MCP, 上下文工程, 记忆与状态, 规划与任务分解,
Agent 编排与框架, 编码 Agent, 计算机操作 Agent, 多智能体协作, 沙箱与执行环境, Agent 安全, Agent 评测,
Agent 技能与运行时*. Two guards keep the topics view useful:

- **Catch-all names are dropped.** A topic called "AI Agent" / "Agent" / "智能体" partitions nothing
  now that agents are the entire domain, so it is filtered out rather than rendered as one giant bucket.
- **Synonyms are folded.** The LLM coins the same idea differently on different days; a synonym map
  maps near-duplicates onto the canonical name so one thread does not split in two.

The LLM system prompt in `ain/summarize.py` is Agent-specific: it forbids catch-all topic names,
requires concrete Agent sub-domains, and asks for transferable agent-engineering concepts rather
than company news.

## How it works

```
 14 sources ──► normalize ──► dedupe ──► domain gate ──► score ──► select ──► full text ──► concepts ──► store
   adapters      Item          title+URL   keep only       rules     top-N      cascade      (LLM)       JSONL
                              fingerprint  Agent titles    +decay    +caps      fallback     optional
```

The **domain gate** runs before ranking and is a keep/drop decision, not a weight: an item must match
an Agent term to survive. It reads the **title** (plus tags), deliberately not the summary — a media
roundup whose summary happens to mention "MCP" is not an agent story, while a real one almost
always says so in its title. The pipeline persists only items that passed the gate, so the archive
never accumulates news the digest excluded. Each run records the number dropped as `out_of_domain`
in `data/runs.jsonl`, which is the first thing to check when a digest looks thin.

**Scoring formula** (all from config, no model involved):

```
relevance  = Σ(keyword weight × 1.6 if in title else 1.0)  + category boost
             ×1.25 if ≥5 distinct keywords matched        (breadth bonus)
freshness  = 0.5 ^ (age_hours / half_life_hours)
score      = relevance × freshness + source_bonus + engagement_bonus
```

A real example, fully traced:

```
Item: "How we built a coding agent with reliable tool use" [LangChain]

  strong  coding agent  3.0 × 1.6 (title hit)   +4.80
  strong  agent         3.0 × 1.6 (title hit)   +4.80
  strong  tool use      3.0 × 1.6 (title hit)   +4.80
  strong  tool calling  3.0 × 1.0 (body only)   +3.00
  medium  framework     1.5 × 1.0               +1.50
                                     relevance = 18.90
  category boost (vendor)                      +1.50  → 20.40
  breadth bonus (5 distinct keywords)          ×1.25  → 25.50
  freshness: 16.2h old, 60h half-life          ×0.829 → 21.14
  source weight (1.4−1.0)×1.5                  +0.60
                                                ───────
                                          score = 21.75
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
| `python3 -m ain fetch` | Fetch, apply the domain gate, rank, extract text, record the digest |
| `python3 -m ain fetch --llm` | Same, plus LLM concept extraction (needs a key) |
| `python3 -m ain serve` | Start the web UI |
| `python3 -m ain sources` | Connectivity check per source |
| `python3 -m ain query "rag"` | Search the archive |
| `python3 -m ain prune` | Remove archive rows that no longer pass the domain gate |
| `python3 -m ain usage` | LLM token spend and cost estimate |
| `python3 -m ain enrich` | Backfill concept cards onto older archive items |
| `python3 -m ain doctor` | Environment self-check |
| `python3 -m ain show` | Print the latest Markdown report (if exported) |

Useful flags:

```bash
python3 -m ain fetch -n 50                    # keep up to 50 items
python3 -m ain fetch --sources arxiv-agents   # debug one source (won't replace the digest)
python3 -m ain fetch --dry-run                # preview without writing
python3 -m ain fetch --no-content             # skip full-text fetching (faster)
python3 -m ain fetch --llm                    # enable concept extraction
python3 -m ain fetch --markdown               # also export a Markdown report
python3 -m ain prune --dry-run                # list out-of-domain archive rows, delete nothing
```

> **After narrowing the domain, run `prune` once.** The gate governs what new runs write; rows already
> in `data/items.jsonl` from before the gate (or from a wider config) keep feeding search, the topics
> view and the stats. `prune` deletes exactly the rows that fail the current gate and is safe to
> re-run.

## Configuration

Two files, no code changes needed. Both are plain TOML with inline comments.

### `config/interests.toml` — what's in scope, and what ranks highest

| Key | Meaning |
| --- | --- |
| `[domain].require` | `true` turns the hard topic gate on |
| `[domain].keywords` | An item must match one of these Agent terms to be kept at all |
| `strong` | High-value keywords (big score boost) |
| `medium` | Related keywords (moderate boost) |
| `negative` | Noise to penalize (recruiting, ads, podcast promos) |
| `cn_strong` / `cn_medium` | **Chinese keywords, configured separately** |

The gate is what makes this an Agent tracker rather than an AI tracker. Weights only *reorder* what
came in; the gate decides **inclusion**, and unlike a score threshold it cannot be outvoted by
source weight or engagement points. It matches the **title** (plus tags) and deliberately not the
summary: a media roundup whose summary happens to mention "MCP" is not an agent story, whereas a
real one almost always advertises itself in the title. Items that fail it are excluded from the
digest *and never written to the archive*, so they cannot resurface through search or the topics
view. Domain keywords are folded into `strong` automatically, so they are not listed twice.

```toml
[domain]
require = true
keywords = [
  "agent", "agents", "agentic", "multi-agent", "subagent",
  "tool use", "tool calling", "function calling", "mcp", "model context protocol",
  "coding agent", "claude code", "codex", "computer use", "browser agent",
  "context engineering", "agent memory", "long-term memory", "task decomposition",
  "sandboxing", "prompt injection", "agent security", "agent evaluation",
  "langgraph", "langchain", "agent harness",
  # Chinese terms are matched as substrings, like cn_strong below
  "智能体", "多智能体", "工具调用", "上下文工程", "沙箱", "长期记忆",
]
```

> **Why Chinese keywords are a separate list:** English keywords cannot match Chinese titles.
> "大模型推理加速" contains no English token, so an English-only keyword list scores it `0` and the
> relevance gate drops it — silently discarding every Chinese source you added.
> Chinese has no word separators, so these match by **substring**, not word boundary. Avoid very
> short terms (`模型` would match almost everything).

> **Widening the gate.** If legitimate Agent stories are being dropped (arXiv is exempt, but other
> sources are not), add the term they use to `[domain].keywords` rather than turning the gate off.
> `require = false` keeps every source's output and falls back to pure ranking.

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
id = "arxiv-agents"      # stable id
type = "arxiv"           # adapter
name = "arXiv · Agent 方向"  # display name
category = "paper"       # paper|vendor|cn|release|community|news|other
weight = 1.6             # higher = more likely to surface
categories = ["cs.AI", "cs.CL", "cs.SE", "cs.MA"]
query = '(abs:"LLM agent" OR abs:"agentic" OR abs:"tool use" ...)'
domain_exempt = true     # the query already narrows to Agent on the abstract
```

Available `type` values: `rss` (aliases `feed`, `atom`), `arxiv`, `hackernews` (alias `hn`),
`html_list` (for sites without a feed), `hf_models`, `hf_blog`, `reddit`.

The enabled set is 14 sources: `arxiv-agents`, `anthropic-news`, `anthropic-engineering`,
`langchain-blog`, `simon-willison`, `latent-space`, `openai-news`, `deepmind-blog`,
`google-ai-blog`, `hn-ai`, `qbitai`, `aiera`, `infoq-cn`, `solidot`. `hf-models` and
`reddit-localllama` ship disabled because `huggingface.co` and `reddit.com` are unreachable from
mainland China without a proxy.

**Two separate per-source flags** — neither implies the other:

| Flag | What it skips | Use it for |
| --- | --- | --- |
| `keep_all = true` | The keyword threshold and the `min_score` cutoff | Curated sources that publish rarely |
| `domain_exempt = true` | The Agent domain gate | Sources that are Agent-only end to end |

`keep_all` still has to clear the domain gate. Curated blogs (OpenAI, Anthropic, DeepMind, the
Chinese outlets) publish rarely, so a low score there reflects an old publish date rather than
irrelevance — that is all `keep_all` claims. It does **not** claim everything the source publishes
is in scope. Only sources that are Agent-only end to end set `domain_exempt`:
`arxiv-agents` (its query matches Agent terms on the abstract, so a second title check would wrongly
kill papers like *"Mental-Models for …"*) and `langchain-blog`. Do **not** set `keep_all` on
firehose sources (HN, arXiv).

Note the gate's honest boundary: its term list contains Agent **product names** such as `codex`,
`claude code` and `mcp`, so a vendor case study titled *"Oracle cut hours with Codex"* passes
(verified). A title carrying an Agent product name is the strongest signal the gate can get, and
the price is the occasional vendor case study. Drop `codex` from `[domain].keywords` if you would
rather have it gone — at the cost of missing real Codex Agent updates.

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

Measured on a 253-item archive (**a figure from before this change and not re-measured**; the costs
are per-run and depend on how many items are new, not on archive scope):

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

> **GitHub Actions was removed.** This repo previously shipped `.github/workflows/daily.yml`,
> which ran a fetch on GitHub's runners and force-committed the archive back with
> `git add -f data/`. Two problems made that a bad fit: it kept running the old
> broad-AI source list, and force-adding `data/` overrode the local `.gitignore`,
> so out-of-domain archives were pushed into the repo. If you want scheduled runs
> that can reach `huggingface.co` / `reddit.com`, re-add a workflow yourself — and
> commit no archive, or commit only what passes the domain gate.

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

A new source is subject to the domain gate like any other, so only add `domain_exempt = true` if the
source honestly covers nothing but agents. If it is a curated blog that publishes rarely, `keep_all`
is the right flag — it is a different claim.

## Project layout

```
ain/
  cli.py              command-line entry point (fetch / prune / serve / …)
  pipeline.py         fetch → dedupe → domain gate → score → full text → concepts
  web.py              web server (stdlib http.server) + JSON API (same domain gate)
  web/index.html      Archive / Daily digest view ("Agent 前沿")
  web/knowledge.html  Topics view
  scorer.py           rule-based ranking + Scorer.in_domain (deterministic)
  content.py          article extraction (JSON-LD → container → <p> → meta)
  enrich.py           concurrent full-text fetch + archive reuse
  summarize.py        rule-based summary + Agent-specific LLM concept extraction
  env.py              .env loader (stdlib; env vars win)
  report.py           Markdown export (off by default)
  store.py            JSONL archive + cross-process lock + search + prune + token ledger
  config.py           config loading (incl. the [domain] gate)
  defaults.py         fallback source list, used only if config/sources.toml is missing
  http.py             HTTP with retries and gzip
  html.py             HTML → text, extractive summaries
  models.py           Item model
  sources/            per-source adapters
config/
  sources.toml        source list                              ← edit often
  interests.toml      domain gate + interest profile           ← edit often
  settings.toml       output toggles
scripts/
  daily.sh            scheduled-run entry point
  install-launchd.sh  generate a launchd agent for this checkout
data/items.jsonl      archive with bodies and concept cards (generated, untracked)
data/runs.jsonl       per-run record incl. selected_ids and out_of_domain
data/usage.jsonl      LLM token ledger (generated)
```

## Design decisions

1. **Zero dependencies.** Chosen after measuring a 25-second PyPI round trip on the target network.
   The cost is maintaining our own RSS parser — which handles RSS 2.0, Atom, RSS 1.0 and common
   namespace extensions.
2. **Rules rank, the LLM explains.** Ranking must be reproducible and auditable; prose does not.
3. **Inclusion is a gate, not a weight.** The Agent domain gate is a title-level keep/drop rule, so
   no source weight, engagement bonus or model opinion can carry an off-topic story into the report.
   It is the deterministic half of "the LLM never decides what you see".
4. **The LLM is not on the critical path.** Missing key, failed call, timeout — all degrade to
   rule-based summaries. A fetch never dies because a model was unavailable.
5. **Full text only for selected items.** Fetching bodies for everything would mean 250+ requests
   per run; fetching the top ~40 keeps a run in the minutes range.
6. **Archive reuse.** Bodies and concept cards are keyed by content id, so re-runs neither
   re-download nor re-bill.
7. **Failure isolation.** A dead source affects only itself. Exit code is non-zero only if
   *every* source failed.
8. **Cross-process lock.** A scheduled run and a manual run cannot interleave writes to
   `items.jsonl`. The lock self-reclaims if a run dies.
9. **The archive keeps everything in scope; the digest shows the top N.** Anything not in today's
   digest is still searchable later — but anything outside the domain is not archived at all, and
   `prune` is the cleanup path for rows written before the gate existed.

## Known limitations

- **JS-rendered pages yield no body.** Sites like 新智元 only expose `og:description`
  (~70–110 chars). Fixing this needs a headless browser, which conflicts with zero dependencies.
- **Extraction is heuristic.** A site redesign can degrade one source to its meta description.
  Degradation is graceful; nothing crashes.
- **Scoring uses the feed teaser, not the body** (bodies are fetched after scoring). Keywords that
  appear only in the body do not affect relevance — the direct consequence of fetching only top-N.
- **The domain gate reads the title, not the body or summary.** That is deliberate (the summary let a
  third of the curated-source noise through in testing), but it has a cost: a real Agent story whose
  title never says so is dropped. Widen `[domain].keywords` or set `domain_exempt = true` on a source
  that is Agent-only end to end.
- **"Agent" is an overloaded word.** In an RL paper it means something else, which is why the
  domain list stays narrow, the arXiv source narrows at the query level, and that source is exempt
  from a second title check.
- **Pre-gate archives need `prune`.** The web views hide out-of-domain rows, but they still occupy
  space in `data/items.jsonl` until you run `python3 -m ain prune`.
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
| Digest is too short | Check `out_of_domain` in `data/runs.jsonl` first: if it is high, broaden `[domain].keywords` in `config/interests.toml`. Otherwise lower `min_score` or raise `top_n` |
| Everything looks like general AI news, not agents | The gate may be off — check `[domain].require = true`, then run `python3 -m ain prune --dry-run` to see what is out of scope |
| A specific Agent story was dropped | Add the term its title uses to `[domain].keywords`, or set `domain_exempt = true` for that source if it is Agent-only end to end |
| Archive still shows non-Agent items | `python3 -m ain prune` (the web views hide them, the archive file still holds them) |
| A topic you care about never appears | Add keywords to `keywords.strong` |
| A source keeps failing | Set `enabled = false` for it in `config/sources.toml` |
| "another ain process is running" | One really is; if not, delete `data/.lock` |
| Everything is English | Configure an LLM — it also writes Chinese summaries for English items |

## Contributing

Issues and pull requests are welcome. The most valuable contributions are **new source adapters**
and **keyword list improvements** — in particular Agent terms that the `[domain]` list is currently
missing. If you add a source, please note in the PR whether it worked from a mainland-China network.

The project is deliberately dependency-free. PRs adding a third-party runtime dependency will
generally be declined unless there's a strong reason.

## License

[MIT](LICENSE)
