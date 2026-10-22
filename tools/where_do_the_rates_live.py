"""Every price, rate and shop constant in the engine, and which file owns it.

    "all the prices / calculations also need to be in the s/sheet itself or in one easily
     modified config file. not scattered around all over the code"
                                                    — James Gray, SDI, 14 Sep 2026

This is the inventory that makes that instruction checkable instead of a feeling. Run it and
you get every module-level rate constant and rate table outside config.py, and — the part
that actually costs money — every place two files hold the SAME rate under DIFFERENT values.

The duplicates are not a tidiness problem. They are how one job gets costed two ways:

  * FOAMEX is 550 kg/m3 in config and 500 in the two modules that work out what a pallet
    weighs. PLYWOOD is 680 against 600. A density feeds mass, mass feeds freight.
  * The powder consumption figure is 0.20 kg/m2 in one config constant and 0.1667 in
    another (6 m2/kg), twenty per cent apart, both live.
  * Wire is £1500/tonne in config's workbook defaults and £1600 in wire_costing, whose own
    comment says "Engine currently holds 1500 — stale". The 7332-01 template says 1600.

None of those is a bug anybody wrote. Each is two people being right in two files.

    python tools/where_do_the_rates_live.py            # the inventory
    python tools/where_do_the_rates_live.py --clashes  # only what disagrees
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# Working files, dead ends and superseded copies are not the shipping engine. A leading
# underscore is this tree's convention for a probe or a one-shot patch script.
SKIP_FILE = re.compile(r"^_|_old\.py$|backup|baclkup|estimator1\.py$|^diag_|^test_")

# What makes a name a RATE rather than an index, a column or a page margin. Deliberately
# generous: a false positive costs one line of reading, a false negative costs an audit.
RATE_NAME = re.compile(
    r"(gbp|price|cost|rate|speed|per_hour|per_kg|per_m2|per_sheet|per_tonne|tonne|charge|"
    r"margin|markup|minute|_min\b|_sec\b|setup|scrap|waste|yield|hourly|uplift|multiplier|"
    r"factor|density|coverage|card|bars_per|throughput|per_item|items_per|allowance)", re.I)

# Names that match the pattern and are not money: layout, tolerances and sort keys.
NOT_A_RATE = re.compile(
    r"^(_MARGIN|_ABS_TOL_GBP|_PER_ROW_TOL_GBP|_TOLERANCE_TABLE|cost_cols_present)", re.I)


def _count_numbers(node: Any) -> int:
    # `x: float` with no value is an AnnAssign whose .value is None — legal, and nothing to
    # count. Walking it raises, which took the whole audit down.
    if node is None:
        return 0
    return sum(1 for x in ast.walk(node)
               if isinstance(x, ast.Constant)
               and isinstance(x.value, (int, float)) and not isinstance(x.value, bool))


def inventory() -> List[Tuple[str, int, str, int]]:
    """(relative path, line, constant name, how many numbers it holds)."""
    out: List[Tuple[str, int, str, int]] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "config.py" \
                or SKIP_FILE.search(path.name):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                            # noqa: BLE001
            continue
        # EVERY SCOPE, NOT ONLY THE MODULE'S.
        #
        # The first version of this walked tree.body alone, on the reasoning that a real
        # shared constant lives at module level. It does not. The single most consequential
        # rate table in the engine — _THROUGHPUT_DEFAULTS, thirty-odd operations in
        # pieces-per-hour, the thing that actually sets the Rate Per Hour column an
        # estimator reads — is declared INSIDE populate_workbook(), and the audit reported
        # wb_populate.py as holding no rates at all.
        #
        # A rate does not stop being a rate because it is indented. James Gray asked "is the
        # throughput not on the sheets? the config." and the honest answer was neither — and
        # the tool built to answer exactly that question could not see it.
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if not isinstance(t, ast.Name):
                    continue
                if not RATE_NAME.search(t.id) or NOT_A_RATE.match(t.id):
                    continue
                # A RATE IS WRITTEN DOWN. A working variable is worked out.
                #
                # `_cost = area * rate * qty` matches the name pattern and is not a rate —
                # it is the arithmetic that USES one, and counting it buries the thirty
                # numbers that matter under three hundred that do not. So the value has to
                # be a literal: a number, or a table of them. That is what "the rate lives
                # here" means, and it is what can be moved to config or to the sheet.
                try:
                    _lit = ast.literal_eval(node.value)
                except Exception:                                    # noqa: BLE001
                    continue
                # A RATE OF ZERO IS NOT A RATE. `priced = 0` and `credible_cost = 0.0` are
                # accumulators being opened, and both match the name pattern. A rate that
                # really is held at zero is a deliberate commercial decision and belongs in
                # config with a note, which is where PACKAGING and DELIVERY already are.
                if isinstance(_lit, (int, float)) and not isinstance(_lit, bool) \
                        and float(_lit) == 0.0:
                    continue
                n = _count_numbers(node.value)
                if n:
                    out.append((str(path.relative_to(ROOT)), node.lineno, t.id, n))
    return out


# ── the clashes, which are the part that costs money ─────────────────────────────────────
#
# Checked by IMPORTING and comparing values, not by reading text: two tables can be written
# differently and mean the same thing, and two written identically can have diverged by one
# key. Each entry names what has to be true and who rules if it is not.

def clashes() -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []

    def _add(what, a_name, a, b_name, b, whose, why):
        found.append({"what": what, "a": (a_name, a), "b": (b_name, b),
                      "whose_call": whose, "why_it_matters": why})

    import config                                                     # noqa: PLC0415

    # 1. Material density — three tables, two of them identical to each other.
    try:
        import commercial_lines, palletising                          # noqa: PLC0415
        mod = commercial_lines._DENSITY_KG_M3
        if mod != palletising._DENSITY_KG_M3:
            _add("material density (module copies)",
                 "commercial_lines._DENSITY_KG_M3", "…",
                 "palletising._DENSITY_KG_M3", "…",
                 "engineering", "two copies of one table have drifted apart")
        cfg = config.MATERIAL_DENSITY_KG_PER_M3
        for key in sorted(set(mod) & set(cfg)):
            if abs(float(mod[key]) - float(cfg[key])) > 1e-9:
                _add(f"density of {key}",
                     "config.MATERIAL_DENSITY_KG_PER_M3", cfg[key],
                     "commercial_lines/palletising._DENSITY_KG_M3", mod[key],
                     "James / engineering",
                     "density feeds mass; mass feeds pallet count and freight")
    except Exception as exc:                                          # noqa: BLE001
        _add("material density", "import", str(exc), "—", "—", "—", "could not compare")

    # 2. Powder consumption — both figures are in config, twenty per cent apart.
    try:
        a = float(config.POWDER_KG_PER_M2)
        b = float(config.POWDER_COSTING_POLICY["kg_per_m2"])
        if abs(a - b) > 1e-6:
            _add("powder consumed per m2",
                 "config.POWDER_KG_PER_M2", a,
                 "config.POWDER_COSTING_POLICY['kg_per_m2']", b,
                 "Tim / James",
                 f"{abs(a - b) / max(a, b):.0%} apart on every powder-coated job")
    except Exception:                                                 # noqa: BLE001
        pass

    # 3. Powder price per kilo — the policy's figure against a module's historical standard.
    try:
        import sheet_steel_costing                                    # noqa: PLC0415
        a = float(config.POWDER_COST_PER_KG)
        b = float(sheet_steel_costing.POWDER_PRICE_GBP_PER_KG)
        if abs(a - b) > 1e-9:
            _add("powder £/kg",
                 "config.POWDER_COST_PER_KG", a,
                 "sheet_steel_costing.POWDER_PRICE_GBP_PER_KG", b,
                 "James",
                 "the module's own comment says reading it as a competing figure has cost "
                 "an hour more than once")
    except Exception:                                                 # noqa: BLE001
        pass

    # 4. Wire per tonne — and the workbook template is a third opinion.
    try:
        import wire_costing                                           # noqa: PLC0415
        a = float(config.WORKBOOK_INPUT_DEFAULTS["wire_cost_per_tonne_gbp"])
        b = float(wire_costing.WIRE_RATE_PER_TONNE_GBP)
        if abs(a - b) > 1e-9:
            _add("wire £/tonne",
                 "config.WORKBOOK_INPUT_DEFAULTS['wire_cost_per_tonne_gbp']", a,
                 "wire_costing.WIRE_RATE_PER_TONNE_GBP", b,
                 "James",
                 "wire_costing's own comment calls the config figure stale, and 7332-01's "
                 "own Estimate sheet cell L3 shipped 1600 — so the config default is the "
                 "odd one out of three")
    except Exception:                                                 # noqa: BLE001
        pass

    # 5. Sheet steel per tonne — config against what the sheet that shipped actually says.
    # Not comparing two modules: comparing the engine's default with the number an
    # estimator read on the deliverable. 7332-01's Estimate!L5 shipped 900.
    try:
        a = float(config.WORKBOOK_INPUT_DEFAULTS["sheet_steel_cost_per_tonne_gbp"])
        if abs(a - 900.0) > 1e-9:
            _add("sheet steel £/tonne",
                 "config.WORKBOOK_INPUT_DEFAULTS['sheet_steel_cost_per_tonne_gbp']", a,
                 "7332-01 Estimate!L5, as shipped 14 Sep", 900.0,
                 "James",
                 "the default and the sheet disagree; whichever the template wins with, "
                 "the loser is a number nobody is maintaining")
    except Exception:                                                 # noqa: BLE001
        pass

    return found


def duplicated_but_agreeing() -> List[Tuple[str, ...]]:
    """One rate, several names, same value — today.

    Not a clash and not harmless: these are the clashes of next year. Each is a place where
    changing the team's 4% means finding four files, and finding three of them looks exactly
    like finding four until a job is costed.
    """
    out: List[Tuple[str, ...]] = []
    try:
        import config, sheet_steel_costing, wire_costing              # noqa: PLC0415
        scrap = {"config.SCRAP_PERCENTAGE": float(config.SCRAP_PERCENTAGE),
                 "config.WORKBOOK_INPUT_DEFAULTS['scrap_pct']":
                     float(config.WORKBOOK_INPUT_DEFAULTS["scrap_pct"]) / 100.0,
                 "sheet_steel_costing.POWDER_SCRAP_PERCENT":
                     float(sheet_steel_costing.POWDER_SCRAP_PERCENT),
                 "wire_costing.WIRE_SCRAP": float(wire_costing.WIRE_SCRAP)}
        if len(set(scrap.values())) == 1:
            out.append(("scrap %", str(next(iter(scrap.values()))), *sorted(scrap)))
        import commercial_lines, palletising                          # noqa: PLC0415
        if commercial_lines._DENSITY_KG_M3 == palletising._DENSITY_KG_M3:
            out.append(("material density table", "18 keys, identical",
                        "commercial_lines._DENSITY_KG_M3",
                        "palletising._DENSITY_KG_M3"))
        import document_builder, extractor_patterns                   # noqa: PLC0415
        if document_builder._TOLERANCE_TABLE_VALUES == \
                extractor_patterns._TOLERANCE_TABLE_VALUES:
            out.append(("tolerance table", "identical",
                        "document_builder._TOLERANCE_TABLE_VALUES",
                        "extractor_patterns._TOLERANCE_TABLE_VALUES"))
        import invariants, blank_credibility                          # noqa: PLC0415
        if float(invariants._CUT_PATH_ABSURDITY_MARGIN) == \
                float(blank_credibility.CUT_PATH_ABSURDITY_MARGIN):
            out.append(("cut-path absurdity margin",
                        str(blank_credibility.CUT_PATH_ABSURDITY_MARGIN),
                        "invariants._CUT_PATH_ABSURDITY_MARGIN",
                        "blank_credibility.CUT_PATH_ABSURDITY_MARGIN"))
    except Exception:                                                 # noqa: BLE001
        pass
    return out


def against_the_template() -> List[str]:
    """The code's rate card against the Estimate template's own rate rows.

    THE SPREADSHEET IS ALLOWED TO BE THE OWNER — that is half of what was asked for, and for
    the £/hr card it already is: sheet_steel_costing._RATE_CARD_AS_READ_OFF_THE_TEMPLATE
    names the rows it was read from and every figure in it matches what 7332-01 shipped.

    What was missing is any check that it STILL matches. config.py already records one
    instance of this going wrong, in its own words: "THE TEMPLATE MOVED AND THIS CONSTANT DID
    NOT." A transcription nobody re-reads is a copy that is right until the day it is not,
    and there is no symptom in between.

    Matched by the operation's NAME, not by cell address, so inserting a row in the template
    cannot make this silently compare the wrong things. Returns human lines; an absent
    template is reported, never guessed around.
    """
    out: List[str] = []
    try:
        import config                                                 # noqa: PLC0415
        import sheet_steel_costing                                    # noqa: PLC0415
        from openpyxl import load_workbook                            # noqa: PLC0415
    except Exception as exc:                                          # noqa: BLE001
        return [f"cannot compare: {exc}"]

    tpl = Path(getattr(config, "AI_ESTIMATE_XLSX_TEMPLATE", "") or "")
    if not tpl.is_file():
        return [f"template not on this machine: {tpl}",
                "run this on the box that holds SPREADSHEETS_DIR — the comparison needs the "
                "live Blank Estimate Sheet, and reporting a guess instead would be worse "
                "than reporting nothing."]

    card = sheet_steel_costing._RATE_CARD_AS_READ_OFF_THE_TEMPLATE
    wanted = {str(k).strip().upper(): float(v[0]) for k, v in card.items()}
    seen: Dict[str, float] = {}
    wb = load_workbook(tpl, data_only=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            label = None
            for c in row:
                if isinstance(c.value, str) and c.value.strip().upper() in wanted:
                    label = c.value.strip().upper()
                    break
            if label is None:
                continue
            for c in row:                       # the first money-shaped number on that row
                if isinstance(c.value, (int, float)) and 1.0 < float(c.value) < 10000.0:
                    seen.setdefault(label, float(c.value))
                    break
    for name, coded in sorted(wanted.items()):
        live = seen.get(name)
        if live is None:
            out.append(f"  {name:28} coded {coded:>10.4f}   NOT FOUND in the template")
        elif abs(live - coded) > 0.005:
            out.append(f"  {name:28} coded {coded:>10.4f}   template {live:>10.4f}   "
                       f"DIFFERS")
    if not out:
        out.append(f"  all {len(wanted)} rate-card figures match {tpl.name}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--clashes", action="store_true",
                    help="only the rates two files disagree about")
    ap.add_argument("--vs-template", action="store_true",
                    help="compare the coded rate card against the live Estimate template")
    args = ap.parse_args()

    if args.vs_template:
        print("THE CODED RATE CARD AGAINST THE ESTIMATE TEMPLATE")
        print("=" * 78)
        for line in against_the_template():
            print(line)
        print()
        return 0

    bad = clashes()
    if not args.clashes:
        rows = inventory()
        by_file: Counter = Counter()
        detail: Dict[str, List[Tuple[int, str, int]]] = defaultdict(list)
        for f, ln, name, n in rows:
            by_file[f] += n
            detail[f].append((ln, name, n))
        print("RATES DEFINED OUTSIDE config.py")
        print("=" * 78)
        print(f"{len(rows)} constants and tables, {sum(n for *_, n in rows)} numbers, "
              f"{len(by_file)} modules\n")
        for f, total in by_file.most_common():
            print(f"{total:5d} numbers   {f}")
            for ln, name, n in sorted(detail[f]):
                print(f"              L{ln:<6} {name}  ({n})")
        print()

    print("RATES TWO FILES DISAGREE ABOUT")
    print("=" * 78)
    if not bad:
        print("none — every duplicated rate holds the same value.")
    for c in bad:
        print(f"\n  {c['what']}")
        print(f"      {c['a'][0]} = {c['a'][1]}")
        print(f"      {c['b'][0]} = {c['b'][1]}")
        print(f"      whose call : {c['whose_call']}")
        print(f"      matters    : {c['why_it_matters']}")
    print()

    same = duplicated_but_agreeing()
    if same:
        print("ONE RATE, SEVERAL NAMES — agreeing today")
        print("=" * 78)
        print("Change the team's figure and you have to find all of these. Finding three of "
              "four\nlooks exactly like finding four, until a job is costed.\n")
        for row in same:
            print(f"  {row[0]}  (= {row[1]})")
            for where in row[2:]:
                print(f"      {where}")
        print()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
