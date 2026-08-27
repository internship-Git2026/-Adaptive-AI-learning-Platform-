"""PDF text extraction with robust OCR support.

Kept separate from the request handlers so the upload flow (pdf_upload.py) and
the doubt-solver page indexer (doubt_solver.py) share one extraction pipeline.

Pipeline:
1. Try pdfplumber's embedded text layer (digital PDFs).
2. If the embedded text is too thin, OCR the document:
   - Prefer OCR-ing each page's embedded raster image directly. Many scanned
     PDFs place a low-resolution scan on a very large page; Tesseract cannot
     read a render of the whole page because the text occupies only a small
     region of it.
   - Fall back to rendering the page (cropped to the image bounds when the
     page declares images) only when no usable embedded image exists.
"""
import io
import logging
import re

import pdfplumber
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

logger = logging.getLogger(__name__)

# Below this many characters the embedded text layer is considered useless and
# OCR takes over.
DIGITAL_MIN_CHARS = 100

# Rendering resolution for the full-page OCR fallback.
FALLBACK_DPI = 150
# Small embedded images are upscaled so Tesseract can read them.
MIN_OCR_EDGE = 1600
# Very large renders are downscaled to keep OCR fast and reliable.
MAX_OCR_EDGE = 4000


class ExtractionError(Exception):
    """Raised when a PDF yields no usable text through any extraction path."""


def clean_text(text):
    """Normalize extracted text: strip page numbers, collapse whitespace."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    cleaned_lines = []
    for line in text.split("\n"):
        line_str = line.strip()
        line_str = re.sub(r"[ \t]+", " ", line_str)
        if re.match(r"^(page)?\s*\d+\s*(of\s*\d+)?$", line_str, re.I):
            continue
        cleaned_lines.append(line_str)

    cleaned_text = "\n".join(cleaned_lines)
    cleaned_text = re.sub(r"\n\s*\n", "\n\n", cleaned_text)
    return cleaned_text.strip()


def _ocr_image(image):
    """OCR a PIL image, up/down-scaling to a size Tesseract reads reliably."""
    img = image.convert("L")
    w, h = img.size
    longest = max(w, h)
    if longest < MIN_OCR_EDGE:
        scale = MIN_OCR_EDGE / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    elif longest > MAX_OCR_EDGE:
        scale = MAX_OCR_EDGE / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return pytesseract.image_to_string(img)


def _ocr_embedded_images(page):
    """OCR the raster images embedded in `page` (pdfplumber Page object)."""
    parts = []
    for image_info in page.images:
        stream = image_info.get("stream")
        if stream is None:
            continue
        try:
            data = stream.get_data()
            if not data:
                continue
            img = Image.open(io.BytesIO(data))
            text = _ocr_image(img)
        except Exception as exc:  # pragma: no cover - defensive per image
            logger.warning(
                "OCR of embedded image on page %s failed: %s",
                page.page_number, exc,
            )
            continue
        if text and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _ocr_rendered_page(pdf_path, page):
    """Render one page (cropped to its image bounds) and OCR the result.

    Used only when a page carries no readable embedded image.
    """
    try:
        rendered = page.to_image(resolution=FALLBACK_DPI).original
    except Exception as exc:
        logger.warning("Could not render page %s for OCR: %s", page.page_number, exc)
        return ""

    crop = None
    if page.images:
        scale = FALLBACK_DPI / 72.0
        x0 = min(im["x0"] for im in page.images)
        y0 = min(im["top"] for im in page.images)
        x1 = max(im["x1"] for im in page.images)
        y1 = max(im["bottom"] for im in page.images)
        crop = (int(x0 * scale), int(y0 * scale), int(x1 * scale), int(y1 * scale))

    if crop is not None:
        try:
            rendered = rendered.crop(crop)
        except Exception:  # pragma: no cover - malformed bbox
            rendered = rendered

    return _ocr_image(rendered)


def _ocr_pdf(pdf_path):
    """OCR every page; returns a list of (page_number, text)."""
    pages_text = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = _ocr_embedded_images(page).strip()
            if not text:
                text = _ocr_rendered_page(pdf_path, page).strip()
            if text:
                pages_text.append((page.page_number, text))
    return pages_text


def _extract_digital(pdf_path):
    """Extract the embedded text layer; returns a list of (page_number, text)."""
    pages_text = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text and text.strip():
                pages_text.append((page.page_number, text.strip()))
    return pages_text


def extract_pdf_pages(pdf_path):
    """Extract text from a PDF.

    Returns ``(method, [(page_number, text), ...], total_pages)`` where
    ``method`` is ``"Digital"`` when the embedded text layer was usable and
    ``"OCR"`` when OCR was required.

    Raises :class:`ExtractionError` when no usable text can be produced and
    :class:`ExtractionError` (with an explicit OCR-toolchain message) when OCR
    cannot run because a system dependency is missing.
    """
    total_pages = 0
    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)

    digital_pages = _extract_digital(pdf_path)
    digital_len = sum(len(text) for _, text in digital_pages)

    if digital_len >= DIGITAL_MIN_CHARS:
        return "Digital", digital_pages, total_pages

    # Not enough embedded text: run OCR.
    try:
        ocr_pages = _ocr_pdf(pdf_path)
    except Exception as exc:
        # pdftoppm/poppler or tesseract missing typically surfaces here.
        message = (
            "OCR toolchain error (Tesseract/Poppler may not be installed): "
            f"{exc}"
        )
        logger.error("OCR toolchain error for %s: %s", pdf_path, exc)
        raise ExtractionError(message) from exc

    ocr_len = sum(len(text) for _, text in ocr_pages)
    if ocr_len == 0:
        raise ExtractionError(
            "OCR ran but no readable text could be extracted from the PDF. "
            "The document may be a photo or an unreadable scan."
        )

    return "OCR", ocr_pages, total_pages