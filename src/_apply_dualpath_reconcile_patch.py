r"""LIVE PATCH v2 (safer: self-contained at call site, no fragile module-level def placement).
Match-or-refuse, AST-validated, timestamped backup. Fixes the hybrid BOM.

Inserts a SINGLE self-contained block right after the dual-path override in file_scan.py:1223.
The block imports estimator locally and defines its helpers as inner functions, so there is NO
module-level insertion (removes all placement risk). Logic (validated by 4 dry-runs on 12120):
  1) CODE match vs part_estimates -> update qty, no add (prevents THUM620 double-add)
  2) TOKEN match vs bought-in parts (estimator._bought_in_token_set/_same_item) -> dual-path qty
     wins (fixes self-clinch 1->4, knob 1->2)
  3) No match -> APPEND clean BI-<TYPE> row (adds the missing pem stud, clean code not 'STD PART')
Fabricated parts untouched. Failure-isolated.
"""
import ast, shutil, datetime

SRC=r"C:\ClaudeVision\src\file_scan.py"
bak=SRC+".bak_dualpathrecon_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

with open(SRC,encoding="utf-8") as f: src=f.read()

ANCHOR = '''            if _dp.get("rows"):
                _da = summary.setdefault("document_analysis", {})
                _da["bom_rows"] = _dp["rows"]
                _da["bom_code_quality_findings"] = _dp.get("findings", [])
                _debug(f"dual-path bom_rows applied: {len(_dp['rows'])} rows")
        except Exception as _dp_err:
            _debug(f"dual-path bom_rows hook skipped: {_dp_err}")'''

if src.count(ANCHOR) != 1:
    raise SystemExit(f"REFUSE: anchor found {src.count(ANCHOR)}x (need exactly 1). No change made.")

# Self-contained replacement: same anchor + a reconcile block whose helpers are all inner defs.
REPLACEMENT = ANCHOR + '''

        # -- Dual-path -> part_estimates reconciliation (self-contained) -----------
        # bom_rows was updated above, but the SHEET reads estimate_summary.part_estimates.
        # Push dual-path fastener quantities/identities into part_estimates so they reach
        # the sheet. Failure-isolated; fabricated parts never touched.
        try:
            if _dp.get("rows"):
                import estimator as _E_recon
                import re as _re_recon

                _es_recon = summary.setdefault("estimate_summary", {})
                _parts_recon = _es_recon.get("part_estimates")
                if _parts_recon is None:
                    _parts_recon = summary.get("part_estimates")

                if isinstance(_parts_recon, list):

                    def _is_fastener_row(_r):
                        _d = (str(_r.get("description") or "") + " " +
                              str(_r.get("part_code") or _r.get("code") or
                                  _r.get("part_number") or "")).upper()
                        return any(_k in _d for _k in ("CLINCH", "NUT", "KNURL", "KNOB",
                                   "THUMB", "SCREW", "PEM", "STUD", "RIVET", "THUM",
                                   "WASHER", "BOLT", "GLIDE"))

                    def _dp_code(_r):
                        return str(_r.get("part_code") or _r.get("code") or
                                   _r.get("part_number") or "").strip()

                    def _dp_qty(_r):
                        _q = _r.get("qty") or _r.get("quantity") or _r.get("qty_per_unit")
                        try:
                            return int(float(_q)) if _q is not None else None
                        except (TypeError, ValueError):
                            return None

                    def _p_code(_p):
                        return str(_p.get("part_number") or "").strip().upper()

                    def _clean_code(_desc, _fallback):
                        _dU = (_desc or "").upper()
                        _fb = (_fallback or "").upper().strip()
                        _VAGUE = ("STD PART", "FIXING", "FIXINGTBC", "TBC", "STDPART", "")
                        if _fb not in _VAGUE and _re_recon.search(r"\\d", _fb):
                            return _fallback
                        _MAP = [
                            (r"SELF[\\s-]?CLINCH.*NUT|CLINCH.*NUT", "BI-SELFCLINCHNUT"),
                            (r"KNURLED.*KNOB", "BI-KNURLEDKNOB"),
                            (r"KNURLED.*NUT", "BI-KNURLEDNUT"),
                            (r"THREADED.*PEM.*STUD|PEM.*STUD", "BI-PEMSTUD"),
                            (r"KEYHOLE.*PEM", "BI-KEYHOLEPEM"),
                            (r"MUSHROOM.*THUMB|THUMB.*SCREW", "BI-THUMBSCREW"),
                            (r"BUTTON.*HEAD.*SCREW", "BI-BUTTONSCREW"),
                            (r"DOME.*RIVET|POP.*RIVET|RIVET", "BI-RIVET"),
                            (r"NUT", "BI-NUT"), (r"SCREW", "BI-SCREW"),
                            (r"WASHER", "BI-WASHER"), (r"BOLT", "BI-BOLT"),
                        ]
                        for _pat, _code in _MAP:
                            if _re_recon.search(_pat, _dU):
                                return _code
                        return _fallback or "BI-FIXING"

                    _added = _updated = 0
                    for _r in _dp["rows"]:
                        if not _is_fastener_row(_r):
                            continue
                        _code = _dp_code(_r)
                        _qty = _dp_qty(_r)
                        _desc = str(_r.get("description") or _code)
                        if _qty is None or _qty <= 0:
                            _qty = 1

                        # 1) CODE match -> update qty, no add
                        _cm = None
                        if _code:
                            for _p in _parts_recon:
                                if _p_code(_p) == _code.upper():
                                    _cm = _p
                                    break
                        if _cm is not None:
                            if _cm.get("quantity") != _qty:
                                _cm["quantity"] = _qty
                                _cm.setdefault("review_flags", []).append(
                                    f"Quantity set to {_qty} from dual-path BOM table read")
                                _updated += 1
                            continue

                        # 2) TOKEN match vs bought-in parts -> dual-path qty wins
                        _ctoks = _E_recon._bought_in_token_set({"description": _desc})
                        _tm = None
                        if _ctoks is not None:
                            for _p in _parts_recon:
                                _roles = _p.get("page_roles") or []
                                if not ("bought_in" in _roles or _p_code(_p).startswith("BI-")):
                                    continue
                                _ptoks = _E_recon._bought_in_token_set(_p)
                                if _ptoks is not None and _E_recon._bought_in_same_item(_ctoks, _ptoks):
                                    _tm = _p
                                    break
                        if _tm is not None:
                            if _tm.get("quantity") != _qty:
                                _old = _tm.get("quantity")
                                _tm["quantity"] = _qty
                                _tm.setdefault("review_flags", []).append(
                                    f"Quantity corrected {_old} -> {_qty} from dual-path BOM "
                                    f"table read (matched '{_desc}')")
                                _updated += 1
                            continue

                        # 3) No match -> ADD clean bought-in row
                        _cc = _clean_code(_desc, _code)
                        if any(_p_code(_p) == _cc.upper() for _p in _parts_recon):
                            continue
                        _parts_recon.append({
                            "part_number": _cc, "description": _desc, "quantity": _qty,
                            "pages": [], "page_roles": ["bought_in"], "materials": [],
                            "surface_finishes": [], "colours": [], "thicknesses_mm": [],
                            "weights": [], "textual_operations": ["handling"],
                            "inferred_operations": [], "flat_pattern_detected": False,
                            "assembly_candidate": False, "process_notes": [],
                            "review_flags": [
                                f"Added from dual-path BOM table read (code '{_code}' -> "
                                f"'{_cc}'), qty {_qty} - price via waterfall, estimator to verify"],
                            "confidence": {"overall": 0.0}, "source": "non_sdi_bom_row",
                        })
                        _added += 1

                    if _es_recon.get("part_estimates") is not None:
                        _es_recon["part_estimates"] = _parts_recon
                    else:
                        summary["part_estimates"] = _parts_recon
                    if _added or _updated:
                        print(f"   [dual-path recon] part_estimates: {_updated} qty-corrected, "
                              f"{_added} added from BOM table read")
        except Exception as _dpr_err:
            _debug(f"dual-path part_estimates reconcile skipped: {_dpr_err}")'''

src2 = src.replace(ANCHOR, REPLACEMENT, 1)

# AST validate the WHOLE modified file
ast.parse(src2)

shutil.copy2(SRC, bak)
with open(SRC, "w", encoding="utf-8") as f: f.write(src2)
print(f"PATCHED  {SRC}")
print(f"backup   {bak}")
print("Self-contained reconcile block inserted after dual-path override (no module-level defs).")
print("Verify next with the direct-call test on 12120 + 1282.")
