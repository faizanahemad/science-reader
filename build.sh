#!/usr/bin/env bash
#
# build.sh — Production build script for Chrome Web Store packaging.
#
# Replaces symlinks to extension-shared/ with actual file copies so each
# extension directory is self-contained. Run this before zipping extensions
# for Chrome Web Store upload.
#
# Usage:
#   ./build.sh              # Build all extensions
#   ./build.sh extension/   # Build specific extension directory
#
# Created: 2026-02-19
# Part of: Three-Extension Architecture
#

set -euo pipefail

SHARED_DIR="extension-shared"
EXTENSION_DIRS=("extension" "extension-iframe")

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[BUILD]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# If specific directory provided, only build that one
if [ $# -gt 0 ]; then
    EXTENSION_DIRS=("$@")
fi

# Verify extension-shared exists
if [ ! -d "$SHARED_DIR" ]; then
    log_error "Shared directory '$SHARED_DIR' not found. Run from repo root."
    exit 1
fi

replaced=0
skipped=0

for ext_dir in "${EXTENSION_DIRS[@]}"; do
    if [ ! -d "$ext_dir" ]; then
        log_warn "Directory '$ext_dir' does not exist, skipping."
        continue
    fi

    log_info "Processing $ext_dir/"

    # Find all symlinks that point to extension-shared/
    while IFS= read -r -d '' symlink; do
        target=$(readlink "$symlink" 2>/dev/null || true)

        # Check if symlink points to extension-shared (relative or absolute)
        if [[ "$target" == *"$SHARED_DIR"* ]]; then
            # Resolve to actual file
            resolved=$(cd "$(dirname "$symlink")" && realpath "$target" 2>/dev/null || true)

            if [ -f "$resolved" ]; then
                log_info "  Replacing: $symlink -> $target"
                rm "$symlink"
                cp "$resolved" "$symlink"
                replaced=$((replaced + 1))
            else
                log_error "  Symlink target not found: $symlink -> $target (resolved: $resolved)"
                skipped=$((skipped + 1))
            fi
        fi
    done < <(find "$ext_dir" -type l -print0 2>/dev/null)
done

echo ""
log_info "Build complete: $replaced symlinks replaced, $skipped skipped."

# Verify no remaining symlinks to extension-shared
remaining=0
for ext_dir in "${EXTENSION_DIRS[@]}"; do
    if [ -d "$ext_dir" ]; then
        while IFS= read -r -d '' symlink; do
            target=$(readlink "$symlink" 2>/dev/null || true)
            if [[ "$target" == *"$SHARED_DIR"* ]]; then
                log_warn "Remaining symlink: $symlink -> $target"
                remaining=$((remaining + 1))
            fi
        done < <(find "$ext_dir" -type l -print0 2>/dev/null)
    fi
done

if [ "$remaining" -gt 0 ]; then
    log_warn "$remaining symlinks still reference $SHARED_DIR"
    exit 1
else
    log_info "All extensions are self-contained. Ready for packaging."
fi
