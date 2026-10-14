"""REPLAY PROBE (D-514): does the saved record's own page text reach the edging reader?

Three runs of 12343-01J charged edging labour on a CEILING while the record's own page text
holds "EDGED ALL AROUND EDGING ORDER: 2S/SL" verbatim. The harvester, the stamp and the
reader all pass their tests on that exact text — so the live decline is structural, and this
probe replays the saved record through the SAME functions the estimate calls, printing every
gate's verdict:

    1  each page: its role, the drawing numbers its title block names, how much text it
       carries, and what the harvester finds in that text;
    2  each part list the record holds: the part numbers, whether banding_statements is
       already on them, what the estimate-time stamp does, and the banded length the edging
       reader then resolves (basis and millimetres);
    3  the edging MATERIAL line the estimator would mint: code and metres, or the reason
       there are none.

Read-only: nothing is written back to the record.

    python tools\\probe_banding_stamp.py output\\json\\12343-01J.json
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


def main(path: str) -> None:
    with open(path, encoding="utf-8") as handle:
        summary = json.load(handle)

    from edge_banding import (banded_length_mm, harvest_banding_statements,
                              stamp_banding_statements_from_pages)
    try:
        from extractor_patterns import strip_specification_legend as _strip
    except Exception:                                                # noqa: BLE001
        def _strip(t):                                               # type: ignore[misc]
            return str(t or "")

    pages = summary.get("pages") or []
    print(f"record: {path}")
    print(f"pages: {len(pages)}")
    for i, pg in enumerate(pages):
        if not isinstance(pg, dict):
            print(f"  page {i + 1}: NOT A DICT ({type(pg).__name__})")
            continue
        role = pg.get("page_role")
        role = role.get("primary_role") if isinstance(role, dict) else role
        pa = pg.get("page_analysis") or {}
        tb = (pa.get("title_block") or {}) if isinstance(pa, dict) else {}
        codes = list(tb.get("drawing_numbers") or [])
        for k in ("current_number", "primary_drawing_number"):
            if tb.get(k):
                codes.append(f"{k}={tb.get(k)}")
        bits = [pg.get("text_preview"), pg.get("pdfplumber_text"),
                pg.get("normalized_text"), pg.get("pypdf_text")]
        rt = pg.get("region_text")
        if isinstance(rt, dict):
            bits.extend(rt.values())
        text = " ".join(str(b) for b in bits if b)
        hits = harvest_banding_statements(_strip(text))
        print(f"  page {i + 1}: role={role!r}  title-block numbers={codes!r}  "
              f"text={len(text)} chars  harvest={hits!r}")

    part_lists = [("manufacturing_writeup.parts",
                   (summary.get("manufacturing_writeup") or {}).get("parts") or []),
                  ("summary.parts", summary.get("parts") or [])]
    for label, plist in part_lists:
        plist = [p for p in plist if isinstance(p, dict)]
        if not plist:
            print(f"{label}: none")
            continue
        print(f"{label}: {[p.get('part_number') for p in plist]}")
        for p in plist:
            print(f"  before: {p.get('part_number')}: "
                  f"banding_statements={p.get('banding_statements')!r}")
        n = stamp_banding_statements_from_pages(plist, summary)
        print(f"  stamp fired on {n} part(s)")
        for p in plist:
            out = banded_length_mm(p) or {}
            print(f"  after:  {p.get('part_number')}: basis={out.get('basis')!r} "
                  f"mm={out.get('mm')!r} "
                  f"statements={p.get('banding_statements')!r}")

        # The edging MATERIAL line the estimator's block would mint from these parts.
        try:
            import config
            from costed_facts import is_other_sheet_material
            edge_mm = 0.0
            for p in plist:
                board = False
                try:
                    board = is_other_sheet_material(p.get("normalized_material") or "")
                except Exception:                                    # noqa: BLE001
                    board = False
                if not (board or p.get("_laminate_in_board")
                        or (p.get("material_estimate") or {}).get(
                            "costing_material_family")):
                    continue
                v = banded_length_mm(p) or {}
                if v.get("mm"):
                    qty = p.get("quantity") or 1
                    try:
                        qty = float(qty)
                    except (TypeError, ValueError):
                        qty = 1.0
                    edge_mm += float(v["mm"]) * qty
            if edge_mm > 0:
                print(f"  edging line WOULD MINT: code="
                      f"{getattr(config, 'FACED_BOARD_EDGING_CODE', '?')} "
                      f"at {edge_mm / 1000.0:.3f} m a unit")
            else:
                print("  edging line: NO METRES — the line would not mint from this list")
        except Exception as exc:                                     # noqa: BLE001
            print(f"  edging line calc failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    main(sys.argv[1])
