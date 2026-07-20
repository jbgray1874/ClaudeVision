r"""
Patch: in document_builder._apply_post_build_fixes, an assembly-only zero-geometry
part hits `continue` (the 8-space `if (...)` block) and is dropped from all downstream
processing -- so a described bought-in commodity on an assembly page ("ELECTRICS 50CM"
/ LOOM LIGHTING ELECTRICS, 1282 page 10) keeps roles ["assembly"] + source None and
never becomes a candidate for _reconcile_bought_in -> duplicate loom (it costs
standalone AND BI-50CMLOOM costs too).

Fix: immediately before that continue, if the part is clearly a bought-in commodity
(assembly-only, zero-geometry, NON-SDI part number, real description), add the
"bought_in" role so the reconciler folds it against the note-scan/manual-sheet loom.
SDI drawing refs (1455-C-101, 1455-C-GA) and any geometry-bearing part are excluded.

Exact-string match-or-refuse + ast.parse before write.
Run:  C:\\ClaudeVision\\.venv\\Scripts\\python.exe patch_assembly_boughtin_retag.py
"""
import pathlib

SRC = pathlib.Path(r"C:\ClaudeVision\src\document_builder.py")

ANCHOR = '        if (\n            geo_reliability == 0.0\n            and page_roles\n            and all(r == "assembly" for r in page_roles)\n            and not _is_wire_part\n        ):\n            continue\n'

REPLACEMENT = '        if (\n            geo_reliability == 0.0\n            and page_roles\n            and all(r == "assembly" for r in page_roles)\n            and not _is_wire_part\n        ):\n            # Before dropping this assembly-only, zero-geometry line: if it is a\n            # bought-in COMMODITY (a described purchased item, not an SDI drawing\n            # part), tag it "bought_in" so the estimator\'s bought-in reconciler can\n            # fold it against the note-scan / manual-sheet duplicate (e.g. the loom:\n            # "ELECTRICS 50CM" vs "BI-50CMLOOM"). SDI drawing refs (1455-C-101,\n            # 1455-C-GA) and any geometry-bearing part are excluded, so real\n            # sub-assemblies and make-parts are never mis-tagged. We still fall through\n            # to the drop below — a bought-in line needs no fabrication ops.\n            import re as _re_bi\n            _pn_bi = str(part.get("part_number") or "").strip().upper()\n            _has_geom_bi = bool(\n                part.get("dxf_augmented")\n                or part.get("blank_length_mm")\n                or part.get("overall_length_mm")\n                or (part.get("dxf_raw_geometry") or {}).get("blank_area_mm2")\n            )\n            if (\n                _pn_bi\n                and not _re_bi.match(r"^\\d{3,5}-", _pn_bi)\n                and not _has_geom_bi\n                and _is_good_description(part.get("description"))\n                and "bought_in" not in page_roles\n            ):\n                part["page_roles"] = list(page_roles) + ["bought_in"]\n                part.setdefault("review_flags", []).append(\n                    "assembly_page_bought_in_commodity_retagged"\n                )\n            continue\n'


def run():
    src = SRC.read_text(encoding="utf-8")
    if "assembly_page_bought_in_commodity_retagged" in src:
        print("ABORT: retag already present -- nothing changed.")
        return
    if src.count(ANCHOR) != 1:
        print(f"ABORT: anchor found {src.count(ANCHOR)} times (need exactly 1). Nothing changed.")
        return
    src2 = src.replace(ANCHOR, REPLACEMENT, 1)
    import ast
    try:
        ast.parse(src2)
    except SyntaxError as e:
        print(f"ABORT: patched result failed syntax check ({e}). Nothing written.")
        return
    SRC.write_text(src2, encoding="utf-8")
    print("OK: assembly-page bought-in retag inserted before the drop.")
    print()
    print("RE-RUN flag ON and check:")
    print(r'  $env:SDI_DUALPATH_BOM="1"')
    print(r'  C:\ClaudeVision\.venv\Scripts\python.exe main.py --search-root "K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay" --folder-as-job')
    print("  1) SINGLE loom: BI-50CMLOOM kept (rank-3 beats loom source=None rank-0) at 24.15; [reconcile] 1 merged.")
    print("  2) 1455-C-101 still its own part (SDI code -> not retagged).")
    print("  3) FIXINGs still clean.")


if __name__ == "__main__":
    run()
