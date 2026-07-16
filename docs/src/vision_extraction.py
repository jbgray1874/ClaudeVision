from pathlib import Path
from typing import Any, Dict, List
import os
import tempfile

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None

try:
    import numpy as np  # type: ignore
except ImportError:  # pragma: no cover
    np = None

from extractor_patterns import normalize_text
from layout_zones import bom_rows_to_text, segment_bom_rows
from layout_zones import zone_boxes as _zone_boxes
from layout_zones import words_in_box as _words_in_box
from layout_zones import words_to_text as _words_to_text

try:
    import ollama  # type: ignore
except Exception:  # pragma: no cover
    ollama = None


_OCR_INSTANCE = None
_OCR_IMPORT_ATTEMPTED = False
_PADDLEOCR_CLASS = None


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


def reset_ocr_instance() -> None:
    global _OCR_INSTANCE
    _OCR_INSTANCE = None


def _use_ollama() -> bool:
    return os.getenv("VISION_USE_OLLAMA", "1").strip().lower() in {"1", "true", "yes", "on"}


def _ollama_model() -> str:
    return os.getenv("VISION_OLLAMA_MODEL", "llava:13b").strip() or "llava:13b"


def _is_critical_page(idx: int, title_block_text: str, bom_text: str, ocr_conf: float, word_count: int) -> bool:
    upper_tb = (title_block_text or "").upper()
    upper_bom = (bom_text or "").upper()
    if idx == 1:
        return True
    if "SCALE" in upper_tb or "DRAWN" in upper_tb or "DWG" in upper_tb:
        return True
    if any(token in upper_bom for token in {"ITEM", "QTY", "BOM", "DESCRIPTION", "DWG"}):
        return True
    if ocr_conf < 0.82 or word_count < 80:
        return True
    return False


def _ollama_reconcile(image_path: str, prompt: str) -> str:
    if not _use_ollama() or ollama is None:
        return ""
    try:
        response = ollama.chat(
            model=_ollama_model(),
            messages=[{"role": "user", "content": prompt, "images": [image_path]}],
        )
        message = response.get("message", {}) if isinstance(response, dict) else {}
        return str(message.get("content", "")).strip()
    except Exception:
        return ""


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
            bom_rows_words = segment_bom_rows(region_words.get("bom", []), y_tolerance=5.0)
            bom_rows = [
                {
                    "row_text": _words_to_text(row),
                    "word_count": len(row),
                }
                for row in bom_rows_words
                if row
            ]
            bom_text = normalize_text(
                f"{bom_rows_to_text(bom_rows_words)} {_words_to_text(region_words.get('notes', []))}"
            )
            ocr_conf = round(sum(word.get("confidence", 0.0) for word in words) / len(words), 3) if words else 0.0
            is_critical = _is_critical_page(
                idx,
                region_text.get("title_block", ""),
                bom_text,
                ocr_conf,
                len(words),
            )
            reconciled_text = ""
            used_llava = False
            if is_critical and _use_ollama() and ollama is not None:
                prompt = (
                    "You are an expert OCR assistant for manufacturing drawings. "
                    "Extract title block fields, BOM rows (ITEM, DWG NO, DESCRIPTION, QTY), "
                    "dimensions, material, revision, and notes exactly as shown. "
                    "Preserve numeric precision and symbols."
                )
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                    temp_image_path = handle.name
                try:
                    pix.save(temp_image_path)
                    reconciled_text = _ollama_reconcile(temp_image_path, prompt)
                    used_llava = bool(reconciled_text)
                finally:
                    try:
                        os.unlink(temp_image_path)
                    except Exception:
                        pass
            pages.append(
                {
                    "page_number": idx,
                    "ocr_engine": "paddleocr" if _get_ocr() is not None else "unavailable",
                    "ocr_word_count": len(words),
                    "ocr_confidence_avg": ocr_conf,
                    "ocr_text": _words_to_text(words),
                    "ocr_text_reconciled": reconciled_text,
                    "region_text": region_text,
                    "bom_table_text": bom_text,
                    "bom_rows": bom_rows,
                    "revision_table_text": revision_text,
                    "drawings": page.get_drawings(),
                    "vision_model": _ollama_model() if used_llava else "",
                    "used_llava": used_llava,
                    "process_callouts": [],
                    "layout_engine": "layoutparser_ready",
                    "table_engine": "img2table_ready",
                    "confidence": {
                        "ocr": ocr_conf,
                        "reconciled": 0.92 if used_llava else 0.0,
                    },
                }
            )
    finally:
        document.close()
    return pages
