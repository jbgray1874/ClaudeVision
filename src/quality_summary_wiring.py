# ----------------------------------------------------------------------------
# WIRING: add the Estimate Quality Summary tab back into the run.
#
# Drop this where main.py adds the Decision Report / AI Provenance sheets.
# Put it in its OWN try/except (NOT the shared one) so a fault here can only
# drop THIS sheet — and is logged with a real traceback — instead of silently
# taking other tabs down with it. That also fixes the broad-try/except issue.
# ----------------------------------------------------------------------------

import traceback
import quality_summary

# --- Option A: you already have the openpyxl workbook object `wb` in scope ---
try:
    quality_summary.add_quality_summary_sheet(wb, summary)
    print("   [xlsx] Estimate Quality Summary sheet added")
except Exception:
    print("   [xlsx] WARNING: Estimate Quality Summary sheet FAILED — other tabs unaffected:")
    traceback.print_exc()

# --- Option B: if the sheets are added by re-opening the saved file ----------
# (use this if there is no live `wb`, only the path to the written workbook)
#
# from openpyxl import load_workbook
# try:
#     wb = load_workbook(xlsx_path)
#     quality_summary.add_quality_summary_sheet(wb, summary)
#     wb.save(xlsx_path)
#     print("   [xlsx] Estimate Quality Summary sheet added")
# except Exception:
#     print("   [xlsx] WARNING: Estimate Quality Summary sheet FAILED:")
#     traceback.print_exc()

# NOTE on the existing broad try/except: wrap EACH report sheet
# (Decision Report, AI Provenance, Quality Summary) in its own try/except like
# the above, each with traceback.print_exc(), so one failing sheet never
# silently removes the others.
