import { exec } from 'child_process';
import path from 'path';
import fs from 'fs';
import { detectPython } from './python-runner';

/**
 * 宪法册三 3.3：UI 触发的数据库更新 job 队列。
 * 顺序固定：fengdata fx（写 fx_latest.json）→ fengdata --holdings-update（持仓现价）
 *   → fengstockintl fetch（四源链，实写 safe_batch）→ fengfuyao backfill（增量财报）。
 * 批量写库由工具内部走 fengdb.py safe_batch 可回滚；本队列只编排与汇报进度。
 * 2026-09-06 创始人令：一键更新必须真写（去 dry-run），且支持打开自动更新/定时更新。
 */

export interface JobStep {
  tool: string;
  scope: string;
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  rows?: number;
  error?: string;
  started_at?: string;
  finished_at?: string;
}

export interface Job {
  job_id: string;
  status: 'running' | 'done' | 'failed';
  steps: JobStep[];
  started_at: string;
  finished_at?: string;
}

const STAMP_PATH = (baseDir: string): string => path.join(baseDir, 'data', 'cache', 'last_update.json');
const FX_PATH = (baseDir: string): string => path.join(baseDir, 'data', 'cache', 'fx_latest.json');

export class JobQueue {
  private jobs = new Map<string, Job>();
  private baseDir: string;
  private running = false;

  constructor(baseDir: string) {
    this.baseDir = baseDir;
  }

  get(jobId: string): Job | undefined {
    return this.jobs.get(jobId);
  }

  isRunning(): boolean {
    return this.running;
  }

  /** 上次成功更新时间（ISO），无记录返回 null */
  lastUpdate(): string | null {
    try {
      const j = JSON.parse(fs.readFileSync(STAMP_PATH(this.baseDir), 'utf-8'));
      return j.finished_at || null;
    } catch {
      return null;
    }
  }

  /** 启动更新任务；scope: all（全链）| fx（仅汇率）| quotes（汇率+现价） */
  start(scope: string = 'all'): string {
    if (this.running) {
      // 已有任务在跑：复用正在跑的 job，不并发重入
      for (const j of this.jobs.values()) if (j.status === 'running') return j.job_id;
    }
    const job_id = `job_${Date.now().toString(36)}`;
    const steps: JobStep[] = [
      { tool: 'fengdata.py', scope: 'fx', status: 'pending' },
      { tool: 'fengdata.py', scope: 'holdings-prices', status: 'pending' },
      // R27 创始人令：一键更新 = 所有东西。fengstockdb update 不带参数 = 19 市场全量增量（含 CN/HK，safe_batch 可回滚）
      { tool: 'fengstockdb.py', scope: 'stockdb-daily', status: 'pending' },
      { tool: 'fengfuyao.py', scope: 'financials', status: 'pending' },
    ];
    if (scope === 'fx') { steps.length = 1; }
    if (scope === 'quotes') { steps.length = 2; }
    const job: Job = { job_id, status: 'running', steps, started_at: new Date().toISOString() };
    this.jobs.set(job_id, job);
    this.running = true;
    this.run(job);
    return job_id;
  }

  private run(job: Job): void {
    const python = detectPython();
    const next = (i: number): void => {
      if (i >= job.steps.length) {
        job.status = job.steps.some(s => s.status === 'failed') ? 'failed' : 'done';
        job.finished_at = new Date().toISOString();
        this.running = false;
        this.stamp(job);
        return;
      }
      const step = job.steps[i];
      step.status = 'running';
      step.started_at = new Date().toISOString();
      const cmd = `"${python}" "${path.join(this.baseDir, 'tools', step.tool)}" ${this.argsFor(step.scope).join(' ')}`;
      exec(cmd, {
        cwd: this.baseDir,
        // 全市场日线（19 市场、CN 串行）跑得久：单独放宽到 60 分钟；其余步骤 10 分钟
        timeout: step.scope === 'stockdb-daily' ? 3_600_000 : 600_000,
        maxBuffer: 10 * 1024 * 1024, windowsHide: true,
        // 国际日线实写开关（工具侧仍走 fengdb.safe_batch 可回滚）
        env: { ...process.env, FENG_INTL_FILL_CONFIRM: 'YES' },
      }, (error, stdout, stderr) => {
        step.finished_at = new Date().toISOString();
        const m = stdout.match(/(\d[\d,]*)\s*(?:行|rows)/);
        if (m) step.rows = parseInt(m[1].replace(/,/g, ''), 10);
        if (error) {
          step.status = 'failed';
          step.error = (stderr || stdout || error.message).split('\n').slice(-5).join(' | ').slice(0, 500);
        } else {
          step.status = 'done';
          if (step.scope === 'fx') this.saveFx(stdout);
          if (step.scope === 'holdings-prices') {
            // 真跑校验：updated_count=0 而非 0 只票 → 判失败，不许假成功
            try {
              const j = JSON.parse(stdout.slice(stdout.indexOf('{')));
              step.rows = j.updated_count || 0;
              if (!j.updated_count && j.failed_count) {
                step.status = 'failed';
                step.error = `全部 ${j.failed_count} 只未取到价（Futu 与免费源均无价）`;
              }
            } catch { /* ignore */ }
          }
        }
        next(i + 1);
      });
    };
    next(0);
  }

  /** fx 步骤：fengdata.py fx 输出纯 JSON，落盘供组合页换汇 */
  private saveFx(stdout: string): void {
    try {
      const start = stdout.indexOf('{');
      const json = JSON.parse(stdout.slice(start));
      if (json && json.HKDCNY) {
        const p = FX_PATH(this.baseDir);
        fs.mkdirSync(path.dirname(p), { recursive: true });
        fs.writeFileSync(p, JSON.stringify(json), 'utf-8');
      }
    } catch { /* 解析失败不影响 job 状态 */ }
  }

  /** 更新完成打时间戳（自动更新据此判断是否过期） */
  private stamp(job: Job): void {
    try {
      const p = STAMP_PATH(this.baseDir);
      fs.mkdirSync(path.dirname(p), { recursive: true });
      fs.writeFileSync(p, JSON.stringify({ job_id: job.job_id, status: job.status, finished_at: job.finished_at }), 'utf-8');
    } catch { /* ignore */ }
  }

  private argsFor(scope: string): string[] {
    switch (scope) {
      case 'fx': return ['fx'];
      case 'holdings-prices': return ['--holdings-update'];
      case 'intl-daily': return ['fill', '--market', 'US', '--no-dry-run']; // 已被 stockdb-daily 取代，保留兼容
      case 'stockdb-daily': return ['update']; // 全市场增量（us/cn/hk/jp/... 19 市场）
      case 'financials': return ['backfill', '--universe', '--limit', '200']; // --universe 自带增量（进度文件跳过 done）；限块防超时
      default: return [];
    }
  }
}
