// Calculate Enterprise AI Penetration Index (EAPI) and write to growth_metrics
const https = require('https');
const config = require('../server/config');
const { createLogger } = require('./logger');

const logger = createLogger('calculate_eapi');

// Feishu webhook notification
function feishuSend(title, text) {
  const webhook = process.env.FEISHU_WEBHOOK || process.env.FEISHU_ROBOTAXI_WEBHOOK;
  if (!webhook) { logger.warn(`[${title}] FEISHU_WEBHOOK not set, skipping`); return; }
  const payload = JSON.stringify({ msg_type: 'text', content: { text: `**${title}**\n${text}` } });
  const req = https.request(webhook, { method: 'POST', headers: { 'Content-Type': 'application/json' } }, (res) => {
    logger.info(`[${title}] Feishu: ${res.statusCode}`);
  });
  req.on('error', (e) => logger.error(`[${title}] Feishu error: ${e.message}`));
  req.write(payload);
  req.end();
}

// Config
const SUPABASE_HOST = config.supabase.host;
const SUPABASE_KEY = config.supabase.key;

function querySupabase(table, filters = '') {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: SUPABASE_HOST,
      path: `/rest/v1/${table}?select=*${filters}`,
      method: 'GET',
      headers: {
        'apikey': SUPABASE_KEY,
        'Authorization': 'Bearer ' + SUPABASE_KEY
      }
    };
    https.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch(e) { resolve([]); }
      });
    }).on('error', reject).end();
  });
}

async function upsertGrowthMetrics(records) {
  // Supabase REST API: POST with merge-duplicates returns 409 for existing records.
  // Strategy: try upsert first; on 409, DELETE then INSERT.
  let success = 0;
  for (const record of records) {
    const data = JSON.stringify([record]);
    const baseHeaders = {
      'apikey': SUPABASE_KEY,
      'Authorization': 'Bearer ' + SUPABASE_KEY,
      'Content-Type': 'application/json'
    };

    await new Promise((resolve) => {
      // Step 1: try upsert (merge-duplicates on the table's unique key)
      const req1 = https.request({
        hostname: SUPABASE_HOST,
        path: '/rest/v1/growth_metrics?on_conflict=date,entity_type,entity_name,metric_name',
        method: 'POST',
        headers: { ...baseHeaders, 'Prefer': 'resolution=merge-duplicates' }
      }, (res) => {
        let body = '';
        res.on('data', c => body += c);
        res.on('end', () => {
          if (res.statusCode < 400) { success++; resolve(); return; }
          if (res.statusCode === 409) {
            // Already exists → skip
            resolve();
          } else {
            logger.error(`  Upsert failed for ${record.date}/${record.metric_name}: ${res.statusCode}`);
            resolve();
          }
        });
      });
      req1.write(data); req1.end();
    });
    await new Promise(r => setTimeout(r, 50));
  }
  logger.info(`Upserted ${success}/${records.length} records to growth_metrics`);
  return success;
}

// Package definitions
const AI_SDK_PACKAGES = [
  'ai-sdk-openai downloads',
  'ai-sdk-anthropic downloads',
  'ai-sdk-google downloads',
];

const ENTERPRISE_PACKAGES = [
  'dd-trace downloads',
  'snowflake-sdk downloads',
  // '@atlaskit/rovo-triggers downloads',  // 已剔除：下载量级过小、波动大，会扭曲 enterprise 子指数
];

const ALL_PACKAGES = [...AI_SDK_PACKAGES, ...ENTERPRISE_PACKAGES];

async function main() {
  // 命令行参数：--start YYYY-MM-DD / --end YYYY-MM-DD 过滤写入范围（可选）
  const argv = process.argv.slice(2);
  const arg = (name) => { const i = argv.indexOf(name); return i >= 0 && argv[i + 1] ? argv[i + 1] : null; };
  const startDate = arg('--start');
  const endDate = arg('--end');

  logger.info('='.repeat(60));
  logger.info('Enterprise AI Penetration Index (EAPI) Calculator');
  logger.info('='.repeat(60));
  if (startDate || endDate) {
    logger.info(`Write filter: ${startDate || '(no start)'} ~ ${endDate || '(no end)'}`);
  }

  // Fetch all historical weekly data for our packages
  logger.info('Fetching npm_weekly data for target packages...');
  
  const allData = {};
  for (const pkg of ALL_PACKAGES) {
    // URL-encode the metrics value (contains spaces and special chars)
    const encoded = encodeURIComponent(pkg);
    const rows = await querySupabase('npm_weekly', `&metrics=eq.${encoded}&order=end_date.asc&select=start_date,end_date,value`);
    allData[pkg] = rows;
    // Compute effective week date = end_date + 1 day (Monday after the week ends)
    for (const row of rows) {
      const mondayAfter = new Date(row.end_date);
      mondayAfter.setDate(mondayAfter.getDate() + 1);
      row.week_date = mondayAfter.toISOString().split('T')[0];
    }
    logger.info(`  ${pkg}: ${rows.length} weeks, week_date ${rows[0]?.week_date || 'N/A'} to ${rows[rows.length-1]?.week_date || 'N/A'}`);
  }

  // Verify all packages have data
  const missingPackages = ALL_PACKAGES.filter(p => !allData[p] || allData[p].length === 0);
  if (missingPackages.length > 0) {
    logger.error(`Missing data for: ${missingPackages.join(', ')}`);
    feishuSend('EAPI Calculation', `❌ 数据缺失: ${missingPackages.join(', ')}`);
    process.exit(1);
  }

  // Determine base week: the earliest week where ALL packages have at least one data point
  const allWeeks = new Set();
  for (const pkg of ALL_PACKAGES) {
    for (const row of allData[pkg]) {
      allWeeks.add(row.week_date);
    }
  }
  const sortedWeeks = Array.from(allWeeks).sort();

  // Find base week: earliest week where every package has data
  let baseWeek = null;
  for (const week of sortedWeeks) {
    const allHave = ALL_PACKAGES.every(pkg =>
      allData[pkg].some(row => row.week_date === week)
    );
    if (allHave) {
      baseWeek = week;
      break;
    }
  }

  if (!baseWeek) {
    logger.error('Could not find a base week where all packages have data');
    process.exit(1);
  }
  logger.info(`Base week (base=100): ${baseWeek}`);

  // Get base values for each package
  const baseValues = {};
  for (const pkg of ALL_PACKAGES) {
    const baseRow = allData[pkg].find(row => row.week_date === baseWeek);
    baseValues[pkg] = baseRow.value;
    logger.info(`  ${pkg} base value: ${baseValues[pkg].toLocaleString()}`);
  }

  // Build normalized time series for each package
  // normalized_value[pkg][week] = value / baseValue * 100
  const normalizedData = {};
  for (const pkg of ALL_PACKAGES) {
    normalizedData[pkg] = {};
    for (const row of allData[pkg]) {
      normalizedData[pkg][row.week_date] = (row.value / baseValues[pkg]) * 100;
    }
  }

  // Get all weeks where ALL packages have data (aligned weeks)
  const alignedWeeks = sortedWeeks.filter(week =>
    ALL_PACKAGES.every(pkg => normalizedData[pkg].hasOwnProperty(week))
  );
  logger.info(`Aligned weeks (all packages have data): ${alignedWeeks.length}`);

  if (alignedWeeks.length < 2) {
    logger.error('Not enough aligned weeks to calculate index');
    process.exit(1);
  }

  // Calculate sub-indices and composite index for each aligned week
  const results = [];
  
  for (const week of alignedWeeks) {
    // Geometric mean for AI SDK sub-index
    const aiSdkNorm = AI_SDK_PACKAGES.map(pkg => normalizedData[pkg][week]);
    const aiSdkGeoMean = Math.pow(aiSdkNorm.reduce((a, b) => a * b, 1), 1 / aiSdkNorm.length);

    // Geometric mean for Enterprise Tools sub-index
    const entNorm = ENTERPRISE_PACKAGES.map(pkg => normalizedData[pkg][week]);
    const entGeoMean = Math.pow(entNorm.reduce((a, b) => a * b, 1), 1 / entNorm.length);

    // Weighted composite: 60% AI SDK, 40% Enterprise Tools
    const composite = Math.pow(aiSdkGeoMean, 0.6) * Math.pow(entGeoMean, 0.4);

    // Get raw values for metadata（按 week_date 匹配：week 是 end_date+1 的周一锚点，
    // 原先用 start_date 匹配会命中下一周，导致 metadata 原始值整体错位一周）
    const rawValues = {};
    for (const pkg of ALL_PACKAGES) {
      const row = allData[pkg].find(r => r.week_date === week);
      rawValues[pkg] = row ? row.value : null;
    }

    // Find previous week for WoW calculation (by week_date)
    const weekIdx = alignedWeeks.indexOf(week);
    const prevWeek = weekIdx > 0 ? alignedWeeks[weekIdx - 1] : null;

    // Find same-week-last-month for MoM (approx: 4 weeks back)
    const monthIdx = alignedWeeks.indexOf(week) - 4;
    const momWeek = monthIdx >= 0 ? alignedWeeks[monthIdx] : null;

    results.push({
      week_date: week,
      week,  // preserve original start_date for debugging
      ai_sdk_sub: aiSdkGeoMean,
      enterprise_sub: entGeoMean,
      composite,
      rawValues,
      prevWeek,
      momWeek
    });
  }

  logger.info(`Calculated ${results.length} weekly index values`);
  
  // Print last few weeks
  logger.info('\nLast 5 weeks:');
  for (const r of results.slice(-5)) {
    logger.info(`  ${r.week_date} (npm end ${r.week}): EAPI=${r.composite.toFixed(2)} | AI_SDK=${r.ai_sdk_sub.toFixed(2)} | ENT=${r.enterprise_sub.toFixed(2)}`);
  }

  // Prepare growth_metrics records
  // For each result week, write 3 records (composite + 2 sub-indices)
  const todayStr = new Date().toISOString().split('T')[0];
  
  const records = [];
  
  for (const r of results) {
    // Lookup previous week values for WoW
    let wowComposite = null, wowAiSdk = null, wowEnt = null;
    let momComposite = null;

    if (r.prevWeek) {
      const prev = results.find(x => x.week_date === r.prevWeek);
      if (prev) {
        wowComposite = (r.composite - prev.composite) / prev.composite;
        wowAiSdk = (r.ai_sdk_sub - prev.ai_sdk_sub) / prev.ai_sdk_sub;
        wowEnt = (r.enterprise_sub - prev.enterprise_sub) / prev.enterprise_sub;
      }
    }

    if (r.momWeek) {
      const mom = results.find(x => x.week_date === r.momWeek);
      if (mom) {
        momComposite = (r.composite - mom.composite) / mom.composite;
      }
    }

    // Composite index record — use week_date (Monday after end_date)
    records.push({
      date: r.week_date,
      entity_type: 'aggregate',
      entity_name: 'enterprise_ai',
      metric_name: 'enterprise_ai_penetration_index',
      value: parseFloat(r.composite.toFixed(4)),
      metadata: {
        base_week: baseWeek,
        wow_pct: wowComposite !== null ? parseFloat(wowComposite.toFixed(4)) : null,
        mom_pct: momComposite !== null ? parseFloat(momComposite.toFixed(4)) : null,
        ai_sdk_sub_index: parseFloat(r.ai_sdk_sub.toFixed(4)),
        enterprise_sub_index: parseFloat(r.enterprise_sub.toFixed(4)),
        raw_values: r.rawValues,
        npm_end_date: r.week,
        calculated_at: todayStr
      }
    });

    // AI SDK sub-index record
    records.push({
      date: r.week_date,
      entity_type: 'aggregate',
      entity_name: 'enterprise_ai',
      metric_name: 'enterprise_ai_sdk_sub_index',
      value: parseFloat(r.ai_sdk_sub.toFixed(4)),
      metadata: {
        base_week: baseWeek,
        packages: AI_SDK_PACKAGES.map(pkg => ({
          name: pkg,
          raw_value: r.rawValues[pkg],
          normalized: parseFloat(normalizedData[pkg][r.week_date].toFixed(4))
        })),
        wow_pct: wowAiSdk !== null ? parseFloat(wowAiSdk.toFixed(4)) : null,
        npm_end_date: r.week,
        calculated_at: todayStr
      }
    });

    // Enterprise tools sub-index record
    records.push({
      date: r.week_date,
      entity_type: 'aggregate',
      entity_name: 'enterprise_ai',
      metric_name: 'enterprise_tools_sub_index',
      value: parseFloat(r.enterprise_sub.toFixed(4)),
      metadata: {
        base_week: baseWeek,
        packages: ENTERPRISE_PACKAGES.map(pkg => ({
          name: pkg,
          raw_value: r.rawValues[pkg],
          normalized: parseFloat(normalizedData[pkg][r.week_date].toFixed(4))
        })),
        wow_pct: wowEnt !== null ? parseFloat(wowEnt.toFixed(4)) : null,
        npm_end_date: r.week,
        calculated_at: todayStr
      }
    });
  }

  // 按 --start/--end 过滤写入范围
  let filteredRecords = records;
  if (startDate || endDate) {
    filteredRecords = records.filter(r => {
      if (startDate && r.date < startDate) return false;
      if (endDate && r.date > endDate) return false;
      return true;
    });
    logger.info(`Filtered to ${filteredRecords.length}/${records.length} records in range`);
  }

  logger.info(`\nUpserting ${filteredRecords.length} records to growth_metrics...`);
  try {
    const written = await upsertGrowthMetrics(filteredRecords);
    
    // Report latest week stats
    const latest = results[results.length - 1];
    const prev = results.length > 1 ? results[results.length - 2] : null;
    
    let msg = `✅ EAPI 计算完成\n`;
    msg += `最新周: ${latest.week_date} (npm end ${latest.week})\n`;
    msg += `综合指数: ${latest.composite.toFixed(2)}`;
    if (prev) {
      const wow = (latest.composite - prev.composite) / prev.composite;
      msg += ` (wow: ${(wow*100).toFixed(1)}%)`;
    }
    msg += `\nAI SDK子指数: ${latest.ai_sdk_sub.toFixed(2)}`;
    msg += `\n企业工具子指数: ${latest.enterprise_sub.toFixed(2)}`;
    
    logger.info(msg);
    feishuSend('EAPI Weekly Update', msg);
    
  } catch (e) {
    logger.error('Upsert failed:', e.message);
    feishuSend('EAPI Calculation', `❌ 写入失败: ${e.message}`);
    process.exit(1);
  }

  logger.info('Done!');
}

main().catch(err => { logger.error('Script failed:', err); process.exit(1); });
