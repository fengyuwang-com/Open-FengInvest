import { Router, Request, Response } from 'express';
import path from 'path';
import fs from 'fs';
import { FileStore, Holding, DashboardData, JournalEntry } from '../services/file-store';
import { PythonRunner } from '../services/python-runner';
import { JobQueue } from '../services/job-queue';

export function createApiRoutes(store: FileStore, runner: PythonRunner, queue?: JobQueue): Router {
  const router = Router();

  /**
   * 失败统一契约：非 2xx 状态码 + { error, detail }。
   * 之前失败也返回 200，前端 res.ok === true 会把错误静默吞掉。
   */
  const fail = (res: Response, error: string, detail?: string, status: number = 502) =>
    res.status(status).json({ error, detail: detail || error });

  // ----- Dashboard -----

  router.get('/dashboard', (_req: Request, res: Response) => {
    const data = store.getDashboard();
    res.json(data);
  });

  // ----- Market Data -----

  // fail-loud（2026-09-13 有声失败审计 P1）：/market 的后台采集器失败不再空吞——
  // 记入 pendingNote，console.error 有声 + 透传进下一次 pending 响应的 collect_error
  let marketPendingNote: string | null = null;

  router.get('/market', async (_req: Request, res: Response) => {
    const fs = require('fs');
    const marketDir = path.join(store['baseDir'], 'research', 'market');

    // Always serve cached data first
    const marketFile = path.join(marketDir, 'latest.json');
    if (fs.existsSync(marketFile)) {
      try {
        const data = JSON.parse(fs.readFileSync(marketFile, 'utf-8'));
        marketPendingNote = null;
        return res.json({ ...data, _source: 'cache', _date: fs.statSync(marketFile).mtime.toISOString() });
      } catch (e: any) {
        // 缓存坏了不是致命，但 fall through 到采集器的原因要记下来
        marketPendingNote = 'latest.json 解析失败: ' + String(e?.message ?? e).slice(0, 160);
        console.error('[market] cache 解析失败，转后台采集:', marketPendingNote);
      }
    }

    // No cache: run collector in background, return immediately with empty
    runner.runTool('fengmarket.py', ['collect'])
      .then(() => { marketPendingNote = null; })
      .catch((e: any) => {
        marketPendingNote = '采集器后台运行失败: ' + String(e?.message ?? e).slice(0, 160);
        console.error('[market] fengmarket collect 后台采集失败:', marketPendingNote);
      });
    res.json({ _source: 'pending', message: 'Data collection in progress, try again in 30s',
               ...(marketPendingNote ? { collect_error: marketPendingNote } : {}) });
  });

  // ----- Market Overview (live indices；Futu 已退出数据工作流，源=腾讯+Yahoo) -----

  let _marketCache: { data: any; ts: number } | null = null;
  const MARKET_CACHE_TTL_MS = 60_000; // 60s: 大盘速览不频繁变动, 避免每次刷都慢连 Yahoo

  // 路径名保留 futu-overview（前端/体检脚本依赖），数据源已换腾讯+Yahoo，无 Futu 依赖
  router.get('/market/futu-overview', async (_req: Request, res: Response) => {
    // Serve short-lived cache first so page refreshes are instant.
    if (_marketCache && Date.now() - _marketCache.ts < MARKET_CACHE_TTL_MS) {
      return res.json({ ..._marketCache.data, _source: 'cache' });
    }
    // 指数代码（腾讯行情 hkHSI/hkHSTECH；美股 SPY/QQQ 走 Yahoo）
    const indices = ['hkHSI', 'hkHSTECH', 'SPY', 'QQQ'];
    const promises = indices.map(code => runner.runTool('fengdata.py', [code, '--mode', 'price']));
    const results = await Promise.all(promises);
    const data: Record<string, any> = {};
    const labels: Record<string, string> = {
      'hkHSI': '恒生指数', 'hkHSTECH': '恒生科技',
      'SPY': 'S&P 500 (SPY)', 'QQQ': 'Nasdaq 100',
    };
    for (let i = 0; i < indices.length; i++) {
      const r = results[i];
      if (r.success && r.data?.price) {
        const p = r.data.price;
        data[indices[i]] = {
          name: labels[indices[i]],
          price: p.price, change_pct: p.change_pct,
          ma50: p.ma50, ma200: p.ma200,
        };
      }
    }
    const payload = { indices: data, fetched_at: new Date().toISOString() };
    _marketCache = { data: payload, ts: Date.now() };
    res.json(payload);
  });

  // ----- Comprehensive Market Data (value investing dashboard) -----

  router.get('/market/comprehensive', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengmarketdata.py', []);
    if (result.success && result.data) {
      // 宪法 3.2/3.4：陈旧度阈值 24h，超龄打 _stale 标
      const snap = path.join(store['baseDir'], 'research', 'market', 'latest.json');
      let ageH: number | null = null;
      try { ageH = (Date.now() - fs.statSync(snap).mtimeMs) / 3600000; } catch { /* 无快照 */ }
      return res.json({ ...result.data, _stale: ageH == null || ageH > 24, _age_hours: ageH == null ? null : Math.round(ageH) });
    }
    return fail(res, '综合市场数据获取失败', result.error || 'fengmarketdata.py 未返回数据');
  });

  // ----- FX (汇率卡片：fengfx.py 纯本地库，零网络) -----

  router.get('/fx/latest', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengfx.py', ['latest']);
    if (result.success && result.data) return res.json(result.data);
    return fail(res, '汇率数据获取失败', result.error || 'fengfx.py latest 未返回数据');
  });

  // ----- Sector Rotation (板块轮动) -----

  router.get('/sector/rotation', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengsector.py', ['analyze', '--json']);
    if (result.success && result.data) return res.json(result.data);
    return fail(res, '板块轮动分析失败', result.error || 'fengsector.py analyze 未返回数据');
  });

  router.get('/sector/longterm', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengsector.py', ['longterm', '--json']);
    if (result.success && result.data) return res.json(result.data);
    return fail(res, '板块长期分析失败', result.error || 'fengsector.py longterm 未返回数据');
  });

  // ----- Stock Quick Data (腾讯/Yahoo 多源；Futu 已退出数据工作流) -----

  router.get('/stock-quick/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    // Live fetch via fengdata.py (腾讯 qt.gtimg.cn 优先, Yahoo chart HTTP / yfinance 兜底)
    const result = await runner.runTool('fengdata.py', [ticker, '--mode', 'price', '--backend=auto']);
    if (result.success && result.data?.price) {
      const p = result.data.price;
      const f = result.data.financials || {};
      const ds = result.data.data_sources || [];
      return res.json({
        source: ds[0]?.source || 'yahoo/tencent', ticker,
        price: p.price, ma50: p.ma50, ma120: p.ma120, ma200: p.ma200,
        return_1m_pct: p.return_1m_pct, return_ytd_pct: p.return_ytd_pct,
        change_pct: p.change_pct, volume: p.volume,
        trailing_pe: f.trailing_pe, pb: f.pb, market_cap: f.market_cap,
        high_52w: p.high_52w, low_52w: p.low_52w,
      });
    }
    // 兜底：行情源（腾讯/Yahoo/yfinance）失败时读本地日线库，给降级但诚实的快照（标注 as_of 与来源）
    const dbPath = path.join(store['baseDir'], 'data', 'market_data.db');
    const fbCode = [
      'import sqlite3, json, sys',
      `conn = sqlite3.connect(r"${dbPath}")`,
      `row = conn.execute("SELECT id FROM indices WHERE ticker = ?", ("${ticker}",)).fetchone()`,
      'if not row: print(json.dumps({"error": "not_in_db"})); sys.exit(0)',
      'rows = conn.execute("SELECT date, close, volume FROM daily_data WHERE index_id = ? AND close IS NOT NULL ORDER BY date DESC LIMIT 260", (row[0],)).fetchall()',
      'if len(rows) < 2: print(json.dumps({"error": "insufficient"})); sys.exit(0)',
      'closes = [r[1] for r in rows]',
      'ma = lambda n: round(sum(closes[:n]) / n, 4) if len(closes) >= n else None',
      'prev = closes[1]',
      'print(json.dumps({',
      '  "as_of": rows[0][0], "price": closes[0],',
      '  "change_pct": round((closes[0] - prev) / prev * 100, 2) if prev else None,',
      '  "ma50": ma(50), "ma120": ma(120), "ma200": ma(200),',
      '  "volume": rows[0][2],',
      '  "high_52w": max(closes), "low_52w": min(closes),',
      '}))',
    ].join('\n');
    const fb = await runner.runCode(fbCode);
    if (fb.success && fb.stdout) {
      try {
        const d = JSON.parse(fb.stdout.trim());
        if (!d.error) {
          return res.json({ source: 'db-fallback', as_of: d.as_of, ticker,
            price: d.price, ma50: d.ma50, ma120: d.ma120, ma200: d.ma200,
            change_pct: d.change_pct, volume: d.volume,
            high_52w: d.high_52w, low_52w: d.low_52w,
            note: '实时源不可用，以下为本地库最近收盘降级快照' });
        }
      } catch { /* 兜底解析失败，走 502 */ }
    }
    return res.status(502).json({
      error: '个股行情获取失败',
      detail: result.error || 'fengdata.py 未返回 price 数据',
      ticker,
    });
  });

  // ----- Extended Data Modes（原 Futu Data Modes；Futu 退出后 fengdata 对无替代源的模式返回明确停用错误，API 层 fail() 透传）-----

  router.get('/stock/valuation/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'valuation']);
    if (result.success && result.data) return res.json(result.data);
    return fail(res, '估值数据获取失败', result.error || 'No valuation data');
  });

  router.get('/stock/shareholders/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'shareholders']);
    if (result.success && result.data) return res.json(result.data);
    return fail(res, '股东数据获取失败', result.error || 'No shareholder data');
  });

  router.get('/stock/analysts/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'analysts']);
    if (result.success && result.data) return res.json(result.data);
    return fail(res, '分析师数据获取失败', result.error || 'No analyst data');
  });

  router.get('/stock/profile/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'profile']);
    if (result.success && result.data) return res.json(result.data);
    return fail(res, '公司概况获取失败', result.error || 'No profile data');
  });

  // ----- Holdings -----

  router.get('/holdings', (_req: Request, res: Response) => {
    const holdings = store.getHoldings();
    res.json(holdings);
  });

  router.get('/holdings/:ticker', (req: Request, res: Response) => {
    const holding = store.getHolding(req.params.ticker);
    if (!holding) return res.status(404).json({ error: 'Holding not found' });
    res.json(holding);
  });

  router.post('/holdings', (req: Request, res: Response) => {
    const holding = req.body as Holding;
    const hid = holding.id || holding.ticker;
    if (!hid) return res.status(400).json({ error: 'ticker or id required' });
    store.saveHolding(holding);
    res.json({ success: true, id: hid });
  });

  // ----- Research -----

  router.get('/research', (_req: Request, res: Response) => {
    const meta = store.getResearchMeta();
    res.json(meta);
  });

  router.get('/research/:ticker', (req: Request, res: Response) => {
    const layers = store.getResearchLayers(req.params.ticker);
    res.json(layers);
  });

  // ----- 决策台任务行：研究清单 + 七层进度 → "现在轮到谁" -----

  router.get('/workspace/tasks', (_req: Request, res: Response) => {
    const fsx = require('fs');
    const ORDER = ['l0', 'm', 'l1', 'l2b', 'l2a', 'l3', 'l4'];
    const LABEL: Record<string, string> = {
      l0: '看懂这家公司（L0 能力圈）', m: '市场与数据（M）', l1: '硬纪律过闸（L1）',
      l2b: '量化因子（L2b）', l2a: '定性研究（L2a）', l3: '正反碰撞（L3）', l4: '写决策报告（L4）',
    };
    const meta = store.getResearchMeta();
    const doneMap = new Map<string, Set<string>>();
    for (const m of meta) doneMap.set(m.ticker.toUpperCase(), new Set(m.layers.map((l: any) => l.layer)));
    let list: any[] = [];
    try {
      list = JSON.parse(fsx.readFileSync(path.join(store['baseDir'], 'data', 'config', 'research_list.json'), 'utf-8')).companies || [];
    } catch { /* 清单缺失则只给进行中任务 */ }
    const nameOf = (tk: string): string => {
      const c = list.find((x: any) => x.ticker === tk);
      const m = meta.find((x) => x.ticker === tk);
      return (c && (c.name_cn || c.name)) || (m && m.name && !m.name.includes(tk) ? m.name : '') || tk;
    };
    const tasks: any[] = [];
    // 1) 进行中：已有层但未满七层 → 继续研究
    for (const m of meta) {
      const done = doneMap.get(m.ticker.toUpperCase()) || new Set<string>();
      if (done.size >= 7) continue;
      const next = ORDER.find((k) => !done.has(k)) || null;
      tasks.push({ ticker: m.ticker, name: nameOf(m.ticker), kind: 'continue', layers_done: done.size, next_layer: next, next_label: next ? LABEL[next] : '收尾' });
    }
    // 2) 候选：research_list 里 candidate/researching 但还没开层 → 从 L0 开始
    for (const c of list) {
      if (!['candidate', 'researching'].includes(c.status)) continue;
      const doneSet = doneMap.get(String(c.ticker).toUpperCase());
      if (doneSet && doneSet.size > 0) continue;
      tasks.push({ ticker: c.ticker, name: nameOf(c.ticker), kind: 'start', layers_done: 0, next_layer: 'l0', next_label: LABEL.l0 });
    }
    tasks.sort((a, b) => (a.kind === b.kind ? b.layers_done - a.layers_done : a.kind === 'continue' ? -1 : 1));
    res.json({ tasks });
  });

  // ----- 公司速览（宪法 6.3：估值分位；A股走 fengastock，港美股回退 M 层快照） -----

// 进程内 TTL 缓存：日线低频哲学下，重活端点（实时取数/估值分位）短缓存即可，
// 重复轮询不重算；命中返回 { _cached: true, cached_at }
const ttlCache = new Map<string, { at: number; body: unknown }>();
async function withTtlCache(key: string, ttlMs: number, fn: () => Promise<unknown>): Promise<unknown> {
  const hit = ttlCache.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return { ...(hit.body as object), _cached: true, cached_at: new Date(hit.at).toISOString() };
  const body = await fn();
  ttlCache.set(key, { at: Date.now(), body });
  return body;
}

router.get('/company/:ticker', async (req: Request, res: Response) => {
  const { ticker } = req.params;
  try {
    const data = await withTtlCache(`company:${ticker}`, 10 * 60 * 1000, async () => {
      const isA = /\.(SH|SS|SZ|BJ)$/i.test(ticker);
      if (isA) {
        const code = ticker.replace(/\.(SS|SH)$/i, '.SH').replace(/\.SZ$/i, '.SZ');
        // quote 与 valuation-hist 并行：冷跑串行 ~2.9s 贴 3s warn 阈值，并行 ~1.7s 防 D1 闪烁
        const [q, vh] = await Promise.all([
          runner.runTool('fengastock.py', ['quote', code], 30000),
          runner.runTool('fengastock.py', ['valuation-hist', code, '--metric', 'pe,pb'], 90000).catch(() => ({ success: false, stdout: '' })),
        ]);
        if (q.success) {
          const quoteData = JSON.parse(q.stdout || '{}');
          const first = Object.values(quoteData.quotes || {})[0] as any;
          let pct = null as any;
          if (vh.success) {
            try {
              const stats = JSON.parse(vh.stdout || '{}').metrics_stats || {};
              const norm = (v: any) => (v == null ? null : (v > 1 ? v / 100 : v)); // fengastock 分位口径偶有 0-100，统一归一
              pct = {
                pe: norm(stats.peTTM?.latest_percentile),
                pb: norm(stats.pbMRQ?.latest_percentile),
                window: '2016 至今',
              };
            } catch { /* 分位缺省 */ }
          }
          if (first) return {
            ticker, name: (first.name || '').replace(/\s+/g, ''),
            price: first.price, change_pct: first.change_pct,
            pe_ttm: first.pe_ttm, pb: first.pb, mcap_yi: first.mcap_yi,
            pe_percentile: pct, stale: !!first.is_stale, source: quoteData.source, as_of: quoteData.as_of,
          };
        }
      }
      // 港美股/降级：读最新日期目录的 02-market.json
      const companiesDir = path.join(store['baseDir'], 'research', '060-companies');
      let found: string | null = null;
      for (const e of fs.readdirSync(companiesDir)) {
        if (new RegExp(`^${ticker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}-`).test(e) || e.startsWith(`${ticker}-`)) { found = path.join(companiesDir, e); break; }
      }
      if (!found) throw new Error('公司目录未找到');
      const dates = fs.readdirSync(found).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d)).sort();
      if (!dates.length) throw new Error('无日期目录');
      const mfile = path.join(found, dates[dates.length - 1], '02-market.json');
      if (!fs.existsSync(mfile)) throw new Error('M 层数据未找到');
      const m = JSON.parse(fs.readFileSync(mfile, 'utf-8'));
      const f = m.financials || {};
      return {
        ticker, name: m.name || ticker,
        price: m.price_data?.price ?? null, currency: m.price_data?.currency || null,
        change_pct: m.price_data?.change_pct ?? null,
        pe_ttm: f.trailing_pe ?? null, pb: f.pb ?? null,
        pe_percentile: null, stale: true,
        source: `M 层快照 ${dates[dates.length - 1]}（${m.price_data?.source || '无来源'}）`,
        as_of: dates[dates.length - 1],
      };
    });
    return res.json(data);
  } catch (err: any) {
    return fail(res, '公司速览取数失败', err?.message || String(err));
  }
});

  // ----- 自主进化看板（MISSION DoD / 复测台账 / 策略卡 / 数据新鲜度 / FENGMEM 时间线） -----

  router.get('/mission/overview', async (_req: Request, res: Response) => {
    const base = store['baseDir'];
    const read = (p: string) => { try { return fs.readFileSync(path.join(base, p), 'utf-8'); } catch { return ''; } };
    // 1) MISSION.md DoD 勾选状态
    let mission: any = { goal: '', dod: [] as any[], redlines: [] as string[] };
    try {
      const md = read('MISSION.md');
      mission.goal = (md.match(/^## 总目标\s*\n+([\s\S]*?)(?=\n## )/) || [])[1]?.trim() || '';
      for (const m of md.matchAll(/^- \[( |x)\] (D\d[^\n]+)$/gim)) mission.dod.push({ id: m[2].slice(0, 2), text: m[2], done: m[1].toLowerCase() === 'x' });
      const rl = md.match(/## 禁止事项[^\n]*\n([\s\S]*?)(?=\n## |$)/);
      if (rl) mission.redlines = rl[1].split('\n').map((s: string) => s.replace(/^[-*]\s*/, '').trim()).filter(Boolean);
    } catch { /* 无 MISSION */ }
    // 2) 复测台账统计（000-CONCLUSIONS.md）
    let claims: any = { total: 52, settled: 0, ok: 0, no: 0, cond: 0, nodata: 0 };
    try {
      const c = read(path.join('research', '110-strategy-verification', '000-CONCLUSIONS.md'));
      // 只统计论断行（表格行以 | 编号 | 开头），避免正文中符号污染计数
      const rows = c.split('\n').filter((l) => /^\|\s*\d+\s*\|/.test(l));
      claims.ok = rows.filter((l) => l.includes('✅')).length;
      claims.no = rows.filter((l) => l.includes('❌')).length;
      claims.cond = rows.filter((l) => l.includes('🟡')).length;
      claims.nodata = (c.match(/数据不可得.*?(\d+)\s*条/) || [])[1] ? parseInt((c.match(/数据不可得.*?(\d+)\s*条/) || [])[1]) : 24;
      claims.settled = rows.length;
    } catch { /* 无台账 */ }
    // 3) 策略卡
    let strategy: any = { cards: [] as string[] };
    try {
      strategy.cards = fs.readdirSync(path.join(base, 'knowledge', 'strategy'))
        .filter((f) => f.endsWith('.md') && f !== 'README.md');
    } catch { /* 无策略库 */ }
    // 4) 数据新鲜度 + 工具链冒烟体检（python 只读探针）
    let freshness: any = null;
    let toolHealth: any = null;
    try {
      const r = await runner.runTool('fengmission.py', [], 20000);
      if (r.success) {
        const j = JSON.parse(r.stdout || '{}');
        freshness = j.freshness || null;
        toolHealth = j.tool_health || null;
      }
    } catch { /* 探针失败不挡页面 */ }
    // 5) FENGMEM 最近轮次（隐私文件只在本机 GUI 展示）
    let rounds: any[] = [];
    try {
      const mem = read('FENGMEM.md');
      const blocks = mem.split(/\n(?=## \d{4}-)/).slice(-9, -1);
      for (const b of blocks) {
        const head = (b.match(/^## (.+)$/m) || [])[1] || '';
        const get = (k: string) => {
          const m = b.match(new RegExp(`- ${k}: ?([\\s\\S]*?)(?=\\n- [^ ]|\\n$)`));
          return (m ? m[1] : '').trim();
        };
        rounds.push({ head, ask: get('用户要求'), act: get('AI 行动'), out: get('产出') });
      }
      rounds.reverse();
    } catch { /* 无台账 */ }
    // 6) todo 概览（本机隐私文件）
    let todo: any = { open: 0, blocked: 0, items: [] as any[] };
    try {
      const t = read('todo.md');
      const todoSec = t.split(/^## /m).find((s) => s.startsWith('待办'));
      if (todoSec) {
        for (const m of todoSec.matchAll(/^- \[ \] (.+)$/gm)) {
          todo.open++;
          const isBlocked = /待拍板|阻塞|等 /.test(m[1]);
          if (isBlocked) todo.blocked++;
          todo.items.push({ text: m[1].slice(0, 80), blocked: isBlocked });
        }
      }
    } catch { /* 无 todo */ }
    // 7) 开源调研落盘
    let evals: string[] = [];
    try {
      evals = fs.readdirSync(path.join(base, 'research', 'opensource-eval')).filter((f) => f.endsWith('.md'));
    } catch { /* 无目录 */ }
    res.json({ mission, claims, strategy, freshness, toolHealth, rounds, todo, evals });
  });

  // 手动触发冒烟探针（董事长在看板点一次=全链真跑；日常由 server 定时跑）
  router.post('/mission/probe', async (_req: Request, res: Response) => {
    try {
      const r = await runner.runTool('fengprobe.py', ['--json'], 900000);
      let report: any = null;
      try { report = r.stdout ? JSON.parse(r.stdout) : null; } catch { report = null; }
      res.json({ ok: !!report, exit: r.success ? 0 : 1, report, error: r.success ? undefined : r.error });
    } catch (err: any) {
      res.status(500).json({ ok: false, error: err?.message || String(err) });
    }
  });

  // ----- 系统页（宪法 6.18：状态机总览 + DB 更新进度 + 环境检查） -----

  router.get('/system/status', async (_req: Request, res: Response) => {
    const base = store['baseDir'];
    // 1) 状态机总览
    const stateDir = path.join(base, 'research', 'state');
    const states: any[] = [];
    try {
      for (const f of fs.readdirSync(stateDir)) {
        if (!/^temp_state_.*\.json$/.test(f)) continue;
        try {
          const d = JSON.parse(fs.readFileSync(path.join(stateDir, f), 'utf-8'));
          const done = Object.keys(d.completed || {}).filter((k: string) => /^(0[1-8]-|l[0-4]|m$|market$)/.test(k));
          states.push({
            ticker: d.ticker, status: d.status,
            layers_done: Math.min(8, new Set(done.map((k: string) => k.replace(/^l/, '0').slice(0, 2))).size),
            total: 8, updated_at: d.updated_at || null,
          });
        } catch { /* 跳过坏文件 */ }
      }
    } catch { /* 目录缺失 */ }
    // 2) DB 更新进度
    let db: any = null;
    const dbFile = path.join(base, 'data', 'market_data.db');
    try {
      const st = fs.statSync(dbFile);
      const ageDays = (Date.now() - st.mtimeMs) / 86400000;
      let fuyaoDone = null as number | null;
      try {
        const fp = JSON.parse(fs.readFileSync(path.join(base, 'data', 'cache', 'fuyao_progress.json'), 'utf-8'));
        fuyaoDone = (fp.done || []).length;
      } catch { /* 无进度文件 */ }
      db = { size_gb: st.size / 1073741824, mtime: st.mtime.toISOString(), age_days: ageDays, stale: ageDays > 7, fuyao_done: fuyaoDone };
    } catch { /* 无 DB */ }
    // 3) 环境检查
    const pyVersion = await runner.version();
    res.json({
      states: states.sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || '')),
      db,
      env: { python: pyVersion, server_uptime_s: Math.round(process.uptime()) },
    });
  });

  // ----- 纪律执行账本（信条 7：执行 > 判断——把"说到做到"变成一面镜子） -----

  router.get('/discipline/ledger', (_req: Request, res: Response) => {
    const base = store['baseDir'];
    const holdings = store.getHoldings() as any[];
    const real = holdings.filter((h) => h.asset_type !== 'cash');

    // 1) 论文齐备率：无 thesis.original + redlines 的持仓 = 黄灯（处置效应温床）
    const thesisOk = real.filter((h) => h.thesis && h.thesis.original && ((h.thesis.redlines || h.thesis.exit_conditions || []).length > 0));
    const thesisMissing = real.filter((h) => !(h.thesis && h.thesis.original && ((h.thesis.redlines || h.thesis.exit_conditions || []).length > 0)))
      .map((h) => ({ ticker: h.ticker || h.id, name: h.name }));

    // 2) 复盘守时：回顾日过期 = 拖欠
    const now = Date.now();
    const reviewOverdue = real.filter((h) => h.triggers && h.triggers.next_review_date && new Date(h.triggers.next_review_date).getTime() < now)
      .map((h) => ({ ticker: h.ticker || h.id, name: h.name, date: h.triggers.next_review_date,
        days: Math.round((now - new Date(h.triggers.next_review_date).getTime()) / 86400000) }));

    // 3) 分析烂尾：状态机文件 30 天未动且未走完 = 烂尾（L0 不懂合法 skip 不算）
    const stateDir = path.join(base, 'research', 'state');
    const states: any[] = [];
    try {
      for (const f of fs.readdirSync(stateDir)) {
        if (!/^temp_state_.*\.json$/.test(f)) continue;
        try {
          const d = JSON.parse(fs.readFileSync(path.join(stateDir, f), 'utf-8'));
          const done = Object.keys(d.completed || {}).filter((k: string) => /^(0[1-8]-|l[0-4]|m$|market$)/.test(k));
          const layers = Math.min(8, new Set(done.map((k: string) => k.replace(/^l/, '0').slice(0, 2))).size);
          const skipped = d.status === 'skipped' || d.skip_reason;
          const ageDays = (now - new Date(d.updated_at || 0).getTime()) / 86400000;
          states.push({ ticker: d.ticker, layers, skipped, age_days: Math.round(ageDays), abandoned: layers > 0 && layers < 8 && !skipped && ageDays > 30 });
        } catch { /* 跳过坏文件 */ }
      }
    } catch { /* 目录缺失 */ }
    const abandoned = states.filter((s) => s.abandoned);

    // 4) 监控出勤：journal 里 daily_check 的日期分布（30 天窗口）
    const checks: string[] = [];
    const redLog: any[] = [];
    const redCurrent: any[] = [];
    try {
      const lines = fs.readFileSync(path.join(base, 'logs', 'journal.jsonl'), 'utf-8').split('\n').filter(Boolean);
      const latestByTicker: Record<string, any> = {};
      for (const line of lines) {
        try {
          const e = JSON.parse(line);
          if (e.type === 'daily_check') {
            if (e.date && !checks.includes(e.date)) checks.push(e.date);
            const det = e.details || {};
            for (const tk of Object.keys(det)) {
              if (String(det[tk]).toUpperCase().includes('RED')) redLog.push({ date: e.date, ticker: tk });
              latestByTicker[tk] = { ticker: tk, light: det[tk], date: e.date };
            }
          }
        } catch { /* 跳过坏行 */ }
      }
      for (const x of Object.values(latestByTicker) as any[]) {
        if (String(x.light).toUpperCase().includes('RED')) redCurrent.push(x);
      }    } catch { /* 无日志 */ }
    checks.sort();
    const last30 = checks.filter((d) => (now - new Date(d).getTime()) / 86400000 <= 30);
    // 最大断档天数
    let maxGap = 0;
    for (let i = 1; i < checks.length; i++) {
      const gap = Math.round((new Date(checks[i]).getTime() - new Date(checks[i - 1]).getTime()) / 86400000);
      if (gap > maxGap) maxGap = gap;
    }

    res.json({
      thesis_rate: real.length ? thesisOk.length / real.length : null,
      thesis_ok: thesisOk.length, thesis_total: real.length, thesis_missing: thesisMissing,
      review_overdue: reviewOverdue,
      states_total: states.length, states_abandoned: abandoned.map((s) => ({ ticker: s.ticker, layers: s.layers, age_days: s.age_days })),
      check_dates: checks, check_last30: last30.length, check_max_gap_days: maxGap,
      check_last_date: checks.length ? checks[checks.length - 1] : null,
      red_events_total: redLog.length,
      red_current: redCurrent,
      generated_at: new Date().toISOString(),
    });
  });

  // ----- Knowledge -----

  router.get('/knowledge', (_req: Request, res: Response) => {
    const tree = store.getKnowledgeTree();
    res.json(tree);
  });

  router.get('/knowledge/*', (req: Request, res: Response) => {
    const relPath: string = (req.params as any)['0'] || '';
    if (!relPath) return res.status(400).json({ error: 'path required' });
    const doc = store.getKnowledgeDoc(relPath);
    if (!doc) return res.status(404).json({ error: 'Document not found' });
    res.json(doc);
  });

  // ----- 组合三轴矩阵（宪法 6.15：市场×资金域，板块明细） -----

  router.get('/portfolio/matrix', (_req: Request, res: Response) => {
    const holdings = store.getHoldings().filter((h: any) => h.asset_type !== 'cash');
    const matrix: Record<string, any> = {};
    for (const h of holdings as any[]) {
      const m = h.market || 'UNKNOWN';
      matrix[m] = matrix[m] || { total: 0, zones: {} };
      const mv = h.position?.market_value ?? (h.position?.shares && h.position?.current_price ? h.position.shares * h.position.current_price : (h.position?.units && h.position?.nav ? h.position.units * h.position.nav : 0));
      matrix[m].total += mv;
      const z = h.capital_zone || 'UNKNOWN';
      matrix[m].zones[z] = matrix[m].zones[z] || { total: 0, segments: {} };
      matrix[m].zones[z].total += mv;
      const seg = h.segment || '未分类';
      matrix[m].zones[z].segments[seg] = (matrix[m].zones[z].segments[seg] || 0) + mv;
    }
    res.json({ matrix, holdings_count: holdings.length });
  });

  // ----- 投机钱包 fengtick 侧车（宪法 6.16：幽灵原则只读） -----

  router.get('/spec/t0', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengtick.py', ['t0']);
    if (!result.success) return fail(res, 'T0 候选获取失败', result.error || 'fengtick t0 失败');
    res.json(result.data ?? { raw: result.stdout });
  });

  router.get('/spec/t2/:ticker', async (req: Request, res: Response) => {
    // fengtick t2 要求 --file 本地 OHLCV（幽灵原则：数据纯本地，不联网）；
    // 从 market_data.db 导出日线 CSV 到 Temp/ 再喂给 fengtick。
    const ticker = (req.params.ticker || '').toUpperCase();
    if (!/^[A-Z0-9.]{1,20}$/.test(ticker)) return fail(res, 'T2 防线位获取失败', `非法 ticker: ${ticker}`, 400);
    const csvPath = path.join(store['baseDir'], 'Temp', `fengtick_t2_${ticker.replace(/\./g, '_')}_${Date.now()}.csv`);
    const dbPath = path.join(store['baseDir'], 'data', 'market_data.db');
    const exportCode = [
      'import sqlite3, sys',
      `conn = sqlite3.connect(r"${dbPath}")`,
      `row = conn.execute("SELECT id FROM indices WHERE ticker = ?", ("${ticker}",)).fetchone()`,
      'if not row:',
      '    print("TICKER_NOT_FOUND"); sys.exit(1)',
      'rows = conn.execute(',
      '    "SELECT date, open, high, low, close, volume FROM daily_data WHERE index_id = ? AND open IS NOT NULL ORDER BY date",',
      '    (row[0],)).fetchall()',
      'if len(rows) < 30:',
      '    print("INSUFFICIENT_DATA"); sys.exit(1)',
      `with open(r"${csvPath}", "w", encoding="utf-8", newline="") as f:`,
      '    f.write("date,open,high,low,close,volume\\n")',
      '    for r in rows:',
      '        f.write(",".join("" if v is None else str(v) for v in r) + "\\n")',
      'print("OK")',
    ].join('\n');
    const exported = await runner.runCode(exportCode);
    if (!exported.success) {
      const out = exported.stdout || '';
      const reason = out.includes('TICKER_NOT_FOUND') ? `${ticker} 不在本地库`
        : out.includes('INSUFFICIENT_DATA') ? `${ticker} 本地日线不足 30 根`
        : (exported.error || '导出失败');
      return fail(res, 'T2 防线位获取失败', reason);
    }
    const result = await runner.runTool('fengtick.py', ['t2', ticker, '--file', csvPath, '--json']);
    try { fs.unlinkSync(csvPath); } catch (_e) { /* 临时文件清理失败可忽略 */ }
    if (!result.success) return fail(res, 'T2 防线位获取失败', result.error || 'fengtick t2 失败');
    res.json(result.data ?? { raw: result.stdout });
  });

  // ----- 筛选流水线（宪法 6.13：fengbatch plan/status/summary） -----

  router.get('/screen/pipeline', (_req: Request, res: Response) => {
    const fs = require('fs');
    const batchDir = path.join(store['baseDir'], 'research', '070-reports', 'batch');
    const batches: any[] = [];
    if (fs.existsSync(batchDir)) {
      for (const b of fs.readdirSync(batchDir)) {
        const bd = path.join(batchDir, b);
        if (!fs.statSync(bd).isDirectory()) continue;
        const read = (f: string) => { try { const fp = path.join(bd, f); return fs.existsSync(fp) ? JSON.parse(fs.readFileSync(fp, 'utf-8')) : null; } catch { return { _invalid: true }; } };
        batches.push({ batch: b, meta: read('meta.json'), survivors: read('survivors.json'), summary: fs.existsSync(path.join(bd, 'summary.md')) ? fs.readFileSync(path.join(bd, 'summary.md'), 'utf-8').slice(0, 3000) : null });
      }
    }
    res.json({ lists: ['cn_dividend', 'us_quality', 'us_dividend'], batches });
  });

  router.post('/screen/pipeline', async (req: Request, res: Response) => {
    const listName = (req.body || {}).list_name || 'cn_dividend';
    const top = parseInt((req.body || {}).top, 10) || 50;
    // fengbatch plan = 粗筛→精筛→幸存者名单，实测约 9 分钟；走契约长超时
    const result = await runner.runTool('fengbatch.py', ['plan', '--list-name', listName, '--top', String(top)], 600000);
    if (!result.success) return fail(res, `筛选流水线失败: ${listName}`, result.error || 'fengbatch plan 失败');
    res.json(result.data ?? { raw: result.stdout });
  });

  // ----- 数据一键更新（宪法册三 3.3：202 job_id → 轮询进度） -----

  router.post('/data/update', (req: Request, res: Response) => {
    if (!queue) return res.status(501).json({ error: 'job 队列未启用' });
    const scope = (req.body || {}).scope || 'all';
    const job_id = queue.start(scope);
    res.status(202).json({ job_id, status: 'running' });
  });

  router.get('/data/last-update', (_req: Request, res: Response) => {
    if (!queue) return res.status(501).json({ error: 'job 队列未启用' });
    res.json({ last_update: queue.lastUpdate(), running: queue.isRunning() });
  });

  router.get('/data/update/:job_id', (req: Request, res: Response) => {
    if (!queue) return res.status(501).json({ error: 'job 队列未启用' });
    const job = queue.get(req.params.job_id);
    if (!job) return res.status(404).json({ error: 'job 不存在', detail: req.params.job_id });
    res.json(job);
  });

  // ----- Reports（宪法册五） -----

  router.get('/reports/:ticker', (req: Request, res: Response) => {
    const shelf = store.getReports(req.params.ticker);
    if (!shelf) return res.status(404).json({ error: '公司报告书架未找到', detail: req.params.ticker });
    res.json(shelf);
  });

  router.get('/report/:ticker/*', (req: Request, res: Response) => {
    const rel: string = (req.params as any)['0'] || '';
    if (!rel) return res.status(400).json({ error: '报告路径 required' });
    const doc = store.getReportDoc(req.params.ticker, rel);
    if (!doc) return res.status(404).json({ error: '报告未找到', detail: `${req.params.ticker}/${rel}` });
    res.json(doc);
  });

  // ----- Buy Register（宪法 6.7：四步登记，fengholding add 是真门） -----

  router.post('/holdings/:ticker/buy-register', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const h = req.body || {};
    if (!h.name || !h.position || !h.position.shares || !h.position.avg_cost) {
      return res.status(400).json({ error: '缺少必填字段', detail: 'name / position.shares / position.avg_cost 必填' });
    }
    const the = h.thesis || {};
    if (!the.original || !Array.isArray(the.redlines) || the.redlines.length === 0 || !Array.isArray(the.exit_conditions) || the.exit_conditions.length === 0) {
      return res.status(400).json({ error: '论文四段不完整', detail: '为什么买(original)/预期(expected)/何时会错(redlines)/卖出条件(exit_conditions) 全部必填' });
    }
    const holding = { ...h, id: ticker, ticker, asset_type: h.asset_type || 'stock', lifecycle_phase: 'holding', thesis: the };
    store.saveHolding(holding);
    const result = await runner.runTool('fengholding.py', ['add', ticker], 300000); // add 内含预算+相关性检查，可能跑几分钟
    if (!result.success) {
      return fail(res, `fengholding add 拒绝登记: ${ticker}`, result.error || 'SCHEMA/价格核对未通过', 400);
    }
    res.json({ success: true, ticker, report: result.data });
  });

  // ----- Prompt 生成器（宪法册七：生成→外部AI→贴回→fengstate complete 真门） -----
  // PROMPT-PLAN（2026-09-07 R37）：8 个状态层 + 4 个场景层（exit/discuss/translate/spec，修订2）
  const PROMPT_LAYERS: Record<string, string> = { '01-capability': 'L0 能力圈', 'm': 'M 市场数据', '03-discipline': 'L1 硬纪律', '04-quantitative': 'L2b 量化', '05-qualitative': 'L2a 定性', '06-collision': 'L3 碰撞', '07-report': 'L4 报告', 'review': '复盘', 'exit': '卖出自查', 'discuss': '讨论对手', 'translate': '白话翻译器', 'spec': '投机侧车解读' };
  // 场景层不进状态机（PROMPT-PLAN 修订1/2：贴回只存档渲染，推进状态机的只有八层）
  const PROMPT_SCENE_LAYERS = new Set(['exit', 'discuss', 'translate', 'spec']);

  // 分层轻验证：贴回 JSON 的最小必填顶层 key（浅检，只看顶层存在性+粗类型）。
  // 真门仍是 fengstate complete；这里只提前拦"贴错层/缺字段"的回贴，400 带 detail。
  // 注：05-qualitative(moat_rating)/review(thesis_valid) 按 PROMPT-PLAN 目标 schema 定；
  //     现有旧模板尚未输出这两个 key（模板重写待创始人过目），重写前这两层贴回会被拦。
  //     06-collision 按任务要求 challenges 数组；旧模板/fengstate 真门用 conflicts，二者兼容其一。
  type MinKeySpec = { key: string; type?: 'array' | 'number' | 'string'; alt?: string };
  const PROMPT_LAYER_MIN_KEYS: Record<string, MinKeySpec[]> = {
    '05-qualitative': [{ key: 'moat_rating' }],
    '06-collision': [{ key: 'challenges', type: 'array', alt: 'conflicts' }],
    'review': [{ key: 'thesis_valid' }],
    'exit': [{ key: 'reason_class' }, { key: 'bias_checks', type: 'array' }],
    'discuss': [{ key: 'stance' }, { key: 'rebuttal' }],
    'translate': [{ key: 'plain_explanation' }],
    'spec': [{ key: 'risk_verdict' }, { key: 'stop_loss' }],
  };
  const MIN_KEY_TYPE_LABEL: Record<string, string> = { array: '数组', number: '数字', string: '字符串' };
  const checkLayerMinKeys = (layer: string, data: any): string | null => {
    if (typeof data !== 'object' || data === null || Array.isArray(data)) {
      return '贴回内容必须是 JSON 对象（{...}），不能是数组/标量/null';
    }
    const specs = PROMPT_LAYER_MIN_KEYS[layer];
    if (!specs || !specs.length) return null; // 其余层：合法 JSON 对象即可
    const missing: string[] = [];
    for (const s of specs) {
      const suffix = s.type ? `（需为${MIN_KEY_TYPE_LABEL[s.type]}）` : '';
      const ok = (v: any) => s.type === 'array' ? Array.isArray(v) : s.type === 'number' ? typeof v === 'number' : s.type === 'string' ? typeof v === 'string' : v !== undefined;
      if (ok(data[s.key])) continue;
      if (s.alt && ok(data[s.alt])) continue;
      missing.push(`${s.key}${s.alt ? ` 或 ${s.alt}` : ''}${suffix}`);
    }
    return missing.length ? `缺少必填顶层 key: ${missing.join(', ')}` : null;
  };

  // 提取模板里 ```json fenced 的「输出 schema」块：取"标题行含 schema"之后的第一个 json fence；没有返回 null
  const extractOutputSchema = (tpl: string): string | null => {
    const heading = /^#{1,6}[^\n]*schema[^\n]*$/im.exec(tpl);
    if (!heading) return null;
    const fence = /```json[^\S\n]*\n?([\s\S]*?)```/i.exec(tpl.slice(heading.index + heading[0].length));
    return fence ? fence[1].trim() : null;
  };

  router.get('/prompt/templates', (_req: Request, res: Response) => {
    res.json({ layers: Object.entries(PROMPT_LAYERS).map(([id, label]) => ({ id, label, scene: PROMPT_SCENE_LAYERS.has(id) })) });
  });

  router.post('/prompt/generate', async (req: Request, res: Response) => {
    const { ticker, layer } = req.body || {};
    if (!ticker || !PROMPT_LAYERS[layer]) return res.status(400).json({ error: 'ticker 与合法 layer 必填', detail: `layer ∈ ${Object.keys(PROMPT_LAYERS).join(', ')}` });
    const fs = require('fs');
    const tplPath = path.join(__dirname, '..', '..', 'src', 'prompt-templates', `${layer}.md`);
    if (!fs.existsSync(tplPath)) return res.status(404).json({ error: '模板不存在', detail: tplPath });
    let tpl = fs.readFileSync(tplPath, 'utf-8');
    const list = store.getResearchList().find(c => c.ticker === ticker);
    const name = list?.name || ticker;
    // L3 碰撞：注入已有层证据摘要
    let evidence = '（无已存档层输出——先跑 M/L1/L2b/L2a 再来碰撞）';
    if (layer === '06-collision') {
      const layers = store.getResearchLayers(ticker);
      const brief = layers.map(l => `- ${l.layer}: ${l.output_path ? path.basename(l.output_path) : '无文件'}`).join('\n');
      if (brief) evidence = brief;
    }
    const prompt = tpl.replace(/\{\{TICKER\}\}/g, ticker).replace(/\{\{NAME\}\}/g, name).replace(/\{\{EVIDENCE\}\}/g, evidence);
    // PROMPT-PLAN 四约束：模板若带 ```json fenced 的「输出 schema」块，一并返回（旧模板无该块 → null）
    const schema = extractOutputSchema(tpl);
    res.json({ ticker, layer, prompt, schema });
  });

  router.post('/prompt/submit', async (req: Request, res: Response) => {
    const { ticker, layer, output } = req.body || {};
    if (!ticker || !PROMPT_LAYERS[layer] || !output) return res.status(400).json({ error: 'ticker/layer/output 必填' });
    let data: any;
    try { data = typeof output === 'string' ? JSON.parse(output) : output; }
    catch (e: any) { return res.status(400).json({ error: '输出不是合法 JSON', detail: e.message }); }
    // 分层轻验证（PROMPT-PLAN 三.2）：最小必填顶层 key，不过 → 400 + detail 缺什么
    const miss = checkLayerMinKeys(layer, data);
    if (miss) return res.status(400).json({ error: '贴回 JSON 未通过该层最小字段检查', detail: miss });
    const fs = require('fs');
    const wsDir = path.join(store['baseDir'], 'research', 'workspace', ticker);
    fs.mkdirSync(wsDir, { recursive: true });
    const outFile = path.join(wsDir, `${layer}.json`);
    fs.writeFileSync(outFile, JSON.stringify(data, null, 2), 'utf-8');
    // 场景层（exit/discuss/translate/spec）不进状态机：只存档渲染（PROMPT-PLAN 修订1/2）
    if (PROMPT_SCENE_LAYERS.has(layer)) {
      return res.json({ success: true, ticker, layer, output_file: outFile, state_machine: false });
    }
    // fengstate complete = 状态机真门（结构不符会 exit(1)）
    const result = await runner.runTool('fengstate.py', ['complete', ticker, layer, outFile]);
    if (!result.success) {
      return res.status(400).json({ error: 'fengstate complete 拒绝', detail: (result.data ? JSON.stringify(result.data) : result.error || '').slice(0, 1500) });
    }
    res.json({ success: true, ticker, layer, output_file: outFile, state: result.data });
  });

  // markdown 通道（PROMPT-PLAN 修订1）：L4 报告书/白话卡等 markdown 贴回——不进状态机、不 JSON 校验，只存档
  router.post('/prompt/submit-md', (req: Request, res: Response) => {
    const { ticker, layer, title, markdown } = req.body || {};
    if (!ticker || !layer || typeof markdown !== 'string' || !markdown.trim()) {
      return res.status(400).json({ error: 'ticker/layer/markdown 必填', detail: 'body: {ticker, layer, title?, markdown}，markdown 须为非空字符串' });
    }
    // 文件名消毒：Windows 文件名禁 :/\ 等；ISO 时间戳的冒号/点替换为 -
    const safe = (s: string) => String(s).trim().replace(/[^A-Za-z0-9._-]/g, '_').replace(/^_+|_+$/g, '').slice(0, 64) || 'unknown';
    const now = new Date();
    const dir = path.join(store['baseDir'], 'data', 'reports', 'prompt_md');
    fs.mkdirSync(dir, { recursive: true });
    const savedPath = path.join(dir, `${safe(ticker)}_${safe(layer)}_${now.toISOString().replace(/[:.]/g, '-')}.md`);
    const meta = `<!-- saved_at: ${now.toISOString()} | ticker: ${safe(ticker)} | layer: ${safe(layer)}${title ? ` | title: ${String(title).replace(/\s+/g, ' ').replace(/--+/g, '-').slice(0, 200)}` : ''} -->\n\n`;
    fs.writeFileSync(savedPath, meta + markdown, 'utf-8');
    res.json({ ok: true, savedPath });
  });

  // ----- 论断验证（宪法 6.14：fengverify 白话卡） -----

  router.post('/verify/:claim_id', async (req: Request, res: Response) => {
    const { claim_id } = req.params;
    const result = await runner.runTool('fengverify.py', [claim_id], 600000);
    if (!result.success) return fail(res, `论断复测失败: ${claim_id}`, result.error || 'fengverify.py 失败');
    res.json(result.data ?? result.stdout ?? { ok: true });
  });

  // ----- 复盘（宪法 6.9：四态假设+红线+下次回顾，写回 reviews） -----

  router.post('/review/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const { hypothesis_status, redline_results, health_score, next_review_date, notes } = req.body || {};
    if (!['valid', 'uncertain', 'falsified', 'unknown'].includes(hypothesis_status)) {
      return res.status(400).json({ error: 'hypothesis_status 必须是 valid|uncertain|falsified|unknown' });
    }
    if (!next_review_date) return res.status(400).json({ error: '下次回顾日期必填' });
    const holding = store.getHolding(ticker);
    if (!holding) return res.status(404).json({ error: '持仓未找到', detail: ticker });
    const h: any = holding;
    h.reviews = h.reviews || [];
    h.reviews.unshift({
      date: new Date().toISOString().slice(0, 10),
      hypothesis_status,
      redline_results: redline_results || [],
      health_score: health_score ?? null,
      notes: notes || '',
    });
    h.triggers = h.triggers || {};
    h.triggers.next_review_date = next_review_date;
    store.saveHolding(h);
    const j = await runner.runTool('fengwatch.py', ['review', ticker]);
    res.json({ success: true, ticker, fengwatch: j.success ? 'review 已生成' : (j.error || '').slice(0, 200) });
  });

  router.get('/review/:ticker', (req: Request, res: Response) => {
    const holding = store.getHolding(req.params.ticker);
    if (!holding) return res.status(404).json({ error: '持仓未找到' });
    res.json({ reviews: (holding as any).reviews || [], thesis: (holding as any).thesis || {}, next_review_date: (holding as any).triggers?.next_review_date });
  });

  // ----- 全文搜索（宪法 5.5：MD 正文，≤50 条） -----

  router.get('/search', (req: Request, res: Response) => {
    const q = String(req.query.q || '').trim();
    if (!q) return res.status(400).json({ error: 'q required' });
    const fs = require('fs');
    const roots = ['research/060-companies', 'knowledge', 'Discussion'].map(r => path.join(store['baseDir'], r));
    const results: any[] = [];
    const walk = (dir: string) => {
      if (results.length >= 50) return;
      let items: any[] = [];
      try { items = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
      for (const it of items) {
        if (results.length >= 50) return;
        const p = path.join(dir, it.name);
        if (it.isDirectory()) walk(p);
        else if (it.isFile() && it.name.endsWith('.md')) {
          try {
            const content = fs.readFileSync(p, 'utf-8');
            const idx = content.toLowerCase().indexOf(q.toLowerCase());
            if (idx >= 0) {
              results.push({
                file: path.relative(store['baseDir'], p).replace(/\\/g, '/'),
                ticker: (path.relative(store['baseDir'], p).split(path.sep).join('/').match(/060-companies\/([A-Z0-9.]+)-/) || [])[1] || null,
                snippet: content.slice(Math.max(0, idx - 40), idx + 80).replace(/\s+/g, ' ').trim(),
              });
            }
          } catch { /* skip */ }
        }
      }
    };
    roots.forEach(walk);
    res.json({ query: q, count: results.length, results });
  });

  // ----- Research List（宪法 6.11：status 调整） -----

  const LIST_STATUSES = ['researching', 'candidate', 'watching', 'holding', 'parked'];
  router.post('/research-list/:ticker/status', (req: Request, res: Response) => {
    const { ticker } = req.params;
    const { status } = req.body || {};
    if (!LIST_STATUSES.includes(status)) return res.status(400).json({ error: `status 必须是 ${LIST_STATUSES.join('|')}` });
    const fs = require('fs');
    const listPath = path.join(store['baseDir'], 'data', 'config', 'research_list.json');
    if (!fs.existsSync(listPath)) return res.status(404).json({ error: 'research_list.json 不存在' });
    const data = JSON.parse(fs.readFileSync(listPath, 'utf-8'));
    const c = (data.companies || []).find((x: any) => x.ticker === ticker);
    if (!c) return res.status(404).json({ error: '标的不在研究清单中', detail: ticker });
    const from = c.status;
    c.status = status;
    c.updated = new Date().toISOString().slice(0, 10);
    fs.writeFileSync(listPath, JSON.stringify(data, null, 2), 'utf-8');
    res.json({ success: true, ticker, from, to: status });
  });

  // ----- Portfolio（宪法 6.15） -----

  router.get('/portfolio/overview', async (_req: Request, res: Response) => {
    const holdings = store.getHoldings();
    const PROJECT_DIR = path.resolve(__dirname, '..', '..', '..');
    // 汇率：现调 fengfx.py latest（本地库最新收盘，与汇率卡同源）；
    // 库空时回退 fx_latest.json，再回退各持仓 meta.fx_rates 快照
    let fx: Record<string, number> = {};
    let fxSource = 'holdings meta 快照';
    try {
      const r = await runner.runTool('fengfx.py', ['latest']);
      for (const p of (r.data?.pairs || [])) if (p.ticker && p.close != null) fx[String(p.ticker).toUpperCase()] = Number(p.close);
      if (fx['USDCNY']) fxSource = 'fengfx live';
    } catch { /* 库空回退 */ }
    if (!fx['USDCNY']) {
      try { fx = JSON.parse(fs.readFileSync(path.join(PROJECT_DIR, 'data', 'cache', 'fx_latest.json'), 'utf-8')); } catch { /* 尚未更新过 */ }
      if (fx['USDCNY']) fxSource = 'fx_latest.json';
    }
    let invested = 0, value = 0, cashValue = 0, lastBuyMs = 0;
    const byZone: Record<string, number> = {};
    const oppRows: any[] = [];
    const fxFor = (ccy: string, h: any): number => {
      const c = String(ccy || 'CNY').toUpperCase();
      if (c === 'CNY') return 1;
      if (fx[c + '_CNY']) return fx[c + '_CNY'];
      const snap = ((h as any).meta || {}).fx_rates || {};
      return snap[c + '_CNY'] || 1;
    };
    for (const h of holdings) {
      const pos = (h as any).position || {};
      const rate = fxFor((h as any).currency, h);
      const qty: number | null = pos.shares ?? pos.units ?? null;
      // 市值（本币）：优先现价×数量，回退存量 market_value / units×nav / amount
      const mvNative = (pos.current_price && qty != null) ? qty * pos.current_price
        : (pos.market_value ?? (pos.units && pos.nav ? pos.units * pos.nav : (pos.amount ?? null)));
      const mv = mvNative != null ? mvNative * rate : null;
      // 成本（人民币口径）：数量×均价后换汇。旧版漏算基金（只有 units/avg_cost）且不换汇——2026-09-06 创始人纠错
      const cost = (qty != null && pos.avg_cost != null) ? qty * pos.avg_cost * rate : null;
      const isCash = (h as any).asset_type === 'cash' || ['cash', 'quasi_cash'].includes((h as any).qualifier);
      if (!isCash && mv != null) { value += mv; const z = (h as any).capital_zone || 'UNKNOWN'; byZone[z] = (byZone[z] || 0) + mv; }
      if (isCash && mv != null) cashValue += mv;
      if (!isCash && cost != null) invested += cost;
      const _m: any = (h as any).meta || {};
      const bd = (_m.buy_date || _m.created_at) ? new Date(_m.buy_date || _m.created_at) : null;
      if (bd && bd.getTime() > lastBuyMs) lastBuyMs = bd.getTime();
      if (!isCash) oppRows.push({
        ticker: (h as any).ticker || (h as any).id, name: (h as any).name,
        mv: mv != null ? Math.round(mv) : null,
        currency: String((h as any).currency || 'CNY').toUpperCase(),
        pct_total: null as number | null,
        pe: (h as any).position && (h as any).position.pe_ttm != null ? (h as any).position.pe_ttm : ((h as any).valuation && (h as any).valuation.pe_ttm) || null,
        pnl_pct: (pos.avg_cost && pos.current_price) ? Math.round((pos.current_price / pos.avg_cost - 1) * 1000) / 10 : null,
        thesis_ok: !!((h as any).thesis && (h as any).thesis.original),
      });
    }
    // 占比与排序：大仓位在前（机会成本的"对手盘"）；占比=占总资产（持仓+现金）
    for (const r of oppRows) r.pct_total = (value + cashValue) ? Math.round(r.mv / (value + cashValue) * 1000) / 10 : null;
    oppRows.sort((a, b) => (b.mv || 0) - (a.mv || 0));
    res.json({
      holdings_count: holdings.length, total_invested: Math.round(invested * 100) / 100,
      total_market_value: Math.round(value * 100) / 100,
      cash_value: Math.round(cashValue * 100) / 100,
      pnl_pct: invested ? Math.round((value / invested - 1) * 1000) / 10 : null,
      by_capital_zone: byZone,
      cash_pool_value: Math.round(cashValue * 100) / 100,
      cash_pool_pct: (value + cashValue) ? Math.round(cashValue / (value + cashValue) * 1000) / 10 : null,
      days_since_last_buy: lastBuyMs ? Math.round((Date.now() - lastBuyMs) / 86400000) : null,
      fx_source: fxSource,
      opportunity_rows: oppRows,
    });
  });

  router.post('/portfolio/risk', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengportfolio.py', ['risk'], 300000);
    if (!result.success) return fail(res, '风险归因失败', result.error || 'fengportfolio risk 失败');
    res.json(result.data);
  });

  // ----- 组合预算检查（登记第3步用） -----
  router.post('/portfolio/budget-check', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengportfolio.py', ['check']);
    if (!result.success) return fail(res, '预算检查失败', result.error || 'fengportfolio check 失败');
    res.json(result.data);
  });

  // ----- Sell Wizard（宪法 6.8：触发源→六类理由→偏误自查→执行，双闸门） -----

  const SELL_REASON_CLASSES = ['thesis_broken', 'valuation_target', 'better_opportunity', 'need_cash', 'risk_control', 'rollover'];
  const BIAS_CHECKS = ['sunk_cost', 'loss_aversion', 'confirmation', 'anchoring', 'disposition', 'recency'];

  router.post('/sell/execute/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const { price, shares, reason, reason_class, bias_ack } = req.body || {};
    if (!SELL_REASON_CLASSES.includes(reason_class)) {
      return res.status(400).json({ error: '卖出理由分类缺失或不合法', detail: `reason_class 必须是: ${SELL_REASON_CLASSES.join(', ')}` });
    }
    if (!Array.isArray(bias_ack) || bias_ack.length < 3) {
      return res.status(400).json({ error: '偏误自查未完成', detail: '至少逐条确认 3 项行为偏误自查（bias_ack）' });
    }
    const args = ['sell', ticker, '--price', String(price || ''), '--shares', String(shares || ''), '--reason', `[${reason_class}] ${reason || ''}`].filter(a => a !== '');
    const result = await runner.runTool('fengwatch.py', args);
    if (!result.success) return fail(res, `卖出执行失败: ${ticker}`, result.error || 'fengwatch.py sell 失败');
    res.json({ success: true, ticker, message: `卖出记录已保存: ${ticker}` });
  });

  // ----- Rollover -----

  router.post('/rollover/calculate', (req: Request, res: Response) => {
    const { avg_cost, shares, current_price } = req.body;
    if (!avg_cost || !shares || !current_price) {
      return res.status(400).json({ error: 'avg_cost, shares, current_price required' });
    }

    const totalInvested = avg_cost * shares;
    const marketValue = current_price * shares;
    const profitPct = ((current_price / avg_cost) - 1) * 100;
    const canRecover = marketValue >= totalInvested;
    const recoverAmount = canRecover ? totalInvested : 0;
    const sellShares = canRecover ? Math.ceil(totalInvested / current_price) : 0;
    const keepZeroCost = canRecover ? shares - sellShares : 0;

    res.json({
      total_invested: totalInvested,
      market_value: marketValue,
      profit_pct: Math.round(profitPct * 10) / 10,
      can_recover: canRecover,
      recovery_suggestion: canRecover ? {
        sell_shares: sellShares,
        recover_amount: recoverAmount,
        keep_zero_cost: keepZeroCost,
      } : null,
    });
  });

  // ----- Journal -----

  router.get('/journal', (_req: Request, res: Response) => {
    const limit = parseInt(_req.query.limit as string) || 50;
    const entries = store.getJournal(limit);
    res.json(entries);
  });

  router.post('/journal', (req: Request, res: Response) => {
    const entry = req.body as JournalEntry;
    if (!entry.message) return res.status(400).json({ error: 'message required' });
    store.appendJournal({
      ...entry,
      timestamp: entry.timestamp || new Date().toISOString(),
    });
    res.json({ success: true });
  });

  // ----- Watch / Monitor -----

  router.get('/watch/status', (_req: Request, res: Response) => {
    const fs = require('fs');
    const marketDir = path.join(store['baseDir'], 'alerts');
    const alertFile = path.join(marketDir, 'today.json');
    const now = new Date();
    const todayStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0') + '-' + String(now.getDate()).padStart(2, '0');
    if (fs.existsSync(alertFile)) {
      try {
        const data = JSON.parse(fs.readFileSync(alertFile, 'utf-8'));
        let generated = data.date as string | undefined;
        if (!generated) {
          const m = new Date(fs.statSync(alertFile).mtime);
          generated = m.getFullYear() + '-' + String(m.getMonth() + 1).padStart(2, '0') + '-' + String(m.getDate()).padStart(2, '0');
        }
        return res.json({ ...data, generated_date: generated, stale: generated !== todayStr });
      } catch (e: any) { /* fall through */ }
    }
    return res.status(404).json({ error: '暂无监控数据，请先运行每日检查', detail: `未找到缓存文件: ${alertFile}`, generated_date: null, stale: true });
  });

  router.post('/watch/daily', async (_req: Request, res: Response) => {
    const result = await runner.runTool('fengwatch.py', ['daily', '--json']);
    if (result.success && result.data) {
      return res.json(result.data);
    }
    // Fallback: try reading alerts/today.json
    const fs = require('fs');
    const alertFile = path.join(store['baseDir'], 'alerts', 'today.json');
    if (fs.existsSync(alertFile)) {
      try {
        const data = JSON.parse(fs.readFileSync(alertFile, 'utf-8'));
        return res.json(data);
      } catch (e: any) { /* fall through */ }
    }
    return fail(res, '每日检查执行失败', result.error || 'fengwatch.py daily 未返回数据');
  });

  router.get('/watch/log', (_req: Request, res: Response) => {
    const limit = parseInt(_req.query.limit as string) || 50;
    res.json({ entries: store.getJournal(limit) });
  });

  router.post('/watch/review/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const result = await runner.runTool('fengwatch.py', ['review', ticker]);
    if (!result.success) return fail(res, `复盘生成失败: ${ticker}`, result.error || 'fengwatch.py review 失败');
    res.json({ success: true, ticker, message: `Review generated for ${ticker}` });
  });

  router.get('/watch/check/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    try {
      // 10 条退出规则逐条拉实时数据，单次 15s+ 是固有成本；15 分钟内重复检查走缓存
      const data = await withTtlCache(`watchcheck:${ticker}`, 15 * 60 * 1000, async () => {
        const r = await runner.runTool('fengwatch.py', ['check', ticker, '--json']);
        if (!r.success || !r.data) throw new Error(r.error || 'fengwatch.py check 未返回数据');
        return r.data;
      });
      return res.json(data);
    } catch (err: any) {
      return fail(res, '个股检查失败', err?.message || String(err), 502);
    }
  });

  // ----- Watch: History -----

  router.get('/watch/history', async (_req: Request, res: Response) => {
    const holdingsDir = path.join(store['baseDir'], 'holdings');
    const fs = require('fs');
    if (!fs.existsSync(holdingsDir)) return res.json({ active: [], closed: [] });

    const active = [] as any[];
    const closed = [] as any[];
    for (const f of fs.readdirSync(holdingsDir)) {
      const mActive = f.match(/^hold_([A-Za-z0-9.]+)\.json$/);
      const mClosed = f.match(/^hold_([A-Za-z0-9.]+)_closed_(\d{4}-\d{2}-\d{2})\.json$/);
      if (mActive || mClosed) {
        const data = JSON.parse(fs.readFileSync(path.join(holdingsDir, f), 'utf-8'));
        data._display_id = data.id || data.ticker || mActive?.[1] || mClosed?.[1] || '?';
        if (mClosed) {
          data._type = 'closed';
          data._closed_date = mClosed![2];
          closed.push(data);
        } else {
          data._type = 'active';
          const pos = data.position || {};
          if (pos.avg_cost && pos.current_price) {
            pos.return_pct = Math.round((pos.current_price - pos.avg_cost) / pos.avg_cost * 1000) / 10;
          }
          active.push(data);
        }
      }
    }
    res.json({ active, closed });
  });

  router.post('/watch/sell/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const { price, shares, reason } = req.body || {};
    const args = ['sell', ticker];
    if (price) args.push('--price', String(price));
    if (shares) args.push('--shares', String(shares));
    if (reason) args.push('--reason', reason);
    const result = await runner.runTool('fengwatch.py', args);
    if (!result.success) return fail(res, `卖出记录保存失败: ${ticker}`, result.error || 'fengwatch.py sell 失败');
    res.json({ success: true, ticker, message: `卖出记录已保存: ${ticker}` });
  });

  return router;
}
