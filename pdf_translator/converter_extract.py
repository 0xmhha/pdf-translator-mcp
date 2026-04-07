"""PDF text extraction converter — Section A of scholar-translator's receive_layout().

Parses PDF pages to extract text paragraphs and formula information,
WITHOUT performing translation. Returns structured data for later rebuild.
"""

import logging
import re
import unicodedata

import numpy as np
from pdfminer.converter import PDFConverter
from pdfminer.layout import LTChar, LTFigure, LTLine, LTPage
from pdfminer.pdffont import PDFCIDFont, PDFUnicodeNotDefined
from pdfminer.pdfinterp import PDFGraphicState, PDFResourceManager
from pdfminer.utils import apply_matrix_pt, mult_matrix
from pymupdf import Font

from pdf_translator.models import FormulaChar, FormulaLine, PageState, Paragraph

log = logging.getLogger(__name__)


class PDFConverterEx(PDFConverter):
    def __init__(self, rsrcmgr: PDFResourceManager) -> None:
        PDFConverter.__init__(self, rsrcmgr, None, "utf-8", 1, None)

    def begin_page(self, page, ctm) -> None:
        (x0, y0, x1, y1) = page.cropbox
        (x0, y0) = apply_matrix_pt(ctm, (x0, y0))
        (x1, y1) = apply_matrix_pt(ctm, (x1, y1))
        mediabox = (0, 0, abs(x0 - x1), abs(y0 - y1))
        self.cur_item = LTPage(page.pageno, mediabox)

    def end_page(self, page):
        return self.receive_layout(self.cur_item)

    def begin_figure(self, name, bbox, matrix) -> None:
        self._stack.append(self.cur_item)
        self.cur_item = LTFigure(name, bbox, mult_matrix(matrix, self.ctm))
        self.cur_item.pageid = self._stack[-1].pageid

    def end_figure(self, _: str) -> None:
        fig = self.cur_item
        assert isinstance(self.cur_item, LTFigure), str(type(self.cur_item))
        self.cur_item = self._stack.pop()
        self.cur_item.add(fig)
        return self.receive_layout(fig)

    def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate):
        try:
            text = font.to_unichr(cid)
            assert isinstance(text, str), str(type(text))
        except PDFUnicodeNotDefined:
            text = self.handle_undefined_char(font, cid)
        textwidth = font.char_width(cid)
        textdisp = font.char_disp(cid)
        item = LTChar(
            matrix, font, fontsize, scaling, rise,
            text, textwidth, textdisp, ncs, graphicstate,
        )
        self.cur_item.add(item)
        item.cid = cid
        item.font = font
        return item.adv


class ExtractConverter(PDFConverterEx):
    """Extracts text paragraphs and formula info from PDF pages (Section A only)."""

    def __init__(
        self,
        rsrcmgr,
        vfont: str = None,
        vchar: str = None,
        layout={},
        noto_name: str = "",
        noto: Font = None,
    ) -> None:
        super().__init__(rsrcmgr)
        self.vfont = vfont
        self.vchar = vchar
        self.layout = layout
        self.noto_name = noto_name
        self.noto = noto
        # Collected page states
        self.page_states: list[PageState] = []

    def _ltchar_to_formula_char(self, ch: LTChar) -> FormulaChar:
        """Convert an LTChar to a serializable FormulaChar."""
        return FormulaChar(
            x0=ch.x0, y0=ch.y0, x1=ch.x1, y1=ch.y1,
            cid=ch.cid,
            fontname=ch.fontname if isinstance(ch.fontname, str) else str(ch.fontname),
            font_id=self.fontid.get(ch.font, self.noto_name),
            size=ch.size,
            text=ch.get_text(),
            matrix=list(ch.matrix),
            width=ch.width,
        )

    def _ltline_to_formula_line(self, line: LTLine) -> FormulaLine:
        """Convert an LTLine to a serializable FormulaLine."""
        return FormulaLine(
            x0=line.pts[0][0], y0=line.pts[0][1],
            x1=line.pts[1][0], y1=line.pts[1][1],
            linewidth=line.linewidth,
        )

    def receive_layout(self, ltpage: LTPage):
        """Section A: Parse original document, extract text and formula data.

        Returns PDF ops string (for compatibility with interpreter),
        and appends extracted PageState to self.page_states.
        """
        # ── Data structures (same as scholar-translator) ──
        sstk: list[str] = []
        pstk: list = []
        vbkt: int = 0
        vstk: list[LTChar] = []
        vlstk: list[LTLine] = []
        vfix: float = 0
        var: list[list[LTChar]] = []
        varl: list[list[LTLine]] = []
        varf: list[float] = []
        vlen: list[float] = []
        lstk: list[LTLine] = []
        xt: LTChar = None
        xt_cls: int = -1
        vmax: float = ltpage.width / 4
        ops: str = ""

        def vflag(font: str, char: str):
            if isinstance(font, bytes):
                try:
                    font = font.decode("utf-8")
                except UnicodeDecodeError:
                    font = ""
            font = font.split("+")[-1]
            if re.match(r"\(cid:", char):
                return True
            if self.vfont:
                if re.match(self.vfont, font):
                    return True
            else:
                if re.match(
                    r"(CM[^R]|MS.M|XY|MT|BL|RM|EU|LA|RS|LINE|LCIRCLE|TeX-|rsfs|txsy|wasy|stmary|.*Mono|.*Code|.*Ital|.*Sym|.*Math)",
                    font,
                ):
                    return True
            if self.vchar:
                if re.match(self.vchar, char):
                    return True
            else:
                if (
                    char
                    and char != " "
                    and (
                        unicodedata.category(char[0])
                        in ["Lm", "Mn", "Sk", "Sm", "Zl", "Zp", "Zs"]
                        or ord(char[0]) in range(0x370, 0x400)
                    )
                ):
                    return True
            return False

        # ── Section A: Original document parsing ──
        for child in ltpage:
            if isinstance(child, LTChar):
                cur_v = False
                layout = self.layout[ltpage.pageid]
                h, w = layout.shape
                cx, cy = np.clip(int(child.x0), 0, w - 1), np.clip(int(child.y0), 0, h - 1)
                cls = layout[cy, cx]
                if child.get_text() == "\u2022":
                    cls = 0
                if (
                    cls == 0
                    or (cls == xt_cls and len(sstk[-1].strip()) > 1 and child.size < pstk[-1].size * 0.79)
                    or vflag(child.fontname, child.get_text())
                    or (child.matrix[0] == 0 and child.matrix[3] == 0)
                ):
                    cur_v = True
                if not cur_v:
                    if vstk and child.get_text() == "(":
                        cur_v = True
                        vbkt += 1
                    if vbkt and child.get_text() == ")":
                        cur_v = True
                        vbkt -= 1
                if (
                    not cur_v
                    or cls != xt_cls
                    or (sstk[-1] != "" and abs(child.x0 - xt.x0) > vmax)
                ):
                    if vstk:
                        if (
                            not cur_v
                            and cls == xt_cls
                            and child.x0 > max([vch.x0 for vch in vstk])
                        ):
                            vfix = vstk[0].y0 - child.y0
                        if sstk[-1] == "":
                            xt_cls = -1
                        sstk[-1] += f"{{v{len(var)}}}"
                        var.append(vstk)
                        varl.append(vlstk)
                        varf.append(vfix)
                        vstk = []
                        vlstk = []
                        vfix = 0
                if not vstk:
                    if cls == xt_cls:
                        if child.x0 > xt.x1 + 1:
                            sstk[-1] += " "
                        elif child.x1 < xt.x0:
                            sstk[-1] += " "
                            pstk[-1].brk = True
                    else:
                        sstk.append("")
                        pstk.append(Paragraph(child.y0, child.x0, child.x0, child.x0, child.y0, child.y1, child.size, False))
                if not cur_v:
                    if (
                        child.size > pstk[-1].size
                        or len(sstk[-1].strip()) == 1
                    ) and child.get_text() != " ":
                        pstk[-1].y -= child.size - pstk[-1].size
                        pstk[-1].size = child.size
                    sstk[-1] += child.get_text()
                else:
                    if (
                        not vstk
                        and cls == xt_cls
                        and child.x0 > xt.x0
                    ):
                        vfix = child.y0 - xt.y0
                    vstk.append(child)
                pstk[-1].x0 = min(pstk[-1].x0, child.x0)
                pstk[-1].x1 = max(pstk[-1].x1, child.x1)
                pstk[-1].y0 = min(pstk[-1].y0, child.y0)
                pstk[-1].y1 = max(pstk[-1].y1, child.y1)
                xt = child
                xt_cls = cls
            elif isinstance(child, LTFigure):
                pass
            elif isinstance(child, LTLine):
                layout = self.layout[ltpage.pageid]
                h, w = layout.shape
                cx, cy = np.clip(int(child.x0), 0, w - 1), np.clip(int(child.y0), 0, h - 1)
                cls = layout[cy, cx]
                if vstk and cls == xt_cls:
                    vlstk.append(child)
                else:
                    lstk.append(child)

        # Finalize formula stack
        if vstk:
            sstk[-1] += f"{{v{len(var)}}}"
            var.append(vstk)
            varl.append(vlstk)
            varf.append(vfix)

        # Calculate formula widths
        for v in var:
            l = max([vch.x1 for vch in v]) - v[0].x0
            vlen.append(l)

        # ── Convert to serializable PageState ──
        ser_var = [[self._ltchar_to_formula_char(ch) for ch in group] for group in var]
        ser_varl = [[self._ltline_to_formula_line(line) for line in group] for group in varl]
        ser_lstk = [self._ltline_to_formula_line(line) for line in lstk]

        page_state = PageState(
            pageno=ltpage.pageid,
            sstk=sstk,
            pstk=pstk,
            var=ser_var,
            varl=ser_varl,
            varf=varf,
            vlen=vlen,
            lstk=ser_lstk,
            page_xref=0,  # Set later by extractor
        )
        self.page_states.append(page_state)

        # Return empty ops — we don't build PDF ops in extract phase
        ops = f"BT ET "
        return ops
