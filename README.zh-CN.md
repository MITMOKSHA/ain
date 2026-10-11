<div align="center">

# ain

**个人 Agent（智能体）前沿追踪 agent —— 获取、排序、摘要，把新闻变成真正能用的 Agent 工程知识。**

从 14 个信源获取内容 → 过一道 Agent 硬门槛 → 按你的兴趣打分排序 → 取回原文正文
→ 可选地用 LLM 提炼可迁移的 Agent 工程概念 → 在本地网页里阅读。

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](#设计取舍)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md) · [快速开始](#快速开始) · [功能](#功能) · [工作原理](#工作原理) · [配置](#配置)

</div>

---

## 为什么做这个

跟踪 Agent 前沿意味着阅读一条洪流。通常有两件事会出问题：

1. **被淹没**。每天几百篇论文和帖子，没时间筛选。
2. **学了等于没学**。即使读了，拿到的是*事件*（"某公司发布了新的编码 Agent"），
   而不是*可迁移的知识*（"为什么把工具返回值裁剪后再回灌，比加大上下文窗口更有效"）。

`ain` 同时针对这两点。**规则打分**负责筛选——确定性、零成本、可解释（每条都列出命中了哪些关键词）。
**可选的 LLM 阶段**负责规则做不到的事：提炼值得记住的工程概念。

这个仓库不追整个 AI，只追 **Agent（智能体）** 这一条线：工具调用、上下文工程、记忆、
编排框架、编码 Agent、计算机操作、沙箱与权限、Agent 评测、多智能体协作。
所以 `ain` 比"一个 AI 资讯器"多做了一件事：**先判定一条内容到底是不是 Agent 内容**，
再谈排序。这个判定是关键词硬门槛，不看分数高低——因为它回答的是"收不收录"，不是"排第几"。
详见下面「配置」一节的 `[domain]` 段。

> **设计原则：LLM 从不决定"你看到什么"，只决定"怎么解释"。**
> 排序必须可复现——同一批数据，今天和明天必须排出同样的顺序。
> Agent 领域门槛进一步强化了这一点：**进不进门也由确定性的关键词规则决定，模型无权放行。**

## 功能

- **开箱 14 个信源** —— arXiv（用 query 在摘要字段定向筛选 Agent 论文）、
  OpenAI、DeepMind、Google AI、Anthropic News、Anthropic Engineering、
  LangChain Blog、Simon Willison、Latent.Space、Hacker News（filter_keywords 已收窄为 Agent 术语），
  以及四个中文源（量子位 / 新智元 / InfoQ 中文 / Solidot）。
- **Agent 硬门槛** —— 只看标题（加 tags），不看摘要。不是 Agent 的内容既进不了日报，
  也根本不会写进归档。
- **原文正文** —— 多数 feed 只给一句话摘要（InfoQ 实际发的是 `点击查看原文>`）。
  `ain` 会跟进链接，用四层降级策略把正文取回来。
- **透明的打分** —— 关键词权重 × 时效衰减 + 信源权重 + 互动量。每一分都能解释，没有黑盒。
- **概念卡片（可选）** —— 每篇一个 `{"name", "what", "how"}`：这是什么、解决什么问题、工程上怎么用。
- **知识专题** —— 按 Agent 子领域（工具调用与 MCP、上下文工程、编码 Agent……）跨天、跨信源聚合，
  而不是只按日期排列。
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
| **知识专题** | "Agent 这条线到底是怎么串起来的？" —— 按 Agent 子领域聚合 | `/knowledge` |

网页层（归档列表、今日精选、知识专题、统计）都套用了和门槛一致的领域过滤，
所以即使还没跑 `prune`，归档里的旧越界条目也不会显示出来。

### 知识专题：Agent 子领域，而不是"通用 AI 主题"

专题名现在是一组规范化的 Agent 子领域：**工具调用与 MCP**、**上下文工程**、**记忆与状态**、
**规划与任务分解**、**Agent 编排与框架**、**编码 Agent**、**计算机操作 Agent**、
**多智能体协作**、**沙箱与执行环境**、**Agent 安全**、**Agent 评测**、**Agent 技能与运行时**。

模型偶尔会自造近义名（"评测基准" vs "Agent 评测"），这会把一个知识串拆成两个。
`ain/web.py` 里因此加了两道守卫：`_CATCH_ALL_TOPICS` 丢弃「AI Agent」「Agent」「智能体」
这类没有信息量的兜底名，`_CANONICAL_BY_SYNONYM` 把已知的近义名归并到上面的规范名。
两道守卫都只做**归一化**，不改变内容的收录结果。

### 概念卡片（需要 LLM）

不开 LLM 时，你拿到标题、规则摘要、关键词归并的主题——够用，但只停留在"发生了什么"。
配置之后，每条内容会多出这样的卡片：

> **上下文压缩（context compaction）** —— 长任务里工具返回会迅速吃满上下文窗口，
> 于是把历史轨迹压成结构化摘要、只保留结论和未决事项，而不是原样重放。
> **工程上**：压缩点的选择比压缩算法更关键——在"任务阶段切换"处压最省，
> 压在工具调用中途会丢掉正在进行的推理链。

这种提炼用正则做不到。**这是整个项目里唯一真正需要模型的部分。**

## 工作原理

```
 14 个信源 ──► 归一化 ──► 去重 ──► 领域门槛 ──► 打分 ──► 筛选 ──► 正文 ──► 概念 ──► 归档
   适配器      Item      标题+URL   标题命中    规则    top-N    四层降级   (LLM)    JSONL
                          指纹      Agent 词    +衰减   +配额              可选
                                    (硬性，不通过即丢弃，不写归档)
```

**领域门槛**（确定性的，且是"收录与否"而不是"排序高低"）：标题（加 tags）命中
`config/interests.toml` 的 `[domain].keywords` 里任一关键词才继续往下走。没通过的内容被直接丢弃——
**既不进日报，也不会写进 `data/items.jsonl`**。这是刻意的：归档是搜索、知识专题和后续运行的输入，
把越界内容写进去等于慢慢重建这个项目要排除的"全 AI"噪声。每次运行会把被门槛挡掉的数量记进
`data/runs.jsonl` 的 `out_of_domain` 字段，这样"日报变薄"和"信源挂了"可以一眼区分。
`domain_exempt = true` 的信源跳过这一关（见下文）。

**打分公式**（全部来自配置，不涉及任何模型）：

```
相关性 = Σ(关键词权重 × 标题命中则 1.6 否则 1.0) + 分类加成
         ×1.25 若命中 ≥5 个不同关键词          (广度加成)
新鲜度 = 0.5 ^ (已发布小时数 / 半衰期小时数)
分数   = 相关性 × 新鲜度 + 信源加成 + 互动加成
```

`[domain].keywords` 会自动并入 `strong` 词表参与打分，所以领域词不需要在
`[domain]` 和 `keywords.strong` 两处重复维护。

一个条目的完整拆解（这里只展示打分算术；领域门槛在更早一步就完成了"收录与否"的判断，
不参与下面任何一个数）：

```
条目："MCP 工具调用与沙箱权限设计" [新智元]
摘要："Anthropic 复盘 Claude Code 这类编码 Agent 的上下文工程。"

  strong     mcp          3.0 × 1.6 (标题命中)   +4.80
  strong     工具调用      3.0 × 1.6 (标题命中)   +4.80
  strong     沙箱          3.0 × 1.6 (标题命中)   +4.80
  strong     agent        3.0 × 1.0 (仅摘要命中) +3.00
  strong     claude code  3.0 × 1.0             +3.00
  strong     上下文工程     3.0 × 1.0             +3.00
  cn_strong  工具调用      3.0 × 1.6 (标题命中)   +4.80
  cn_strong  沙箱          3.0 × 1.6 (标题命中)   +4.80
  cn_strong  上下文工程     3.0 × 1.0             +3.00
  medium     anthropic    1.5 × 1.0             +1.50
  medium     claude       1.5 × 1.0             +1.50
  cn_medium  上下文        1.5 × 1.0             +1.50
                                   相关性 = 40.50
  分类加成 (cn)                              +1.50  → 42.00
  广度加成 (9 个不同关键词)                   ×1.25  → 52.50
  时效: 已发布 16.2h，半衰期 60h              ×0.829 → 43.54
  信源权重 (1.2−1.0)×1.5                     +0.30
                                              ───────
                                       分数 = 43.84
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
| `python3 -m ain prune` | 清理归档里不再通过 Agent 领域门槛的旧条目 |
| `python3 -m ain usage` | 查看 LLM token 消耗与费用估算 |
| `python3 -m ain enrich` | 给归档里的旧条目补概念卡片 |
| `python3 -m ain doctor` | 环境自检 |
| `python3 -m ain show` | 打印最近一期 Markdown 日报（需先导出） |

常用参数：

```bash
python3 -m ain fetch -n 50                    # 最多保留 50 条
python3 -m ain fetch --sources arxiv-agents   # 调试单个信源（不会替换精选）
python3 -m ain fetch --dry-run                # 只预览，不写文件
python3 -m ain fetch --no-content             # 跳过正文获取（更快）
python3 -m ain fetch --llm                    # 启用概念提炼
python3 -m ain fetch --markdown               # 额外导出 Markdown 日报
python3 -m ain prune --dry-run                # 只列出会被清理的越界条目
```

## 配置

两个文件，不用改代码。都是带注释的 TOML。

### `config/interests.toml` —— 什么内容排前面，什么内容进得来

| 键 | 含义 |
| --- | --- |
| `strong` | 高价值关键词（大幅加分） |
| `medium` | 相关关键词（中等加分） |
| `negative` | 需要扣分的噪声（招聘、广告、播客预告） |
| `cn_strong` / `cn_medium` | **中文关键词，必须单独配** |
| `[domain]` | **Agent 硬门槛**：`require` 开关 + `keywords` 词表，不命中即不收录 |

> **为什么中文要单独一组**：英文关键词匹配不到中文标题。"大模型推理加速"不含任何英文词，
> 只用英文词表它的得分是 `0`，会被相关性门槛丢掉——你加的中文信源等于白加。
> 中文没有空格分词，所以这些词按**子串**匹配，不是整词匹配。别放太短的词
> （`模型` 会命中几乎所有内容）。

#### `[domain]` —— 领域硬门槛（只决定"收不收录"）

```toml
[domain]
require = true            # 关掉就退回"什么 AI 内容都收"
keywords = [
  "agent", "agentic", "tool use", "tool calling", "function calling",
  "mcp", "model context protocol", "coding agent", "computer use",
  "context engineering", "agent memory", "sandboxing", "prompt injection",
  "agent evaluation", "swe-bench", "langchain", "langgraph", ...
  "智能体", "工具调用", "上下文工程", "沙箱", "长期记忆", ...
]
```

这个门槛和 `strong`/`medium` 词表是两回事，值得说清：

- **只看标题（加 tags），刻意不看摘要。** 摘要是"顺带提了一嘴"的重灾区：一篇模型盘点文章
  的摘要里出现 "Codex" 不代表它是 Agent 内容，而真正的 Agent 故事几乎一定写在标题里。
  放宽到摘要会在实测中放进大量策展源的噪声。
- **它管的是"收录与否"，不是"排序高低"。** 没通过的内容会被直接丢弃：既进不了今日精选，
  **也不会写进 `data/items.jsonl`**。因为归档是搜索框、知识专题和后续运行的输入，
  把越界内容写进去等于悄悄重建这个项目要排除的"全 AI"噪声——即使当天的日报看起来是干净的。
- **它不会被分数盖过。** 信源权重、互动量、时效加成再高，也不能让一条非 Agent 内容越线。
  这是它存在的全部理由：一个阈值可以被加权"投票"推翻，一个门槛不能。
- **领域词会自动并入 `strong` 参与打分**，所以在 `[domain]` 和 `keywords.strong` 里
  不需要重复维护同一批词。
- **一个如实的边界：词表里有 `codex`、`claude code`、`mcp` 这类本身就是 Agent 产品名的词。**
  所以「Oracle 用 Codex 省了多少时间」这样的厂商案例文会通过门槛（已实测）。
  标题里带 Agent 产品名是门槛能拿到的最强信号，代价就是偶尔混进这类案例文；
  想要更干净就把 `codex` 从 `[domain].keywords` 里拿掉，代价是漏掉真正的 Codex Agent 更新。
- **门槛挡掉多少条会记在 `data/runs.jsonl` 的 `out_of_domain` 字段**，方便区分
  "日报变薄"和"信源挂了"。

打分用的仍然是 feed 摘要，门槛看的是标题——两者读的字段不同，这是刻意的。

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
id = "arxiv-agents"        # 稳定标识
type = "arxiv"             # 适配器
name = "arXiv · Agent 方向" # 显示名
category = "paper"         # paper|vendor|cn|release|community|news|other
weight = 1.6               # 越高越容易浮现
enabled = true
limit = 60
```

启用的 14 个信源（全部 Agent 定向）：

| 信源 | 类型 | 备注 |
| --- | --- | --- |
| `arxiv-agents` | arxiv | `query` 在摘要字段定向筛选，`domain_exempt = true` |
| `openai-news` | rss | `keep_all` |
| `deepmind-blog` | rss | `keep_all` |
| `google-ai-blog` | rss | `keep_all` |
| `anthropic-news` | html_list | `keep_all`，无 feed，解析 `/news` |
| `anthropic-engineering` | html_list | **新增**，抓 `/engineering`——Anthropic 的 Agent 工程博客 |
| `langchain-blog` | rss | **新增**，`keep_all` + `domain_exempt` |
| `simon-willison` | rss | **新增**，不豁免门槛 |
| `latent-space` | rss | **新增**，不豁免门槛 |
| `hn-ai` | hackernews | `filter_keywords` 已收窄为 Agent 术语 |
| `qbitai` | rss | 中文，`keep_all` |
| `aiera` | rss | 中文，`keep_all` |
| `infoq-cn` | rss | 中文 |
| `solidot` | rss | 中文 |

**两个信源因中国大陆网络不可达而保持禁用**：`hf-models`（huggingface.co）和
`reddit-localllama`（reddit.com）。需要代理才能启用。

好消息是 GitHub Actions 的 runner 连得上它们。如果想收这两个源，把 `enabled` 改成 `true` 即可，
参见下面的「定时运行」。

可用的 `type`：`rss`（别名 `feed`、`atom`）、`arxiv`、`hackernews`（别名 `hn`）、
`html_list`（没有 feed 的站点）、`hf_models`、`hf_blog`、`reddit`。

**`keep_all` 标志** —— 策展型信源（OpenAI/Anthropic/DeepMind 官方博客、中文媒体）发布少、
单看关键词分数容易偏低。标上 `keep_all = true` 会同时跳过**关键词门槛和最低分阈值**。
不加会出真事故：*"Gemini 4 Argon 发布"* 曾因为标题里恰好没有词表里的关键词而被静默丢弃。
**不要**给大水漫灌型信源（HN、arXiv）开这个。

**`domain_exempt` 标志（新增）** —— 跳过 **Agent 领域硬门槛**。它和 `keep_all` 是
**刻意分开的两个开关**，因为两者主张的不是一回事：

| 开关 | 跳过的关卡 | 适用信源 |
| --- | --- | --- |
| `keep_all = true` | 关键词门槛 + `min_score` 阈值 | 策展型大厂博客、中文媒体：发布少，标题不一定带词表关键词 |
| `domain_exempt = true` | Agent 领域硬门槛 | **整站都在讲 Agent 工程**的信源 |
| 两个都开 | 以上全部 | 例如 LangChain Blog |

关键点：**`keep_all` 不再豁免领域门槛。** 旧版 README 说"官方博客必然相关所以全放行"，
这个说法已经不准了——"这个源值得信"不等于"它发的每一条都是 Agent 内容"。
OpenAI/DeepMind/Google 的博客会发模型能力、安全政策、公司动态，这些不是 Agent 资讯，
现在会被门槛挡掉。只有整站都在讲 Agent 工程的信源才设 `domain_exempt`，
目前是 `langchain-blog`（以及用 query 在摘要字段做定向筛选的 `arxiv-agents`）。

`arxiv-agents` 豁免是有意为之：它的 `query` 已经在**摘要**上筛过 Agent 了，比事后用标题
再筛一遍更准；不加这一条，标题里没写 "agent" 的真 Agent 论文会被自己的门槛误杀。

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

概念提炼的系统提示词已改写为 **Agent 专用**：禁止用「AI Agent」「Agent」这类兜底主题名，
要求给出具体的 Agent 子领域主题，并且只提炼可迁移的 Agent 工程概念（"上下文压缩"是好概念，
"某公司发布了新 Agent"不是）。

## 费用

**已有概念卡片的条目不会重复送模型**（按内容 id 匹配），所以只为真正的新条目付费。

以下数字来自收窄到 Agent 之前的一次实测，用于说明**量级**（Agent 定向后单次运行的
候选条目更少，实际只会更省）：

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

注意：新信源的条目同样要过 Agent 领域门槛。信源本身专注 Agent 工程才考虑加
`domain_exempt = true`；官方大厂博客**不要**加，否则又是一次"什么都收"。

## 项目结构

```
ain/
  cli.py              命令行入口（含 prune 清理命令）
  pipeline.py         获取 → 去重 → 领域门槛 → 打分 → 正文 → 概念
  web.py              网页服务（标准库 http.server）+ JSON API
                      （归档列表/精选/专题/统计套用同一套领域过滤）
  web/index.html      全部内容 / 今日精选 视图（标题：「Agent 前沿」）
  web/knowledge.html  知识专题视图
  scorer.py           规则打分（确定性）+ in_domain 领域硬门槛
  content.py          正文提取（JSON-LD → 容器 → <p> → meta）
  enrich.py           正文并发获取 + 归档复用
  summarize.py        规则摘要 + LLM 概念提取（Agent 专用提示词）
  env.py              .env 加载（stdlib；环境变量优先）
  report.py           Markdown 导出（默认关闭）
  store.py            JSONL 归档 + 跨进程锁 + 搜索 + token 账本 + prune
  config.py           配置加载（domain 词并入 strong）
  defaults.py         sources.toml 缺失时的兜底信源表（Agent 定向）
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
data/items.jsonl      含正文与概念卡片的归档（只写通过领域门槛的条目）
data/runs.jsonl       每次运行的记录，含 selected_ids 与 out_of_domain（精选的事实来源）
data/usage.jsonl      LLM token 账本（自动生成）
```

## 设计取舍

1. **零依赖。** 在目标网络上实测 PyPI 往返要 25 秒后才这么定的。代价是自己维护 RSS 解析器——
   它同时处理 RSS 2.0、Atom、RSS 1.0 和常见命名空间扩展。
2. **规则排序，LLM 解释。** 排序必须可复现、可审计；文案不需要。
3. **领域门槛也是规则，不是模型判断。** 标题命中关键词才收录——门槛不参与打分，也不可被
   分数、信源权重或互动量推翻。让 LLM 来决定"这条算不算 Agent"会把这个项目最需要确定性的
   一环交给最不确定的组件。
4. **LLM 不在关键路径上。** 没 key、调用失败、超时——全部降级到规则摘要。获取流程永不会因为
   模型不可用而中断。
5. **只给入选条目取正文。** 全量取正文意味着每次 250+ 请求；只取前约 40 条能让一次运行保持在分钟级。
6. **归档复用。** 正文和概念卡片按内容 id 索引，重复运行既不重新下载也不重复计费。
7. **失败隔离。** 一个信源挂掉只影响它自己。只有*全部*信源失败时退出码才非零。
8. **跨进程锁。** 定时任务和手动运行不能交错写入 `items.jsonl`。进程异常退出后锁会自动回收。
9. **归档保留全部，精选只展示前 N 条。** 没进今天精选的内容，之后仍然搜得到。
   （但没通过领域门槛的内容不属于"归档"，见上。）

## 已知限制

- **领域门槛只看标题。** 一条真正关于 Agent、但标题刻意不含任何 Agent 词的内容会被挡掉。
  这是为了挡住摘要里的"顺带一提"而付出的代价。可在 `[domain].keywords` 里补词缓解。
- **JS 渲染的页面取不到正文。** 新智元这类站点只暴露 `og:description`（约 70–110 字符）。
  要解决得上无头浏览器，与零依赖冲突。
- **提取是启发式的。** 站点改版可能让某个源退化成 meta 摘要。降级是优雅的，不会崩。
- **打分用的是 feed 摘要而非正文**（正文在打分之后才取）。只出现在正文里的关键词不参与相关性判断——
  这是"只取前 N 条"的直接后果。领域门槛读的则是标题，两者字段不同，这是刻意的。
- **arXiv 用摘要，不抓 PDF。** 判断相关性足够；抓 PDF 需要额外依赖。
- **概念质量取决于模型。** 便宜的小模型可能提炼得浅。提示词在 `ain/summarize.py:SYSTEM_PROMPT`
  （已改写为 Agent 专用：禁止"AI Agent"这类兜底主题名，要求给出具体的 Agent 子领域）。
- **`POST /api/fetch` 没有鉴权。** 默认绑定 `127.0.0.1`，本地使用是安全的。
  **暴露到公网前必须加鉴权**——否则任何人都能反复触发运行，而一旦配了 LLM key，
  那就是在花你的钱。

## 排查问题

```bash
python3 -m ain doctor        # 环境自检
python3 -m ain sources       # 哪些信源在失败
python3 -m ain prune --dry-run   # 归档里有多少越界条目
tail -50 logs/fetch.log      # 定时任务日志
```

| 现象 | 处理 |
| --- | --- |
| 精选条目太少 | **先看 `data/runs.jsonl` 最新一条的 `out_of_domain`**：数值大说明是领域门槛挡多了，放宽 `config/interests.toml` 的 `[domain].keywords`（例如补上你关心的 Agent 子领域说法）；数值小才是 `min_score` 或 `top_n` 的问题 |
| 归档里还有一堆旧的非 Agent 内容 | 跑 `python3 -m ain prune`（先 `--dry-run` 预览）。门槛只管新写入，旧条目要显式清理 |
| 关心的主题从不出现 | 把关键词加进 `keywords.strong`，或加进 `[domain].keywords`（后者同时起门槛和打分作用） |
| 某个信源一直失败 | 在 `config/sources.toml` 里给它设 `enabled = false` |
| 提示「另一个 ain 进程正在运行」 | 确实在跑；如果没有，删掉 `data/.lock` |
| 内容全是英文 | 配置 LLM，它也会给英文条目写中文摘要 |

## 参与贡献

欢迎提 issue 和 PR。最有价值的贡献是**新的信源适配器**和**关键词表的改进**——
尤其是 `config/interests.toml` 里 `[domain].keywords` 还没覆盖到的 Agent 子领域说法。
如果你加了信源，请在 PR 里说明它在中国大陆网络下是否可用，以及是否属于"整站都在讲 Agent"
（只有这种才考虑 `domain_exempt = true`）。

本项目刻意保持零依赖。引入第三方运行时依赖的 PR 一般会被拒绝，除非有充分理由。

## 许可

[MIT](LICENSE)
