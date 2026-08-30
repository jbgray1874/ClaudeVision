"""
fix_portal_blip.py — Run on SDI-APP01 to rewire the portal button from
roster-pull to Blip (who's clocked in). Makes four targeted edits:

1. Changes button label: "Pull staff from BrightHR" -> "Who's clocked in?"
2. Changes endpoint in hrPull(): /api/hr/pull -> /api/hr/blip (ONLY inside
   the function, NOT in the SERVICES array description text)
3. Changes the result display from roster format to on-site format
4. Removes the duplicate second hrPull() function

Run:  .\.venv\Scripts\python.exe fix_portal_blip.py
"""
import shutil
from pathlib import Path

PORTAL = Path(r"C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html")
BACKUP = PORTAL.with_name("sdi-intelligence-portal_pre_blip_fix.html")

# Back up first
shutil.copy2(PORTAL, BACKUP)
print(f"Backed up to {BACKUP}")

html = PORTAL.read_text(encoding="utf-8")
original_len = len(html)

# ── 1. Change button label (inside SERVICES array detail string) ──
old_label = ">Pull staff from BrightHR</button>"
new_label = ">Who's clocked in?</button>"
count = html.count(old_label)
if count == 1:
    html = html.replace(old_label, new_label)
    print(f"1. Button label changed OK")
else:
    print(f"1. WARN: found {count} occurrences of button label (expected 1)")

# ── 2. Change endpoint ONLY inside hrPull() function ──
# The SERVICES array has /api/hr/pull as plain text in description strings.
# The hrPull function has it as: fetch(API_BASE+'/api/hr/pull',{method:'POST'
# We match the fetch() context to avoid hitting the SERVICES descriptions.
old_fetch = "fetch(API_BASE+'/api/hr/pull',{method:'POST'"
new_fetch = "fetch(API_BASE+'/api/hr/blip',{method:'POST'"
count = html.count(old_fetch)
if count >= 1:
    html = html.replace(old_fetch, new_fetch)
    print(f"2. Endpoint changed in {count} occurrence(s) OK (fetch context only)")
else:
    print(f"2. WARN: fetch pattern not found")

# ── 3. Change the result display ──
old_display = (
    "out.textContent='Status: '+d.status.toUpperCase()\n"
    "        +'\\nPulled '+d.pulled+'  \\u00b7  Active '+d.active+'  \\u00b7  Skipped '+d.skipped\n"
    "        +'\\nFile: '+file\n"
    "        +'\\nAt: '+when+' UTC'+warn;"
)
new_display = (
    "out.textContent=d.on_site+' staff on site (of '+d.employees_checked+' checked)'\n"
    "        +'\\nStatus: '+d.status.toUpperCase()\n"
    "        +'\\nFile: '+file\n"
    "        +'\\nAt: '+when+' UTC'+warn;"
)
count = html.count(old_display)
if count >= 1:
    html = html.replace(old_display, new_display)
    print(f"3. Display format changed in {count} occurrence(s) OK")
else:
    print(f"3. WARN: display pattern not found - trying alternate whitespace")
    # Try with different whitespace
    old_alt = "out.textContent='Status: '+d.status.toUpperCase()"
    new_alt = "out.textContent=d.on_site+' staff on site (of '+d.employees_checked+' checked)'"
    count2 = html.count(old_alt)
    if count2 >= 1:
        html = html.replace(old_alt, new_alt)
        print(f"3b. First line replaced in {count2} occurrence(s)")
        # Also replace the Pulled line
        old_pulled = "+d.pulled+'  \\u00b7  Active '+d.active+'  \\u00b7  Skipped '+d.skipped"
        new_pulled = "+'\\nStatus: '+d.status.toUpperCase()"
        if old_pulled in html:
            # This would create duplicate Status lines - just remove the Pulled line
            html = html.replace("+'\\nPulled '+d.pulled+'  \\u00b7  Active '+d.active+'  \\u00b7  Skipped '+d.skipped\n", "")
            print(f"3c. Pulled/Active/Skipped line removed")
    else:
        print(f"3. SKIP: could not match display pattern")

# ── 4. Remove the duplicate second hrPull() ──
marker = "  // ---- BrightHR Pull (COO control) ----"
first = html.find(marker)
if first >= 0:
    second = html.find(marker, first + 1)
    if second >= 0:
        # Find the end of the second function: last } before </script>
        script_end = html.find("</script>", second)
        if script_end >= 0:
            # The second function block runs from `second` to just before </script>
            # We need to find the closing } of the function
            block = html[second:script_end]
            # Remove everything from second marker to just before </script>
            # but keep a newline before </script>
            html = html[:second] + "\n" + html[script_end:]
            print(f"4. Duplicate hrPull() removed OK")
        else:
            print(f"4. WARN: couldn't find </script> after second function")
    else:
        print(f"4. Only one hrPull() found - no duplicate to remove")
else:
    print(f"4. WARN: hrPull marker not found at all")

# ── Write back ──
PORTAL.write_text(html, encoding="utf-8")
print(f"\nDone. File: {len(html)} bytes (was {original_len})")
print(f"Backup at: {BACKUP}")
print(f"\nHard-refresh (Ctrl+Shift+R) and test the button.")
