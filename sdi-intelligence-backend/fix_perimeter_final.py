"""
fix_perimeter_final.py — Applies the 9 remaining edits (VPN auth, VPN scope,
LiveSecurity row, Public IP row, VPN recommendation note, ESXi SVG text,
ESXi asset row, Backup/DR panel, Ninja/CrowdStrike detail, NAT table).
Matches the file confirmed to already have: Fireware, VPN type, Inbound
exposure done. Uses regex throughout to avoid character-encoding issues.
"""
import re, shutil
from pathlib import Path

PORTAL = Path(r"C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html")
BACKUP = PORTAL.with_name("sdi-intelligence-portal_pre_final.html")
shutil.copy2(PORTAL, BACKUP)
print(f"Backed up to {BACKUP}")

html = PORTAL.read_text(encoding="utf-8")
warnings = []

def rx(pattern, replacement, label, flags=re.DOTALL):
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
        print(f"WARN - {label}: {len(matches)} matches")

# 1. VPN authentication row
rx(
    r'<tr><td><b>VPN authentication</b></td><td><span class="chip c-prog">Partial</span></td><td>AD-integrated via WatchGuard Auth Gateway \+ SSO\. <b>No MFA confirmed</b> on the mobile VPN today\.</td></tr>',
    '<tr><td><b>VPN authentication</b></td><td><span class="chip c-prog">Partial</span></td>'
    '<td>AD-integrated via WatchGuard Auth Gateway + SSO. <b>No MFA on the mobile VPN today &mdash; confirmed.</b> '
    'Intercity recommend <b>RADIUS &rarr; Entra ID</b> (simplest, fully supported by WatchGuard) over AuthPoint. '
    'This is also the agreed MFA route for the planned Fortigate migration.</td></tr>',
    "VPN authentication"
)

# 2. VPN scope / routing row
rx(
    r'<tr><td><b>VPN scope / routing</b></td><td style="color:var\(--warn\)"><span class="chip" style="background:rgba\(255,157,66,\.15\);color:var\(--warn\);border-color:rgba\(255,157,66,\.3\)">Risk</span></td><td>Confirm whether connected users reach all internal subnets or are scoped by role\.</td></tr>',
    '<tr><td><b>VPN scope / routing</b></td><td style="color:var(--fail)"><span class="chip" style="background:rgba(255,93,93,.12);color:var(--fail);border-color:rgba(255,93,93,.25)">Confirmed risk</span></td>'
    '<td><b>All internal subnets reachable &mdash; not scoped by role.</b> Confirmed by Intercity 8 Jul 2026, who also confirmed this was '
    'never designed/implemented/maintained by them and <b>will be revised for the planned Fortigate installation</b>.</td></tr>',
    "VPN scope / routing"
)

# 3. LiveSecurity new row - insert after Logging/reporting row
rx(
    r'(<tr><td><b>Logging / reporting</b></td><td><span class="chip c-done">Confirmed</span></td><td>WatchGuard <b>Dimensions</b> in use \(traffic logging &amp; reporting\) with a log encryption key on record\.</td></tr>)',
    r'\1\n          <tr><td><b>LiveSecurity subscription</b></td><td style="color:var(--fail)"><span class="chip" style="background:rgba(255,93,93,.12);color:var(--fail);border-color:rgba(255,93,93,.25)">Expired</span></td>'
    '<td><b>Expired 5 June 2026.</b> No active threat-intelligence / signature update feed on the M390 &mdash; the firewall is currently running without vendor security updates. Renewal action required.</td></tr>',
    "LiveSecurity subscription (new row)"
)

# 4. Public/WAN IP new row - insert after Inbound exposure row (now confirmed present)
rx(
    r'(<tr><td><b>Inbound exposure</b></td><td><span class="chip c-done">Confirmed</span></td><td>Full inbound rule set confirmed by Intercity 8 Jul 2026.*?</td></tr>)',
    r'\1\n          <tr><td><b>Public / WAN IP &amp; redundancy</b></td><td><span class="chip c-done">Confirmed</span></td>'
    '<td>Two public IPs on record: <code>213.210.38.226</code> and <code>193.117.171.246</code>. Link redundancy not explicitly confirmed &mdash; follow up if dual-IP implies dual-circuit failover.</td></tr>',
    "Public/WAN IP (new row)"
)

# 5. VPN recommendation note - Fortigate update
rx(
    r'<b>Recommendation: configure and consolidate the existing WatchGuard.{0,5}don.{0,3}t replace it.{0,5}unless the fitness check fails\.</b>',
    "<b>Update 8 Jul 2026:</b> Intercity have confirmed a <b>Fortigate migration is already planned</b>, which will include VPN role-scoping and Entra ID MFA. "
    "Given the M390's <b>expired LiveSecurity subscription</b> and <b>no procured management/patching service</b>, the practical recommendation is to treat the "
    "Fortigate migration as the fix for these gaps, and prioritise it accordingly rather than trying to fully remediate the M390 in the interim.",
    "VPN recommendation note (Fortigate update)"
)

# 6. ESXi HA status in SVG text
rx(
    r'<text x="372" y="386" text-anchor="middle" font-size="9" fill="#5fd08a" font-style="italic">Confirmed: 2 ESXi hosts \(SDI-ESXi01 DL380 G10, SDI-ESXi02\) \+ vCenter.{0,5}HA-capable, clustering to verify</text>',
    '<text x="372" y="386" text-anchor="middle" font-size="9" fill="#ff9d42" font-style="italic">Confirmed 8 Jul 2026: 2 ESXi hosts running STANDALONE, not clustered &mdash; no HA/vMotion failover</text>',
    "ESXi HA status (SVG text)"
)

# 7. ESXi asset register row
rx(
    r'<tr><td>SDI-ESXi02</td><td>Second ESXi host \(ESXi 8, with iLO\)\. <b>Two hosts = HA failover capability</b>.{0,5}confirm cluster config\.</td></tr>',
    '<tr><td>SDI-ESXi02</td><td>Second ESXi host (ESXi 8, with iLO). '
    '<b style="color:var(--fail)">Confirmed 8 Jul 2026: running standalone, NOT clustered</b> &mdash; no automatic VM failover on host failure. '
    'VM storage is local per-host on RAID (tolerates disk failure, not host failure).</td></tr>',
    "ESXi asset register row"
)

# 8. Ninja/CrowdStrike monitoring detail
rx(
    r'<b>Endpoint security &amp; backup present</b> — CrowdStrike Falcon, Datto backup, NinjaRMM and Sysmon across the estate\.',
    "<b>Endpoint security &amp; backup present</b> — CrowdStrike Falcon, Datto backup, NinjaRMM and Sysmon across the estate. "
    "<b>Confirmed 8 Jul 2026:</b> NinjaRMM alerts on OS patches (CVSS &ge;7.0, 14+ days outstanding), device down 20 min, disk active time &gt;90% for 60 min, "
    "disk free &lt;15%, high CPU/memory, and SMART degraded status &mdash; visible to helpdesk engineers in the Ninja console. "
    "<b style=\"color:var(--warn)\">No information available on CrowdStrike alerting/ownership.</b> Ninja covers endpoints and servers only &mdash; "
    "<b style=\"color:var(--warn)\">network devices (switches, APs) are not monitored</b>. Windows server patching (once in full support) will be monthly via Ninja, delayed 7 days after Patch Tuesday.",
    "Ninja/CrowdStrike monitoring detail"
)

# 9. Backup/DR ownership panel - insert before "Wider infrastructure & asset register" h3
backup_panel = '''<div class="note reveal" style="margin-top:16px;border-color:rgba(255,93,93,.4);background:linear-gradient(180deg,rgba(255,93,93,.06),var(--surface))">
        <h4 style="color:var(--fail)">&#9888; Backup, DR &amp; ESXi HA — confirmed 8 Jul 2026, unresolved</h4>
        Intercity have confirmed the following are <b>owned and managed entirely by WaveNet</b>, not Intercity, and none of the following could be answered directly:
        <ul style="margin:8px 0 0 18px;line-height:1.9">
          <li>What Veeam protects vs what Datto protects, and the schedule/retention for each</li>
          <li>Whether backups are held off-site and immutable (ransomware-resilient)</li>
          <li>When a restore was last tested, and whether there is evidence of a successful test restore</li>
          <li>Expected recovery time for a single server, and for a full-site loss</li>
          <li>Recovery path and expected recovery time for ACCESS-DB01 (production ERP) specifically if that host fails &mdash; <b>ESXi hosts are confirmed standalone with no HA</b>, so this is a real, unquantified exposure</li>
        </ul>
        <b style="display:block;margin-top:10px">Action needed:</b> raise all five directly with WaveNet &mdash; this is the single largest unresolved DR gap in the estate.
      </div>

      '''
rx(
    r'(<h3 style="font-family:var\(--disp\);font-weight:700;font-size:17px;margin:34px 0 8px">Wider infrastructure &amp; asset register</h3>)',
    backup_panel + r'\1',
    "Backup/DR ownership panel (new)"
)

# 10. NAT rule table - insert before the "core finding" note div, after the Perimeter table close
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
# Anchor on the closing </table></div> right after the Perimeter & VPN table (unique via preceding Public IP row)
matches = list(re.finditer(r'(<tr><td><b>Public / WAN IP &amp; redundancy</b></td>.*?</tr>\s*</table>\s*</div>)', html, re.DOTALL))
if len(matches) == 1:
    m = matches[0]
    html = html[:m.end()] + "\n      " + nat_panel.rstrip() + html[m.end():]
    print("OK  - NAT rule table (inserted after Perimeter table)")
else:
    warnings.append("NAT rule table")
    print(f"WARN - NAT rule table: anchor found {len(matches)} times (need 1) - insert manually after Public IP row's table")

PORTAL.write_text(html, encoding="utf-8")
print(f"\nFile size: {len(html)} bytes")
if warnings:
    print(f"\n{len(warnings)} WARNING(S): {warnings}")
else:
    print("\nAll 10 edits applied cleanly. Combined with the 3 already done = 13/13.")
print(f"Backup at: {BACKUP}")
