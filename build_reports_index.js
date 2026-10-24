#!/usr/bin/env node
/**
 * build_reports_index.js
 * 扫描 reports/ 下的周报与 reports/earnings/ 下的财报解读，
 * 生成 reports-data.js（window.TF_DATA），供 index.html 自动渲染列表。
 *
 * 用法: node build_reports_index.js
 * 约定:
 *   周报  : reports/ai-weekly-YYYY-MM-DD.html  -> 取 <title>
 *   财报  : reports/earnings/*.md|*.html       -> 取 frontmatter 的 title:，否则首个 # 标题
 *   日期  : 周报从文件名提取；财报取文件名末尾 _YYYY-MM-DD
 */
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const REPORTS_DIR = path.join(ROOT, 'reports');
const EARNINGS_DIR = path.join(REPORTS_DIR, 'earnings');

function readFileSafe(p) {
  try { return fs.readFileSync(p, 'utf8'); } catch { return ''; }
}

function titleFromHtml(html) {
  const m = html.match(/<title>([\s\S]*?)<\/title>/i);
  return m ? m[1].trim() : '';
}

function titleFromMd(md) {
  // 1) frontmatter 的 title:
  if (md.startsWith('---')) {
    const fm = md.match(/^---[\s\S]*?---/);
    if (fm) {
      const t = fm[0].match(/^\s*title:\s*(.+)$/m);
      if (t) return t[1].trim().replace(/^["']|["']$/g, '');
    }
  }
  // 2) 首个 # 标题
  const lines = md.split('\n');
  for (const ln of lines) {
    const h = ln.match(/^#\s+(.+)$/);
    if (h) return h[1].trim();
  }
  return '';
}

function dateFromWeekly(name) {
  const m = name.match(/(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : '';
}

function dateFromEarnings(name) {
  const m = name.match(/_(\d{4}-\d{2}-\d{2})\.[^.]+$/);
  return m ? m[1] : '';
}

function niceFallback(name, prefix) {
  return (prefix || '') + name.replace(/\.[^.]+$/, '');
}

// ── 周报 ──
const weekly = [];
if (fs.existsSync(REPORTS_DIR)) {
  for (const f of fs.readdirSync(REPORTS_DIR)) {
    if (/^ai-weekly-\d{4}-\d{2}-\d{2}\.html$/i.test(f)) {
      const date = dateFromWeekly(f);
      const title = titleFromHtml(readFileSafe(path.join(REPORTS_DIR, f))) || niceFallback(f, 'AI 应用生态周报 ');
      weekly.push({ date, title, file: 'reports/' + f });
    }
  }
}
weekly.sort((a, b) => b.date.localeCompare(a.date));

// ── 财报解读 ──
const earnings = [];
if (fs.existsSync(EARNINGS_DIR)) {
  for (const f of fs.readdirSync(EARNINGS_DIR)) {
    if (/\.(md|html)$/i.test(f)) {
      const full = path.join(EARNINGS_DIR, f);
      const raw = readFileSafe(full);
      const isMd = /\.md$/i.test(f);
      const title = (isMd ? titleFromMd : titleFromHtml)(raw) || niceFallback(f);
      const date = dateFromEarnings(f);
      const type = f.split('.').pop().toUpperCase();
      earnings.push({ date, title, file: 'reports/earnings/' + f, type });
    }
  }
}
earnings.sort((a, b) => b.date.localeCompare(a.date));

const data = { weekly, earnings };
const out = '// 由 build_reports_index.js 自动生成，请勿手改。\nwindow.TF_DATA = ' +
  JSON.stringify(data, null, 2) + ';\n';

fs.writeFileSync(path.join(ROOT, 'reports-data.js'), out, 'utf8');
console.log('Generated reports-data.js  |  周报: ' + weekly.length + '  财报: ' + earnings.length);
