/**
 * Shell execution tool: fs_run_shell.
 */
import { execFile } from 'node:child_process';
import { z } from 'zod';
import { validatePath } from '../path-sandbox.js';


/**
 * Register the shell execution tool on the MCP server.
 * @param {import('@modelcontextprotocol/sdk/server/mcp.js').McpServer} server
 * @param {() => string} getWorkdir
 */
export function registerShellTools(server, getWorkdir) {

  // ── fs_run_shell ──────────────────────────────────────────────────────
  server.tool(
    'fs_run_shell',
    'Execute a shell command within the sandbox. Returns stdout, stderr, and exit code.',
    {
      command: z.string().describe('Shell command to execute'),
      cwd: z.string().optional().describe('Working directory (default: workdir, must be within sandbox)'),
      timeout: z.number().optional().describe('Timeout in seconds (default: 120, max: 300)')
    },
    async ({ command, cwd, timeout }) => {
      try {
        const workdir = getWorkdir();

        // Validate cwd if provided
        const execCwd = cwd
          ? await validatePath(cwd, workdir)
          : workdir;

        // Calculate timeout
        const timeoutSec = Math.min(timeout || 120, 300);
        const timeoutMs = timeoutSec * 1000;

        const result = await new Promise((resolve) => {
          // Use execFile with shell: true for better security than exec()
          execFile('/bin/sh', ['-c', command], {
            cwd: execCwd,
            timeout: timeoutMs,
            maxBuffer: 10 * 1024 * 1024, // 10MB
            env: {
              ...process.env,
              // Ensure commands know the working directory
              HOME: process.env.HOME,
              PATH: process.env.PATH,
            }
          }, (error, stdout, stderr) => {
            resolve({
              stdout: stdout || '',
              stderr: stderr || '',
              exitCode: error ? (error.code ?? 1) : 0,
              timedOut: error?.killed || false
            });
          });
        });

        const parts = [];
        if (result.stdout) parts.push(`stdout:\n${result.stdout}`);
        if (result.stderr) parts.push(`stderr:\n${result.stderr}`);
        parts.push(`exit code: ${result.exitCode}`);
        if (result.timedOut) parts.push(`(timed out after ${timeoutSec}s)`);

        return {
          content: [{ type: 'text', text: parts.join('\n\n') }],
          isError: result.exitCode !== 0
        };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );
}
