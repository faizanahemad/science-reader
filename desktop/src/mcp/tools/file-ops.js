/**
 * File operation tools: read, write, edit, delete, move, mkdir, list_directory.
 */
import { readFile, writeFile, mkdir, rm, rename, stat, readdir } from 'node:fs/promises';
import { dirname, relative, join } from 'node:path';
import { validatePath } from '../path-sandbox.js';

import { z } from 'zod';

/**
 * Register all file operation tools on the given MCP server.
 * @param {import('@modelcontextprotocol/sdk/server/mcp.js').McpServer} server
 * @param {() => string} getWorkdir - Returns the current sandbox workdir
 */
export function registerAllFileTools(server, getWorkdir) {

  // ── fs_read_file ──────────────────────────────────────────────────────
  server.tool(
    'fs_read_file',
    'Read the contents of a file. Returns text for text files, base64 for binary.',
    {
      path: z.string().describe('File path (relative to workdir or absolute)'),
      encoding: z.string().optional().describe('Encoding (default: utf-8). Use "base64" for binary files.')
    },
    async ({ path: filePath, encoding }) => {
      try {
        const workdir = getWorkdir();
        const resolved = await validatePath(filePath, workdir);
        const enc = encoding || 'utf-8';

        if (enc === 'base64') {
          const buf = await readFile(resolved);
          return { content: [{ type: 'text', text: buf.toString('base64') }] };
        }

        const content = await readFile(resolved, enc);
        return { content: [{ type: 'text', text: content }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── fs_write_file ─────────────────────────────────────────────────────
  server.tool(
    'fs_write_file',
    'Write content to a file. Creates parent directories if needed.',
    {
      path: z.string().describe('File path (relative to workdir or absolute)'),
      content: z.string().describe('Content to write'),
      encoding: z.string().optional().describe('Encoding (default: utf-8)')
    },
    async ({ path: filePath, content, encoding }) => {
      try {
        const workdir = getWorkdir();
        const resolved = await validatePath(filePath, workdir);
        const enc = encoding || 'utf-8';

        // Ensure parent directory exists
        await mkdir(dirname(resolved), { recursive: true });
        await writeFile(resolved, content, enc);

        const relPath = relative(workdir, resolved);
        return { content: [{ type: 'text', text: `Successfully wrote to ${relPath}` }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── fs_edit_file ──────────────────────────────────────────────────────
  server.tool(
    'fs_edit_file',
    'Apply search-and-replace edits to a file. Each edit replaces oldText with newText.',
    {
      path: z.string().describe('File path (relative to workdir or absolute)'),
      edits: z.array(z.object({
        oldText: z.string().describe('Text to find'),
        newText: z.string().describe('Replacement text')
      })).describe('Array of search-and-replace edits to apply sequentially')
    },
    async ({ path: filePath, edits }) => {
      try {
        const workdir = getWorkdir();
        const resolved = await validatePath(filePath, workdir);

        let content = await readFile(resolved, 'utf-8');
        const originalLines = content.split('\n').length;
        let totalReplacements = 0;

        for (const edit of edits) {
          const idx = content.indexOf(edit.oldText);
          if (idx === -1) {
            return {
              content: [{ type: 'text', text: `Error: Could not find text to replace: "${edit.oldText.slice(0, 80)}..."` }],
              isError: true
            };
          }
          content = content.slice(0, idx) + edit.newText + content.slice(idx + edit.oldText.length);
          totalReplacements++;
        }

        await writeFile(resolved, content, 'utf-8');
        const newLines = content.split('\n').length;
        const relPath = relative(workdir, resolved);
        const lineDiff = newLines - originalLines;
        const lineDiffStr = lineDiff >= 0 ? `+${lineDiff}` : `${lineDiff}`;

        return {
          content: [{
            type: 'text',
            text: `Applied ${totalReplacements} edit(s) to ${relPath} (${originalLines} → ${newLines} lines, ${lineDiffStr})`
          }]
        };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── fs_list_directory ─────────────────────────────────────────────────
  server.tool(
    'fs_list_directory',
    'List directory contents with type and size information.',
    {
      path: z.string().describe('Directory path (relative to workdir or absolute)')
    },
    async ({ path: dirPath }) => {
      try {
        const workdir = getWorkdir();
        const resolved = await validatePath(dirPath, workdir);

        const entries = await readdir(resolved, { withFileTypes: true });
        const lines = [];

        for (const entry of entries) {
          const entryPath = join(resolved, entry.name);
          try {
            const st = await stat(entryPath);
            const size = st.size;
            const sizeStr = formatSize(size);

            if (entry.isDirectory()) {
              lines.push(`${entry.name}/  ${sizeStr}`);
            } else if (entry.isSymbolicLink()) {
              lines.push(`${entry.name}@  ${sizeStr}`);
            } else {
              lines.push(`${entry.name}  ${sizeStr}`);
            }
          } catch {
            lines.push(`${entry.name}  (stat error)`);
          }
        }

        return { content: [{ type: 'text', text: lines.join('\n') || '(empty directory)' }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── fs_mkdir ──────────────────────────────────────────────────────────
  server.tool(
    'fs_mkdir',
    'Create a directory (and parent directories if needed).',
    {
      path: z.string().describe('Directory path to create (relative to workdir or absolute)')
    },
    async ({ path: dirPath }) => {
      try {
        const workdir = getWorkdir();
        const resolved = await validatePath(dirPath, workdir);
        await mkdir(resolved, { recursive: true });
        const relPath = relative(workdir, resolved);
        return { content: [{ type: 'text', text: `Created directory: ${relPath}` }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── fs_move ───────────────────────────────────────────────────────────
  server.tool(
    'fs_move',
    'Move or rename a file or directory. Both source and destination must be within the sandbox.',
    {
      source: z.string().describe('Source path (relative to workdir or absolute)'),
      destination: z.string().describe('Destination path (relative to workdir or absolute)')
    },
    async ({ source, destination }) => {
      try {
        const workdir = getWorkdir();
        const resolvedSrc = await validatePath(source, workdir);
        const resolvedDst = await validatePath(destination, workdir);

        // Ensure destination parent exists
        await mkdir(dirname(resolvedDst), { recursive: true });
        await rename(resolvedSrc, resolvedDst);

        const relSrc = relative(workdir, resolvedSrc);
        const relDst = relative(workdir, resolvedDst);
        return { content: [{ type: 'text', text: `Moved ${relSrc} → ${relDst}` }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );

  // ── fs_delete ─────────────────────────────────────────────────────────
  server.tool(
    'fs_delete',
    'Delete a file or directory. For directories, set recursive=true.',
    {
      path: z.string().describe('Path to delete (relative to workdir or absolute)'),
      recursive: z.boolean().optional().describe('Required for deleting directories (default: false)')
    },
    async ({ path: filePath, recursive: isRecursive }) => {
      try {
        const workdir = getWorkdir();
        const resolved = await validatePath(filePath, workdir);

        const st = await stat(resolved);
        if (st.isDirectory() && !isRecursive) {
          return {
            content: [{ type: 'text', text: 'Error: Path is a directory. Set recursive=true to delete.' }],
            isError: true
          };
        }

        await rm(resolved, { recursive: !!isRecursive, force: false });

        const relPath = relative(workdir, resolved);
        return { content: [{ type: 'text', text: `Deleted: ${relPath}` }] };
      } catch (err) {
        return { content: [{ type: 'text', text: `Error: ${err.message}` }], isError: true };
      }
    }
  );
}

/**
 * Format file size in human-readable form.
 */
function formatSize(bytes) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)}G`;
}
