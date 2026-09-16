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
  type?: string;
  summary?: string;
  date?: string;
}

export interface RedTeamData {
  completed: boolean;
  answers: { q: string; answer: string }[];
}

export interface ReportMeta {
  date: string | null;   // YYYY-MM-DD（日期目录报告）；根/社区文件为 null
  file: string;
  rel: string;           // 相对公司目录的路径（正斜杠）
  title: string;
  source: 'own' | 'community';
  kind: 'formal' | 'note' | 'external'; // formal=七层结论；note=own/过程稿；external=社区/书籍
  redteam: RedTeamData | null;
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

  // fengholding.py 写的持仓 JSON 顶层键是 id 而非 ticker；
  // 视图模板统一用 h.ticker 生成 /holdings/<ticker> 链接，读取口归一化补齐。
  private _normHolding(h: Holding): Holding {
    if (!h.ticker && (h as any).id) (h as any).ticker = (h as any).id;
    return h;
  }

  getHoldings(): Holding[] {
    const dir = path.join(this.baseDir, 'holdings');
    if (!fs.existsSync(dir)) return [];
    return fs.readdirSync(dir)
      .filter(f => f.startsWith('hold_') && f.endsWith('.json'))
      .map(f => this._readJson<Holding>(path.join(dir, f)))
      .filter((h): h is Holding => h !== null)
      .map(h => this._normHolding(h));
  }

  getHolding(ticker: string): Holding | null {
    const h = this._readJson<Holding>(
      path.join(this.baseDir, 'holdings', `hold_${ticker}.json`)
    );
    return h ? this._normHolding(h) : null;
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
    if (/^(l[0-4][abn]?.|m)$/.test(base)) return base;
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

  /** 关注领域标注（knowledge/关注领域.md 三领域，创始人可编辑 data/config/attention-domains.json） */
  getAttentionDomains(): Record<string, string> {
    try {
      const d = JSON.parse(fs.readFileSync(path.join(this.baseDir, 'data', 'config', 'attention-domains.json'), 'utf-8'));
      return d.mapping || {};
    } catch { return {}; }
  }

  /** 公司名总表（data/config/company_names.json：A股 cn_financials.short_name + 研究清单 + 持仓 + 研究目录名） */
  getCompanyNames(): Record<string, { zh?: string; en?: string }> {
    try {
      return JSON.parse(fs.readFileSync(path.join(this.baseDir, 'data', 'config', 'company_names.json'), 'utf-8'));
    } catch { return {}; }
  }

  /** BYOK：自带钥匙 LLM 配置（data/config/llm_config.json，gitignored，永不出本机） */
  getLlmConfig(): { provider?: string; base_url?: string; model?: string; api_key?: string; updated_at?: string } {
    try {
      return JSON.parse(fs.readFileSync(path.join(this.baseDir, 'data', 'config', 'llm_config.json'), 'utf-8'));
    } catch { return {}; }
  }

  saveLlmConfig(cfg: { provider?: string; base_url?: string; model?: string; api_key?: string }): void {
    const file = path.join(this.baseDir, 'data', 'config', 'llm_config.json');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const prev = this.getLlmConfig();
    const next = { ...prev, ...cfg, updated_at: new Date().toISOString() };
    // 空字符串 = 保留旧 key（前端打码回传时不覆盖）
    if (!cfg.api_key) next.api_key = prev.api_key;
    fs.writeFileSync(file, JSON.stringify(next, null, 2), 'utf-8');
  }

  getResearchMeta(): { ticker: string; name: string; layers: ResearchLayer[]; latest_date: string | null }[] {
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

    // R51-A：已研究按新到旧 — 从各层 output_path 抽 YYYY-MM-DD 取最大，无则 null（排最后）
    return Array.from(tickerMap.entries()).map(([ticker, v]) => {
      let latest: string | null = null;
      for (const l of v.layers) {
        const m = (l.output_path || '').match(/(\d{4}-\d{2}-\d{2})/);
        if (m && (!latest || m[1] > latest)) latest = m[1];
      }
      return {
        ticker,
        name: v.name,
        layers: v.layers,
        latest_date: latest,
      };
    });
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

  // 卡片摘要用：把 Markdown 洗成纯文本（**加粗**/引用/列表符/表格竖线/代码围栏全剥掉）
  private _plain(md: string): string {
    return md
      .replace(/^---[\s\S]*?---/, '')
      .replace(/```[\s\S]*?```/g, ' ')
      .replace(/\*\*([^*]+)\*\*/g, '$1')
      .replace(/^\s{0,3}#{1,6}\s+/gm, '')
      .replace(/^\s{0,3}>\s?/gm, '')
      .replace(/^\s{0,3}[-*+]\s+/gm, '')
      .replace(/\|/g, ' ')
      .replace(/`([^`]*)`/g, '$1')
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
      .replace(/\s+/g, ' ')
      .trim();
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
            preview: this._plain(body).slice(0, 120),
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
          const fmName = frontmatter['name'] || '';
          const h1Name = (content.match(/^#\s+(.+)$/m)?.[1]?.trim() || '')
            .replace(/\s*[·•]\s*(思维操作系统|投资思维操作系统|投资思想纲要)\s*$/u, '').trim();
          const name = (/[\u4e00-\u9fff]/.test(fmName) && !/perspective/i.test(fmName))
            ? fmName
            : (/[\u4e00-\u9fff]/.test(h1Name) ? h1Name : f.replace(/\.md$/, ''));
          return {
            category: 'people',
            name,
            path: `knowledge/people/${f}`,
            frontmatter,
            preview: `${frontmatter['school'] || ''} | ${frontmatter['representative'] || ''} — ${this._plain(body).slice(0, 100)}`,
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
          preview: this._plain(body).slice(0, 120),
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
      const title = this._peopleDisplay(fm, content, fileName).name;
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
        const disp = this._peopleDisplay(fm, content, f);
        return {
          id: f.replace(/\.md$/, ''),
          name: disp.name,
          school: disp.school,
          representative: disp.representative,
          when_to_use: fm['when_to_use'] || '',
          sources: fm['sources'] || '',
          disclaimer: fm['disclaimer'] || '',
          distilled_at: fm['distilled_at'] || '',
          preview: this._plain(body).slice(0, 200),
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
    return lines.slice(-limit).map(line => {
      const e = JSON.parse(line) as JournalEntry;
      e.message = e.message || e.summary || '';
      e.action = e.action || e.type || '';
      return e;
    }).reverse();
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

  // 人物显示名统一规则（B: 中文名优先，绝不泄露英文 slug/带杠文件名/unknown）：
  //   1) frontmatter name 含中文 → 直接用（权威）；
  //   2) 否则取 H1（如 "# 罗伯特·巴卡雷纳 · 思维操作系统" → "罗伯特·巴卡雷纳"）；
  //   3) 否则取 description 首句中文名；兜底才用文件名。
  // school 缺失时按关键词推断（绝不返回 unknown）；representative 缺失时从 description 括号英文名提取。
  private _peopleDisplay(
    fm: Record<string, string>,
    content: string,
    fileName: string
  ): { name: string; school: string; representative: string } {
    const hasCjk = (s: string): boolean => /[\u4e00-\u9fff]/.test(s);
    const isSlug = (s: string): boolean => /perspective/i.test(s) || /^[A-Za-z0-9_.\-]+$/.test(s);
    let name = fm['name'] || '';
    if (!name || !hasCjk(name) || isSlug(name)) {
      const h1 = content.match(/^#\s+(.+)$/m)?.[1]?.trim() || '';
      const stripped = h1
        .replace(/\s*[·•]\s*(思维操作系统|投资思维操作系统|投资思想纲要)\s*$/u, '')
        .trim();
      if (stripped && hasCjk(stripped)) {
        name = stripped;
      } else {
        const descBlock = content.match(/^description:\s*\|?\s*\n?((?:  .*\n?)+)/m)?.[1] || '';
        const cn = descBlock.match(/^\s*([\u4e00-\u9fff（）·\s]{2,20}?)\s*[\(（]/);
        if (cn) name = cn[1].trim();
        else name = fileName.replace(/\.md$/, '');
      }
    }
    let school = fm['school'] || '';
    if (!school) {
      const head = content.slice(0, 1500);
      if (/量化|因子|统计套利|随机漫步|指数/.test(head)) school = 'quant';
      else if (/逆向|反向|反脆弱|非对称/.test(head)) school = 'contrarian';
      else if (/宏观|反身性|全天候/.test(head)) school = 'macro';
      else if (/趋势|投机|短线|三重滤网|动量/.test(head)) school = 'trend';
      else if (/成长|GARP|GALP|收益型/.test(head)) school = 'growth';
      else if (/深度价值|安全边际|清算|破产|并购套利/.test(head)) school = 'deep_value';
      else school = 'value';
    }
    let representative = fm['representative'] || '';
    if (!representative) {
      const m = content.slice(0, 1200).match(/[\(（]([A-Za-z][A-Za-z .&'\-]{2,40})[\)）]/);
      if (m) representative = m[1].trim();
    }
    return { name, school, representative };
  }

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
      const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
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

  /** 已清仓持仓（hold_<T>_closed_<date>.json） */
  getClosedHoldings(): { holding: Holding; closed_date: string }[] {
    const dir = path.join(this.baseDir, 'holdings');
    if (!fs.existsSync(dir)) return [];
    const out: { holding: Holding; closed_date: string }[] = [];
    for (const f of fs.readdirSync(dir)) {
      const m = f.match(/^hold_(.+)_closed_(\d{4}-\d{2}-\d{2})\.json$/);
      if (!m) continue;
      const h = this._readJson<Holding>(path.join(dir, f));
      if (h) out.push({ holding: h, closed_date: m[2] });
    }
    return out.sort((a, b) => b.closed_date.localeCompare(a.closed_date));
  }

  // --- Research List（研究清单：在研/候选/观察/持仓/停靠 五态） ---

  getResearchList(): { ticker: string; name: string; status: string; added?: string; note?: string; updated?: string }[] {
    const data = this._readJson<{ companies?: any[] }>(
      path.join(this.baseDir, 'data', 'config', 'research_list.json')
    );
    if (!data || !Array.isArray(data.companies)) return [];
    return data.companies.map((c: any) => ({
      ticker: c.ticker, name: c.name || c.ticker, status: c.status || 'watching',
      added: c.added, note: c.note, updated: c.updated,
    }));
  }

  // --- Discussion（宪法 6.17：讨论档案只读 + 锚定配置置顶） ---

  getDiscussion(): { config: any; entries: { file: string; title: string; preview: string }[] } {
    const dir = path.join(this.baseDir, 'Discussion');
    const config = this._readJson<any>(path.join(dir, 'discuss-config.json')) || {};
    const entries: { file: string; title: string; preview: string }[] = [];
    if (fs.existsSync(dir)) {
      for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.md')).sort().reverse()) {
        const fullPath = path.join(dir, f);
        const content = fs.readFileSync(fullPath, 'utf-8');
        const body = content.replace(/^---[\s\S]*?---\n?/, '').trim();
        const h1 = body.match(/^#\s+(.+)$/m);
        entries.push({ file: f, title: this._readFrontmatter(fullPath)['name'] || (h1 ? h1[1].trim() : f.replace(/\.md$/, '')), preview: this._plain(body).slice(0, 100) });
      }
    }
    return { config, entries };
  }

  getDiscussionDoc(file: string): { content: string; title: string } | null {
    if (!/\.md$/.test(file) || file.includes('..') || file.includes('/') || file.includes('\\')) return null;
    const fullPath = path.join(this.baseDir, 'Discussion', file);
    if (!fs.existsSync(fullPath)) return null;
    const content = fs.readFileSync(fullPath, 'utf-8');
    const body = content.replace(/^---[\s\S]*?---\n?/, '').trim();
    const h1 = body.match(/^#\s+(.+)$/m);
    return { content: body, title: (h1 ? h1[1].trim() : file.replace(/\.md$/, '')) };
  }

  // --- Spec Wallet（宪法 6.16：投机钱包轨道，幽灵原则） ---

  getSpecWallet(): { holdings: Holding[]; notes: { file: string; title: string }[] } {
    const holdings = this.getHoldings().filter((h: any) => h.account_type === 'TRADING');
    const dir = path.join(this.baseDir, 'research', 'speculative');
    const notes: { file: string; title: string }[] = [];
    if (fs.existsSync(dir)) {
      for (const md of this._findMdRecursive(dir).slice(0, 50)) {
        notes.push({ file: path.relative(dir, md).replace(/\\/g, '/'), title: this._reportTitle(md, path.basename(md, '.md')) });
      }
    }
    return { holdings, notes };
  }

  // --- Reports（宪法册五：自有 vs 外来，目录即真相） ---

  /** 红队检验数据（adversarial_check.json，与报告同目录） */
  private _redTeam(dir: string): RedTeamData | null {
    const p = path.join(dir, 'adversarial_check.json');
    const data = this._readJson<{ completed?: boolean; answers?: { q: string; answer: string }[] } & Record<string, { question?: string; answer?: string | string[]; status?: string }>>(p);
    if (!data) return null;
    // 新契约 answers[]（苏泊尔批次写法）
    if (Array.isArray(data.answers) && data.answers.length > 0) {
      return { completed: data.completed !== false, answers: data.answers };
    }
    // 兼容 q1-q4 内联写法（NVDA 批次：q1_five_ways_to_lose / q2_down_30pct / q3_up_30pct / q4_recency_bias）
    const qs = ['q1_five_ways_to_lose', 'q2_down_30pct', 'q3_up_30pct', 'q4_recency_bias']
      .map((k) => data[k]).filter((q) => q && (q.answer ?? q.question));
    if (qs.length === 0) return null;
    return {
      completed: data.completed !== false && qs.every((q) => q.status !== 'todo'),
      answers: qs.map((q) => ({
        q: q.question ?? '',
        answer: Array.isArray(q.answer) ? q.answer.join('；') : (q.answer ?? ''),
      })),
    };
  }

  private _reportTitle(fullPath: string, fallback: string): string {
    const fm = this._readFrontmatter(fullPath);
    if (fm['name']) return fm['name'];
    try {
      const head = fs.readFileSync(fullPath, 'utf-8').slice(0, 600);
      const h1 = head.match(/^#\s+(.+)$/m);
      if (h1) return h1[1].trim();
    } catch { /* fallthrough */ }
    return fallback;
  }

  /** 公司目录名 → 显示名（"0700.HK-腾讯" → "腾讯"） */
  private _companyDisplayName(dirName: string): string {
    const m = dirName.match(/^[^-\s]+[-－]\s*(.+)$/);
    return m ? m[1] : dirName;
  }

  /** 某公司的全部报告书架（日期目录=自有；community/=外来；根散文件=自有未归档） */
  getReports(ticker: string): { name: string; reports: ReportMeta[]; formalLatest: string | null; stale: boolean; staleDays: number } | null {
    const companiesDir = path.join(this.baseDir, 'research', '060-companies');
    if (!fs.existsSync(companiesDir)) return null;
    let companyDir: string | null = null;
    let displayName = ticker;
    for (const e of fs.readdirSync(companiesDir, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      if (this._extractTicker(e.name) === ticker) {
        companyDir = path.join(companiesDir, e.name);
        displayName = this._companyDisplayName(e.name);
        break;
      }
    }
    if (!companyDir || !fs.existsSync(companyDir)) return null;

    const reports: ReportMeta[] = [];
    // 层文件不进书架；但 07-report / 07-narrative 是主报告，必须可读
    const LAYER_RE = /^(0[1-6]-|08-|l[0-4][abn]?\.(md|json)$|m\.(md|json)$|temp_)/i;

    const pushFile = (fullPath: string, date: string | null, source: 'own' | 'community', kind: 'formal' | 'note' | 'external') => {
      const file = path.basename(fullPath);
      if (!file.endsWith('.md')) return;
      // 注意：LAYER_RE 只在日期目录分支用（七层层文件）；own/community/根散文件不套用，
      // 否则 own/ 里以 01- 开头的笔记（如《看懂拼多多》系列）会被误杀
      if (/^(README|TODO|AUDIT_REPORT|00-INDEX)\.md$/i.test(file)) return; // 审计产物与批次索引不进书架
      reports.push({
        date,
        file,
        rel: path.relative(companyDir!, fullPath).replace(/\\/g, '/'),
        title: this._reportTitle(fullPath, file.replace(/\.md$/, '')),
        source,
        kind,
        redteam: date ? this._redTeam(path.join(companyDir!, date)) : null,
      });
    };

    const communityDir = path.join(companyDir, 'community');
    for (const e of fs.readdirSync(companyDir, { withFileTypes: true })) {
      if (e.isFile()) {
        // 目录即真相：自有 = 日期目录里的七层产出；根目录散文件默认外来；
        // 确属本人产出的散文件移入 own/ 子目录即可改判
        pushFile(path.join(companyDir, e.name), null, 'community', 'external');
      } else if (e.isDirectory()) {
        if (/^\d{4}-\d{2}-\d{2}$/.test(e.name)) {
          const dateDir = path.join(companyDir, e.name);
          const rt = this._redTeam(dateDir);
          for (const de of fs.readdirSync(dateDir, { withFileTypes: true })) {
            if (de.isFile()) {
              const file = de.name;
              if (!file.endsWith('.md')) continue;
              if (LAYER_RE.test(file)) continue;
              if (/^(README|TODO|AUDIT_REPORT|00-INDEX)\.md$/i.test(file)) continue; // 审计产物与批次索引不进书架
              // 日期目录内仅 07-report / 07-narrative 是正式报告，其余进书架的 MD 算笔记
              const isFormal = /^(07-report|07-narrative)\.md$/i.test(file);
              reports.push({
                date: e.name, file,
                rel: `${e.name}/${file}`,
                title: this._reportTitle(path.join(dateDir, file), file.replace(/\.md$/, '')),
                source: 'own', kind: isFormal ? 'formal' : 'note', redteam: rt,
              });
            }
          }
        } else if (e.name === 'community') {
          for (const md of this._findMdRecursive(communityDir)) {
            pushFile(md, null, 'community', 'external');
          }
        } else if (e.name === 'own') {
          for (const md of this._findMdRecursive(path.join(companyDir, e.name))) {
            pushFile(md, null, 'own', 'note');
          }
        } else if (e.name !== 'sources' && e.name !== 'temp') {
          // 其他子目录（如未拆分的外来书系）按外来算
          for (const md of this._findMdRecursive(path.join(companyDir, e.name))) {
            pushFile(md, null, 'community', 'external');
          }
        }
      }
    }
    reports.sort((a, b) => (b.date || '').localeCompare(a.date || '') || a.file.localeCompare(b.file));
    // R51-D：正式报告最新日期（仅 kind==formal）+ 过期判定（距今>90天），/api/reports/:ticker 验证用
    const formalDates = reports.filter(r => r.source === 'own' && r.kind === 'formal' && r.date).map(r => r.date as string).sort();
    const formalLatest = formalDates.length > 0 ? formalDates[formalDates.length - 1] : null;
    let stale = false, staleDays = 0;
    if (formalLatest) {
      staleDays = Math.floor((Date.now() - new Date(formalLatest + 'T00:00:00').getTime()) / 86400000);
      stale = staleDays > 90;
    }
    return { name: displayName, reports, formalLatest, stale, staleDays };
  }

  /** 全部公司书架概览（/reports 总览页用） */
  getAllShelves(): { ticker: string; name: string; own: number; formal: number; notes: number; community: number; latestDate: string | null; hasRedteam: boolean; formalLatest: string | null; formalLatestRel: string | null; stale: boolean; staleDays: number }[] {
    const companiesDir = path.join(this.baseDir, 'research', '060-companies');
    if (!fs.existsSync(companiesDir)) return [];
    const out: { ticker: string; name: string; own: number; formal: number; notes: number; community: number; latestDate: string | null; hasRedteam: boolean; formalLatest: string | null; formalLatestRel: string | null; stale: boolean; staleDays: number }[] = [];
    for (const e of fs.readdirSync(companiesDir, { withFileTypes: true })) {
      if (!e.isDirectory()) continue;
      const ticker = this._extractTicker(e.name);
      if (!ticker) continue;
      const shelf = this.getReports(ticker);
      if (!shelf) continue;
      const own = shelf.reports.filter(r => r.source === 'own');
      const formalLatest = shelf.formalLatest;
      const stale = shelf.stale, staleDays = shelf.staleDays;
      // UX 审计 P2：最新正式报告的 rel（报告中心"最近一篇 →"直达链接用）
      const formalSorted = own.filter(r => r.kind === 'formal' && r.rel).sort((a, b) => (b.date || '').localeCompare(a.date || ''));
      out.push({
        ticker,
        name: shelf.name,
        own: own.length,
        formal: own.filter(r => r.kind === 'formal').length,
        notes: own.filter(r => r.kind === 'note').length,
        community: shelf.reports.length - own.length,
        latestDate: own[0]?.date || null,
        hasRedteam: own.some(r => r.redteam),
        formalLatest,
        formalLatestRel: formalSorted[0]?.rel || null,
        stale,
        staleDays,
      });
    }
    return out;
  }

  /** 读单篇报告（带红队数据与来源） */
  getReportDoc(ticker: string, rel: string): { content: string; title: string; source: 'own' | 'community'; kind: 'formal' | 'note' | 'external'; redteam: RedTeamData | null; rel: string } | null {
    const shelf = this.getReports(ticker);
    if (!shelf) return null;
    const meta = shelf.reports.find(r => r.rel === rel.replace(/\\/g, '/'));
    if (!meta) return null; // 只允许书架内已知文件，防路径穿越
    const companiesDir = path.join(this.baseDir, 'research', '060-companies');
    let companyDir: string | null = null;
    for (const e of fs.readdirSync(companiesDir, { withFileTypes: true })) {
      if (e.isDirectory() && this._extractTicker(e.name) === ticker) { companyDir = path.join(companiesDir, e.name); break; }
    }
    if (!companyDir) return null;
    const fullPath = path.join(companyDir, ...meta.rel.split('/'));
    if (!fs.existsSync(fullPath)) return null;
    let content = fs.readFileSync(fullPath, 'utf-8');
    content = content.replace(/^---[\s\S]*?---\n?/, '').trim();
    const redteam = meta.date
      ? this._redTeam(path.join(companyDir, meta.date))
      : null;
    return { content, title: meta.title, source: meta.source, kind: meta.kind, redteam, rel: meta.rel };
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
