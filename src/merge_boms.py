#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
merge_boms.py — DUAL-PATH BOM RECONCILIATION (the architecture, standalone).

Runs BOTH BOM readers on a job and reconciles them into ONE BOM with provenance
+ drawing-quality findings, per the locked rules:

  PATH A (deterministic, _bom_words_reader.read_bom_from_page): the BASE.
  PATH B (Grok vision, _bom_vision_reader, cached): the COVERAGE net.

  Reconciliation, per (parent, item):
    both agree (code + qty)     -> A's row,  source=BOTH,        conf=HIGH, no flag
    both differ (code or qty)   -> B's row,  source=B_OVERRIDE,  conf=LOW,  flag: override
                                    + "possible drawing inconsistency" (Grok wins, your Q1)
    A only (Grok didn't find)   -> A's row,  source=A_ONLY,      conf=MED,  flag: A-only
    B only (A didn't find)      -> B's row,  source=B_RECOVERED, conf=MED,  flag: LLM-recovered
    whole parent in one path    -> emit rows, flagged which path

Guarantee: NO SILENT MISS — every item found by either path is emitted; anything
found by only one path, or where the two disagree, is FLAGGED for review. Grok
overlays what A didn't find (your words). The cache means Grok is free on re-runs.

Alignment notes (both readers' real schemas):
  - Rows share item_number / part_ref / description / quantity(int). No translation.
  - Parents are derived DIFFERENTLY: Path A's title-block regex is tuned for the
    12120-01-XXX format, so on 1282 it may yield parent=None. Path B (Grok) reads
    the title-block verbatim ('1282 - GA'). So we group by a normalised parent key,
    and when parents don't line up we JOIN ON (pdf_name, page_index) — both readers
    processed the same physical page, so file+page is a reliable join.

Run (from C:\ClaudeVision\src so both readers + cache import):
  C:\ClaudeVision\.venv\Scripts\python.exe merge_boms.py --pdf-dir "<job folder>"
  flags: --force-llm / --refresh-file <substr> / --no-cache / --dpi / --max-side / --model
"""
from __future__ import annotations
import argparse
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

# This module started life as a standalone script and exited the process when a
# reader would not import. It is now imported by the live pipeline, where that
# call would take the whole estimate down over a missing optional dependency —
# so an import failure is recorded and reported instead. main() still refuses to
# run without both readers; the difference is that only main() may end the process.
PATH_A_IMPORT_ERROR: Optional[str] = None
PATH_B_IMPORT_ERROR: Optional[str] = None

# ---- import Path A (deterministic reader) ----
try:
    import _bom_words_reader as pathA
except Exception as exc:  # pragma: no cover - environment-dependent
    pathA = None  # type: ignore[assignment]
    PATH_A_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# ---- import Path B (vision reader + cache) ----
try:
    import _bom_vision_reader as pathB
except Exception as exc:  # pragma: no cover - environment-dependent
    pathB = None  # type: ignore[assignment]
    PATH_B_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Shared normalisation (bare code = uppercase, all separators stripped), reused
# from Path B so A and B codes compare identically.
# ---------------------------------------------------------------------------
# '3886-GA-' / '1450 - GA' / '1455-C GA' -> '3886GA' / '1450GA' / '1455CGA'.
# Taken from part_code_conventions, not from Path B: reconciliation must still be able to
# compare codes on a machine where the vision reader will not import.
from part_code_conventions import bare_code as _bare

# WHAT READ EACH PATH, in the vocabulary precedence arbitrates with. Path A reads a parts
# table off the PDF's own text layer, which is what `bom_tree` means; Path B transcribes a
# rendered image, which is `llm_extract` and ranks below it. Naming them any other way
# would let a vision reading displace a deterministic one on rank alone.
PATH_A_SOURCE = "bom_tree"
PATH_B_SOURCE = "llm_extract"

try:
    from record_merge import merge_records as _merge_records
except Exception:                                                  # pragma: no cover
    def _merge_records(winner, loser, **_kw):                       # type: ignore[misc]
        return []


def _parent_key(parent: Optional[str], pdf_name: str, page_index: int) -> str:
    """Group key for aligning A and B. Prefer a normalised parent code; if absent
    (Path A can yield None on 1282), fall back to the physical page identity so the
    two readers' views of the SAME page still align."""
    if parent and _bare(parent):
        return "P:" + _bare(parent)
    return f"F:{pdf_name}#{page_index}"


# A page can be keyed by parent OR by file+page. To be robust we index B by BOTH
# so A can find B's rows whichever key A ends up with.
def _index_by_keys(boms: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for bom in boms:
        pkey = _parent_key(bom.get("parent"), bom.get("pdf_name", ""), bom.get("page_index", -1))
        fkey = f"F:{bom.get('pdf_name','')}#{bom.get('page_index',-1)}"
        idx[pkey] = bom
        idx[fkey] = bom  # also reachable by file+page
    return idx


def _rows_by_item(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(r["item_number"]): r for r in rows}


def reconcile_page(a_bom: Optional[Dict[str, Any]], b_bom: Optional[Dict[str, Any]],
                   parent_label: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Reconcile one parent's A-rows and B-rows. Returns (merged_rows, findings)."""
    findings: List[str] = []
    a_rows = (a_bom or {}).get("rows", [])
    b_rows = (b_bom or {}).get("rows", [])
    a_by = _rows_by_item(a_rows)
    b_by = _rows_by_item(b_rows)
    all_items = sorted(set(a_by) | set(b_by), key=lambda s: (len(s), s))

    merged: List[Dict[str, Any]] = []
    for item in all_items:
        a = a_by.get(item)
        b = b_by.get(item)

        if a and b:
            a_code, b_code = _bare(a.get("part_ref", "")), _bare(b.get("part_ref", ""))
            a_qty, b_qty = int(a["quantity"]), int(b["quantity"])
            code_agree = (a_code == b_code) or (a_code == "" and b_code == "") \
                or (a_code and b_code and (a_code in b_code or b_code in a_code))
            qty_agree = (a_qty == b_qty)
            # THE ROW CONTEST SETTLES THE CODE AND THE QUANTITY. It does not settle the
            # rest of the line, and taking the winner wholesale threw away every column
            # the loser read and the winner did not — a description vision transcribed
            # off a page whose text layer clipped it arrived, agreed, and was discarded
            # unflagged, because nothing about it disagreed. The two fields the rule
            # below arbitrates stay arbitrated by it; every other field is merged under
            # precedence, so gaps fill and genuine conflicts are recorded.
            _decided = ("part_ref", "quantity")
            if code_agree and qty_agree:
                row = dict(a); row["source"] = "BOTH"; row["confidence"] = "HIGH"; row["flag"] = ""
                _notes = _merge_records(row, b, winner_source=PATH_A_SOURCE,
                                        loser_source=PATH_B_SOURCE, decided=_decided,
                                        label=f"[{parent_label}] item {item}")
                findings.extend(_notes)
                merged.append(row)
            else:
                # conflict -> Grok wins (your Q1), flag override + drawing-inconsistency
                row = dict(b)
                _notes = _merge_records(row, a, winner_source=PATH_B_SOURCE,
                                        loser_source=PATH_A_SOURCE, decided=_decided,
                                        label=f"[{parent_label}] item {item}")
                findings.extend(_notes)
                row["source"] = "B_OVERRIDE"; row["confidence"] = "LOW"
                diff = []
                if not code_agree:
                    diff.append(f"code A='{a.get('part_ref','')}' vs B='{b.get('part_ref','')}'")
                if not qty_agree:
                    diff.append(f"qty A={a_qty} vs B={b_qty}")
                row["flag"] = "OVERRIDE (vision wins) — possible drawing inconsistency: " + "; ".join(diff)
                merged.append(row)
                findings.append(f"[{parent_label}] item {item}: {row['flag']}")
        elif a and not b:
            row = dict(a); row["source"] = "A_ONLY"; row["confidence"] = "MED"
            row["flag"] = "A-only (vision did not corroborate) — review"
            merged.append(row)
            findings.append(f"[{parent_label}] item {item}: found by deterministic reader only "
                            f"(code '{a.get('part_ref','')}', qty {a['quantity']}) — vision missed it")
        elif b and not a:
            row = dict(b); row["source"] = "B_RECOVERED"; row["confidence"] = "MED"
            row["flag"] = "LLM-recovered (deterministic reader missed it) — review"
            merged.append(row)
            findings.append(f"[{parent_label}] item {item}: RECOVERED by vision "
                            f"(code '{b.get('part_ref','')}', qty {b['quantity']}) — deterministic reader missed it")
    return merged, findings


# ---------------------------------------------------------------------------
# Drawing-quality signals from the codes themselves (format inconsistencies),
# independent of A-vs-B. Captured now for the future report section.
# ---------------------------------------------------------------------------
def code_quality_findings(parent_label: str, rows: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    codes = [r.get("part_ref", "") for r in rows if r.get("part_ref")]
    for c in codes:
        if re.search(r"\s-\s|\s-|-\s", c):
            out.append(f"[{parent_label}] code '{c}': stray space around hyphen")
        if c.endswith("-"):
            out.append(f"[{parent_label}] code '{c}': trailing hyphen")
    # inconsistent trailing-hyphen within one table (some have it, some don't)
    fam: Dict[str, List[str]] = {}
    for c in codes:
        stem = re.sub(r"[-\s]+$", "", c)
        stem = re.sub(r"-\d+-?$", "", stem)  # rough family stem (e.g. 3886)
        m = re.match(r"^(\d{3,})", c)
        if m:
            fam.setdefault(m.group(1), []).append(c)
    for stem, members in fam.items():
        has_tr = [c for c in members if c.endswith("-")]
        no_tr = [c for c in members if not c.endswith("-")]
        if has_tr and no_tr:
            out.append(f"[{parent_label}] family {stem}: INCONSISTENT trailing hyphens "
                       f"(e.g. {no_tr[0]} vs {has_tr[0]}) — standardise")
    return out


# ---------------------------------------------------------------------------
# Run both readers over a job.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Which pages are worth paying to look at.
# ---------------------------------------------------------------------------
# A vision call is charged mostly on image size, so the expensive pattern is every page
# of every pack on every run. The cheap pattern is the one that is actually wanted: the
# pages that carry a bill of materials, and the pages that look like they should carry
# one but came back empty.
#
# Two pages therefore earn a call:
#
#   the deterministic reader FOUND a table here   -> corroborate it. This is where the
#       money is, and a row only one reader saw is the whole reason to read twice.
#   the page TALKS like a parts list and the deterministic reader found nothing ->
#       this is the coverage gap. A whole parent BOM absent from a job lives here, and
#       it is invisible in the output because what is wrong with it is what is not in it.
#
# Everything else — detail sheets, sections, revision pages — is read from cache if it
# happens to be there and otherwise not read at all. Skipping is recorded, not silent:
# a page nobody looked at is not a page with no BOM on it.
def merge_pages_into_parents(pages: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Gather every page's rows under the drawing that owns them.

    A parts list is not confined to the GA. It continues onto a second sheet, it is
    repeated as a fixings table on a detail, and a sub-assembly states its own on the
    page that details it. Reading page by page and stopping there gives one BOM per
    SHEET, so a parent whose list spans two sheets arrives as two half-BOMs and a
    fixings table repeated for the fitter's convenience arrives as double the fixings.

    WHAT MAKES TWO ROWS ONE LINE. Within a single parent's bill of materials the item
    number is unique — that is what an item number is for. So:

        same parent, same item, same code      one line, seen on two sheets
        same parent, different item            two lines (a continuation sheet)
        same parent, same item, DIFFERENT code the sheets disagree; both are emitted
                                               and flagged, because dropping either
                                               loses a real part to tidy up a conflict

    Rows under DIFFERENT parents are never folded together. One code legitimately
    appears in several assemblies, and collapsing those is how a part used twice
    becomes a part used once — the global part-number deduplication this system has
    already been bitten by.
    """
    by_parent: Dict[str, Dict[str, Any]] = {}
    findings: List[str] = []
    for pg in pages:
        label = pg.get("label") or ""
        key = _bare(label) or label
        entry = by_parent.setdefault(key, {
            "label": label, "parent_known": bool(pg.get("parent_known")),
            "sheets": [], "rows": [], "_by_item": {},
        })
        if pg.get("parent_known") and not entry["parent_known"]:
            # A page that knows its drawing names the group; a page-identity placeholder
            # never overrides a real title block.
            entry["label"] = label
            entry["parent_known"] = True
        _sheet = pg.get("sheet") or label
        if _sheet not in entry["sheets"]:
            entry["sheets"].append(_sheet)
        for row in pg.get("rows", []):
            item = str(row.get("item_number") or "").strip()
            code = _bare(row.get("part_number") or row.get("part_ref") or "")
            if not item:
                entry["rows"].append(dict(row, sheet=_sheet))
                continue
            prior = entry["_by_item"].get(item)
            if prior is None:
                _r = dict(row, sheet=_sheet)
                entry["_by_item"][item] = _r
                entry["rows"].append(_r)
                continue
            prior_code = _bare(prior.get("part_number") or prior.get("part_ref") or "")
            if prior_code == code:
                # The same line on a second sheet. Record where it was seen; do not
                # count it twice — and READ IT. Noting the sheet and nothing else meant
                # a column the first sheet clipped and the second sheet printed in full
                # was never taken, on a row we had positively identified as the same
                # line. Both readings come off a parts table, so they rank equally:
                # the second fills what the first left blank and can displace nothing.
                _seen = prior.setdefault("also_on_sheets", [])
                if _sheet not in _seen and _sheet != prior.get("sheet"):
                    _seen.append(_sheet)
                findings.extend(_merge_records(
                    prior, row, winner_source=PATH_A_SOURCE, loser_source=PATH_A_SOURCE,
                    decided=("item_number",),
                    label=f"[{entry['label']}] item {item} on {_sheet}"))
                continue
            _r = dict(row, sheet=_sheet)
            _r["flag"] = ((_r.get("flag") or "") + "; " if _r.get("flag") else "") + (
                f"item {item} is '{prior.get('part_ref') or prior_code}' on "
                f"{prior.get('sheet')} and '{row.get('part_ref') or code}' on {_sheet} — "
                f"the sheets disagree; both are costed until someone says which is right")
            entry["rows"].append(_r)
            findings.append(f"[{entry['label']}] {_r['flag']}")

    out = []
    for entry in by_parent.values():
        entry.pop("_by_item", None)
        if len(entry["sheets"]) > 1:
            findings.append(f"[{entry['label']}] parts list read from {len(entry['sheets'])} "
                            f"sheets: {', '.join(str(s) for s in entry['sheets'])}")
        out.append(entry)
    return out, findings


def page_needs_vision(verdict: Dict[str, Any]) -> Tuple[bool, str]:
    """Decide from what the deterministic reader SAW, not from a guess about the page.

    The first version of this asked whether the page's text contained parts-list words,
    against a word list written here. That was wrong twice over. It kept a private copy
    of a vocabulary the reader already owns — so the two could drift, and only one of
    them would ever be corrected. And more fundamentally it decided whether text
    extraction could be trusted by consulting the text extraction, which is circular on
    precisely the pages that matter.

    The reader's own verdict does not have that problem. It knows the difference between
    a page it read, a page it could not read, and a page with nothing on it.
    """
    if not verdict.get("has_text"):
        return True, "no text layer — a scanned or raster sheet is what vision is for"
    if verdict.get("header_found") and verdict.get("rows_parsed"):
        return True, "a parts list was read here; corroborate the rows that carry cost"
    if verdict.get("header_found"):
        return True, ("a parts-list header was found and no rows parsed under it — "
                      "a table this reader could see and could not read")
    if verdict.get("header_words"):
        return True, ("parts-list column words are on this page but no header row "
                      "qualified — the layout defeated the row clustering")
    return False, "no parts-list structure or vocabulary on this page"


# A page neither reader could look at is a page whose BOM cannot be missing-or-present:
# it is simply unknown, and that is the one state this module must never report as clean.
# Both runners therefore append to `unread`, and reconcile_job carries those out to the
# caller as findings. Prints alone were how a whole job ran vision-blind in silence.
def run_path_a(pdf_paths: List[str], unread: Optional[List[Dict[str, Any]]] = None,
               survey: Optional[Dict[Tuple[str, int], bool]] = None) -> List[Dict[str, Any]]:
    """Read every page deterministically, and — since the page is already open — note
    whether it talks like a parts list, into `survey` keyed by (pdf_name, page_index).
    That survey is what lets Path B spend only where a BOM plausibly is."""
    import pdfplumber
    out: List[Dict[str, Any]] = []
    if pathA is None:
        if unread is not None:
            unread.append({"path": "A", "scope": "job", "pdf": "", "page": None,
                           "detail": f"deterministic BOM reader unavailable ({PATH_A_IMPORT_ERROR})"})
        return out
    for p in pdf_paths:
        try:
            with pdfplumber.open(p) as pdf:
                for pi, page in enumerate(pdf.pages):
                    if survey is not None:
                        try:
                            _v = pathA.survey_page(page)
                        except Exception:
                            # A page this reader cannot even survey is exactly a page
                            # vision should see. Unknown is not "no".
                            _v = {"has_text": False}
                        survey[(os.path.basename(p), pi)] = page_needs_vision(_v)
                    bom = pathA.read_bom_from_page(page)
                    if bom:
                        bom["page_index"] = pi
                        bom["pdf_name"] = os.path.basename(p)
                        out.append(bom)
        except Exception as exc:
            print(f"  [Path A skip] {os.path.basename(p)}: {exc}")
            if unread is not None:
                unread.append({"path": "A", "scope": "file", "pdf": os.path.basename(p), "page": None,
                               "detail": f"{type(exc).__name__}: {exc}"})
    return out


def run_path_b(pdf_paths: List[str], args, unread: Optional[List[Dict[str, Any]]] = None,
               worth_paying_for: Optional[Dict[Tuple[str, int], bool]] = None,
               spend: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Read pages with the vision model. `worth_paying_for` maps (pdf_name, page_index)
    to whether this page earns a paid call; a page not in it, or mapped False, is read
    from cache if present and otherwise left unread and recorded. None means the caller
    did not select, and every page is paid for — the standalone tool's behaviour."""
    out: List[Dict[str, Any]] = []
    if pathB is None:
        if unread is not None:
            unread.append({"path": "B", "scope": "job", "pdf": "", "page": None,
                           "detail": f"vision BOM reader unavailable ({PATH_B_IMPORT_ERROR})"})
        return out
    force_all = args.refresh or args.force_llm

    # ── EVERY PAGE AT ONCE, BECAUSE EVERY PAGE IS A SEPARATE ROUND TRIP ──────────────
    #
    # This read the pages one at a time. On 10575-02 that was NINETEEN sequential calls
    # to the vision model, each one a network round trip of several seconds, and it is
    # the largest single block in a run -- the estimator watching it has no way to tell
    # a slow model from a stuck one.
    #
    # Nothing made it sequential. Each page is independent, the cache is keyed per page,
    # and the results are collected rather than accumulated into shared state. The work
    # is entirely WAITING on an API, so threads are the right tool: the GIL is released
    # for the whole of it, and processes would pay to pickle a PNG per page.
    #
    # ORDER IS PRESERVED DELIBERATELY. Results used to arrive in page order and something
    # downstream may lean on that without saying so; a reordering that only shows up on a
    # pack with two GAs is not a debugging session anybody wants. So the work is indexed
    # and the output rebuilt in the original sequence.
    #
    # SDI_VISION_WORKERS bounds it. Default 6: enough to turn minutes into tens of
    # seconds, low enough not to trip a rate limit on the shared xAI key and turn a slow
    # run into a failed one. 1 restores exactly the old behaviour, which is the first
    # thing to try if the model starts refusing.
    try:
        _workers = int(os.environ.get("SDI_VISION_WORKERS", "6"))
    except ValueError:
        _workers = 6
    _workers = max(1, min(_workers, 16))

    jobs: List[Tuple[str, str, int, bool, bool]] = []
    for p in pdf_paths:
        this_refresh = force_all or (
            args.refresh_file is not None and args.refresh_file.lower() in os.path.basename(p).lower()
        )
        try:
            n = pathB.count_pages(p)
        except Exception as exc:
            print(f"  [Path B skip] {os.path.basename(p)}: {exc}")
            if unread is not None:
                unread.append({"path": "B", "scope": "file", "pdf": os.path.basename(p), "page": None,
                               "detail": f"{type(exc).__name__}: {exc}"})
            continue
        for pi in range(n):
            _name = os.path.basename(p)
            _pay = force_all or worth_paying_for is None or worth_paying_for.get((_name, pi), False)
            jobs.append((p, _name, pi, _pay, this_refresh))

    def _one(job: Tuple[str, str, int, bool, bool]) -> Dict[str, Any]:
        p, _name, pi, _pay, this_refresh = job
        try:
            png = pathB.render_page_to_png(p, pi, dpi=args.dpi, max_side=args.max_side)
            res = pathB.get_vision_bom_cached(
                png, model=args.model, pdf_name=_name, page_index=pi,
                cache_dir=args.cache_dir, use_cache=not args.no_cache, refresh=this_refresh,
                cache_only=not _pay,
            )
            return {"name": _name, "page": pi, "res": res}
        except Exception as exc:                                 # noqa: BLE001
            # RETURNED, NOT RAISED. One page the model refuses must not take the other
            # eighteen with it -- the sequential version continued, and so does this.
            return {"name": _name, "page": pi, "error": f"{type(exc).__name__}: {exc}"}

    results: List[Optional[Dict[str, Any]]] = [None] * len(jobs)
    if jobs:
        import concurrent.futures as _futures                    # noqa: PLC0415
        with _futures.ThreadPoolExecutor(max_workers=_workers) as ex:
            for idx, out_one in zip(range(len(jobs)), ex.map(_one, jobs)):
                results[idx] = out_one

    # The bookkeeping stays on ONE thread, in page order. Counters incremented from six
    # threads is how a "paid" total quietly stops matching the bill.
    for entry in results:
        if entry is None:
            continue
        _name, pi = entry["name"], entry["page"]
        if "error" in entry:
            print(f"  [Path B error] {_name} p{pi}: {entry['error']}")
            if unread is not None:
                unread.append({"path": "B", "scope": "page", "pdf": _name, "page": pi,
                               "detail": entry["error"]})
            continue
        res = entry["res"]
        if spend is not None:
            if res.get("skipped"):
                spend["skipped"] = spend.get("skipped", 0) + 1
            elif res.get("cache_hit"):
                spend["cached"] = spend.get("cached", 0) + 1
            else:
                spend["paid"] = spend.get("paid", 0) + 1
        if res.get("skipped"):
            # Not an error and not an empty page — a page nobody looked at. Recorded
            # so "no BOM here" is never inferred from a call that was never made.
            if unread is not None:
                unread.append({"path": "B", "scope": "page", "pdf": _name, "page": pi,
                               "detail": "not read by the vision model: the page does not "
                                         "talk like a parts list and the deterministic "
                                         "reader found no table on it",
                               "reason": "not_selected"})
            continue
        parsed = res["parsed"]
        if parsed and parsed.get("rows"):
            parsed["page_index"] = pi
            parsed["pdf_name"] = _name
            out.append(parsed)
    return out


def find_pdfs(pdf_dir: str) -> List[str]:
    if pathB is not None:
        return pathB.find_pdfs(pdf_dir)  # reuse the deduped finder
    # Same contract as the deduped finder: case-insensitive, one entry per real file.
    # Finding the job's PDFs must not depend on the vision reader importing.
    seen: Dict[str, str] = {}
    for name in sorted(os.listdir(pdf_dir)):
        if name.lower().endswith(".pdf"):
            seen.setdefault(name.lower(), os.path.join(pdf_dir, name))
    return list(seen.values())


def reconcile_job(
    pdf_paths,
    *,
    dpi=300,
    max_side=2000,
    model=None,
    cache_dir=None,
    no_cache=False,
    refresh=False,
    force_llm=False,
    refresh_file=None,
    verbose=False,
    select_pages=True,
    llm_only=None,
):
    """Dual-path BOM reconcile for a set of PDFs (library entry point).

    Runs Path A (deterministic) + Path B (Grok vision, cached) exactly as main() did,
    pairs pages by file+page, reconciles each, and returns structured results:
        {'pages': [{'label','a_bom','b_bom','rows','findings'}, ...],
         'findings': [...], 'counts': {'both','recovered','override','a_only'},
         'pdf_paths': [...], 'a_count': int, 'b_count': int}
    No Grok logic lives here -- it delegates to run_path_a / run_path_b, so behaviour
    is identical to the previous inline main() (verified: standalone output unchanged).
    """
    if model is None:
        model = os.environ.get("XAI_VISION_MODEL", "grok-4.3")
    if cache_dir is None:
        cache_dir = pathB.DEFAULT_CACHE_DIR if pathB is not None else ""
    _args = argparse.Namespace(
        pdf=None, pdf_dir=None, dpi=dpi, max_side=max_side, model=model,
        cache_dir=cache_dir, no_cache=no_cache, refresh=refresh,
        force_llm=force_llm, refresh_file=refresh_file,
    )
    unread: List[Dict[str, Any]] = []
    survey: Dict[Tuple[str, int], bool] = {}
    # DEFAULTED FROM THE ENVIRONMENT so the flag does not have to be threaded through
    # file_scan's signature and bom_pipeline's **opts to reach here. SDI_SW_FLATTEN and
    # SDI_SW_EXTRACT already work this way, and main.py --llm-only sets it for the process.
    # An explicit argument still wins, so a caller that knows what it wants is not
    # second-guessed by a variable somebody left set in a shell.
    if llm_only is None:
        llm_only = os.environ.get("SDI_LLM_ONLY", "").strip().lower() in {"1", "true", "yes"}

    spend: Dict[str, int] = {"paid": 0, "cached": 0, "skipped": 0}

    # ── llm_only: THE MODEL ON ITS OWN, WITH NOTHING TO CORROBORATE IT ──────────────
    #
    # Path A is the deterministic reader and the auditable base; Path B is the coverage
    # net. The whole design is that they check each other, and reconcile_page records
    # which of them saw a row. Turning A off deliberately breaks that — every row becomes
    # B_ONLY and nothing disputes it.
    #
    # WHICH IS THE POINT, and only for measuring. "What does Grok make of this pack by
    # itself" cannot be answered while a deterministic reader is quietly supplying half
    # the rows and correcting the other half. It is a diagnostic, never a way to estimate:
    # an LLM-only read is exactly the thing this engine's source waterfall exists to rank
    # LAST, at confidence 0.68 and capped.
    #
    # The survey is still built, because page selection reads it — and with A off, every
    # page it would have skipped now has no other reader, so all of them are paid for.
    if llm_only:
        a_boms: List[Dict[str, Any]] = []
        if unread is not None:
            unread.append({"path": "A", "scope": "job", "pdf": "", "page": None,
                           "detail": "deterministic BOM reader DISABLED by --llm-only: this "
                                     "read is the vision model alone and nothing corroborates "
                                     "it"})
        if verbose:
            print("  Path A SKIPPED (--llm-only): the model is on its own.")
    else:
        if verbose:
            print("\nRunning Path A (deterministic extract_words)...")
        a_boms = run_path_a(pdf_paths, unread, survey)
        if verbose:
            print(f"  Path A found {len(a_boms)} BOM table(s).")

    # A page earns a paid vision call when Path A found a table on it (corroborate the
    # money) or when the page's own words name parts-list columns and Path A found
    # nothing (the coverage gap). `select_pages=False` restores every-page behaviour.
    if llm_only:
        # EVERY PAGE, PAID FOR. Selection exists to spend the model's time only where the
        # deterministic reader left a gap. With A off the whole document is a gap, and a
        # page skipped here would look in the output like a page with no BOM on it.
        worth = None  # type: ignore[assignment]
        why = {}
    elif select_pages:
        worth: Dict[Tuple[str, int], bool] = {k: v[0] for k, v in survey.items()}
        why: Dict[Tuple[str, int], str] = {k: v[1] for k, v in survey.items()}
        # Belt and braces. survey_page already returns True for a page it read a table
        # on, but a page reaching a_boms without a survey entry — a reader that answered
        # one call and not the other — must not lose its corroboration to a missing key.
        for bom in a_boms:
            _k = (bom.get("pdf_name", ""), bom.get("page_index", -1))
            if not worth.get(_k):
                worth[_k] = True
                why[_k] = "a parts list was read here; corroborate the rows that carry cost"
    else:
        worth = None  # type: ignore[assignment]
        why = {}
    if verbose:
        print(f"Running Path B (Grok vision, cached) on "
              f"{sum(1 for v in worth.values() if v) if worth is not None else 'all'} "
              f"selected page(s)...")
        for (pdf_name, pi), sel in sorted((worth or {}).items()):
            print(f"    {'read ' if sel else 'skip '} {pdf_name} p{pi + 1}: {why.get((pdf_name, pi), '')}")
    b_boms = run_path_b(pdf_paths, _args, unread, worth, spend)
    if verbose:
        print(f"  Path B found {len(b_boms)} BOM table(s). "
              f"Vision calls: {spend['paid']} paid, {spend['cached']} from cache, "
              f"{spend['skipped']} pages not selected.")

    b_index = _index_by_keys(b_boms)
    a_index = _index_by_keys(a_boms)
    seen_fp = set()
    pages = []
    counts = {"both": 0, "recovered": 0, "override": 0, "a_only": 0}
    total_findings = []
    for bom in a_boms + b_boms:
        fp = f"{bom.get('pdf_name','')}#{bom.get('page_index',-1)}"
        if fp in seen_fp:
            continue
        seen_fp.add(fp)
        fkey = f"F:{fp}"
        a_bom = a_index.get(fkey)
        b_bom = b_index.get(fkey)
        # A page whose title block named no drawing falls back to its own file+page
        # identity. That groups the page's rows, which is right, but "12392-04-GA.pdf#1"
        # is not a drawing number and nothing downstream may build a hierarchy on it as
        # though it were. Say which it is rather than leaving it to be guessed from the
        # shape of a string.
        _named = (b_bom or {}).get("parent") or (a_bom or {}).get("parent") or ""
        label = _named or fp
        merged, findings = reconcile_page(a_bom, b_bom, label)
        if not merged:
            continue
        page_findings = list(findings) + code_quality_findings(label, merged)
        if not _named:
            page_findings.append(
                f"[{fp}] this sheet's title block names no drawing number, so its "
                f"{len(merged)} BOM row(s) are grouped by the page they were read from "
                f"and cannot be placed under a parent assembly")
        total_findings.extend(page_findings)
        for r in merged:
            s = r["source"]
            if s == "BOTH":
                counts["both"] += 1
            elif s == "B_RECOVERED":
                counts["recovered"] += 1
            elif s == "B_OVERRIDE":
                counts["override"] += 1
            elif s == "A_ONLY":
                counts["a_only"] += 1
        pages.append({"label": label, "a_bom": a_bom, "b_bom": b_bom,
                      "parent_known": bool(_named), "sheet": fp,
                      "rows": merged, "findings": page_findings})
    # A job where one path never ran is not a reconciled job — it is a single-reader read
    # wearing a reconciled job's shape, and every "BOTH ... HIGH confidence" it cannot
    # produce is a corroboration that silently did not happen. Say so out loud.
    if pdf_paths and not any(u.get("path") == "B" and u.get("scope") == "job" for u in unread):
        if not b_boms:
            unread.append({"path": "B", "scope": "job", "pdf": "", "page": None,
                           "detail": "vision reader returned no BOM table on any page of this job"})
    if pdf_paths and pathA is not None and not a_boms:
        unread.append({"path": "A", "scope": "job", "pdf": "", "page": None,
                       "detail": "deterministic reader found no BOM table on any page of this job"})
    # Pages carry one BOM per SHEET. Parents carry one BOM per DRAWING, which is what a
    # bill of materials is: a continuation sheet finishes a list rather than starting a
    # second one, and a fixings table repeated on a detail is the same fixings.
    parents, parent_findings = merge_pages_into_parents(pages)
    total_findings.extend(parent_findings)
    return {
        "pages": pages, "parents": parents,
        "findings": total_findings, "counts": counts,
        "pdf_paths": list(pdf_paths), "a_count": len(a_boms), "b_count": len(b_boms),
        "unread": unread, "vision_calls": dict(spend),
    }


def main():
    # Only the command line may end the process. Run standalone, this tool exists to
    # compare two readers, so one missing reader makes it pointless and it should say so
    # loudly. Imported, the same condition is a degraded read the caller must be told
    # about — never a reason to take an estimate down.
    for _label, _mod, _err in (("A (_bom_words_reader)", pathA, PATH_A_IMPORT_ERROR),
                               ("B (_bom_vision_reader)", pathB, PATH_B_IMPORT_ERROR)):
        if _mod is None:
            print(f"Could not import Path {_label}: {_err}")
            print("Run this from the src/ directory, with the project's virtualenv active.")
            sys.exit(1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", default=None)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--max-side", type=int, default=2000)
    ap.add_argument("--model", default=os.environ.get("XAI_VISION_MODEL", "grok-4.3"))
    ap.add_argument("--cache-dir", default=pathB.DEFAULT_CACHE_DIR)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--force-llm", action="store_true")
    ap.add_argument("--refresh-file", default=None)
    args = ap.parse_args()
    if args.pdf:
        pdf_paths = [args.pdf]
    elif args.pdf_dir:
        pdf_paths = find_pdfs(args.pdf_dir)
    else:
        print("Provide --pdf-dir or --pdf."); sys.exit(1)
    if not pdf_paths:
        print("No PDFs found."); sys.exit(1)
    print("=" * 82)
    print("DUAL-PATH BOM RECONCILIATION  (Path A deterministic + Path B vision)")
    print(f"Files: {len(pdf_paths)}   Model: {args.model}   DPI: {args.dpi}")
    print("=" * 82)
    result = reconcile_job(
        pdf_paths, dpi=args.dpi, max_side=args.max_side, model=args.model,
        cache_dir=args.cache_dir, no_cache=args.no_cache, refresh=args.refresh,
        force_llm=args.force_llm, refresh_file=args.refresh_file, verbose=True,
    )
    for pg in result["pages"]:
        label = pg["label"]; a_bom = pg["a_bom"]; b_bom = pg["b_bom"]; merged = pg["rows"]
        a_n = len((a_bom or {}).get("rows", []))
        b_n = len((b_bom or {}).get("rows", []))
        print("\n" + "#" * 82)
        print(f"PARENT: {label}    (Path A: {a_n} rows, Path B: {b_n} rows -> merged: {len(merged)})")
        print("#" * 82)
        for r in merged:
            src = r["source"]; conf = r["confidence"]
            code = r.get("part_number") or r.get("part_ref") or ""
            tag = {"BOTH": "", "B_RECOVERED": "  <= RECOVERED by vision",
                   "B_OVERRIDE": "  <= VISION OVERRIDE", "A_ONLY": "  <= A-only"}.get(src, "")
            print(f"  item {str(r['item_number']):>2} | {code:<16} | {r.get('description','')[:36]:<36} "
                  f"| qty {r['quantity']} | {src:<11} {conf}{tag}")
    print("\n" + "=" * 82)
    print("RECONCILIATION SUMMARY")
    print("=" * 82)
    c = result["counts"]
    print(f"  BOTH agree (high confidence):     {c['both']}")
    print(f"  RECOVERED by vision (A missed):   {c['recovered']}   <- coverage vision adds")
    print(f"  VISION OVERRIDE (conflict):       {c['override']}   <- Grok won, flagged")
    print(f"  A-only (vision missed):           {c['a_only']}")
    print()
    if result["findings"]:
        print("DRAWING-QUALITY & REVIEW FINDINGS (for the emailed report):")
        for f in result["findings"]:
            print(f"  - {f}")
    else:
        print("No review findings -- both paths agreed on everything, codes clean.")
    print("=" * 82)


if __name__ == "__main__":
    main()
