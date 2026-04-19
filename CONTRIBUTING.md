# Contributing to pdf-translator-mcp

Thanks for taking the time to contribute. This guide explains how to report issues, set up a development environment, and submit changes.

By participating in this project you agree to engage respectfully and in good faith with other contributors.

## Ways to contribute

- **Reporting bugs** — if the server crashes, produces broken PDFs, or misbehaves with a real paper, file an issue with enough detail to reproduce.
- **Suggesting features** — open an issue first and describe the problem you're trying to solve. We'd rather discuss approach before you write code.
- **Improving docs** — README fixes, typo corrections, and clearer examples are always welcome.
- **Code changes** — bug fixes, new layout heuristics, additional MCP tools, better font handling, etc.
- **Testing on new platforms** — especially edge cases on Linux distros or older macOS versions.

## Filing an issue

Please include:

1. **What you did** — the exact command or MCP call, including file paths.
2. **What happened** — error message, stack trace, or unexpected output (attach if possible).
3. **What you expected** — one sentence is fine.
4. **Environment**:
   - OS and architecture (e.g. `macOS 14.5 arm64`, `Ubuntu 24.04 x86_64`).
   - Install method (prebuilt binary version, or commit SHA if running from source).
   - Python version (if from source).
5. **PDF sample** — if the issue is PDF-specific and the document isn't sensitive, attach a minimal reproducer (even a single page often helps).

For security-sensitive reports, please do **not** file a public issue — email the maintainer instead.

## Development setup

Requires [`uv`](https://github.com/astral-sh/uv) and Python ≥ 3.10.

```bash
git clone https://github.com/0xmhha/pdf-translator-mcp.git
cd pdf-translator-mcp
uv sync --group dev
```

Run the server from source to sanity-check:

```bash
uv run pdf-translator-mcp
# speaks MCP JSON-RPC on stdio; Ctrl+C to exit
```

## Making changes

### Branching

Create a feature branch off `main`:

```bash
git checkout -b feat/descriptive-name
```

### Code style

- **Formatter + linter**: [`ruff`](https://github.com/astral-sh/ruff). Run both before committing:

  ```bash
  uv run ruff format .
  uv run ruff check .
  ```

- **Python style**: keep modules focused (see existing split between `extractor.py`, `builder.py`, `converter_*.py`). Prefer small, testable functions. Avoid adding dependencies unless there's no reasonable alternative — this project already carries a heavy native stack (`pymupdf`, `onnxruntime`, `opencv`) and each new library inflates the binary.
- **Comments**: explain *why*, not *what*. If a future reader can infer the intent from the code, skip the comment.

### Testing your change

**Fast iteration** — run the server from source directly via your MCP client (Claude Code). The source path avoids rebuilding the binary.

**Before opening a PR** — build a binary and run the E2E smoke test against a real PDF:

```bash
./scripts/build-local.sh
python3 scripts/e2e-smoke.py dist/pdf-translator-mcp path/to/paper.pdf
```

This catches:

- PyInstaller hidden-import regressions (runtime `ModuleNotFoundError`).
- Native-library bundling problems surfaced only in the frozen build.
- JSON-RPC contract breakage (tool schemas, response shapes).

If you touched extraction or building, also inspect the output `mono`/`dual` PDFs visually — the server can succeed silently and still produce garbage layout.

### Commit messages

Conventional-style prefixes, short imperative subject, wrap at ~72 chars:

```
feat: preserve footnote superscripts across chunks
fix: handle single-column layout on arxiv preprints
ci: cache uv virtualenv between release workflow runs
docs: clarify placeholder preservation rules
refactor: extract font fallback logic into font.py
```

Keep each commit focused and reviewable. Unrelated changes belong in separate commits.

## Submitting a pull request

1. Push your branch and open a PR against `main`.
2. **In the PR description**, cover:
   - What problem the change solves.
   - How it solves it (one or two paragraphs).
   - Any tradeoffs or alternatives you considered.
   - How you tested it (command + expected output, or screenshots for layout changes).
3. Link the related issue if one exists (`Fixes #123`).
4. Expect review comments — they're about making the change better, not gatekeeping. Feel free to push back with reasoning.

### Pull request checklist

- [ ] `uv run ruff format .` and `uv run ruff check .` pass.
- [ ] `./scripts/build-local.sh` succeeds locally for at least your own platform.
- [ ] `python3 scripts/e2e-smoke.py dist/pdf-translator-mcp <pdf>` succeeds.
- [ ] New/changed public behavior is covered in README or docstrings.
- [ ] No new dependencies added without justification in the PR description.
- [ ] Commit history is clean (squash fixups locally before requesting review).

## Releases

Releases are maintainer-only. Binaries are built by the `.github/workflows/release.yml` matrix on `v*` tag push — regular commits never produce releases. If a change you're making needs to be validated across all four target platforms (macOS arm64/x86_64, Linux x86_64/arm64) before merge, flag that in the PR and a maintainer can cut a pre-release candidate (`vX.Y.Z-rcN`).

## Questions

If anything in this guide is unclear, open an issue or ask in a draft PR. Don't let uncertainty block you from contributing.
