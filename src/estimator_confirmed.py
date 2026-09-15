"""What a person read off the drawing, entered once, ranked above everything the engine guessed.

source_precedence has carried `estimator_confirmed` at rank 100 — "a person looked at it and
said so" — since it was written. Nothing has ever written it. The top of the ranking was a
door with no handle on the outside, so on any pack the readers cannot handle there was no way
to state a fact except to change code.

0359342 is what that costs. Its parts bound to their parent's parts list rather than their own
detail sheet, so geometry_inference handed out category-default envelopes — 400 x 300 for
anything named PANEL, 350 x 250 for anything named PLATE — and those envelopes drove the nest,
the laser time and the coated area. The real sizes are printed on the sheets: JAE826 is
1680 x 560, JAE832 is 1670 x 546, MBY439 is 1578 x 188. Seven board panels nested from
400 x 300 against sizes up to 1680 x 560 is an UNDER-charge of three to nine times on the
board — the direction nobody notices, because a quote that is too low is accepted.

Two attempts to teach the extractor to read these sheets failed, and both failures are
instructive: the figures are on the page, but choosing WHICH figures are the overall is a
view-and-direction problem the flat text layer does not carry. That work is worth doing and
is not this. A person can read the sheet in ten seconds. This is the door that lets them.

WHAT THIS ACCEPTS, AND WHAT IT REFUSES.

It accepts geometry, material, gauge and quantity — facts a drawing states and a person can
check against it. It REFUSES prices, rates and costs, by name, with an explanation. That is
deliberate and it is the whole reason this is safe to add: a rate typed into a side file would
be indistinguishable in the output from a rate the engine sourced, and the standing rule of
this codebase is that no price is invented. An estimator who wants to override a price should
do it on the sheet, where it is visible as their decision, not here where it would inherit the
engine's provenance.

Nothing is silent. A stamped part says on its own record who confirmed it and off which sheet;
a part number in the file that matches nothing in the job is reported loudly rather than
ignored, because a typo'd code silently doing nothing is exactly how this feature would come
to be trusted while contributing nothing.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# The rank source_precedence already defines. Named once so the two cannot drift apart.
SOURCE = "estimator_confirmed"

# The conventional names, in the order they are looked for. A job-specific name wins over the
# generic one so a folder holding several jobs cannot have one file quietly govern them all.
FILE_NAMES = (
    "{drawing}_estimator_dimensions.json",
    "{drawing}_confirmed.json",
    "estimator_dimensions.json",
)

# Field name in the file -> field name on the part record. The part-record names are the ones
# the estimator actually reads; the file uses the shorter names a person would write.
_FIELD_MAP = {
    "blank_length_mm": "blank_length_mm",
    "blank_width_mm": "blank_width_mm",
    "thickness_mm": "normalized_thickness_mm",
    "material": "normalized_material",
    "quantity": "quantity",
    # LINEAR STOCK IS SIZED BY A LENGTH AND A DIAMETER, NOT BY A BLANK.
    #
    # A bar or wire has no rectangle to nest, so the sheet fields above cannot describe it,
    # and the engine will not infer its length: wire_length_mm is written only by a bar/wire
    # schedule, because a PDF vector outline is not a developed length. MBY432 on 0359342 is
    # Ø8 x 219.6 printed on its own detail sheet with no schedule anywhere in the pack, so it
    # costed on an assumed 900 mm form band — four times the mass, 56 off. The figure was on
    # the drawing; there was simply no audited way for a person to enter it.
    "wire_length_mm": "wire_length_mm",
    "wire_gauge_mm": "wire_gauge_mm",
    # A ROLL-GOODS PIECE IS SIZED BY THE LENGTH CUT OFF THE ROLL. 10975's pack states the
    # tape twice — LENGTH: 200.00 on one BOM row and 220.00 on its duplicate — and the
    # engine prices on the kept reading while asking the estimator to pick. This is where
    # the pick lands: Howard confirmed three 200 mm strips (his own sheet prices 0.06 of a
    # 10 m roll), and a confirmed length closes that decision instead of re-asking it on
    # every run. A length a drawing states and a person checked — squarely in scope.
    "piece_length_mm": "confirmed_piece_length_mm",
}

# Fields that describe a FLAT BLANK, and fields that describe LINEAR STOCK. A part is one or
# the other, and a file stating both is describing two different parts.
_SHEET_FIELDS = ("blank_length_mm", "blank_width_mm")
_LINEAR_FIELDS = ("wire_length_mm", "wire_gauge_mm")

# Descriptive keys: recorded on the part for the report, never costed from.
_NOTE_KEYS = ("read_from", "note", "description")

# PRICE IT, AND SAY WHAT YOU ASSUMED. Two bases, two ranks, one file.
#
# The first version of this file took readings only, so anything the drawing did not print
# had to be left out — and six parts of 0359342 were, including a thermoformed Corian tray
# and a laminated curved corner. That was the wrong call. A drawing pack is never perfect;
# an estimate with holes cannot be quoted from, and a hole is not more honest than a stated
# assumption, only less useful. An estimator can overturn an assumption they can see.
#
# So a figure is entered on one of three bases, and they are never confused:
#
#   "read"      printed on the sheet          estimator_read_drawing  rank 72
#   "inferred"  worked out from what it shows estimator_inferred      rank 45
#   "corrected" the files are WRONG, and why  estimator_confirmed     rank 100
#
# THE DXF AND THE MODEL ARE AUTHORITATIVE, AND "read" DELIBERATELY DOES NOT OUTRANK THEM.
# The DXF is the file the laser cuts from and the model is what the shop builds; where either
# disagrees with a sheet, they win, and the estimate says so. A person transcribing an
# overall off a PDF has not overturned a flat pattern — they have read the same drawing the
# engine read, more reliably, so they rank as the best PDF-derived source and no higher.
# Rank 100 is reserved for the different act of KNOWING the files are wrong, which has to be
# claimed on purpose and argued for.
#
# Both "inferred" and "corrected" MUST carry their working. A number with no stated reasoning
# is a guess wearing a person's authority, which is the one thing this file must never
# launder — and that goes double for the basis that outranks a measurement.
_BASIS_SOURCE = {
    "read": "estimator_read_drawing",
    "inferred": "estimator_inferred",
    "corrected": SOURCE,
}
_BASIS_NEEDS_REASON = ("inferred", "corrected")

# Refused by name rather than ignored. See the module docstring: a price entered here would be
# indistinguishable in the output from one the engine sourced.
_REFUSED_KEYS = ("price", "cost", "rate", "gbp", "price_gbp", "cost_gbp",
                 "unit_price", "material_cost", "labour_cost")


def _num(value: Any, *, positive: bool = True) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if positive and out <= 0:
        return None
    return out


def drawing_stems(drawing_number: Any) -> List[str]:
    """The names a person actually calls the job by, most specific first.

    The engine knows a pack by its GA sheet — "10975-02-GA" — and the office knows the job
    by the number on the folder — "10975-02". A confirmations file is written by the office,
    so `10975-02_confirmed.json` sat unread beside a job whose only recognised name carried
    the sheet-role suffix, and Howard's answers did nothing. The suffix (GA, DETAIL, an
    issue letter) is the engine's business, not the author's, so every trailing PURELY
    ALPHABETIC dash-segment yields a further stem. Segments with digits are the code itself
    ("-02", "-A01") and are never stripped: "10975" alone could name a different job in the
    same folder, which is exactly the quiet cross-governance the specific-name-first rule
    exists to prevent.
    """
    stems: List[str] = []
    text = str(drawing_number or "").strip()
    while text and text not in stems:
        stems.append(text)
        head, sep, tail = text.rpartition("-")
        if not sep or not head or not tail.isalpha():
            break
        text = head
    return stems


def find_corrections_file(job_folder: Any, pdf_path: Any = None,
                          drawing_number: Any = None) -> Optional[Path]:
    """The confirmations file for this job, if one has been written. None is the normal case.

    Looked for beside the job's drawings, so it travels with the job rather than living in the
    engine — a pack handed to someone else carries its confirmations with it.
    """
    stems = drawing_stems(drawing_number)
    roots: List[Path] = []
    for candidate in (job_folder, (Path(pdf_path).parent if pdf_path else None)):
        if not candidate:
            continue
        try:
            root = Path(candidate)
        except (TypeError, ValueError):
            continue
        if root.is_dir() and root not in roots:
            roots.append(root)
    for root in roots:
        for pattern in FILE_NAMES:
            if "{drawing}" in pattern:
                for stem in stems:
                    path = root / pattern.format(drawing=stem)
                    if path.is_file():
                        return path
                continue
            path = root / pattern
            if path.is_file():
                return path
    return None


def load_corrections(path: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Read and validate the file. Returns (parsed, problems); problems are for the operator.

    A malformed file is NOT a silent no-op. Someone who wrote it believes the job is being
    costed from it, so every reason a line was not used has to reach them.
    """
    problems: List[str] = []
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, [f"{path}: no such file"]
    except (OSError, ValueError) as err:
        return {}, [f"{path}: could not be read — {type(err).__name__}: {err}"]
    if not isinstance(raw, Mapping):
        return {}, [f"{path}: the top level must be an object, not {type(raw).__name__}"]

    parts_in = raw.get("parts")
    if not isinstance(parts_in, Mapping):
        return {}, [f"{path}: no 'parts' object — nothing to apply"]

    clean: Dict[str, Dict[str, Any]] = {}
    for code, spec in parts_in.items():
        code_s = str(code).strip()
        if not code_s:
            continue
        if not isinstance(spec, Mapping):
            problems.append(f"{code_s}: expected an object of fields, got "
                            f"{type(spec).__name__} — skipped")
            continue
        entry: Dict[str, Any] = {}
        for key, value in spec.items():
            key_l = str(key).strip().lower()
            if key_l in _REFUSED_KEYS:
                problems.append(
                    f"{code_s}: '{key}' REFUSED — this file states what the drawing says "
                    f"(size, gauge, material, quantity), never what something costs. A price "
                    f"entered here would read in the output exactly like one the engine "
                    f"sourced. Price it on the sheet, where it shows as your decision")
                continue
            if key_l in _NOTE_KEYS:
                entry[key_l] = str(value)
                continue
            if key_l == "layers":
                # A LAMINATION IS ONE COMPONENT MADE OF SEVERAL MATERIALS. Declared here so
                # every layer reaches the price; kept ON the part so no second identity is
                # minted, because a layer turned into a part would double the fasteners, the
                # handling and the assembly around it.
                if not isinstance(value, Sequence) or isinstance(value, str):
                    problems.append(f"{code_s}: 'layers' must be a list of layers — skipped")
                    continue
                layers: List[Dict[str, Any]] = []
                for position, layer in enumerate(value, start=1):
                    if not isinstance(layer, Mapping):
                        problems.append(f"{code_s} layer {position}: expected an object "
                                        f"— skipped")
                        continue
                    built: Dict[str, Any] = {}
                    for lk in ("material", "note"):
                        if layer.get(lk):
                            built[lk] = str(layer[lk])
                    for lk in ("thickness_mm", "blank_length_mm", "blank_width_mm"):
                        ln = _num(layer.get(lk))
                        if ln is not None:
                            built[lk] = ln
                    if not built.get("material") or built.get("thickness_mm") is None:
                        problems.append(
                            f"{code_s} layer {position}: a layer needs at least a material "
                            f"and a thickness_mm, or it cannot be priced — skipped")
                        continue
                    layers.append(built)
                if len(layers) < 2:
                    problems.append(
                        f"{code_s}: 'layers' describes fewer than two usable layers, so it "
                        f"says nothing the single material fields do not — skipped")
                    continue
                entry["layers"] = layers
                continue
            if key_l == "basis":
                basis = str(value).strip().lower()
                if basis not in _BASIS_SOURCE:
                    problems.append(
                        f"{code_s}: basis {value!r} is not understood — use 'read' for a "
                        f"figure printed on the sheet, or 'inferred' for one worked out "
                        f"from it")
                    continue
                entry["basis"] = basis
                continue
            if key_l not in _FIELD_MAP:
                problems.append(f"{code_s}: '{key}' is not a field this understands "
                                f"(accepted: {', '.join(sorted(_FIELD_MAP))}) — skipped")
                continue
            if key_l == "material":
                text = str(value).strip()
                if not text:
                    problems.append(f"{code_s}: material is empty — skipped")
                    continue
                entry[key_l] = text
                continue
            number = _num(value)
            if number is None:
                problems.append(f"{code_s}: {key} = {value!r} is not a positive number "
                                f"— skipped")
                continue
            if key_l == "quantity":
                if number != int(number):
                    problems.append(f"{code_s}: quantity {value!r} is not a whole number "
                                    f"— skipped")
                    continue
                entry[key_l] = int(number)
                continue
            entry[key_l] = number
        # A LENGTH WITHOUT A WIDTH IS NOT A BLANK. blank_credibility refuses one-without-the-
        # other for the readers, and a typed figure gets no easier ride: half a rectangle
        # sizes nothing, and filling the other half from a category default is the very
        # failure this exists to end.
        has_l, has_w = "blank_length_mm" in entry, "blank_width_mm" in entry
        if has_l != has_w:
            missing = "blank_width_mm" if has_l else "blank_length_mm"
            problems.append(f"{code_s}: only one blank dimension given — {missing} is "
                            f"missing, so neither is used. Give both or neither")
            entry.pop("blank_length_mm", None)
            entry.pop("blank_width_mm", None)
        # A PART IS SHEET OR LINEAR, NEVER BOTH. Both sets present means the file is
        # describing two different parts under one code, and stamping either at rank 100
        # would settle by field order which stock the part is bought as.
        if any(k in entry for k in _SHEET_FIELDS) and any(k in entry for k in _LINEAR_FIELDS):
            problems.append(
                f"{code_s}: a flat blank ({', '.join(k for k in _SHEET_FIELDS if k in entry)}) "
                f"and linear stock ({', '.join(k for k in _LINEAR_FIELDS if k in entry)}) are "
                f"both stated. A part is one or the other — neither set is used. Give the "
                f"blank for a sheet part, or the length and diameter for a bar")
            for _k in _SHEET_FIELDS + _LINEAR_FIELDS:
                entry.pop(_k, None)
        # A CLAIM WITHOUT ITS WORKING IS A GUESS WEARING A PERSON'S AUTHORITY.
        if entry.get("basis") in _BASIS_NEEDS_REASON and not (
                entry.get("read_from") or entry.get("note")):
            _b = entry["basis"]
            problems.append(
                f"{code_s}: basis is {_b!r} but no reasoning is given. State it in "
                f"'read_from' or 'note' — "
                + ("an inference has to be overturnable, and nobody can overturn what they "
                   "cannot see" if _b == "inferred" else
                   "this basis OUTRANKS the DXF and the model, so it must say why they are "
                   "wrong. Use 'read' for a figure you have simply read off the sheet"))
            for _k in list(_FIELD_MAP):
                entry.pop(_k, None)

        if any(k in entry for k in list(_FIELD_MAP) ):
            clean[code_s] = entry
        elif not any(p.startswith(f"{code_s}:") for p in problems):
            problems.append(f"{code_s}: no usable field — skipped")

    _decisions, _dec_problems = _read_decisions(raw, path)
    problems.extend(_dec_problems)

    return {
        "confirmed_by": str(raw.get("confirmed_by") or "").strip(),
        "confirmed_on": str(raw.get("confirmed_on") or "").strip(),
        "note": str(raw.get("note") or "").strip(),
        "parts": clean,
        "estimator_decisions": _decisions,
        "path": str(path),
    }, problems


# ── THE ESTIMATOR'S OWN DECISIONS, WHICH ARE A DIFFERENT THING FROM A READING ────────────
#
# `parts` above refuses prices and rates, and the reason is sound and unchanged: a price
# typed into a side file would read in the output exactly like one the engine sourced, so it
# has to be entered on the sheet where it shows as a person's decision.
#
# The trouble is that it did not show up there either. Howard Thurley's answers to 7332-01 —
# Brass Harrods 01 at £250, the tube bend not required, acrylic laser at 95/hr not 252 — have
# no home at all. Each is a config edit by us or an overtype that dies with that workbook,
# and the next run of the same job asks him the same questions again.
#
# So this block exists BESIDE `parts`, never inside it, and the distinction is the whole
# point:
#
#   parts               "the drawing says 1.0 mm"        a READING, ranked with the readers
#   estimator_decisions "we are charging £250 for this"  a DECISION, ranked as a person's
#
# A decision carries its owner's name and date onto every line it touches and is reported as
# theirs, never as the engine's. It is not a price the engine found; it is a price a person
# set, and the sheet says so.
#
# AND IT DOES NOT INHERIT. The file is named for the drawing, so it governs that job and no
# other. Anything that SHOULD apply to every job — the weld allowance, the plater freight,
# the brushing minutes — belongs in config.py, which is where those already are. The two
# homes answer two different questions: "how does SDI work" and "what did we decide about
# this stand".
_DECISION_KEYS = ("plating_gbp_per_unit", "plating_spec", "operations_off",
                  "throughput_per_hour")


def _read_decisions(raw: Mapping[str, Any], path: Any) -> Tuple[Dict[str, Any], List[str]]:
    out: Dict[str, Any] = {}
    problems: List[str] = []
    block = raw.get("estimator_decisions")
    if block in (None, {}):
        return out, problems
    if not isinstance(block, Mapping):
        return out, [f"{path}: 'estimator_decisions' must be an object, not "
                     f"{type(block).__name__}"]

    for key in block:
        if str(key).strip() not in _DECISION_KEYS:
            problems.append(
                f"estimator_decisions: '{key}' is not a decision this engine applies — "
                f"known: {', '.join(_DECISION_KEYS)}. The line did nothing")

    _plate = _num(block.get("plating_gbp_per_unit"), positive=True) \
        if block.get("plating_gbp_per_unit") is not None else None
    if block.get("plating_gbp_per_unit") is not None and _plate is None:
        problems.append("estimator_decisions.plating_gbp_per_unit: not a positive number — "
                        "ignored")
    elif _plate is not None:
        out["plating_gbp_per_unit"] = _plate
        out["plating_spec"] = str(block.get("plating_spec") or "").strip()

    _off = block.get("operations_off")
    if _off is not None:
        if not isinstance(_off, Mapping):
            problems.append("estimator_decisions.operations_off: expected {part: [ops]} — "
                            "ignored")
        else:
            clean_off: Dict[str, List[str]] = {}
            for code, ops in _off.items():
                if isinstance(ops, str):
                    ops = [ops]
                if not isinstance(ops, (list, tuple)):
                    problems.append(f"estimator_decisions.operations_off[{code}]: expected a "
                                    f"list of operation names — ignored")
                    continue
                names = [str(o).strip().lower().replace(" ", "_") for o in ops if str(o).strip()]
                if names:
                    clean_off[str(code).strip().upper()] = names
            if clean_off:
                out["operations_off"] = clean_off

    _tp = block.get("throughput_per_hour")
    if _tp is not None:
        if not isinstance(_tp, Mapping):
            problems.append("estimator_decisions.throughput_per_hour: expected "
                            "{operation: pieces per hour} — ignored")
        else:
            clean_tp: Dict[str, float] = {}
            for op, val in _tp.items():
                n = _num(val, positive=True)
                if n is None:
                    problems.append(f"estimator_decisions.throughput_per_hour[{op}]: not a "
                                    f"positive number — ignored")
                    continue
                clean_tp[str(op).strip()] = n
            if clean_tp:
                out["throughput_per_hour"] = clean_tp

    return out, problems


def _same_figure(held: Any, stated: Any) -> bool:
    """Whether the part already holds what the file states — numerically where both are
    numbers, as normalised text otherwise. Used only to tell an AGREEMENT apart from a
    REFUSAL after apply_field returns False for both."""
    if held is None:
        return False
    try:
        return abs(float(held) - float(stated)) < 1e-9
    except (TypeError, ValueError):
        pass
    a = re.sub(r"[\s_\-]+", " ", str(held).strip().upper())
    b = re.sub(r"[\s_\-]+", " ", str(stated).strip().upper())
    return bool(a) and a == b


def confirmation_match_keys(part: Mapping[str, Any]) -> List[str]:
    """Every name a person could reasonably write in the file for THIS part, bare-coded.

    The record's own part_number is a COMPONENT name when the part came from the model —
    "10975 EPDM Closed Cell Tape^10975-02-GA" — and nobody types that into a confirmations
    file. The BOM calls the same tape "10975"; the folded duplicate row called it
    "10975-02-00"; each is a name somebody actually read off a sheet. Howard's
    `"10975": {"piece_length_mm": 200}` matched nothing and his answer did nothing —
    silently, which is the one failure mode this module promises not to have.

    So a part answers to: its part_number as stored; that name with any ^configuration
    tail removed; the LEADING CODE of a "CODE Description" component name (digits-led,
    four or more, and never a category word — "TAPE" names a drawer, not a part); and
    every identity the duplicate fold has recorded onto it.
    """
    try:
        from part_code_conventions import bare_code, is_category_not_a_code
    except Exception:                                                     # noqa: BLE001
        def bare_code(text: str) -> str:                                  # type: ignore
            return re.sub(r"[\s\-]+", "", str(text or "").upper())

        def is_category_not_a_code(text: str) -> bool:                    # type: ignore
            return False

    keys: List[str] = []

    def _add(text: Any) -> None:
        code = bare_code(str(text or ""))
        if code and code not in keys:
            keys.append(code)

    raw = str(part.get("part_number") or "") if isinstance(part, Mapping) else ""
    name = raw.split("^", 1)[0].strip()
    _add(raw)
    _add(name)
    lead = name.split(None, 1)[0] if name else ""
    if lead and lead != name and re.match(r"^\d{4,}", lead) \
            and not is_category_not_a_code(lead):
        _add(lead)
    if isinstance(part, Mapping):
        for alias in (part.get("folded_duplicate_identities") or []):
            _add(alias)
    return keys


def apply_estimator_confirmed(parts: Any, corrections: Mapping[str, Any]) -> Dict[str, Any]:
    """Stamp the confirmed figures onto the parts. Returns a report for the operator.

    Every value goes through source_precedence at rank 100, so it wins against everything the
    engine derived — and the record still shows what it displaced. A code in the file that
    matches no part in the job is returned in `unmatched`, NOT swallowed: the person who wrote
    it is entitled to know their line did nothing.
    """
    report: Dict[str, Any] = {"stamped": 0, "fields": 0, "unmatched": [], "matched": [],
                              "agreed": 0}
    if not isinstance(parts, Sequence) or not isinstance(corrections, Mapping):
        return report
    wanted = corrections.get("parts")
    if not isinstance(wanted, Mapping) or not wanted:
        return report

    import source_precedence as sp
    try:
        from part_code_conventions import bare_code
    except Exception:                                                     # noqa: BLE001
        def bare_code(text: str) -> str:                                  # type: ignore
            return str(text or "").strip().upper()

    who = corrections.get("confirmed_by") or "an estimator"
    when = corrections.get("confirmed_on") or ""

    by_code: Dict[str, List[Dict[str, Any]]] = {}
    for part in parts:
        if isinstance(part, dict):
            for key in confirmation_match_keys(part):
                by_code.setdefault(key, []).append(part)

    for code, spec in wanted.items():
        targets = by_code.get(bare_code(code)) or []
        if not targets:
            report["unmatched"].append(code)
            continue
        source_note = spec.get("read_from") or spec.get("note") or ""
        basis = str(spec.get("basis") or "read").lower()
        rank_source = _BASIS_SOURCE.get(basis, SOURCE)
        for part in targets:
            changed: List[str] = []
            agreed: List[str] = []
            for file_key, part_field in _FIELD_MAP.items():
                if file_key not in spec:
                    continue
                before = part.get(part_field)
                if sp.apply_field(part, part_field, spec[file_key], rank_source):
                    changed.append(f"{file_key} {spec[file_key]}"
                                   + (f" (was {before})" if before not in (None, "") else ""))
                elif _same_figure(part.get(part_field), spec[file_key]):
                    # apply_field returns False for agreement as well as refusal, and the
                    # two must not look alike here: a person confirming what the files
                    # already said has ANSWERED a question (the agreement is recorded in
                    # _agreed and closes the open decision), and a confirmation that
                    # vanishes from the log is how a working file comes to look broken.
                    agreed.append(f"{file_key} {spec[file_key]}")
            if spec.get("layers"):
                # Direct-write, not through apply_field: this is not a competing reading of
                # a datum some other source also supplies — nothing else in the engine
                # describes a lamination at all, so there is nothing to arbitrate against.
                part["material_layers"] = [dict(_l) for _l in spec["layers"]]
                changed.append(f"{len(spec['layers'])} material layers")
            if not changed and not agreed:
                continue
            if changed:
                report["stamped"] += 1
                report["fields"] += len(changed)
            report["agreed"] += len(agreed)
            report["matched"].append(code)
            part["estimator_confirmed"] = {
                "by": who,
                "on": when,
                "basis": basis,
                "source": rank_source,
                "read_from": source_note,
                "fields": dict(spec),
                "file": corrections.get("path"),
            }
            _stamp = f" on {when}" if when else ""
            if agreed:
                part.setdefault("review_flags", []).append(
                    f"{code}: {', '.join(agreed)} — CONFIRMED by {who}{_stamp}, agreeing "
                    f"with what the files already said. Nothing changed; the open question "
                    f"on this figure is answered and is not re-asked")
            if not changed:
                continue
            if basis == "inferred":
                # Worded as an ASSUMPTION, because that is what it is, and priced anyway.
                part.setdefault("review_flags", []).append(
                    f"{code}: {', '.join(changed)} — INFERRED by {who}{_stamp}. "
                    f"Basis: {source_note}. The drawing does not print this figure; it is "
                    f"priced on the stated assumption so the line is not left empty. Any "
                    f"measurement displaces it — overturn it if you disagree")
            elif basis == "corrected":
                part.setdefault("review_flags", []).append(
                    f"{code}: {', '.join(changed)} — CORRECTED by {who}{_stamp}, OVERRULING "
                    f"the CAD files. Reason: {source_note}. This is the one source that "
                    f"outranks a DXF and the model, claimed deliberately")
            else:
                part.setdefault("review_flags", []).append(
                    f"{code}: {', '.join(changed)} — read off the drawing by {who}{_stamp}"
                    + (f" ({source_note})" if source_note else "")
                    + ". Better than any machine reading of the same sheet, and a DXF flat "
                      "or the model still displaces it — those are what the shop cuts to")
    return report
