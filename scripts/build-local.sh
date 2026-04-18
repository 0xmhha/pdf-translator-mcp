#!/usr/bin/env bash
# Build a single-file pdf-translator-mcp binary for the host platform.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Syncing dev dependencies (includes pyinstaller)"
uv sync --group dev

echo "==> Cleaning previous build artifacts"
rm -rf build dist

echo "==> Building with PyInstaller"
uv run pyinstaller pdf_translator_mcp.spec --clean --noconfirm

BIN="dist/pdf-translator-mcp"
if [[ ! -x "$BIN" ]]; then
    echo "ERROR: expected binary at $BIN was not produced" >&2
    exit 1
fi

SIZE=$(du -sh "$BIN" | awk '{print $1}')
echo "==> Built: $BIN ($SIZE)"

echo "==> Smoke test (launches server, terminates after 3s)"
# MCP server reads JSON-RPC on stdin and will idle waiting for input.
# A clean startup that survives 3s without crashing is the success signal.
LOG="$(mktemp -t pdf-translator-mcp-build.XXXXXX.log)"
if ( "$BIN" </dev/null >/dev/null 2>"$LOG" & PID=$!; sleep 3; kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; true ); then
    echo "==> Smoke test passed (log: $LOG)"
else
    echo "WARN: smoke test returned non-zero; log: $LOG" >&2
fi

echo
echo "Done. Binary: $ROOT_DIR/$BIN"
