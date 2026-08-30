"""
fix_portal_blip.py v2 — Wire the Blip button into the portal.
Matches the EXACT bytes on disk. Run on SDI-APP01.
"""
import shutil
from pathlib import Path

PORTAL = Path(r"C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html")
BACKUP = PORTAL.with_name("sdi-intelligence-portal_pre_blip_v2.html")

shutil.copy2(PORTAL, BACKUP)
print(f"Backed up to {BACKUP}")

html = PORTAL.read_text(encoding="utf-8")

# ── 1. Replace the disabled buttons block with live Blip buttons ──
old_buttons = (
    "+\'<div style=\"display:flex;gap:10px;flex-wrap:wrap\">\'\n"
    "       +\'<button class=\"run\" disabled title=\"Enabled once BrightHR API access is configured in .env\" style=\"opacity:.5;cursor:not-allowed\">Run Sync (Pull + Load)</button>\'\n"
    "       +\'<button class=\"run\" disabled title=\"Pull only \\u2014 writes a timestamped JSON snapshot, no CSV\" style=\"opacity:.5;cursor:not-allowed;background:transparent;color:var(--ink);border:1px solid var(--line)\">Pull only</button>\'\n"
    "       +\'<button class=\"run\" disabled title=\"Load only \\u2014 writes the latest snapshot to the InVentry watched folder\" style=\"opacity:.5;cursor:not-allowed;background:transparent;color:var(--ink);border:1px solid var(--line)\">Load only</button>\'\n"
    "       +\'</div>\'\n"
    "       +\'<div class=\"muted\" style=\"margin-top:10px"
)

new_buttons = (
    "+\'<div style=\"display:flex;gap:10px;flex-wrap:wrap;align-items:center\">\'\n"
    "       +\'<button class=\"run\" id=\"hr-blip-btn\" onclick=\"hrBlip()\">Who\\'s clocked in?</button>\'\n"
    "       +\'<button class=\"run\" style=\"background:transparent;color:var(--ink);border:1px solid var(--line)\" onclick=\"var n=document.querySelector(\\\'.nav a[data-view=files]\\\');if(n)n.click();\">View HR output folder \\u2192</button>\'\n"
    "       +\'<button class=\"run\" disabled title=\"Load to InVentry \\u2014 in development\" style=\"opacity:.5;cursor:not-allowed;background:transparent;color:var(--ink);border:1px solid var(--line)\">Load to InVentry (soon)</button>\'\n"
    "       +\'</div>\'\n"
    "       +\'<div id=\"hr-blip-result\" class=\"muted\" style=\"margin-top:12px;font-size:12px;font-family:var(--mono);white-space:pre-wrap\"></div>\'\n"
    "       +\'<div class=\"muted\" style=\"margin-top:10px"
)

if old_buttons in html:
    html = html.replace(old_buttons, new_buttons, 1)
    print("1. Buttons replaced OK")
else:
    print("1. WARN: button block not found")
    # debug
    i = html.find("Run Sync (Pull + Load)")
    print(f"   'Run Sync' at position: {i}")
    i2 = html.find("Pull only</button>")
    print(f"   'Pull only</button>' at position: {i2}")

# ── 2. Inject hrBlip() function before </script> ──
blip_fn = """
  // ---- BrightHR Blip (COO control — who's clocked in) ----
  async function hrBlip(){
    var btn=document.getElementById('hr-blip-btn');
    var out=document.getElementById('hr-blip-result');
    if(!btn||!out) return;
    var orig=btn.textContent;
    btn.disabled=true; btn.textContent='Checking\\u2026';
    out.style.color='var(--ink-dim)'; out.textContent='Querying BrightHR Blip (~20s)\\u2026';
    try{
      var r=await fetch(API_BASE+'/api/hr/blip',{method:'POST',headers:_hdr()});
      if(!r.ok) throw new Error(r.status+' '+(await r.text()).slice(0,200));
      var d=await r.json();
      var when=(d.timestamp||'').replace('T',' ').slice(0,19);
      var file=d.output_file ? d.output_file.split('\\\\').pop() : '';
      out.style.color = d.status==='ok' ? 'var(--ok)' : 'var(--warn)';
      out.textContent=d.on_site+' staff on site (of '+d.employees_checked+' checked)'
        +'\\nStatus: '+d.status.toUpperCase()
        +(file ? '\\nFile: '+file : '')
        +'\\nAt: '+when+' UTC';
    }catch(e){
      out.style.color='var(--fail)';
      out.textContent='Blip failed: '+e.message;
    }finally{
      btn.disabled=false; btn.textContent=orig;
    }
  }
"""

anchor = "</script>"
idx = html.rfind(anchor)
if idx >= 0:
    html = html[:idx] + blip_fn + "\n" + html[idx:]
    print("2. hrBlip() function injected OK")
else:
    print("2. WARN: </script> not found")

PORTAL.write_text(html, encoding="utf-8")

# Verify
html2 = PORTAL.read_text(encoding="utf-8")
print(f"\nVerify: 'hr-blip-btn' found: {'hr-blip-btn' in html2}")
print(f"Verify: 'hrBlip' found: {'hrBlip' in html2}")
print(f"Verify: '/api/hr/blip' found: {'/api/hr/blip' in html2}")
print(f"File size: {len(html2)} bytes")
print(f"\nHard-refresh (Ctrl+Shift+R) and click 'Who's clocked in?'")
