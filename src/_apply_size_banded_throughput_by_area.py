#!/usr/bin/env python3
r"""
_apply_size_banded_throughput_by_area.py

JG spotted that M176 (Total Unit Cost) is a FORMULA, unresolved when the labour block runs,
so keying the size band on it would silently fall back to the default every time. Correct.

THE FIX: key the band on PART AREA, which the engine already computes for nesting and which
is known the instant the labour block runs. No workbook formula, no dependency on Excel
having recalculated, no SQL.

WHY THE SAME MEDIANS STILL APPLY

The medians were measured banded by JOB UNIT COST:
    Assemble/pack:  A(<15)=90  B=30  C=20  D(150+)=15
    P.Coat:         A(<15)=638 B=319 C=319 D=319
Fold, measured the same way, matched Tim (93.76 vs 90), so the measurement is sound.

Cost and size move together for sheet metal - a small part is a cheap job. So the medians
travel with the BAND, and we only need area boundaries that reproduce the cost bands. Known
parts confirm them:
    1310 hook       0.019 m2   job GBP 6.90   -> A
    12439 acrylic   0.010 m2   job GBP 1.30   -> A
    1282 bay panel  0.30  m2   job GBP 170     -> D
    =>  A < 0.05    B 0.05-0.15    C 0.15-0.40    D >= 0.40  (m2)

WHAT DECIDES THE BAND

The job's LARGEST fabricated part by area - pack and coat speed track the biggest thing in
the job, not the average. The engine already computes each part's blank area (L x W) for the
Sheet Steel nesting block; we reuse it. Wire/bar parts contribute their cylinder area.

WHAT THIS TOUCHES - only the two size-driven ops
    Assemble/pack, P.Coat.  Fold and Laser are derived and not in the band table. Robomac and
    Weld are not size-driven and not in it. They all fall through untouched.

Every number is a config lever (THROUGHPUT_SIZE_BANDS, THROUGHPUT_AREA_EDGES).

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_size_banded_throughput_by_area.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

CONFIG = r"C:\ClaudeVision\src\config.py"
TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "THROUGHPUT_SIZE_BANDS"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


C_ANCHOR = '''POWDER_MIN_KG_PER_PIECE = 0.03'''

C_NEW = '''POWDER_MIN_KG_PER_PIECE = 0.03

# Size-banded throughput (pieces/hour). Medians MEASURED 2026-07-14 from 1,982 historical jobs
# (throughput recovered from raw_line_json $.J.labels.left), banded by product size. Fold,
# measured the same way, matched the estimator to 4% (93.76 vs 90), so the measurement holds.
#
# ONLY operations where SIZE is genuinely the driver belong here. Fold/Laser are derived from
# the drawing/template and must not be banded; Robomac (driver: wire length + bends) and Weld
# (driver: weld count, on no drawing) are not size-driven and are deliberately absent.
#
# KEYED ON PART AREA, not job cost: area is known when the labour block runs; unit cost is an
# unresolved workbook formula at that point. Boundaries reproduce the original cost bands and
# are confirmed against known parts (1310 hook 0.019 m2 -> A; 1282 bay panel 0.30 m2 -> D).
THROUGHPUT_SIZE_BANDS = {
    "Assemble/pack (Metal)":   {"A": 90, "B": 30, "C": 20, "D": 15},
    "Assemble/pack (Acrylic)": {"A": 90, "B": 30, "C": 20, "D": 15},
    "P.Coat":                  {"A": 638, "B": 319, "C": 319, "D": 319},
}
# m2 boundaries: A < 0.05 <= B < 0.15 <= C < 0.40 <= D
THROUGHPUT_AREA_EDGES = (0.05, 0.15, 0.40)'''


W_IMPORT_ANCHOR = '''try:
    from config import POWDER_MIN_KG_PER_PIECE as _POWDER_MIN_KG_PER_PIECE
except Exception:
    _POWDER_MIN_KG_PER_PIECE = 0.03'''

W_IMPORT_NEW = '''try:
    from config import POWDER_MIN_KG_PER_PIECE as _POWDER_MIN_KG_PER_PIECE
except Exception:
    _POWDER_MIN_KG_PER_PIECE = 0.03
try:
    from config import THROUGHPUT_SIZE_BANDS as _THROUGHPUT_SIZE_BANDS
    from config import THROUGHPUT_AREA_EDGES as _THROUGHPUT_AREA_EDGES
except Exception:
    _THROUGHPUT_SIZE_BANDS = {}
    _THROUGHPUT_AREA_EDGES = (0.05, 0.15, 0.40)'''


# Compute the job's largest fabricated-part area ONCE, up where the powder area is already
# being computed (that block already walks _all_pes_pw and has _sheet/_wire area logic).
W_AREA_ANCHOR = '''    _powder_kg_total = round(max(_powder_by_area_kg, _powder_by_floor_kg), 5)'''

W_AREA_NEW = '''    _powder_kg_total = round(max(_powder_by_area_kg, _powder_by_floor_kg), 5)

    # Largest fabricated part by area (m2) - the size proxy for throughput banding. Pack and
    # coat speed track the biggest part in the job, not the average. Reuses the same geometry
    # the powder area calc reads; known when the labour block runs, unlike the unit-cost cell.
    _max_part_area_m2 = 0.0
    for _ap in _all_pes_pw:
        _ame = _ap.get("material_estimate") or {}
        _asf = str(_ame.get("stock_form") or "").lower()
        _ang = _ap.get("normalized_geometry") or {}
        _aq = _safe(_ap.get("quantity"), 1) or 1
        _area = 0.0
        if _asf in ("sheet", "plate", "board", ""):
            _al = _safe(_ame.get("blank_length_mm") or _ang.get("blank_length_mm"))
            _aw = _safe(_ame.get("blank_width_mm") or _ang.get("blank_width_mm"))
            if _al and _aw:
                _area = (_al / 1000.0) * (_aw / 1000.0)
        elif _asf in ("wire", "bar"):
            _ag = _safe(_ame.get("gauge_mm") or _ame.get("diameter_mm"))
            _aln = _safe(_ame.get("length_mm") or _ame.get("cut_length_mm"))
            if _ag and _aln:
                _area = 3.14159265 * (_ag / 1000.0) * (_aln / 1000.0)
        if _area > _max_part_area_m2:
            _max_part_area_m2 = _area'''


W_PICK_ANCHOR = '''        default_tp = _THROUGHPUT_DEFAULTS.get(wb_op or "")'''

W_PICK_NEW = '''        default_tp = _THROUGHPUT_DEFAULTS.get(wb_op or "")

        # ── SIZE-BANDED DEFAULT, keyed on the job's largest part AREA ────────────────
        # For Assemble/pack and P.Coat one number cannot be right - a small part is packed
        # and coated far faster than a big one. Pick the band from _max_part_area_m2, which
        # is known here (unlike unit cost, a workbook formula). Fold/Laser are not in the
        # band table (derived); Robomac/Weld are not (not size-driven) - all fall through.
        _bands = _THROUGHPUT_SIZE_BANDS.get(wb_op or "")
        if _bands and _max_part_area_m2 > 0:
            _e1, _e2, _e3 = _THROUGHPUT_AREA_EDGES
            _a = _max_part_area_m2
            _band = "A" if _a < _e1 else "B" if _a < _e2 else "C" if _a < _e3 else "D"
            _banded = _bands.get(_band)
            if _banded:
                _flag(f"throughput for '{wb_op}' size-banded on part area: largest part "
                      f"{_max_part_area_m2:.4f} m2 -> band {_band} -> {_banded}/hr "
                      f"(was default {default_tp}/hr). MEASURED from your own history by product "
                      f"size - a small part runs faster than a big one, and one median cannot "
                      f"say that. Retune in config.THROUGHPUT_SIZE_BANDS.", flags)
                default_tp = _banded
        elif _bands and _max_part_area_m2 <= 0:
            _flag(f"throughput for '{wb_op}': wanted to size-band it but no fabricated part "
                  f"area was computed - using the un-banded default {default_tp}/hr. Not "
                  f"guessing a band.", flags)'''


def main():
    for p in (CONFIG, TARGET):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")
    cfg = open(CONFIG, "r", encoding="utf-8").read()
    wbp = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in cfg or SENTINEL in wbp:
        sys.exit("Already applied (sentinel present).")

    cfg = sub(cfg, C_ANCHOR, C_NEW, "config: area-keyed size bands for Pack + P.Coat")
    wbp = sub(wbp, W_IMPORT_ANCHOR, W_IMPORT_NEW, "wb_populate: import the bands + area edges")
    wbp = sub(wbp, W_AREA_ANCHOR, W_AREA_NEW, "wb_populate: compute largest-part area once")
    wbp = sub(wbp, W_PICK_ANCHOR, W_PICK_NEW, "wb_populate: pick banded default from part area")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, text in ((CONFIG, cfg), (TARGET, wbp)):
        bak = f"{path}.bak_areaband_{ts}"
        shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(text)
        print(f"  backup: {bak}")

    print("""
RUN 1310 (qty 50), THEN 1282 (qty 10).

    1310 - largest part is the hook plate, 0.0189 m2 -> band A:
        Assemble/pack   58 -> 90     GBP 0.64 -> 0.46     (Tim 0.29)
        P.Coat         458 -> 638     GBP 2.55 -> 2.33     (Tim 2.00)
        unit cost      GBP 7.82 -> ~7.44   (Tim 6.90)
        Two flags will name the band, the area, and the numbers.

    The remaining gap on both lines is now SETUP, not throughput:
        our Pack setup 15 min vs Tim's 5. That is the AISheets-vs-Tim template version
        issue, a cell in the rate table - not something the engine sets.

    1282 - its largest panel is a big sheet part -> band C or D:
        Assemble/pack  58 -> 15/20   SLOWER, and correct: a wall bay packs slower per piece
                                     than a hook. This is the band doing its job.
        P.Coat        458 -> 319
        DIFF IT - only Pack/P.Coat throughputs and the totals below may move.

STILL NOT ADDRESSED (correctly):
    Robomac -> derive from wire length + bends (the Fold treatment). Next.
    Weld    -> needs the weld count from Tim. On no drawing.
""")


if __name__ == "__main__":
    main()
