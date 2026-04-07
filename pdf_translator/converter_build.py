"""PDF rebuild converter — Section C of scholar-translator's receive_layout().

Takes extracted page state + translated text and generates PDF operations
to render translated content into the document.
"""

import logging
import re
import unicodedata
from enum import Enum

from pdfminer.pdffont import PDFCIDFont
from pymupdf import Font

from pdf_translator.font import get_line_height
from pdf_translator.models import FormulaChar, FormulaLine, PageState, Paragraph

log = logging.getLogger(__name__)


class OpType(Enum):
    TEXT = "text"
    LINE = "line"


class BuildConverter:
    """Generates PDF operations from extracted state + translations (Section C)."""

    def __init__(
        self,
        noto_name: str,
        noto: Font,
        fontmap: dict,
        fontid: dict,
        lang_out: str,
    ):
        self.noto_name = noto_name
        self.noto = noto
        self.fontmap = fontmap
        self.fontid = fontid
        self.lang_out = lang_out

    def build_page_ops(self, page_state: PageState, translations: dict[int, str]) -> str:
        """Build PDF operations for one page given translated texts.

        Args:
            page_state: Extracted state for this page.
            translations: Dict mapping chunk_id (relative to page) to translated text.
                         If a chunk is not in translations, the original text is used.
        """
        sstk = page_state.sstk
        pstk = page_state.pstk
        var = page_state.var
        varl = page_state.varl
        varf = page_state.varf
        vlen = page_state.vlen
        lstk = page_state.lstk

        # Apply translations — replace sstk entries
        news = []
        for i, s in enumerate(sstk):
            if i in translations:
                news.append(translations[i])
            else:
                news.append(s)

        # ── Section C: New document layout ──
        def raw_string(fcur: str, cstk: str) -> str:
            if fcur == self.noto_name:
                return "".join(["%04x" % self.noto.has_glyph(ord(c)) for c in cstk])
            elif fcur in self.fontmap and isinstance(self.fontmap[fcur], PDFCIDFont):
                return "".join(["%04x" % ord(c) for c in cstk])
            else:
                return "".join(["%02x" % ord(c) for c in cstk])

        default_line_height = get_line_height(self.lang_out)

        def gen_op_txt(font, size, x, y, rtxt):
            return f"/{font} {size:f} Tf 1 0 0 1 {x:f} {y:f} Tm [<{rtxt}>] TJ "

        def gen_op_line(x, y, xlen, ylen, linewidth):
            return f"ET q 1 0 0 1 {x:f} {y:f} cm [] 0 d 0 J {linewidth:f} w 0 0 m {xlen:f} {ylen:f} l S Q BT "

        ops_list = []

        for idx, new in enumerate(news):
            x: float = pstk[idx].x
            y: float = pstk[idx].y
            x0: float = pstk[idx].x0
            x1: float = pstk[idx].x1
            height: float = pstk[idx].y1 - pstk[idx].y0
            size: float = pstk[idx].size
            brk: bool = pstk[idx].brk
            cstk: str = ""
            fcur: str = None
            lidx = 0
            tx = x
            fcur_ = fcur
            ptr = 0

            ops_vals: list[dict] = []

            while ptr < len(new):
                vy_regex = re.match(r"\{\s*v([\d\s]+)\}", new[ptr:], re.IGNORECASE)
                mod = 0

                if vy_regex:
                    ptr += len(vy_regex.group(0))
                    try:
                        vid = int(vy_regex.group(1).replace(" ", ""))
                        adv = vlen[vid]
                    except Exception:
                        continue
                    if (
                        var[vid]
                        and var[vid][-1].text
                        and unicodedata.category(var[vid][-1].text[0]) in ["Lm", "Mn", "Sk"]
                    ):
                        mod = var[vid][-1].width
                else:
                    ch = new[ptr]
                    fcur_ = None
                    try:
                        if fcur_ is None and self.fontmap.get("tiro") and self.fontmap["tiro"].to_unichr(ord(ch)) == ch:
                            fcur_ = "tiro"
                    except Exception:
                        pass
                    if fcur_ is None:
                        fcur_ = self.noto_name
                    if fcur_ == self.noto_name:
                        adv = self.noto.char_lengths(ch, size)[0]
                    else:
                        adv = self.fontmap[fcur_].char_width(ord(ch)) * size
                    ptr += 1

                if (
                    fcur_ != fcur
                    or vy_regex
                    or x + adv > x1 + 0.1 * size
                ):
                    if cstk:
                        ops_vals.append({
                            "type": OpType.TEXT,
                            "font": fcur,
                            "size": size,
                            "x": tx,
                            "dy": 0,
                            "rtxt": raw_string(fcur, cstk),
                            "lidx": lidx,
                        })
                        cstk = ""

                if brk and x + adv > x1 + 0.1 * size:
                    x = x0
                    lidx += 1

                if vy_regex:
                    fix = 0
                    if fcur is not None:
                        fix = varf[vid]
                    for vch in var[vid]:
                        vc = chr(vch.cid)
                        ops_vals.append({
                            "type": OpType.TEXT,
                            "font": vch.font_id,
                            "size": vch.size,
                            "x": x + vch.x0 - var[vid][0].x0,
                            "dy": fix + vch.y0 - var[vid][0].y0,
                            "rtxt": raw_string(vch.font_id, vc),
                            "lidx": lidx,
                        })
                    for fl in varl[vid]:
                        if fl.linewidth < 5:
                            ops_vals.append({
                                "type": OpType.LINE,
                                "x": fl.x0 + x - var[vid][0].x0,
                                "dy": fl.y0 + fix - var[vid][0].y0,
                                "linewidth": fl.linewidth,
                                "xlen": fl.x1 - fl.x0,
                                "ylen": fl.y1 - fl.y0,
                                "lidx": lidx,
                            })
                else:
                    if not cstk:
                        tx = x
                        if x == x0 and ch == " ":
                            adv = 0
                        else:
                            cstk += ch
                    else:
                        cstk += ch

                adv -= mod
                fcur = fcur_
                x += adv

            if cstk:
                ops_vals.append({
                    "type": OpType.TEXT,
                    "font": fcur,
                    "size": size,
                    "x": tx,
                    "dy": 0,
                    "rtxt": raw_string(fcur, cstk),
                    "lidx": lidx,
                })

            line_height = default_line_height
            while (lidx + 1) * size * line_height > height and line_height >= 1:
                line_height -= 0.05

            for vals in ops_vals:
                if vals["type"] == OpType.TEXT:
                    ops_list.append(gen_op_txt(
                        vals["font"], vals["size"], vals["x"],
                        vals["dy"] + y - vals["lidx"] * size * line_height,
                        vals["rtxt"],
                    ))
                elif vals["type"] == OpType.LINE:
                    ops_list.append(gen_op_line(
                        vals["x"],
                        vals["dy"] + y - vals["lidx"] * size * line_height,
                        vals["xlen"], vals["ylen"], vals["linewidth"],
                    ))

        # Global lines
        for fl in lstk:
            if fl.linewidth < 5:
                ops_list.append(gen_op_line(
                    fl.x0, fl.y0,
                    fl.x1 - fl.x0, fl.y1 - fl.y0,
                    fl.linewidth,
                ))

        return f"BT {''.join(ops_list)}ET "
