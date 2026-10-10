"""Command line interface.

    python -m ain fetch              # 抓取 + 打分 + 写日报
    python -m ain sources            # 体检各信源连通性
    python -m ain query "rag" -n 20  # 查历史归档
    python -m ain show               # 打印最近一期日报
    python -m ain doctor             # 环境自检
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .models import Item, parse_dt
from .pipeline import run
from .report import write_report
from .sources import build_source
from .store import Store, run_lock, search_items

ROOT = Path(__file__).resolve().parent.parent


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _load(args) -> "object":
    root = Path(args.root).expanduser().resolve() if getattr(args, "root", None) else ROOT
    return load_config(root)


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------

def cmd_fetch(args) -> int:
    config = _load(args)
    now = datetime.now(timezone.utc)

    print(f"→ 抓取 {len(config.enabled_sources)} 个信源 ...", file=sys.stderr)
    result = run(
        config,
        use_llm=args.llm,
        top_n=args.top,
        per_source_cap=args.per_source,
        min_score=args.min_score,
        only_sources=args.sources,
        dry_run=args.dry_run,
        no_content=getattr(args, "no_content", False),
    )

    ok = len(result.ok_sources)
    total_sources = len(result.source_results)
    print(
        f"→ 信源 {ok}/{total_sources} 成功，抓到 {len(result.items)} 条(去重后归档), "
        f"新增 {result.added}, 更新 {result.updated}",
        file=sys.stderr,
    )
    if result.content_stats:
        cs = result.content_stats
        print(
            f"→ 正文抓取: {cs.get('ok', 0)} 成功 / {cs.get('failed', 0)} 失败 "
            f"(跳过 {cs.get('skipped', 0)})",
            file=sys.stderr,
        )
    usage = result.llm_usage or {}
    if usage.get("calls"):
        pin = usage.get("prompt_tokens", 0)
        pout = usage.get("completion_tokens", 0)
        print(
            f"→ LLM: {usage['calls']} 次调用, 输入 {pin:,} / 输出 {pout:,} tokens"
            + (f", 复用归档跳过 {result.llm_skipped} 条" if result.llm_skipped else ""),
            file=sys.stderr,
        )
    if result.failed_sources:
        for res in result.failed_sources:
            print(f"  ❌ {res.source_id}: {res.error}", file=sys.stderr)

    if args.dry_run:
        print("→ dry-run: 不写入文件", file=sys.stderr)
    elif config.write_markdown or args.markdown:
        path = write_report(
            result.items,
            config.reports_dir,
            now=now,
            source_results=result.source_results,
            duplicates=result.duplicates,
            summarizer_mode=result.summarizer_mode,
        )
        print(f"✓ 日报已写入 {path.relative_to(config.root)}", file=sys.stderr)
    else:
        print(
            "→ 精选已记入归档，网页可查看（Markdown 导出已关闭，"
            "用 --markdown 或 config/settings.toml 里 write_markdown = true 开启）",
            file=sys.stderr,
        )

    if args.json:
        print(json.dumps([json.loads(i.to_json()) for i in result.items], ensure_ascii=False, indent=2))

    # Exit non-zero only when everything failed - partial success is normal.
    return 0 if ok else 1


# --------------------------------------------------------------------------
# sources (health check)
# --------------------------------------------------------------------------

def cmd_sources(args) -> int:
    config = _load(args)
    sources = config.sources if args.all else config.enabled_sources

    def probe(src_cfg):
        try:
            items = build_source(src_cfg).fetch()
            newest = None
            for item in items:
                dt = item.published_dt
                if dt and (newest is None or dt > newest):
                    newest = dt
            return src_cfg, True, len(items), newest, ""
        except Exception as exc:
            return src_cfg, False, 0, None, f"{type(exc).__name__}: {exc}"

    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(probe, s) for s in sources]
        for future in as_completed(futures):
            results.append(future.result())

    order = {s.id: n for n, s in enumerate(sources)}
    results.sort(key=lambda r: order.get(r[0].id, 999))

    width = max((len(s.id) for s in sources), default=10)
    print(f"{'source'.ljust(width)}  {'state':6}  {'items':>5}  {'newest':16}  note")
    print("-" * (width + 50))
    for src_cfg, ok, count, newest, err in results:
        state = "OK" if ok else "FAIL"
        stamp = newest.astimezone().strftime("%Y-%m-%d %H:%M") if newest else "-"
        flag = "" if src_cfg.enabled else " (disabled)"
        note = err[:70] if err else f"{src_cfg.type}{flag}"
        print(f"{src_cfg.id.ljust(width)}  {state:6}  {count:5}  {stamp:16}  {note}")

    failed = sum(1 for r in results if not r[1])
    print(f"\n{len(results) - failed}/{len(results)} 可用")
    return 0 if failed == 0 else 1


# --------------------------------------------------------------------------
# query
# --------------------------------------------------------------------------

def cmd_query(args) -> int:
    config = _load(args)
    store = Store(config.data_dir)
    items = list(store.load().values())

    query = (args.text or "").lower()
    if query:
        items = search_items(items, query)

    if args.source:
        wanted = set(args.source)
        items = [i for i in items if i.source_id in wanted]
    if args.category:
        wanted = set(args.category)
        items = [i for i in items if i.category in wanted]
    if args.since:
        cutoff = parse_dt(args.since)
        if cutoff is None:
            print(f"无法解析 --since 值: {args.since}", file=sys.stderr)
            return 2
        items = [i for i in items if (i.published_dt or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]

    items.sort(key=lambda i: (i.score, i.published_at or ""), reverse=True)
    items = items[: args.limit]

    if args.json:
        print(json.dumps([json.loads(i.to_json()) for i in items], ensure_ascii=False, indent=2))
        return 0

    if not items:
        print("没有匹配的条目。", file=sys.stderr)
        return 0

    for item in items:
        dt = item.published_dt
        stamp = dt.astimezone().strftime("%Y-%m-%d") if dt else "----------"
        print(f"{stamp}  {item.score:6.2f}  [{item.source_name}] {item.title}")
        print(f"          {item.url}")
    print(f"\n共 {len(items)} 条", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# show / doctor
# --------------------------------------------------------------------------

def cmd_show(args) -> int:
    config = _load(args)
    reports = sorted(config.reports_dir.glob("*.md"))
    if not reports:
        print(
            "reports/ 里没有 Markdown 日报（默认不导出）。\n"
            "看内容请用网页：python3 -m ain serve\n"
            "要导出日报：python3 -m ain fetch --markdown\n"
            "要查历史：python3 -m ain query \"关键词\"",
            file=sys.stderr,
        )
        return 1
    target = reports[-1]
    if args.path:
        print(target)
        return 0
    print(target.read_text(encoding="utf-8"))
    return 0


def cmd_serve(args) -> int:
    from .web import serve

    config = _load(args)
    serve(config, host=args.host, port=args.port)
    return 0


def cmd_enrich(args) -> int:
    """Backfill LLM summaries/concepts onto items already in the archive.

    Needed because `fetch` only enriches the items it selects, so most of the
    archive has no topics. Without this the knowledge page mixes two naming
    schemes (LLM topics for recent items, keyword fallback for the rest), which
    splits one real topic into several near-duplicate threads.
    """
    from .enrich import reuse_archived
    from .summarize import Summarizer, collect_topics

    config = _load(args)
    store = Store(config.data_dir)
    items = list(store.load().values())

    pending = [i for i in items if not i.concepts]
    # Prefer items with real text to analyse.
    pending.sort(key=lambda i: (len(i.content or "") + len(i.summary or "")), reverse=True)
    if args.limit:
        pending = pending[: args.limit]

    if not pending:
        print("所有条目都已有概念卡片，无需补齐。", file=sys.stderr)
        return 0

    print(f"→ 待补齐 {len(pending)} 条（共 {len(items)} 条）", file=sys.stderr)
    if args.dry_run:
        for i in pending[:20]:
            print(f"   {i.score:6.2f} [{i.source_name}] {i.title[:60]}")
        print("→ dry-run: 不调用 LLM、不写文件", file=sys.stderr)
        return 0

    summarizer = Summarizer(use_llm=True)
    if not summarizer.use_llm:
        print("需要 LLM：请设置 AIN_LLM_API_KEY（可写在项目根目录的 .env）", file=sys.stderr)
        return 2

    known = collect_topics(items)
    batch = max(1, int(args.batch))
    done = 0
    for start in range(0, len(pending), batch):
        chunk = pending[start:start + batch]
        summarizer.summarize(chunk, known_topics=known)
        with run_lock(config.data_dir, wait=120):
            store.merge(chunk)
        done += len(chunk)
        known = collect_topics(items)
        print(
            f"   {done}/{len(pending)} 条，累计 {summarizer.usage['calls']} 次调用, "
            f"输出 {summarizer.usage['completion_tokens']:,} tokens",
            file=sys.stderr,
        )

    u = summarizer.usage
    with run_lock(config.data_dir, wait=120):
        store.record_usage(
            {
                "op": "enrich",
                "model": summarizer.model,
                "calls": u.get("calls", 0),
                "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "items": done,
            }
        )
    print(
        f"✓ 完成：{done} 条，{u['calls']} 次调用，"
        f"输入 {u['prompt_tokens']:,} / 输出 {u['completion_tokens']:,} tokens",
        file=sys.stderr,
    )
    return 0


def cmd_usage(args) -> int:
    """Show accumulated LLM token usage.

    The provider exposes no balance/usage API (verified: /credits, /balance and
    /usage all 404), so this reads the local ledger written by fetch/enrich.
    """
    config = _load(args)
    store = Store(config.data_dir)
    summary = store.usage_summary()

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    t = summary["totals"]
    if not summary["entries"]:
        print("还没有 LLM 消耗记录。")
        print("用法：python3 -m ain fetch --llm（或 python3 -m ain enrich）")
        return 0

    # Prices are configurable because they vary by provider and by peak/off-peak.
    price_in = args.price_in
    price_out = args.price_out
    cost = t["prompt_tokens"] / 1e6 * price_in + t["completion_tokens"] / 1e6 * price_out

    print("LLM token 消耗")
    print("=" * 58)
    print(f"  调用次数     {t['calls']:>12,}")
    print(f"  输入 tokens  {t['prompt_tokens']:>12,}")
    print(f"  输出 tokens  {t['completion_tokens']:>12,}")
    print(f"  合计 tokens  {t['prompt_tokens'] + t['completion_tokens']:>12,}")
    print(f"  估算费用     ${cost:>11.4f}  ≈ ¥{cost * args.rate:.2f}")
    print(f"  （按输入 ${price_in}/M、输出 ${price_out}/M，汇率 {args.rate}）")
    print(f"  统计区间     {summary['first']} → {summary['last']}")
    print()

    if len(summary["by_day"]) > 1 or args.verbose:
        print("按天：")
        for day, row in summary["by_day"].items():
            c = row["prompt_tokens"] / 1e6 * price_in + row["completion_tokens"] / 1e6 * price_out
            print(
                f"  {day}  {row['calls']:>4} 次  "
                f"入 {row['prompt_tokens']:>9,}  出 {row['completion_tokens']:>9,}  "
                f"¥{c * args.rate:.3f}"
            )
        print()

    print("按操作：")
    for op, row in summary["by_op"].items():
        c = row["prompt_tokens"] / 1e6 * price_in + row["completion_tokens"] / 1e6 * price_out
        print(
            f"  {op:<10} {row['calls']:>4} 次  "
            f"入 {row['prompt_tokens']:>9,}  出 {row['completion_tokens']:>9,}  "
            f"¥{c * args.rate:.3f}"
        )

    print()
    print("按模型：")
    for model, row in summary["by_model"].items():
        print(f"  {model:<28} {row['calls']:>4} 次  "
              f"入 {row['prompt_tokens']:>9,}  出 {row['completion_tokens']:>9,}")
    return 0


def cmd_doctor(args) -> int:
    config = _load(args)
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Python", sys.version_info >= (3, 11), sys.version.split()[0]))
    checks.append(("config/sources.toml", (config.root / "config" / "sources.toml").exists(),
                   f"{len(config.sources)} 个信源"))
    checks.append(("config/interests.toml", (config.root / "config" / "interests.toml").exists(),
                   f"强关键词 {len(config.interests.strong)} 个"))
    checks.append(("data 目录可写", _writable(config.data_dir), str(config.data_dir)))
    checks.append(("reports 目录可写", _writable(config.reports_dir), str(config.reports_dir)))

    key = os.environ.get("AIN_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    checks.append(("LLM API key", bool(key), "已设置" if key else "未设置（用规则摘要，正常）"))

    print("环境自检")
    print("-" * 60)
    for name, ok, note in checks:
        print(f"{'✅' if ok else '❌'} {name:24} {note}")

    enabled = config.enabled_sources
    print(f"\n启用信源 {len(enabled)}/{len(config.sources)}")
    for src in config.sources:
        mark = "•" if src.enabled else "○"
        print(f"  {mark} {src.id:22} {src.type:14} {src.name}")

    return 0 if all(ok for _, ok, _ in checks[:5]) else 1


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".ain-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ain",
        description="个人 AI 前沿信息 agent：抓取、打分、摘要、归档。",
    )
    parser.add_argument("--root", help="项目根目录（默认自动定位）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="抓取并生成日报")
    p_fetch.add_argument("-n", "--top", type=int, default=None, help="日报条数上限")
    p_fetch.add_argument("--per-source", type=int, default=None, help="单个信源条数上限")
    p_fetch.add_argument("--min-score", type=float, default=None, help="最低分数阈值")
    p_fetch.add_argument("-s", "--sources", nargs="*", help="只抓取指定 source id")
    p_fetch.add_argument("--llm", action="store_true", help="启用 LLM 中文摘要与概念提取（需 AIN_LLM_API_KEY）")
    p_fetch.add_argument("--dry-run", action="store_true", help="不写文件，只打印结果")
    p_fetch.add_argument("--no-content", action="store_true",
                         help="跳过正文抓取（更快，但摘要只有 RSS 里的内容）")
    p_fetch.add_argument("--markdown", action="store_true",
                         help="额外导出一份 Markdown 日报到 reports/（默认不生成）")
    p_fetch.add_argument("--json", action="store_true", help="同时输出 JSON")
    p_fetch.set_defaults(func=cmd_fetch)

    p_sources = sub.add_parser("sources", help="信源连通性体检")
    p_sources.add_argument("--all", action="store_true", help="包含已禁用的信源")
    p_sources.set_defaults(func=cmd_sources)

    p_query = sub.add_parser("query", help="查询历史归档")
    p_query.add_argument("text", nargs="?", help="搜索关键词（多个词为 AND）")
    p_query.add_argument("-n", "--limit", type=int, default=20)
    p_query.add_argument("--source", nargs="*", help="按 source id 过滤")
    p_query.add_argument("--category", nargs="*", help="按分类过滤")
    p_query.add_argument("--since", help="起始日期，如 2026-09-01")
    p_query.add_argument("--json", action="store_true")
    p_query.set_defaults(func=cmd_query)

    p_show = sub.add_parser("show", help="打印最近一期日报")
    p_show.add_argument("--path", action="store_true", help="只打印文件路径")
    p_show.set_defaults(func=cmd_show)

    p_serve = sub.add_parser("serve", help="启动本地网页界面")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8848)
    p_serve.set_defaults(func=cmd_serve)

    p_enrich = sub.add_parser(
        "enrich",
        help="给归档里的历史条目补概念卡片（修主题命名不一致）",
    )
    p_enrich.add_argument("-n", "--limit", type=int, default=0, help="最多处理多少条（0=全部）")
    p_enrich.add_argument("--batch", type=int, default=6, help="每批条数")
    p_enrich.add_argument("--dry-run", action="store_true", help="只看看要处理哪些")
    p_enrich.set_defaults(func=cmd_enrich)

    p_usage = sub.add_parser("usage", help="查看 LLM token 消耗与估算费用")
    p_usage.add_argument("-v", "--verbose", action="store_true", help="按天列出明细")
    p_usage.add_argument("--json", action="store_true", help="输出 JSON")
    p_usage.add_argument("--price-in", type=float, default=0.15,
                         help="输入价格（美元/百万 token，默认 0.15 = DeepSeek 低谷）")
    p_usage.add_argument("--price-out", type=float, default=0.6,
                         help="输出价格（美元/百万 token，默认 0.6 = DeepSeek 低谷）")
    p_usage.add_argument("--rate", type=float, default=7.1, help="美元兑人民币汇率")
    p_usage.set_defaults(func=cmd_usage)

    p_doc = sub.add_parser("doctor", help="环境自检")
    p_doc.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except Exception as exc:
        if args.verbose:
            raise
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
