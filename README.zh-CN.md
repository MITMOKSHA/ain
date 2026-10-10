<div align="center">

# ain

**个人 AI 前沿学习 agent —— 获取、排序、摘要，把新闻变成真正能用的知识。**

从 10 个信源获取内容 → 按你的兴趣打分排序 → 取回原文正文 → 可选地用 LLM 提炼可迁移的技术概念
→ 在本地网页里阅读。

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#设计取舍)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md) · [快速开始](#快速开始) · [功能](#功能) · [工作原理](#工作原理) · [配置](#配置)

</div>

---

## 为什么做这个

跟踪 AI 前沿意味着阅读一条洪流。通常有两件事会出问题：

1. **被淹没**。每天几百篇论文和帖子，没时间筛选。
2. **学了等于没学**。即使读了，拿到的是*事件*（"某公司发布了某模型"），
   而不是*可迁移的知识*（"为什么模式坍缩让大模型的置信度不可信"）。

`ain` 同时针对这两点。**规则打分**负责筛选——确定性、零成本、可解释（每条都列出命中了哪些关键词）。
**可选的 LLM 阶段**负责规则做不到的事：提炼值得记住的工程概念。

> **设计原则：LLM 从不决定"你看到什么"，只决定"怎么解释"。**
> 排序必须可复现——同一批数据，今天和明天必须排出同样的顺序。

## 功能

- **开箱 10 个信源** —— arXiv（cs.AI/LG/CL/CV）、OpenAI、DeepMind、Google AI、Anthropic、
  Hacker News，以及四个中文源（量子位 / 新智元 / InfoQ 中文 / Solidot）。
- **原文正文** —— 多数 feed 只给一句话摘要（InfoQ 实际发的是 `点击查看原文>`）。
  `ain` 会跟进链接，用四层降级策略把正文取回来。
- **透明的打分** —— 关键词权重 × 时效衰减 + 信源权重 + 互动量。每一分都能解释，没有黑盒。
- **概念卡片（可选）** —— 每篇一个 `{"name", "what", "how"}`：这是什么、解决什么问题、工程上怎么用。
- **知识专题** —— 按技术主题跨天、跨信源聚合，而不是只按日期排列。
- **本地网页** —— 浏览、搜索、筛选、展开全文。三个视图：全部内容 / 今日精选 / 知识专题。
- **Token 记账** —— 本地账本记录每次运行真实花了多少。
- **零依赖** —— 只用标准库。不需要 `pip install`，不需要数据库，不需要构建步骤。

## 快速开始

```bash
git clone https://github.com/<you>/ain.git
cd ain

python3 -m ain fetch     # 获取并排序
python3 -m ain serve     # 打开 http://127.0.0.1:8848
```

**安装就这些。只需要 Python 3.11+，别的都不用。**

想点按钮？打开网页，点「获取最新」。

> **全新 clone 后归档是空的**，这是设计如此。`data/` 被 gitignore 了，所以第一次运行从零开始，
> 不是出错了。

## 功能详解

### 三个视图，回答三个问题

| 视图 | 回答的问题 | 地址 |
| --- | --- | --- |
| **全部内容**（默认） | "上周看到的那个东西在哪？" —— 全量历史，可搜索 | `/` |
| **今日精选** | "今天有什么值得看的？" —— 上次运行策展的那批 | `/` → 切换 |
| **知识专题** | "这个领域到底是怎么串起来的？" —— 按主题聚合 | `/knowledge` |

### 概念卡片（需要 LLM）

不开 LLM 时，你拿到标题、规则摘要、关键词归并的主题——够用，但只停留在"发生了什么"。
配置之后，每条内容会多出这样的卡片：

> **模式坍缩（mode dropping）** —— RLHF 训练让模型偏向安全、常见的回答，丢弃概率分布的长尾，
> 导致它自称的置信度不再反映真实的不确定性。
> **工程上**：别把流畅自信的措辞当成置信信号；用显式分数 + 阈值在
> 「自动执行 / 人工复核 / 拒绝」之间分流。

这种提炼用正则做不到。**这是整个项目里唯一真正需要模型的部分。**

## 工作原理

```
 10 个信源 ──► 归一化 ──► 去重 ──► 打分 ──► 筛选 ──► 正文 ──► 概念 ──► 归档
   适配器      Item      标题+URL   规则    top-N    四层降级   (LLM)    JSONL
                          指纹       +衰减   +配额              可选
```

**打分公式**（全部来自配置，不涉及任何模型）：

```
相关性 = Σ(关键词权重 × 标题命中则 1.6 否则 1.0) + 分类加成
         ×1.25 若命中 ≥5 个不同关键词          (广度加成)
新鲜度 = 0.5 ^ (已发布小时数 / 半衰期小时数)
分数   = 相关性 × 新鲜度 + 信源加成 + 互动加成
```

一个真实的完整拆解：

```
条目："GPT-6.1 Sol" [新智元]

  strong  openai   3.0 × 1.0 (仅正文命中)   +3.00
  strong  gpt      3.0 × 1.6 (标题命中)     +4.80
  strong  chatgpt  3.0 × 1.0                +3.00
  strong  codex    3.0 × 1.0                +3.00
  medium  api      1.5 × 1.0                +1.50
                                  相关性 = 15.30
  分类加成 (cn)                             +1.50  → 16.80
  广度加成 (5 个不同关键词)                  ×1.25  → 21.00
  时效: 已发布 16.2h，半衰期 60h             ×0.829 → 17.41
  信源权重 (1.2−1.0)×1.5                    +0.30
                                            ───────
                                     分数 = 17.71
```

因为排序是纯算术，所以**可复现、可调试**。你看到的内容里没有任何非确定性成分。

## 安装

不需要安装。`ain` 只用标准库：

```bash
git clone https://github.com/<you>/ain.git && cd ain
python3 -m ain doctor    # 环境自检
```

需要 Python **3.11+**（因为用了 `tomllib`）。如果还想要 `ain` 这个命令行入口：

```bash
pip install -e .    # 可选，提供 ain 命令
```

## 使用方法

| 命令 | 作用 |
| --- | --- |
| `python3 -m ain fetch` | 获取、排序、取正文、记录精选 |
| `python3 -m ain fetch --llm` | 同上，并让 LLM 提炼概念（需要 key） |
| `python3 -m ain serve` | 启动网页界面 |
| `python3 -m ain sources` | 检查各信源连通性 |
| `python3 -m ain query "rag"` | 搜索归档 |
| `python3 -m ain usage` | 查看 LLM token 消耗与费用估算 |
| `python3 -m ain enrich` | 给归档里的旧条目补概念卡片 |
| `python3 -m ain doctor` | 环境自检 |
| `python3 -m ain show` | 打印最近一期 Markdown 日报（需先导出） |

常用参数：

```bash
python3 -m ain fetch -n 50                    # 最多保留 50 条
python3 -m ain fetch --sources arxiv-cs-ai    # 调试单个信源（不会替换精选）
python3 -m ain fetch --dry-run                # 只预览，不写文件
python3 -m ain fetch --no-content             # 跳过正文获取（更快）
python3 -m ain fetch --llm                    # 启用概念提炼
python3 -m ain fetch --markdown               # 额外导出 Markdown 日报
```

## 配置

两个文件，不用改代码。都是带注释的 TOML。

### `config/interests.toml` —— 什么内容排前面

| 键 | 含义 |
| --- | --- |
| `strong` | 高价值关键词（大幅加分） |
| `medium` | 相关关键词（中等加分） |
| `negative` | 需要扣分的噪声（招聘、广告、播客预告） |
| `cn_strong` / `cn_medium` | **中文关键词，必须单独配** |

> **为什么中文要单独一组**：英文关键词匹配不到中文标题。"大模型推理加速"不含任何英文词，
> 只用英文词表它的得分是 `0`，会被相关性门槛丢掉——你加的中文信源等于白加。
> 中文没有空格分词，所以这些词按**子串**匹配，不是整词匹配。别放太短的词
> （`模型` 会命中几乎所有内容）。

```toml
[scoring]
half_life_hours = 60.0   # 时效半衰期；调大 = 更不看重"新"
top_n = 30               # 每次精选最多几条
per_source_cap = 12      # 单个信源最多占几条，防止一家刷屏
min_score = 1.5          # 进入精选的最低分
strong_weight = 3.0
medium_weight = 1.5
negative_weight = -4.0
max_age_days = 21.0
```

### `config/sources.toml` —— 内容从哪来

```toml
[[source]]
id = "arxiv-cs-ai"       # 稳定标识
type = "arxiv"           # 适配器
name = "arXiv cs.AI"     # 显示名
category = "paper"       # paper|vendor|cn|release|community|news|other
weight = 1.3             # 越高越容易浮现
enabled = true
limit = 80
```

可用的 `type`：`rss`（别名 `feed`、`atom`）、`arxiv`、`hackernews`（别名 `hn`）、
`html_list`（没有 feed 的站点）、`hf_models`、`hf_blog`、`reddit`。

**`keep_all` 标志** —— 策展型信源（OpenAI/Anthropic/DeepMind 官方博客、中文媒体）发布少且必然相关。
标上 `keep_all = true` 会同时跳过关键词门槛和分数阈值。不加会出真事故：
*"Gemini 4 Argon 发布"* 曾因为标题里恰好没有词表里的关键词而被静默丢弃。
**不要**给大水漫灌型信源（HN、arXiv）开这个。

### `config/settings.toml` —— 输出开关

```toml
[output]
write_markdown = false   # Markdown 导出默认关闭；网页是主入口
```

### 启用 LLM 阶段（可选）

把 key 放在仓库根目录的 `.env`（已被 gitignore）。从 `.env.example` 复制起步：

```bash
cp .env.example .env
```

```bash
# 任何 OpenAI 兼容端点都可以
AIN_LLM_API_KEY=sk-...
AIN_LLM_BASE_URL=https://api.deepseek.com/v1
AIN_LLM_MODEL=deepseek-chat
```

> **优先级：真实环境变量覆盖 `.env`**。所以临时覆盖可以：
> `AIN_LLM_MODEL=xxx python3 -m ain fetch --llm`。

兼容 OpenAI、DeepSeek、Moonshot、通义，或本地 vLLM/Ollama。两个坑已经处理掉了：

- **只支持流式的后端**（例如腾讯 copilot 网关）—— `ain` 会自动改用 `stream: true` 并重组 SSE 分片。
- **JSON 被包在 ` ```json ` 里** —— 解析器会剥掉代码围栏和周围的解释文字。

不配 key 时，`--llm` 会自动降级到规则摘要，获取流程永不失败。

## 费用

**已有概念卡片的条目不会重复送模型**（按内容 id 匹配），所以只为真正的新条目付费。

在 253 条归档上实测：

| 操作 | 花费 |
| --- | --- |
| `fetch --llm`，30 条（仅 2 条是新的） | 1 次调用，723 输入 / 216 输出 ≈ **$0.0002** |
| `fetch --llm`，30 条（8 条是新的） | 2 次调用，2,724 输入 / 1,958 输出 ≈ **$0.0016** |
| `enrich` 全量补齐 217 条（一次性） | 37 次调用，35k 输入 / 55k 输出 ≈ **$0.04** |

日常使用大致是**每月几块钱**。一次性补齐占了大头。

```bash
python3 -m ain usage            # 汇总
python3 -m ain usage -v         # 按天明细
python3 -m ain usage --price-in 0.3 --price-out 1.2   # 换了供应商/价格
```

> 默认按 DeepSeek 低谷价估算。**这是估算，不是账单。** 很多网关没有余额接口
> （实测 `/credits`、`/balance`、`/usage` 全部 404），所以 `ain` 在 `data/usage.jsonl`
> 本地记账。**同一个 key 在别处用的量不计入。**

## 定时运行

**macOS（launchd）** —— 用生成脚本，它会按当前 checkout 写绝对路径：

```bash
sh scripts/install-launchd.sh                   # 每天 8:30 和 20:30
sh scripts/install-launchd.sh --hours "9" --minute 0
sh scripts/install-launchd.sh --uninstall
```

**cron：**

```bash
0 9 * * * /bin/sh /path/to/ain/scripts/daily.sh
```

`daily.sh` 会从脚本自身位置推导项目根目录，所以移动目录或换个地方 clone 都不用改。

**GitHub Actions** —— 已附带 `.github/workflows/daily.yml`。如果所在网络访问不了
`huggingface.co` 或 `reddit.com`，这个方式特别有用：GitHub 的 runner 能连上。
把 `AIN_LLM_API_KEY` 加为仓库 secret（可选，不设则纯规则、零成本），
并把想要的信源改成 `enabled = true`。

## 添加信源

写一个适配器并注册。标准 feed 完全不用写代码：

```toml
[[source]]
id = "my-blog"
type = "rss"
name = "My Blog"
url = "https://example.com/feed.xml"
category = "vendor"
weight = 1.2
```

自定义适配器就继承 `Source`，然后在 `ain/sources/__init__.py:REGISTRY` 加一行。

## 项目结构

```
ain/
  cli.py              命令行入口
  pipeline.py         获取 → 去重 → 打分 → 正文 → 概念
  web.py              网页服务（标准库 http.server）+ JSON API
  web/index.html      全部内容 / 今日精选 视图
  web/knowledge.html  知识专题视图
  scorer.py           规则打分（确定性）
  content.py          正文提取（JSON-LD → 容器 → <p> → meta）
  enrich.py           正文并发获取 + 归档复用
  summarize.py        规则摘要 + LLM 概念提取
  env.py              .env 加载（stdlib；环境变量优先）
  report.py           Markdown 导出（默认关闭）
  store.py            JSONL 归档 + 跨进程锁 + 搜索 + token 账本
  config.py           配置加载
  http.py             带重试与 gzip 的 HTTP
  html.py             HTML → 文本、截断式摘要
  models.py           Item 数据模型
  sources/            各信源适配器
config/
  sources.toml        信源清单          ← 常改
  interests.toml      兴趣画像          ← 常改
  settings.toml       输出开关
scripts/
  daily.sh            定时任务入口
  install-launchd.sh  按当前目录生成 launchd 任务
.github/workflows/
  daily.yml           GitHub Actions 定时任务
data/items.jsonl      含正文与概念卡片的归档（自动生成）
data/runs.jsonl       每次运行的记录，含 selected_ids（精选的事实来源）
data/usage.jsonl      LLM token 账本（自动生成）
```

## 设计取舍

1. **零依赖。** 在目标网络上实测 PyPI 往返要 25 秒后才这么定的。代价是自己维护 RSS 解析器——
   它同时处理 RSS 2.0、Atom、RSS 1.0 和常见命名空间扩展。
2. **规则排序，LLM 解释。** 排序必须可复现、可审计；文案不需要。
3. **LLM 不在关键路径上。** 没 key、调用失败、超时——全部降级到规则摘要。获取流程永不会因为
   模型不可用而中断。
4. **只给入选条目取正文。** 全量取正文意味着每次 250+ 请求；只取前约 40 条能让一次运行保持在分钟级。
5. **归档复用。** 正文和概念卡片按内容 id 索引，重复运行既不重新下载也不重复计费。
6. **失败隔离。** 一个信源挂掉只影响它自己。只有*全部*信源失败时退出码才非零。
7. **跨进程锁。** 定时任务和手动运行不能交错写入 `items.jsonl`。进程异常退出后锁会自动回收。
8. **归档保留全部，精选只展示前 N 条。** 没进今天精选的内容，之后仍然搜得到。

## 已知限制

- **JS 渲染的页面取不到正文。** 新智元这类站点只暴露 `og:description`（约 70–110 字符）。
  要解决得上无头浏览器，与零依赖冲突。
- **提取是启发式的。** 站点改版可能让某个源退化成 meta 摘要。降级是优雅的，不会崩。
- **打分用的是 feed 摘要而非正文**（正文在打分之后才取）。只出现在正文里的关键词不参与相关性判断——
  这是"只取前 N 条"的直接后果。
- **arXiv 用摘要，不抓 PDF。** 判断相关性足够；抓 PDF 需要额外依赖。
- **概念质量取决于模型。** 便宜的小模型可能提炼得浅。提示词在 `ain/summarize.py:SYSTEM_PROMPT`。
- **`POST /api/fetch` 没有鉴权。** 默认绑定 `127.0.0.1`，本地使用是安全的。
  **暴露到公网前必须加鉴权**——否则任何人都能反复触发运行，而一旦配了 LLM key，
  那就是在花你的钱。

## 排查问题

```bash
python3 -m ain doctor        # 环境自检
python3 -m ain sources       # 哪些信源在失败
tail -50 logs/fetch.log      # 定时任务日志
```

| 现象 | 处理 |
| --- | --- |
| 精选条目太少 | 调低 `config/interests.toml` 的 `min_score`，或调大 `top_n` |
| 关心的主题从不出现 | 把关键词加进 `keywords.strong` |
| 某个信源一直失败 | 在 `config/sources.toml` 里给它设 `enabled = false` |
| 提示「另一个 ain 进程正在运行」 | 确实在跑；如果没有，删掉 `data/.lock` |
| 内容全是英文 | 配置 LLM，它也会给英文条目写中文摘要 |

## 参与贡献

欢迎提 issue 和 PR。最有价值的贡献是**新的信源适配器**和**关键词表的改进**。
如果你加了信源，请在 PR 里说明它在中国大陆网络下是否可用。

本项目刻意保持零依赖。引入第三方运行时依赖的 PR 一般会被拒绝，除非有充分理由。

## 许可

[MIT](LICENSE)
