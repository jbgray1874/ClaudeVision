"""The BOMs and the routes this pack gave us, on their own, with where each one came from.

WHAT THIS IS FOR. The estimate answers "what does it cost". Before anybody can trust that, two
earlier questions have to be answerable on their own: what parts did you find, and what work did
you decide each one needs. Those are in the record, spread across the readers that produced them,
and nobody should have to open a costed workbook to see them.

So this builds a deliverable with exactly two subjects — BOMs and Routes — one sheet each, plus a
third that explains how every column was derived. Same data in a styled page, because estimating
works from the spreadsheet and everyone else reads the page.

EVERY COLUMN SAYS WHERE IT CAME FROM. A parts list read off a drawing by the vision model and one
typed into a SolidWorks BOM are not the same evidence, and a route decision the compiler REQUIRED
is not one it merely considered. Both distinctions are on the face of the sheet, because an
extract that flattens them reads as a single authority and is then quoted as one.

A DEFECT THIS FIXES ON THE WAY. source_drawing_data.operation_rows read the route from
`estimate_summary.canonical_route` only. Every real run writes it to `canonical_route_shadow` —
v0013 of 7332-01 carries 27 decisions there — so the Operations sheet of the extraction audit has
been EMPTY on every real job since it was written, and read as "this pack states no operations".
Both spellings and both nestings are read here, and the audit's reader is corrected to match.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

SHEETS = ("BOMs", "Routes", "How these were derived")

# WHERE A BOM ROW CAME FROM, in words an estimator can weigh. The reader key is whatever the
# pipeline recorded; these are what it means. An unrecognised reader is reported as itself rather
# than mapped to a guess.
READER_MEANING: Dict[str, str] = {
    "bom_table": "a parts-list TABLE on the drawing, read by the table parser — ruled lines and "
                 "columns, so the quantities are as printed",
    "vision": "the drawing read as an IMAGE by the vision model. It sees parts lists a table "
              "parser cannot, and it can misread a character, so it is corroborated where a "
              "second reader saw the same row",
    "llm_extract": "the whole-document model pass. Broad and not line-exact; useful where "
                   "nothing else read the page",
    "solidworks_api": "the SolidWorks model's own BOM, read through the API. The strongest "
                      "source there is: the designer's structure rather than a print of it",
    "bom_tree": "the assembly tree the engine built from the drawing set, not a single page",
    "title_block": "the drawing's title block",
    "dxf_filename": "the DXF filename, which at SDI encodes part, gauge and material",
}

# ── WHAT READ PRODUCED THESE TABLES ───────────────────────────────────────────────────
#
# Three ways to get a BOM and a route out of a pack, and they are NOT interchangeable:
#
#   costed_run   a full estimate ran. The route was projected onto priced rows, so "charged"
#                means money actually passed through the sheet.
#   pack_read    every reader ran and nothing was costed. The route says what it REQUIRES.
#                Nothing is charged, because nothing was priced.
#   fast_read    the vision model alone. No BOM line is corroborated by a second reader.
#
# This exists for the same reason money_provenance does, and it is the same failure it guards
# against: an output that cannot say how it was produced gets quoted as though it were the
# strongest kind. The specific trap here is the "charged" column — on a pack that was never
# costed, "charged: no" against every row would read as "this pack needs no work", which is the
# opposite of the truth. So the column changes its NAME with the source rather than its values.
SOURCE_MEANING: Dict[str, str] = {
    "costed_run": "a full estimate ran on this pack and these tables come from its saved "
                  "record. The route was projected onto the priced rows, so an operation "
                  "marked charged is one the estimate actually charged for",
    "pack_read": "the drawings were read by every reader and NOTHING WAS COSTED. The route "
                 "states what each part REQUIRES; no operation here is charged, because no "
                 "price was calculated at all",
    "fast_read": "the drawings were read by the VISION MODEL ALONE. No parts-list row is "
                 "corroborated by a second reader, and nothing was costed. Useful as a first "
                 "look at what is in a pack; not a basis for quoting",
}

STATUS_MEANING: Dict[str, str] = {
    "required": "the route REQUIRES this operation: it is charged and the part cannot be made "
                "without it",
    "unverified": "the compiler found evidence for it and could not confirm it. NOT charged on "
                  "this basis alone, and a person should rule on it",
    "not_applicable": "ruled out, with a reason — usually physically impossible on this stock "
                      "form, or already covered by another operation",
    "refused": "actively refused by a gate, with a reason",
    "excluded": "removed from this part's scope",
}


def _text(value: Any, limit: int = 400) -> str:
    if value is None:
        return ""
    out = str(value)
    return out if len(out) <= limit else out[: limit - 1] + "…"


def source_declaration(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """Which of the three reads produced this record — DERIVED, never passed in.

    A caller that labels its own output is a caller that can label it wrongly, and the one
    mislabelling that matters here ("this was costed") is the one a hurried caller is most
    likely to reach for. So the record is asked instead, from the marks the pipeline already
    leaves on it: llm_only is stamped by main.py, and money_provenance says whether a workbook
    was ever read back.
    """
    llm_only = bool(summary.get("llm_only")) if isinstance(summary, Mapping) else False
    if not llm_only:
        try:
            from run_readers import run_was_llm_only
            llm_only = bool(run_was_llm_only(dict(summary) if isinstance(summary, Mapping)
                                             else {}))
        except Exception:                                                # noqa: BLE001
            pass

    costed = False
    if isinstance(summary, Mapping):
        try:
            import money_provenance as _mp
            costed = bool(_mp.can_evidence_a_price(summary))
        except Exception:                                                # noqa: BLE001
            costed = False
        if not costed:
            # A RECORD CAN PREDATE money_provenance AND STILL BE COSTED. The totals themselves
            # are the older evidence, and reading them keeps an archived record from being
            # downgraded to "never costed" by the absence of a block that did not exist when it
            # was written.
            _es = summary.get("estimate_summary")
            _fe = (_es or {}).get("final_estimate") if isinstance(_es, Mapping) else None
            if isinstance(_fe, Mapping) and (_fe.get("totals") or _fe.get("labour_rows")):
                costed = True
        if not costed:
            # AND THE EVIDENCE THAT EXISTS EARLIER THAN EITHER. This shipped wrong on 7332-01's
            # 14:17 run: the BOMs & Routes tab said "Nothing here is charged — this pack was not
            # costed" on a pack costed at GBP 80.34 per unit.
            #
            # A TIMING BOUNDARY, not a logic error. wb_populate writes that tab WHILE building
            # the estimate workbook; final_estimate.totals is written back afterwards, once
            # Excel has calculated. So at the moment the tab is written the totals genuinely do
            # not exist yet, and asking for them can only ever answer "no".
            #
            # workbook_labour.rows DOES exist at that moment — the same tab reads it to print
            # the "sheet row" column, and on that run it resolved decisions to rows 96 to 107.
            # A workbook labour row is not a hint that costing may happen: it is a line the
            # workbook charges, carrying its own row number. Its presence is proof.
            _wl = summary.get("workbook_labour")
            if isinstance(_wl, Mapping) and (_wl.get("rows") or []):
                costed = True

    if llm_only:
        source = "fast_read"
    elif costed:
        source = "costed_run"
    else:
        source = "pack_read"
    return {
        "schema": "extract_source.v1",
        "source": source,
        "meaning": SOURCE_MEANING[source],
        # THE ONE BOOLEAN EVERY CONSUMER READS, exactly as money_provenance publishes
        # can_evidence_a_price rather than making each caller re-derive it from three fields.
        "charged_is_meaningful": source == "costed_run",
        # What the operation column is actually reporting, so a sheet, a page and an email
        # cannot each pick their own word for it.
        "operation_column": "charged" if source == "costed_run" else "required by the route",
    }


def route_payloads(summary: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Every canonical-route payload in the record, under either spelling and either nesting.

    THE DEFECT THIS EXISTS FOR. Reading one spelling and missing the other is how a route that IS
    recorded reads as absent — and it did: the extraction audit's Operations sheet read
    `canonical_route` alone and came back empty on every real job, because the pipeline writes
    `canonical_route_shadow`.
    """
    out: List[Mapping[str, Any]] = []
    holders = [summary]
    nested = summary.get("estimate_summary") if isinstance(summary, Mapping) else None
    if isinstance(nested, Mapping):
        holders.append(nested)
    for holder in holders:
        if not isinstance(holder, Mapping):
            continue
        for key in ("canonical_route_shadow", "canonical_route"):
            payload = holder.get(key)
            if isinstance(payload, Mapping) and payload not in out:
                out.append(payload)
    return out


def _title_block_material_by_page(summary: Mapping[str, Any]) -> Dict[Any, str]:
    """Page number -> the material printed in that page's title block.

    WHY THE MATERIAL IS NOT ON THE PARTS-TABLE ROW. An SDI parts table lists item, part number,
    description and quantity — there is no material column to read, so the extract asking a BOM
    row for one could only ever come back blank. The material IS printed on the drawing; it is
    in the title block of the detail sheet. Once a row knows which page it was read from, that
    is reachable, and it is still the drawing's own words rather than an arbitrated answer.
    """
    out: Dict[Any, str] = {}
    for page in (summary.get("pages") or []):
        if not isinstance(page, Mapping):
            continue
        number = page.get("page_number")
        if number is None:
            continue
        analysis = page.get("page_analysis")
        block = analysis.get("title_block") if isinstance(analysis, Mapping) else None
        materials = block.get("materials") if isinstance(block, Mapping) else None
        text = ", ".join(str(m).strip() for m in (materials or []) if str(m).strip())
        if text:
            out[number] = text
    return out


def _title_block_thickness_by_page(summary: Mapping[str, Any]) -> Dict[Any, Any]:
    """Page number -> the gauge printed in that page's title block. Same reasoning as the
    material: the parts table has no gauge column, and the drawing does print one."""
    out: Dict[Any, Any] = {}
    for page in (summary.get("pages") or []):
        if not isinstance(page, Mapping):
            continue
        number = page.get("page_number")
        if number is None:
            continue
        analysis = page.get("page_analysis")
        block = analysis.get("title_block") if isinstance(analysis, Mapping) else None
        values = block.get("thicknesses_mm") if isinstance(block, Mapping) else None
        for value in (values or []):
            try:
                out[number] = float(str(value).strip())
                break
            except (TypeError, ValueError):
                continue
    return out


# The fields worth reporting a disagreement on. Every one of them changes a cost or an
# identity; a reader differing on, say, a formatting artefact is noise.
_CONTESTABLE = ("quantity", "description", "material_text", "thickness_mm")


def _disagreements(row: Mapping[str, Any]) -> str:
    """Where two readers read the same line differently, in their own words.

    THE MOST VALUABLE FACT THE PIPELINE PRODUCES, and it used to be a sentence in a merge note
    that nothing could act on. If the table parser read quantity 2 and the vision model read 4,
    one of them is wrong and an estimator can settle it in seconds from the drawing — but only
    if the sheet says so. Agreement is not reported: a column that speaks on every row is one
    nobody reads.
    """
    readings = [r for r in (row.get("readings") or []) if isinstance(r, Mapping)]
    if len(readings) < 2:
        return ""
    out: List[str] = []
    for field in _CONTESTABLE:
        seen: Dict[str, List[str]] = {}
        for reading in readings:
            if field not in reading:
                continue
            value = str(reading[field]).strip()
            reader = str(reading.get("source") or "a reader")
            seen.setdefault(value, [])
            if reader not in seen[value]:
                seen[value].append(reader)
        if len(seen) > 1:
            out.append(field.replace("_", " ") + ": "
                       + "; ".join(f"{', '.join(who)} read {value!r}"
                                   for value, who in seen.items()))
    return " | ".join(out)


def bom_sheet(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every parts-list row, with the page it was read from and the reader that read it."""
    rows: List[Dict[str, Any]] = []
    seen_codes: Dict[str, int] = {}
    by_page = _title_block_material_by_page(summary)
    thick_by_page = _title_block_thickness_by_page(summary)
    for row in ((summary.get("document_analysis") or {}).get("bom_rows") or []):
        if not isinstance(row, Mapping):
            continue
        code = _text(row.get("part_number"))
        seen_codes[code.upper()] = seen_codes.get(code.upper(), 0) + 1
        reader = _text(row.get("source") or row.get("reader") or "")
        page = row.get("source_page") if row.get("source_page") is not None else row.get("page")
        # THE PARTS TABLE FIRST, THE PAGE'S TITLE BLOCK SECOND, AND THE SHEET SAYS WHICH. Both
        # are printed on the drawing; they are not the same claim. A material on the row is that
        # line's own; a material from the title block is the SHEET's, and on a detail sheet
        # drawing one part those are the same thing — on a page carrying several, they are not,
        # so the reader has to be able to see the difference rather than being handed one word.
        material = _text(row.get("material_text"))
        material_from = "the parts table row" if material else ""
        if not material and page is not None and by_page.get(page):
            material = _text(by_page[page])
            material_from = f"title block of page {page} — the parts table has no material column"
        rows.append({
            "part_number": code,
            "description": _text(row.get("description")),
            "quantity": row.get("quantity"),
            "material_as_printed": material,
            "material_read_from": material_from,
            # SAME PAGE, SAME REASONING. Filled only where the row itself has none, and the
            # source column above already says the page it came from.
            "thickness_mm": (row.get("thickness_mm")
                             if row.get("thickness_mm") is not None
                             else (thick_by_page.get(page) if page is not None else None)),
            # item_number IS THE NAME. The deterministic table reader builds every row as
            # {item_number, part_number, description, quantity} — extractor_patterns.py:1049 and
            # :1082 — and part_identity.normalize_bom_row keeps that spelling. Asking for "item"
            # or "item_no" found nothing, so this column was blank on every row of every pack
            # while the value sat on the row under its real name.
            "item_no": _text(row.get("item_number") or row.get("item")
                             or row.get("item_no") or ""),
            "read_from_page": _text(row.get("source_page") or row.get("page") or ""),
            "read_by": reader,
            # CORROBORATION, WHICH IS THE WHOLE POINT OF HAVING SIX READERS. A line the table
            # parser and the vision model both saw is stronger than either alone, and until the
            # merge started keeping this, a row read twice came out looking read once.
            "also_read_by": ", ".join(str(r) for r in (row.get("also_read_by") or [])),
            "times_read": len(row.get("readings") or []) or 1,
            # WHERE THE READERS DISAGREE, named reader by reader. Empty where they agree.
            "readers_disagree_on": _disagreements(row),
            "what_that_reader_is": READER_MEANING.get(reader.lower(),
                                                      "reader not named on this row"
                                                      if not reader else
                                                      f"reader recorded as {reader!r}"),
        })
    # APPEARING TWICE IS NOT THE SAME AS BEING WANTED TWICE. A part number on three sheets of one
    # pack is usually one part drawn three times, and the quantity that matters is the assembly's.
    # Flagged rather than merged: merging here would hide the very duplication an estimator needs
    # to rule on.
    for row in rows:
        count = seen_codes.get(str(row["part_number"]).upper(), 0)
        row["appears_on_n_rows"] = count
        row["duplicate_note"] = ("" if count <= 1 else
                                 f"this part number appears on {count} BOM rows in this pack — "
                                 f"usually one part drawn more than once, NOT a quantity to add "
                                 f"up. Not merged here: that is a judgement, and merging would "
                                 f"hide it")
    return rows


def bom_columns_not_recorded(summary: Mapping[str, Any]) -> Dict[str, str]:
    """Columns that are blank on EVERY row, with the reason — because the record never held it.

    A BLANK CELL IS THE WORST WAY FOR A FACT TO BE MISSING. It is indistinguishable from a fact
    that was looked for and found to be absent: an empty "material as printed" reads as "the
    drawing printed no material", which on 7332-01 was flatly untrue — the covering email from
    the same run printed 5mm MS and 2mm Acrylic. Exactly the failure the empty Operations sheet
    had, where "this pack states no operations" was the record failing to carry them.

    WHAT IS ACTUALLY MISSING, AND WHERE. The deterministic BOM table reader builds each row as
    {item_number, part_number, description, quantity} and nothing else — extractor_patterns.py
    :1049 and :1082. No reader stamps `source` or `source_page` onto a BOM row at all. So on a
    normal pack the material, the gauge, the page and above all WHICH READER PRODUCED THE ROW
    are absent from the record, not merely unread by this module. That last one matters most:
    reading quality cannot be audited row by row while a row cannot say who read it.

    Reported per column rather than as one warning, so a pack whose vision rows DO carry a
    source is not told its rows are anonymous.
    """
    rows = bom_sheet(summary)
    if not rows:
        return {}
    why = {
        "material_as_printed": "no BOM reader records the material column on the row. The "
                               "material an estimator sees elsewhere was arbitrated from the "
                               "title block, the DXF filename and the model — not taken from "
                               "this table",
        "thickness_mm": "gauge is not captured on the parts-table row; it is resolved later "
                        "from the title block, the filename and the model",
        "read_from_page": "the reader does not record which page it read the row from",
        "read_by": "no reader stamps itself onto a BOM row, so this pack cannot say which "
                   "reader produced which line",
        "item_no": "the parts table carried no item numbers on this pack",
        "description": "no description was read on any row",
        "quantity": "no quantity was read on any row",
    }
    out: Dict[str, str] = {}
    for column in ("material_as_printed", "thickness_mm", "item_no", "read_from_page",
                   "read_by", "description", "quantity"):
        if all(str(r.get(column) or "").strip() == "" for r in rows):
            out[column] = why.get(column, "not recorded on the BOM row")
    return out


def route_sheet(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Every route decision, its target, whether the route requires it, and why it stands.

    THE COLUMN CHANGES ITS NAME WITH THE SOURCE, not its values. On a costed run "charged" is
    true of an operation the estimate actually charged for. On a pack that was never priced the
    same column of yeses and nos would read as a statement about money — and a wall of
    "charged: no" would read as "this pack needs no work", which is the opposite of what the
    route says. So an uncosted read labels it "required by the route", which is precisely what
    the compiler decided and all it decided.
    """
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    _column = source_declaration(summary)["operation_column"]
    for payload in route_payloads(summary):
        for decision in (payload.get("decisions") or []):
            if not isinstance(decision, Mapping):
                continue
            key = (_text(decision.get("decision_id")),
                   _text(decision.get("operation")),
                   _text(decision.get("target_id") or decision.get("part_number")))
            if key in seen:
                continue
            seen.add(key)
            status = _text(decision.get("status")).strip().lower()
            participants = [_text(p) for p in (decision.get("participants") or [])]
            rows.append({
                "part_or_assembly": _text(decision.get("target_id")
                                          or decision.get("part_number")
                                          or decision.get("target")),
                "operation": _text(decision.get("operation")),
                _column: "yes" if status == "required" else "no",
                "status": status or "(none recorded)",
                # AND THE WORDS BESIDE IT, for the same reason. STATUS_MEANING's "required"
                # reads "it is charged and the part cannot be made without it" — true of a
                # costed run and false of a pack nobody priced. The half that is true either
                # way is the half about the part; the money half is dropped rather than
                # rewritten into something vaguer, because the vaguer version would still be
                # read as being about money.
                "what_that_status_means": (
                    STATUS_MEANING.get(status, "status not recognised — treat as unconfirmed")
                    if _column == "charged" or status != "required" else
                    "the route REQUIRES this operation: the part cannot be made without it. "
                    "Nothing here is charged — this pack was not costed"),
                "scope": _text(decision.get("scope")),
                "covers_parts": ", ".join(participants),
                "why": _text(decision.get("reason")),
                "decided_from": _text(decision.get("source") or decision.get("decided_by")),
                "decision_id": _text(decision.get("decision_id")),
            })
    rows.sort(key=lambda r: (r["part_or_assembly"], r["operation"]))
    return rows


def derivation_sheet(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Column by column: what it is, where it came from, and what it does NOT mean.

    The last column is the one that earns its place. Every figure on a sheet like this gets
    quoted eventually, and the quickest way to be misquoted is to publish a number with no
    statement of its limits.
    """
    payloads = route_payloads(summary)
    where_route = ", ".join(
        k for k in ("canonical_route_shadow", "canonical_route")
        if any(k in h for h in ([summary] + ([summary.get("estimate_summary")]
               if isinstance(summary.get("estimate_summary"), Mapping) else []))
               if isinstance(h, Mapping))) or "not present in this record"
    readers = sorted({str(r.get("read_by") or "") for r in bom_sheet(summary)} - {""})
    return [
        {"sheet": "BOMs", "column": "part_number",
         "derived_from": "document_analysis.bom_rows[].part_number",
         "how": "as printed on the drawing's parts list, or as the SolidWorks BOM gave it",
         "what_it_does_not_mean": "not evidence the part is IN this job's scope — a parts list "
                                  "can name a part for reference. Scope is the assembly tree"},
        {"sheet": "BOMs", "column": "quantity",
         "derived_from": "document_analysis.bom_rows[].quantity",
         "how": "the quantity column of the parts list, per the row it was read from",
         "what_it_does_not_mean": "NOT the job quantity, and not rolled through the assembly. A "
                                  "sub-assembly's 2-off inside a 6-off stand is 12 parts, and "
                                  "that multiplication is the route compiler's, not this sheet's"},
        {"sheet": "BOMs", "column": "material_as_printed",
         "derived_from": "document_analysis.bom_rows[].material_text",
         "how": "the material cell exactly as the drawing office typed it, never normalised",
         "what_it_does_not_mean": "not the material the engine priced — that is the normalised "
                                  "code, which can differ and says so on the estimate"},
        {"sheet": "BOMs", "column": "read_by / what_that_reader_is",
         "derived_from": "document_analysis.bom_rows[].source",
         "how": f"the reader that produced the row. Present in this pack: "
                f"{', '.join(readers) if readers else 'none recorded'}",
         "what_it_does_not_mean": "a row read by one reader is not wrong; it is "
                                  "uncorroborated, which is a different thing"},
        {"sheet": "BOMs", "column": "appears_on_n_rows / duplicate_note",
         "derived_from": "counted across this pack's BOM rows",
         "how": "how many rows carry this part number",
         "what_it_does_not_mean": "NOT a quantity to add up. Most SDI parts appear on several "
                                  "sheets of one pack. Nothing is merged here"},
        {"sheet": "Routes", "column": "operation",
         "derived_from": f"the canonical route ({where_route})",
         "how": f"one row per compiler decision. {len(payloads)} route payload(s) found in this "
                f"record",
         "what_it_does_not_mean": "an operation listed is not necessarily charged — read the "
                                  "charged column"},
        {"sheet": "Routes", "column": "charged",
         "derived_from": "decision.status",
         "how": "yes only where the status is exactly `required`",
         "what_it_does_not_mean": "`unverified` means the compiler found evidence and could not "
                                  "confirm it. It is NOT charged and it is NOT ruled out — it is "
                                  "waiting for a person"},
        {"sheet": "Routes", "column": "covers_parts",
         "derived_from": "decision.participants",
         "how": "an assembly-scoped decision is ONE event across several parts — a weld is not "
                "three welds because three parts meet",
         "what_it_does_not_mean": "not a per-part charge. Dividing it between the participants "
                                  "is what makes a setup look like three setups"},
        {"sheet": "Routes", "column": "why",
         "derived_from": "decision.reason",
         "how": "the compiler's own sentence for why this decision stands or does not",
         "what_it_does_not_mean": "it explains the DECISION, not the price"},
    ]


def build_tables(summary: Mapping[str, Any], want: str = "both") -> Dict[str, List[Dict[str, Any]]]:
    """`want` is "boms", "routes" or "both" — the three buttons, one builder."""
    tables: Dict[str, List[Dict[str, Any]]] = {}
    if want in ("boms", "both"):
        tables["BOMs"] = bom_sheet(summary)
    if want in ("routes", "both"):
        tables["Routes"] = route_sheet(summary)
    tables["How these were derived"] = [
        row for row in derivation_sheet(summary)
        if want == "both" or row["sheet"].lower().startswith(want[:4])]
    return tables


def _job_label(summary: Mapping[str, Any], job: str = "") -> str:
    return str(job or summary.get("job_number") or summary.get("scan_label") or "job").strip()


def write_workbook(summary: Mapping[str, Any], out_dir: Any, job: str = "",
                   want: str = "both",
                   tables: Optional[Mapping[str, List[Dict[str, Any]]]] = None) -> Optional[Path]:
    """The spreadsheet: one sheet per subject, one explaining how each column was derived.

    Never raises into the caller — an extract that breaks the page it was launched from is worse
    than no extract.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except Exception:                                                    # noqa: BLE001
        return None
    tables = dict(tables) if tables is not None else build_tables(summary, want)
    label = _job_label(summary, job)
    book = Workbook()
    book.remove(book.active)
    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(bold=True, color="FFFFFF")
    for name in SHEETS:
        if name not in tables:
            continue
        rows = tables[name] or []
        sheet = book.create_sheet(name[:31])
        if not rows:
            sheet.cell(row=1, column=1,
                       value=f"No {name.lower()} in this record. That is a fact about the "
                             f"record, not about the pack — see How these were derived.")
            continue
        headers = list(rows[0].keys())
        for column, header in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=column, value=header.replace("_", " "))
            cell.fill = head_fill
            cell.font = head_font
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        for r, row in enumerate(rows, start=2):
            for c, header in enumerate(headers, start=1):
                cell = sheet.cell(row=r, column=c, value=row.get(header))
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for column, header in enumerate(headers, start=1):
            longest = max([len(str(header))]
                          + [len(str(row.get(header) or "")) for row in rows])
            sheet.column_dimensions[get_column_letter(column)].width = min(60, max(12, longest + 2))
        sheet.freeze_panes = "A2"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = {"boms": "boms", "routes": "routes", "both": "boms_and_routes"}.get(want, want)
    path = out / f"{label}_{suffix}.xlsx"
    try:
        book.save(path)
    except Exception:                                                    # noqa: BLE001
        return None
    return path


def _esc(value: Any) -> str:
    import html as _html
    return _html.escape("" if value is None else str(value), quote=True)


_CSS = """
*{box-sizing:border-box}
body{margin:0;background:#f4f5f7;color:#14181f;
     font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1500px;margin:0 auto;padding:28px 20px 64px}
header{border-bottom:3px solid #1f3864;padding-bottom:14px;margin-bottom:8px}
.kicker{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:#1f3864;font-weight:700}
h1{margin:6px 0 4px;font-size:27px;letter-spacing:-.015em}
.sub{margin:0;color:#515b6b;max-width:86ch}
h2{margin:34px 0 6px;font-size:19px;letter-spacing:-.01em}
h2 .cnt{font-size:12px;font-weight:600;color:#1f3864;background:#e6ebf5;
        border-radius:999px;padding:2px 9px;margin-left:8px;vertical-align:2px}
.why{margin:0 0 12px;color:#515b6b;max-width:92ch;font-size:13px}
.panel{background:#fff;border:1px solid #dfe3ea;border-radius:10px;
       box-shadow:0 1px 2px rgba(16,24,40,.05)}
.scroll{overflow-x:auto;border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}
th{background:#1f3864;color:#fff;text-align:left;padding:9px 11px;font-weight:600;
   white-space:nowrap;position:sticky;top:0}
td{padding:8px 11px;border-top:1px solid #eceef3;vertical-align:top}
tr:nth-child(even) td{background:#fbfcfd}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.yes{color:#0a7a3d;font-weight:700}
.no{color:#8a6100;font-weight:700}
.dup{color:#8a1c1c}
footer{margin-top:40px;padding-top:14px;border-top:1px solid #dfe3ea;color:#6b7585;font-size:12px;
       max-width:92ch}
@media (max-width:760px){th,td{font-size:12px;padding:6px 8px}}
"""

_INTRO = {
    "BOMs": ("Every parts-list row this pack gave us, with the page it was read from and the "
             "reader that read it. Nothing is merged: a part number on three sheets stays three "
             "rows, flagged, because deciding whether that is one part or three is an "
             "estimator's call and merging it here would hide the question."),
    "Routes": ("Every decision the route compiler made, what it covers, and whether it is "
               "charged. An operation listed is not necessarily charged — `required` is charged, "
               "`unverified` means the compiler found evidence it could not confirm and is "
               "waiting for a person."),
    "How these were derived": ("Column by column: where the value came from and what it does "
                               "NOT mean. Every figure on a sheet like this gets quoted "
                               "eventually, and the quickest way to be misquoted is to publish "
                               "a number with no statement of its limits."),
}


def write_html(summary: Mapping[str, Any], out_dir: Any, job: str = "", want: str = "both",
               tables: Optional[Mapping[str, List[Dict[str, Any]]]] = None) -> Optional[Path]:
    """The same tables as a page. Built from the SAME snapshot when one is passed."""
    tables = dict(tables) if tables is not None else build_tables(summary, want)
    label = _job_label(summary, job)
    title = {"boms": "BOMs", "routes": "Routes", "both": "BOMs and routes"}.get(want, want)
    parts: List[str] = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{_esc(title)} — {_esc(label)}</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        "<header><div class='kicker'>SDI Estimating Intelligence</div>",
        f"<h1>{_esc(title)} — {_esc(label)}</h1>",
        "<p class='sub'>What the drawing pack says is in the job, and what work the engine "
        "decided each part needs. This prices nothing. It exists so the two questions that come "
        "BEFORE a price — what parts, and what work — can be checked on their own.</p></header>",
    ]
    for name in SHEETS:
        if name not in tables:
            continue
        rows = tables[name] or []
        parts.append(f"<h2>{_esc(name)}<span class='cnt'>{len(rows)}</span></h2>")
        parts.append(f"<p class='why'>{_esc(_INTRO.get(name, ''))}</p>")
        if not rows:
            parts.append("<div class='panel' style='padding:14px 16px'>Nothing in this record. "
                         "That is a fact about the record, not about the pack.</div>")
            continue
        headers = list(rows[0].keys())
        parts.append("<div class='panel scroll'><table><thead><tr>")
        for header in headers:
            parts.append(f"<th>{_esc(header.replace('_', ' '))}</th>")
        parts.append("</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>")
            for header in headers:
                value = row.get(header)
                klass = ""
                # THE YES/NO COLUMN BY ROLE, NOT BY NAME. It is called "charged" on a costed
                # run and "required by the route" on a pack that was never priced, and keying
                # the styling on the literal name lost the colour on exactly the outputs the
                # new buttons produce — where telling a required operation from a ruled-out one
                # at a glance is the whole point of the sheet.
                if header in ("charged", "required by the route"):
                    klass = " class='yes'" if str(value) == "yes" else " class='no'"
                elif header == "duplicate_note" and value:
                    klass = " class='dup'"
                elif isinstance(value, (int, float)):
                    klass = " class='num'"
                parts.append(f"<td{klass}>{_esc(value)}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table></div>")
    parts.append(
        "<footer>Read off the drawing pack and the compiled route; no price is computed here "
        "and no figure on this page is a cost. A quantity is the row's own, not rolled through "
        "the assembly. An operation is charged only where its status is <b>required</b>.</footer>"
        "</div></body></html>")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = {"boms": "boms", "routes": "routes", "both": "boms_and_routes"}.get(want, want)
    path = out / f"{label}_{suffix}.html"
    try:
        path.write_text("".join(parts), encoding="utf-8")
    except Exception:                                                    # noqa: BLE001
        return None
    return path


def write_both(summary: Mapping[str, Any], out_dir: Any, job: str = "",
               want: str = "both") -> Dict[str, Optional[str]]:
    """One snapshot, both outputs — so the sheet and the page cannot disagree."""
    tables = build_tables(summary, want)
    xlsx = write_workbook(summary, out_dir, job, want, tables=tables)
    html = write_html(summary, out_dir, job, want, tables=tables)
    return {"xlsx": str(xlsx) if xlsx else None,
            "html": str(html) if html else None,
            "boms": len(tables.get("BOMs") or []),
            "routes": len(tables.get("Routes") or [])}


__all__ = ["SHEETS", "READER_MEANING", "STATUS_MEANING", "route_payloads", "bom_sheet",
           "route_sheet", "derivation_sheet", "source_declaration",
           "bom_columns_not_recorded", "build_tables", "write_workbook", "write_html",
           "write_both"]
