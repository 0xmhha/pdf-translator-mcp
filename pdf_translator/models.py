"""Data models for PDF translation pipeline."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Chunk:
    """A text chunk extracted from a PDF page."""
    id: int
    page: int
    text: str
    char_count: int


@dataclass
class Paragraph:
    """Position and style info for a text paragraph in a PDF page."""
    y: float      # Initial y-coordinate
    x: float      # Initial x-coordinate
    x0: float     # Left boundary
    x1: float     # Right boundary
    y0: float     # Top boundary
    y1: float     # Bottom boundary
    size: float   # Font size
    brk: bool     # Line break flag

    def to_dict(self) -> dict:
        return {
            "y": self.y, "x": self.x,
            "x0": self.x0, "x1": self.x1,
            "y0": self.y0, "y1": self.y1,
            "size": self.size, "brk": self.brk,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Paragraph":
        return cls(**d)


@dataclass
class FormulaChar:
    """Serializable representation of a formula character (from LTChar)."""
    x0: float
    y0: float
    x1: float
    y1: float
    cid: int
    fontname: str
    font_id: str
    size: float
    text: str
    matrix: list
    width: float

    def to_dict(self) -> dict:
        return {
            "x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1,
            "cid": self.cid, "fontname": self.fontname, "font_id": self.font_id,
            "size": self.size, "text": self.text, "matrix": self.matrix,
            "width": self.width,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FormulaChar":
        return cls(**d)


@dataclass
class FormulaLine:
    """Serializable representation of a formula line (from LTLine)."""
    x0: float
    y0: float
    x1: float
    y1: float
    linewidth: float

    def to_dict(self) -> dict:
        return {
            "x0": self.x0, "y0": self.y0,
            "x1": self.x1, "y1": self.y1,
            "linewidth": self.linewidth,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FormulaLine":
        return cls(**d)


@dataclass
class PageState:
    """Complete extracted state for a single PDF page."""
    pageno: int
    sstk: list[str]                          # Paragraph texts
    pstk: list[Paragraph]                    # Paragraph positions
    var: list[list[FormulaChar]]             # Formula character groups
    varl: list[list[FormulaLine]]            # Formula line groups
    varf: list[float]                        # Formula vertical offsets
    vlen: list[float]                        # Formula widths
    lstk: list[FormulaLine]                  # Global lines
    page_xref: int                           # PyMuPDF xref for this page

    def to_dict(self) -> dict:
        return {
            "pageno": self.pageno,
            "sstk": self.sstk,
            "pstk": [p.to_dict() for p in self.pstk],
            "var": [[fc.to_dict() for fc in group] for group in self.var],
            "varl": [[fl.to_dict() for fl in group] for group in self.varl],
            "varf": self.varf,
            "vlen": self.vlen,
            "lstk": [fl.to_dict() for fl in self.lstk],
            "page_xref": self.page_xref,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PageState":
        return cls(
            pageno=d["pageno"],
            sstk=d["sstk"],
            pstk=[Paragraph.from_dict(p) for p in d["pstk"]],
            var=[[FormulaChar.from_dict(fc) for fc in group] for group in d["var"]],
            varl=[[FormulaLine.from_dict(fl) for fl in group] for group in d["varl"]],
            varf=d["varf"],
            vlen=d["vlen"],
            lstk=[FormulaLine.from_dict(fl) for fl in d["lstk"]],
            page_xref=d["page_xref"],
        )


@dataclass
class SessionMeta:
    """Metadata for a translation session."""
    id: str
    file_path: str
    file_name: str
    lang_in: str
    lang_out: str
    page_count: int
    total_chunks: int
    created_at: str
    noto_name: str
    font_path: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "file_path": self.file_path,
            "file_name": self.file_name,
            "lang_in": self.lang_in,
            "lang_out": self.lang_out,
            "page_count": self.page_count,
            "total_chunks": self.total_chunks,
            "created_at": self.created_at,
            "noto_name": self.noto_name,
            "font_path": self.font_path,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMeta":
        return cls(**d)
