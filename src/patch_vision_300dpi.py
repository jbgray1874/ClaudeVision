r"""
patch_vision_300dpi.py — render the live vision path at 300 DPI (was 144).

vision_extraction.extract_document_vision is the LIVE vision path (imported by file_scan). It has
ONE render at line 130 — `fitz.Matrix(2, 2)` = 144 DPI — which feeds BOTH PaddleOCR (_ocr_page_image)
and, when critical, llava (same pixmap -> temp PNG -> ollama.chat). OCR accuracy is highly DPI-
sensitive; 300 DPI is the sweet spot. Both consumers are LOCAL (no token cost), so we render at a
true 300 DPI with only a generous memory cap for extreme sheets.

FIX: replace the hardcoded Matrix(2,2) with a config-driven 300-DPI render:
    zoom = VISION_RENDER_DPI / 72.0   (default 300 -> ~4.17)
    cap the long side at VISION_MAX_SIDE px (default 4000) — shrink zoom only if exceeded
Both via env knobs (consistent with the existing VISION_USE_OLLAMA / VISION_OLLAMA_MODEL envs in
this file). Improves OCR + llava together. Match-or-refuse, AST-validated, backup.
"""
import ast, shutil, datetime, os

T = r"C:\ClaudeVision\src\vision_extraction.py"

OLD = '''        for idx, page in enumerate(document, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)'''

NEW = '''        # Render DPI for OCR + llava. 300 DPI is the OCR sweet spot (was 144 via Matrix(2,2)).
        # Both consumers are local (no token cost); cap the long side for memory on huge sheets.
        _vis_dpi = float(os.getenv("VISION_RENDER_DPI", "300") or "300")
        _vis_max_side = float(os.getenv("VISION_MAX_SIDE", "4000") or "4000")
        for idx, page in enumerate(document, start=1):
            _zoom = _vis_dpi / 72.0
            try:
                _rect = page.rect
                _long_pts = max(float(_rect.width), float(_rect.height))
                if _long_pts * _zoom > _vis_max_side and _long_pts > 0:
                    _zoom = _vis_max_side / _long_pts
            except Exception:
                pass
            pix = page.get_pixmap(matrix=fitz.Matrix(_zoom, _zoom), alpha=False)'''

def apply():
    src = open(T, encoding="utf-8").read()
    # ensure os is imported at module level (it's used via getenv elsewhere already)
    if "import os" not in src:
        print("NOTE: 'import os' not found at module level — checking usage...")
    n = src.count(OLD)
    if n != 1:
        print(f"REFUSE: anchor found {n} times (need 1). No changes.")
        return False
    new = src.replace(OLD, NEW, 1)
    try:
        ast.parse(new)
    except SyntaxError as e:
        print(f"REFUSE: AST parse failed: {e}. No changes.")
        return False
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = T + f".bak_vis300_{ts}"
    shutil.copy2(T, bak)
    open(T, "w", encoding="utf-8").write(new)
    print(f"OK: vision render now 300 DPI (config VISION_RENDER_DPI, cap VISION_MAX_SIDE=4000). Backup: {os.path.basename(bak)}")
    print("Improves both PaddleOCR + llava reads. Env-tunable. Verify os is imported in vision_extraction.py.")
    return True

if __name__ == "__main__":
    apply()
