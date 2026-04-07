"""Session state management for PDF translation pipeline.

Stores intermediate state (extracted text, positions, formulas, layout)
between extract and build phases using JSON files and numpy arrays.
"""

import json
import logging
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from pdf_translator.models import PageState, SessionMeta

logger = logging.getLogger(__name__)

SESSION_DIR = Path.home() / ".cache" / "pdf-translator-mcp" / "sessions"
SESSION_TTL_SECONDS = 3600  # 1 hour


def _ensure_session_dir():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def create_session_id() -> str:
    return uuid.uuid4().hex[:12]


def get_session_path(session_id: str) -> Path:
    return SESSION_DIR / session_id


def save_session(
    session_id: str,
    meta: SessionMeta,
    pages: list[PageState],
    layouts: dict[int, np.ndarray],
    doc_zh_bytes: bytes,
    font_ids: dict[str, int],
) -> Path:
    """Save session state to disk."""
    _ensure_session_dir()
    session_path = get_session_path(session_id)
    session_path.mkdir(parents=True, exist_ok=True)

    # Save metadata
    with open(session_path / "meta.json", "w", encoding="utf-8") as f:
        json.dump(meta.to_dict(), f, ensure_ascii=False, indent=2)

    # Save page states (JSON-safe)
    pages_data = [p.to_dict() for p in pages]
    with open(session_path / "pages.json", "w", encoding="utf-8") as f:
        json.dump(pages_data, f, ensure_ascii=False)

    # Save layout arrays as .npy
    for pageno, layout_arr in layouts.items():
        np.save(session_path / f"layout_{pageno}.npy", layout_arr)

    # Save PyMuPDF document as PDF bytes
    with open(session_path / "doc_zh.pdf", "wb") as f:
        f.write(doc_zh_bytes)

    # Save font IDs
    with open(session_path / "font_ids.json", "w", encoding="utf-8") as f:
        json.dump(font_ids, f)

    logger.info(f"Session {session_id} saved to {session_path}")
    return session_path


def load_session(session_id: str) -> tuple[SessionMeta, list[PageState], dict[int, np.ndarray], bytes, dict[str, int]]:
    """Load session state from disk."""
    session_path = get_session_path(session_id)
    if not session_path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")

    # Load metadata
    with open(session_path / "meta.json", "r", encoding="utf-8") as f:
        meta = SessionMeta.from_dict(json.load(f))

    # Load page states
    with open(session_path / "pages.json", "r", encoding="utf-8") as f:
        pages = [PageState.from_dict(p) for p in json.load(f)]

    # Load layout arrays
    layouts = {}
    for npy_file in session_path.glob("layout_*.npy"):
        pageno = int(npy_file.stem.split("_")[1])
        layouts[pageno] = np.load(npy_file)

    # Load PyMuPDF document bytes
    with open(session_path / "doc_zh.pdf", "rb") as f:
        doc_zh_bytes = f.read()

    # Load font IDs
    with open(session_path / "font_ids.json", "r", encoding="utf-8") as f:
        font_ids = json.load(f)

    return meta, pages, layouts, doc_zh_bytes, font_ids


def cleanup_session(session_id: str):
    """Remove a session directory."""
    session_path = get_session_path(session_id)
    if session_path.exists():
        shutil.rmtree(session_path)
        logger.info(f"Session {session_id} cleaned up")


def cleanup_expired_sessions():
    """Remove sessions older than TTL."""
    _ensure_session_dir()
    now = time.time()
    for session_dir in SESSION_DIR.iterdir():
        if not session_dir.is_dir():
            continue
        meta_file = session_dir / "meta.json"
        if not meta_file.exists():
            shutil.rmtree(session_dir)
            continue
        try:
            with open(meta_file, "r") as f:
                meta = json.load(f)
            created = datetime.fromisoformat(meta["created_at"]).timestamp()
            if now - created > SESSION_TTL_SECONDS:
                shutil.rmtree(session_dir)
                logger.info(f"Expired session removed: {session_dir.name}")
        except Exception:
            pass
