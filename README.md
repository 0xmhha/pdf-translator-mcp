# pdf-translator-mcp

[![Release](https://img.shields.io/github/v/release/0xmhha/pdf-translator-mcp?include_prereleases&sort=semver)](https://github.com/0xmhha/pdf-translator-mcp/releases)
[![CI](https://github.com/0xmhha/pdf-translator-mcp/actions/workflows/release.yml/badge.svg)](https://github.com/0xmhha/pdf-translator-mcp/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](#license)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![MCP](https://img.shields.io/badge/MCP-FastMCP-informational)](https://modelcontextprotocol.io/)

An MCP server that lets Claude Code translate academic PDFs while **preserving formulas, figures, tables, and page layout**. The server extracts text chunks from a PDF, hands them to the model for translation, then rebuilds a new PDF — so Claude does the language work and the server does the PDF surgery.

---

## Why this exists

Translating scientific papers by copy/pasting loses math, citations, and figure placement. Off-the-shelf PDF translators either mangle equations or ship opaque neural pipelines. `pdf-translator-mcp` splits the problem:

- **This server** parses the PDF layout (using DocLayout-YOLO for figure/formula detection) and hands Claude clean text chunks with formula placeholders (`{v0}`, `{v1}`, …).
- **Claude** translates the chunks, preserving placeholders.
- **This server** rebuilds the PDF, re-flowing translated text and putting formulas back exactly where they were.

You get a bilingual (dual) and a translated-only (mono) PDF per run.

## Features

- **Layout-aware extraction** — formulas, figures, tables, and columns are detected and preserved.
- **Model-agnostic translation** — the MCP host (Claude Code, Claude Desktop, or any MCP client) supplies the translations; no third-party API keys live in this server.
- **Self-contained binaries** — prebuilt for macOS (arm64/x86_64) and Linux (x86_64/arm64). No Python install required on the host machine.
- **Zero-network mode after first run** — the ONNX layout model is cached locally after initial download.
- **Three focused MCP tools** (see [Tools](#tools)).

## Installation

Pick whichever path matches your environment.

### Option 1 — Prebuilt binary (recommended)

No Python, no `uv`, no build step. Each GitHub Release ships a single executable per platform.

1. Go to [Releases](https://github.com/0xmhha/pdf-translator-mcp/releases) and download the archive for your platform:

   | Platform        | Asset                                          |
   |-----------------|------------------------------------------------|
   | macOS (Apple)   | `pdf-translator-mcp-macos-arm64.tar.gz`        |
   | macOS (Intel)   | `pdf-translator-mcp-macos-x86_64.tar.gz`       |
   | Linux (x86_64)  | `pdf-translator-mcp-linux-x86_64.tar.gz`       |
   | Linux (arm64)   | `pdf-translator-mcp-linux-arm64.tar.gz`        |

2. Extract and place on your `PATH`:

   ```bash
   tar -xzf pdf-translator-mcp-<platform>.tar.gz
   install -m 0755 pdf-translator-mcp "$HOME/.local/bin/"
   ```

3. (Optional) Verify the checksum:

   ```bash
   shasum -a 256 -c pdf-translator-mcp-<platform>.tar.gz.sha256
   ```

4. Configure Claude Code — see [Configuration](#configuration).

### Option 2 — Run from source with `uv`

Requires [`uv`](https://github.com/astral-sh/uv) and Python 3.10+.

```bash
git clone https://github.com/0xmhha/pdf-translator-mcp.git
cd pdf-translator-mcp
uv sync
```

Then point your MCP client at `uv run pdf-translator-mcp` (see [Configuration](#configuration)).

### Option 3 — Build your own binary

See [Building from source](#building-from-source) below. This is the same PyInstaller pipeline the CI uses.

## Configuration

Add the server to your MCP client's config file.

### Claude Code — project-scoped (`.mcp.json` in repo root)

**If you installed the prebuilt binary:**

```json
{
  "mcpServers": {
    "pdf-translator": {
      "command": "pdf-translator-mcp"
    }
  }
}
```

**If you're running from source:**

```json
{
  "mcpServers": {
    "pdf-translator": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/pdf-translator-mcp",
        "run",
        "pdf-translator-mcp"
      ]
    }
  }
}
```

### Claude Code — user-scoped (applies to all projects)

Register once via the CLI:

```bash
claude mcp add pdf-translator -s user -- pdf-translator-mcp
```

### Other MCP clients

The server speaks standard MCP over stdio. Any client that accepts a command + args works — point it at the `pdf-translator-mcp` binary (or `uv run pdf-translator-mcp` from source).

## Usage

Once the server is configured, you can ask Claude naturally:

> "Translate `paper.pdf` to Korean, pages 1–3"

Under the hood Claude will:

1. Call `extract_pdf` → gets a `session_id` and a list of text chunks.
2. Translate each chunk locally (it's just a language model task).
3. Call `build_translated_pdf` with the translations → gets back two files:
   - `<name>-<lang>-mono.pdf` — translation only
   - `<name>-<lang>-dual.pdf` — original and translation side-by-side

The output directory defaults to `./<basename>-<lang_out>/` next to the source PDF.

## Tools

All tools are standard MCP tools discoverable via `tools/list`.

| Tool                    | Purpose                                                        | Key arguments                                                |
|-------------------------|----------------------------------------------------------------|--------------------------------------------------------------|
| `analyze_pdf`           | Inspect a PDF before translating — page count, chunks, fonts.  | `file`                                                       |
| `extract_pdf`           | Parse layout and return text chunks to translate.              | `file`, `lang_in`, `lang_out`, `pages` (e.g. `"1-5"`)        |
| `build_translated_pdf`  | Reassemble a translated PDF from an extraction session.        | `session_id`, `translations` (JSON: `{chunk_id: text}`)      |

Formula segments in chunks appear as placeholders like `{v0}`, `{v1}`. These **must be preserved verbatim** in translations — they're how the server re-inserts the original math.

## How it works

```
 ┌──────────┐      extract_pdf       ┌─────────────────┐
 │  PDF in  │ ─────────────────────▶ │  DocLayout-YOLO │──── chunks ───┐
 └──────────┘                        │  + pdfminer six │               │
                                     └─────────────────┘               ▼
                                                              ┌────────────────┐
                                                              │ Claude (host)  │
                                                              │   translates    │
                                                              └────────┬───────┘
                                                                       │ translations
                                                                       ▼
                                                              ┌─────────────────┐
                                                              │ build_translated │── mono.pdf
                                                              │ _pdf (pymupdf)   │── dual.pdf
                                                              └─────────────────┘
```

- **Layout detection**: [`DocLayout-YOLO`](https://github.com/opendatalab/DocLayout-YOLO) ONNX model, downloaded on first run to `~/.cache/babeldoc/models/`.
- **Text extraction & font handling**: `pdfminer.six` + `pymupdf`.
- **Rebuild**: `pymupdf` writes translated glyphs using bundled Noto fonts fetched from [babeldoc assets](https://github.com/funstory-ai/BabelDOC).

## Requirements

- **End users (prebuilt binary)**: macOS 12+ (arm64 or x86_64) or Linux (glibc 2.31+, x86_64 or arm64).
- **From source**: Python ≥ 3.10 and [`uv`](https://github.com/astral-sh/uv).
- **Network (first run only)**: outbound HTTPS to download the ONNX layout model and Noto fonts. After caching, the server runs fully offline.

## Development

### Project layout

```
pdf_translator/          # Python package (MCP server + PDF pipeline)
  mcp_server.py          # FastMCP entrypoint + 3 tools
  extractor.py           # extract_pdf implementation
  builder.py             # build_translated_pdf implementation
  doclayout.py           # YOLO layout model wrapper
  converter_{extract,build}.py
  pdfinterp.py           # pdfminer interpreter overrides
scripts/
  build-local.sh         # uv sync + pyinstaller + smoke test
  e2e-smoke.py           # JSON-RPC roundtrip against the frozen binary
pdf_translator_mcp.spec  # PyInstaller spec (collect_all for native deps)
.github/workflows/
  release.yml            # multi-platform binary build on `v*` tag push
```

### Setup

```bash
git clone https://github.com/0xmhha/pdf-translator-mcp.git
cd pdf-translator-mcp
uv sync --group dev
uv run pdf-translator-mcp   # sanity-check the server boots
```

### Building from source

Reproduces exactly what CI does for a single platform:

```bash
./scripts/build-local.sh
# → dist/pdf-translator-mcp (single-file executable, ~200 MB)
```

The build bundles `pymupdf`, `onnxruntime`, `opencv`, `pdfminer-six`, `babeldoc`, and the MCP SDK into one executable. The ONNX layout model is **not** bundled — it's fetched on first run (≈ 20 MB, one-time).

### End-to-end smoke test

Drives the built binary over real MCP JSON-RPC, extracts the first page of a PDF, and builds a pass-through translated PDF back:

```bash
python3 scripts/e2e-smoke.py dist/pdf-translator-mcp path/to/some.pdf
```

## Release process

Binaries are built **only on tag push** (`v*`), never on regular commits. The workflow matrix produces macOS arm64/x86_64 and Linux x86_64/arm64 archives plus SHA-256 checksums, then attaches them to a GitHub Release.

To cut a release (maintainers):

```bash
# Pre-release candidate
git tag v0.2.0-rc1 && git push origin v0.2.0-rc1

# Stable release
git tag v0.2.0 && git push origin v0.2.0
```

Follow the Actions run at [Actions → Release Binaries](https://github.com/0xmhha/pdf-translator-mcp/actions/workflows/release.yml).

## Contributing

Issues and PRs are welcome. Please read [CONTRIBUTING.md](./CONTRIBUTING.md) before submitting — it covers the development setup, style rules, testing expectations, and PR checklist.

## License

[MIT](./LICENSE).

## Acknowledgments

- [scholar-translator](https://github.com/scholarpdf/scholar-translator) — original inspiration for the layout-preserving pipeline.
- [BabelDOC](https://github.com/funstory-ai/BabelDOC) — ONNX layout model hosting, font assets, and download helpers.
- [DocLayout-YOLO](https://github.com/opendatalab/DocLayout-YOLO) — document structure detection model.
- [Model Context Protocol](https://modelcontextprotocol.io/) & [FastMCP](https://github.com/jlowin/fastmcp) — the server plumbing.
