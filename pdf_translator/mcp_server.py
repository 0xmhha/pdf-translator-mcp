"""MCP Server for PDF Translation.

Provides three tools:
- extract_pdf: Extract text chunks from PDF
- build_translated_pdf: Rebuild PDF with translated text
- analyze_pdf: Analyze PDF structure without processing
"""

import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

from pdf_translator.session import cleanup_expired_sessions

logger = logging.getLogger(__name__)

mcp = FastMCP("pdf-translator")


@mcp.tool()
async def extract_pdf(
    file: str,
    lang_in: str = "en",
    lang_out: str = "ko",
    pages: str = "",
    ctx: Context = None,
) -> str:
    """Extract text chunks from a PDF file for translation.

    This tool parses a PDF, detects layout (formulas, figures, tables),
    and returns text chunks that need translation. Formula markers like
    {v0}, {v1} must be preserved in translations.

    Args:
        file: Path to the input PDF file
        lang_in: Source language code (e.g., 'en', 'ko', 'ja')
        lang_out: Target language code (e.g., 'ko', 'en', 'ja')
        pages: Page range to extract (e.g., '1-5', '1,3,5'). Empty = all pages

    Returns:
        JSON with session_id, metadata, and text chunks to translate
    """
    from pdf_translator.extractor import extract_pdf as do_extract

    file_path = Path(file).resolve()
    if not file_path.exists():
        return json.dumps({"error": f"File not found: {file}"})

    if ctx:
        await ctx.log(level="info", message=f"Extracting text from {file_path.name}...")

    try:
        session_id, chunks, meta = do_extract(
            file_path=str(file_path),
            lang_in=lang_in,
            lang_out=lang_out,
            pages_range=pages if pages else None,
        )

        result = {
            "session_id": session_id,
            "metadata": {
                "file": str(file_path),
                "file_name": meta.file_name,
                "page_count": meta.page_count,
                "total_chunks": meta.total_chunks,
                "lang_in": lang_in,
                "lang_out": lang_out,
            },
            "chunks": [
                {
                    "id": c.id,
                    "page": c.page,
                    "text": c.text,
                    "char_count": c.char_count,
                }
                for c in chunks
            ],
        }

        if ctx:
            await ctx.log(
                level="info",
                message=f"Extracted {len(chunks)} chunks from {meta.page_count} pages. Session: {session_id}",
            )

        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        error_msg = f"Extraction failed: {e}"
        logger.exception(error_msg)
        if ctx:
            await ctx.log(level="error", message=error_msg)
        return json.dumps({"error": error_msg})


@mcp.tool()
async def build_translated_pdf(
    session_id: str,
    translations: str,
    output_dir: str = "",
    ctx: Context = None,
) -> str:
    """Build translated PDF from extracted chunks and their translations.

    Takes the session_id from extract_pdf and a translations JSON mapping
    chunk IDs to translated text. Generates mono (translated only) and
    dual (original + translated) PDF files.

    Args:
        session_id: Session ID returned by extract_pdf
        translations: JSON string mapping chunk ID to translated text.
                     Example: {"0": "번역된 텍스트", "1": "1. 서론"}
                     Formula markers {v0} must be preserved in translations.
        output_dir: Output directory path. Default: cwd/{filename}-{lang_out}/

    Returns:
        JSON with output file paths and translation stats
    """
    from pdf_translator.builder import build_translated_pdf as do_build

    if ctx:
        await ctx.log(level="info", message=f"Building translated PDF for session {session_id}...")

    try:
        trans_dict = json.loads(translations)

        result = do_build(
            session_id=session_id,
            translations=trans_dict,
            output_dir=output_dir,
        )

        if ctx:
            await ctx.log(
                level="info",
                message=f"PDF built: {result['stats']['chunks_translated']} chunks, {result['stats']['pages_processed']} pages",
            )

        return json.dumps(result, ensure_ascii=False, indent=2)

    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid translations JSON: {e}"})
    except FileNotFoundError as e:
        return json.dumps({"error": f"Session not found: {e}"})
    except Exception as e:
        error_msg = f"Build failed: {e}"
        logger.exception(error_msg)
        if ctx:
            await ctx.log(level="error", message=error_msg)
        return json.dumps({"error": error_msg})


@mcp.tool()
async def analyze_pdf(
    file: str,
    ctx: Context = None,
) -> str:
    """Analyze PDF structure without translating.

    Returns page count, text regions, character count, and detected fonts.
    Useful for estimating translation effort before extracting.

    Args:
        file: Path to the input PDF file

    Returns:
        JSON with PDF analysis: page count, text regions, fonts, estimated chunks
    """
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams, LTTextBox, LTChar

    file_path = Path(file).resolve()
    if not file_path.exists():
        return json.dumps({"error": f"File not found: {file}"})

    if ctx:
        await ctx.log(level="info", message=f"Analyzing PDF: {file_path.name}")

    try:
        with open(file_path, "rb") as f:
            page_list = list(PDFPage.get_pages(f))
            page_count = len(page_list)

            f.seek(0)
            rsrcmgr = PDFResourceManager()
            laparams = LAParams()
            device = PDFPageAggregator(rsrcmgr, laparams=laparams)
            interpreter = PDFPageInterpreter(rsrcmgr, device)

            text_regions = 0
            total_chars = 0
            fonts_used = set()

            for page in PDFPage.get_pages(f):
                interpreter.process_page(page)
                layout = device.get_result()
                for element in layout:
                    if isinstance(element, LTTextBox):
                        text_regions += 1
                        total_chars += len(element.get_text())
                        for item in element:
                            if hasattr(item, "__iter__"):
                                for char in item:
                                    if isinstance(char, LTChar):
                                        fonts_used.add(char.fontname)

        # Rough estimates
        estimated_chunks = max(1, text_regions // 2)
        estimated_tokens = total_chars // 4

        analysis = {
            "file": str(file_path),
            "page_count": page_count,
            "total_characters": total_chars,
            "text_regions": text_regions,
            "fonts_detected": sorted(list(fonts_used)),
            "estimated_chunks": estimated_chunks,
            "estimated_tokens": estimated_tokens,
        }

        if ctx:
            await ctx.log(level="info", message="Analysis complete")

        return json.dumps(analysis, ensure_ascii=False, indent=2)

    except Exception as e:
        error_msg = f"Analysis failed: {e}"
        logger.exception(error_msg)
        if ctx:
            await ctx.log(level="error", message=error_msg)
        return json.dumps({"error": error_msg})


def main():
    """Entry point for the MCP server."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    cleanup_expired_sessions()
    mcp.run()


if __name__ == "__main__":
    main()
