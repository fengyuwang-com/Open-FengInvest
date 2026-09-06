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

  router.get('/market', async (_req: Request, res: Response) => {
    const fs = require('fs');
    const marketDir = path.join(store['baseDir'], 'research', 'market');

    // Always serve cached data first
    const marketFile = path.join(marketDir, 'latest.json');
    if (fs.existsSync(marketFile)) {
      try {
        const data = JSON.parse(fs.readFileSync(marketFile, 'utf-8'));
        return res.json({ ...data, _source: 'cache', _date: fs.statSync(marketFile).mtime.toISOString() });
      } catch (e: any) {
        // fall through to run collector
      }
    }

    // No cache: run collector in background, return immediately with empty
    runner.runTool('fengmarket.py', ['collect']).catch(() => {});
    res.json({ _source: 'pending', message: 'Data collection in progress, try again in 30s' });
  });

  // ----- Futu Market Overview (live indices) -----

  let _futuCache: { data: any; ts: number } | null = null;
  const FUTU_CACHE_TTL_MS = 60_000; // 60s: 大盘速览不频繁变动, 避免每次刷都慢连 Yahoo

  router.get('/market/futu-overview', async (_req: Request, res: Response) => {
    // Serve short-lived cache first so page refreshes are instant.
    if (_futuCache && Date.now() - _futuCache.ts < FUTU_CACHE_TTL_MS) {
      return res.json({ ..._futuCache.data, _source: 'cache' });
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
    _futuCache = { data: payload, ts: Date.now() };
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

  // ----- Stock Quick Data (Futu primary) -----

  router.get('/stock-quick/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    // Live fetch via fengdata.py (Futu primary, yfinance fallback)
    const result = await runner.runTool('fengdata.py', [ticker, '--mode', 'price', '--backend=auto']);
    if (result.success && result.data?.price) {
      const p = result.data.price;
      const f = result.data.financials || {};
      const ds = result.data.data_sources || [];
      return res.json({
        source: ds[0]?.source || 'futu', ticker,
        price: p.price, ma50: p.ma50, ma120: p.ma120, ma200: p.ma200,
        return_1m_pct: p.return_1m_pct, return_ytd_pct: p.return_ytd_pct,
        change_pct: p.change_pct, volume: p.volume,
        trailing_pe: f.trailing_pe, pb: f.pb, market_cap: f.market_cap,
        high_52w: p.high_52w, low_52w: p.low_52w,
      });
    }
    return res.status(502).json({
      error: '个股行情获取失败',
      detail: result.error || 'fengdata.py 未返回 price 数据',
      ticker,
    });
  });

  // ----- Futu Data Modes -----

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

  // ----- 公司速览（宪法 6.3：估值分位；A股走 fengastock，港美股回退 M 层快照） -----

  router.get('/company/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const isA = /\.(SH|SS|SZ|BJ)$/i.test(ticker);
    try {
      if (isA) {
        const code = ticker.replace(/\.(SS|SH)$/i, '.SH').replace(/\.SZ$/i, '.SZ');
        const q = await runner.runTool('fengastock.py', ['quote', code], 30000);
        if (q.success) {
          const quoteData = JSON.parse(q.stdout || '{}');
          const first = Object.values(quoteData.quotes || {})[0] as any;
          const vh = await runner.runTool('fengastock.py', ['valuation-hist', code, '--metric', 'pe,pb'], 90000);
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
          if (first) return res.json({
            ticker, name: (first.name || '').replace(/\s+/g, ''),
            price: first.price, change_pct: first.change_pct,
            pe_ttm: first.pe_ttm, pb: first.pb, mcap_yi: first.mcap_yi,
            pe_percentile: pct, stale: !!first.is_stale, source: quoteData.source, as_of: quoteData.as_of,
          });
        }
      }
      // 港美股/降级：读最新日期目录的 02-market.json
      const companiesDir = path.join(store['baseDir'], 'research', '060-companies');
      let found: string | null = null;
      for (const e of fs.readdirSync(companiesDir)) {
        if (new RegExp(`^${ticker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}-`).test(e) || e.startsWith(`${ticker}-`)) { found = path.join(companiesDir, e); break; }
      }
      if (!found) return res.status(404).json({ error: '公司目录未找到' });
      const dates = fs.readdirSync(found).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d)).sort();
      if (!dates.length) return res.status(404).json({ error: '无日期目录' });
      const mfile = path.join(found, dates[dates.length - 1], '02-market.json');
      if (!fs.existsSync(mfile)) return res.status(404).json({ error: 'M 层数据未找到' });
      const m = JSON.parse(fs.readFileSync(mfile, 'utf-8'));
      const f = m.financials || {};
      res.json({
        ticker, name: m.name || ticker,
        price: m.price_data?.price ?? null, currency: m.price_data?.currency || null,
        change_pct: m.price_data?.change_pct ?? null,
        pe_ttm: f.trailing_pe ?? null, pb: f.pb ?? null,
        pe_percentile: null, stale: true,
        source: `M 层快照 ${dates[dates.length - 1]}（${m.price_data?.source || '无来源'}）`,
        as_of: dates[dates.length - 1],
      });
    } catch (err: any) {
      return fail(res, '公司速览取数失败', err?.message || String(err));
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

  // ----- Analysis -----

  router.post('/analysis/:ticker/run', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const { layer } = req.body || {};

    if (!layer) return res.status(400).json({ error: 'layer required' });

    // Check state machine
    const check = await runner.runStateCheck(ticker, layer);
    if (!check.success) {
      return res.status(400).json({ error: `State check failed: ${check.error}` });
    }

    const result = await runner.runAnalysis(ticker, layer);
    if (!result.success) {
      return fail(res, '分析执行失败', result.error || 'Analysis failed');
    }

    res.json(result.data);
  });

  router.get('/analysis/:ticker/status', (req: Request, res: Response) => {
    const layers = store.getResearchLayers(req.params.ticker);
    res.json({ ticker: req.params.ticker, layers });
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
    const result = await runner.runTool('fengtick.py', ['t2', req.params.ticker]);
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

  const PROMPT_LAYERS: Record<string, string> = { '01-capability': 'L0 能力圈', 'm': 'M 市场数据', '03-discipline': 'L1 硬纪律', '04-quantitative': 'L2b 量化', '05-qualitative': 'L2a 定性', '06-collision': 'L3 碰撞', '07-report': 'L4 报告', 'review': '复盘' };

  router.get('/prompt/templates', (_req: Request, res: Response) => {
    res.json({ layers: Object.entries(PROMPT_LAYERS).map(([id, label]) => ({ id, label })) });
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
    res.json({ ticker, layer, prompt });
  });

  router.post('/prompt/submit', async (req: Request, res: Response) => {
    const { ticker, layer, output } = req.body || {};
    if (!ticker || !PROMPT_LAYERS[layer] || !output) return res.status(400).json({ error: 'ticker/layer/output 必填' });
    let data: any;
    try { data = typeof output === 'string' ? JSON.parse(output) : output; }
    catch (e: any) { return res.status(400).json({ error: '输出不是合法 JSON', detail: e.message }); }
    const fs = require('fs');
    const wsDir = path.join(store['baseDir'], 'research', 'workspace', ticker);
    fs.mkdirSync(wsDir, { recursive: true });
    const outFile = path.join(wsDir, `${layer}.json`);
    fs.writeFileSync(outFile, JSON.stringify(data, null, 2), 'utf-8');
    // fengstate complete = 状态机真门（结构不符会 exit(1)）
    const result = await runner.runTool('fengstate.py', ['complete', ticker, layer, outFile]);
    if (!result.success) {
      return res.status(400).json({ error: 'fengstate complete 拒绝', detail: (result.data ? JSON.stringify(result.data) : result.error || '').slice(0, 1500) });
    }
    res.json({ success: true, ticker, layer, output_file: outFile, state: result.data });
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

  router.get('/portfolio/overview', (_req: Request, res: Response) => {
    const holdings = store.getHoldings();
    const PROJECT_DIR = path.resolve(__dirname, '..', '..', '..');
    // 汇率：优先 data/cache/fx_latest.json（一键更新任务写入），回退各持仓 meta.fx_rates 快照
    let fx: Record<string, number> = {};
    try { fx = JSON.parse(fs.readFileSync(path.join(PROJECT_DIR, 'data', 'cache', 'fx_latest.json'), 'utf-8')); } catch { /* 尚未更新过 */ }
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
      fx_source: fx['USDCNY'] ? 'fx_latest.json' : 'holdings meta 快照',
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
    if (fs.existsSync(alertFile)) {
      try {
        const data = JSON.parse(fs.readFileSync(alertFile, 'utf-8'));
        return res.json(data);
      } catch (e: any) { /* fall through */ }
    }
    return fail(res, '暂无监控数据，请先运行每日检查', `未找到缓存文件: ${alertFile}`, 404);
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
    const fs = require('fs');
    const limit = parseInt(_req.query.limit as string) || 50;
    const journalFile = path.join(store['baseDir'], 'logs', 'journal.jsonl');
    if (!fs.existsSync(journalFile)) {
      return res.json({ entries: [] });
    }
    const lines = fs.readFileSync(journalFile, 'utf-8').trim().split('\n').filter(Boolean);
    const entries = lines.slice(-limit).reverse().map((l: string) => JSON.parse(l));
    res.json({ entries });
  });

  router.post('/watch/review/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const result = await runner.runTool('fengwatch.py', ['review', ticker]);
    if (!result.success) return fail(res, `复盘生成失败: ${ticker}`, result.error || 'fengwatch.py review 失败');
    res.json({ success: true, ticker, message: `Review generated for ${ticker}` });
  });

  router.get('/watch/check/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const result = await runner.runTool('fengwatch.py', ['check', ticker, '--json']);
    if (result.success && result.data) {
      return res.json(result.data);
    }
    return res.status(502).json({
      error: '个股检查失败',
      detail: result.error || 'fengwatch.py check 未返回数据',
      ticker,
    });
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
