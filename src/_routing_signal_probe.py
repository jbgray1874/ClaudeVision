"""READ-ONLY. Answers ONE question for each of four routing issues:
  "Is the signal actually IN the drawing data, or would a fix be hardcoding Tim's answer?"

It reads the engine's OWN extracted JSON for 1282 (no drawings re-parsed, no Tim data) and
reports, per part, the geometry + text signals that a route decision could legitimately use.

  1. PUNCH vs LASER  -> hole_count / pierce_count / hole density per part. Tim punches the
     hole-heavy ones. If the engine already has the counts, punch-vs-laser is drawing-derivable.
  2. ASSEMBLY-P.COAT -> page_roles + which parts are assembly vs detail, and whether the
     assembly/weldment structure is captured (so P.Coat can be grouped at assembly level).
  3. ROLL            -> scan each part's raw text/process-notes/angles for ANY roll indicator
     (ROLL, ROLLED, RADIUS on a large R, curved). If nothing -> NOT derivable, must not invent.
  4. SPOTWELD        -> scan for SPOT / RESISTANCE / assembly-join language; report whether the
     assembly pages give a join signal or whether it'd be pure guess.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _routing_signal_probe.py
"""
import json, io, re

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(io.open(P, encoding="utf-8"))
parts = (data.get("manufacturing_writeup") or {}).get("parts") or data.get("parts") or []

def g(p, k, default=None):
    return p.get(k, default)

print("=" * 78)
print("1. PUNCH vs LASER  — is hole/pierce geometry present per part?")
print("=" * 78)
print(f"{'part':14} {'holes':>6} {'pierces':>8} {'cutlen':>9}  current_ops")
for p in parts:
    pn = str(g(p,'part_number','—'))
    if pn.startswith(('BI-','FIXING','VINYL','PACKAGING','DELIVERY')):
        continue
    geo = g(p,'geometry_rollup') or {}
    holes = int(geo.get('estimated_hole_count') or 0)
    pierce = int(geo.get('estimated_pierce_count') or 0)
    cut = geo.get('estimated_cut_length_mm') or 0
    ops = list(g(p,'textual_operations') or []) + list(g(p,'inferred_operations') or [])
    cutmethod = 'PUNCH' if 'punch' in ops else ('LASER' if 'laser_cutting' in ops else '—')
    print(f"{pn:14} {holes:6d} {pierce:8d} {cut:9.0f}  {cutmethod}  ({','.join(ops)})")
print("\n  -> If hole counts vary meaningfully across parts, punch-vs-laser is drawing-derivable.")
print("     Tim punches: 1449, 1450, 2621, 1448-02, 3886-02/03. Do THOSE have the holes?")

print("\n" + "=" * 78)
print("2. ASSEMBLY-P.COAT — is the assembly hierarchy captured?")
print("=" * 78)
for p in parts:
    pn = str(g(p,'part_number','—'))
    if pn.startswith(('BI-','FIXING','VINYL','PACKAGING','DELIVERY')):
        continue
    roles = g(p,'page_roles') or []
    src = g(p,'source') or ''
    parent = g(p,'parent_part') or g(p,'parent') or g(p,'assembly_parent') or '—'
    print(f"  {pn:14} roles={str(roles):24} parent={parent!s:12} src={src}")
print("\n  -> 'assembly' roles + any parent/child link = P.Coat can be grouped at assembly level.")
print("     If parent links are all '—', the hierarchy isn't captured yet (would need building).")

print("\n" + "=" * 78)
print("3. ROLL — is there ANY roll indicator in the drawing data? (decision: build or DON'T)")
print("=" * 78)
ROLL_RX = re.compile(r'\b(ROLL|ROLLED|ROLLING|CURVE|CURVED|RADIUS)\b', re.I)
any_roll = False
for p in parts:
    pn = str(g(p,'part_number','—'))
    blob = " ".join(str(x) for x in [
        g(p,'process_notes'), g(p,'raw_text'), g(p,'description'),
        g(p,'angles_deg'), g(p,'finishes'), g(p,'textual_operations')
    ] if x)
    hits = ROLL_RX.findall(blob)
    # also look at big radii (roll often = large R)
    big_r = re.findall(r'\bR\s?(\d{2,})', blob)
    if hits or big_r:
        any_roll = True
        print(f"  {pn:14} roll-ish tokens={hits}  large_radii={big_r}")
if not any_roll:
    print("  NO roll indicator found on ANY part.")
    print("  -> HONEST CONCLUSION: roll is NOT drawing-derivable from current extraction.")
    print("     Do NOT hardcode Tim's roll choice. Flag 'estimator to confirm' instead.")

print("\n" + "=" * 78)
print("4. SPOTWELD — join signal in assembly pages, or pure guess?")
print("=" * 78)
SPOT_RX = re.compile(r'\b(SPOT|RESISTANCE|SPOTWELD|TACK)\b', re.I)
WELD_RX = re.compile(r'\bWELD', re.I)
any_spot = False
for p in parts:
    pn = str(g(p,'part_number','—'))
    blob = " ".join(str(x) for x in [g(p,'process_notes'), g(p,'raw_text'), g(p,'description')] if x)
    spot = SPOT_RX.findall(blob)
    weld = WELD_RX.findall(blob)
    roles = g(p,'page_roles') or []
    if spot or weld or 'assembly' in [str(r).lower() for r in roles]:
        any_spot = True
        print(f"  {pn:14} spot_tokens={spot} weld_tokens={bool(weld)} roles={roles}")
if not any_spot:
    print("  No spot/weld/assembly signal found.")
print("\n  -> If only generic WELD/assembly appears (no SPOT), spotweld-vs-CO2 is NOT")
print("     distinguishable from the drawing -> flag, don't guess which weld type.")
