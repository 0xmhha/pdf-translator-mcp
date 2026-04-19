"""PDF text extraction orchestrator.

Processes a PDF file through the extraction pipeline:
PDF bytes → DocLayout-YOLO → pdfminer → text chunks + session state.
"""

import io
import logging
import re
from datetime import datetime
from typing import Optional

import numpy as np
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pymupdf import Document, Font

from pdf_translator.converter_extract import ExtractConverter
from pdf_translator.doclayout import DocLayoutModel, OnnxModel
from pdf_translator.font import NOTO_NAME, download_font
from pdf_translator.models import Chunk, SessionMeta
from pdf_translator.pdfinterp import PDFPageInterpreterEx
from pdf_translator.session import create_session_id, save_session

logger = logging.getLogger(__name__)

_model: OnnxModel = None


def _get_model() -> OnnxModel:
    global _model
    if _model is None:
        _model = DocLayoutModel.load_available()
    return _model


def extract_pdf(
    file_path: str,
    lang_in: str = "en",
    lang_out: str = "ko",
    pages_range: Optional[str] = None,
) -> tuple[str, list[Chunk], SessionMeta]:
    """Extract text chunks from a PDF file.

    Returns:
        Tuple of (session_id, chunks, metadata).
    """
    model = _get_model()

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    # Parse page range
    target_pages = _parse_pages(pages_range) if pages_range else None

    # Prepare fonts
    font_path = download_font(lang_out)
    noto_name = NOTO_NAME
    noto = Font(noto_name, font_path)

    # Prepare PyMuPDF documents
    doc_en = Document(stream=file_bytes)
    stream = io.BytesIO()
    doc_en.save(stream)
    doc_zh = Document(stream=stream)
    page_count = doc_zh.page_count

    # Insert fonts into all pages
    font_list = [("tiro", None), (noto_name, font_path)]
    font_id = {}
    for page in doc_zh:
        for font in font_list:
            font_id[font[0]] = page.insert_font(font[0], font[1])

    # Fix font resources in xrefs
    xreflen = doc_zh.xref_length()
    for xref in range(1, xreflen):
        for label in ["Resources/", ""]:
            try:
                font_res = doc_zh.xref_get_key(xref, f"{label}Font")
                target_key_prefix = f"{label}Font/"
                if font_res[0] == "xref":
                    resource_xref_id = re.search(r"(\d+) 0 R", font_res[1]).group(1)
                    xref_id = int(resource_xref_id)
                    font_res = ("dict", doc_zh.xref_object(xref_id))
                    target_key_prefix = ""
                if font_res[0] == "dict":
                    for font in font_list:
                        target_key = f"{target_key_prefix}{font[0]}"
                        font_exist = doc_zh.xref_get_key(xref, target_key)
                        if font_exist[0] == "null":
                            doc_zh.xref_set_key(
                                xref, target_key, f"{font_id[font[0]]} 0 R"
                            )
            except Exception:
                pass

    # Save prepared doc_zh for build phase
    fp = io.BytesIO()
    doc_zh.save(fp)

    # Run extraction
    rsrcmgr = PDFResourceManager()
    layout = {}
    device = ExtractConverter(
        rsrcmgr,
        vfont="",
        vchar="",
        layout=layout,
        noto_name=noto_name,
        noto=noto,
    )

    obj_patch = {}
    interpreter = PDFPageInterpreterEx(rsrcmgr, device, obj_patch)

    parser = PDFParser(fp)
    doc = PDFDocument(parser)

    page_xref_map: dict[int, int] = {}

    for pageno, page in enumerate(PDFPage.create_pages(doc)):
        if target_pages and pageno not in target_pages:
            continue

        page.pageno = pageno

        # Get page image for layout detection
        pix = doc_zh[page.pageno].get_pixmap()
        image = np.frombuffer(pix.samples, np.uint8).reshape(
            pix.height, pix.width, 3
        )[:, :, ::-1]

        # Detect layout
        page_layout = model.predict(image, imgsz=int(pix.height / 32) * 32)[0]

        # Build exclusion mask
        box = np.ones((pix.height, pix.width))
        h, w = box.shape
        vcls = ["abandon", "figure", "table", "isolate_formula", "formula_caption"]
        for i, d in enumerate(page_layout.boxes):
            if page_layout.names[int(d.cls)] not in vcls:
                x0, y0, x1, y1 = d.xyxy.squeeze()
                x0, y0, x1, y1 = (
                    np.clip(int(x0 - 1), 0, w - 1),
                    np.clip(int(h - y1 - 1), 0, h - 1),
                    np.clip(int(x1 + 1), 0, w - 1),
                    np.clip(int(h - y0 + 1), 0, h - 1),
                )
                box[y0:y1, x0:x1] = i + 2
        for i, d in enumerate(page_layout.boxes):
            if page_layout.names[int(d.cls)] in vcls:
                x0, y0, x1, y1 = d.xyxy.squeeze()
                x0, y0, x1, y1 = (
                    np.clip(int(x0 - 1), 0, w - 1),
                    np.clip(int(h - y1 - 1), 0, h - 1),
                    np.clip(int(x1 + 1), 0, w - 1),
                    np.clip(int(h - y0 + 1), 0, h - 1),
                )
                box[y0:y1, x0:x1] = 0
        layout[page.pageno] = box

        # Create a fresh xref for the translated page content and make it the
        # sole entry in the page's /Contents.
        #
        # NOTE on empty vs. placeholder streams: set_contents() only reliably
        # persists through the save/reload cycle when the write() call uses
        # garbage>=2. But garbage collection also prunes xrefs whose streams are
        # empty. So we seed the new stream with a minimal valid PDF operation
        # ("BT ET") — this is a no-op text block that keeps the xref alive
        # through garbage collection until the build phase overwrites it with
        # the real translated content.
        page.page_xref = doc_zh.get_new_xref()
        doc_zh.update_object(page.page_xref, "<<>>")
        doc_zh.update_stream(page.page_xref, b"BT ET")
        doc_zh[page.pageno].set_contents(page.page_xref)
        page_xref_map[page.pageno] = page.page_xref

        interpreter.process_page(page)

    device.close()

    # Propagate page_xref into each PageState so the build phase can write
    # rendered ops back into the doc_zh stream.
    for ps in device.page_states:
        if ps.page_xref == 0 and ps.pageno in page_xref_map:
            ps.page_xref = page_xref_map[ps.pageno]

    # Build chunks from extracted states
    chunks = []
    chunk_id = 0
    for ps in device.page_states:
        for i, text in enumerate(ps.sstk):
            if text.strip() and not re.match(r"^\{v\d+\}$", text):
                chunks.append(Chunk(
                    id=chunk_id,
                    page=ps.pageno,
                    text=text,
                    char_count=len(text),
                ))
            chunk_id += 1

    # Create session
    session_id = create_session_id()
    import os
    file_name = os.path.splitext(os.path.basename(file_path))[0]

    meta = SessionMeta(
        id=session_id,
        file_path=file_path,
        file_name=file_name,
        lang_in=lang_in,
        lang_out=lang_out,
        page_count=page_count,
        total_chunks=len(chunks),
        created_at=datetime.now().isoformat(),
        noto_name=noto_name,
        font_path=font_path,
    )

    # Save session. garbage=3 is required for set_contents() to actually persist
    # a single-xref /Contents on pages whose original /Contents is an array
    # (title pages with watermark/header streams). The "BT ET" placeholder
    # seeded above keeps the new xref alive through garbage collection so that
    # the build phase can still find it and write the real translated ops.
    doc_zh_bytes = doc_zh.write(deflate=True, garbage=3, use_objstms=1)
    save_session(
        session_id=session_id,
        meta=meta,
        pages=device.page_states,
        layouts=layout,
        doc_zh_bytes=doc_zh_bytes,
        font_ids=font_id,
    )

    doc_en.close()
    doc_zh.close()

    return session_id, chunks, meta


def _parse_pages(pages_str: str) -> set[int]:
    """Parse page range string like '1-5,8,10-12' into a set of 0-indexed page numbers."""
    pages = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            for p in range(int(start) - 1, int(end)):
                pages.add(p)
        else:
            pages.add(int(part) - 1)
    return pages
