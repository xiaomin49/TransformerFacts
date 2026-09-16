# TransformerFacts · TF数据官

> AI 产业先行指标监测 + 投研支持框架 —— 用一线研发视角和量化数据，追踪 Transformer / 大模型技术从研发、生态、商业落地到社会渗透的全链路演进。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Data: Supabase](https://img.shields.io/badge/Data-Supabase-3ECF8E.svg)](https://supabase.com)
[![Stack: Node + Python](https://img.shields.io/badge/Stack-Node%20%2B%20Python-3178C6.svg)]()

**TransformerFacts（简称 TF数据官）** 是一套聚焦 AI 产业真实落地节奏的先行指标监测与深度研究体系。它不预测股价，而是用**可量化、可回溯、可对比**的先行指标，识别 AI 产业的周期拐点、供需结构变化、算力通胀风险与就业结构变迁，为产业研究、投资决策与技术落地提供客观、前置、可落地的数据支撑。

---

## 📑 目录

- [一、AI 产业先行指标监测](#一ai-产业先行指标监测)
  - [1.1 数据指标全景](#11-数据指标全景)
  - [1.2 周报 Agent（每周自动生成）](#12-周报-agent每周自动生成)
  - [1.3 ROIC 模型与测算](#13-roic-模型与测算)
- [二、EAPI 指数](#二eapi-指数)
- [三、投研支持框架体系](#三投研支持框架体系)
  - [3.1 WorkBuddy + karpathy-claude-wiki 本地知识库](#31-workbuddy--karpathy-claude-wiki-本地知识库)
  - [3.2 数据脚本（定时 / 非定时）](#32-数据脚本定时--非定时)
  - [3.3 基于 hermes + 飞书的及时通知](#33-基于-hermes--飞书的及时通知)
  - [3.4 开源 Skill](#34-开源-skill)
- [关于我们](#关于我们)
- [技术栈](#技术栈)
- [⚠️ Disclaimer](#-disclaimer)

---

## 一、AI 产业先行指标监测

监测体系围绕四大核心维度展开：**开发者生态活跃度（GitHub / HuggingFace）**、**企业商业化渗透度（npm / PyPI）**、**算力供给侧（GPU 租赁 / Token 价格）**、**企业基本面（财报 / Transcript）**。所有原始数据经采集脚本入库 [Supabase](https://supabase.com)（PostgreSQL），再经指数计算脚本合成统一指标，最终通过前端站点与周报呈现。

### 1.1 数据指标全景

| 维度 | 指标示例 | 数据源 |
|------|----------|--------|
| **GitHub 社区** | 项目 Star / Fork 7 日增长、AI 项目增长排行榜 | GitHub REST API |
| **HuggingFace** | 模型下载量、Spaces 下载量及 7 日增速 | HuggingFace API |
| **npm 包** | AI SDK 包（OpenAI / Anthropic / Google 等）月 / 周下载量、企业工具包（dd-trace、snowflake-sdk 等） | npm registry |
| **PyPI 包** | 四大 AI SDK（google-genai / openai / anthropic / langchain）月下载 | PyPI Stats |
| **GPU 租赁价格** | H100 / H200 / B200 / A100 等数据中心 GPU 时租（"硅基通胀"） | Vast.ai 公开定价（GCS） |
| **Token 价格（第三方）** | 各模型 $/M token 价、量价加权指数 | OpenRouter、Vercel AI Gateway |
| **财报数据** | 资本开支（CapEx）、收入 YoY、营业 / 毛利率、Azure / M365 等分项 | SEC EDGAR（10-K / 10-Q / 8-K） |
| **Transcript** | 财报电话会纪要（结构化清洗文本） | roic.ai API（兜底 Tavily） |
| **新闻** | Token 降价、AI 行业资讯、裁员 / 招聘信号 | Google News RSS、Serper / Tavily |

### 1.2 周报 Agent（每周自动生成）

`batch/generate_ai_weekly_report.py` 是一个**自动化的 AI 生态周报生成 Agent**：每周（周二）从 Supabase 拉取最新数据，自动合成 HTML / Markdown 双格式报告，并 upsert 进 `research_reports` 表（同时落盘到 `public/reports/`）。

每期周报常驻以下板块：

| 板块 | 内容 |
|------|------|
| **AI 应用发展指数（EAPI）** | 企业 AI 渗透度综合指数及子指数环比 |
| **Agent 生产力工具追踪** | 8 大 Agent 框架周下载量对比 |
| **大模型 API SDK 月下载对比** | OpenAI / Anthropic / Google 等官方 SDK 走势 |
| **HuggingFace Top 10 模型** | 模型下载量与增速排行 |
| **Token 价格观察** | OTPI Vercel Token 价格指数（量价加权） |
| **硅基通胀** | GPU Aggregator（Vast.ai 等）时租走势 |
| **AI 项目增长排行榜** | GitHub 7 日 Star 增量 Top 20 |
| **常驻板块 · 开源生态焦点** | Agent Harness 双雄（如 OpenAI Codex Harness vs DeepSeek Harness）深度追踪 |

报告样例见：https://transformerfacts.substack.com/ （自 2026-06 起持续产出）

### 1.3 ROIC 模型与测算

`public/genai-roic.html` + `public/js/genai_roic/roic-model.js` 是一套 **GenAI 算力 ROIC 动态精算模型**，面向"建算力到底赚不赚钱"这一核心问题，把抽象的商业判断拆成可编辑、可试算的变量。

模型结构：
- **五层变量体系**：`资本层（CapEx / GPU 卡数 / 单价）` → `利用率层（GPU 利用率 / 训练-推理占比 / 单卡吞吐）` → `成本结构层（电价 / PUE / 折旧 / 运维）` → `定价层（GPU 时租 / Token 价 / 折扣）` → `利润层（收入 / EBIT / NOPAT / ROIC）`。
- **三条商业路径对比**：
  - **路径 A · GPU 租赁**（如 RunPod / CoreWeave 模式）
  - **路径 B · 自有模型 API**（按 Token 计费，推理为主）
  - **路径 C · 第三方算力 API**（CSP 转售，承担算力成本）
- **在线试算器**：变量全部可在前端编辑，保存即重算 `ROIC / EBIT Margin / NOPAT Margin`；变量从 Supabase `genai_roic_variables` 表加载，API 不可用时回退到内置硬编码基线值。

变量通过 `scripts/upload_genai_roic_variables.py` 上传维护，GPU 吞吐等基准参考 `batch/gpu_nvidia_benchmarks.json`（MLPerf 等）。

---

## 二、EAPI 指数

**EAPI（Enterprise AI Penetration Index，企业 AI 渗透度指数）** 是 TF数据官三大指数体系之一，追踪企业在实际业务中引入 AI 工具的渗透速度。它采用 **npm 六包体系**：

- **AI SDK 三包**（OpenAI / Anthropic / Google 官方 SDK）——模型调用层，权重 60%
- **企业工具三包**（dd-trace / snowflake-sdk / @atlaskit/rovo-triggers）——生产环境集成层，权重 40%

通过几何加权合成，捕捉企业从"试用模型"到"深度集成"的完整渗透路径。它与 **ADMI（开发者活跃度）**、**AADI（应用落地强度）** 共同构成 AI 应用生态三大指数。

> **编制原理、权重方案与公式细节** → 详见指数方法论专页：
> 🔗 **https://xiaomin49.github.io/TransformerFacts/ai-indices-methodology.html**

---

## 三、投研支持框架体系

TF数据官不止是"看板"，而是一套**实用、低成本、定位于数据与知识库支持**的投研框架。其设计原则是：把昂贵的研究员时间，让位于可复用、可自动化的数据与知识基础设施。

### 3.1 WorkBuddy + karpathy-claude-wiki 本地知识库

将 **WorkBuddy**（AI 助手）与 **karpathy-claude-wiki**（本地化、文件即知识库的轻量 RAG / Wiki 方案）组合，得到一个**低成本、本地优先的"Google NotebookLM 替代"**：

- **本地优先、隐私可控**：知识以纯文本 / Markdown 形式存放在本地目录，不上传第三方，零订阅成本。
- **投研知识库积累**：尤其适合沉淀**财报（10-K / 10-Q）与 Earnings Call Transcript**——把原始 filing 与纪要放入 Wiki 目录后，即可用自然语言持续追问、对比、提炼。
- **与 WorkBuddy 协同**：WorkBuddy 负责检索、调用数据脚本、生成报告；claude-wiki 负责长期记忆与可追溯引用，二者互补形成研究闭环。

**以研究 Google（Alphabet）财报为例的工作流：**
1. 用 `batch/sec_filings_downloader.py` 拉取 GOOG 近 8 个季度的 10-K / 10-Q，放入 Wiki 知识库目录；
2. 用 `batch/transcripts_downloader.py` 抓取对应季度的 Earnings Call Transcript，一并入库；
3. 在 claude-wiki 中直接提问，例如："对比最近四个季度 Google Cloud 收入增速与整体 CapEx 节奏，并标出管理层对资本开支的表述变化"；
4. 将 Wiki 给出的引用片段交给 WorkBuddy，结合 `earning_metrics_quarterly` 表做量化交叉验证，生成投研笔记。

> 该组合强调"原始来源可追溯"：所有结论都能回链到具体 filing / transcript 段落，而非黑盒摘要。

### 3.2 数据脚本（定时 / 非定时）

`batch/` 与 `scripts/` 目录覆盖了从采集、清洗到入库的完整数据管线，绝大多数通过 cron / hermes 定时运行：

- **Earnings**：`sec_filings_downloader.py`（开源）、`transcripts_downloader.py`（开源）、`*_earning_loader.py`（MSFT / GOOG / AMZN / META / ORCL / AAPL）、`msft_monthly_report.py`
- **包下载**：`npm_downloads_*.py`、`pypi_*.py`、`npm_downloads_monthly_supplement.py`
- **指数计算**：`calculate_admi_v2.js`、`calculate_eapi.js`、`calculate_aadi.js`、`calculate_agentic_index.js`、`admi_v2_backfill.js`
- **GPU / Token**：`scripts/vast_gpu_price_tracker.py`、`openrouter_*_collector.py`、`otpi_vercel_calculator.py`、`vercel_ai_leaderboard_scraper.py`
- **ROIC**：`scripts/upload_genai_roic_variables.py`
- **新闻 / 信号**：`token_price_news_daily.py`、`news_search_*_daily.py`、`ai_news_monitor.py`、`layoff_news_scraper.py`、`california_warn_scraper.py`、`challenger_report_scraper.py`、`tesla_robotaxi_tracker.py`


### 3.3 基于 hermes + 飞书的及时通知

框架通过 **hermes（本地 cron / 任务调度）+ 飞书 webhook** 实现"数据 / 价格 / 新闻"的及时推送：

- `batch/feishu_notify.py` 是统一的飞书通知模块，所有 cron 脚本 `import` 后直接调用 `send(title, text)`；支持 `@` 提及，webhook 地址读取自 `.env` 的 `FEISHU_WEBHOOK`。
- `batch/token_price_news_daily.py` 每天定时（北京时间 09:30）扫描 Google News RSS，用信号模式过滤"真正的降价公告"与"媒体推测"，命中即推送飞书。
- 其他脚本（GPU 价格、周报生成、新闻监控）均可在关键节点调用飞书通知，形成"采集 → 异常 / 信号 → 推送"的闭环。

### 3.4 开源 Skill

框架沉淀了可直接复用的 **Skill（可复用工作流 / 提示词包）**，例如：

- `skills/sec-earnings-analysis`：基于本地 SEC 财报文件（8-K / 10-Q / 10-K 与电话会纪要）撰写中文财报解读报告的完整流程——文件拉取与归档、结构化解析、定量对比、定性分析、HTML 报告生成与 `research_reports` 入库。

后续将持续补充财报分析、指数计算等 Skill，供社区直接调用或二次开发。

---

## 关于我

我由一名软件工程师转型独立数据分析师，目前专注于 AI 应用领域数据分析和股票基本面研究。超过 20 年软件和金融科技职业背景，帮助我构建独特的数据和分析视角。
可以通过以下方式了解更多或与我联系：
- Substack专栏 https://transformerfacts.substack.com/  
- 小红书：TF数据官

---

## 技术栈

- **后端**：Node.js 原生 HTTP（前端站点 API）
- **数据管线**：Python（urllib / requests）+ Node.js
- **数据库**：Supabase（PostgreSQL，REST API 读写）
- **前端**：HTML5 + CSS3 + Chart.js（金融终端深色风格）
- **调度 / 通知**：cron / hermes + 飞书 webhook
- **知识库**：karpathy-claude-wiki（本地 RAG）+ WorkBuddy

---

## ⚠️ Disclaimer

**TransformerFacts（"TF数据官"）是投研与个人知识管理工具，不构成投资建议。** 所有市场数据、公司信息、财务数字、新闻和监管信息都应以原始来源为准。本项目的指数、模型与报告基于公开数据合成，可能存在滞后、误差或方法论局限，使用者须独立判断并自担风险。

---

## License

[MIT](LICENSE) —— 欢迎社区复用、二次开发与贡献 Skill。
