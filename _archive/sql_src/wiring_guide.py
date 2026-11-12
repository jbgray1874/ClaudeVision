"""
SDIAIVision — Learning Engine Wiring Guide
==========================================
Add these lines to main.py / scan_document() to activate the learning system.
Search for the anchor comments and insert at the marked points.

STEP 1 — Add imports at top of main.py:
────────────────────────────────────────
from learning_engine import get_engine

STEP 2 — Add learning engine calls in scan_document() or scan_pdf_file():
──────────────────────────────────────────────────────────────────────────
"""

# ── ANCHOR 1: After augment_summary_with_dxf, before estimate_document ────────
#
# Find this line in main.py or file_scan.py:
#   summary = augment_summary_with_dxf(summary, dxf_paths, reestimate=False)
#
# Add immediately after:
#
#   # ── Learning Engine: pre-scan injection ───────────────────────────────────
#   try:
#       from learning_engine import get_engine
#       summary = get_engine().pre_scan(summary, dxf_paths)
#   except Exception as _le:
#       pass  # learning engine failure never breaks a scan


# ── ANCHOR 2: After estimate_document ─────────────────────────────────────────
#
# Find the estimate_document call, e.g.:
#   estimate_document(summary, ...)
#
# Add immediately after:
#
#   # ── Learning Engine: post-scan validation ─────────────────────────────────
#   try:
#       from learning_engine import get_engine
#       summary = get_engine().post_scan(summary)
#   except Exception as _le:
#       pass  # learning engine failure never breaks a scan


# ══════════════════════════════════════════════════════════════════════════════
# XLSX "SUBMIT CORRECTIONS" BUTTON SPEC
# ══════════════════════════════════════════════════════════════════════════════
#
# In estimator.py where xlsx is written, add a "Corrections" sheet:
#
# Sheet: "AI Corrections"
# Columns:
#   A: Part Number    (pre-filled from estimate)
#   B: Field          (pre-filled: "material" / "thickness_mm" / "unit_cost")
#   C: AI Value       (pre-filled: what AI estimated)
#   D: Correct Value  (ESTIMATOR FILLS THIS IN)
#   E: Your Name      (ESTIMATOR FILLS THIS IN)
#   F: Notes          (optional)
#   G: [SUBMIT button - calls submit_corrections.py via macro]
#
# submit_corrections.py (called by macro):
#   reads the Corrections sheet
#   calls learning_engine.get_engine().submit_correction() for each row
#   writes "SUBMITTED ✅" in column H
#
# This means Tim/Howard/Tony fill in corrections directly in the xlsx,
# click Submit, and the learning database updates immediately.


# ══════════════════════════════════════════════════════════════════════════════
# POWERSHELL WIRING — run nightly learning job as Windows Task Scheduler
# ══════════════════════════════════════════════════════════════════════════════
#
# Create scheduled task on 10.0.0.200:
#
# schtasks /create /tn "SDIAIVision Nightly Learning" `
#   /tr "C:\ClaudeVision\.venv\Scripts\python.exe C:\ClaudeVision\src\rule_generator.py --apply" `
#   /sc daily /st 02:00 /ru SYSTEM
#
# This runs at 2am every night:
#   1. Checks corrections database for new patterns
#   2. Auto-generates rules if pattern seen 3+ times
#   3. Patches json_normaliser.py automatically
#   4. Logs output to C:\ClaudeVision\data\logs\nightly_learning.log


# ══════════════════════════════════════════════════════════════════════════════
# FOLDER STRUCTURE
# ══════════════════════════════════════════════════════════════════════════════
#
# C:\ClaudeVision\
#   src\
#     corrections_db.py       ← database layer
#     learning_engine.py      ← pre/post scan intelligence
#     rule_generator.py       ← nightly auto-rule generation
#     wiring_guide.py         ← this file (reference only)
#     main.py                 ← add 6 lines (see ANCHOR 1 + 2 above)
#     json_normaliser.py      ← auto-patched by rule_generator
#     estimator.py            ← add "AI Corrections" sheet
#     file_scan.py            ← already has dxf_source_file injection
#   data\
#     sdi_learning.db         ← SQLite learning database (auto-created)
#     rule_backups\           ← backups before each auto-patch
#     logs\
#       nightly_learning.log

print("SDIAIVision Learning System — Wiring Guide")
print("See comments in this file for integration instructions.")
print()
print("Files to deploy to C:\\ClaudeVision\\src\\:")
print("  corrections_db.py")
print("  learning_engine.py")
print("  rule_generator.py")
print()
print("Main.py changes required: 6 lines (see ANCHOR 1 + 2 above)")
print("Nightly task: schtasks (see POWERSHELL WIRING above)")
