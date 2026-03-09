/**
 * Local Filesystem MCP Server (M0.5) for Science Reader Desktop Companion.
 *
 * Provides 10 filesystem tools via the Model Context Protocol over HTTP.
 * Binds to 127.0.0.1 only (no external access) with dynamic port allocation.
 * All file operations are sandboxed to a configurable workdir.
 *
 * Usage:
 *   import { startServer, stopServer } from './filesystem-server.js';
 *   const { port, close } = await startServer('/path/to/workdir');
 *   // MCP endpoint available at http://127.0.0.1:{port}/mcp
 *   close(); // or stopServer()
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { realpath } from 'node:fs/promises';

import { registerAllFileTools } from './tools/file-ops.js';
import { registerSearchTools } from './tools/search-ops.js';
import { registerShellTools } from './tools/shell-ops.js';

// ── Module State ────────────────────────────────────────────────────────
let _workdir = null;
let _httpServer = null;
/** @type {Map<string, StreamableHTTPServerTransport>} */
const _sessions = new Map();

/**
 * Get the current sandbox workdir.
 * @returns {string}
 */
function getWorkdir() {
  if (!_workdir) throw new Error('MCP filesystem server not started — no workdir set');
  return _workdir;
}

/**
 * Parse the JSON body from an incoming HTTP request.
 * @param {import('node:http').IncomingMessage} req
 * @returns {Promise<any>}
 */
function parseBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', chunk => chunks.push(chunk));
    req.on('end', () => {
      try {
        const body = Buffer.concat(chunks).toString('utf-8');
        resolve(body ? JSON.parse(body) : undefined);
      } catch (err) {
        reject(new Error(`Invalid JSON body: ${err.message}`));
      }
    });
    req.on('error', reject);
  });
}

/**
 * Check if a JSON-RPC request is an initialize request.
 * @param {any} body - Parsed JSON body
 * @returns {boolean}
 */
function isInitializeRequest(body) {
  if (Array.isArray(body)) {
    return body.some(msg => msg?.method === 'initialize');
  }
  return body?.method === 'initialize';
}

/**
 * Create and configure the MCP server with all filesystem tools.
 * @returns {McpServer}
 */
function createMcpServer() {
  const server = new McpServer({
    name: 'science-reader-filesystem',
    version: '1.0.0'
  });

  // Register all 10 tools
  registerAllFileTools(server, getWorkdir);
  registerSearchTools(server, getWorkdir);
  registerShellTools(server, getWorkdir);

  return server;
}

/**
 * Start the filesystem MCP server.
 *
 * @param {string} workdir - The sandbox root directory. All file operations
 *   will be constrained to this directory.
 * @returns {Promise<{ port: number, close: () => Promise<void> }>}
 */
export async function startServer(workdir) {
  if (_httpServer) {
    throw new Error('MCP filesystem server is already running');
  }

  // Resolve the workdir through symlinks
  const resolvedWorkdir = await realpath(resolve(workdir));
  _workdir = resolvedWorkdir;


  _httpServer = createServer(async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`);

    // Only handle /mcp endpoint
    if (url.pathname !== '/mcp') {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found' }));
      return;
    }

    try {
      if (req.method === 'POST') {
        const body = await parseBody(req);
        const sessionId = req.headers['mcp-session-id'];

        if (sessionId && _sessions.has(sessionId)) {
          // Reuse existing session
          const transport = _sessions.get(sessionId);
          await transport.handleRequest(req, res, body);
          return;
        }

        if (isInitializeRequest(body)) {
          // Create new session with a new MCP server instance
          const transport = new StreamableHTTPServerTransport({
            sessionIdGenerator: () => randomUUID(),
            onsessioninitialized: (id) => {
              _sessions.set(id, transport);
            }
          });

          transport.onclose = () => {
            if (transport.sessionId) {
              _sessions.delete(transport.sessionId);
            }
          };

          // Each session gets its own McpServer for isolation
          const sessionServer = createMcpServer();
          await sessionServer.connect(transport);
          await transport.handleRequest(req, res, body);
          return;
        }

        // No valid session and not an initialize request
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32000, message: 'Invalid or missing session. Send an initialize request first.' },
          id: null
        }));

      } else if (req.method === 'GET') {
        // SSE streaming for existing sessions
        const sessionId = req.headers['mcp-session-id'];
        if (sessionId && _sessions.has(sessionId)) {
          const transport = _sessions.get(sessionId);
          await transport.handleRequest(req, res);
        } else {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid session for SSE' }));
        }

      } else if (req.method === 'DELETE') {
        // Session termination
        const sessionId = req.headers['mcp-session-id'];
        if (sessionId && _sessions.has(sessionId)) {
          const transport = _sessions.get(sessionId);
          await transport.handleRequest(req, res);
          _sessions.delete(sessionId);
        } else {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid session' }));
        }

      } else {
        res.writeHead(405, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Method not allowed' }));
      }
    } catch (err) {
      console.error('[MCP filesystem] Request error:', err);
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          jsonrpc: '2.0',
          error: { code: -32603, message: `Internal error: ${err.message}` },
          id: null
        }));
      }
    }
  });

  // Dynamic port on localhost only
  return new Promise((resolvePromise, reject) => {
    _httpServer.listen(0, '127.0.0.1', () => {
      const { port } = _httpServer.address();
      console.log(`[MCP filesystem] Server started on 127.0.0.1:${port} (workdir: ${_workdir})`);
      resolvePromise({
        port,
        close: () => stopServer()
      });
    });

    _httpServer.on('error', (err) => {
      _httpServer = null;
      reject(err);
    });
  });
}

/**
 * Stop the filesystem MCP server and clean up all sessions.
 * @returns {Promise<void>}
 */
export async function stopServer() {
  // Close all active sessions
  for (const [id, transport] of _sessions) {
    try {
      await transport.close?.();
    } catch {
      // Ignore close errors during shutdown
    }
    _sessions.delete(id);
  }

  if (_httpServer) {
    return new Promise((resolve, reject) => {
      _httpServer.close((err) => {
        _httpServer = null;
        _workdir = null;
        console.log('[MCP filesystem] Server stopped');
        if (err) reject(err);
        else resolve();
      });
    });
  }

  _workdir = null;
}
