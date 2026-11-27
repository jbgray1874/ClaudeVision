r"""
replay_bought_in_gate.py — would the prices this book refused reach the total NOW, and would
every table row get a record NOW, replayed against the saved JSON instead of a 74-minute run.

WHY THIS EXISTS. 12567-01-GA's 13:14 book (163 off) carried eleven bought-in lines at £0 with
a price found for every one of them. Each settle note read:

    NOT YET PRICED — but <source> gives £X each. NOT APPLIED: the engine did not classify
    this part as a bought-in, so the engine will not total it.

MAGNET21 had a UDEF row at £0.35, eight P/P lines had market figures, BI-SCREW and BI-PEMSTUD
had been minted with nothing found. The price chain had done its work and a classifier that
never asked the make/buy authority withheld the answer — GUARD 1 refused any part carrying
inferred geometry, which every bought-in row given a fallback envelope does (D-289). On the
same book the two EPDM tape lengths, printed "P/P" and read by the deterministic BOM reader
only, reached the graph as edges with no record behind them and no line on the Estimate: the
reconcile that runs after the writeup minted fasteners and nothing else (D-290).

Both were fixed at estimator._bought_in_candidate_for and file_scan._reconcile_dualpath_into_
part_estimates. Proving a fix on this job means running it again, and this job runs for over
an hour. The saved JSON already holds everything the two gates read: the record each price was
found for, the figure and its source, and the reconciled table rows. So this replays the two
gates over the saved document with the code that is checked out now, and says line by line
what would happen — before anyone spends the hour finding out.

    python tools\diagnose\replay_bought_in_gate.py
    python tools\diagnose\replay_bought_in_gate.py --json output\json\<job>.json
    python tools\diagnose\replay_bought_in_gate.py MAGNET21 --json output\json\<job>.json

READ-ONLY. It opens the JSON, never writes it, touches no network and no database, and exits 0
whatever it finds — it is a diagnostic, and a diagnostic that stops a script is a second fault.
Every engine function it drives is handed a COPY of the record, so nothing here can change the
document under it even by accident.

IT KNOWS NO PART NUMBERS AND NO PRICES. Which lines held a refused figure is asked of
price_provenance.declined_whole_part_price — the same function the settle note and the price
column read, so this tool and the sheet cannot disagree about which prices were declined. The
classification is asked of the estimator's own gate and the make/buy authority's own reason;
the minting is the shared minter itself. Nothing is re-implemented here, so nothing here can
agree with a rule that has since changed.

WHICH RECORD. The costed part_estimate is a PROJECTION: it carries the price stamp and not the
operations, the geometry flags or the printed code the gate reads. estimate_part was handed the
raw record under manufacturing_writeup.parts, so that is what the gate is replayed on; where a
document has no raw record for a line the costed one stands in, with the route's operations
lifted out of route_context, and the output says so.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

# Windows consoles default to cp1252, which cannot encode "→" or "£". main.py forces UTF-8 on
# the console streams for the same reason; a diagnostic that dies on its own arrow has
# answered nothing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                # noqa: BLE001
        pass


# ── the document ─────────────────────────────────────────────────────────────────────────

def _newest_job_json(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)
    import config
    candidates: List[str] = []
    for pattern in ("json/*.json", "estimates/*.json"):
        candidates += glob.glob(str(Path(config.OUTPUT_DIR) / pattern))
    # The LLM extract is a different document with a different shape; it is not the job.
    candidates = [c for c in candidates if "llm_extract" not in os.path.basename(c).lower()]
    if not candidates:
        raise FileNotFoundError(f"No job JSON under {config.OUTPUT_DIR}. Pass --json <path>.")
    return Path(max(candidates, key=os.path.getmtime))


def _parts(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """part_estimates, wherever this document keeps them.

    Some writers stamp the estimate on the root and some inside estimate_summary. A reader
    that looks in one place reports "no such part" on every job of the other shape.
    """
    for holder in (doc.get("estimate_summary"), doc):
        if isinstance(holder, dict):
            pes = holder.get("part_estimates")
            if isinstance(pes, list) and pes:
                return [p for p in pes if isinstance(p, dict)]
    return []


def _code(rec: Any) -> str:
    return str((rec or {}).get("part_number") or "").strip().upper() if isinstance(rec, dict) else ""


def _raw_record_for(doc: Dict[str, Any], code: str) -> Optional[Dict[str, Any]]:
    """The record estimate_part was handed for this code, or None.

    file_scan calls estimate_document(summary["manufacturing_writeup"]["parts"], ...), so the
    writeup's list is asked first and the top-level parts list second, in the order
    estimator's own readers use.
    """
    holders = ((doc.get("manufacturing_writeup") or {}).get("parts")
               if isinstance(doc.get("manufacturing_writeup"), dict) else None,
               doc.get("parts"))
    for holder in holders:
        if isinstance(holder, list):
            for rec in holder:
                if isinstance(rec, dict) and _code(rec) == code:
                    return rec
    return None


def _document_analysis(doc: Dict[str, Any]) -> Dict[str, Any]:
    for holder in (doc, doc.get("estimate_summary")):
        if isinstance(holder, dict) and isinstance(holder.get("document_analysis"), dict):
            return holder["document_analysis"]
    return {}


def _build_lines(doc: Dict[str, Any]) -> List[str]:
    """Which build wrote this document, and which is reading it now.

    "The fix is not live" and "the fix does not work" look identical on a spreadsheet and
    lead opposite ways. The stamp lands at estimate_summary.engine_build, not the root.
    """
    try:
        import engine_build
    except Exception as exc:                                         # noqa: BLE001
        return [f"engine build: could not be asked ({type(exc).__name__}: {exc})"]
    stamped = None
    for holder in (doc, doc.get("estimate_summary")):
        if isinstance(holder, dict) and isinstance(holder.get("engine_build"), dict):
            stamped = holder["engine_build"]
            break
    here = engine_build.describe()
    out: List[str] = []
    if stamped:
        out.append("WROTE this estimate:  " + engine_build.one_line(stamped))
    else:
        out.append("WROTE this estimate:  NOT RECORDED (no build stamp on this document)")
    out.append("REPLAYING with:       " + engine_build.one_line(here))
    if stamped and stamped.get("commit") and stamped["commit"] != here.get("commit"):
        out.append("                      ^ DIFFERENT BUILDS. Every verdict below is the "
                   "checked-out code's, not the book's.")
    return out


# ── (1) the prices the book refused ──────────────────────────────────────────────────────

def _as_estimate_part_saw_it(pe: Dict[str, Any], raw: Optional[Dict[str, Any]]
                             ) -> Tuple[Dict[str, Any], str]:
    """A COPY of the record the gate is replayed on, and which record that was."""
    if raw is not None:
        return copy.deepcopy(raw), "raw record"
    # THE PROJECTION KEEPS THE ROUTE UNDER route_context AND NOWHERE ELSE. estimate_part
    # never copies textual_operations onto the costed record (wb_populate.route_operations_
    # by_part says why), so read from the top the projection has no operations at all and
    # every line would replay as "no ops except handling". Lifted, so the fallback is the
    # closest thing this document holds to what the gate saw.
    part = copy.deepcopy(pe)
    rc = part.get("route_context") if isinstance(part.get("route_context"), dict) else {}
    for key in ("textual_operations", "inferred_operations"):
        if not part.get(key) and isinstance(rc.get(key), list):
            part[key] = list(rc[key])
    return part, ("costed projection — this document holds no raw record for the line, and "
                  "the projection lacks geometry_inferred / is_bought_in / printed_code")


def _gate_inputs(part: Dict[str, Any]) -> Tuple[bool, str]:
    """no_ops_except_handling and desc_blob, exactly as estimate_part derives them.

    These are estimate_part's own lines immediately before it calls _bought_in_candidate_for;
    estimator has no helper for them to import, so they are restated with the same _part_ops.
    If estimate_part changes them this will disagree, and disagreeing loudly beats a stale
    copy that agrees with nothing.
    """
    from estimator import _part_ops
    op_set = {str(op).strip().lower() for op in _part_ops(part) if str(op).strip()}
    no_ops_except_handling = op_set <= {"handling"}
    desc_blob = " ".join(
        [
            str(part.get("description") or ""),
            ";".join(part.get("process_notes") or []),
            ";".join(_part_ops(part) or []),
        ]
    ).upper()
    return no_ops_except_handling, desc_blob


def _source_label(stamp_name: str) -> str:
    import price_provenance as pp
    label = pp.source_system_label(stamp_name)
    return f"{stamp_name} — {label}" if label and label.lower() != stamp_name.lower() else stamp_name


def _facts_the_gate_turns_on(part: Dict[str, Any]) -> str:
    from estimator import _part_ops
    bits = []
    for key in ("geometry_inferred", "flat_pattern_detected", "special_finish_item",
                "is_bought_in", "printed_code", "source", "material_family",
                "normalized_material"):
        if key in part and part.get(key) not in (None, "", [], {}):
            bits.append(f"{key}={part.get(key)!r}")
    roles = part.get("page_roles")
    if roles:
        bits.append(f"page_roles={roles!r}")
    bits.append(f"ops={list(_part_ops(part) or [])!r}")
    return "  ".join(bits)


def _replay_refused_prices(doc: Dict[str, Any], parts: List[Dict[str, Any]],
                           wanted: Optional[set]) -> None:
    import price_provenance as pp
    import bought_in_policy
    import config
    import estimator

    print(f"\n{'=' * 78}\n(1) PRICES FOUND AND NOT TOTALLED — replayed through the gate as it is now"
          f"\n{'=' * 78}")
    cap = getattr(config, "BOUGHT_IN_MAX_PLAUSIBLE_GBP", None)
    held = 0
    would_total = 0
    still_refused: List[str] = []
    for pe in parts:
        code = _code(pe)
        if wanted and code not in wanted:
            continue
        declined = pp.declined_whole_part_price(pe)
        if not declined:
            continue
        held += 1
        gbp = float(declined["gbp"])
        source = _source_label(str(declined.get("source") or "an unnamed lookup"))
        matched = declined.get("matched_code") or ""
        sc = ((pe.get("cost_breakdown") or {}).get("system_cost") or {}) \
            if isinstance(pe.get("cost_breakdown"), dict) else {}
        stamp = sc.get("source") if isinstance(sc.get("source"), dict) else {}
        withheld_why = str((stamp or {}).get("withheld_reason") or "").strip()

        raw = _raw_record_for(doc, code)
        part, which = _as_estimate_part_saw_it(pe, raw)
        try:
            no_ops, blob = _gate_inputs(part)
            cand = bool(estimator._bought_in_candidate_for(part, no_ops, blob))
            gate = f"bought-in candidate = {cand}"
        except Exception as exc:                                     # noqa: BLE001
            cand = False
            gate = f"the gate could not be run ({type(exc).__name__}: {exc})"
        try:
            reason = bought_in_policy.bought_in_reason(copy.deepcopy(part))
        except Exception as exc:                                     # noqa: BLE001
            reason = f"bought_in_reason failed: {type(exc).__name__}: {exc}"
        authority = reason or "no opinion — the authority does not call this a part we buy"

        print(f"\n{code}  £{gbp:.2f} ({source})  was NOT APPLIED  →  now: {gate} "
              f"(bought_in_policy: {authority})")
        print(f"    description   {str(pe.get('description') or part.get('description') or '')[:80]}")
        stamp_bits = []
        if matched:
            stamp_bits.append(f"matched {matched}")
        if withheld_why:
            # D-284: a stamp can read applied_to_total False because the SHEET wrote nothing
            # on a line the engine DID classify bought-in. That is a different fault from the
            # classifier's, and the stamp says which.
            stamp_bits.append(f"withheld_reason: {withheld_why}")
        if stamp_bits:
            print(f"    stamp         {'; '.join(stamp_bits)}")
        print(f"    replayed on   {which}")
        print(f"    turns on      {_facts_the_gate_turns_on(part)}")

        if cand:
            if cap is not None and gbp > float(cap):
                # GUARD 2 runs after the candidate test and is untouched by D-289.
                still_refused.append(code)
                print(f"    verdict       STILL REFUSED on a re-run: £{gbp:.2f} exceeds the "
                      f"plausibility cap (config.BOUGHT_IN_MAX_PLAUSIBLE_GBP = £{float(cap):.2f}); "
                      f"GUARD 2 flags it for a person, as before")
            else:
                would_total += 1
                cap_note = (f" (GUARD 2 cap £{float(cap):.2f} not exceeded)"
                            if cap is not None else "")
                print(f"    verdict       a re-run would TOTAL this figure{cap_note}")
        else:
            still_refused.append(code)
            why = []
            if part.get("geometry_inferred") and not reason:
                why.append("GUARD 1 refuses inferred geometry and the make/buy authority "
                           "has no opinion to overrule it")
            elif not reason:
                why.append("neither the keyword test, the operations test nor the make/buy "
                           "authority calls it bought-in")
            print(f"    verdict       STILL REFUSED on a re-run"
                  + (": " + "; ".join(why) if why else ""))

    if held == 0:
        print("\n  No part_estimate on this document holds a resolved bought-in price that did "
              "not reach the total"
              + (" (among the codes asked for)." if wanted else ".")
              + "\n  Either every found price was applied, or the book was written before "
                "estimator stamped system_cost.applied_to_total.")
    else:
        print(f"\n  {held} held figure(s) the book refused; {would_total} would now reach the "
              f"total; {len(still_refused)} would still be refused"
              + (f": {', '.join(still_refused)}" if still_refused else "."))


# ── (2) the table rows and their records ─────────────────────────────────────────────────

def _row_code(row: Dict[str, Any]) -> str:
    # The spellings the reconcile accepts, in its order.
    return str(row.get("part_code") or row.get("code") or row.get("part_number") or "").strip()


def _row_qty(row: Dict[str, Any]) -> Optional[int]:
    q = row.get("qty") or row.get("quantity") or row.get("qty_per_unit")
    try:
        return int(float(q)) if q is not None else None
    except (TypeError, ValueError):
        return None


def _row_as_the_reconcile_hands_it(row: Dict[str, Any]) -> Dict[str, Any]:
    """The shape _reconcile_dualpath_into_part_estimates gives the minter: the row's code as
    part_number, the printed class word, the words, the quantity, the table that listed it."""
    q = _row_qty(row)
    return {"part_number": _row_code(row),
            "printed_code": row.get("printed_code"),
            "description": str(row.get("description") or ""),
            "quantity": q if q is not None else 1,
            "bom_parent": str(row.get("bom_parent") or row.get("source_pdf") or "")}


def _match_row(row: Dict[str, Any], parts: List[Dict[str, Any]]) -> Optional[str]:
    """How an existing record already stands for this row, or None.

    The three tests the reconcile applies, in its order: the code, the article words (the
    D-290 pass), and the fastener loop's token test against bought-in records.
    """
    from part_identity import _article_words
    code = _row_code(row).upper()
    if code:
        for p in parts:
            if _code(p) == code:
                return f"code match → {_code(p)}"
    words = tuple(_article_words(row.get("description")))
    if words:
        for p in parts:
            if p.get("description") and tuple(_article_words(p.get("description"))) == words:
                return f"article words match → {_code(p)}"
    try:
        from estimator import _bought_in_same_item, _bought_in_token_set
        rtoks = _bought_in_token_set({"description": str(row.get("description") or code)})
        if rtoks is not None:
            for p in parts:
                roles = p.get("page_roles") or []
                if not ("bought_in" in roles or _code(p).startswith("BI-")):
                    continue
                ptoks = _bought_in_token_set(p)
                if ptoks is not None and _bought_in_same_item(rtoks, ptoks):
                    return f"token match (the fastener loop's test) → {_code(p)}"
    except Exception:                                                # noqa: BLE001
        pass
    return None


def _replay_table_rows(doc: Dict[str, Any], parts: List[Dict[str, Any]], verbose: bool) -> None:
    print(f"\n{'=' * 78}\n(2) TABLE ROWS WITH NO RECORD — what the shared minter would give them now"
          f"\n{'=' * 78}")
    da = _document_analysis(doc)
    rows = da.get("bom_rows") if isinstance(da, dict) else None
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    if not rows:
        # THE RECONCILED ROWS LIVE IN ONE PLACE. file_scan writes the dual-path result's rows
        # to document_analysis.bom_rows and keeps no separate copy of the reconcile's input,
        # so a document without them cannot be replayed — say so rather than print an empty
        # list that reads as "every row has a record".
        print("\n  This document carries no BOM table rows (document_analysis.bom_rows is "
              "absent or empty).\n  The dual-path reader's reconciled rows are persisted ONLY "
              "there — file_scan writes them to that key\n  and keeps no other copy — so this "
              "book was written before the dual path ran, or by a run with it off.\n  Nothing "
              "to replay for (2).")
        return

    unread = da.get("bom_readers_unread")
    counts = da.get("bom_reader_counts")
    by_reader: Dict[str, int] = {}
    for r in rows:
        key = str(r.get("bom_source") or "no reader attribution")
        by_reader[key] = by_reader.get(key, 0) + 1
    print(f"\n  {len(rows)} row(s) on document_analysis.bom_rows; by reader: "
          + ", ".join(f"{k} {v}" for k, v in sorted(by_reader.items())))
    if isinstance(counts, dict) and counts:
        print(f"  reader counts as the reconcile recorded them: {counts}")
    if isinstance(unread, list) and unread:
        for u in unread:
            if isinstance(u, dict):
                print(f"  reader {u.get('path')} did not read ({u.get('scope')}): {u.get('detail')}")
    if "bom_source" not in rows[0] and not any("bom_source" in r for r in rows):
        print("  (no row carries bom_source — these rows may be the writeup's page-text fallback, "
              "not the dual-path reconcile)")

    unmatched: List[Tuple[int, Dict[str, Any]]] = []
    for i, row in enumerate(rows):
        how = _match_row(row, parts)
        if how is None:
            unmatched.append((i, row))
        elif verbose:
            print(f"  row {i + 1:>3}  {_row_code(row) or '-':<44} {how}")

    if not unmatched:
        print(f"\n  Every row already has a record (by code, article words or the fastener "
              f"loop's tokens). Nothing for the minter to add.")
        return

    # THE MINTER IS RUN OVER THE WHOLE TABLE, as the reconcile runs it, and only then read for
    # the rows no record stands for. A class-coded row is told apart from its siblings by the
    # rest of the table (part_identity.category_code_identities), so handing it the unmatched
    # rows alone would change the answer on a document whose rows were saved unsplit.
    try:
        from document_builder import bought_in_rows_without_records
        shaped = [_row_as_the_reconcile_hands_it(r) for r in rows]
        minted = bought_in_rows_without_records(shaped, copy.deepcopy(parts))
    except Exception as exc:                                         # noqa: BLE001
        minted = []
        print(f"\n  the minter could not be run ({type(exc).__name__}: {exc})")
    # Back to the rows they came from: the minter names a record after the row's words and,
    # failing those, its code — one record per row, so the pool is drained as rows claim.
    pool = list(minted)

    def _claim(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        desc = str(row.get("description") or "").strip().upper()
        code = _row_code(row).upper()
        for key in ("description", "part_number"):
            for rec in pool:
                if key == "description" and desc and str(rec.get("description") or "").strip().upper() == desc:
                    pool.remove(rec)
                    return rec
                if key == "part_number" and code and _code(rec) == code:
                    pool.remove(rec)
                    return rec
        return None

    print(f"\n  {len(unmatched)} row(s) with NO record by code, article words or tokens:")
    added = 0
    for i, row in unmatched:
        code = _row_code(row) or "-"
        printed = str(row.get("printed_code") or "").strip()
        qty = _row_qty(row)
        reader = str(row.get("bom_source") or "?")
        parent = str(row.get("bom_parent") or row.get("source_pdf") or "?")
        print(f"\n  ROW {i + 1}  {code}" + (f"  (printed {printed})" if printed and printed.upper() != code.upper() else "")
              + f"  x{qty if qty is not None else '?'}  read by {reader}  under {parent}")
        print(f"         \"{str(row.get('description') or '')[:90]}\"")
        rec = _claim(row)
        if rec is None:
            print("         minter now → NOTHING. The minter names no record for this row: a "
                  "class word with no article words, an SDI drawing\n"
                  "         number or GA (those have records of their own or are the "
                  "assembly), or a code/description it refuses as not a part.")
            continue
        added += 1
        print(f"         minter now → {rec.get('part_number')}  qty {rec.get('quantity')}  "
              f"is_bought_in={bool(rec.get('is_bought_in'))}  page_roles={rec.get('page_roles')}"
              f"  source={rec.get('source')}"
              + (f"  printed_code={rec.get('printed_code')}" if rec.get("printed_code") else "")
              + (f"  bom_parent={rec.get('bom_parent')}" if rec.get("bom_parent") else ""))
    print(f"\n  {added} of {len(unmatched)} unmatched row(s) would be given a record by the "
          f"minter on a re-run; the reconcile then costs each added record through "
          f"estimate_part.")
    print("  (A fastener row — screw, nut, stud, rivet, washer — is added by the reconcile's own "
          "fastener loop under a BI- code instead; the minter's answer above is for every other row.)")


# ── main ─────────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("parts", nargs="*", help="part number(s) to limit (1) to, case-insensitive")
    ap.add_argument("--json", help="job JSON (default: the newest under OUTPUT_DIR)")
    ap.add_argument("--verbose", action="store_true",
                    help="also list every table row that already has a record, and how")
    args = ap.parse_args()

    # EXIT 0 ON EVERY PATH. This is read by a person, sometimes from a script that runs the
    # diagnostics in a row; the answer to "the file is not there" is the sentence, not a stop.
    try:
        path = _newest_job_json(args.json)
        print(f"reading {path}")
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                                         # noqa: BLE001
        print(f"could not read a job JSON ({type(exc).__name__}: {exc}). Pass --json <path>.")
        return 0
    if not isinstance(doc, dict):
        print("That document is not a job: its root is not an object.")
        return 0

    for line in _build_lines(doc):
        print(line)

    parts = _parts(doc)
    if not parts:
        print("\nThat document holds no part_estimates, so (1) has nothing to replay.")
    wanted = {p.strip().upper() for p in args.parts if p.strip()} or None
    if parts:
        _replay_refused_prices(doc, parts, wanted)
        if wanted:
            present = {_code(p) for p in parts}
            for missing in sorted(wanted - present):
                print(f"\n{missing}: NOT IN part_estimates ({len(parts)} parts on this job).")
    _replay_table_rows(doc, parts, args.verbose)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
