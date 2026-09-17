#!/usr/bin/env python3
"""
SEC EDGAR 数据下载器
====================
从 SEC EDGAR 获取公司财报数据（10-K、10-Q、8-K）。

数据获取方式：
- 10-Q / 10-K → 下载 HTML 主报告文件
- 8-K        → 下载 HTML 文件（事件披露，非结构化数据）

功能：
- 支持配置多只股票
- 下载过去 8 个季度的数据
- 幂等：重复运行只获取新数据，不重复下载已有文件
- 10-Q/10-K 文件命名：{symbol}_{form_type}_{filing_date}_{filename}.htm
- 8-K 文件命名：{symbol}_8-K_{filing_date}_{filename}.htm

依赖：requests（标准库之外）
SEC EDGAR 对非商业用途开放，无需 API key。

配置：公司列表在 COMPANIES 字典中。
"""

import os
import re
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── requests 兼容处理 ─────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error
    requests = None

# ── 日志配置 ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sec_filings")


# ── 公司配置 ─────────────────────────────────────────────────────────────────
# CIK 格式：10 位数字，不足前面补 0
COMPANIES: dict[str, dict] = {
    # "MSFT": { "name": "Microsoft Corp", "cik": "0000789019"},
	# "GOOG": { "name": "Alphabet Inc.", "cik": "0001652044"},
   	# "META": { "name": "META Platforms, Inc.", "cik": "0001326801"},
	# "AMZN": { "name": "AMAZON COM,Inc.", "cik": "0001018724"},
	# "MCD": { "name": "MCDONALDS CORP", "cik": "0000063908"},
	 # "ORCL": { "name": "oracle corp", "cik": "0001341439"},
    "PLTR": { "name": "Palantir Technologies Inc.", "cik": "0001321655"},
    # "AAPL": {"name": "Apple Inc", "cik": "0000320193"},
	# "NBIS": {"name": "Nebius Group N.V.", "cik": "0001513845"},
	# "CRWV": {"name": "CoreWeave, Inc.", "cik": "0001769628"},
	# "SNOW": {"name": "Snowflake Inc.", "cik": "0001640147"},
	# "DDOG": {"name": "Datadog, Inc.", "cik": "0001561550"},
	# "TEAM": {"name": "Atlassian Corp", "cik": "0001650372"},
	# "CRM": {"name": "Salesforce, Inc. ", "cik": "0001108524"},
}

# ── 全局配置 ─────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(r"C:\Users\xiaom\Desktop\ai-workspace\ai-workspace-hub\inbox")  # 输出到 inbox/{ticker}/（{ticker} 子目录由 ensure_company_dir 创建）
START_DATE = "2025-09-01"   # YYYY-MM-DD，空字符串表示不限制（PLTR 测试：覆盖最近 4 个季度）
END_DATE = ""     # YYYY-MM-DD，空字符串表示不限制（默认取今天）
REQUEST_DELAY = 0.2
USER_AGENT = "Mozilla/5.0 (compatible; sec_filings_script/1.0; research@example.com)"

# ── HTTP 工具 ─────────────────────────────────────────────────────────────────

def http_get(url: str, headers: dict, timeout: int = 20) -> Optional[str]:
    """发送 HTTP GET，返回响应文本。失败返回 None。"""
    try:
        if requests:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("  HTTP 请求失败: %s — %s", url, exc)
        return None


def http_get_with_retry(url: str, headers: dict, timeout: int = 20,
                         max_retries: int = 3) -> Optional[str]:
    """带重试的 HTTP GET（应对 SEC 限流）。"""
    for attempt in range(max_retries):
        status_ok, text = _do_get(url, headers, timeout)
        if status_ok:
            return text
        if not status_ok and text == "RATE_LIMIT":
            wait = (attempt + 1) * 5
            log.warning("  SEC API 限流，等待 %ds...", wait)
            time.sleep(wait)
            continue
        if not status_ok and text == "NOT_FOUND":
            return None
        # 网络错误，重试
        if attempt < max_retries - 1:
            time.sleep((attempt + 1) * 2)
    return None


def _do_get(url: str, headers: dict, timeout: int):
    """执行一次 GET。返回 (True, text) 或 (False, error_type)。"""
    try:
        if requests:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 404:
                return False, "NOT_FOUND"
            # SEC 限流通常返回 403/429/503，均按限流退避重试
            if resp.status_code in (403, 429, 503):
                return False, "RATE_LIMIT"
            resp.raise_for_status()
            return True, resp.text
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return True, r.read().decode("utf-8", errors="replace")
    except Exception:
        return False, "NETWORK_ERROR"


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def sec_headers(host: str = "www.sec.gov") -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Host": host,
    }


def filing_date_in_window(filing_date: str) -> bool:
    """判断 filing_date 是否在 START_DATE ~ END_DATE 区间内。"""
    try:
        fd = datetime.strptime(filing_date, "%Y-%m-%d")
        start = datetime.strptime(START_DATE, "%Y-%m-%d") if START_DATE else None
        end = datetime.strptime(END_DATE, "%Y-%m-%d") if END_DATE else datetime.today()
        if start and fd < start:
            return False
        if fd > end:
            return False
        return True
    except ValueError:
        return False


def parse_atom_feed(xml_text: str) -> list[dict]:
    """解析 SEC EDGAR ATOM feed。"""
    entries = []
    in_entry = False
    current = {}

    for line in xml_text.splitlines():
        line = line.strip()
        if "<entry>" in line:
            in_entry = True
            current = {}
        elif "</entry>" in line:
            if current:
                entries.append(current)
            in_entry = False
        elif in_entry:
            m = re.match(r"<([^/>]+)>(.*)</[^>]+>", line)
            if m:
                tag, val = m.group(1).split("}")[-1], m.group(2).strip()
                current[tag] = val
    return entries


def get_filing_list(cik: str, form_type: str, max_pages: int = 5) -> list[dict]:
    """获取某公司某类 filing 的（accession, filing_date, filing_href）列表。

    优先使用 data.sec.gov 的 submissions JSON API（官方推荐，单次请求返回全部
    filing 列表，避开 cgi-bin/browse-edgar 频繁 503）；失败时回退到 atom 接口。
    """
    # ── 方式一：submissions JSON API ──
    cik10 = str(cik).zfill(10)
    json_url = f"https://data.sec.gov/submissions/CIK{cik10}.json"
    text = http_get_with_retry(json_url, sec_headers("data.sec.gov"))
    if text:
        try:
            data = json.loads(text)
            recent = data.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            accs = recent.get("accessionNumber", [])
            dates = recent.get("filingDate", [])
            target = form_type.upper()
            filings = []
            for form, acc, fdate in zip(forms, accs, dates):
                if form != target or not acc or not fdate:
                    continue
                acc_nodash = acc.replace("-", "")
                filings.append({
                    "accession": acc,
                    "filing_date": fdate,
                    "filing_href": (
                        f"https://www.sec.gov/Archives/edgar/data/"
                        f"{int(cik)}/{acc_nodash}/{acc}-index.htm"
                    ),
                })
            if filings:
                log.info("    submissions API: %d 条 %s", len(filings), target)
                return filings  # 最新在前
        except (json.JSONDecodeError, AttributeError, ValueError) as exc:
            log.warning("  submissions JSON 解析失败: %s，回退 atom 接口", exc)

    # ── 方式二（回退）：browse-edgar atom 接口 ──
    filings = []
    for page in range(max_pages):
        start = page * 40
        url = (
            f"https://www.sec.gov/cgi-bin/browse-edgar"
            f"?action=getcompany&CIK={cik}"
            f"&type={form_type.upper()}"
            f"&dateb=&owner=include"
            f"&start={start}&count=40&output=atom"
        )
        text = http_get_with_retry(url, sec_headers())
        if not text:
            break
        entries = parse_atom_feed(text)
        if not entries:
            break
        for e in entries:
            accession = e.get("accession-number", "").strip()
            filing_date = e.get("filing-date", "")
            filing_href = e.get("filing-href", "").replace("&amp;", "&")
            if accession and filing_date:
                filings.append({
                    "accession": accession,
                    "filing_date": filing_date,
                    "filing_href": filing_href,
                })
        time.sleep(REQUEST_DELAY)
    return filings


def get_document_links(index_url: str) -> list[dict]:
    """从 filing index 页面解析文档列表。

    返回 [{"filename": ..., "url": ..., "type": ...}, ...]，
    type 为 SEC 文档类型（如 8-K / EX-99.1 / GRAPHIC / EX-101.SCH），
    仅保留 .htm 文件（跳过 .txt/.jpg/.xml/.xsd 等）。
    """
    text = http_get_with_retry(index_url, sec_headers())
    if not text:
        return []

    base = "https://www.sec.gov"
    result = []
    seen = set()
    # index 页面表格列顺序：Seq | Description | Document | Type | Size
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.DOTALL | re.IGNORECASE)
    for row in rows:
        m = re.search(r'href="([^"]+)"[^>]*>\s*([^<]+?)\s*</a>', row, re.IGNORECASE)
        if not m:
            continue
        link, label = m.group(1), m.group(2).strip()
        if not label:
            continue

        # 解析 Type 列（第 4 个 <td>）
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        cell_texts = [
            re.sub(r"<[^>]+>", "", c).replace("&nbsp;", "").strip()
            for c in cells
        ]
        dtype = cell_texts[3] if len(cell_texts) >= 4 else ""

        if link.startswith("/ix?doc="):
            raw_path = link.split("doc=", 1)[-1]
            actual_url = base + raw_path
        elif link.startswith("/"):
            actual_url = base + link
        else:
            actual_url = link

        fname = os.path.basename(actual_url)
        if not fname.lower().endswith(".htm"):
            continue
        if fname in seen:
            continue
        seen.add(fname)
        result.append({"filename": fname, "url": actual_url, "type": dtype})
    time.sleep(REQUEST_DELAY)
    return result



def download_10q_10k_html(
    company_dir: Path,
    symbol: str,
    form_type: str,
    filing_date: str,
    acc_nodash: str,
    accession: str,
    cik: str,
) -> Optional[Path]:
    """
    下载 10-Q 或 10-K 主报告 HTML 文件。
    主报告 = 含 8 位日期的 .htm 文件，跳过 index 和 ex* 附件。
    幂等：文件已存在则跳过。
    """
    index_url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{acc_nodash}/{accession}-index.htm"
    )
    docs = get_document_links(index_url)
    if not docs:
        log.warning("  无法获取 %s 的文档列表: %s", form_type, accession)
        return None

    # 找主报告：含日期 + 不含 ex + 不含 index
    primary = None
    for doc in docs:
        fname = doc["filename"]
        fn_lower = fname.lower()
        if "index" in fn_lower or fn_lower.startswith("ex"):
            continue
        if fname.endswith(".htm") and re.search(r'\d{8}\.htm', fname):
            primary = doc
            break

    if not primary:
        log.warning("  %s 无主报告文档: %s", form_type, accession)
        return None

    fname = primary["filename"]
    out_name = f"{symbol}_{form_type.upper()}_{filing_date}_{fname}"
    out_path = company_dir / out_name

    if out_path.exists():
        log.debug("  已存在，跳过: %s", out_name)
        return out_path

    text = http_get(primary["url"], sec_headers())
    if text is None:
        log.warning("  下载失败: %s", primary["url"])
        return None

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        log.info("  ✓ 保存: %s", out_name)
        return out_path
    except IOError as exc:
        log.warning("  写入失败: %s — %s", out_name, exc)
        return None


# ── 8-K 清理 ─────────────────────────────────────────────────────────────────

# 每个公司的财报附件（EX-99.1）命名模式（大小写不敏感）
EX99_1_PATTERNS: dict[str, re.Pattern] = {
    "GOOG": re.compile(r"exhibit991", re.IGNORECASE),
    "MSFT": re.compile(r"ex99_1", re.IGNORECASE),
    "SNOW": re.compile(r"ex99|exhibit99|fy\d{4}q\d", re.IGNORECASE),
}


def cleanup_8k_files(company_dir: Path, symbol: str) -> int:
    """
    删除所有非财报附件的 8-K 文件，只保留各公司财报附件。
    返回删除的文件数量。
    """
    pattern = EX99_1_PATTERNS.get(symbol.upper())
    if not pattern:
        log.debug("  %s: 无 8-K 清理规则，跳过清理", symbol)
        return 0

    removed = 0
    for fpath in company_dir.iterdir():
        if not fpath.name.startswith(f"{symbol.upper()}_8-K_"):
            continue
        if not pattern.search(fpath.name):
            log.info("  🗑 删除非 EX-99.1 8-K: %s", fpath.name)
            fpath.unlink()
            removed += 1
    return removed


# ── 8-K 下载 ─────────────────────────────────────────────────────────────────

def ensure_company_dir(symbol: str) -> Path:
    d = OUTPUT_DIR / symbol.upper()
    d.mkdir(parents=True, exist_ok=True)
    return d


def download_8k(company_dir: Path, symbol: str,
                 filing_date: str, doc: dict) -> Optional[Path]:
    """下载 8-K HTML 文件。只保留 ex99_1（附件99.1含财务数据）。跳过 index 和其他 ex。幂等。"""
    fname = doc["filename"]
    fn_lower = fname.lower()
    if "index" in fn_lower:
        return None
    # 优先按 SEC 文档类型判断：财报附件类型为 EX-99.1（最可靠，跨公司通用）
    dtype = doc.get("type", "").upper()
    is_ex991 = dtype == "EX-99.1"
    if not is_ex991:
        # 回退：个别 index 页可能无标准类型列，按文件名模式兜底
        # 支持: ex99_1, ex-99-1, exhibit991, googexhibit991q42025 等
        if not re.search(r'(?:exhibit|ex)(?![a-z])[-_]?99[-_]?1(?!\d)', fn_lower):
            return None

    out_name = f"{symbol}_8-K_{filing_date}_{fname}"
    out_path = company_dir / out_name

    if out_path.exists():
        log.debug("  已存在，跳过: %s", out_name)
        return out_path

    text = http_get(doc["url"], sec_headers())
    if text is None:
        return None
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        log.info("  ✓ 保存: %s", out_name)
        return out_path
    except IOError as exc:
        log.warning("  写入失败: %s — %s", out_name, exc)
        return None


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def process_company(symbol: str, config: dict) -> list[Path]:
    """处理单只股票：10-Q、10-K 用 XBRL API，8-K 下载 HTML。"""
    cik = config["cik"]
    name = config["name"]
    log.info("═══ 处理 %s (%s) ═══", symbol, name)

    company_dir = ensure_company_dir(symbol)
    saved = []
    # ── 10-Q / 10-K：下载 HTML ──
    for form_type in ["10-Q", "10-K"]:
        log.info("  ── %s ──", form_type)

        # 获取 filing 列表并过滤
        filings = get_filing_list(cik, form_type)
        filtered = [
            f for f in filings
            if filing_date_in_window(f["filing_date"])
        ]
        log.info("    窗口内 %d 条 filing，开始下载...", len(filtered))

        for f in filtered:
            acc = f["accession"]
            acc_nodash = acc.replace("-", "")
            filing_date = f["filing_date"]

            # 下载 HTML 主报告文件
            html_path = download_10q_10k_html(
                company_dir, symbol, form_type,
                filing_date, acc_nodash, acc, cik,
            )
            if html_path:
                saved.append(html_path)
            time.sleep(REQUEST_DELAY)

        time.sleep(REQUEST_DELAY)

    # ── 8-K：下载 HTML ──
    log.info("  ── 8-K ──")
    filings_8k = get_filing_list(cik, "8-K")
    filtered_8k = [
        f for f in filings_8k
        if filing_date_in_window(f["filing_date"])
    ]
    log.info("    窗口内 %d 条 8-K", len(filtered_8k))

    for f in filtered_8k:
        acc = f["accession"]
        date = f["filing_date"]
        acc_nodash = acc.replace("-", "")
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(cik)}/{acc_nodash}/{acc}-index.htm"
        )
        docs = get_document_links(index_url)
        for doc in docs:
            path = download_8k(company_dir, symbol, date, doc)
            if path:
                saved.append(path)
            time.sleep(REQUEST_DELAY)

    # ── 清理：只保留 EX-99.1 ──
    removed = cleanup_8k_files(company_dir, symbol)
    if removed:
        log.info("  清理了 %d 个非 EX-99.1 8-K 文件", removed)

    log.info("  完成: %d 个新文件", len(saved))
    return saved


def main():
    log.info("SEC EDGAR 数据下载器 启动")
    log.info("输出目录: %s", OUTPUT_DIR)
    date_range = f"{START_DATE or '不限'} ~ {END_DATE or datetime.today().strftime('%Y-%m-%d')}"
    log.info("日期区间: %s", date_range)
    log.info("公司: %s", list(COMPANIES.keys()))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for symbol, config in COMPANIES.items():
        try:
            saved = process_company(symbol, config)
            if not saved:
                log.info("  %s: 没有新数据", symbol)
        except Exception as exc:
            log.error("  %s 处理异常: %s", symbol, exc)
            import traceback
            traceback.print_exc()

    log.info("全部完成!")


if __name__ == "__main__":
    main()
