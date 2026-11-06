# -*- coding: utf-8 -*-
"""Run the note-scan in ISOLATION with the real 1282 note text, NO try/except swallowing.
Surfaces whatever's actually failing (Grok call, parse, signature).
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe C:\\ClaudeVision\\src\\_notescan_probe.py"""
import os, json, traceback

print("=== 1. config gate ===")
import config
# THE ANSWER THIS PROBE EXISTS TO GIVE. config defines no NOTE_SCAN_POLICY at all, so
# note_scan's gate -- getattr(cfg, "NOTE_SCAN_POLICY", {}).get("enable", False) -- has read
# False on every job since the module was written, and harvest_bought_ins_from_note_text has
# returned [] without making a single call. Reading the attribute directly made this probe
# die with AttributeError on its own line 9, so the one tool built to explain the silence
# could not run. Say it instead.
_policy = getattr(config, "NOTE_SCAN_POLICY", None)
if _policy is None:
    print("  NOTE_SCAN_POLICY: NOT DEFINED IN config — the note scan is OFF on every job.")
else:
    print("  NOTE_SCAN_POLICY:", _policy,
          "" if (_policy or {}).get("enable") else "  <- enable is FALSE, scan is OFF")
print("  XAI_API_KEY present:", bool(os.environ.get("XAI_API_KEY", "").strip()))

print("\n=== 2. can we import the xAI helper the scan relies on? ===")
try:
    from web_ai_price_lookup import _call_xai_llm
    print("  _call_xai_llm import: OK")
except Exception as e:
    print("  _call_xai_llm import FAILED:", e)

print("\n=== 3. direct raw Grok call with the note prompt (no swallowing) ===")
note_text = ("ADHESIVE CABLE CLIPS TO BE USED TO SECURE ALL LOOSE CABLES TO HEADER BASE. "
             "EARTH STRAP TO BE RIVETTED UNDER LED CLIP. 5m MAINS CABLE, BLACK. "
             "JUNCTION BOX TO BE AFIXED USING D/S FOAM TAPE. GU10 DOWNLIGHTS. PLUG COUNTRY DEPENDENT.")
import note_scan as ns
try:
    prompt = ns._build_prompt(note_text)
    raw = ns._call_llm(prompt)
    print("  _call_llm returned type:", type(raw).__name__)
    print("  raw (first 500 chars):", repr(raw)[:500])
except Exception:
    print("  _call_llm RAISED:")
    traceback.print_exc()

print("\n=== 4. full scan_notes_for_bought_in, errors NOT swallowed ===")
def stub_builder(code, desc, qty):
    return {"part_number": code, "description": desc, "quantity": qty, "page_roles": ["bought_in"]}
try:
    # bypass the internal try/except by calling the pieces, but easiest: just call it
    out = ns.scan_notes_for_bought_in(
        note_text, existing_pns=set(), seen_codes=set(),
        existing_descriptions=set(), stub_builder=stub_builder)
    print("  returned %d items:" % len(out))
    for s in out:
        print("   ", s["part_number"], "-", s["description"])
except Exception:
    print("  scan RAISED:")
    traceback.print_exc()