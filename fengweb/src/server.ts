import express from 'express';
import path from 'path';
import fs from 'fs';
import layouts from 'express-ejs-layouts';
import { marked } from 'marked';
import { FileStore } from './services/file-store';
import { PythonRunner } from './services/python-runner';
import { createApiRoutes } from './routes/api';

const APP_DIR = path.resolve(__dirname, '..');
const PROJECT_DIR = path.resolve(APP_DIR, '..');

export function createServer(port: number = 23456) {
  const app = express();
  const store = new FileStore(PROJECT_DIR);
  const runner = new PythonRunner(PROJECT_DIR);

  // --- Middleware ---
  app.use(express.json());
  app.use(express.static(path.join(APP_DIR, 'public')));

  // --- View engine ---
  app.set('view engine', 'ejs');
  app.set('views', path.join(APP_DIR, 'views'));
  app.use(layouts);
  app.set('layout', 'layout');

  // --- API routes ---
  app.use('/api', createApiRoutes(store, runner));

  // --- Page routes ---

  app.get('/', (_req, res) => {
    const sys = store.getSystemStatus();
    res.render('index', { sys, title: 'FengInvest' });
  });

  app.get('/system', (_req, res) => {
    // 图6: 全系统组件关系图 — 由 tools/system-map/build.py 生成, 服务端动态读入
    let systemMapMermaid = '';
    const mmdPath = path.join(PROJECT_DIR, 'docs', 'system-map.mmd');
    if (fs.existsSync(mmdPath)) {
      systemMapMermaid = fs.readFileSync(mmdPath, 'utf-8');
    }
    res.render('system', { title: '系统架构', systemMapMermaid });
  });

  app.get('/holdings', (_req, res) => {
    const holdings = store.getHoldings();
    res.render('holdings', { holdings, title: '持仓总览' });
  });

  app.get('/holdings/:ticker', (req, res) => {
    const holding = store.getHolding(req.params.ticker);
    if (!holding) return res.status(404).send('持仓未找到');
    const layers = store.getResearchLayers(req.params.ticker);
    res.render('holding-detail', { holding, layers, title: `${req.params.ticker} 详情` });
  });

  app.get('/research', (_req, res) => {
    const meta = store.getResearchMeta();
    res.render('research', { meta, title: '研究' });
  });

  app.get('/research/:ticker', (req, res) => {
    const layers = store.getResearchLayers(req.params.ticker);
    const meta = store.getResearchMeta();
    const info = meta.find(m => m.ticker === req.params.ticker);
    const layerLabels: Record<string, string> = {
      l0: 'L0 能力圈', m: 'M 市场数据', l1: 'L1 硬纪律',
      l2b: 'L2b 量化', l2a: 'L2a 定性', l3: 'L3 碰撞',
      l4: 'L4 报告', l4n: 'L4 叙事',
    };
    res.render('research-detail', {
      ticker: req.params.ticker,
      name: info?.name || req.params.ticker,
      layers,
      layerLabels,
      path, // needed for path.basename in template
      title: `${req.params.ticker} 研究`,
    });
  });

  app.get('/knowledge', (_req, res) => {
    const tree = store.getKnowledgeTree();
    res.render('knowledge', { tree, title: '知识库' });
  });

  app.get('/knowledge/*', (req, res) => {
    const relPath: string = (req.params as any)['0'] || '';
    const doc = store.getKnowledgeDoc(relPath);
    if (!doc) return res.status(404).send('文档未找到');
    // Strip frontmatter and render Markdown to HTML
    const body = doc.content.replace(/^---[\s\S]*?---\n?/, '').trim();
    const contentHtml = marked.parse(body);
    res.render('knowledge-detail', { doc: { ...doc, contentHtml }, title: doc.title, relPath });
  });

  app.get('/rollover', (_req, res) => {
    res.render('rollover', { title: '钱仓滚存' });
  });

  app.get('/journal', (_req, res) => {
    const entries = store.getJournal();
    res.render('journal', { entries, title: '决策日志' });
  });

  app.get('/market', (_req, res) => {
    res.render('market', { title: '市场数据' });
  });

  app.get('/watch', async (_req, res) => {
    res.render('watch', { title: '持仓监控' });
  });

  app.get('/watch/history', async (_req, res) => {
    res.render('watch-history', { title: '持仓历史' });
  });

  app.get('/watch/sell/:ticker', (req, res) => {
    const holding = store.getHolding(req.params.ticker);
    if (!holding) return res.status(404).send('持仓未找到');
    res.render('watch-sell', { holding, title: `卖出 ${req.params.ticker}` });
  });

  app.get('/analyze', (_req, res) => {
    res.render('analyze', { title: '股票分析' });
  });

  app.get('/analyze/:ticker', (req, res) => {
    const layers = store.getResearchLayers(req.params.ticker);
    const meta = store.getResearchMeta();
    const info = meta.find(m => m.ticker === req.params.ticker);
    res.render('analyze', {
      ticker: req.params.ticker,
      name: info?.name || req.params.ticker,
      layers: layers || [],
      title: `${req.params.ticker} 分析`,
    });
  });

  // --- Start ---
  app.listen(port, () => {
    console.log(`FengInvest Web UI → http://localhost:${port}`);
  });

  return app;
}
