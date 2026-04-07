# pdf-translator-mcp

PDF Translation MCP Server for Claude Code.

Extracts text from academic PDFs (preserving formulas, figures, tables) and rebuilds translated PDFs — letting Claude Code handle the translation itself.

## Setup

```bash
uv sync
```

## Usage with Claude Code

Add to `.mcp.json`:

```json
{
  "mcpServers": {
    "pdf-translator": {
      "command": "uv",
      "args": ["--directory", "/path/to/pdf-translator-mcp", "run", "pdf-translator-mcp"]
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `extract_pdf` | Extract text chunks from PDF |
| `build_translated_pdf` | Rebuild PDF with translated text |
| `analyze_pdf` | Analyze PDF structure |
