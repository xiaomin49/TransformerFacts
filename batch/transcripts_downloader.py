#!/usr/bin/env python3
"""
财报电话会议 transcript 下载器
================================

数据源（按优先级，自动选择可用者）：
  1. roic.ai  —— 专门的 earnings-call transcript API，返回结构化、干净文本
                 （speaker 分段、无 HTML 噪声）。这是替代 Tavily 网页抓取的核心：
                 抓取公开网页会得到夹杂导航栏/Logo/页脚的脏文本，且部分源内容不完整。
                 · 免费层可用（无需信用卡），仅含最近 2 个季度历史
                 · Individual $29/月 = 20 个季度历史；Professional $89/月 = 全部历史
                 · API key: ~/.env 中 ROIC_API_KEY
                 · Endpoint: GET https://api.roic.ai/v3.0.0/earnings-calls/{identifier}
                             ?apikey=KEY&fiscal_year=Y&fiscal_quarter=Q&format=json
  2. Tavily   —— 仅当 roic 不可用/无 key 时的兜底（保留原网页抓取逻辑，仍受 HTML 噪声影响）

为什么弃用"纯 Tavily 抓取"：
  Tavily 抓的是 Fool / GlobeAndMail / Investing / GuruFocus 等公开文章，
  返回正文夹杂大量导航/页脚 HTML 噪声（如之前 SNOW 文件前 17 行都是 Logo/菜单），
  且 GuruFocus 等源内容常不完整（仅 2~3 KB），导致"文件内容不对"。
  专用 API 直接返回清洗后的结构化文本，质量与稳定性远胜网页抓取。

配置项（用户可改）：
  TICKERS      : dict[ticker, 公司全名]
  START_DATE   : 窗口起始 YYYY-MM-DD（空 = 不限）
  END_DATE     : 窗口结束 YYYY-MM-DD（空 = 今天）
  OUTPUT_DIR   : 输出目录（用户主目录下 ~/data/transcripts）

国内（中国）是否有更便宜的 API？
  —— 经调研，没有。国内数据源（AKShare / Tushare / 聚合数据 / 天行数据 等）
     聚焦 A 股行情与财报，不提供美股 earnings call transcript。
  便宜且干净的替代是海外专门 API：
     · roic.ai      免费层可用（无信用卡），Individual $29/月 = 20 季度（本脚本默认接入）
     · earningscalls.dev  $24.99/月 = 5 年以上深度（免费 RapidAPI 50 次/月试用），可作为后续扩展
"""

import os
import re
import json
import time
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Tuple

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error
    import urllib.parse
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("transcripts")


# ── .env 加载 ───────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(ROOT_DIR, ".env")


def load_env() -> dict:
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    env[key.strip()] = val.strip()
    return env


_env = load_env()


# ── 公司配置（可改）─────────────────────────────────────────────────────────
# Ticker -> 公司名
TICKERS: dict[str, str] = {
    "ORCL": "Oracle Corp",
    # "SNOW": "Snowflake Inc.",
    #"MSFT": "Microsoft Corp",
    #"AMZN": "Amazon.com Inc.",
    #"GOOG": "Alphabet Inc.",
    #"META": "META Platforms, Inc.",
    #"AAPL": "Apple Inc",
    #"NVDA": "NVIDIA Corp",
    #"CRM":  "Salesforce, Inc.",
    #"DDOG": "Datadog, Inc.",
    #"TEAM": "Atlassian Corp",
    #"MCD":  "McDonalds Corp",
    #"CRWV": "CoreWeave, Inc.",
    #"NBIS": "Nebius Group N.V.",
    #"BABA": "Alibaba Group Holding Ltd",
}

# ── 全局配置（可改）─────────────────────────────────────────────────────────
# 输出目录：与 sec_filings_downloader.py 一致，用 Path.home()/"data"/"transcripts"。
# 在 WSL 环境下 Path.home() == /home/xiaom，即 \\wsl$\Ubuntu\home\xiaom\data\transcripts。
OUTPUT_DIR = Path.home() / "data" / "transcripts"
START_DATE = "2026-07-01"     # YYYY-MM-DD，空字符串表示不限制
END_DATE = ""                 # YYYY-MM-DD，空字符串表示今天
REQUEST_DELAY = 2.0           # roic 免费层严格限速，2s/请求更稳妥；Tavily 同理
# 同一财报日保留的最小"完整"长度阈值：低于此值视为片段，允许被更长的源覆盖
MIN_COMPLETE_CHARS = 8000

# ── roic.ai 配置 ────────────────────────────────────────────────────────────
ROIC_API_KEY = _env.get("ROIC_API_KEY", "")
ROIC_BASE = "https://api.roic.ai"
ROIC_LIST_PATH = "/v3.0.0/earnings-calls"                 # 列出可获取的 call（发现财政周期）
ROIC_CALL_PATH = "/v3.0.0/earnings-calls/{identifier}"    # 获取单个 call 全文

# ── Tavily 配置（兜底）──────────────────────────────────────────────────────
TAVILY_API_KEY = _env.get("TAVILY_API_KEY", "")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
MAX_RESULTS_PER_TICKER = 20
PRIORITY_DOMAINS = [
    "fool.com",
    "theglobeandmail.com",
    "investing.com",
    "gurufocus.com",
]
URL_ALLOW_PATTERNS = [
    r"fool\.com/earnings/call-transcripts/",
    r"theglobeandmail\.com/.*earnings-call-transcript",
    r"investing\.com/news/transcripts/",
    r"gurufocus\.com/news/.*transcript",
]
URL_BLOCK_PATTERNS = [
    r"youtube\.com", r"youtu\.be",
    r"\.pdf$",
    r"bamsec\.com",
    r"stocklight\.com",
    r"stockanalysis\.com/.*/transcripts",
    r"nasdaq\.com/market-activity",
    r"marketscreener\.com",
    r"/symbol/.*/earnings", r"/quote/.*/earnings",
    r"investors\.[a-z]+\.com",
]


# ── 通用工具 ─────────────────────────────────────────────────────────────────

def parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def date_in_window(d: date, start: date, end: date) -> bool:
    if start and d < start:
        return False
    if d > end:
        return False
    return True


def priority_rank(url: str) -> int:
    u = url.lower()
    for i, d in enumerate(PRIORITY_DOMAINS):
        if d in u:
            return i
    return len(PRIORITY_DOMAINS)


def infer_date_from_url(url: str) -> Optional[date]:
    m = re.search(r"/(\d{4})/(\d{1,2})/(\d{1,2})/", url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return None


def is_transcript_url(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    for pat in URL_BLOCK_PATTERNS:
        if re.search(pat, u):
            return False
    for pat in URL_ALLOW_PATTERNS:
        if re.search(pat, u):
            return True
    return False


# ── roic.ai 客户端 ──────────────────────────────────────────────────────────

def _retry_after_seconds(attempt: int, headers=None) -> int:
    """从 Retry-After 头或指数退避计算等待秒数。"""
    ra = None
    if headers:
        try:
            ra = headers.get("Retry-After")
            ra = int(ra)
        except (TypeError, ValueError):
            ra = None
    return ra if ra else (attempt + 1) * 8


def _roic_get(path: str, params: dict) -> Tuple[Optional[dict], int]:
    """GET roic.ai，带重试。返回 (json, status)。apikey 通过 query 传递。

    重试策略：仅对 429（限流，按 Retry-After / 指数退避等待）与网络/超时错误重试；
    401/403 为鉴权问题、404 为资源不存在、402 为付费限制，均属终态立即返回。
    urllib 分支也正确回传 HTTP 状态码（而非吞掉为 0）。
    """
    url = ROIC_BASE + path
    params = dict(params)
    params["apikey"] = ROIC_API_KEY
    last_exc = None
    for attempt in range(2):
        try:
            if requests:
                resp = requests.get(url, params=params, timeout=30)
                status = resp.status_code
                if status == 429:
                    wait = _retry_after_seconds(attempt, resp.headers)
                    log.warning("  roic.ai 限流，等待 %ds...", wait)
                    time.sleep(wait)
                    continue
                if status == 200:
                    try:
                        return resp.json(), status
                    except ValueError:
                        return None, status
                return None, status
            else:
                full = url + "?" + "&".join(
                    f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
                req = urllib.request.Request(full, method="GET")
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8", errors="replace")), r.status
        except urllib.error.HTTPError as he:
            code = he.code
            if code == 429:
                wait = _retry_after_seconds(attempt, getattr(he, "headers", None))
                log.warning("  roic.ai 限流，等待 %ds...", wait)
                time.sleep(wait)
                continue
            return None, code
        except Exception as exc:  # 网络/超时等才重试
            last_exc = exc
        if attempt < 3:
            time.sleep((attempt + 1) * 3)
    if last_exc:
        log.warning("  roic.ai 请求最终失败: %s", last_exc)
    return None, 0


# ── 交易所解析 + 周期发现（基于 roic list 端点，单次发现全部可获取周期）────────
# roic.ai 的 list 端点 `GET /v3.0.0/earnings-calls?identifier=EXCHANGE:TICKER`
# 会按 identifier 过滤，直接返回该标的全部可获取 call（含 fiscal_year/
# fiscal_quarter/date）。无效交易所前缀返回 404，有效前缀返回 200（data 可能为空）。
# 因此：
#   · 解析交易所：依次试候选交易所，首个 list 返回 200 的即为正确前缀（无需逐个
#     财政周期探测）；结果缓存到磁盘，避免每次运行都重探。
#   · 发现周期：一次 list 调用即得全部可获取周期，无需枚举 16 个财政周期逐个
#     请求——这正是此前触发免费层限流（429）的根因。
_IDENT_CACHE_FILE = os.path.join(ROOT_DIR, ".roic_ident_cache.json")
_IDENT_CACHE: dict[str, Optional[str]] = {}


def _load_ident_cache() -> dict:
    try:
        with open(_IDENT_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_ident_cache(cache: dict) -> None:
    try:
        with open(_IDENT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _roic_resolve_identifier(ticker: str) -> Optional[str]:
    """解析 ticker -> 'EXCHANGE:TICKER'，基于 roic list 端点（单次发现）。

    依次尝试常见交易所，首个 list 返回 200 的前缀即为正确 identifier；
    404 表示该交易所下 ticker 无效，换下一个；结果缓存到磁盘，重复运行零额外请求。
    若所有候选都 200-empty/404，则回退到最后一个 200（有效但无可用 call）。
    """
    if ticker in _IDENT_CACHE:
        return _IDENT_CACHE[ticker]
    disk = _load_ident_cache()
    if ticker in disk:
        _IDENT_CACHE[ticker] = disk[ticker]
        return disk[ticker]

    candidates = [
        f"NASDAQ:{ticker}", f"NYSE:{ticker}",
        f"NYSEAMERICAN:{ticker}", f"BATS:{ticker}",
    ]
    result: Optional[str] = None
    last_200: Optional[str] = None
    for cand in candidates:
        data, status = _roic_get(ROIC_LIST_PATH, {"identifier": cand})
        time.sleep(REQUEST_DELAY)
        if status == 200:
            last_200 = cand
            items = (data or {}).get("data") or []
            if items:
                result = cand
                break
        elif status in (401, 403):
            _IDENT_CACHE[ticker] = None
            _save_ident_cache({**_load_ident_cache(), ticker: None})
            return None
        # 404 -> 下一交易所；429 由 _roic_get 内部退避重试
    if result is None:
        result = last_200
    _IDENT_CACHE[ticker] = result
    _save_ident_cache({**_load_ident_cache(), ticker: result})
    return result


def _roic_parse_transcript(data: dict) -> Optional[str]:
    """从 roic 响应中提取纯文本（speaker 分段，无 HTML 噪声）。"""
    if not isinstance(data, dict):
        return None
    transcript = data.get("transcript")
    if isinstance(transcript, list):
        parts = []
        for turn in transcript:
            if not isinstance(turn, dict):
                continue
            spk = (turn.get("speaker") or "Speaker").strip()
            txt = turn.get("text") or ""
            if txt:
                parts.append(f"{spk}: {txt}")
        text = "\n\n".join(parts)
    elif isinstance(transcript, str):
        text = transcript
    else:
        return None
    return text.strip() or None


def roic_get_transcripts(ticker: str, start: date, end: date) -> List[Tuple[date, str, str]]:
    """roic.ai 主入口：返回 [(call_date, clean_text, url), ...]（仅窗口内）。

    流程（极省请求，不触发限流）：
      1) 解析交易所前缀（list 端点，命中即停，且磁盘缓存）
      2) 一次 list 调用得到该标的全部可获取 call 的周期与日期
      3) 仅对窗口内的周期逐个 fetch 全文（通常 1~2 个）
    免费层 list 仅返回最近 2 个 call，付费层返回更多；无需再枚举财政周期。
    """
    identifier = _roic_resolve_identifier(ticker)
    if not identifier:
        log.warning("  roic.ai: 无法解析 %s 的交易所前缀（已尝试 NASDAQ/NYSE/NYSEAMERICAN/BATS）", ticker)
        return []

    data, status = _roic_get(ROIC_LIST_PATH, {"identifier": identifier})
    time.sleep(REQUEST_DELAY)
    if status != 200 or not data:
        log.warning("  roic.ai: 获取 %s call 列表失败 (status=%s)", identifier, status)
        return []
    calls = data.get("data") or []

    out: List[Tuple[date, str, str]] = []
    for c in calls:
        fy = c.get("fiscal_year")
        fq = c.get("fiscal_quarter")
        ds = c.get("date")
        cd = parse_date(ds) if ds else None
        if not cd or not date_in_window(cd, start, end):
            continue
        d2, st2 = _roic_get(ROIC_CALL_PATH.format(identifier=identifier),
                            {"fiscal_year": fy, "fiscal_quarter": fq})
        time.sleep(REQUEST_DELAY)
        if st2 == 200 and d2:
            text = _roic_parse_transcript(d2)
            if text and cd:
                url = (f"{ROIC_BASE}{ROIC_CALL_PATH.format(identifier=identifier)}"
                       f"?fiscal_year={fy}&fiscal_quarter={fq}")
                out.append((cd, text, url))
        elif st2 in (401, 403):
            log.error("  roic.ai: 鉴权失败 (%d)，请检查 ROIC_API_KEY", st2)
            break
        elif st2 == 402:
            # 付费限制：该周期超出免费层，停止（免费层最近 2 个 call 已覆盖）
            log.info("  roic.ai: %s 该周期超出免费层 (402)，停止", identifier)
            break
        # 404/429 等：忽略继续；429 已由 _roic_get 内部退避
    return out


# ── Tavily 客户端（兜底）────────────────────────────────────────────────────

def tavily_post(url: str, payload: dict, max_retries: int = 3) -> Optional[dict]:
    headers = {"Content-Type": "application/json"}
    for attempt in range(max_retries):
        try:
            if requests:
                resp = requests.post(url, json=payload, headers=headers, timeout=30)
            else:
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode("utf-8"),
                    headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode("utf-8", errors="replace"))
            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                log.warning("  Tavily 限流，等待 %ds...", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.warning("  Tavily 请求失败 (attempt %d): %s", attempt + 1, exc)
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
    return None


def search_transcripts(query: str) -> list:
    payload = {"api_key": TAVILY_API_KEY, "query": query,
               "max_results": MAX_RESULTS_PER_TICKER}
    data = tavily_post(TAVILY_SEARCH_URL, payload)
    if not data:
        return []
    return [r.get("url", "") for r in data.get("results", []) if r.get("url")]


def collect_urls(company_name: str, ticker: str, start: date, end: date) -> list:
    years = set()
    if start:
        years.add(start.year)
    if end:
        years.add(end.year)
    years.add(date.today().year)
    years = sorted(years)

    base = f'"{company_name}" ({ticker}) earnings call transcript'
    seen, raw = set(), []
    for y in years:
        for q in [base, f"{company_name} {ticker} earnings call transcript {y}"]:
            urls = search_transcripts(q)
            time.sleep(REQUEST_DELAY)
            for u in urls:
                if u and u not in seen:
                    seen.add(u)
                    raw.append(u)
            time.sleep(REQUEST_DELAY)

    filtered = [u for u in raw if is_transcript_url(u)]
    if not filtered:
        filtered = raw[:5]
    filtered.sort(key=lambda u: (priority_rank(u), infer_date_from_url(u) or date.max))
    return filtered


def extract_transcript(url: str) -> Optional[dict]:
    payload = {"api_key": TAVILY_API_KEY, "urls": [url]}
    data = tavily_post(TAVILY_EXTRACT_URL, payload)
    if not data:
        return None
    results = data.get("results", [])
    return results[0] if results else None


MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_MONTH_ALT = (r"January|February|March|April|May|June|July|August|September|"
              r"October|November|December|Sept|Sep|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Oct|Nov|Dec")
_WEEKDAY = r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
_DATE_RE_WD = re.compile(r"\b" + _WEEKDAY + r",?\s+(" + _MONTH_ALT + r")\.?\s+(\d{1,2}),?\s*(20\d{2})\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(" + _MONTH_ALT + r")\.?\s+(\d{1,2}),?\s*(20\d{2})\b", re.IGNORECASE)


def _to_date(m) -> Optional[date]:
    if not m:
        return None
    mon = MONTHS.get(m.group(1)[:3].capitalize())
    if not mon:
        return None
    try:
        return date(int(m.group(3)), mon, int(m.group(2)))
    except ValueError:
        return None


def extract_call_date(text: str, url: str = "") -> Optional[date]:
    if text:
        m = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", text[:2000])
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
        for window in (text[:8000], text):
            d = _to_date(_DATE_RE_WD.search(window))
            if d:
                return d
            d = _to_date(_DATE_RE.search(window))
            if d:
                return d
    return infer_date_from_url(url)


def tavily_get_transcripts(company_name: str, ticker: str,
                           start: date, end: date) -> List[Tuple[date, str, str]]:
    """Tavily 兜底：搜索 -> 抽取 -> 解析日期。返回 [(call_date, content, url), ...]。"""
    urls = collect_urls(company_name, ticker, start, end)
    if not urls:
        return []
    log.info("  候选 URL（已过滤排序）: %d 条", len(urls))
    out = []
    for url in urls:
        log.info("  → %s", url)
        result = extract_transcript(url)
        time.sleep(REQUEST_DELAY)
        if not result:
            continue
        content = result.get("raw_content", "")
        if not content or len(content) < 200:
            continue
        cd = extract_call_date(content, url)
        if not cd or not date_in_window(cd, start, end):
            continue
        out.append((cd, content, url))
    return out


# ── 保存 ─────────────────────────────────────────────────────────────────────

def save_transcript(company_name: str, ticker: str, url: str,
                    content: str, call_date: date,
                    start: date, end: date) -> Optional[Path]:
    if not date_in_window(call_date, start, end):
        return None
    out_path = OUTPUT_DIR / f"{company_name}_{call_date.isoformat()}_transcript.txt"
    if out_path.exists():
        old_len = out_path.stat().st_size
        if old_len >= len(content):
            log.info("    已存在且不劣于当前内容，跳过: %s", out_path.name)
            return out_path
        log.info("    已存在但更短 (%d<%d)，覆盖: %s", old_len, len(content), out_path.name)
    header = (
        f"{company_name} ({ticker}) - Earnings Call Transcript\n"
        f"Call Date: {call_date.isoformat()}\n"
        f"Source: {url}\n"
        f"{'=' * 80}\n\n"
    )
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(content)
        log.info("  ✓ 保存: %s (%d chars, %s)", out_path.name, len(content),
                 url.split("/")[2] if "//" in url else url)
        return out_path
    except IOError as exc:
        log.warning("  写入失败: %s — %s", out_path.name, exc)
        return None


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def process_ticker(ticker: str, company_name: str, start: date, end: date) -> int:
    log.info("═══ 处理 %s (%s) ═══", ticker, company_name)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) roic.ai 优先（干净结构化文本）
    results: List[Tuple[date, str, str, int]] = []  # (date, content, url, clean_flag)
    if ROIC_API_KEY:
        try:
            for cd, content, url in roic_get_transcripts(ticker, start, end):
                results.append((cd, content, url, 1))
        except Exception as exc:
            log.warning("  roic.ai 获取失败: %s", exc)
    else:
        log.info("  未配置 ROIC_API_KEY，跳过 roic.ai")

    # 2) 兜底 Tavily（仅在 roic 无结果时）
    if not results and TAVILY_API_KEY:
        log.info("  roic.ai 无结果，回退 Tavily 抓取")
        try:
            for cd, content, url in tavily_get_transcripts(company_name, ticker, start, end):
                results.append((cd, content, url, 0))
        except Exception as exc:
            log.warning("  Tavily 获取失败: %s", exc)

    if not results:
        log.info("  无 transcript 获取")
        return 0

    # 同 call_date 择优：clean 源优先，其次更长
    best: dict[date, Tuple[int, int, str, str]] = {}
    for cd, content, url, clean in results:
        if not date_in_window(cd, start, end):
            continue
        cur = best.get(cd)
        score = (clean, len(content))
        if cur is None or score > (cur[0], cur[1]):
            best[cd] = (clean, len(content), content, url)

    saved = 0
    for cd in sorted(best):
        _, _, content, url = best[cd]
        p = save_transcript(company_name, ticker, url, content, cd, start, end)
        if p:
            saved += 1
    log.info("  完成: %d 个 transcript", saved)
    return saved


def main():
    start = parse_date(START_DATE) if START_DATE else date(2000, 1, 1)
    end = parse_date(END_DATE) if END_DATE else date.today()

    active = []
    if ROIC_API_KEY:
        active.append("roic.ai")
    if TAVILY_API_KEY:
        active.append("Tavily(兜底)")
    if not active:
        log.error("未配置任何 API key。请在 ~/transformerfacts_web/.env 中配置 ROIC_API_KEY")
        log.error("（免费申请 https://roic.ai ，无需信用卡；免费层含最近 2 个季度历史）。")
        return

    log.info("transcript 下载器 启动，数据源: %s", " + ".join(active))
    log.info("输出目录: %s", OUTPUT_DIR)
    log.info("日期范围: %s ~ %s", start, end)
    log.info("Tickers: %s", list(TICKERS.keys()))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for ticker, name in TICKERS.items():
        try:
            total += process_ticker(ticker, name, start, end)
        except Exception as exc:
            log.error("  %s 处理异常: %s", ticker, exc)
            import traceback
            traceback.print_exc()

    log.info("全部完成，共保存 %d 个 transcript", total)


if __name__ == "__main__":
    main()
