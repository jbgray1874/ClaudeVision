"""
fix_portal_blip_warnings.py — show Blip warnings in the portal.

The write to HR_OUTPUT_DIR is non-fatal, so when that share is unreachable the
run still reported "Status: OK" and simply omitted the File line. Nothing on
screen said why the output directory had not updated.

This makes hrBlip() render any warnings the backend returns, and say plainly
when no output file was written.

Idempotent: running it twice is a no-op.

    python fix_portal_blip_warnings.py                      # server default path
    python fix_portal_blip_warnings.py <path-to-portal.html> # e.g. the repo copy
"""
import shutil
import sys
from pathlib import Path

DEFAULT_PORTAL = Path(r"C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html")

PORTAL = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORTAL
if not PORTAL.exists():
    sys.exit(f"Portal not found: {PORTAL}")

html = PORTAL.read_text(encoding="utf-8")

if "NOT WRITTEN" in html:
    print("Already patched — nothing to do.")
    sys.exit(0)

OLD = (
    "      out.style.color = d.status==='ok' ? 'var(--ok)' : 'var(--warn)';\n"
    "      out.textContent=d.on_site+' staff on site (of '+d.employees_checked+' checked)'\n"
    "        +'\\nStatus: '+d.status.toUpperCase()\n"
    "        +(file ? '\\nFile: '+file : '')\n"
    "        +'\\nAt: '+when+' UTC';"
)

NEW = (
    "      var warn=(d.warnings||[]).join('\\n');\n"
    "      out.style.color = (d.status==='ok' && !warn) ? 'var(--ok)' : 'var(--warn)';\n"
    "      out.textContent=d.on_site+' staff on site (of '+d.employees_checked+' checked)'\n"
    "        +'\\nStatus: '+d.status.toUpperCase()\n"
    "        +(file ? '\\nFile: '+file : '\\nFile: NOT WRITTEN \\u2014 see below')\n"
    "        +'\\nAt: '+when+' UTC'\n"
    "        +(warn ? '\\n\\n'+warn : '');"
)

if OLD not in html:
    sys.exit("Could not find the hrBlip() render block — has fix_portal_blip.py run?")

BACKUP = PORTAL.with_name(PORTAL.stem + "_pre_blip_warnings.html")
shutil.copy2(PORTAL, BACKUP)
print(f"Backed up to {BACKUP}")

PORTAL.write_text(html.replace(OLD, NEW, 1), encoding="utf-8")

check = PORTAL.read_text(encoding="utf-8")
print(f"Verify: warnings rendered: {'(d.warnings||[])' in check}")
print(f"Verify: missing-file notice: {'NOT WRITTEN' in check}")
print("\nHard-refresh (Ctrl+Shift+R) and click \"Who's clocked in?\".")
