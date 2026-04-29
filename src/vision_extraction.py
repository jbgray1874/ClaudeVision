from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover
    np = None

from extractor_patterns import normalize_text


_OCR_INSTANCE = None
_OCR_IMPORT_ATTEMPTED = False
_PADDLEOCR_CLASS = None


def _zone_boxes(page_width: float, page_height: float) -> Dict[str, Tuple[float, float, float, float]]:
    return {
        "title_block": (page_width * 0.58, page_height * 0.72, page_width, page_height),
        "bom": (0.0, page_height * 0.55, page_width * 0.55, page_height),
        "notes": (page_width * 0.55, 0.0, page_width, page_height * 0.5),
        "revision": (page_width * 0.72, page_height * 0.55, page_width, page_height * 0.8),
    }


def _get_ocr():
    global _OCR_INSTANCE, _OCR_IMPORT_ATTEMPTED, _PADDLEOCR_CLASS
    if _OCR_INSTANCE is not None:
        return _OCR_INSTANCE
    if not _OCR_IMPORT_ATTEMPTED:
        _OCR_IMPORT_ATTEMPTED = True
        try:
            from paddleocr import PaddleOCR  # type: ignore

            _PADDLEOCR_CLASS = PaddleOCR
        except Exception:
            _PADDLEOCR_CLASS = None
    if _PADDLEOCR_CLASS is None:
        return None
    try:
        _OCR_INSTANCE = _PADDLEOCR_CLASS(use_angle_cls=True, lang="en", show_log=False)
        return _OCR_INSTANCE
    except Exception:
        _OCR_INSTANCE = None
        return None


def _ocr_page_image(image_array: Any) -> List[Dict[str, Any]]:
    ocr = _get_ocr()
    if ocr is None:
        return []
    result = ocr.ocr(image_array, cls=True) or []
    words: List[Dict[str, Any]] = []
    for line in result:
        for item in line or []:
            box = item[0]
            text = str(item[1][0]) if item[1] else ""
            score = float(item[1][1]) if item[1] and len(item[1]) > 1 else 0.0
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            words.append(
                {
                    "text": text,
                    "confidence": round(score, 3),
                    "x0": min(xs),
                    "x1": max(xs),
                    "top": min(ys),
                    "bottom": max(ys),
                }
            )
    return words


def _words_in_box(words: List[Dict[str, Any]], box: Tuple[float, float, float, float]) -> List[Dict[str, Any]]:
    x0, top, x1, bottom = box
    return [
        word for word in words
        if word["x1"] >= x0 and word["x0"] <= x1 and word["bottom"] >= top and word["top"] <= bottom
    ]


def _words_to_text(words: List[Dict[str, Any]]) -> str:
    ordered = sorted(words, key=lambda item: (round(float(item.get("top", 0.0)), 1), float(item.get("x0", 0.0))))
    return normalize_text(" ".join(str(item.get("text", "")) for item in ordered))


def _extract_process_callouts(text: str) -> List[str]:
    upper = text.upper()
    callouts: List[str] = []
    for token in ["WELD", "FOLD", "BEND", "DEBURR", "PEM", "CSK", "TAP", "PITCH", "HOLE", "SLOT"]:
        if token in upper and token not in callouts:
            callouts.append(token)
    return callouts


def extract_document_vision(pdf_path: Path) -> List[Dict[str, Any]]:
    if fitz is None or np is None:
        return []

    document = fitz.open(str(pdf_path))
    pages: List[Dict[str, Any]] = []
    try:
        for idx, page in enumerate(document, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image_bytes = pix.samples
            image = np.frombuffer(image_bytes, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            words = _ocr_page_image(image)
            page_width = float(pix.width)
            page_height = float(pix.height)
            zones = _zone_boxes(page_width, page_height)
            region_words = {name: _words_in_box(words, box) for name, box in zones.items()}
            region_text = {name: _words_to_text(items) for name, items in region_words.items()}
            bom_text = normalize_text(f"{region_text.get('bom', '')} {region_text.get('notes', '')}")
            revision_text = normalize_text(region_text.get("revision", ""))
            process_callouts = _extract_process_callouts(normalize_text(" ".join(region_text.values())))
            pages.append(
                {
                    "page_number": idx,
                    "ocr_engine": "paddleocr" if _get_ocr() is not None else "unavailable",
                    "ocr_word_count": len(words),
                    "ocr_confidence_avg": round(sum(word.get("confidence", 0.0) for word in words) / len(words), 3) if words else 0.0,
                    "ocr_text": _words_to_text(words),
                    "region_text": region_text,
                    "bom_table_text": bom_text,
                    "revision_table_text": revision_text,
                    "process_callouts": process_callouts,
                    "layout_engine": "layoutparser_ready",
                    "table_engine": "img2table_ready",
                }
            )
    finally:
        document.close()
    return pages
