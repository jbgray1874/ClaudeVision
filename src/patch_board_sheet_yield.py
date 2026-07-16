#!/usr/bin/env python3
r"""
patch_board_sheet_yield.py
--------------------------
Adds the faced-board (MFC) sheet-yield pricing lane, reverse-engineered from the
Rev G manual (Egger MFC GBP 60.43/sheet x parts-per-sheet x scrap). Edits four files:

  drawing_job_merge.py : add an MFC/PRE-LAM/MFMDF token BEFORE plain \bMDF\b so faced
                         board resolves to the faced class (not plain MDF).
  json_normaliser.py   : map MFC / MFMDF / PRE LAM MDF / MELAMINE FACED -> MFC.
  config.py            : add MFC sheet sizes (incl Egger 2800x2070), a per-kg fallback,
                         and BOARD_SHEET_PRICE_GBP = {MFC: 60.43}.
  estimator.py         : price board classes that have a configured sheet price by
                         sheet-yield (mirrors the acrylic branch), else unchanged.

Safe by construction: only material that resolves to MFC changes pricing; every other
material/job is byte-identical. Per file: idempotent (skips if already applied),
all-or-nothing (verifies every anchor before writing), preserves CRLF, writes .bak,
and compile-checks. Run from C:\ClaudeVision\src in your venv:  python patch_board_sheet_yield.py

NOTE: this fixes the board CLASS + PRICING METHOD. The table-top panel (01J) is still
under-captured by the DXF part-merge (a separate drawing_job_merge change), so the board
total will not fully land until that fix — see the chat notes.
"""
import sys, os, py_compile, json

JOBS = json.loads(r"""[["drawing_job_merge.py", "MFC", [["    (r\"\\bACRYLIC\\b|\\bACR\\b|\\bPERSPEX\\b|\\bPMMA\\b\", \"ACRYLIC\"),\n    (r\"POLYCARB|\\bPC\\b\", \"POLYCARBONATE\"),\n    (r\"\\bCARD\\b|GREYBOARD|GREY\\s*BOARD\", \"CARD\"),\n    (r\"\\bMDF\\b\", \"MDF\"),\n    (r\"PLYWOOD|\\bPLY\\b\", \"PLYWOOD\"),\n    (r\"STAINLESS|\\bSS\\b|\\b304\\b|\\b316\\b\", \"STAINLESS STEEL\"),", "    (r\"\\bACRYLIC\\b|\\bACR\\b|\\bPERSPEX\\b|\\bPMMA\\b\", \"ACRYLIC\"),\n    (r\"POLYCARB|\\bPC\\b\", \"POLYCARBONATE\"),\n    (r\"\\bCARD\\b|GREYBOARD|GREY\\s*BOARD\", \"CARD\"),\n    # Faced sheet board (melamine-faced / pre-laminated MDF/chipboard) — MUST precede the\n    # plain \\bMDF\\b token so \"PRE LAM MDF\" / \"MFMDF\" resolve to the faced class (priced by\n    # the sheet at the faced rate), not plain MDF priced by mass.\n    (r\"MFMDF|MELAMINE\\s*FACED|PRE\\s*LAM(?:INATE)?|PRELAM|\\bMFC\\b\", \"MFC\"),\n    (r\"\\bMDF\\b\", \"MDF\"),\n    (r\"PLYWOOD|\\bPLY\\b\", \"PLYWOOD\"),\n    (r\"STAINLESS|\\bSS\\b|\\b304\\b|\\b316\\b\", \"STAINLESS STEEL\"),"]]], ["json_normaliser.py", "\"MFC\": \"MFC\"", [["    \"OAK VENEER MDF\": \"OAK_VENEER_MDF\",\n    \"OAK VENEER\": \"OAK_VENEER_MDF\",\n    \"OAK MDF\": \"OAK_VENEER_MDF\",\n    \"PAPER\": \"BOUGHT_IN\",\n    \"PRINTED PAPER\": \"BOUGHT_IN\",\n    \"DISPA BOARD\": \"BOUGHT_IN\",", "    \"OAK VENEER MDF\": \"OAK_VENEER_MDF\",\n    \"OAK VENEER\": \"OAK_VENEER_MDF\",\n    \"OAK MDF\": \"OAK_VENEER_MDF\",\n    \"MELAMINE FACED MDF\": \"MFC\",\n    \"MELAMINE FACED\": \"MFC\",\n    \"PRE LAM MDF\": \"MFC\",\n    \"PRE LAMINATE\": \"MFC\",\n    \"PRELAM\": \"MFC\",\n    \"PRE LAM\": \"MFC\",\n    \"MFMDF\": \"MFC\",\n    \"MFC\": \"MFC\",\n    \"PAPER\": \"BOUGHT_IN\",\n    \"PRINTED PAPER\": \"BOUGHT_IN\",\n    \"DISPA BOARD\": \"BOUGHT_IN\","]]], ["config.py", "BOARD_SHEET_PRICE_GBP", [["    \"MDF_BOARD\": [(2440, 1220), (3050, 1525)],\n    \"VENEERED MDF\": [(2440, 1220), (3050, 1525)],\n    \"OAK_VENEER_MDF\": [(2440, 1220), (3050, 1525)],\n    \"PLYWOOD\": [(2440, 1220), (3050, 1525)],\n    \"BIRCH_PLYWOOD\": [(2440, 1220), (3050, 1525)],\n    \"TIMBER\": [(2400, 1200)],", "    \"MDF_BOARD\": [(2440, 1220), (3050, 1525)],\n    \"VENEERED MDF\": [(2440, 1220), (3050, 1525)],\n    \"OAK_VENEER_MDF\": [(2440, 1220), (3050, 1525)],\n    # Faced board (MFC / melamine-faced). Egger oversize board is 2800x2070; 2440x1220 kept\n    # as the standard fallback so nesting picks whichever yields more parts.\n    \"MFC\": [(2800, 2070), (2440, 1220)],\n    \"PLYWOOD\": [(2440, 1220), (3050, 1525)],\n    \"BIRCH_PLYWOOD\": [(2440, 1220), (3050, 1525)],\n    \"TIMBER\": [(2400, 1200)],"], ["    \"PLYWOOD\": 1.45,\n    \"BIRCH_PLYWOOD\": 1.65,\n    \"OAK_VENEER_MDF\": 2.20,\n    \"HDPE_PLASTIC\": 2.85,\n    \"SOFTWOOD\": 0.95,\n    \"HIGH IMPACT ACRYLIC\": 3.26,", "    \"PLYWOOD\": 1.45,\n    \"BIRCH_PLYWOOD\": 1.65,\n    \"OAK_VENEER_MDF\": 2.20,\n    \"MFC\": 2.20,\n    \"HDPE_PLASTIC\": 2.85,\n    \"SOFTWOOD\": 0.95,\n    \"HIGH IMPACT ACRYLIC\": 3.26,"], ["    8.0: 112.00,\n    10.0: 138.00,\n    \"default\": 46.20,\n}\nACRYLIC_OP_DRIVERS = {\n    # CANONICAL — reverse-engineered from the M18 (10897) workbook acrylic cells; reproduces", "    8.0: 112.00,\n    10.0: 138.00,\n    \"default\": 46.20,\n}\n\n# Faced sheet board priced per SHEET (nested), mirroring the manual estimate's\n# \"real sheet price x parts-per-sheet + scrap\" method rather than by mass. Keyed by the\n# normalised material code. Only classes listed here are routed through the sheet-yield\n# board path in estimator.estimate_material; any board class without an entry falls back\n# to the existing per-kg path unchanged (so no other job's pricing shifts).\n#   MFC = Egger H131 Natural Davos Oak MFC, Latham, confirmed GBP 60.43/sheet (Rev G manual).\nBOARD_SHEET_PRICE_GBP = {\n    \"MFC\": 60.43,\n    \"default\": 60.43,\n}\nACRYLIC_OP_DRIVERS = {\n    # CANONICAL — reverse-engineered from the M18 (10897) workbook acrylic cells; reproduces"]]], ["estimator.py", "board_sheet_yield", [["                applied=True, applied_basis=\"acrylic_sheet_price_per_sheet_provisional\",\n            ),\n        }\n    external_price = _resolve_material_price(material, thickness, quantity, part=part)\n    external_result = external_price.get(\"result\", {})\n", "                applied=True, applied_basis=\"acrylic_sheet_price_per_sheet_provisional\",\n            ),\n        }\n    # Faced sheet board (MFC / melamine-faced / pre-lam) is bought and costed by the SHEET\n    # with a nesting yield, exactly like the manual estimate (Egger MFC £60.43/sheet ÷\n    # parts-per-sheet × (1+scrap)) — NOT by mass. The £/kg path mis-states the buy. Gated\n    # strictly to board classes that have a configured sheet price (config.BOARD_SHEET_PRICE_GBP),\n    # so any board without one falls through to the existing per-kg path unchanged.\n    _mat_brd = str(material or \"\").upper()\n    _board_prices = getattr(config, \"BOARD_SHEET_PRICE_GBP\", {}) or {}\n    if _mat_brd in _board_prices and blank_length and blank_width:\n        try:\n            _brd_price = float(_board_prices.get(_mat_brd) or _board_prices.get(\"default\"))\n        except (TypeError, ValueError):\n            _brd_price = None\n        if _brd_price:\n            _brd_scrap = float(getattr(config, \"SCRAP_PERCENTAGE\", 0.04))\n            _brd_sheet_est = select_sheet_size(material, blank_length, blank_width)\n            _brd_pps = _brd_sheet_est.get(\"parts_per_sheet\") or 1\n            if not _brd_pps or int(_brd_pps) < 1:\n                _brd_pps = 1\n            _brd_cost_part = (_brd_price / _brd_pps) * (1.0 + _brd_scrap)\n            _brd_area_m2 = (float(blank_length) * float(blank_width)) / 1_000_000.0\n            _brd_ext = round(_brd_cost_part * quantity, 2)\n            return {\n                \"material\": material,\n                \"thickness_mm\": thickness,\n                \"blank_length_mm\": blank_length,\n                \"blank_width_mm\": blank_width,\n                \"blank_area_m2\": round(_brd_area_m2, 4),\n                \"unit_material_mass_kg\": None,\n                \"unit_material_cost_gbp\": round(_brd_cost_part, 2),\n                \"cost_per_part_gbp\": round(_brd_cost_part, 2),\n                \"extended_sheet_material_cost_gbp\": _brd_ext,\n                \"powder_consumable\": None,\n                \"extended_material_cost_gbp\": _brd_ext,\n                \"stock_estimate\": _brd_sheet_est,\n                \"cost_method\": \"board_sheet_yield\",\n                \"part_confidence_overall\": _part_confidence_overall(part),\n                \"part_geometry_reliability\": _part_geometry_reliability(part),\n                \"reliability_flags\": [\"board_sheet_priced\"],\n                \"note\": \"Faced board sheet-nested cost — £%.2f/sheet ÷ %s parts/sheet × (1+%.0f%% scrap).\" % (_brd_price, _brd_pps, _brd_scrap * 100.0),\n                \"price_source\": _build_price_source_metadata(\n                    {}, fallback_source=\"board_sheet_price_per_sheet\",\n                    applied=True, applied_basis=\"board_sheet_price_per_sheet\",\n                ),\n            }\n\n    external_price = _resolve_material_price(material, thickness, quantity, part=part)\n    external_result = external_price.get(\"result\", {})\n"]]]]""")

def patch_one(name, marker, pairs):
    path = os.path.abspath(name)
    if not os.path.isfile(path):
        print(f"[skip] {name}: not found at {path}")
        return None
    with open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    crlf = "\r\n" in raw
    norm = raw.replace("\r\n", "\n")
    if marker in norm:
        print(f"[ok]   {name}: already applied (marker present) - no change")
        return True
    for old, _new in pairs:
        n = norm.count(old)
        if n != 1:
            print(f"[ABORT] {name}: an anchor matched {n}x (expected 1). File not written.")
            print(f"        Your {name} differs from the expected base here - send it and I'll rebase.")
            return False
    patched = norm
    for old, new in pairs:
        patched = patched.replace(old, new, 1)
    out = patched.replace("\n", "\r\n") if crlf else patched
    with open(path + ".bak", "w", encoding="utf-8", newline="") as f:
        f.write(raw)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(raw)
        print(f"[FAIL] {name}: compile error - restored .bak\n{e}")
        return False
    print(f"[done] {name}: patched ({len(pairs)} hunk(s)), .bak written, compiles ({'CRLF' if crlf else 'LF'})")
    return True

def main():
    print("Applying board sheet-yield lane to 4 files...\n")
    results = [patch_one(name, marker, pairs) for name, marker, pairs in JOBS]
    ok = sum(1 for r in results if r)
    print(f"\n{ok}/{len(JOBS)} file(s) ready.")
    if all(r is not False for r in results):
        print('Re-run:  python main.py --search-root "...0354158_FlatPackTrestle" --folder-as-job')
        return 0
    print("One or more files aborted - nothing partial was left behind on those.")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
