---
name: sec-earnings-analysis
description: 基于本地 SEC 财报文件（8-K/10-Q/10-K HTML 及电话会纪要 PDF）撰写中文财报解读报告的标准流程。当用户要求“分析某公司最新财报 / 按提示词做财报解读 / 解读 Q2 财报”且财报文件位于本地目录（如 ~/data/sec_filings/{TICKER}）时使用。硬性规范：报告只允许纯文本、列表一律只用一级（禁止二级/嵌套列表）、禁止 Markdown 表格等复杂格式；只引用本地 SEC 文件、禁止引用媒体文章或外部一致预期。
agent_created: true
---

# SEC 本地财报分析

## Overview

根据本地 SEC 财报文件撰写一份中文、可溯源、结构化、纯文本格式的财报解读报告。输入通常是一份最新 8-K 业绩公告（含附件 99.1 新闻稿），可选配套 10-Q/10-K 与电话会纪要 PDF。

本技能沉淀了以下已验证的实践（来源：SNOW/GOOG/MSFT/AMZN/CRM/ORCL 等财报分析任务）：
- SEC HTML 可靠提取为纯文本的方法与脚本
- 环比/同比数据配对的来源策略（最新 8-K 为当季 + 前一份 10-Q 为上季 + 上上年 10-K/10-Q 或 8-K 内对比列做同比）
- 用户明确的输出格式硬性约束
- 报告结构模板与证据核验清单

## Ticker 特化配置

技能主流程是 ticker 无关的，但部分公司（如 Oracle）有强特化的财年映射与指标口径，直接套通用 SaaS 模板会漏关键项或误读。目前已沉淀的 ticker 特化配置：

- **ORCL（Oracle）**：`references/ticker-oracle.md` —— 财年截止日 5/31、OCI(IaaS)/SaaS 拆分、RPO 转化节奏、Ampere 一次性收益对 EPS 同比的扭曲、CapEx 与净现金 CapEx 的区分、BYO/供应商融资/客户预付结构。分析 ORCL 前**先读本文件**，并按其清单逐项核对。
- 其他 ticker（GOOG/MSFT/AMZN/SNOW/CRM）沿用通用流程即可；若某 ticker 反复出现且口径特殊，按同样的 `references/ticker-{ticker}.md` 模式沉淀配置。

## 硬性输出规范（用户要求，不可违反）

1. **禁止表格**：全文不得使用 Markdown 表格（`|` 分列）或 HTML 表格等复杂格式。
2. **列表一律只用一级（禁止二级/嵌套列表）**：任何列表项下都不得再缩进出子列表；需要补充层级时改用标题（#/##/###），同一列表项要罗列多组信息时，用括号、分号、顿号在该项内一句写全。可接受写法示例（全部顶格 `- `，无缩进子项）：`- 总收入：$1,546.8M，同比 +35%（上年同期 $1,145.0M；上季 Q1 $1,391.0M，环比 +11.2%）`
3. **只用本地文件**：所有数字必须来自用户指定的本地 SEC 文件（8-K/10-Q/10-K/纪要 PDF）。禁止引用媒体文章、第三方一致预期、盘后股价、分析师目标价等内容，除非用户明确另行授权。
4. 报告用中文撰写。
5. 每个关键数字后标注来源文件（可文首统一声明数据来源，正文按需标注如「8-K 调节表」「10-Q 现金流量表」）。
6. 严守角色边界：只摆证据与逻辑，不给买卖建议、目标价或确定性结论；文末加“仅供研究参考，不构成投资建议”。
7. 交付物为 Markdown 文件，命名 `{TICKER}_FY{年度}Q{n}_财报解读_{YYYY-MM-DD}.md`，存放在该公司财报目录下（如 `~/data/sec_filings/SNOW/SNOW_FY2027Q2_财报解读_2026-09-02.md`）。

## Workflow

### Step 1: 定位输入文件

- 在用户给出的目录（如 `~/data/sec_filings/SNOW`）中按修改时间列出文件，确认最新财报文件与可用配套文件。
- 常见文件命名模式：`{TICKER}_8-K_{日期}_fy{年度}q{n}earnings.htm`（业绩公告主文件）、`{TICKER}_10-Q_{日期}_{ticker}-{period}.htm`（上季报）、`{TICKER}_10-K_*.htm`。

确定所需三份参考：
- 当季：最新 8-K（含附件 99.1 新闻稿：损益表/资产负债表/现金流量表/Non-GAAP 调节表/指引/管理层表态）
- 上季：上一份 10-Q（做环比 QoQ）
- 同比：8-K 内的“上年同期”列通常已含 YoY 数据，无需额外文件

### Step 2: 提取文本

- 对 HTML 财报：使用 `scripts/sec_html_to_text.py` 脚本提取为可读纯文本（处理标签剥离、实体解码、空白折叠）。
- 脚本单文件用法：`python sec_html_to_text.py <in.htm> <out.txt>`
- 脚本多文件用法：`python sec_html_to_text.py <out.txt> <in1.htm> <in2.htm> ...`（自动先合并再转换）
- 可选参数 `--keep-tables`：保留表格文本顺序（默认会尝试重排表格为可读行）。
- 长文本分行：提取结果若为超长单行，用 `--width 120` 折行，便于通读。
- PDF（电话会纪要等）：先尝试 `pdfminer.six`；若环境无该库且安装太慢，用 PDF 字节流正则 `re.finditer(rb'\((?:[^()\\]|\\.)*\)\s*Tj', data)` 提取 Tj 操作符文本（已多次验证有效）。

### Step 3: 建立数据清单

从当季 8-K 提取并核对以下区块（按需用文本检索定位）：
- 损益表：总收入、各业务线收入、毛利/毛利率、营业利润、净利润、EPS（GAAP 与非 GAAP 双口径）
- 资产负债表：现金及等价物、短期/长期投资、可转债或有息负债、股东权益
- 现金流量表：经营现金流、购建固定资产（CapEx）、自由现金流（如披露）
- Non-GAAP 调节表：剔除项（股权激励、摊销、并购费用、重组等）
- 指引（Financial Outlook）：下季与全年指引区间
- 管理层表态：CEO/CFO 原话（新闻稿内的引言）
- 公司特有关键指标（如 SaaS 公司：RPO、净收入留存率 NRR、客户数、>$1M 客户数等）

从上一份 10-Q 提取上季对应数字用于环比；同比直接取 8-K 中“上年同期”列。

### Step 4: 计算与口径统一

- 计算 YoY（对上年同期）与 QoQ（对上一季度）百分比。
- 全文统一口径说明：财年定义（如 SNOW 财年截至每年 1 月 31 日）、币种、GAAP/Non-GAAP、单位（M/亿）。
- 无法精确确认的环比/推算值明确标注「约」「推算」；数据缺口列明“待 10-Q / 待纪要文本”。

### Step 5: 撰写报告

按 `references/report-template.md` 的结构撰写（六段式：财报快照 / 经营要点与驱动 / 指引 / 管理层重要谈话 / 财务健康度 / 附：证据核验与不确定性说明），全篇遵守硬性输出规范：无表格、列表只用一级、不引媒体、可溯源、无投资建议。

### Step 6: 交付与清理

- 将报告写入 `~/data/sec_filings/{TICKER}/{TICKER}_FY{年度}Q{n}_财报解读_{YYYY-MM-DD}.md`。
- 清理任务中创建的临时脚本与中间文本文件（位于 `C:/Users/xiaom/` 下 `*_extract.py`、`*_text.txt`、`*_split.py` 等），可用 Python `os.remove` 逐个删除（沙箱内 `rm -f` 可能被中断）。
- 用 present_files 展示最终报告。

## 环境备注

- 本机 Windows + WSL 混合环境。SEC 目录通常形如 `\\wsl$\Ubuntu\home\xiaom\data\sec_filings\{TICKER}`；bash 中用 `//wsl$/Ubuntu/...`。
- Python（managed，优先）：`C:/Users/xiaom/.workbuddy/binaries/python/versions/3.13.12/python.exe`
- 沙箱内长命令可能被 SIGTERM 中断：优先用 Write 落盘 `.py` 脚本再执行；需要删除多文件时用 Python 而非 shell rm。
- 引号/路径转义在 bash `-c` 内联常失败，一律写脚本文件再运行。

## Resources

### scripts/

- `sec_html_to_text.py`：SEC 财报 HTML → 纯文本提取器（标签剥离/实体解码/空白折叠/表格重排/折行/多文件合并）。每次财报分析直接调用，无需重写提取逻辑。

### references/

- `report-template.md`：财报解读报告的六段式结构模板（纯文本版），含各章节应放什么内容、示例句式、来源标注规范与交付前自查清单。
