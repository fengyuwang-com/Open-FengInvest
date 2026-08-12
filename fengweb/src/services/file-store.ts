import * as fs from 'fs';
import * as path from 'path';

// ===== Types =====

export interface Position {
  shares?: number;
  avg_cost?: number;
  current_price?: number;
  market_value?: number;
  // Fund
  units?: number;
  nav?: number;
  // Deposit
  principal?: number;
  rate?: number;
  term_months?: number;
  start_date?: string;
  maturity_date?: string;
  // Bond
  face_value?: number;
  coupon_rate?: number;
  quantity?: number;
  // Other
  description?: string;
  cost?: number;
  estimated_value?: number;
  valuation_method?: string;
  [key: string]: any;
}

export interface Capital {
  total_invested: number;
  total_fees?: number;
  total_dividends?: number;
  realized_pl?: number;
  cost_basis?: number;
  currency?: string;
  // Multi-currency: CNY-equivalent values (snapshot FX from meta.fx_rates)
  market_value_equiv_cny?: number;
  cost_basis_equiv_cny?: number;
}

export interface CapitalRollover {
  total_invested: number;
  recovered: number;
  recoverable_at_price?: number;
  zero_cost_shares?: number;
  phase: string;
}

export interface Thesis {
  original: string;
  summary?: string;
  principles?: string[];
  benchmark?: string;
  valuation_gap?: number;
  expected_return?: number;
  time_horizon_months?: number;
  exit_conditions?: string[];
}

export interface Review {
  date: string;
  type: string;
  thesis_valid: boolean;
  triggers_ok?: boolean;
  notes: string;
  action?: string;
}

export interface Triggers {
  price_up_alert: number;
  price_down_alert: number;
  next_review_date?: string;
  thesis_invalidation?: boolean;
  stop_loss_pct?: number;
}

export interface Trade {
  date: string;
  type: string;       // buy | sell | dividend | adjust
  shares?: number;
  price?: number;
  fees?: number;
  currency?: string;
  note?: string;
}

export interface Meta {
  created_at?: string;
  updated_at?: string;
  version?: number;
  source?: string;
}

export interface Holding {
  id?: string;
  ticker?: string;       // backward compat
  name?: string;
  asset_type?: string;   // stock | fund | cash | deposit | bond | other
  currency?: string;
  broker?: string;
  account_type: string;
  lifecycle_phase: string;
  // 正交维度（SCHEMA「风险盘面」章节）：market 资产类别 / segment 板块 / qualifier 现金属性
  market?: string;       // CN_A | CN_HK | CN_OVS | US | GLOBAL | …
  segment?: string;      // 互联网 | 半导体·AI算力 | 保险 | …
  qualifier?: string;    // cash | quasi_cash | 缺省=权益
  capital_zone?: string; // CN_IN | OVERSEAS（仅作买入预算，不参与风险告警）
  market_access?: string; // hksi=港股通
  position: Position;
  capital?: Capital;
  capital_rollover: CapitalRollover;
  trades?: Trade[];
  thesis: Thesis;
  reviews: Review[];
  triggers: Triggers;
  meta?: Meta;
}

export interface ResearchLayer {
  layer: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  output_path?: string;
  data?: any;
}

export interface KnowledgeEntry {
  category: string;
  name: string;
  path: string;
  frontmatter: Record<string, string>;
  preview: string;
}

export interface KnowledgeCategory {
  name: string;
  label: string;
  entries: KnowledgeEntry[];
}

export interface AlertItem {
  id?: string;
  ticker?: string;
  type: string;
  message: string;
  severity: 'info' | 'warning' | 'danger';
  date?: string;
}

export interface PeopleEntry {
  id: string;
  name: string;
  school: string;
  representative: string;
  when_to_use: string;
  sources: string;
  disclaimer: string;
  distilled_at: string;
  preview: string;
  content: string;
}

export interface JournalEntry {
  timestamp: string;
  ticker?: string;
  action?: string;
  message: string;
}

export interface DashboardData {
  holdings_count: number;
  alerts: AlertItem[];
  research_count: number;
  total_value: number;
  total_invested: number;
  total_pnl_pct: number;
}

// ===== File Store =====

export class FileStore {
  private baseDir: string;

  constructor(baseDir: string) {
    this.baseDir = baseDir;
  }

  // --- Holdings ---

  getHoldings(): Holding[] {
    const dir = path.join(this.baseDir, 'holdings');
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
      .filter(f => f.startsWith('hold_') && f.endsWith('.json'))
      .map(f => this._readJson<Holding>(path.join(dir, f)))
      .filter((h): h is Holding => h !== null);
  }

  getHolding(ticker: string): Holding | null {
    return this._readJson<Holding>(
      path.join(this.baseDir, 'holdings', `hold_${ticker}.json`)
    );
  }

  saveHolding(holding: Holding): void {
    const dir = path.join(this.baseDir, 'holdings');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      path.join(dir, `hold_${holding.ticker}.json`),
      JSON.stringify(holding, null, 2),
      'utf-8'
    );
  }

  // --- Research ---
  // Scans three sources: research/060-companies/, research/ (flat temp_*), research/state/

  private static LAYER_ALIASES: Record<string, string> = {
    '01-capability': 'l0',
    '02-market': 'm',
    '03-discipline': 'l1',
    '04-quantitative': 'l2b',
    '05-qualitative': 'l2a',
    '06-collision': 'l3',
    '07-report': 'l4',
    '07-narrative': 'l4n',
  };

  private static LAYER_LABELS: Record<string, string> = {
    l0: 'L0 能力圈',
    m: 'M 市场数据',
    l1: 'L1 硬纪律',
    l2b: 'L2b 量化',
    l2a: 'L2a 定性',
    l3: 'L3 碰撞',
    l4: 'L4 报告',
    l4n: 'L4 叙事',
  };

  /** Map any layer filename (l0.md, 02-market.json, temp_m_MSFT.json) to canonical layer name */
  private _layerFromFile(filename: string): string | null {
    const base = path.basename(filename).replace(/\.(json|md)$/, '');
    // temp_<layer>_<TICKER>.*
    let m = base.match(/^temp_([a-z0-9]+)_/);
    if (m) return FileStore.LAYER_ALIASES[m[1]] || m[1];
    // numbered: 02-market → m
    if (FileStore.LAYER_ALIASES[base]) return FileStore.LAYER_ALIASES[base];
    // plain: m, l0, l1, l2a, l2b, l3, l4
    if (/^(l[0-4][abn]?|m)$/.test(base)) return base;
    return null;
  }

  /** Extract ticker from a directory or filename */
  private _extractTicker(name: string): string | null {
    // "1810.HK-小米集团" → "1810.HK"
    let m = name.match(/^([A-Z0-9]+(?:\.[A-Z]+)?)/);
    if (m) return m[1];
    // "PDD-拼多多" → "PDD"
    m = name.match(/^([A-Z]+)/);
    if (m) return m[1];
    return null;
  }

  /** Scan a company directory for layer files */
  private _scanCompanyLayers(companyDir: string): { layer: string; path: string }[] {
    const results: { layer: string; path: string }[] = [];
    if (!fs.existsSync(companyDir)) return results;

    const entries = fs.readdirSync(companyDir, { withFileTypes: true });

    // Check flat files directly in company dir (e.g., 6896.HK/l0.md)
    for (const e of entries) {
      if (!e.isFile()) continue;
      const layer = this._layerFromFile(e.name);
      if (layer) results.push({ layer, path: path.join(companyDir, e.name) });
    }

    // Check date subdirectories (e.g., 0239.HK/2026-07-14/)
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      if (!/^\d{4}-\d{2}-\d{2}$/.test(e.name)) continue; // only YYYY-MM-DD dirs
      const dateDir = path.join(companyDir, e.name);

      // Scan date dir for layer files
      const dateEntries = fs.readdirSync(dateDir, { withFileTypes: true });
      for (const de of dateEntries) {
        if (!de.isFile()) continue;
        const layer = this._layerFromFile(de.name);
        if (layer) results.push({ layer, path: path.join(dateDir, de.name) });
      }

      // Also check temp/ subdir within date dir
      const tempDir = path.join(dateDir, 'temp');
      if (fs.existsSync(tempDir)) {
        const tempEntries = fs.readdirSync(tempDir, { withFileTypes: true });
        for (const te of tempEntries) {
          if (!te.isFile()) continue;
          const layer = this._layerFromFile(te.name);
          if (layer) results.push({ layer, path: path.join(tempDir, te.name) });
        }
      }
    }

    return results;
  }

  getResearchMeta(): { ticker: string; name: string; layers: ResearchLayer[] }[] {
    const tickerMap = new Map<string, { name: string; layers: ResearchLayer[] }>();

    // 1. Scan research/060-companies/
    const companiesDir = path.join(this.baseDir, 'research', '060-companies');
    if (fs.existsSync(companiesDir)) {
      for (const entry of fs.readdirSync(companiesDir, { withFileTypes: true })) {
        if (!entry.isDirectory()) continue;
        const ticker = this._extractTicker(entry.name);
        if (!ticker) continue;
        const scan = this._scanCompanyLayers(path.join(companiesDir, entry.name));
        const layers = scan.map(s => ({
          layer: s.layer,
          status: 'completed' as const,
          output_path: s.path,
          data: s.path.endsWith('.json') ? this._readJson<any>(s.path) : undefined,
        }));
        if (!tickerMap.has(ticker)) {
          tickerMap.set(ticker, { name: entry.name, layers: [] });
        }
        const existing = tickerMap.get(ticker)!;
        // Merge unique layers
        const existingLayers = new Set(existing.layers.map(l => l.layer));
        for (const l of layers) {
          if (!existingLayers.has(l.layer)) {
            existing.layers.push(l);
            existingLayers.add(l.layer);
          }
        }
      }
    }

    // 2. Scan research/ root for flat temp_* files
    const researchDir = this.baseDir + '/research';
    if (fs.existsSync(researchDir)) {
      for (const f of fs.readdirSync(researchDir)) {
        const m = f.match(/^temp_([a-z0-9]+)_(.+?)\.(json|md)$/);
        if (!m) continue;
        const layer = FileStore.LAYER_ALIASES[m[1]] || m[1];
        const ticker = m[2];
        const fullPath = path.join(researchDir, f);
        if (!tickerMap.has(ticker)) {
          tickerMap.set(ticker, { name: ticker, layers: [] });
        }
        const existing = tickerMap.get(ticker)!;
        if (!existing.layers.find(l => l.layer === layer)) {
          existing.layers.push({
            layer,
            status: 'completed',
            output_path: fullPath,
            data: f.endsWith('.json') ? this._readJson<any>(fullPath) : undefined,
          });
        }
      }
    }

    return Array.from(tickerMap.entries()).map(([ticker, v]) => ({
      ticker,
      name: v.name,
      layers: v.layers,
    }));
  }

  getResearchLayers(ticker: string): ResearchLayer[] {
    // Find this ticker in getResearchMeta
    const meta = this.getResearchMeta();
    const found = meta.find(m => m.ticker === ticker);
    return found ? found.layers : [];
  }

  private _tickerFromLayer(layer: ResearchLayer): string | null {
    if (!layer.output_path) return null;
    const basename = path.basename(layer.output_path);
    const m = basename.match(/temp_[a-z0-9]+_(.+?)\./);
    return m ? m[1] : null;
  }

  // --- Knowledge ---

  getKnowledgeTree(): KnowledgeCategory[] {
    const dir = path.join(this.baseDir, 'knowledge');
    if (!fs.existsSync(dir)) return [];
    const categories: KnowledgeCategory[] = [];

    const dirs = fs.readdirSync(dir, { withFileTypes: true });
    for (const d of dirs) {
      if (!d.isDirectory()) continue;
      const categoryDir = path.join(dir, d.name);
      const entries: KnowledgeEntry[] = fs.readdirSync(categoryDir)
        .filter(f => f.endsWith('.md'))
        .map(f => {
          const fullPath = path.join(categoryDir, f);
          const frontmatter = this._readFrontmatter(fullPath);
          const content = fs.readFileSync(fullPath, 'utf-8');
          const body = content.replace(/---[\s\S]*?---\n?/, '').trim();
          return {
            category: d.name,
            name: f.replace(/\.md$/, ''),
            path: `knowledge/${d.name}/${f}`,
            frontmatter,
            preview: body.slice(0, 120).replace(/#/g, '').trim(),
          };
        });
      if (entries.length > 0) {
        categories.push({
          name: d.name,
          label: this._categoryLabel(d.name),
          entries,
        });
      }
    }

    // Include people/masters as a knowledge category
    const peopleDir = path.join(this.baseDir, 'research', '040-people', 'named');
    if (fs.existsSync(peopleDir)) {
      const peopleEntries: KnowledgeEntry[] = fs.readdirSync(peopleDir)
        .filter(f => f.endsWith('.md'))
        .map(f => {
          const fullPath = path.join(peopleDir, f);
          const frontmatter = this._readFrontmatter(fullPath);
          const content = fs.readFileSync(fullPath, 'utf-8');
          const body = content.replace(/---[\s\S]*?---\n?/, '').trim();
          return {
            category: 'people',
            name: frontmatter['name'] || f.replace(/\.md$/, ''),
            path: `knowledge/people/${f}`,
            frontmatter,
            preview: `${frontmatter['school'] || ''} | ${frontmatter['representative'] || ''} — ${body.slice(0, 100).replace(/#/g, '').trim()}`,
          };
        });
      if (peopleEntries.length > 0) {
        categories.push({
          name: 'people',
          label: '🧠 投资家列传',
          entries: peopleEntries,
        });
      }
    }

    // Aggregate research/ knowledge-type directories into the knowledge tree
    // so研究成果/文档 also surface here (in addition to knowledge/).
    const researchToKnowledge: Record<string, string> = {
      '010-macro': '🌍 宏观研究',
      '020-market': '📉 市场情报',
      '030-asset-classes': '🏦 资产类别',
      '070-reports': '📄 研究报告',
      '090-portfolio-management': '🎯 组合管理',
      '100-learning-investment': '📚 学投资',
      '110-strategy-verification': '🧪 论断验证',
    };
    for (const [resDir, label] of Object.entries(researchToKnowledge)) {
      const srcDir = path.join(this.baseDir, 'research', resDir);
      if (!fs.existsSync(srcDir)) continue;
      const mdFiles = this._findMdRecursive(srcDir);
      if (mdFiles.length === 0) continue;
      const entries: KnowledgeEntry[] = mdFiles.map((fullPath) => {
        const rel = path.relative(srcDir, fullPath);
        const frontmatter = this._readFrontmatter(fullPath);
        const content = fs.readFileSync(fullPath, 'utf-8');
        const body = content.replace(/---[\s\S]*?---\n?/, '').trim();
        return {
          category: resDir,
          name: frontmatter['name'] || rel.replace(/\.md$/, '').replace(/\\/g, '/'),
          path: `research/${resDir}/${rel.replace(/\\/g, '/')}`,
          frontmatter,
          preview: body.slice(0, 120).replace(/#/g, '').trim(),
        };
      }).slice(0, 40); // cap per category to keep the page manageable
      categories.push({ name: resDir, label, entries });
    }

    return categories;
  }

  getKnowledgeDoc(relPath: string): { content: string; title: string } | null {
    // Route people/ paths to research/040-people/named/
    if (relPath.startsWith('people/')) {
      const fileName = path.basename(relPath);
      const peoplePath = path.join(this.baseDir, 'research', '040-people', 'named', fileName);
      const mdPath = peoplePath.endsWith('.md') ? peoplePath : peoplePath + '.md';
      if (!fs.existsSync(mdPath)) return null;
      const content = fs.readFileSync(mdPath, 'utf-8');
      const fm = this._readFrontmatter(mdPath);
      const title = fm['name'] || path.basename(relPath, '.md');
      return { content, title };
    }
    // Route research/ paths (aggregated knowledge categories) to research/ dir
    if (relPath.startsWith('research/')) {
      const fullPath = path.join(this.baseDir, relPath);
      const mdPath = fullPath.endsWith('.md') ? fullPath : fullPath + '.md';
      if (!fs.existsSync(mdPath)) return null;
      const content = fs.readFileSync(mdPath, 'utf-8');
      const title = this._readFrontmatter(mdPath)['name'] || path.basename(relPath, '.md');
      return { content, title };
    }
    const fullPath = path.join(this.baseDir, 'knowledge', relPath);
    const mdPath = fullPath.endsWith('.md') ? fullPath : fullPath + '.md';
    if (!fs.existsSync(mdPath)) return null;
    const content = fs.readFileSync(mdPath, 'utf-8');
    const title = this._readFrontmatter(fullPath)['name'] || path.basename(relPath, '.md');
    return { content, title };
  }

  // --- People / Masters ---

  getPeople(): PeopleEntry[] {
    const dir = path.join(this.baseDir, 'research', '040-people', 'named');
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
      .filter(f => f.endsWith('.md'))
      .map(f => {
        const fullPath = path.join(dir, f);
        const fm = this._readFrontmatter(fullPath);
        const content = fs.readFileSync(fullPath, 'utf-8');
        const body = content.replace(/---[\s\S]*?---\n?/, '').trim();
        return {
          id: f.replace(/\.md$/, ''),
          name: fm['name'] || f.replace(/\.md$/, ''),
          school: fm['school'] || 'unknown',
          representative: fm['representative'] || '',
          when_to_use: fm['when_to_use'] || '',
          sources: fm['sources'] || '',
          disclaimer: fm['disclaimer'] || '',
          distilled_at: fm['distilled_at'] || '',
          preview: body.slice(0, 200).replace(/#/g, '').trim(),
          content: body,
        };
      })
      .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));
  }

  // --- Alerts ---

  getAlerts(): AlertItem[] {
    const file = path.join(this.baseDir, 'alerts', 'today.json');
    if (!fs.existsSync(file)) return [];
    const data = this._readJson<{ alerts: AlertItem[] }>(file);
    return data?.alerts || [];
  }

  // --- Journal ---

  getJournal(limit: number = 50): JournalEntry[] {
    const file = path.join(this.baseDir, 'logs', 'journal.jsonl');
    if (!fs.existsSync(file)) return [];
    const lines = fs.readFileSync(file, 'utf-8').split('\n').filter(Boolean);
    return lines.slice(-limit).map(line => JSON.parse(line) as JournalEntry).reverse();
  }

  appendJournal(entry: JournalEntry): void {
    const dir = path.join(this.baseDir, 'logs');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(
      path.join(dir, 'journal.jsonl'),
      JSON.stringify(entry) + '\n',
      'utf-8'
    );
  }

  // --- Dashboard ---

  getDashboard(): DashboardData {
    const holdings = this.getHoldings();
    const alerts = this.getAlerts();
    const research = this.getResearchMeta();
    // Multi-currency aggregation: prefer CNY-equivalent snapshot (capital.market_value_equiv_cny /
    // cost_basis_equiv_cny); fall back to native market_value for legacy single-currency files.
    const totalValue = holdings.reduce((s, h) => {
      const cny = h.capital?.market_value_equiv_cny;
      return s + (cny ?? (h.position.market_value || 0));
    }, 0);
    const totalInvested = holdings.reduce((s, h) => {
      const cny = h.capital?.cost_basis_equiv_cny;
      const native = h.capital?.cost_basis ?? h.capital_rollover.total_invested;
      return s + (cny ?? (native || 0));
    }, 0);
    const pnl = totalInvested > 0 ? ((totalValue - totalInvested) / totalInvested) * 100 : 0;

    return {
      holdings_count: holdings.length,
      alerts,
      research_count: research.length,
      total_value: totalValue,
      total_invested: totalInvested,
      total_pnl_pct: Math.round(pnl * 10) / 10,
    };
  }

  // --- System Status (rich dashboard) ---

  getSystemStatus(): any {
    const holdings = this.getHoldings();
    const research = this.getResearchMeta();
    const tree = this.getKnowledgeTree();
    const journal = this.getJournal(5);
    const alerts = this.getAlerts();
    const dashboard = this.getDashboard();

    // Pipeline status per ticker
    const pipelineMap: Record<string, string[]> = {};
    for (const r of research) {
      pipelineMap[r.ticker] = r.layers.map(l => l.layer);
    }

    // Build layer completeness for dashboard display
    const allLayers = ['l0', 'm', 'l1', 'l2a', 'l2b', 'l3', 'l4'];
    const layerLabels: Record<string, string> = {
      l0: 'L0 能力圈',
      m: 'M 市场数据',
      l1: 'L1 硬纪律',
      l2a: 'L2a 定性',
      l2b: 'L2b 量化',
      l3: 'L3 碰撞',
      l4: 'L4 报告',
    };

    // Check directory existence
    const dirs = ['holdings', 'knowledge', 'research', 'logs', 'reviews', 'alerts'];
    const dirStatus: Record<string, boolean> = {};
    for (const d of dirs) {
      dirStatus[d] = fs.existsSync(path.join(this.baseDir, d));
    }

    // Knowledge doc count
    const kbCount = tree.reduce((s, c) => s + c.entries.length, 0);

    // Knowledge categories summary for dashboard
    const kbCategories = tree.map(c => ({ name: c.name, label: c.label, count: c.entries.length }));

    // Recent research activity (tickers with latest completed layers)
    const recentResearch = research
      .filter(r => r.layers.length > 0)
      .sort((a, b) => {
        const aMax = Math.max(...a.layers.map(l => allLayers.indexOf(l.layer)));
        const bMax = Math.max(...b.layers.map(l => allLayers.indexOf(l.layer)));
        return bMax - aMax;
      })
      .slice(0, 10)
      .map(r => ({
        ticker: r.ticker,
        layers: r.layers.sort((a, b) => allLayers.indexOf(a.layer) - allLayers.indexOf(b.layer)),
      }));

    return {
      holdings_count: holdings.length,
      holdings,
      research_count: research.length,
      pipelineMap,
      allLayers,
      layerLabels,
      dirStatus,
      kbCount,
      kbCategoryCount: tree.length,
      kbCategories,
      journalCount: journal.length,
      tickersWithFullPipeline: Object.values(pipelineMap).filter(
        ls => allLayers.every(l => ls.includes(l))
      ).length,
      // New dashboard fields
      total_pnl_pct: dashboard.total_pnl_pct,
      alertsCount: alerts.length,
      alerts,
      recentResearch,
      journal,
    };
  }

  // --- Private helpers ---

  private _readJson<T>(filePath: string): T | null {
    try {
      if (!fs.existsSync(filePath)) return null;
      return JSON.parse(fs.readFileSync(filePath, 'utf-8')) as T;
    } catch {
      return null;
    }
  }

  private _readFrontmatter(filePath: string): Record<string, string> {
    try {
      const content = fs.readFileSync(filePath, 'utf-8');
      const match = content.match(/^---\n([\s\S]*?)\n---/);
      if (!match) return {};
      const fm: Record<string, string> = {};
      for (const line of match[1].split('\n')) {
        const kv = line.match(/^(\w+):\s*(.+)$/);
        if (kv) fm[kv[1]] = kv[2];
      }
      return fm;
    } catch {
      return {};
    }
  }

  private _findMdRecursive(dir: string): string[] {
    const out: string[] = [];
    const walk = (d: string): void => {
      let items: import('fs').Dirent[];
      try {
        items = fs.readdirSync(d, { withFileTypes: true });
      } catch {
        return;
      }
      for (const it of items) {
        const p = path.join(d, it.name);
        if (it.isDirectory()) walk(p);
        else if (it.isFile() && it.name.endsWith('.md')) out.push(p);
      }
    };
    walk(dir);
    return out.sort();
  }

  private _categoryLabel(name: string): string {
    const labels: Record<string, string> = {
      principles: '🏛️ 四大原则',
      discipline: '⚖️ 纪律规则',
      methodology: '🔬 方法论',
      market_view: '📊 市场观',
      personal: '📓 个人沉淀',
    };
    return labels[name] || name;
  }
}
