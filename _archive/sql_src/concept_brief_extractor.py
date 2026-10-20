from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import config
from concept_pricing import build_concept_part_rows, estimate_concept_pricing

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\x00", " ").replace("\r", " ").split())


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ocr_image(image_path: Path) -> Tuple[str, Dict[str, Any]]:
    try:
        from PIL import Image  # type: ignore
    except ImportError:  # pragma: no cover
        Image = None  # type: ignore

    if Image is not None:
        try:
            import pytesseract  # type: ignore

            with Image.open(image_path) as img:
                text = pytesseract.image_to_string(img) or ""
            normalized = _normalize_text(text)
            if normalized:
                return text, {"engine": "pytesseract", "status": "ok"}
        except Exception as exc:  # pragma: no cover
            tesseract_error = str(exc)
        else:
            tesseract_error = None
    else:
        tesseract_error = "Pillow not installed"

    try:
        import easyocr  # type: ignore

        reader = easyocr.Reader(["en"], gpu=False)
        results = reader.readtext(str(image_path), detail=0, paragraph=True)
        text = "\n".join(str(item) for item in results if str(item).strip())
        normalized = _normalize_text(text)
        if normalized:
            return text, {"engine": "easyocr", "status": "ok", "fallback_from": tesseract_error}
    except Exception as exc:  # pragma: no cover
        easyocr_error = str(exc)
    else:
        easyocr_error = None

    return "", {
        "engine": None,
        "status": "unavailable",
        "errors": [error for error in [tesseract_error, easyocr_error] if error],
    }


def _extract_pptx(path: Path) -> Dict[str, Any]:
    slide_texts: List[Dict[str, Any]] = []
    media_items: List[Dict[str, Any]] = []
    temp_dir = Path(tempfile.mkdtemp(prefix="concept_brief_media_"))

    with zipfile.ZipFile(path) as archive:
        slide_names = sorted(
            [name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
            key=lambda value: int(re.search(r"(\d+)", value).group(1)),
        )
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        for slide_index, name in enumerate(slide_names, start=1):
            root = ET.fromstring(archive.read(name))
            texts = [" ".join("".join(node.itertext()).split()) for node in root.findall(".//a:t", ns)]
            texts = [text for text in texts if text]
            slide_texts.append(
                {
                    "slide_number": slide_index,
                    "embedded_text": texts,
                }
            )

        for media_name in sorted(name for name in archive.namelist() if name.startswith("ppt/media/")):
            output_path = temp_dir / Path(media_name).name
            output_path.write_bytes(archive.read(media_name))
            ocr_text, ocr_meta = _ocr_image(output_path)
            media_items.append(
                {
                    "media_name": output_path.name,
                    "media_path": str(output_path),
                    "ocr_text": ocr_text,
                    "ocr_metadata": ocr_meta,
                }
            )

    return {
        "source_type": "pptx",
        "slide_count": len(slide_texts),
        "slides": slide_texts,
        "media_items": media_items,
    }


def _extract_image(path: Path) -> Dict[str, Any]:
    ocr_text, ocr_meta = _ocr_image(path)
    return {
        "source_type": "image",
        "slide_count": 1,
        "slides": [{"slide_number": 1, "embedded_text": []}],
        "media_items": [
            {
                "media_name": path.name,
                "media_path": str(path),
                "ocr_text": ocr_text,
                "ocr_metadata": ocr_meta,
            }
        ],
    }


def _extract_pdf(path: Path) -> Dict[str, Any]:
    if fitz is None:
        return {
            "source_type": "pdf",
            "slide_count": 0,
            "slides": [],
            "media_items": [],
            "warnings": ["PyMuPDF not available for PDF concept extraction."],
        }

    temp_dir = Path(tempfile.mkdtemp(prefix="concept_brief_pdf_"))
    document = fitz.open(str(path))
    media_items: List[Dict[str, Any]] = []
    slides: List[Dict[str, Any]] = []
    try:
        for index, page in enumerate(document, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            image_path = temp_dir / f"page_{index}.png"
            pix.save(str(image_path))
            ocr_text, ocr_meta = _ocr_image(image_path)
            slides.append({"slide_number": index, "embedded_text": []})
            media_items.append(
                {
                    "media_name": image_path.name,
                    "media_path": str(image_path),
                    "ocr_text": ocr_text,
                    "ocr_metadata": ocr_meta,
                }
            )
    finally:
        document.close()

    return {
        "source_type": "pdf",
        "slide_count": len(slides),
        "slides": slides,
        "media_items": media_items,
    }


def _extract_source(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        return _extract_pptx(path)
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return _extract_image(path)
    raise ValueError(f"Unsupported concept source type: {path.suffix}")


def _collect_text(extracted: Dict[str, Any]) -> Dict[str, Any]:
    embedded_lines: List[str] = []
    for slide in extracted.get("slides", []):
        embedded_lines.extend(slide.get("embedded_text", []))

    ocr_lines: List[str] = []
    for media in extracted.get("media_items", []):
        text = media.get("ocr_text", "") or ""
        for raw_line in text.splitlines():
            normalized = _normalize_text(raw_line)
            if normalized:
                ocr_lines.append(normalized)

    return {
        "embedded_text_lines": embedded_lines,
        "ocr_text_lines": ocr_lines,
        "full_text": "\n".join(embedded_lines + ocr_lines),
    }


def _find_first(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
    match = re.search(pattern, text, flags=flags)
    return match.group(1).strip() if match else None


def _find_int(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[int]:
    value = _find_first(pattern, text, flags=flags)
    return _safe_int(value)


def _find_float(pattern: str, text: str, flags: int = re.IGNORECASE) -> Optional[float]:
    value = _find_first(pattern, text, flags=flags)
    return _safe_float(value)


def _infer_client(path: Path, full_text: str) -> Optional[str]:
    upper = full_text.upper()
    for candidate in ["GILLETTE", "P&G", "PROCTER", "GROOMING"]:
        if candidate in upper:
            return "Gillette" if candidate == "GILLETTE" else candidate.title()
    stem = path.stem
    token = stem.split()[0].strip()
    return token if token else None


def _infer_product_name(path: Path, text_lines: List[str]) -> str:
    for line in text_lines:
        if "VERSION" in line.upper() or "CAGE" in line.upper():
            return line
    return path.stem


def _extract_dimensions(full_text: str) -> Dict[str, Optional[float]]:
    length = _find_float(r"LENGTH\s+(\d+(?:\.\d+)?)", full_text)
    depth = _find_float(r"DEPTH\s+(\d+(?:\.\d+)?)", full_text)
    height = _find_float(r"HEIGHT\s+(\d+(?:\.\d+)?)", full_text)
    if length is None:
        matches = re.findall(r"\b(\d+(?:\.\d+)?)\b", full_text)
        numbers = [_safe_float(value) for value in matches if _safe_float(value) is not None]
        dimension_candidates = [value for value in numbers if 300 <= value <= 2500]
        if len(dimension_candidates) >= 3:
            length = length or dimension_candidates[0]
            depth = depth or dimension_candidates[1]
            height = height or max(dimension_candidates[:3])
    return {
        "length": length,
        "depth": depth,
        "height_including_wheels": height,
    }


def _extract_feature_summary(full_text: str) -> Dict[str, Any]:
    text = full_text
    rals = sorted(set(re.findall(r"RAL\s*\d{4}", text, flags=re.IGNORECASE)))
    tube_sizes = re.findall(r"(\d+)\s*[xX]\s*(\d+)\s*cm", text, flags=re.IGNORECASE)
    panel_match = re.search(r"(\d+)\s+GILLETTE\s+BRANDING\s+PANELS?\s+(\d+)\s*[xX]\s*(\d+)\s*mm", text, flags=re.IGNORECASE)
    bins_match = re.search(r"(\d+)\s+PLASTIC\s+BINS?\s+(\d+)\s*[xX]\s*(\d+)\s*[xX]\s*(\d+)\s*mm", text, flags=re.IGNORECASE)
    rails_match = re.search(r"(\d+)\s+RAILS?\s+AND\s+(\d+)\s+SEPARATORS?", text, flags=re.IGNORECASE)

    return {
        "shelves": {
            "count": _find_int(r"(\d+)\s+STEEL\s+SHELVES?", text),
            "adjustable": "ADJUSTABLE" in text.upper(),
        },
        "doors": {
            "count": _find_int(r"(\d+)\s+DOORS?", text),
            "hinges_per_door": _find_int(r"ON\s+(\d+)\s+HINGES", text),
        },
        "locks": {
            "spring_locks": _find_int(r"(\d+)\s+SPRING\s+LOCKS?", text),
            "padlock": {
                "type": "code padlock" if "PADLOCK" in text.upper() else None,
                "digits": _find_int(r"(\d+)\s+DIGITS?", text),
                "brand": _find_first(r"FROM\s+([A-Z0-9]+)", text),
            },
        },
        "branding": {
            "panel_count": _safe_int(panel_match.group(1)) if panel_match else None,
            "panel_size_mm": {
                "width": _safe_float(panel_match.group(2)) if panel_match else None,
                "height": _safe_float(panel_match.group(3)) if panel_match else None,
            },
            "brand": "Gillette" if "GILLETTE" in text.upper() else None,
        },
        "bins": {
            "count": _safe_int(bins_match.group(1)) if bins_match else None,
            "size_mm": {
                "length": _safe_float(bins_match.group(2)) if bins_match else None,
                "width": _safe_float(bins_match.group(3)) if bins_match else None,
                "height": _safe_float(bins_match.group(4)) if bins_match else None,
            },
        },
        "internal_fixtures": {
            "rails": _safe_int(rails_match.group(1)) if rails_match else None,
            "separators": _safe_int(rails_match.group(2)) if rails_match else None,
            "intended_use": "distinguish men's and women's shavers" if "DISTINGUISH MEN'S AND WOMEN'S SHAVERS" in text.upper() else None,
        },
        "security_accessory": {
            "anti_theft_decoupler": {
                "supply_required": "ANTI-THEFT DECOUPLER" in text.upper() or "ANTI THEFT DECOUPLER" in text.upper(),
                "fixing_required": "FIXING" in text.upper(),
            }
        },
        "mobility": {
            "wheel_count": _find_int(r"(\d+)\s+WHEELS?", text),
            "braked_wheels": _find_int(r"WITH\s+(\d+)\s+WHEELS?\s+ALL\s+WITH\s+BRAKES", text) or (_find_int(r"(\d+)\s+WHEELS?\s+ALL\s+WITH\s+BRAKES", text)),
        },
        "structure": {
            "tube_sizes_cm": [f"{left} x {right}" for left, right in tube_sizes],
            "mesh_description": _find_first(r"GRIDS?\s+IN\s+([0-9A-Z\s]+WIRE\s+MESH)", text),
        },
        "finish": {
            "primary_finish": _find_first(r"([A-Z\s]+EPOXY\s+FINISH)", text),
            "primary_colour": rals[0] if rals else None,
            "all_ral_codes": rals,
        },
    }


def _build_risk_flags(brief: Dict[str, Any]) -> List[str]:
    flags = [
        "client_originated_not_design_controlled",
        "concept_pricing_only",
    ]
    if not brief.get("assembly_summary", {}).get("overall_dimensions_mm", {}).get("length"):
        flags.append("missing_primary_dimensions")
    if not brief.get("features", {}).get("structure", {}).get("tube_sizes_cm"):
        flags.append("missing_structure_detail")
    flags.append("no_part_level_bom")
    flags.append("no_manufacturing_detail_drawing")
    return sorted(set(flags))


def build_concept_brief(path: str | Path) -> Dict[str, Any]:
    source_path = Path(path).resolve()
    extracted = _extract_source(source_path)
    text_payload = _collect_text(extracted)
    full_text = text_payload["full_text"]
    text_lines = text_payload["embedded_text_lines"] + text_payload["ocr_text_lines"]

    overall_dimensions = _extract_dimensions(full_text)
    features = _extract_feature_summary(full_text)

    brief: Dict[str, Any] = {
        "source_type": "client_concept_presentation",
        "document_type": "concept_brief",
        "source_file": source_path.name,
        "full_path": str(source_path),
        "scanned_at": datetime.now().isoformat(timespec="seconds"),
        "client": _infer_client(source_path, full_text),
        "product_name": _infer_product_name(source_path, text_lines),
        "drawing_metadata": {
            "page_count": extracted.get("slide_count", 0),
            "embedded_image_count": len(extracted.get("media_items", [])),
            "extraction_mode": extracted.get("source_type"),
            "ocr_engines_used": sorted(
                {
                    item.get("ocr_metadata", {}).get("engine")
                    for item in extracted.get("media_items", [])
                    if item.get("ocr_metadata", {}).get("engine")
                }
            ),
        },
        "assembly_summary": {
            "product_family": "mobile stock cage",
            "overall_dimensions_mm": overall_dimensions,
            "primary_finish": features.get("finish", {}).get("primary_finish"),
            "primary_colour": features.get("finish", {}).get("primary_colour"),
        },
        "features": features,
        "commercial_requirements": {
            "packaging": "all in one individual package" if "ALL IN ONE INDIVIDUAL PACKAGE" in full_text.upper() else None,
            "installation_scope": [
                requirement
                for requirement in [
                    "supply and fixing of an anti-theft decoupler" if "ANTI-THEFT DECOUPLER" in full_text.upper() or "ANTI THEFT DECOUPLER" in full_text.upper() else None,
                    "install 6 rails and 9 separators" if "6 RAILS" in full_text.upper() and "9 SEPARATORS" in full_text.upper() else None,
                ]
                if requirement
            ],
        },
        "raw_evidence": {
            "embedded_text_lines": text_payload["embedded_text_lines"],
            "ocr_text_lines": text_payload["ocr_text_lines"],
            "media_items": extracted.get("media_items", []),
        },
    }

    pricing = estimate_concept_pricing(brief)
    brief["cost_breakdown"] = pricing
    brief["parts"] = build_concept_part_rows(features, pricing)
    brief["risk_flags"] = _build_risk_flags(brief)
    brief["nesting_recommendations"] = {
        "status": "not_applicable_at_concept_stage",
        "reason": "No manufacturing detail geometry or flat patterns available from client concept file.",
    }
    brief["alternative_processes"] = []
    brief["quality_metrics"] = {
        "overall_confidence": 0.72 if text_payload["ocr_text_lines"] else 0.35,
        "extraction_issues": len(brief["risk_flags"]),
        "pricing_transparency": pricing.get("confidence", {}).get("pricing_transparency"),
        "geometry_confidence": "assembly_level_only",
    }
    return brief


def write_concept_brief_json(path: str | Path, output_path: str | Path | None = None) -> Path:
    source_path = Path(path).resolve()
    target = Path(output_path) if output_path else (config.JSON_DIR / f"{source_path.stem}.concept.json")
    brief = build_concept_brief(source_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(brief, handle, indent=2, ensure_ascii=False)
    return target
