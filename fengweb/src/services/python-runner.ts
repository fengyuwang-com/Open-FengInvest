import { exec, execFileSync } from 'child_process';
import { existsSync } from 'fs';

/**
 * 候选解释器，按优先级排列。
 * 有些机器上 PATH 里的 `python` 是个没装项目依赖的精简解释器，
 * 所以按绝对路径优先探测，避免跑起来才发现缺库。
 */
const PYTHON_CANDIDATES: string[] = [
  'C:\\Python314\\python.exe',
  'python',
];

/** 探测结果进程内缓存，避免每次调用都 fork 一次解释器。 */
let _detectedPython: string | null = null;

/** 单个候选能否执行给定的 -c 代码。任何异常都视为不可用。 */
function _canRun(cmd: string, code: string): boolean {
  try {
    execFileSync(cmd, ['-c', code], {
      stdio: 'pipe',
      timeout: 15000,
      windowsHide: true,
    });
    return true;
  } catch (_err) {
    return false;
  }
}

/**
 * 选一个能用的解释器：
 * 1. 环境变量 FENG_PYTHON（优先级最高）
 * 2. 候选里能 `import numpy` 的
 * 3. 候选里能 `import sys` 的（至少是个能跑的 Python）
 * 4. 兜底 'python'
 */
export function detectPython(): string {
  if (_detectedPython) return _detectedPython;

  const envPython = (process.env.FENG_PYTHON || '').trim();
  if (envPython && _canRun(envPython, 'import sys')) {
    _detectedPython = envPython;
    return envPython;
  }
  if (envPython) {
    console.warn(`[python-runner] FENG_PYTHON="${envPython}" 不可用，回退到自动探测`);
  }

  for (const code of ['import numpy', 'import sys']) {
    for (const cand of PYTHON_CANDIDATES) {
      if (_canRun(cand, code)) {
        console.log(`[python-runner] 使用解释器: ${cand}`);
        _detectedPython = cand;
        return cand;
      }
    }
  }

  console.warn('[python-runner] 未探测到可用解释器，兜底使用 "python"');
  _detectedPython = 'python';
  return _detectedPython;
}

export interface PythonResult {
  success: boolean;
  data?: any;
  error?: string;
  stdout?: string;
  stderr?: string;
}

export class PythonRunner {
  private baseDir: string;
  private pythonCmd: string;

  constructor(baseDir: string, pythonCmd?: string) {
    this.baseDir = baseDir;
    // 未显式指定时自动探测（环境变量 FENG_PYTHON > 候选探测 > 'python'）
    this.pythonCmd = pythonCmd || detectPython();
  }

  /** 环境检查用：解释器版本（宪法 6.18） */
  async version(): Promise<string> {
    try {
      const r = await this._exec(`"${this.pythonCmd}" -V`, 10000);
      const out = `${r.stdout} ${r.stderr}`.trim();
      return r.code === 0 ? out : `不可用（${out || 'exit ' + r.code}）`;
    } catch (e: any) { return `不可用（${e?.message || e}）`; }
  }

  /**
   * Run any Python tool and parse JSON output.
   */
  async runTool(tool: string, args: string[] = [], timeoutMs: number = 120000): Promise<PythonResult> {
    const toolPath = this._resolveTool(tool);
    const cmd = `"${this.pythonCmd}" "${toolPath}" ${args.join(' ')}`;

    try {
      const result = await this._exec(cmd, timeoutMs);
      if (result.code !== 0) {
        // 工具非零退出 = 失败（宪法册四：非 2xx 契约的根），带出 stdout 尾部供排障
        const tail = result.stdout.trim().split('\n').slice(-5).join(' | ');
        return { success: false, error: result.stderr || tail || `exit code ${result.code}`, stdout: result.stdout, stderr: result.stderr };
      }
      if (result.stderr && result.stderr.toLowerCase().includes('error')) {
        return { success: false, error: result.stderr, stdout: result.stdout, stderr: result.stderr };
      }
      // Try to parse JSON from stdout (object or array — 按首个非空白字符区分)
      const trimmed = result.stdout.trimStart();
      const jsonMatch = trimmed.startsWith('[')
        ? trimmed.match(/\[[\s\S]*\]/)
        : trimmed.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        return { success: true, data: JSON.parse(jsonMatch[0]), stdout: result.stdout };
      }
      return { success: true, data: { raw: result.stdout }, stdout: result.stdout };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * 执行一段内联 Python 代码（base64 传递，避免 Windows shell 引号地狱）。
   * 代码通过 print() 输出结果；非零退出 = 失败。
   */
  async runCode(code: string, timeoutMs: number = 60000): Promise<PythonResult> {
    const b64 = Buffer.from(code, 'utf-8').toString('base64');
    const cmd = `"${this.pythonCmd}" -c "import base64;exec(base64.b64decode('${b64}').decode('utf-8'))"`;
    try {
      const result = await this._exec(cmd, timeoutMs);
      if (result.code !== 0) {
        const tail = result.stderr.trim().split('\n').slice(-5).join(' | ');
        return { success: false, error: tail || `exit code ${result.code}`, stdout: result.stdout, stderr: result.stderr };
      }
      return { success: true, data: { raw: result.stdout }, stdout: result.stdout };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Run state machine complete.
   */
  async runStateComplete(ticker: string, layer: string, outputPath: string): Promise<PythonResult> {
    return this.runTool('fengstate.py', ['complete', ticker, layer, outputPath]);
  }

  /**
   * 返回**不带引号**的纯路径，引号统一由 runTool() 添加。
   */
  private _resolveTool(toolName: string): string {
    // Check tools/ subdirectory first, then root
    const toolsDir = `${this.baseDir}\\tools\\${toolName}`;
    const rootDir = `${this.baseDir}\\${toolName}`;

    if (existsSync(toolsDir.replace(/"/g, ''))) return toolsDir;
    return rootDir;
  }

  private _exec(cmd: string, timeoutMs: number = 120000): Promise<{ stdout: string; stderr: string; code: number | null }> {
    return new Promise((resolve, reject) => {
      exec(cmd, {
        cwd: this.baseDir,
        maxBuffer: 10 * 1024 * 1024, // 10MB buffer
        timeout: timeoutMs,
      }, (error, stdout, stderr) => {
        const code = error && typeof (error as any).code === 'number' ? (error as any).code : (error ? 1 : 0);
        if (error && !stdout) {
          reject(error);
        } else {
          resolve({ stdout, stderr, code });
        }
      });
    });
  }
}
