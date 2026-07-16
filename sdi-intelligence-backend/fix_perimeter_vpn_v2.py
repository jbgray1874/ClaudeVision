"""
fix_perimeter_vpn_v2.py — Fixes the remaining 4 items using regex
(immune to em-dash/encoding mismatches). Run AFTER fix_perimeter_vpn.py
already succeeded on the other 9 items.
"""
import re, shutil
from pathlib import Path

PORTAL = Path(r"C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html")
BACKUP = PORTAL.with_name("sdi-intelligence-portal_pre_perimeter_v2.html")
shutil.copy2(PORTAL, BACKUP)
print(f"Backed up to {BACKUP}")

html = PORTAL.read_text(encoding="utf-8")
warnings = []

def regex_replace_once(pattern, replacement, label, flags=0):
    global html
    matches = list(re.finditer(pattern, html, flags))
    if len(matches) == 1:
        html = re.sub(pattern, replacement, html, count=1, flags=flags)
        print(f"OK  - {label}")
    elif len(matches) == 0:
        warnings.append(label)
        print(f"WARN - {label}: 0 matches")
    else:
        warnings.append(label)
        print(f"WARN - {label}: {len(matches)} matches (need exactly 1)")

# 1. Fireware OS version row
pattern = r'<tr><td><b>Fireware OS version</b></td><td><span class="chip c-plan">Pending</span></td><td class="muted">Confirm current version.*?</td></tr>'
replacement = ('<tr><td><b>Fireware OS version</b></td><td><span class="chip c-done">Confirmed</span></td>'
    '<td><b>12.11.6 (Build 728370)</b>. Confirmed 8 Jul 2026 by Intercity. '
    '<span style="color:var(--warn)">No management/patching service for the M390 has been procured from Intercity</span> &mdash; patch cadence is currently undefined.</td></tr>')
regex_replace_once(pattern, replacement, "Fireware OS version", flags=re.DOTALL)

# 2. VPN type & tunnel mode row
pattern = r'<tr><td><b>VPN type &amp; tunnel mode</b></td><td><span class="chip c-plan">Pending</span></td><td class="muted">Mobile VPN method.*?</td></tr>'
replacement = ('<tr><td><b>VPN type &amp; tunnel mode</b></td><td><span class="chip c-done">Confirmed</span></td>'
    '<td>SSL and IPSec both configured; Intercity report only SSL clients observed connecting in practice. <b>Split tunnel.</b></td></tr>')
regex_replace_once(pattern, replacement, "VPN type & tunnel mode", flags=re.DOTALL)

# 3. Inbound exposure row
pattern = r'<tr><td><b>Inbound exposure</b></td><td><span class="chip c-plan">Pending</span></td><td class="muted">Confirm published inbound.*?</td></tr>'
replacement = ('<tr><td><b>Inbound exposure</b></td><td><span class="chip c-done">Confirmed</span></td>'
    '<td>Full inbound rule set confirmed by Intercity 8 Jul 2026 &mdash; see full NAT/inbound rule table below. '
    '<b>No RDP (3389) inbound rule found</b> &mdash; port 3389 appears only in an AutoBlock (deny) rule.</td></tr>')
regex_replace_once(pattern, replacement, "Inbound exposure", flags=re.DOTALL)

# 4. Insert the NAT rule table panel before the "core finding" note.
# Use a stable, plain-ASCII anchor: the start of the note div with border-color rgba(255,93,93,.4) that follows the Perimeter table
nat_panel = '''<div class="panel reveal" style="overflow-x:auto;margin-top:16px">
         <h3 style="font-family:var(--disp);font-weight:700;font-size:14px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:12px">Confirmed inbound NAT / firewall rules &mdash; 8 Jul 2026</h3>
         <table>
           <tr><th>Source</th><th>Destination (NAT to)</th><th>Port / Service</th></tr>
           <tr><td>Remote users</td><td>Mobile VPN (SSL/IPSec)</td><td>VPN client access</td></tr>
           <tr><td>WaveNet</td><td>Firewall management</td><td>Admin access from specific servers</td></tr>
           <tr><td>Cyberguard</td><td><code>193.117.171.246</code> &rarr; <code>10.0.0.7</code></td><td>22 (SSH)</td></tr>
           <tr><td>Any external</td><td><code>213.210.38.226</code> &rarr; <code>10.0.30.200</code></td><td>443 (HTTPS)</td></tr>
           <tr><td>Cyberguard</td><td>&rarr; <code>10.0.0.5</code></td><td>8443 (HTTPS proxy)</td></tr>
           <tr><td>WaveNet</td><td>&rarr; <code>10.0.0.14</code></td><td>9000 (ESXi management)</td></tr>
           <tr><td>WaveNet</td><td>&rarr; <code>10.0.20.5</code></td><td>9001 (ESXi iLO)</td></tr>
           <tr><td>AutoBlock.OGL</td><td style="color:var(--fail)">Deny &rarr; Firebox</td><td>21, 22, 23, 139, 389, 445, 636, 3389, 137-138 (blocked)</td></tr>
           <tr><td>PhoneSystemVoIP</td><td>&rarr; <code>10.0.0.183</code></td><td>UDP 5060, TCP 10000-20000 (SIP)</td></tr>
         </table>
         <p class="sub" style="margin-top:10px">Source: Intercity, 8 Jul 2026. Port 3389 (RDP) appears only in the AutoBlock deny rule &mdash; no inbound allow rule found for RDP.</p>
       </div>

       '''
# Anchor: match the div opening tag that starts "The core finding" note (unique, plain ASCII except emoji which we avoid matching)
pattern = r'<div class="note reveal" style="margin-top:16px;animation-delay:\.04s;border-color:rgba\(255,93,93,\.4\);background:linear-gradient\(180deg,rgba\(255,93,93,\.06\),var\(--surface\)\)">\s*<h4 style="color:var\(--fail\)">'
matches = list(re.finditer(pattern, html))
if len(matches) >= 1:
    # Insert before the FIRST occurrence (the Perimeter section one, not the R&D one) -
    # find the one that appears after "Perimeter &amp; VPN" heading
    perimeter_idx = html.find('Perimeter &amp; VPN</h1>')
    target_match = None
    for m in matches:
        if m.start() > perimeter_idx:
            target_match = m
            break
    if target_match:
        html = html[:target_match.start()] + nat_panel + html[target_match.start():]
        print("OK  - Full inbound NAT rule table (new panel)")
    else:
        warnings.append("NAT rule table")
        print("WARN - Full inbound NAT rule table: could not find insertion point after Perimeter heading")
else:
    warnings.append("NAT rule table")
    print("WARN - Full inbound NAT rule table: anchor pattern not found at all")

PORTAL.write_text(html, encoding="utf-8")
print(f"\nFile size: {len(html)} bytes")
if warnings:
    print(f"\n{len(warnings)} WARNING(S) remain: {warnings}")
else:
    print("\nAll 4 remaining edits applied cleanly.")
print(f"Backup at: {BACKUP}")
