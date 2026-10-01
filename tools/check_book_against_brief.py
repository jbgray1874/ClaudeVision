"""Hold a run's saved record against an estimator's brief, and report EVERY pin.

    python tools/check_book_against_brief.py output/json/<job>.json docs/briefs/<job>.facts.json
                                             [--xlsx <book.xlsx>]

The replay harness (tests/replay) asserts a frozen, signed-off record and stops at the first
failure, which is right for a gate and wrong for a review: an estimator re-running a job wants
the whole list — what held, what failed, and the figure behind each. This reads the same
record every surface reads (costed_facts.costed_job) and the same facts format the replay layer
uses, so a brief written here can become a replay pin unchanged once a run is signed off.

GENERIC BY CONSTRUCTION. Nothing in this file knows a job: every number, code and word comes
from the facts file. Structure, never money — rates move.

Keys understood (all optional; the replay keys behave as they do there):
  product_root                   the declared product the record must be built from
  not_set_aside                  identities that must not be set aside outside the product
  quantities                     {code: qty per finished unit}
  exactly_one_line               {words: qty or null} — exactly one line whose code or
                                 description carries these words (a merged pair or a doubled
                                 line both fail)
  required_operations            {code: [op]} routed or charged on the line
  required_operations_incl_pieces{code: [op]} met by the line or its numbered pieces
  forbidden_operations           {code: [op]} not charged on the line
  forbidden_operations_anywhere  [op] charged on no line
  material_charged               [code] material money reaches the line
  no_cut_assemblies              true: no assembly / GA line carries a cutting operation
  forbidden_names_everywhere     [name] no line carries it
  unit_mass_kg                   {expected, tolerance_pct} — sum of the material mass the
                                 costing used x quantity, against the drawn mass
  max_unit_material_mass_kg      {code: kg} — a title-block mass used as material fails here
  min_unit_material_mass_kg      {code: kg}
  quantity_breaks                [q] the book's Quantity Breaks columns (needs --xlsx)

Exit status 0 when every pin holds, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_CUTTING = {"laser_cutting", "laser", "cnc_routing", "punching", "guillotine", "saw",
            "tube_cut"}


def _sq(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


class Result:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, bool, str]] = []

    def add(self, check: str, item: str, ok: bool, detail: str = "") -> None:
        self.rows.append((check, item, bool(ok), detail))

    @property
    def failed(self) -> List[Tuple[str, str, bool, str]]:
        return [r for r in self.rows if not r[2]]


def _lines(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    import costed_facts as cf
    record = cf.costed_job(summary)
    return [l for l in (record.get("lines") or []) if isinstance(l, dict)]


def _ops(line: Optional[Dict[str, Any]], routed: bool = False) -> set:
    if not line:
        return set()
    out = {str(o).lower() for o in (line.get("operations") or [])}
    if routed:
        out |= {str(o).lower() for o in (line.get("route_operations") or [])}
    return out


def _product_root(summary: Dict[str, Any]) -> str:
    for holder in (summary.get("estimate_summary") or {}, summary):
        payload = holder.get("canonical_route_shadow") if isinstance(holder, dict) else None
        if isinstance(payload, dict) and payload.get("product_root"):
            return str(payload["product_root"])
    return ""


def _part_estimates(summary: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    es = summary.get("estimate_summary") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for key in ("canonical_part_estimates", "part_estimates"):
        for p in es.get(key) or []:
            if isinstance(p, dict) and p.get("part_number"):
                out.setdefault(_sq(p["part_number"]), p)
    return out


def _unit_mass(pe: Optional[Dict[str, Any]]) -> Optional[float]:
    if not pe:
        return None
    me = pe.get("material_estimate") or {}
    return _num(me.get("unit_material_mass_kg"))


def _breaks_in_book(xlsx: Path) -> Tuple[List[int], Dict[int, float]]:
    import openpyxl
    wb = openpyxl.load_workbook(str(xlsx), data_only=True, read_only=True)
    name = next((n for n in wb.sheetnames if n.strip().lower() == "quantity breaks"), None)
    if name is None:
        return [], {}
    qtys: List[int] = []
    unit: Dict[int, float] = {}
    for row in wb[name].iter_rows(values_only=True):
        head = str(row[0] or "").strip().lower() if row else ""
        if head == "quantity":
            qtys = [int(v) for v in row[1:] if _num(v) is not None]
        elif head.startswith("unit cost") and qtys:
            for q, v in zip(qtys, row[1:]):
                if _num(v) is not None:
                    unit[q] = float(v)
    return qtys, unit


def check(summary: Dict[str, Any], facts: Dict[str, Any],
          xlsx: Optional[Path] = None) -> Result:
    res = Result()
    lines = _lines(summary)
    by_id: Dict[str, Dict[str, Any]] = {}
    for l in lines:
        by_id.setdefault(_sq(l.get("part_number")), l)
    pes = _part_estimates(summary)

    def find(code: str) -> Optional[Dict[str, Any]]:
        return by_id.get(_sq(code))

    def pieces(code: str) -> List[Dict[str, Any]]:
        stem = _sq(code)
        return [l for k, l in by_id.items()
                if k != stem and re.fullmatch(re.escape(stem) + r"\d{1,2}", k)]

    # ── the product ─────────────────────────────────────────────────────────────
    want_root = facts.get("product_root")
    if want_root:
        got = _product_root(summary)
        res.add("product_root", want_root, _sq(got) == _sq(want_root),
                f"record is built from {got or 'nothing'}")
    _aside = {_sq(e.get("part_number")) for e in (summary.get("set_aside_outside_product")
                                                  or []) if isinstance(e, dict)}
    for code in facts.get("not_set_aside") or []:
        res.add("not_set_aside", code, _sq(code) not in _aside,
                "set aside outside the product" if _sq(code) in _aside else "inside the product")

    # ── quantities ──────────────────────────────────────────────────────────────
    for code, q in (facts.get("quantities") or {}).items():
        line = find(code)
        got = _num(line.get("qty_per_unit")) if line else None
        res.add("quantity", code, got is not None and abs(got - float(q)) < 0.01,
                f"book {got if got is not None else 'no line'} / brief {q:g}")
    for words, q in (facts.get("exactly_one_line") or {}).items():
        key = _sq(words)
        hits = [l for l in lines
                if key in _sq(l.get("part_number")) or key in _sq(l.get("description"))]
        ok = len(hits) == 1
        detail = f"{len(hits)} line(s): " + ", ".join(
            f"{l.get('part_number')} x{l.get('qty_per_unit')}" for l in hits[:4])
        if ok and q is not None:
            got = _num(hits[0].get("qty_per_unit"))
            ok = got is not None and abs(got - float(q)) < 0.01
            detail += f" / brief {q:g}"
        res.add("exactly_one_line", words, ok, detail)

    # ── routes ──────────────────────────────────────────────────────────────────
    for code, ops in (facts.get("required_operations") or {}).items():
        line = find(code)
        got = _ops(line, routed=True)
        for op in ops:
            res.add("required_op", f"{code} {op}", op.lower() in got,
                    "no line" if line is None else f"line carries {sorted(got)}")
    for code, ops in (facts.get("required_operations_incl_pieces") or {}).items():
        group = [l for l in [find(code)] + pieces(code) if l]
        got = set().union(*(_ops(l, routed=True) for l in group)) if group else set()
        for op in ops:
            res.add("required_op", f"{code} (or its pieces) {op}", op.lower() in got,
                    f"{[l.get('part_number') for l in group]} carry {sorted(got)}")
    for code, ops in (facts.get("forbidden_operations") or {}).items():
        line = find(code)
        got = _ops(line)
        for op in ops:
            res.add("forbidden_op", f"{code} {op}", op.lower() not in got,
                    "no line (see quantity)" if line is None else
                    ("charged" if op.lower() in got else "not charged"))
    for op in facts.get("forbidden_operations_anywhere") or []:
        guilty = [l.get("part_number") for l in lines if op.lower() in _ops(l)]
        res.add("forbidden_anywhere", op, not guilty, f"charged on {guilty}" if guilty else "")
    if facts.get("no_cut_assemblies"):
        guilty = [l.get("part_number") for l in lines
                  if (str(l.get("kind") or "").lower() == "assembly"
                      or _sq(l.get("part_number")).endswith("GA"))
                  and _ops(l) & _CUTTING]
        res.add("no_cut_assemblies", "assemblies", not guilty,
                f"cut: {guilty}" if guilty else "no assembly is cut")

    # ── material ────────────────────────────────────────────────────────────────
    for code in facts.get("material_charged") or []:
        line = find(code)
        money = None
        if line:
            money = _num(line.get("charged_unit_gbp"))
            if money is None:
                money = _num(line.get("engine_unit_gbp"))
        res.add("material_charged", code, bool(money and money > 0),
                "no line" if line is None else f"£{money}")
    for name in facts.get("forbidden_names_everywhere") or []:
        hit = [l.get("part_number") for l in lines if _sq(name) == _sq(l.get("part_number"))]
        res.add("forbidden_name", name, not hit, f"on {hit}" if hit else "")

    # ── mass ────────────────────────────────────────────────────────────────────
    for code, kg in (facts.get("max_unit_material_mass_kg") or {}).items():
        m = _unit_mass(pes.get(_sq(code)))
        res.add("max_mass", code, m is None or m <= float(kg),
                f"material mass {m} kg (limit {kg})")
    for code, kg in (facts.get("min_unit_material_mass_kg") or {}).items():
        m = _unit_mass(pes.get(_sq(code)))
        res.add("min_mass", code, m is not None and m >= float(kg),
                f"material mass {m} kg (floor {kg})")
    _um = facts.get("unit_mass_kg") or {}
    if _um.get("expected"):
        total, counted = 0.0, 0
        for l in lines:
            if str(l.get("kind") or "").lower() == "assembly":
                continue
            m = _unit_mass(pes.get(_sq(l.get("part_number"))))
            q = _num(l.get("qty_per_unit")) or 0.0
            if m:
                total += m * q
                counted += 1
        exp, tol = float(_um["expected"]), float(_um.get("tolerance_pct") or 25)
        res.add("unit_mass", f"{exp:g} kg", abs(total - exp) <= exp * tol / 100.0,
                f"book's material mass {total:.2f} kg over {counted} line(s) "
                f"(±{tol:g}%; blanks include the cut-outs, bought items weigh nothing here)")

    # ── breaks ──────────────────────────────────────────────────────────────────
    want = facts.get("quantity_breaks")
    if want:
        if xlsx is None:
            res.add("quantity_breaks", str(want), False, "pass --xlsx <book> to check")
        else:
            got, unit = _breaks_in_book(xlsx)
            res.add("quantity_breaks", str(want), sorted(got) == sorted(int(q) for q in want),
                    f"book columns {got}; unit £ " + ", ".join(
                        f"{q}: {unit[q]:.2f}" for q in got if q in unit))
    return res


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("summary", type=Path)
    ap.add_argument("facts", type=Path)
    ap.add_argument("--xlsx", type=Path, default=None)
    a = ap.parse_args(list(argv) if argv is not None else None)
    summary = json.loads(a.summary.read_text(encoding="utf-8"))
    facts = json.loads(a.facts.read_text(encoding="utf-8"))
    res = check(summary, facts, a.xlsx)
    width = max((len(r[1]) for r in res.rows), default=10)
    for check_name, item, ok, detail in res.rows:
        print(f"{'PASS' if ok else 'FAIL'}  {check_name:<20} {item:<{width}}  {detail}")
    n_fail = len(res.failed)
    print(f"\n{len(res.rows) - n_fail} held, {n_fail} failed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
