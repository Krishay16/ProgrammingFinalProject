"""SYNTHETIC test PDFs, built in memory with PyMuPDF (Person 3).

SYNTHETIC: invented for testing, not a real company. The sample statement uses the same
figures as tests/fixtures/sample_data.py (FY2024 and FY2023, in millions of USD).

Run this file directly to (re)generate tests/fixtures/sample_statement_SYNTHETIC.pdf:
    python -m tests.pdf_builders
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

Line = Union[str, tuple]  # "title text" or ("Label", "value 1", "value 2", ...)
SAMPLE_PDF_PATH = Path(__file__).parent / "fixtures" / "sample_statement_SYNTHETIC.pdf"


def make_pdf(pages: list[list[Line]]) -> bytes:
    """A PDF where each tuple line prints a label and right-aligned value columns."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        y = 60
        for line in lines:
            if isinstance(line, tuple):
                page.insert_text((50, y), line[0], fontsize=10)
                for i, value in enumerate(line[1:]):
                    width = fitz.get_text_length(value, fontsize=10)
                    page.insert_text((380 + 100 * i - width, y), value, fontsize=10)
            else:
                page.insert_text((50, y), line, fontsize=10)
            y += 18
    data = doc.tobytes()
    doc.close()
    return data


def make_blank_pdf() -> bytes:
    """A PDF with a drawing but no text, like a scanned image-only document."""
    doc = fitz.open()
    page = doc.new_page()
    page.draw_rect(fitz.Rect(50, 50, 300, 300), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    data = doc.tobytes()
    doc.close()
    return data


SAMPLE_PAGES: list[list[Line]] = [
    ["Sample Manufacturing Co (SYNTHETIC)",
     "SYNTHETIC demo statement - invented for testing, not a real company",
     "Consolidated Income Statement",
     "(in millions of USD)",
     ("", "2024", "2023"),
     ("Revenue", "9,000", "8,400"),
     ("Cost of revenue", "(5,850)", "(5,500)"),
     ("Gross profit", "3,150", "2,900"),
     ("Operating income", "1,350", "1,200"),
     ("EBITDA", "1,800", "1,630"),
     ("Interest expense", "(150)", "(160)"),
     ("Net income", "900", "780"),
     ("Net income per share", "4.50", "3.90"),
     ("Depreciation and amortization", "450", "430")],
    ["Sample Manufacturing Co (SYNTHETIC)",
     "Consolidated Balance Sheet",
     "(in millions of USD)",
     ("", "2024", "2023"),
     ("Cash and cash equivalents", "1,500", "1,300"),
     ("Total current assets", "4,800", "4,500"),
     ("Total assets", "12,000", "11,400"),
     ("Total current liabilities", "2,600", "2,500"),
     ("Total liabilities", "6,600", "6,400"),
     ("Short-term debt", "400", "450"),
     ("Long-term debt", "2,800", "2,900"),
     ("Total shareholders' equity", "5,400", "5,000")],
    ["Sample Manufacturing Co (SYNTHETIC)",
     "Consolidated Cash Flow Statement",
     "(in millions of USD)",
     ("", "2024", "2023"),
     ("Net cash provided by operating activities", "1,500", "1,300"),
     ("Capital expenditures", "(600)", "(550)"),
     ("Net cash used in investing activities", "(750)", "(700)"),
     ("Net cash used in financing activities", "(500)", "(450)")],
]


def make_sample_statement_pdf() -> bytes:
    return make_pdf(SAMPLE_PAGES)


if __name__ == "__main__":
    SAMPLE_PDF_PATH.write_bytes(make_sample_statement_pdf())
    print(f"Wrote {SAMPLE_PDF_PATH}")
