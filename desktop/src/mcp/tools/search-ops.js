/**
 * Search tools: glob and grep.
 * Uses Node.js 22+ built-in fs.glob with fast-glob as fallback.
 */
import { glob as fsGlob } from 'node:fs/promises';
import { readFile } from 'node:fs/promises';
import { relative, join } from 'node:path';
import { z } from 'zod';
import { validatePath } from '../path-sandbox.js';

/**
 * Register glob and grep tools on the MCP server.
 * @param {import('@modelcontextprotocol/sdk/server/mcp.js').McpServer} server
 * @param {() => string} getWorkdir
 */
export function registerSearchTools(server, getWorkdir) {

  // ── fs_glob ───────────────────────────────────────────────────────────
  server.tool(
    'fs_glob',
    'Find files matching a glob pattern. Returns paths relative to workdir.',
    {
      pattern: z.string().describe('Glob pattern (e.g., "**/*.js", "src/**/*.ts")'),
      path: z.string().optional().describe('Base directory for search (default: workdir)')
    },
    async ({ pattern, path: basePath }) => {
      try {
        const workdir = getWorkdir();
        const searchRoot = basePath
          ? await validatePath(basePath, workdir)
          : workdir;

        const matches = [];

        // Use Node.js 22+ built-in fs.glob
        try {
          for await (const entry of fsGlob(pattern, { cwd: searchRoot })) {
            matches.push(entry);
            if (matches.length >= 1000) break; // Safety limit
          }
        } catch (nativeErr) {
          // Fallback to fast-glob if native glob fails
          const fg = (await import('fast-glob')).default;
          const results = await fg(pattern, {
            cwd: searchRoot,
            dot: false,
            onlyFiles: false,
            followSymbolicLinks: false,
          });
          matches.push(...results.slice(0, 1000));
        }

        if (matches.length === 0) {
          return { content: [{ type: 'text', text: 'No matches found.' }] };
        }

        return { content: [{ type: 'text', text: matches.join('\n') }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── fs_grep ───────────────────────────────────────────────────────────
  server.tool(
    'fs_grep',
    'Search file contents with a regex pattern. Returns matching lines with file path and line number.',
    {
      pattern: z.string().describe('Regex pattern to search for'),
      path: z.string().optional().describe('Directory to search in (default: workdir)'),
      include: z.string().optional().describe('Glob filter for filenames (e.g., "*.js", "*.{ts,tsx}")')
    },
    async ({ pattern, path: searchPath, include: includeGlob }) => {
      try {
        const workdir = getWorkdir();
        const searchRoot = searchPath
          ? await validatePath(searchPath, workdir)
          : workdir;

        let regex;
        try {
          regex = new RegExp(pattern, 'g');
        } catch {
          return {
            content: [{ type: 'text', text: `Error: Invalid regex pattern: "${pattern}"` }],
            isError: true
          };
        }

        // Find files to search
        const filePattern = includeGlob || '**/*';
        const filesToSearch = [];

        try {
          for await (const entry of fsGlob(filePattern, { cwd: searchRoot })) {
            filesToSearch.push(entry);
            if (filesToSearch.length >= 5000) break;
          }
        } catch {
          const fg = (await import('fast-glob')).default;
          const results = await fg(filePattern, {
            cwd: searchRoot,
            onlyFiles: true,
            followSymbolicLinks: false,
          });
          filesToSearch.push(...results.slice(0, 5000));
        }

        const matches = [];
        const MAX_MATCHES = 100;

        for (const file of filesToSearch) {
          if (matches.length >= MAX_MATCHES) break;

          const fullPath = join(searchRoot, file);
          try {
            const content = await readFile(fullPath, 'utf-8');
            const lines = content.split('\n');

            for (let i = 0; i < lines.length; i++) {
              if (matches.length >= MAX_MATCHES) break;

              // Reset regex lastIndex for each line
              regex.lastIndex = 0;
              if (regex.test(lines[i])) {
                const relFile = relative(workdir, fullPath);
                matches.push(`${relFile}:${i + 1}: ${lines[i]}`);
              }
            }
          } catch {
            // Skip files that can't be read (binary, permission, etc.)
          }
        }

        if (matches.length === 0) {
          return { content: [{ type: 'text', text: 'No matches found.' }] };
        }

        let result = matches.join('\n');
        if (matches.length >= MAX_MATCHES) {
          result += `\n\n(Results limited to ${MAX_MATCHES} matches)`;
        }

        return { content: [{ type: 'text', text: result }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );
}
