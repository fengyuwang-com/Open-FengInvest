import express from 'express';
import path from 'path';
import fs from 'fs';
import layouts from 'express-ejs-layouts';
import { marked } from 'marked';
import sanitizeHtml from 'sanitize-html';
import { FileStore } from './services/file-store';
import { PythonRunner } from './services/python-runner';
import { JobQueue } from './services/job-queue';
import { createApiRoutes } from './routes/api';

const APP_DIR = path.resolve(__dirname, '..');
const PROJECT_DIR = path.resolve(APP_DIR, '..');

export function createServer(port: number = 23456) {
  const app = express();
  const store = new FileStore(PROJECT_DIR);
  const runner = new PythonRunner(PROJECT_DIR);
  const queue = new JobQueue(PROJECT_DIR);

  // --- Middleware ---
  app.use(express.json());
  app.use(express.static(path.join(APP_DIR, 'public')));
  app.use('/locales', express.static(path.join(APP_DIR, 'locales'))); // 宪法册八：i18n 词条文件

  // --- View engine ---
  app.set('view engine', 'ejs');

// 宪法册五：服务端 XSS 净化（marked 输出直插 EJS 前必经）
function safeMd(html: string): string {
  return sanitizeHtml(html, {
    allowedTags: sanitizeHtml.defaults.allowedTags.concat(['img', 'h1', 'h2', 'del', 'ins', 'details', 'summary']),
    allowedAttributes: {
      a: ['href', 'name', 'target'], img: ['src', 'alt', 'title'],
      h1: ['id'], h2: ['id'], h3: ['id'], h4: ['id'], span: ['class'], div: ['class'], code: ['class'], table: ['class'], td: ['class'],
    },
    allowedSchemes: ['http', 'https', 'mailto'],
  });
}

  app.set('views', path.join(APP_DIR, 'views'));
  app.use(layouts);
  app.set('layout', 'layout');

  // 公司名总表注入所有视图（R27：名字为主、代码为辅）
  app.use((_req, res, next) => { res.locals.names = store.getCompanyNames(); next(); });

  // --- API routes ---
  app.use('/api', createApiRoutes(store, runner, queue));

  // --- 自动更新（2026-09-06 创始人令：打开就更新、到点就更新，不靠跟 AI 说话）---
  // 启动 15 秒后检查：上次成功更新超过 12 小时 → 自动跑全链；此后每 30 分钟巡检一次
  const AUTO_UPDATE_MIN_AGE_MS = 12 * 3600_000;
  const autoUpdateCheck = (): void => {
    if (queue.isRunning()) return;
    const last = queue.lastUpdate();
    if (!last || Date.now() - new Date(last).getTime() > AUTO_UPDATE_MIN_AGE_MS) queue.start('all');
  };
  setTimeout(autoUpdateCheck, 15_000);
  setInterval(autoUpdateCheck, 30 * 60_000);

  // --- Page routes ---

  app.get('/', (_req, res) => {
    const sys = store.getSystemStatus();
    const list = store.getResearchList();
    const meta = store.getResearchMeta();
    res.render('index', { sys, list, meta, title: 'FengInvest' });
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

  app.get('/ledger', (_req, res) => {
    res.render('ledger', { title: '纪律执行账本' });
  });

  app.get('/holdings', (_req, res) => {
    const holdings = store.getHoldings();
    const closed = store.getClosedHoldings();
    res.render('holdings', { holdings, closed, title: '持仓总览' });
  });

  app.get('/holdings/:ticker/review', (req, res) => {
    const holding = store.getHolding(req.params.ticker);
    if (!holding) return res.status(404).send('持仓未找到');
    res.render('review', { holding, title: `复盘 ${req.params.ticker}` });
  });

  app.get('/holdings/new', (_req, res) => {
    res.render('buy-register', { title: '登记买入' });
  });

  app.get('/holdings/:ticker', (req, res) => {
    const holding = store.getHolding(req.params.ticker);
    if (!holding) return res.status(404).send('持仓未找到');
    const layers = store.getResearchLayers(req.params.ticker);
    res.render('holding-detail', { holding, layers, title: `${req.params.ticker} 详情` });
  });

  app.get('/research', (_req, res) => {
    const meta = store.getResearchMeta();
    const list = store.getResearchList();
    res.render('research', { meta, list, domains: store.getAttentionDomains(), title: '研究' });
  });

  app.get('/research/:ticker', (req, res) => {
    const layers = store.getResearchLayers(req.params.ticker);
    const meta = store.getResearchMeta();
    const info = meta.find(m => m.ticker === req.params.ticker);
    const reports = store.getReports(req.params.ticker) || { name: req.params.ticker, reports: [] };
    const layerLabels: Record<string, string> = {
      l0: 'L0 能力圈', m: 'M 市场数据', l1: 'L1 硬纪律',
      l2b: 'L2b 量化', l2a: 'L2a 定性', l3: 'L3 碰撞',
      l4: 'L4 报告', l4n: 'L4 叙事',
    };
    res.render('research-detail', {
      ticker: req.params.ticker,
      name: info?.name || req.params.ticker,
      layers,
      reports,
      layerLabels,
      path, // needed for path.basename in template
      title: `${req.params.ticker} 研究`,
    });
  });

  // --- 报告系统（宪法册五：书架 + 阅读器 + 红队栏） ---

  app.get('/reports', (_req, res) => {
    const shelves = store.getAllShelves();
    res.render('reports-hub', { shelves, domains: store.getAttentionDomains(), title: '报告中心' });
  });

  app.get('/reports/:ticker', (req, res) => {
    const shelf = store.getReports(req.params.ticker);
    if (!shelf) return res.status(404).send('公司报告书架未找到');
    res.render('reports', { ticker: req.params.ticker, shelf, title: `${shelf.name} 报告书架` });
  });

  app.get('/reports/:ticker/*', (req, res) => {
    const rel: string = (req.params as any)['0'] || '';
    const doc = store.getReportDoc(req.params.ticker, rel);
    if (!doc) return res.status(404).send('报告未找到');
    const body = doc.content;
    const contentHtml = safeMd(marked.parse(body) as string);
    // 册五：阅读器目录（h2/h3 锚点）+ 红队栏①结论段
    const toc: { level: number; text: string; id: string }[] = [];
    let hi = 0;
    const withIds = contentHtml.replace(/<h([23])>([\s\S]*?)<\/h\1>/g, (_m: string, lvl: string, txt: string) => {
      if (toc.length < 40) {
        const id = `h-${++hi}`;
        toc.push({ level: +lvl, text: txt.replace(/<[^>]+>/g, '').trim(), id });
        return `<h${lvl} id="${id}">${txt}</h${lvl}>`;
      }
      return _m;
    });
    let conclusion: string | null = null;
    const cm = body.match(/^#{1,3}.*结论.*$/im);
    if (cm) {
      const after = body.slice(body.indexOf(cm[0]) + cm[0].length);
      const para = after.split(/\n\s*\n/).map(s => s.trim()).find(s => s && !s.startsWith('#'));
      if (para) conclusion = para.replace(/\s+/g, ' ').slice(0, 300);
    }
    const shelf = store.getReports(req.params.ticker);
    res.render('report', {
      ticker: req.params.ticker,
      name: shelf?.name || req.params.ticker,
      doc: { ...doc, contentHtml: withIds, conclusion },
      toc,
      title: doc.title,
    });
  });

  app.get('/portfolio', (_req, res) => {
    res.render('portfolio', { title: '组合盘面' });
  });

  app.get('/alerts', (_req, res) => {
    res.render('alerts', { title: '提醒中心' });
  });

  app.get('/workspace', (_req, res) => {
    res.render('workspace', { title: '决策台' });
  });

  app.get('/discuss', (_req, res) => {
    res.render('discuss', { data: store.getDiscussion(), title: '讨论档案' });
  });

  app.get('/discuss/:file', (req, res) => {
    const doc = store.getDiscussionDoc(req.params.file);
    if (!doc) return res.status(404).send('讨论档案未找到');
    const contentHtml = safeMd(marked.parse(doc.content) as string);
    res.render('report', { ticker: '', name: '讨论档案', doc: { title: doc.title, source: 'own', redteam: null, rel: req.params.file, contentHtml }, title: doc.title });
  });

  app.get('/spec', (_req, res) => {
    res.render('spec', { data: store.getSpecWallet(), title: '投机钱包' });
  });

  app.get('/masters', (_req, res) => {
    const people = store.getPeople();
    res.render('masters', { people, title: '投资家列传' });
  });

  app.get('/masters/:id', (req, res) => {
    const person = store.getPeople().find(p => p.id === req.params.id);
    if (!person) return res.status(404).send('投资家未找到');
    res.render('master-detail', { person, title: person.name });
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
    const contentHtml = safeMd(marked.parse(body) as string);
    res.render('knowledge-detail', { doc: { ...doc, contentHtml }, title: doc.title, relPath });
  });

  app.get('/rollover', (_req, res) => {
    res.render('rollover', { title: '钱仓滚存' });
  });

  // --- BYOK：自带钥匙 LLM（OpenAI 兼容协议；key 只存本机 data/config/llm_config.json） ---
  const maskKey = (k?: string) => (k ? k.slice(0, 4) + '***' + k.slice(-4) : '');
  app.get('/api/llm/config', (_req, res) => {
    const cfg = store.getLlmConfig();
    res.json({ provider: cfg.provider || '', base_url: cfg.base_url || '', model: cfg.model || '', api_key_masked: maskKey(cfg.api_key), configured: !!cfg.api_key });
  });
  app.post('/api/llm/config', (req, res) => {
    const { provider, base_url, model, api_key } = req.body || {};
    if (base_url && !/^https?:\/\//.test(base_url)) return res.status(400).json({ ok: false, error: 'base_url 必须以 http(s):// 开头' });
    store.saveLlmConfig({ provider, base_url: (base_url || '').replace(/\/+$/, ''), model, api_key });
    res.json({ ok: true });
  });
  async function llmChat(messages: { role: string; content: string }[]): Promise<string> {
    const cfg = store.getLlmConfig();
    if (!cfg.api_key || !cfg.base_url) throw new Error('尚未配置 API Key 或接口地址（设置 → 自带钥匙）');
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 120_000);
    try {
      const r = await fetch(cfg.base_url + '/chat/completions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + cfg.api_key },
        body: JSON.stringify({ model: cfg.model || 'glm-4-flash', messages, stream: false }),
        signal: ctrl.signal,
      });
      const j: any = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error((j.error && j.error.message) || ('HTTP ' + r.status));
      const content = j.choices && j.choices[0] && j.choices[0].message && j.choices[0].message.content;
      if (!content) throw new Error('响应无内容: ' + JSON.stringify(j).slice(0, 200));
      return content;
    } finally { clearTimeout(timer); }
  }
  app.post('/api/llm/test', async (_req, res) => {
    try {
      const cfg = store.getLlmConfig();
      const out = await llmChat([{ role: 'user', content: '回复两个字：正常' }]);
      res.json({ ok: true, model: cfg.model, content: out.slice(0, 50) });
    } catch (e: any) { res.json({ ok: false, error: String(e.message || e) }); }
  });
  app.post('/api/llm/chat', async (req, res) => {
    try {
      const { messages } = req.body || {};
      if (!Array.isArray(messages) || !messages.length) return res.status(400).json({ ok: false, error: 'messages 必填' });
      const content = await llmChat(messages.slice(-20));
      res.json({ ok: true, content });
    } catch (e: any) { res.json({ ok: false, error: String(e.message || e) }); }
  });

  app.get('/journal', (_req, res) => {
    const entries = store.getJournal();
    res.render('journal', { entries, title: '决策日志' });
  });

  app.get('/market', (_req, res) => {
    res.render('market', { title: '市场数据' });
  });

  app.get('/sector', (_req, res) => {
    res.render('sector', { title: '板块轮动' });
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
