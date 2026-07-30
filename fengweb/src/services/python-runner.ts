import { exec } from 'child_process';

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

  constructor(baseDir: string, pythonCmd: string = 'python') {
    this.baseDir = baseDir;
    this.pythonCmd = pythonCmd;
  }

  /**
   * Run any Python tool and parse JSON output.
   */
  async runTool(tool: string, args: string[] = []): Promise<PythonResult> {
    const toolPath = this._resolveTool(tool);
    const cmd = `"${this.pythonCmd}" "${toolPath}" ${args.join(' ')}`;

    try {
      const result = await this._exec(cmd);
      if (result.stderr && result.stderr.toLowerCase().includes('error')) {
        return { success: false, error: result.stderr, stdout: result.stdout, stderr: result.stderr };
      }
      // Try to parse JSON from stdout
      const jsonMatch = result.stdout.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        return { success: true, data: JSON.parse(jsonMatch[0]), stdout: result.stdout };
      }
      return { success: true, data: { raw: result.stdout }, stdout: result.stdout };
    } catch (err: any) {
      return { success: false, error: err.message };
    }
  }

  /**
   * Run a specific analysis layer.
   */
  async runAnalysis(ticker: string, layer: string): Promise<PythonResult> {
    const toolMap: Record<string, string> = {
      'm': 'fengdata.py',
      'l1': 'fengrule.py',
      'l2b': 'fengquant.py',
      'l3': 'fengcollision.py',
    };
    const tool = toolMap[layer];
    if (!tool) {
      return { success: false, error: `Unknown layer: ${layer}. Supported: ${Object.keys(toolMap).join(', ')}` };
    }
    return this.runTool(tool, [ticker]);
  }

  /**
   * Run state machine check.
   */
  async runStateCheck(ticker: string, layer: string): Promise<PythonResult> {
    return this.runTool('fengstate.py', ['check', ticker, layer]);
  }

  /**
   * Run state machine complete.
   */
  async runStateComplete(ticker: string, layer: string, outputPath: string): Promise<PythonResult> {
    return this.runTool('fengstate.py', ['complete', ticker, layer, outputPath]);
  }

  private _resolveTool(toolName: string): string {
    // Check tools/ subdirectory first, then root
    const toolsDir = `"${this.baseDir}\\tools\\${toolName}"`;
    const rootDir = `"${this.baseDir}\\${toolName}"`;

    // Try both; exec will handle if file not found
    const { existsSync } = require('fs');
    if (existsSync(toolsDir.replace(/"/g, ''))) return toolsDir;
    return rootDir;
  }

  private _exec(cmd: string, timeoutMs: number = 120000): Promise<{ stdout: string; stderr: string }> {
    return new Promise((resolve, reject) => {
      exec(cmd, {
        cwd: this.baseDir,
        maxBuffer: 10 * 1024 * 1024, // 10MB buffer
        timeout: timeoutMs,
      }, (error, stdout, stderr) => {
        if (error && !stdout) {
          reject(error);
        } else {
          resolve({ stdout, stderr });
        }
      });
    });
  }
}
