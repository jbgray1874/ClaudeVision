"""READ-ONLY. Dumps the FULL extracted text of every page of the 1298 drawing
(not the truncated console preview) and flags finish/powder/coat/colour cues.

Answers: did the engine EXTRACT powder-coat content anywhere, and on which page?
  - If a page shows 'POWDER'/'COAT'/'RAL'/a colour -> the content is IN the drawing,
    the engine saw it, and stopping at 'SEE INDIVIDUAL DRAWINGS' is a resolution BUG (fixable).
  - If NO page states a coating -> the powder-coat is NOT on the drawing (only in Tim's
    enquiry) -> engine can't derive it -> honest flag, not a recoverable number.

Reads two sources so we see both what was saved and, if available, re-extracts live:
  1. The saved text output file (what the engine wrote)
  2. Re-parses the PDF directly with pdfplumber (ground truth of the text layer)
"""
import io, re
from pathlib import Path

TXT = Path(r"C:\ClaudeVision\output\text\1298DrillHolder.txt")
PDF = Path(r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\1298DrillHolder\1298-Drill Holder 1_revF.PDF")

CUES = re.compile(r"POWDER|P\.?\s?COAT|COATED|COATING|\bRAL\b|SEMI-?GLOSS|GLOSS|MATT|"
                  r"SURFACE\s*FINISH|\bFINISH\b|COLOUR|COLOR|PPC|WET\s*SPRAY|ANODIS", re.I)

def flag_lines(label, text):
    print("=" * 80)
    print(label)
    print("=" * 80)
    if not text:
        print("  (no text)")
        return
    hits = [l.strip() for l in text.splitlines() if CUES.search(l)]
    if hits:
        print(f"  {len(hits)} finish/coat/colour cue line(s):")
        for h in hits:
            print(f"    | {h[:120]}")
    else:
        print("  NO finish/coat/colour cue found anywhere in this text.")

# 1. saved engine text output
if TXT.exists():
    flag_lines("A. SAVED ENGINE TEXT OUTPUT (1298DrillHolder.txt)",
               TXT.read_text(encoding="utf-8", errors="replace"))
else:
    print("A. saved text output not found:", TXT)

# 2. re-parse the PDF directly, per page — the ground truth of the text layer
print("\n")
try:
    import pdfplumber
    with pdfplumber.open(str(PDF)) as pdf:
        print("=" * 80)
        print(f"B. DIRECT PDF RE-PARSE — {len(pdf.pages)} page(s)")
        print("=" * 80)
        for i, page in enumerate(pdf.pages, 1):
            t = page.extract_text() or ""
            hits = [l.strip() for l in t.splitlines() if CUES.search(l)]
            print(f"\n  --- PAGE {i} ---")
            if hits:
                for h in hits:
                    print(f"    | {h[:120]}")
            else:
                print("    (no finish/coat/colour cue on this page)")
            # also show if this page has the SURFACE FINISH label and what follows it
            m = re.search(r"SURFACE\s*FINISH\s*[:\-]?\s*(.{0,60})", t, re.I)
            if m:
                print(f"    >> SURFACE FINISH label -> '{m.group(1).strip()[:60]}'")
except ImportError:
    print("B. pdfplumber not available in this interpreter — rely on section A + your eyes on the PDF.")
except Exception as e:
    print(f"B. could not open PDF directly: {e}")

print("\n" + "=" * 80)
print("VERDICT GUIDE")
print("=" * 80)
print("  Powder/coat/RAL cue present on some page  -> content IS in drawing -> resolution BUG (fixable).")
print("  Only 'SEE INDIVIDUAL DRAWINGS' / no cue    -> not derivable from drawing -> honest flag, not a fix.")
