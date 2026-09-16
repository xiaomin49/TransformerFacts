#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SEC 财报 HTML → 可读纯文本提取器

把 SEC 8-K/10-Q/10-K 等 HTML 文件提取为可检索、可通读的 UTF-8 文本。
技术要点（已在多份财报上验证）：
  - 删除 <script>/<style> 块
  - 块级/单元格标签(div/p/td/tr/li/h*)替换为换行，其余标签替换为空格
  - html.unescape 实体解码；\xa0 与乱码空白归一化
  - 折叠多余空行；段落按 --width 折行（默认 120）

用法：
  python sec_html_to_text.py <in.htm> -o <out.txt> [--width 120]
  python sec_html_to_text.py <in1.htm> <in2.htm> -o <out.txt>   # 多文件合并（按序）
  python sec_html_to_text.py <in.htm> --stdout | head            # 输出到 stdout

注意：本机 Windows 环境用 managed Python：
  C:/Users/xiaom/.workbuddy/binaries/python/versions/3.13.12/python.exe sec_html_to_text.py ...
"""
import argparse
import html
import re
import sys
import textwrap

# 需要换成换行的标签（保持表格/段落/列表的可读顺序）
_BLOCK_TAGS = {
    "table", "tr", "td", "th", "caption", "thead", "tbody", "tfoot",
    "p", "div", "br", "li", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre",
}


def _tag_repl(m):
    tag = m.group(1).lower()
    return "\n" if tag in _BLOCK_TAGS else " "


def _strip_scripts(raw):
    return re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", " ", raw)


def html_to_text(raw_html):
    raw = _strip_scripts(raw_html)
    txt = re.sub(r"(?i)<(/?)([a-z][a-z0-9]*)[^>]*>", _tag_repl, raw)
    txt = html.unescape(txt)
    txt = txt.replace("\xa0", " ")
    # 行内空白折叠
    txt = re.sub(r"[ \t]+", " ", txt)
    # 空白行折叠
    txt = re.sub(r"\n[ \t]*\n+", "\n\n", txt)
    # 行首行尾清理
    txt = re.sub(r"(?m)^[ \t]+", "", txt)
    txt = re.sub(r"(?m)[ \t]+$", "", txt)
    return txt.strip()


def wrap_text(txt, width):
    if not width or width <= 0:
        return txt
    out = []
    for para in txt.split("\n"):
        if para.strip() == "":
            out.append("")
            continue
        # 段落内折行（避免切单词；对长数字串宽容处理）
        out.append(textwrap.fill(para, width=width, break_long_words=True))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="SEC 财报 HTML → 纯文本")
    ap.add_argument("inputs", nargs="+", help="一个或多个 .htm 文件")
    ap.add_argument("-o", "--output", help="输出 .txt 路径（缺省则打印到 stdout）")
    ap.add_argument("--width", type=int, default=120, help="折行宽度，0=不折行")
    ap.add_argument("--encoding", default="utf-8", help="HTML 读取编码，默认 utf-8")
    args = ap.parse_args()

    parts = []
    for p in args.inputs:
        with open(p, "r", encoding=args.encoding, errors="replace") as f:
            parts.append(html_to_text(f.read()))
    merged = "\n\n".join(parts)
    final = wrap_text(merged, args.width)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(final)
        sys.stderr.write("wrote %s (%d chars)\n" % (args.output, len(final)))
    else:
        sys.stdout.write(final + "\n")


if __name__ == "__main__":
    main()
