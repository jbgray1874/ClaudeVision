"""
bom_pipeline.py — bridge from the proven dual-path BOM reconciler (merge_boms) into
the live estimator pipeline.

reconciled_bom_rows_for_job() resolves a job's PDFs, runs Path A (deterministic
pdfplumber) + Path B (Grok vision) reconciliation via merge_boms.reconcile_job, and
returns a FLAT list of {part_number, description, quantity} rows — the exact shape
build_document_writeup consumes. Reconciliation provenance (source/confidence/flag/
parent) rides along as extra keys; build_document_writeup ignores them, the drawing-
quality report uses them.

Vision-only codes (a row carrying part_ref with no canonical part_number, e.g. the
1282 kick-plate 1453-GA-C that Path A left blank) are promoted into part_number so
the consumer's part-number-keyed logic (Fix A/B/C dedup + backfill) sees them.
Nothing here calls Grok directly — it delegates to the proven merge_boms functions.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence


def dual_path_enabled() -> bool:
    """Whether the reconciled two-reader BOM is the job's BOM. Default: yes.

    It was built behind SDI_DUALPATH_BOM, default OFF, so that turning it on could not
    change a baseline. The consequence was that no live run ever read a BOM table: the
    rows reaching the estimate came from regexes over pdfplumber's text flow, which
    scrambles ruled CAD tables and needs per-drawing string repairs to survive — the
    opposite of a rule that carries to the next job. A drawing states its own bill of
    materials; reading it is not an experiment.

    SDI_DUALPATH_BOM=0 still forces the old single-reader path for a like-for-like
    comparison. The check lives HERE, once, because it previously existed as two
    independent env reads in file_scan and either could have gone stale on its own.
    """
    return os.getenv("SDI_DUALPATH_BOM", "1").strip().lower() not in {"0", "false", "no", "off"}


# A "formal code" is normalised (whitespace squashed, upper-cased, hyphens cleaned):
#   - SDI drawing reference: starts with a digit  (1453-GA-C, 1450 - GA, 3886-02-)
#   - letter-prefix catalogue code ENDING at its digits  (FIXING 236, VINYL76)
# Anything else — a word/unit description such as 'ELECTRICS 50cm' — is left with its
# internal spacing intact. This matters: the estimator's bought-in reconciler folds
# described commodities (loom, foam tape) by FUZZY TOKEN SUBSET, and squashing
# '50cm' into the code destroys the standalone 50/cm tokens its match needs — which
# duplicated the loom on 1282 (ELECTRICS50CM no longer folded into BI-50CMLOOM).
# Formal codes (FIXING236) still squash because they dedup by EXACT code, not tokens.
_SDI_CODE_RE = re.compile(r"^\d")
_LETTER_CODE_RE = re.compile(r"^[A-Za-z]+\s*\d+$")


# EVERY DRAWING HAS A BORDER, AND IT IS NUMBERED.
#
# M&S 2085's sheet is gridded 1-20 across and A-I down. The deterministic table reader
# swallowed "...14 15 16 17 18 19 20" sitting immediately before the "ITEM NO." header and
# emitted part_number "1415", description "16 17 18 19", quantity 20. It was priced by an AI
# market estimate at GBP 10.54 each: GBP 219.21 of a GBP 273.98 unit cost, 80% of the job,
# from the picture frame.
#
# The vision pass refused to corroborate it and the row was flagged "A-only ... review". The
# flag was right and nothing acted on it. This does: a description with no letters in it is
# not a description, and a part number that is only digits with no separator is not one of
# SDI's or a customer's. Neither test alone is safe — a real row can be "1415" if the
# customer numbers that way, and "M6 x 20" is a real description — so both must hold.
_ALPHA = None


def is_drawing_furniture(code: str, description: str) -> bool:
    """True when a BOM row is the drawing's own border grid rather than a part.

    Deliberately narrow. Dropping a real BOM line is far worse than costing a phantom one:
    a phantom is visible in the total and gets challenged, a missing part is silent.
    """
    import re as _re
    desc = str(description or "").strip()
    code_s = str(code or "").strip()
    if not desc or not code_s:
        return False
    # A description with any letter in it is somebody's words. Only pure digits, spaces and
    # punctuation can be grid furniture.
    if _re.search(r"[A-Za-z]", desc):
        return False
    # And the code must itself be featureless: digits only, no separator of any kind. Real
    # numbering here always carries one (2085-01, 12120-01-01M, BI-KNURLEDKNOB, THUM620).
    if not _re.fullmatch(r"\d+", code_s):
        return False
    return True


def _norm_code(raw: Any) -> str:
    """Canonicalise a BOM code, but ONLY for formal codes (SDI refs and letter-prefix
    catalogue codes). Descriptions keep their spacing so fuzzy bought-in reconciliation
    still works. Idempotent on clean Path-A codes; repairs vision variants like
    '3886-GA-' -> '3886-GA', '1450 - GA' -> '1450-GA', 'FIXING 236' -> 'FIXING236';
    leaves 'ELECTRICS 50cm' untouched."""
    s = str(raw or "").strip()
    if _SDI_CODE_RE.match(s) or _LETTER_CODE_RE.match(s):
        s = re.sub(r"\s+", "", s).upper()
        s = re.sub(r"-{2,}", "-", s)
        return s.strip("-")
    return s


def reconciled_bom_rows_for_job(
    *,
    folder: Optional[Any] = None,
    pdfs: Optional[Sequence[Any]] = None,
    **opts: Any,
) -> Dict[str, Any]:
    """Run the dual-path reconcile for a job and flatten to bom_rows.

    Exactly one of ``folder`` (a job folder — all PDFs discovered via the
    case-insensitive DEDUPED merge_boms.find_pdfs) or ``pdfs`` (an explicit list)
    should be given. ``opts`` are forwarded to reconcile_job (dpi, max_side, model,
    cache_dir, no_cache, refresh, force_llm, refresh_file).

    Returns {'rows': [...], 'findings': [...], 'counts': {...}, 'pdf_paths': [...]}.
    On no PDFs or an import failure the caller keeps its existing rows (empty 'rows').
    Deliberately does NOT dedup rows: the same code legitimately recurs across parent
    BOMs, and the downstream consumer (Fix B/C dedup) + bom_tree qty resolution apply
    their own existing logic — matching how the pipeline treats bom_rows today.
    """
    from merge_boms import find_pdfs, reconcile_job

    if folder is not None:
        pdf_paths = find_pdfs(str(folder))
    elif pdfs:
        pdf_paths = [str(p) for p in pdfs if p]
    else:
        pdf_paths = []
    if not pdf_paths:
        return {"rows": [], "findings": [], "counts": {}, "pdf_paths": [],
                "a_count": 0, "b_count": 0}

    result = reconcile_job(pdf_paths, verbose=False, **opts)

    flat: List[Dict[str, Any]] = []
    findings_extra: List[Dict[str, Any]] = []
    # Parents, not pages. A page is one sheet; a parent is one drawing's bill of
    # materials, which is the thing an estimate is built from. Reading pages here gave a
    # parent whose list spans two sheets two half-BOMs, and a fixings table repeated on
    # a detail sheet double the fixings. Falls back to pages so an older reconcile
    # result — or a caller that builds one by hand — still flattens.
    _groups = result.get("parents")
    if _groups is None:
        _groups = result.get("pages", [])
    for pg in _groups:
        parent = pg.get("label")
        _parent_known = pg.get("parent_known", True)
        for r in pg.get("rows", []):
            code = _norm_code(r.get("part_number") or r.get("part_ref") or "")
            desc = str(r.get("description") or "").strip()
            try:
                qty = int(r.get("quantity"))
            except (TypeError, ValueError):
                qty = 1
            if is_drawing_furniture(code, desc):
                findings_extra.append({
                    "code": "bom_row_is_drawing_furniture",
                    "detail": f"dropped BOM row part='{code}' desc='{desc}' qty={qty} — "
                              f"a description with no letters in it is not a part name; this "
                              f"is the drawing's border grid, read as a BOM line",
                    "page": parent,
                })
                continue
            _row_out = {
                # --- the three keys build_document_writeup reads ---
                "part_number": code,
                "description": desc,
                "quantity": qty,
                # --- source_pdf: the parent-BOM label, so bom_tree.resolve_effective_
                #     quantities can group our rows by drawing and cascade the parent GA
                #     multiplier into the leaves (e.g. 1448-01 x1 under 1448-GA x2 -> 2).
                #     bom_tree keys its whole tree on source_pdf; without this our rows
                #     are invisible to it and leaves stay at their per-sub-assembly qty.
                "source_pdf": parent,
                # --- provenance: ignored by the consumer, used by the report ---
                "bom_source": r.get("source"),
                "bom_confidence": r.get("confidence"),
                "bom_flag": r.get("flag"),
                "bom_parent": parent,
                # False when the sheet's title block named no drawing and this group is a
                # file+page placeholder. It groups the rows correctly and it is not a
                # drawing number, so nothing downstream may hang a hierarchy on it.
                "bom_parent_known": _parent_known,
                # Which sheet the row was read off, and any others that restated it.
                "bom_sheet": r.get("sheet"),
                # The ITEM number the table printed. Two rows of one parent's table with the
                # same code and different item numbers are two lines (12173-07-2-GA lists its
                # handed SIDE PANEL as items 1 and 3, qty 1 each) and add up (D-335).
                #
                # ITS OWN KEY, NEVER "item_number". Readers across the engine take a row's
                # identity as `part_number or item_number`, so under that name a row with an
                # empty code column became a part called "4": 12645's hinge (item 4 of
                # 12645-03GA's table) came back as a second hinge line priced at £0.26 on the
                # 29 Sep 21:27 book (D-344). A position in a table is not a part.
                "bom_item_no": (str(r.get("item_number")).strip()
                                if r.get("item_number") not in (None, "") else None),
                "bom_also_on_sheets": list(r.get("also_on_sheets") or []) or None,
            }
            # --- THE ROW'S OWN PRINTED SPECIFICATION SURVIVES THE FLATTEN. The readers
            #     were taught to keep material / thickness / mass, and this dict is
            #     where the review probe found them dying: a new dictionary that copied
            #     everything except the fields needed to retire the blanket-6mm
            #     assumption. Copied only when a reader actually stamped them, so an
            #     SDI row without the columns is byte-identical.
            for _ev in ("material_text", "thickness_mm", "stated_weight_kg",
                        "segmentation_uncertain", "code_token", "length_mm"):
                _v = r.get(_ev)
                if _v not in (None, ""):
                    _row_out[_ev] = _v
            flat.append(_row_out)
    # A reader that did not run is the only failure this module cannot see in its output:
    # the rows simply are not there, and a job read by one path looks exactly like a job
    # both paths agreed was small. Promote every unread scope to a finding so the absence
    # is stated rather than inferred from a count nobody compares.
    for u in result.get("unread", []) or []:
        _scope = u.get("scope")
        _where = u.get("pdf") or "this job"
        if u.get("page") is not None:
            _where = f"{_where} page {int(u['page']) + 1}"
        findings_extra.append({
            "code": "bom_reader_did_not_run",
            "detail": (
                f"{'deterministic' if u.get('path') == 'A' else 'vision'} BOM reader did not "
                f"read {_where}: {u.get('detail')}. Rows it would have contributed are not "
                f"missing from the BOM — they are unknown, and no row on this "
                f"{'job' if _scope == 'job' else _scope} carries two-reader corroboration."
            ),
            "page": u.get("pdf") or None,
            "severity": "blocking" if _scope == "job" else "review",
        })
    return {
        "rows": flat,
        "findings": list(result.get("findings", [])) + findings_extra,
        "unread": list(result.get("unread", []) or []),
        # {'paid','cached','skipped'} vision calls. Reported so the cost of a run is a
        # number an estimator can see rather than something inferred from the bill.
        "vision_calls": dict(result.get("vision_calls") or {}),
        "counts": result.get("counts", {}),
        "pdf_paths": result.get("pdf_paths", []),
        # a_count/b_count = how many BOM tables each reader found across the job.
        # Surfaced so a caller can tell an EMPTY dual-path result apart: a_count==0
        # means the deterministic reader found no table (reader bug), b_count==0 means
        # Grok vision was unavailable/uncached (offline — Path A alone still suffices).
        "a_count": result.get("a_count", 0),
        "b_count": result.get("b_count", 0),
    }


def _row_is_codeless(r: Dict[str, Any]) -> bool:
    """A row the drawing printed without a code (or with a placeholder), and that no reader
    has given an identity of its own — the only kind a parent's reader may claim."""
    from part_identity import is_placeholder_identity
    if r.get("identity_source"):
        return False
    code = str(r.get("part_number") or "").strip()
    return not code or is_placeholder_identity(code)


def _row_parent(r: Any) -> str:
    """The bare code of the drawing whose table printed this row, or "" when unnamed."""
    from part_code_conventions import bare_code
    if not isinstance(r, dict) or r.get("bom_parent_known") is False:
        return ""
    return bare_code(str(r.get("bom_parent") or ""))


def _row_role(r: Dict[str, Any]) -> str:
    """The role the minter gave a codeless row, or the same classifier's answer now. Not
    written back: only a reader that consumes the row stamps it, so a row the minter never
    saw is not questioned on a role nobody acted on."""
    from part_identity import parts_list_row_role
    return str(r.get("row_role") or "") or parts_list_row_role(r.get("description"))


def apply_stated_edging_to_parts(parts: Any, bom_rows: Any) -> int:
    """An edging row on a part's own parts list states that part's banded length (D-381).

    12173-03-01J's table: "EDGING, L: 1979mm  1". The row has no code, so it was never a line
    and never evidence; edging was timed on the 630 x 630 blank's perimeter, 2,520 mm. The row
    belongs to the drawing whose table printed it (bom_parent), and its length x quantity is
    that part's banded length, as a drawing reading. Rows of a table whose drawing was not
    named are left alone — nothing can say whose edge they are. Returns parts stamped.

    THE DRAWING FACT, NOT A SENTENCE (D-383). The stamp records stated_banded_length_mm at
    drawing_deterministic and nothing else: whether the part is banded at all, and on what
    basis, is the estimator's to say when it times the banding (or raises a question when the
    part is not banded), from the same record. A banding row with no length
    ("ABS EDGING 22mm WHITE") is kept on the part as stated_banding_rows, so the banding
    reader's "stated, extent unknown" rung sees it. Rows read here are marked consumed."""
    import source_precedence as sp
    from edge_banding import is_banding_row, stated_edging_length_mm

    by_pn = {}
    from part_code_conventions import bare_code
    for p in parts or []:
        if isinstance(p, dict):
            by_pn.setdefault(bare_code(str(p.get("part_number") or "")), p)
    totals: Dict[str, float] = {}
    for r in bom_rows or []:
        if not isinstance(r, dict):
            continue
        _parent = _row_parent(r)
        desc = str(r.get("description") or "")
        if not _parent or not is_banding_row(desc):
            continue
        mm = stated_edging_length_mm(desc)
        part = by_pn.get(_parent)
        if part is None:
            continue
        r["row_role"], r["consumed"] = "parent_banding", True
        if not mm:
            _rows = part.setdefault("stated_banding_rows", [])
            if isinstance(_rows, list) and desc not in _rows:
                _rows.append(" ".join(desc.split()))
            continue
        try:
            qty = float(r.get("quantity") or 1) or 1.0
        except (TypeError, ValueError):
            qty = 1.0
        totals[_parent] = totals.get(_parent, 0.0) + mm * qty
    n = 0
    for pn, mm in totals.items():
        p = by_pn.get(pn)
        if p is not None and mm and sp.apply_field(p, "stated_banded_length_mm", round(mm, 1),
                                                   "drawing_deterministic"):
            n += 1
    return n


def apply_stated_cut_list_to_parts(parts: Any, bom_rows: Any) -> int:
    """A part's own parts table that lists its section pieces IS its cut list (D-383).

    12173-03-04M's sheet prints "ITEM DESCRIPTION LENGTH QTY / 30.00 x 30.00 x 2.00mm TUBE 1532
    1 / 1532 1 / 290 1 / 350 1" (and 05M's the same), and both table readers carried those four
    rows into bom_rows. D-380 summed the pieces only from the LLM's cut_lengths_mm, so the
    frame's length rested on one transcription nothing deterministic checked — while the rows
    themselves were being minted as bought-in tube (D-381). Here the rows a parent's own table
    prints with no code, which the section reader reads as a canonical profile
    (part_identity.parts_list_row_role -> parent_cut_list), are that parent's pieces:

      * one profile: section_stock {a, b, t, profile_form, cut_lengths_mm, length_mm} is
        written through source_precedence at drawing_deterministic, so it outranks the LLM
        extract (the LLM's list becomes corroboration, and a disagreement is flagged with both
        lists); the summed mass is held against the sheet's stated weight within config
        CUT_LIST_MASS_TOLERANCE, and outside it the length is marked INDICATIVE;
      * several profiles under one part: a question, never a sum of different sections;
      * a profile row with no length ("10 x 30 x 1.50mm TUBE" on 12173-05-01M): it confirms a
        section the part already holds; otherwise it is left for the unread-row question.

    Each row read is marked consumed (row_role parent_cut_list), so it is never minted and
    never dropped silently. Returns parts whose cut list was read."""
    import config
    import source_precedence as sp
    from part_code_conventions import bare_code
    from section_profile import detect_section_stock, section_kg_per_m

    pieces: Dict[str, Dict[tuple, List[float]]] = {}
    rows_of: Dict[str, List[Dict[str, Any]]] = {}
    no_len: Dict[str, List[tuple]] = {}
    for r in bom_rows or []:
        if not isinstance(r, dict):
            continue
        par = _row_parent(r)
        if not par or not _row_is_codeless(r) or _row_role(r) != "parent_cut_list":
            continue
        s = detect_section_stock(str(r.get("description") or ""))
        if not s or s.get("detection_path") != "canonical_profile":
            continue
        # THE TABLE'S OWN LENGTH COLUMN (D-429), where the description does not print one:
        # "ITEM QTY DESCRIPTION LENGTH" puts the piece's length beside the profile, not in it.
        if not s.get("length_mm"):
            try:
                _col_len = float(r.get("length_mm") or 0)
            except (TypeError, ValueError):
                _col_len = 0.0
            if _col_len > 0:
                s = dict(s, length_mm=_col_len)
        key = (min(float(s["a"]), float(s["b"])), max(float(s["a"]), float(s["b"])),
               float(s["t"]), str(s.get("profile_form") or ""))
        if not s.get("length_mm"):
            no_len.setdefault(par, []).append((key, r))
            continue
        try:
            q = max(1, int(round(float(r.get("quantity") or 1))))
        except (TypeError, ValueError):
            q = 1
        pieces.setdefault(par, {}).setdefault(key, []).extend([float(s["length_mm"])] * q)
        rows_of.setdefault(par, []).append(r)

    def _fmt(k: tuple) -> str:
        return "x".join(f"{v:g}" for v in k[:3])

    n = 0
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        pn = bare_code(str(p.get("part_number") or ""))
        # A profile row with no length confirms the section the part already holds.
        for key, r in no_len.get(pn, []):
            ss = p.get("section_stock") if isinstance(p.get("section_stock"), dict) else {}
            try:
                held = (min(float(ss["a"]), float(ss["b"])), max(float(ss["a"]), float(ss["b"])),
                        float(ss["t"]))
            except (KeyError, TypeError, ValueError):
                held = None
            if held is not None and all(abs(h - k) < 0.05 for h, k in zip(held, key[:3])):
                r["row_role"], r["consumed"] = "parent_cut_list", True
        prof = pieces.get(pn)
        if not prof:
            continue
        for r in rows_of.get(pn, []):
            r["row_role"], r["consumed"] = "parent_cut_list", True
        if len(prof) > 1:
            sp.raise_manufacturing_question(
                p,
                (f"{p.get('part_number')}'s own parts table lists pieces of {len(prof)} "
                 f"different sections ({', '.join(_fmt(k) for k in prof)}); no single section "
                 f"length was taken from it"),
                "the section and length the part already carries stand; the pieces are not summed",
                "say which section the part is costed as, or cost each section as its own line",
                "bom_pipeline.apply_stated_cut_list_to_parts")
            continue
        # A PARENT'S TABLE OF PIECES IS NOT ITS OWN STOCK WHEN IT IS AN ASSEMBLY, OR SHEET WE
        # MEASURED: the pieces are its members, and costing them on the parent as one section
        # would put the tube on the bill beside whatever its members already carry.
        _asm = bool(p.get("is_assembly_parent") or p.get("is_sub_assembly")
                    or str(p.get("canonical_kind") or "").lower() == "assembly")
        try:
            from bought_in_policy import has_fabrication_evidence as _measured
            _sheet = bool(_measured(p))
        except Exception:                                        # noqa: BLE001
            _sheet = False
        if _asm or _sheet:
            sp.raise_manufacturing_question(
                p,
                (f"{p.get('part_number')}'s own parts table lists uncoded section pieces "
                 f"({', '.join(_fmt(k) for k in prof)}), but it is "
                 f"{'an assembly' if _asm else 'a part with a measured flat'}; the pieces were "
                 f"not costed as its stock"),
                "nothing is costed for the listed pieces",
                ("say whether the pieces are cut here as members (give them codes or a cut "
                 "list on a part) or are already in a member's cost"),
                "bom_pipeline.apply_stated_cut_list_to_parts")
            continue
        (lo, hi, t, form), pcs = next(iter(prof.items()))
        _ss_now = p.get("section_stock") if isinstance(p.get("section_stock"), dict) else {}
        _held = [float(x) for x in (_ss_now.get("cut_lengths_mm") or [])
                 if isinstance(x, (int, float)) or str(x).replace(".", "", 1).isdigit()]
        _held_by = sp.display_name(sp.source_of(p, "section_stock.cut_lengths_mm")
                                   or _ss_now.get("source") or "an earlier reading")
        for field, value in (("a", lo), ("b", hi), ("t", t), ("profile_form", form or None),
                             ("cut_lengths_mm", list(pcs)), ("length_mm", max(pcs))):
            if value is not None:
                sp.apply_field(p, f"section_stock.{field}", value, "drawing_deterministic")
        ss = p["section_stock"]
        ss.setdefault("detection_path", "canonical_profile")
        if sp.source_of(p, "section_stock.cut_lengths_mm") != "drawing_deterministic":
            # A stronger reader (the model's own cut list) holds the section; apply_field has
            # put the refusal on the part, and the table's mass is not this section's to check.
            n += 1
            continue
        ss["source"] = "drawing_deterministic"
        if _held and sorted(_held) != sorted(pcs):
            p.setdefault("review_flags", []).append(
                f"cut list: the drawing's own parts table reads "
                f"{', '.join(f'{v:g}' for v in sorted(pcs))} mm; {_held_by} read "
                f"{', '.join(f'{v:g}' for v in sorted(_held))} mm — the table is used")
        # THE MASS CHECK. The pieces' steel against the sheet's own WEIGHT. Slots, drains and
        # notches take mass out, so the cut list reads a little heavy; far outside the
        # tolerance the length is held INDICATIVE for a person.
        try:
            from estimator import _parse_stated_weight_kg
            stated = _parse_stated_weight_kg(p)
        except Exception:                                        # noqa: BLE001
            stated = None
        _dens_tab = getattr(config, "MATERIAL_DENSITY_KG_PER_M3", {}) or {}
        _mat = str(p.get("normalized_material") or "").upper()
        _dens = _dens_tab.get(_mat) or _dens_tab.get(_mat.replace("_", " ")) or None
        _kgm = section_kg_per_m(lo, hi, t, form, _dens)
        if stated and _kgm:
            kg = sum(pcs) / 1000.0 * _kgm
            tol = float(getattr(config, "CUT_LIST_MASS_TOLERANCE", 0.15) or 0.15)
            ss["cut_list_mass_check"] = {"kg": round(kg, 3), "stated_kg": stated,
                                         "tolerance": tol}
            if abs(kg - stated) / stated > tol:
                ss["length_indicative"] = True
                p.setdefault("review_flags", []).append(
                    f"cut list {sum(pcs):g} mm of {_fmt((lo, hi, t))} weighs about {kg:.2f} kg; "
                    f"the drawing states {stated:g} kg — the length is INDICATIVE until the "
                    f"pieces or the weight are confirmed")
        n += 1
    return n


def raise_unread_parts_list_rows(parts: Any, bom_rows: Any) -> int:
    """A codeless parts-list row no reader consumed is a question on its parent (D-383).

    part_identity.parts_list_row_role names a codeless row a cut-list piece, the parent's
    edging, an instruction, the parent's material or a size — none of which are minted. The
    readers consume what they can (apply_stated_cut_list_to_parts, apply_stated_edging_to_parts).
    What is left is asked, never dropped: a material row, a placeholder ("TBC"), and a
    cut-list or edging row nobody read become one manufacturing question on the parent each;
    an instruction is noted on the parent. No money is added or removed. Returns questions
    raised."""
    import source_precedence as sp
    from part_code_conventions import bare_code
    from part_identity import is_placeholder_identity
    by_pn = {}
    for p in parts or []:
        if isinstance(p, dict):
            by_pn.setdefault(bare_code(str(p.get("part_number") or "")), p)
    n = 0
    for r in bom_rows or []:
        if not isinstance(r, dict) or r.get("consumed"):
            continue
        role = str(r.get("row_role") or "")
        if role not in ("parent_material", "parent_cut_list", "parent_banding", "instruction"):
            continue
        part = by_pn.get(_row_parent(r))
        if part is None or not _row_is_codeless(r):
            continue
        desc = " ".join(str(r.get("description") or "").split())
        pn = part.get("part_number")
        if role == "instruction" and not is_placeholder_identity(desc):
            _note = (f"parts-list row '{desc}' reads as an instruction, not a part — it was "
                     f"not made a line")
            if _note not in (part.get("review_flags") or []):
                part.setdefault("review_flags", []).append(_note)
            continue
        if role == "instruction":
            issue = (f"{pn}'s parts list carries a row that reads only '{desc}' — no part, no "
                     f"code and no quantity basis")
            action = "say what the row is: a part to buy (give its code) or nothing to cost"
        elif role == "parent_material":
            issue = (f"{pn}'s parts list carries a row that names a material, '{desc}', with no "
                     f"code — it was not made a purchased line")
            action = ("confirm it is the part's own stock (already costed on the part), or a "
                      "separate item to buy (give it a code)")
        elif role == "parent_cut_list":
            issue = (f"{pn}'s parts list carries a section row, '{desc}', that no cut-list "
                     f"reading took (no length, or a section the part does not carry)")
            action = ("confirm the part's section and cut length, or give the row a code if it "
                      "is a bought cut piece")
        else:
            issue = (f"{pn}'s parts list carries an edging row, '{desc}', that was not read as "
                     f"its banding")
            action = "confirm whether the part is banded and the length, or give the row a code"
        if sp.raise_manufacturing_question(part, issue, "nothing is costed for this row",
                                           action, "bom_pipeline.raise_unread_parts_list_rows"):
            n += 1
        r["consumed"] = "question"
    return n


def apply_bom_row_evidence_to_parts(parts: Any, bom_rows: Any) -> int:
    """The BOM table's own MATERIAL / thickness / mass cells become part evidence,
    through source_precedence, before costing.

    0359342 measured the gap exactly: every part record carried an UNSOURCED 6.0 mm
    (a document figure stamped with no provenance) and normalized_material None,
    while the authoritative BOM rows held each component's own printed truth —
    'MDF,18mm' with 4.28 kg on JAE820, 'Steel,Mild2mm' on MBY439, 15 mm on J13149.
    Three populations, one fact, and the population costing reads was the one that
    knew nothing.

    A table reading is bom_tree evidence (rank 60): it REPLACES an unsourced or
    weaker figure and records what it displaced, and it is REFUSED — with the
    disagreement flagged — by a measured DXF, the model, or a deterministic
    title-block read. That asymmetry is the whole design: on a structured pack the
    strong sources stand and gain corroboration; on a PDF-primary pack the printed
    row retires the blanket. Returns how many parts gained at least one datum."""
    import source_precedence as sp
    from part_code_conventions import bare_code

    rows_by: Dict[str, Dict[str, Any]] = {}
    for r in bom_rows or []:
        if not isinstance(r, dict):
            continue
        if not (r.get("material_text") or r.get("thickness_mm") is not None
                or r.get("stated_weight_kg") is not None):
            continue
        _k = bare_code(str(r.get("part_number") or ""))
        if _k:
            rows_by.setdefault(_k, r)
    if not rows_by:
        return 0
    n = 0
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        row = rows_by.get(bare_code(str(p.get("part_number") or "")))
        if not row:
            continue
        changed = False
        if row.get("thickness_mm") is not None:
            changed |= sp.apply_field(p, "normalized_thickness_mm",
                                      float(row["thickness_mm"]), "bom_tree")
        if row.get("material_text"):
            changed |= sp.apply_field(p, "normalized_material",
                                      str(row["material_text"]), "bom_tree")
        if row.get("stated_weight_kg") is not None:
            changed |= sp.apply_field(p, "stated_weight_kg",
                                      float(row["stated_weight_kg"]), "bom_tree")
        n += 1 if changed else 0

    # ── A FIGURE REPEATED ACROSS THE POPULATION IS A DOCUMENT NOTE, NOT A RANK ──────
    # 0359342: one deterministic read of '6mm' was stamped onto 24 parts as
    # drawing_deterministic (rank 70), so every part's OWN printed gauge — 18, 15, 12,
    # 9, 2 — was correctly refused at rank 60 and the blanket priced the job. The rank
    # was never earned: drawing_deterministic means THIS PART's title block, and the
    # same value landing identically on the whole population while their own rows
    # disagree is the signature of a document-level note. On 7332 this class
    # self-corrects (each part's DXF gauge outranks the repeated 1.2), and these
    # thresholds make that shape untriggerable: at least FIVE parts carrying the same
    # deterministic value, at least THREE of them contradicted by their own row.
    # Demotion happens only on the contradicted parts; the rest keep the figure, and
    # the existing repeated-gauge decision row still asks the estimator to rule once.
    from collections import Counter as _Counter
    _det = [p for p in parts or []
            if isinstance(p, dict)
            and str(p.get("thickness_source") or "") == "drawing_deterministic"
            and p.get("normalized_thickness_mm") is not None]
    for _v, _count in _Counter(p["normalized_thickness_mm"] for p in _det).items():
        if _count < 5:
            continue
        _contradicted = []
        for p in _det:
            if p["normalized_thickness_mm"] != _v:
                continue
            for _e in (p.get("_displaced") or {}).get("normalized_thickness_mm", []):
                if (str(_e.get("source")) == "bom_tree" and not _e.get("applied")
                        and _e.get("value") not in (None, _v)):
                    _contradicted.append((p, float(_e["value"])))
                    break
        if len(_contradicted) < 3:
            continue
        for p, _row_v in _contradicted:
            _log = p.setdefault("_displaced", {}).setdefault(
                "normalized_thickness_mm", [])
            _log.append({"value": _v, "source": "drawing_deterministic",
                         "applied": False,
                         "displaced_by": "bom_tree (document-repeated figure)"})
            # precedence: direct-write ok — this IS the arbitration correcting itself:
            # the displaced figure's drawing_deterministic rank was never earned (one
            # document-level read repeated across the population), so apply_field would
            # refuse the honest value on a counterfeit rank; the demotion is recorded
            # in _displaced and flagged on the part above.
            p["normalized_thickness_mm"] = _row_v  # precedence: direct-write ok — the displaced rank was counterfeit (document figure repeated across the population); apply_field would defend it
            p["thickness_source"] = "bom_tree"  # precedence: direct-write ok — provenance moves with the value it belongs to
            p.setdefault("review_flags", []).append(
                f"thickness {_row_v:g} mm taken from this part's own BOM row: the "
                f"{_v:g} mm it displaced is one document figure repeated across "
                f"{_count} parts, not this part's own title block — confirm once "
                f"with the repeated-gauge decision")
        print(f"   [bom-evidence] {_v:g} mm is one document figure repeated across "
              f"{_count} part(s); {len(_contradicted)} of them state their own gauge "
              f"on their BOM row and are priced on it", flush=True)
    return n
