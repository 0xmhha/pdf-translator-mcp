"""PDF rebuild orchestrator.

Takes a session (extracted state) and translated text chunks,
then rebuilds the PDF with translated content.
"""

import logging
import re
from pathlib import Path

from pymupdf import Document, Font

from pdf_translator.converter_build import BuildConverter
from pdf_translator.font import NOTO_NAME
from pdf_translator.models import PageState
from pdf_translator.session import load_session, cleanup_session

logger = logging.getLogger(__name__)


def build_translated_pdf(
    session_id: str,
    translations: dict[str, str],
    output_dir: str = "",
) -> dict:
    """Build translated PDF from session state + translations.

    Args:
        session_id: Session ID from extract_pdf.
        translations: Dict mapping chunk_id (str) to translated text.
        output_dir: Output directory path. If empty, uses cwd/{filename}-{lang_out}/.

    Returns:
        Dict with output paths and stats.
    """
    meta, pages, layouts, doc_zh_bytes, font_ids = load_session(session_id)

    # Restore PyMuPDF document
    doc_zh = Document(stream=doc_zh_bytes)

    # Restore font
    noto = Font(meta.noto_name, meta.font_path)

    # Build a global chunk_id → (page_state_index, sstk_index) mapping
    # and a reverse mapping from chunk_id → translated text
    chunk_translations = {int(k): v for k, v in translations.items()}

    # Map chunk IDs back to per-page sstk indices
    page_translations: dict[int, dict[int, str]] = {}
    chunk_id = 0
    for ps in pages:
        for i, text in enumerate(ps.sstk):
            if text.strip() and not re.match(r"^\{v\d+\}$", text):
                if chunk_id in chunk_translations:
                    if ps.pageno not in page_translations:
                        page_translations[ps.pageno] = {}
                    page_translations[ps.pageno][i] = chunk_translations[chunk_id]
            chunk_id += 1

    # For build, we need fontmap and fontid from the interpreter.
    # Since we don't have the original interpreter state, we need to
    # reconstruct a minimal fontmap. The BuildConverter uses fontmap
    # primarily for raw_string encoding (CID font detection) and char width.
    # For formula characters, font_id is stored in FormulaChar.

    # We'll create a stub fontmap that handles the basic cases.
    # The noto font handles most translated text.
    fontmap = {}
    fontid = {}

    # Build each page
    builder = BuildConverter(
        noto_name=meta.noto_name,
        noto=noto,
        fontmap=fontmap,
        fontid=fontid,
        lang_out=meta.lang_out,
    )

    chunks_translated = 0
    for ps in pages:
        translations_for_page = page_translations.get(ps.pageno, {})
        chunks_translated += len(translations_for_page)

        ops = builder.build_page_ops(ps, translations_for_page)

        # Apply ops to doc_zh
        if ps.page_xref and ps.page_xref > 0:
            doc_zh.update_stream(ps.page_xref, ops.encode())

    # Create dual document (original + translated interleaved)
    with open(meta.file_path, "rb") as f:
        doc_en = Document(stream=f.read())

    doc_en.insert_file(doc_zh)
    for i in range(meta.page_count):
        doc_en.move_page(meta.page_count + i, i * 2 + 1)

    doc_zh.subset_fonts(fallback=True)
    doc_en.subset_fonts(fallback=True)

    # Determine output directory
    if output_dir:
        out_path = Path(output_dir)
    else:
        out_path = Path.cwd() / f"{meta.file_name}-{meta.lang_out}"
    out_path.mkdir(parents=True, exist_ok=True)

    mono_path = out_path / f"{meta.file_name}-{meta.lang_out}-mono.pdf"
    dual_path = out_path / f"{meta.file_name}-{meta.lang_out}-dual.pdf"

    with open(mono_path, "wb") as f:
        f.write(doc_zh.write(deflate=True, garbage=3, use_objstms=1))
    with open(dual_path, "wb") as f:
        f.write(doc_en.write(deflate=True, garbage=3, use_objstms=1))

    doc_en.close()
    doc_zh.close()

    # Cleanup session
    cleanup_session(session_id)

    return {
        "status": "success",
        "output": {
            "mono": str(mono_path.absolute()),
            "dual": str(dual_path.absolute()),
        },
        "stats": {
            "chunks_translated": chunks_translated,
            "pages_processed": len(pages),
        },
    }
