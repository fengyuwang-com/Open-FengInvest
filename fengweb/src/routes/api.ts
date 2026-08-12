import { Router, Request, Response } from 'express';
import path from 'path';
import { FileStore, Holding, DashboardData, JournalEntry } from '../services/file-store';
import { PythonRunner } from '../services/python-runner';

export function createApiRoutes(store: FileStore, runner: PythonRunner): Router {
  const router = Router();

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
    if (result.success && result.data) return res.json(result.data);
    res.json({ error: result.error || 'No market data' });
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
    res.json({ error: result.error || 'No data', ticker });
  });

  // ----- Futu Data Modes -----

  router.get('/stock/valuation/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'valuation']);
    if (result.success && result.data) return res.json(result.data);
    res.json({ error: result.error || 'No valuation data' });
  });

  router.get('/stock/shareholders/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'shareholders']);
    if (result.success && result.data) return res.json(result.data);
    res.json({ error: result.error || 'No shareholder data' });
  });

  router.get('/stock/analysts/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'analysts']);
    if (result.success && result.data) return res.json(result.data);
    res.json({ error: result.error || 'No analyst data' });
  });

  router.get('/stock/profile/:ticker', async (req: Request, res: Response) => {
    const result = await runner.runTool('fengdata.py', [req.params.ticker, '--mode', 'profile']);
    if (result.success && result.data) return res.json(result.data);
    res.json({ error: result.error || 'No profile data' });
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
      return res.status(500).json({ error: result.error || 'Analysis failed' });
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
    res.json({ error: 'No alerts yet. Run daily check first.' });
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
    res.json({ error: result.error || 'Daily check failed' });
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
    res.json({
      success: result.success,
      ticker,
      message: result.success ? `Review generated for ${ticker}` : (result.error || 'Review failed'),
    });
  });

  router.get('/watch/check/:ticker', async (req: Request, res: Response) => {
    const { ticker } = req.params;
    const result = await runner.runTool('fengwatch.py', ['check', ticker, '--json']);
    if (result.success && result.data) {
      return res.json(result.data);
    }
    res.json({ error: result.error || 'Check failed', ticker });
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
    res.json({
      success: result.success,
      ticker,
      message: result.success ? `卖出记录已保存: ${ticker}` : (result.error || '卖出失败'),
    });
  });

  return router;
}
