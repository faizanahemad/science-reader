/**
 * Path sandboxing utility for the filesystem MCP server.
 * Ensures all file operations stay within the configured workdir.
 */
import { resolve, normalize, dirname, isAbsolute } from 'node:path';
import { realpath } from 'node:fs/promises';

/**
 * Normalize a path: resolve `.` and `..`, normalize slashes.
 * @param {string} p - Path to normalize
 * @returns {string} Normalized path
 */
export function normalizePath(p) {
  return normalize(resolve(p));
}

/**
 * Validate that a requested path is within the sandbox workdir.
 * Handles symlinks, relative paths, and non-existent paths (validates parent).
 *
 * @param {string} requestedPath - The path requested by the tool caller
 * @param {string} workdir - The sandbox root directory
 * @returns {Promise<string>} The resolved, validated absolute path
 * @throws {Error} If the path is outside the sandbox
 */
export async function validatePath(requestedPath, workdir) {
  // Resolve the workdir itself through symlinks (e.g. /tmp -> /private/tmp on macOS)
  const realWorkdir = await realpath(workdir);

  // Resolve the requested path: relative to workdir, absolute as-is
  const resolved = isAbsolute(requestedPath)
    ? normalize(requestedPath)
    : normalize(resolve(realWorkdir, requestedPath));

  // Try to resolve through symlinks for existing paths
  try {
    const realResolved = await realpath(resolved);

    // Check the real path is within the real workdir
    if (!realResolved.startsWith(realWorkdir + '/') && realResolved !== realWorkdir) {
      throw new Error(
        `Path "${requestedPath}" resolves to "${realResolved}" which is outside the sandbox "${realWorkdir}"`
      );
    }
    return realResolved;
  } catch (err) {
    if (err.code === 'ENOENT') {
      // Path doesn't exist yet — validate the parent directory instead
      const parentDir = dirname(resolved);
      try {
        const realParent = await realpath(parentDir);
        if (!realParent.startsWith(realWorkdir + '/') && realParent !== realWorkdir) {
          throw new Error(
            `Path "${requestedPath}" has parent "${realParent}" which is outside the sandbox "${realWorkdir}"`
          );
        }
        // Return the resolved path with the real parent + original filename
        return resolve(realParent, resolved.slice(parentDir.length + 1));
      } catch (parentErr) {
        if (parentErr.code === 'ENOENT') {
          // Parent also doesn't exist — validate against normalized workdir
          if (!resolved.startsWith(realWorkdir + '/') && resolved !== realWorkdir) {
            throw new Error(
              `Path "${requestedPath}" resolves to "${resolved}" which is outside the sandbox "${realWorkdir}"`
            );
          }
          return resolved;
        }
        // Re-throw sandbox violations, but wrap other errors
        if (parentErr.message.includes('outside the sandbox')) throw parentErr;
        throw parentErr;
      }
    }
    // Re-throw sandbox violations from the realpath check
    if (err.message.includes('outside the sandbox')) throw err;
    throw err;
  }
}
