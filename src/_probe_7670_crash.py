#!/usr/bin/env python3
r"""
_probe_7670_crash.py  —  READ-ONLY (writes only a throwaway xlsx to %TEMP%).

wb_populate died on 7670 and main.py swallowed the traceback:

    [wb_populate] ⚠ labour: 0 grouped row(s)
    [wb_populate] failed (sequence item 1: expected str instance, dict found)
                  — falling back to xlsx_output

"sequence item 1: expected str instance, dict found" is a str.join() being handed a dict.
The labour flag printed FIRST, so the labour pass completed (with zero groups) — the crash
is downstream of it. Most likely _append_ai_sheets, but that is a guess and guesses have
cost us twice today. This gets the real line number.

It also dumps what the engine actually understood about the three parts, because the run
output raises a much bigger question than the crash:

    THE DRAWINGS SAY RAW. TIM POWDER-COATS IT ORANGE.
      Tim: Powder171-Deep Orange £0.40 + P.Coat £1.92 = £2.32 of a £6.74 job
      Engine: finish detected (RAW) on all three parts -> powder correctly dropped

    THE WHOLE JOB IS 4mm WIRE. The engine sees MILD STEEL sheet.
      Tim: three wire parts, 976mm / 234mm / 425mm at 4mm gauge, 10,140 m/tonne
      Engine: no DXF (0%), no bar schedule, so no route to see any of it

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_7670_crash.py
"""
from __future__ import annotations
import glob, json, os, sys, traceback, tempfile

JSON_DIR = r"C:\ClaudeVision\output\json"


def main():
    cands = glob.glob(os.path.join(JSON_DIR, "*7670*.json"))
    if not cands:
        sys.exit("no 7670 JSON found — run the job first")
    path = max(cands, key=os.path.getmtime)
    print("=" * 96)
    print(os.path.basename(path))
    print("=" * 96)
    summary = json.load(open(path, "r", encoding="utf-8"))

    # ---------- 1. THE CRASH ----------
    print("\n--- 1. REAL TRACEBACK ---")
    try:
        import wb_populate
    except Exception as e:
        sys.exit(f"cannot import wb_populate: {e}")

    out = os.path.join(tempfile.gettempdir(), "_7670_crash_probe.xlsx")
    fn = None
    for name in ("populate_workbook", "populate", "write_estimate", "main"):
        if callable(getattr(wb_populate, name, None)):
            fn = getattr(wb_populate, name)
            print(f"  calling wb_populate.{name}()")
            break
    if fn is None:
        print("  !! could not find the entry point — functions available:")
        for n in dir(wb_populate):
            if not n.startswith("_") and callable(getattr(wb_populate, n)):
                print(f"       {n}")
    else:
        try:
            fn(summary, out)
            print("  (no crash this time — the failure may depend on args main.py passes)")
        except TypeError:
            try:
                fn(summary)
                print("  (no crash)")
            except Exception:
                print("\n" + traceback.format_exc())
        except Exception:
            print("\n" + traceback.format_exc())

    # ---------- 2. WHAT DID THE ENGINE SEE? ----------
    print("\n--- 2. WHAT THE ENGINE UNDERSTOOD ABOUT THE THREE PARTS ---")
    print("    (Tim: 3 WIRE parts @ 4mm gauge — main frame 976mm, back wire 234mm x2,")
    print("     bottom frame 425mm — powder coated Deep Orange)\n")
    pes = summary.get("part_estimates") or []
    for p in pes:
        me = p.get("material_estimate") or {}
        le = p.get("labour_estimate") or {}
        print(f"  {str(p.get('part_number')):<16} {str(p.get('description'))[:44]}")
        print(f"      material        {p.get('normalized_material')!r}")
        print(f"      thickness_mm    {p.get('normalized_thickness_mm')!r}")
        print(f"      stock_form      {me.get('stock_form')!r}")
        print(f"      cost_method     {me.get('cost_method')!r}")
        print(f"      unit_material   {me.get('unit_material_cost_gbp')!r}")
        print(f"      ops             {list((le.get('costs_gbp') or {}).keys())}")
        print(f"      _bar_recognised {p.get('_bar_recognised')!r}")
        print()

    print("--- 3. FINISH — the drawings say RAW, Tim coats it ORANGE ---")
    for mp in ((summary.get("manufacturing_writeup") or {}).get("parts") or []):
        print(f"  {str(mp.get('part_number')):<16} "
              f"normalized_finish={mp.get('normalized_finish')!r}  "
              f"surface_finishes={mp.get('surface_finishes')!r}")

    print("\n--- 4. PAGES / FILE TYPES (DWG-only pack: ezdxf cannot read DWG) ---")
    for pg in (summary.get("pages") or []):
        _r = pg.get("page_role")
        _r = _r.get("primary_role") if isinstance(_r, dict) else _r
        print(f"  page {pg.get('page_number') or pg.get('page')}  role={_r}")
    for k in ("dxf_files", "source_files", "files", "drawings"):
        if summary.get(k):
            print(f"  {k}: {summary[k]}")

    print("""
====================================================================================
WHAT THIS JOB IS REALLY TELLING US — bigger than the crash

1. THE PACK HAS NO DXF. Only DWG + one PDF. ezdxf cannot read DWG, so the engine gets
   ZERO geometry. Credibility 9%, DXF on 0% of parts. The gate is right to refuse.

2. THE DRAWINGS SAY RAW. Tim charges £2.32 of powder + P.Coat — a third of the job.
   Our powder gate honoured the drawing and dropped it. THE GATE IS CORRECT; the
   DRAWING is wrong (or the finish is only on the GA/PDF). This is a Design finding.

3. THE WHOLE JOB IS 4mm WIRE. The engine read MILD STEEL sheet. Without a DXF or a bar
   schedule it has no route to know otherwise — which is exactly the argument for a
   MATERIAL FORM field in the title block.

4. TIM WRITES ROBOMAC AND SPOTWELD PER PART, NOT PER JOB:
       Robomac  main frame   qty 1  100/hr
       Robomac  back wire    qty 2  450/hr
       Robomac  bottom frame qty 1  300/hr
       Spotweld buttweld     qty 1  150/hr
       Spotweld spotweld     qty 1   45/hr
   Every wire form is a different bend program = a different setup. My grouping patch
   collapses Robomac and Spotweld to ONE ROW PER JOB. THAT IS WRONG and it would
   silently UNDER-charge this job. It needs correcting before the next wire job.

   (P.Coat as one row per job, and pack as one row qty 1, are CONFIRMED right by this
   sheet: Tim writes exactly one of each.)

5. FOUR MORE TEMPLATE DEFAULTS ARE WRONG:
       wire £/tonne     Tim £1,500   template £1,600
       steel £/tonne    Tim £800     template £900
       pack setup       Tim 5 min    template 15 min
       P.Coat/hr        Tim 1,276    default 458   <- small wire parts hang many-per-bar
                                                      and coat far faster than sheet
====================================================================================
""")


if __name__ == "__main__":
    main()
