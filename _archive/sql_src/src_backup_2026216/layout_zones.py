from typing import Any, Dict, List, Tuple

from extractor_patterns import normalize_text


def zone_boxes(page_width: float, page_height: float) -> Dict[str, Tuple[float, float, float, float]]:
    return {
        "title_block": (page_width * 0.58, page_height * 0.72, page_width, page_height),
        "bom": (0.0, page_height * 0.55, page_width * 0.55, page_height),
        "notes": (page_width * 0.55, 0.0, page_width, page_height * 0.5),
        "revision": (page_width * 0.72, page_height * 0.55, page_width, page_height * 0.8),
    }


def words_in_box(words: List[Dict[str, Any]], box: Tuple[float, float, float, float]) -> List[Dict[str, Any]]:
    x0, top, x1, bottom = box
    selected: List[Dict[str, Any]] = []
    for word in words:
        word_x0 = float(word.get("x0", 0.0))
        word_x1 = float(word.get("x1", 0.0))
        word_top = float(word.get("top", 0.0))
        word_bottom = float(word.get("bottom", 0.0))
        if word_x1 >= x0 and word_x0 <= x1 and word_bottom >= top and word_top <= bottom:
            selected.append(word)
    return selected


def words_to_text(words: List[Dict[str, Any]]) -> str:
    ordered = sorted(words, key=lambda item: (round(float(item.get("top", 0.0)), 1), float(item.get("x0", 0.0))))
    return normalize_text(" ".join(str(item.get("text", "")) for item in ordered))


def segment_bom_rows(words: List[Dict[str, Any]], y_tolerance: float = 5.0) -> List[List[Dict[str, Any]]]:
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: float(w.get("top", 0.0)))
    rows: List[List[Dict[str, Any]]] = []
    current_row: List[Dict[str, Any]] = [sorted_words[0]]
    current_top = float(sorted_words[0].get("top", 0.0))
    for word in sorted_words[1:]:
        word_top = float(word.get("top", 0.0))
        if abs(word_top - current_top) <= y_tolerance:
            current_row.append(word)
        else:
            rows.append(sorted(current_row, key=lambda w: float(w.get("x0", 0.0))))
            current_row = [word]
            current_top = word_top
    if current_row:
        rows.append(sorted(current_row, key=lambda w: float(w.get("x0", 0.0))))
    return rows


def bom_rows_to_text(rows: List[List[Dict[str, Any]]]) -> str:
    lines = [words_to_text(row) for row in rows if row]
    return "\n".join(line for line in lines if line)
