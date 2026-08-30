# -*- coding: utf-8 -*-
r"""Why did 1450 bind to the 500mm DXF (2262mm,0 bends) not the REV A (5143mm,6 bends)?
Calls the REAL _pick_best_flat / scoring with the real part dict + 3 candidate DXFs.
Also reads the run's JSON to show what actually bound. Read-only.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _match_diagnose.py
"""
from pathlib import Path
import sys, os, json
sys.path.insert(0, os.getcwd()); sys.path.insert(0, r"C:\ClaudeVision\src")

JOB = Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay")
cands = [p for p in JOB.glob("*.DXF") if "1450" in p.name.upper()] + \
        [p for p in JOB.glob("*.dxf") if "1450" in p.name.upper()]
cands = sorted(set(cands))
print("1450 candidate DXFs:")
for c in cands: print("  ", c.name)
print()

import drawing_job_merge as djm

# What revision does the engine think 1450-01C is? Read from the output JSON if present.
js = Path(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json")
part_rev = None
if js.exists():
    data = json.loads(js.read_text(encoding="utf-8"))
    for p in (data.get("parts") or data.get("part_estimates") or []):
        pn = str(p.get("part_number") or "")
        if pn.startswith("1450"):
            part_rev = p.get("revision") or p.get("drawing_revision")
            print(f"1450 part record: part_number={pn} revision={part_rev!r} "
                  f"bend_count={p.get('estimated_bend_line_count') or (p.get('geometry') or {}).get('estimated_bend_line_count')} "
                  f"dxf_source={p.get('dxf_source_file')}")
            break

# Build a minimal part dict mirroring what the matcher sees
part = {"part_number": "1450-01C", "revision": part_rev or "A", "description": "500mm BASE PLATE"}

# Score each candidate the way _pick_best_flat does
print("\n--- scoring each candidate (mirrors _pick_best_flat) ---")
import re
from drawing_job_merge import thickness_mm_from_dxf_filename
for p in cands:
    s = 0.0; why = []
    t = thickness_mm_from_dxf_filename(p)
    if t is not None and 0 < t <= 6.0: s += 2.0; why.append(f"thickness {t}mm +2")
    m = re.search(r"rev[\s_]*([A-Z])", p.stem, flags=re.IGNORECASE)
    pr = str(part.get("revision") or "").upper()
    if m and pr and m.group(1).upper() == pr: s += 3.0; why.append(f"rev {m.group(1)} matches part rev {pr} +3")
    elif m: why.append(f"rev {m.group(1)} (part rev {pr!r}) no match")
    else: why.append(f"no rev in name (part rev {pr!r})")
    try:
        from part_identity import score_dxf_candidate
        extra = score_dxf_candidate(part, p); s += extra
        if extra: why.append(f"identity +{extra}")
    except Exception as e:
        why.append(f"(identity scorer err: {e})")
    print(f"  {p.name}")
    print(f"     score={s}  [{'; '.join(why)}]")

print("\n--- what _pick_best_flat actually returns ---")
try:
    chosen = djm._pick_best_flat(part, cands)
    print("  CHOSEN:", chosen.name)
except Exception as e:
    print("  err:", e)
