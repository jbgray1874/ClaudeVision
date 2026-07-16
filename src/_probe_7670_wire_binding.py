#!/usr/bin/env python3
r"""
_probe_7670_wire_binding.py  —  READ-ONLY.

THE BUG (document_builder.py:957)

    _ws_text = " ".join(str(_get_page_text(pg)) for pg in summary.get("pages", []))
    _wire_sched = _parse_wire_schedule(_ws_text)
    if _wire_sched:
        part["wire_schedule"] = _wire_sched          # <-- the WHOLE schedule, onto ONE part

The schedule is parsed from EVERY PAGE JOINED TOGETHER, then attached to whichever part is
currently in the loop. On 7670 that was parts[3] — the RYOBI GREEN powder bought-in record
(part_number: None). All three wire rows landed there. The three parts they actually
describe — 7670-01-001 / -002 / -003 — got nothing, fell through to stock_form "unknown",
and were rendered in the BOM at their LABOUR cost (£25.18 / £12.27 / £27.07).

The extraction is RIGHT. The engine read 4.0mm gauge and 975.4mm off a PDF; Tim's main
frame is 4mm / 976mm. PDF-only extraction WORKS. The plumbing does not.

WHY I CANNOT WRITE THE FIX YET

The parsed rows come out as:

    {"description": "4.0mm wire", "qty_loops": 1, "gauge_mm": 4.0, "length_mm": 975.4, ...}

"4.0mm wire" is not a part name. There is nothing in the parsed output that says which row
belongs to 7670-01-001 and which to -003. Either:

  (a) the drawing's schedule table DOES carry item numbers / part names, and _WIRE_SCHED_RE
      is discarding them  -> fix the regex, bind by item number. Deterministic, safe.

  (b) the table carries no identifiers at all -> we would have to bind by ORDER or by
      matching lengths against per-part geometry. Both are guesses, and a guess that
      silently mis-assigns a 976mm wire to the wrong part is worse than no assignment.

This probe prints the RAW TABLE so the binding is designed from evidence rather than
invented. That distinction has cost us three hours today already.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_7670_wire_binding.py
"""
from __future__ import annotations
import glob, json, os, re, sys

JSON_DIR = r"C:\ClaudeVision\output\json"
TEXT_KEYS = ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview")


def page_text(pg):
    out = []
    rt = pg.get("region_text") or {}
    if isinstance(rt, dict):
        out += [str(v) for v in rt.values() if v]
    for k in TEXT_KEYS:
        if pg.get(k):
            out.append(str(pg[k]))
    return " ".join(out)


def main():
    cands = glob.glob(os.path.join(JSON_DIR, "*7670*.json"))
    if not cands:
        sys.exit("no 7670 JSON")
    path = max(cands, key=os.path.getmtime)
    data = json.load(open(path, "r", encoding="utf-8"))

    print("=" * 100)
    print("TIM'S GROUND TRUTH — what the schedule SHOULD map to")
    print("=" * 100)
    print("  7670-01-001  MAIN FRAME     4mm wire   976mm  x1   -> £0.15")
    print("  7670-01-002  HOOK           4mm wire   234mm  x2   -> £0.07")
    print("  7670-01-003  BOTTOM FRAME   4mm wire   425mm  x1   -> £0.07")
    print("                                        ------")
    print("                              total     1635mm        engine parsed: 1633.6mm")

    # ---------- 1. what did the parser actually produce? ----------
    print("\n" + "=" * 100)
    print("1. THE PARSED SCHEDULE (full, untruncated) — currently on the WRONG record")
    print("=" * 100)
    for p in (data.get("parts") or []):
        if p.get("wire_schedule"):
            print(f"\n  attached to: part_number={p.get('part_number')!r}")
            print(f"               description={str(p.get('description'))[:70]!r}")
            print(f"               page_roles={p.get('page_roles')!r}   pages={p.get('pages')!r}")
            print(f"               ^^ THIS IS THE POWDER LINE, not a wire part\n")
            for r in p["wire_schedule"]:
                print(f"      {json.dumps(r, default=str)}")
            print(f"\n      wire_total_length_mm: {p.get('wire_total_length_mm')}")

    # ---------- 2. the parts that SHOULD have got it ----------
    print("\n" + "=" * 100)
    print("2. THE THREE REAL PARTS — what they were left with")
    print("=" * 100)
    for p in (data.get("parts") or []):
        pn = str(p.get("part_number") or "")
        if not pn.startswith("7670-01-0"):
            continue
        me = p.get("material_estimate") or {}
        print(f"\n  {pn}  {p.get('description')}")
        print(f"      pages              {p.get('pages')!r}")
        print(f"      wire_schedule      {p.get('wire_schedule', '<none>')!r}")
        print(f"      _wire_part_override{p.get('_wire_part_override', '<none>')!r}")
        print(f"      stock_form         {me.get('stock_form')!r}")
        print(f"      thickness_mm       {p.get('normalized_thickness_mm')!r}  <- the 4mm GAUGE, read as sheet thickness")

    # ---------- 3. THE RAW TABLE — the whole point of this probe ----------
    print("\n" + "=" * 100)
    print("3. RAW PAGE TEXT AROUND EVERY WIRE/DIA MENTION")
    print("   >>> Does the table carry ITEM NUMBERS or PART NAMES? <<<")
    print("   If it does, we bind deterministically by item number.")
    print("   If it does not, binding by order is a GUESS and we should not ship it.")
    print("=" * 100)
    for pg in (data.get("pages") or []):
        num = pg.get("page_number") or pg.get("page")
        role = pg.get("page_role")
        role = role.get("primary_role") if isinstance(role, dict) else role
        txt = page_text(pg)
        if not re.search(r"WIRE|DIA|\bMM\b", txt, re.IGNORECASE):
            continue
        print(f"\n  ---- page {num}  (role={role}) ----")
        for m in re.finditer(r".{0,110}(?:WIRE|\d\s*mm\s*DIA).{0,110}", txt, re.IGNORECASE):
            frag = " ".join(m.group(0).split())
            print(f"      ...{frag}...")

    # ---------- 4. lengths that match Tim, wherever they appear ----------
    print("\n" + "=" * 100)
    print("4. WHERE DO TIM'S LENGTHS (976 / 234 / 425) APPEAR IN THE TEXT?")
    print("   If each length sits on its own DETAIL page, we can bind by PAGE — the same")
    print("   per-part gate that fixed the 1310 stud this morning.")
    print("=" * 100)
    for pg in (data.get("pages") or []):
        num = pg.get("page_number") or pg.get("page")
        role = pg.get("page_role")
        role = role.get("primary_role") if isinstance(role, dict) else role
        txt = page_text(pg)
        hits = []
        for target in ("975", "976", "234", "233", "425", "424"):
            if target in txt:
                hits.append(target)
        print(f"  page {num} (role={role}): {hits if hits else '—'}")

    print("""
====================================================================================
THE DECISION THIS PROBE MAKES FOR US

  If section 3 shows the schedule table carries ITEM NUMBERS or PART NAMES:
      -> Fix _WIRE_SCHED_RE to capture them. Bind row -> part deterministically.
         Safe, and it generalises to every future wire job.

  If section 4 shows each length sits on its OWN DETAIL PAGE:
      -> Bind by page, exactly as the 1310 stud fix does: each part reads only the
         pages it owns. Also safe.

  If NEITHER:
      -> There is no honest way to bind rows to parts. We do NOT bind by order and hope.
         We attach the schedule to the JOB, flag it loudly for the estimator, and put a
         "wire schedule must identify its part" line in the Design recommendations. A
         wrong 976mm wire on the wrong part is a silent error — strictly worse than an
         admitted gap.
====================================================================================
""")


if __name__ == "__main__":
    main()
