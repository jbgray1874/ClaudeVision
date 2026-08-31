"""
wire_blip_inventry_button.py — enable the "Load to InVentry" button in the portal.

Replaces the disabled "Load to InVentry (soon)" placeholder left by
fix_portal_blip.py with a live button that calls POST /api/hr/blip/load, and
injects the hrBlipLoad() handler.

Idempotent: running it twice is a no-op. Matches the EXACT bytes on disk.

    python wire_blip_inventry_button.py                      # server default path
    python wire_blip_inventry_button.py <path-to-portal.html> # e.g. the repo copy

The button runs in DRY RUN until InVentry confirm the presence import — see
HR_LOAD_DRY_RUN in the injected script.
"""
import shutil
import sys
from pathlib import Path

DEFAULT_PORTAL = Path(r"C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html")

PORTAL = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORTAL
if not PORTAL.exists():
    sys.exit(f"Portal not found: {PORTAL}")

html = PORTAL.read_text(encoding="utf-8")

if "hr-load-btn" in html:
    print("Already wired — nothing to do.")
    sys.exit(0)

BACKUP = PORTAL.with_name(PORTAL.stem + "_pre_blip_load.html")
shutil.copy2(PORTAL, BACKUP)
print(f"Backed up to {BACKUP}")

# ── 1. Swap the disabled placeholder for a live button ──
old_button = (
    "+\'<button class=\"run\" disabled title=\"Load to InVentry \\u2014 in development\" "
    "style=\"opacity:.5;cursor:not-allowed;background:transparent;color:var(--ink);"
    "border:1px solid var(--line)\">Load to InVentry (soon)</button>\'"
)

new_button = (
    "+\'<button class=\"run\" id=\"hr-load-btn\" onclick=\"hrBlipLoad()\" "
    "title=\"Write the current on-site list to the InVentry watched folder\" "
    "style=\"background:transparent;color:var(--ink);border:1px solid var(--line)\">"
    "Load to InVentry</button>\'"
)

if old_button in html:
    html = html.replace(old_button, new_button, 1)
    print("1. Button enabled OK")
else:
    print("1. WARN: disabled button block not found — has fix_portal_blip.py run?")
    i = html.find("Load to InVentry")
    print(f"   'Load to InVentry' at position: {i}")

# ── 2. Inject hrBlipLoad() before </script> ──
load_fn = """
  // ---- Blip -> InVentry presence load (stage 3) ----
  // DRY RUN until InVentry confirm they accept a presence import: the CSV is
  // written beside the snapshot instead of into their watched folder.
  // Set to false once confirmed.
  var HR_LOAD_DRY_RUN = true;

  async function hrBlipLoad(){
    var btn=document.getElementById('hr-load-btn');
    var out=document.getElementById('hr-blip-result');
    if(!btn||!out) return;
    if(!HR_LOAD_DRY_RUN && !confirm('Write the current on-site list to InVentry?\\n\\nThis replaces the front-desk on-site register.')) return;
    var orig=btn.textContent;
    btn.disabled=true; btn.textContent='Loading\\u2026';
    out.style.color='var(--ink-dim)';
    out.textContent=(HR_LOAD_DRY_RUN?'[DRY RUN] ':'')+'Writing on-site list to InVentry\\u2026';
    try{
      var r=await fetch(API_BASE+'/api/hr/blip/load?dry_run='+HR_LOAD_DRY_RUN,{method:'POST',headers:_hdr()});
      if(!r.ok) throw new Error(r.status+' '+(await r.text()).slice(0,200));
      var d=await r.json();
      var warn=(d.warnings||[]).join('\\n');
      out.style.color = d.status==='ok' ? 'var(--ok)' : 'var(--warn)';
      out.textContent=(d.dry_run?'[DRY RUN] ':'')
        +'Wrote '+d.written+' of '+d.on_site+' on site'
        +'\\nStatus: '+(d.status||'').toUpperCase()
        +'\\nTarget: '+(d.target||'')
        +(d.snapshot_age_minutes!=null ? '\\nSnapshot age: '+d.snapshot_age_minutes+' min' : '')
        +(warn ? '\\n'+warn : '');
    }catch(e){
      out.style.color='var(--fail)';
      out.textContent='Load failed: '+e.message;
    }finally{
      btn.disabled=false; btn.textContent=orig;
    }
  }
"""

anchor = "</script>"
idx = html.rfind(anchor)
if idx >= 0:
    html = html[:idx] + load_fn + "\n" + html[idx:]
    print("2. hrBlipLoad() injected OK")
else:
    print("2. WARN: </script> not found")

PORTAL.write_text(html, encoding="utf-8")

html2 = PORTAL.read_text(encoding="utf-8")
print(f"\nVerify: 'hr-load-btn' found: {'hr-load-btn' in html2}")
print(f"Verify: 'hrBlipLoad' found: {'hrBlipLoad' in html2}")
print(f"Verify: '/api/hr/blip/load' found: {'/api/hr/blip/load' in html2}")
print(f"File size: {len(html2)} bytes")
print("\nHard-refresh (Ctrl+Shift+R), click \"Who's clocked in?\" then \"Load to InVentry\".")
