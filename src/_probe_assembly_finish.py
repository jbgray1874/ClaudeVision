#!/usr/bin/env python3
r"""
_probe_assembly_finish.py  —  READ-ONLY.

THE QUESTION (raised correctly): "SEE ASSEMBLY DRAWING" is not missing information — it is
a POINTER. So: does the assembly drawing actually STATE the finish?

  * If YES -> the pointer resolves. We cost it, grounded entirely in the drawing. The
    engine failing to follow the pointer is an EXTRACTION BUG, not a costing judgement.

  * If NO  -> we genuinely cannot know, and we must NOT invent it. We flag it loudly as a
    DRAWING DEFECT and tell Design: a detail that says "see assembly" against an assembly
    that specifies no finish is an unanswerable drawing.

Nothing gets guessed either way. This probe just reads what the drawings already say.

Prints, for every page of 1282 and 1310:
    page number, role, part numbers on it, and EVERY finish-bearing phrase found in the
    page text (POWDER / COAT / RAL / FINISH / PAINT / RAW / GALV / ZINC / ANODIS / PLATE).

Usage:
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_assembly_finish.py
"""
from __future__ import annotations
import json, glob, os, re

JSON_DIR = r"C:\ClaudeVision\output\json"
JOBS = ["*1282*", "*1310*"]

FINISH_RE = re.compile(
    r"[^\n]{0,60}(?:POWDER\s*COAT\w*|P\.?\s?COAT|RAL\s*\d{3,4}|SURFACE\s*FINISH|"
    r"\bFINISH\b|\bPAINT\w*|\bRAW\b|GALVANIS\w*|ZINC|ANODIS\w*|SEE\s+ASSEMBLY)[^\n]{0,60}",
    re.IGNORECASE,
)

TEXT_KEYS = ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview")


def page_text(pg):
    for k in TEXT_KEYS:
        v = pg.get(k)
        if v:
            return str(v)
    rt = pg.get("region_text") or {}
    if isinstance(rt, dict):
        return " ".join(str(v) for v in rt.values() if v)
    return ""


def role_of(pg):
    r = pg.get("page_role")
    if isinstance(r, dict):
        return str(r.get("primary_role") or "?")
    return str(r or "?")


def main():
    print("ASSEMBLY-FINISH PROBE  (read-only)")
    print("Does the assembly drawing actually STATE the finish that the details point to?\n")

    for pat in JOBS:
        cands = glob.glob(os.path.join(JSON_DIR, pat + ".json"))
        if not cands:
            print(f"!! no JSON matching {pat}")
            continue
        path = max(cands, key=os.path.getmtime)

        print("=" * 100)
        print(os.path.basename(path))
        print("=" * 100)

        data = json.load(open(path, "r", encoding="utf-8"))
        pages = data.get("pages") or []

        for pg in pages:
            num = pg.get("page_number") or pg.get("page") or "?"
            role = role_of(pg)
            pns = pg.get("part_numbers") or pg.get("parts") or []
            pns_s = ", ".join(str(x) for x in pns)[:60]

            txt = page_text(pg)
            hits = []
            seen = set()
            for m in FINISH_RE.finditer(txt):
                s = " ".join(m.group(0).split())
                key = s.upper()[:50]
                if key in seen:
                    continue
                seen.add(key)
                hits.append(s)

            star = "  <<< ASSEMBLY" if role.lower().startswith("assembl") else ""
            print(f"\n  --- page {num}  role={role}{star}")
            if pns_s:
                print(f"      parts: {pns_s}")
            if hits:
                for h in hits[:8]:
                    print(f"      FINISH TEXT: {h}")
            else:
                print("      FINISH TEXT: (none found on this page)")

        print()

    print("""
====================================================================================
HOW TO READ THIS

Look at the pages marked  <<< ASSEMBLY.

  * If an assembly page carries a real finish (POWDER COATED / RAL xxxx), then every
    detail that says "SEE ASSEMBLY DRAWING" HAS its answer on the drawing set. The
    engine must follow the pointer. Costing it is grounded, not invented.

  * If the assembly pages carry NO finish, then the drawing set is genuinely
    self-contradictory: details defer to an assembly that never answers. We cost
    nothing, we flag it, and it goes to Design as a drawing defect.

Also note from the earlier probe: 1455-C-101 HEADER WELDMENT already carries
"POWDER COATED - SEMI-GLOSS" in its own finish — and the gate dropped powder on it
anyway. That one looks like a plain bug regardless of how the pointer question lands.
====================================================================================
""")


if __name__ == "__main__":
    main()
