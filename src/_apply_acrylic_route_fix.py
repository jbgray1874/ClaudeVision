#!/usr/bin/env python3
r"""
_apply_acrylic_route_fix.py

12439 (acrylic cube) came out at £4.62 against the estimator's £1.30. Every pound of the
overcharge traces to ONE block — the acrylic route in estimator.py (~1983-2011) — which was
reverse-engineered from a single bonded display tank (M18 / 10897) and therefore assumes every
acrylic part is a lasered, bonded, flame-polished assembly. A single formed cleat is none of
those.

WHAT THE ESTIMATOR ACTUALLY DOES (from Tony's 12439 sheet), and it is SIMPLER than metal:

    Diamond Polish   -> the FINISH for acrylic. NOT powder. Acrylic is never powder coated.
    Manual (Peel)    -> peel the protective film. Present on every acrylic part.
    Linebend         -> per bend, when the part folds.
    Assemble/pack    -> pack. Present on every acrylic part.

    Laser            -> ONLY when the part is genuinely laser-cut.
    Glue + flame     -> ONLY on a bonded MULTI-PANEL assembly (the M18 tank), never on a
                        single formed part.

WHAT THE ENGINE WAS DOING WRONG on the single cube:
    - invented GLUE (£1.03) and flame/manual - the tank recipe on a non-bonded part
    - invented LASER (£0.26) - the part is guillotine/router cut + line bent, not lasered
    - resolved POWDER finish (£0.30) on acrylic - acrylic is diamond polished, not coated
    - MISSED Diamond Polish entirely - the actual acrylic finish

THE FIX - four coherent changes, all in the acrylic block:

  1. FINISH: acrylic gets Diamond Polish, and powder is invalid on acrylic. (The powder-coat
     resolution and BOM line must not fire for an acrylic part.) Add DPOL from config driver.

  2. GLUE + FLAME are gated behind a BONDED-ASSEMBLY test, not merely "has bends". A single
     formed part (bends but no bonded children / not a multi-panel assembly) gets neither.
     Signal: the part has bonded child panels, OR is explicitly flagged a bonded assembly.
     A lone part with bends is just line-bent.

  3. LASER on acrylic is gated behind an actual laser-cut signal. Absent that signal, a single
     formed part from sheet is NOT lasered (matches Tony, who has no laser line). This is
     conservative: it only adds laser when we can see the part is laser-cut.

  4. PEEL (manual) + Diamond Polish are ADDED for every acrylic part (the two ops the engine
     was missing). Assemble/pack and linebend already fire correctly.

Result target on 12439 (single formed cube), matching Tony's 4-op routing:
    Diamond Polish + Peel(manual) + Linebend + Assemble/pack
    NO glue, NO laser, NO powder.

NOTE: this does NOT break M18 (the bonded tank) — its panels ARE a bonded assembly, so glue +
flame still fire there via the bonded-assembly gate. Re-run M18 to confirm.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_route_fix.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

CONFIG = r"C:\ClaudeVision\src\config.py"
TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "acrylic_route_v2"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for (first 400 chars) ---\n{old[:400]}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# ── config: add the diamond-polish + peel drivers (config lists them but has no values) ──
C_ANCHOR = '''    "flame_min_per_assembly": 1.2,            # MANA: one op per display assembly (50 parts/hr)
    "flame_setup_min": 15.0,'''

C_NEW = '''    "flame_min_per_assembly": 1.2,            # MANA: one op per display assembly (50 parts/hr)
    "flame_setup_min": 15.0,
    # Added 2026-07-15 from Tony's 12439 sheet: the two ops every acrylic part needs and the
    # engine was omitting. Diamond Polish is the acrylic FINISH (not powder); Peel removes the
    # protective film. Both present on every acrylic part regardless of bonding.
    "diamond_polish_min_per_part": 0.5,       # DPOL: acrylic finish, ~120 parts/hr
    "diamond_polish_setup_min": 10.0,
    "peel_min_per_part": 0.5,                 # MANA/peel: ~120 parts/hr
    "peel_setup_min": 15.0,'''


# ── estimator.py: replace the acrylic op block with the corrected routing ──────────────
# Anchor on the exact bend-gated block that adds linebend/glue/flame.
E_ANCHOR = '''        if _bends > 0:
            _rt["linebend"] = round(_rt.get("linebend", 0.0) + float(_drv.get("min_per_linebend", 1.0)) * _bends, 4)
            _st.setdefault("linebend", float(_drv.get("linebend_setup_min", 30.0)))
            _rt["glue"] = round(_rt.get("glue", 0.0) + float(_drv.get("glue_min_per_assembly", 2.4)), 4)
            _st.setdefault("glue", float(_drv.get("glue_setup_min", 30.0)))
            _rt["manual_labour_acrylic"] = round(_rt.get("manual_labour_acrylic", 0.0) + float(_drv.get("flame_min_per_assembly", 1.2)), 4)
            _st.setdefault("manual_labour_acrylic", float(_drv.get("flame_setup_min", 15.0)))
        process["acrylic_ops_canonical"] = True'''

E_NEW = '''        # acrylic_route_v2 (2026-07-15): route matches the estimator's acrylic sheets.
        # An acrylic part is SIMPLER than metal. Every acrylic part gets Diamond Polish
        # (the finish — acrylic is NOT powder coated) and Peel (protective film). Linebend
        # scales per bend. GLUE + flame are added ONLY for a genuinely BONDED assembly
        # (multi-panel display / tank), never for a single formed part. LASER is added only
        # when there is an actual laser-cut signal; a lone formed part from sheet is
        # guillotine/router + line-bent, not lasered.

        # Is this a bonded multi-panel assembly (glue + flame apply), or a single formed part?
        _bonded = bool(part.get("is_bonded_assembly")) or bool(part.get("acrylic_bonded"))
        _kids = part.get("child_parts") or part.get("children") or []
        if not _bonded and isinstance(_kids, (list, tuple)) and len(_kids) >= 2:
            _bonded = True   # multiple bonded panels under this part

        # Is the part actually laser-cut? Only then does laser apply. Absent a signal, a
        # single formed acrylic part is not lasered (matches the estimator).
        _laser_signal = bool(part.get("is_laser_cut")) or bool(part.get("laser_cut_acrylic"))
        _cut_method = str(part.get("cut_method") or part.get("cutting_method") or "").lower()
        if "laser" in _cut_method:
            _laser_signal = True
        if _cut_method in ("guillotine", "router", "rout", "saw", "cnc_rout"):
            _laser_signal = False
        if not (_laser_signal or _bonded):
            # not lasered: drop the laser op the block added above
            _rt.pop("laser_cutting", None)
            _st.pop("laser_cutting", None)

        # FINISH: Diamond Polish for every acrylic part; powder is invalid on acrylic.
        _rt["diamond_polish"] = round(_rt.get("diamond_polish", 0.0)
                                      + float(_drv.get("diamond_polish_min_per_part", 0.5)), 4)
        _st.setdefault("diamond_polish", float(_drv.get("diamond_polish_setup_min", 10.0)))
        # Peel the protective film — present on every acrylic part.
        _rt["manual_labour_acrylic"] = round(_rt.get("manual_labour_acrylic", 0.0)
                                             + float(_drv.get("peel_min_per_part", 0.5)), 4)
        _st.setdefault("manual_labour_acrylic", float(_drv.get("peel_setup_min", 15.0)))
        # Acrylic is never powder coated — strip any powder op the finish-resolver added.
        for _pw in ("powder_coating",):
            _rt.pop(_pw, None)
            _st.pop(_pw, None)
        part["acrylic_no_powder"] = True   # signal downstream: suppress the powder BOM line

        if _bends > 0:
            _rt["linebend"] = round(_rt.get("linebend", 0.0) + float(_drv.get("min_per_linebend", 1.0)) * _bends, 4)
            _st.setdefault("linebend", float(_drv.get("linebend_setup_min", 30.0)))

        if _bonded:
            # bonded multi-panel assembly: glue joints + flame-polish, ONE op per assembly
            _rt["glue"] = round(_rt.get("glue", 0.0) + float(_drv.get("glue_min_per_assembly", 2.4)), 4)
            _st.setdefault("glue", float(_drv.get("glue_setup_min", 30.0)))
            _rt["manual_labour_acrylic"] = round(_rt.get("manual_labour_acrylic", 0.0) + float(_drv.get("flame_min_per_assembly", 1.2)), 4)
            _st.setdefault("manual_labour_acrylic", float(_drv.get("flame_setup_min", 15.0)))

        process["acrylic_ops_canonical"] = True
        process["acrylic_route_v2"] = True
        process["acrylic_bonded_detected"] = _bonded
        process["acrylic_laser_applied"] = bool(_laser_signal or _bonded)'''


def main():
    for p in (CONFIG, TARGET):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")
    cfg = open(CONFIG, "r", encoding="utf-8").read()
    est = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in cfg or SENTINEL in est:
        sys.exit("Already applied (sentinel present).")

    cfg = sub(cfg, C_ANCHOR, C_NEW, "config: add diamond-polish + peel drivers")
    est = sub(est, E_ANCHOR, E_NEW, "estimator: corrected acrylic routing (v2)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, text in ((CONFIG, cfg), (TARGET, est)):
        bak = f"{path}.bak_acrylicroute_{ts}"
        shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(text)
        print(f"  backup: {bak}")

    print("""
NOTE: this fixes the LABOUR routing. The phantom-powder BOM LINE is suppressed via the
part['acrylic_no_powder'] flag — BUT that flag must be READ where the powder BOM row is
written (wb_populate powder block). If the powder line still appears after this run, the
flag needs wiring into that block too — tell me and I'll add it. This patch sets the flag;
confirm whether the powder row disappears.

RUN 12439 (qty 2025), THEN 10897 (M18 — the bonded tank, to confirm glue/flame still fire).

    12439 expected (single formed cube, matching Tony's 4 ops):
        Diamond Polish + Peel(manual) + Linebend + Assemble/pack
        NO glue, NO laser, NO powder line.
        Tony: material £0.28, labour £1.02, unit £1.30.
        The two remaining gaps to watch after this:
          - acrylic sheet 317x182 @ £46.20 -> £0.53 vs Tony's 311x101 @ £0.12
            (part DIMENSIONS read too big + sheet RATE — separate from routing)
          - assemble/pack 30/hr band vs Tony's 120 (acrylic pack band may differ from metal)

    10897 (M18 bonded tank) expected:
        glue + flame STILL present (it IS a bonded assembly). If they vanish, the bonded
        test is too strict and I need the actual multi-panel signal on that job.
""")


if __name__ == "__main__":
    main()
