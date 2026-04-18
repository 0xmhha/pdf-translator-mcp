#!/usr/bin/env python3
"""E2E smoke test for the PyInstaller-built pdf-translator-mcp binary.

Drives the frozen MCP server over stdio:
  1. initialize handshake
  2. extract_pdf on a small PDF (page 1 only)
  3. build_translated_pdf using the extracted chunks as "translations"
     (pass-through, just exercising the full pipeline)

Prints ✅ on success, ❌ on failure. Exits non-zero on failure.

Usage:
    python scripts/e2e-smoke.py <path-to-binary> <path-to-pdf>
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def send(proc: subprocess.Popen, msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    assert proc.stdin is not None
    proc.stdin.write(line)
    proc.stdin.flush()


def recv(proc: subprocess.Popen, expect_id: int | None = None, timeout: float = 120.0) -> dict:
    """Read JSON-RPC messages, skipping notifications until a response arrives.

    If expect_id is given, keep reading until a message with matching id appears —
    server progress notifications (method="notifications/message") are discarded.
    """
    assert proc.stdout is not None
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise RuntimeError(f"server exited early with code {proc.returncode}")
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if expect_id is not None and msg.get("id") != expect_id:
            # It's a notification or a response for a different request; skip.
            continue
        return msg
    raise TimeoutError(f"No response within {timeout}s")


def unwrap_tool_result(rpc_response: dict) -> dict:
    """FastMCP returns tool results as a TextContent block; unwrap to JSON."""
    result = rpc_response["result"]
    content = result["content"][0]["text"]
    return json.loads(content)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    binary = Path(sys.argv[1]).resolve()
    pdf = Path(sys.argv[2]).resolve()
    if not binary.is_file():
        print(f"❌ Binary not found: {binary}")
        return 1
    if not pdf.is_file():
        print(f"❌ PDF not found: {pdf}")
        return 1

    print(f"→ Launching: {binary.name}")
    proc = subprocess.Popen(
        [str(binary)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        # 1) initialize
        send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "e2e-smoke", "version": "0"},
            },
        })
        init = recv(proc, expect_id=1, timeout=30)
        assert "result" in init, f"init failed: {init}"
        print(f"  ✓ initialized: {init['result']['serverInfo']['name']}")

        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 2) extract_pdf (page 1 only for speed; model download may take a while)
        print("→ Calling extract_pdf (first run downloads ONNX model, may take a minute)…")
        send(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "extract_pdf",
                "arguments": {"file": str(pdf), "lang_in": "en", "lang_out": "ko", "pages": "1"},
            },
        })
        extract_resp = recv(proc, expect_id=2, timeout=300)
        if "result" not in extract_resp:
            print(f"❌ extract_pdf raw response: {json.dumps(extract_resp, ensure_ascii=False)[:2000]}")
            print("--- stderr tail ---")
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                _, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                _, err = proc.communicate()
            print(err[-2000:] if err else "(no stderr)")
            return 1
        extracted = unwrap_tool_result(extract_resp)
        if "error" in extracted:
            print(f"❌ extract_pdf failed: {extracted['error']}")
            return 1

        session_id = extracted["session_id"]
        chunks = extracted["chunks"]
        print(f"  ✓ extracted {len(chunks)} chunks, session={session_id}")
        if not chunks:
            print("❌ no chunks extracted — PDF may be empty or layout model misfired")
            return 1

        # 3) build_translated_pdf — pass-through "translations"
        print("→ Calling build_translated_pdf (pass-through translations)…")
        translations = {str(c["id"]): c["text"] for c in chunks}
        send(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "build_translated_pdf",
                "arguments": {"session_id": session_id, "translations": json.dumps(translations)},
            },
        })
        build_resp = recv(proc, expect_id=3, timeout=180)
        built = unwrap_tool_result(build_resp)
        if "error" in built:
            print(f"❌ build_translated_pdf failed: {built['error']}")
            return 1

        print(f"  ✓ build result: {json.dumps(built, ensure_ascii=False)[:300]}…")

        # Verify output files actually exist
        output = built.get("output", {})
        mono = output.get("mono")
        dual = output.get("dual")
        for label, path in (("mono", mono), ("dual", dual)):
            if path and Path(path).is_file():
                size = Path(path).stat().st_size
                print(f"  ✓ {label}: {path} ({size:,} bytes)")
            else:
                print(f"⚠️  {label} not found at {path}")

        print("\n✅ E2E smoke test passed")
        return 0

    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
