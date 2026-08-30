"""
fix_perimeter_vpn.py — Updates the Perimeter & VPN table and adds new
confirmed findings from Intercity's response (8 Jul 2026), plus updates
the ESXi HA and backup ownership notes on the Server Infrastructure page.

Run on the LAPTOP against the current sdi-intelligence-portal.html,
then deploy the result to the server as usual (laptop -> share -> server).
No service restart needed - static HTML.
"""
import shutil
from pathlib import Path

PORTAL = Path(r"C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html")
BACKUP = PORTAL.with_name("sdi-intelligence-portal_pre_perimeter_update.html")

shutil.copy2(PORTAL, BACKUP)
print(f"Backed up to {BACKUP}")

html = PORTAL.read_text(encoding="utf-8")
warnings = []

def replace_once(old, new, label):
    global html
    count = html.count(old)
    if count == 1:
        html = html.replace(old, new, 1)
        print(f"OK  - {label}")
    elif count == 0:
        warnings.append(f"NOT FOUND - {label}")
        print(f"WARN - {label}: pattern not found, skipped")
    else:
        warnings.append(f"MULTIPLE ({count}) - {label}")
        print(f"WARN - {label}: found {count} times, skipped (needs unique match)")

# ---- 1. Fireware OS version row ----
old = '''<tr><td><b>Fireware OS version</b></td><td><span class="chip c-plan">Pending</span></td><td class="muted">Confirm current version &amp; patch status with Intercity &mdash; only outstanding firewall fitness item.</td></tr>'''
new = '''<tr><td><b>Fireware OS version</b></td><td><span class="chip c-done">Confirmed</span></td><td><b>12.11.6 (Build 728370)</b>. Confirmed 8 Jul 2026 by Intercity. <span style="color:var(--warn)">No management/patching service for the M390 has been procured from Intercity</span> &mdash; patch cadence is currently undefined.</td></tr>'''
replace_once(old, new, "Fireware OS version")

# ---- 2. VPN type & tunnel mode row ----
old = '''<tr><td><b>VPN type &amp; tunnel mode</b></td><td><span class="chip c-plan">Pending</span></td><td class="muted">Mobile VPN method (SSL / IKEv2 / IPSec) and split vs full tunnel &mdash; confirm on console.</td></tr>'''
new = '''<tr><td><b>VPN type &amp; tunnel mode</b></td><td><span class="chip c-done">Confirmed</span></td><td>SSL and IPSec both configured; Intercity report only SSL clients observed connecting in practice. <b>Split tunnel.</b></td></tr>'''
replace_once(old, new, "VPN type & tunnel mode")

# ---- 3. VPN authentication row ----
old = '''<tr><td><b>VPN authentication</b></td><td><span class="chip c-prog">Partial</span></td><td>AD-integrated via WatchGuard Auth Gateway + SSO. <b>No MFA confirmed</b> on the mobile VPN today.</td></tr>'''
new = '''<tr><td><b>VPN authentication</b></td><td><span class="chip c-prog">Partial</span></td><td>AD-integrated via WatchGuard Auth Gateway + SSO. <b>No MFA on the mobile VPN today &mdash; confirmed.</b> Intercity recommend <b>RADIUS &rarr; Entra ID</b> (simplest, fully supported by WatchGuard) over AuthPoint. This is also the agreed MFA route for the planned Fortigate migration.</td></tr>'''
replace_once(old, new, "VPN authentication")

# ---- 4. VPN scope / routing row ----
old = '''<tr><td><b>VPN scope / routing</b></td><td style="color:var(--warn)"><span class="chip" style="background:rgba(255,157,66,.15);color:var(--warn);border-color:rgba(255,157,66,.3)">Risk</span></td><td>Confirm whether connected users reach all internal subnets or are scoped by role.</td></tr>'''
new = '''<tr><td><b>VPN scope / routing</b></td><td style="color:var(--fail)"><span class="chip" style="background:rgba(255,93,93,.12);color:var(--fail);border-color:rgba(255,93,93,.25)">Confirmed risk</span></td><td><b>All internal subnets reachable &mdash; not scoped by role.</b> Confirmed by Intercity 8 Jul 2026, who also confirmed this was never designed/implemented/maintained by them and <b>will be revised for the planned Fortigate installation</b>.</td></tr>'''
replace_once(old, new, "VPN scope / routing")

# ---- 5. Inbound exposure row ----
old = '''<tr><td><b>Inbound exposure</b></td><td><span class="chip c-plan">Pending</span></td><td class="muted">Confirm published inbound rules &mdash; especially that RDP (3389) is not internet-facing. Public/WAN IP &amp; link redundancy.</td></tr>'''
new = '''<tr><td><b>Inbound exposure</b></td><td><span class="chip c-done">Confirmed</span></td><td>Full inbound rule set confirmed by Intercity 8 Jul 2026 &mdash; see full NAT/inbound rule table below. <b>No RDP (3389) inbound rule found</b> &mdash; port 3389 appears only in an AutoBlock (deny) rule.</td></tr>'''
replace_once(old, new, "Inbound exposure")

# ---- 6. NEW ROW: LiveSecurity subscription (insert after Logging/reporting row) ----
old = '''<tr><td><b>Logging / reporting</b></td><td><span class="chip c-done">Confirmed</span></td><td>WatchGuard <b>Dimensions</b> in use (traffic logging &amp; reporting) with a log encryption key on record.</td></tr>'''
new = '''<tr><td><b>Logging / reporting</b></td><td><span class="chip c-done">Confirmed</span></td><td>WatchGuard <b>Dimensions</b> in use (traffic logging &amp; reporting) with a log encryption key on record.</td></tr>
          <tr><td><b>LiveSecurity subscription</b></td><td style="color:var(--fail)"><span class="chip" style="background:rgba(255,93,93,.12);color:var(--fail);border-color:rgba(255,93,93,.25)">Expired</span></td><td><b>Expired 5 June 2026.</b> No active threat-intelligence / signature update feed on the M390 &mdash; the firewall is currently running without vendor security updates. Renewal action required.</td></tr>'''
replace_once(old, new, "LiveSecurity subscription (new row)")

# ---- 7. NEW ROW: Public/WAN IP ----
old = '''<tr><td><b>VPN scope / routing</b></td><td style="color:var(--fail)"><span class="chip" style="background:rgba(255,93,93,.12);color:var(--fail);border-color:rgba(255,93,93,.25)">Confirmed risk</span></td><td><b>All internal subnets reachable &mdash; not scoped by role.</b> Confirmed by Intercity 8 Jul 2026, who also confirmed this was never designed/implemented/maintained by them and <b>will be revised for the planned Fortigate installation</b>.</td></tr>'''
new = old + '''
          <tr><td><b>Public / WAN IP &amp; redundancy</b></td><td><span class="chip c-done">Confirmed</span></td><td>Two public IPs on record: <code>213.210.38.226</code> and <code>193.117.171.246</code>. Link redundancy not explicitly confirmed &mdash; follow up if dual-IP implies dual-circuit failover.</td></tr>'''
replace_once(old, new, "Public/WAN IP (new row)")

# ---- 8. NEW PANEL: full inbound NAT rule table, inserted after the Perimeter & VPN table's closing </table></div> ----
old = '''<div class="note reveal" style="margin-top:16px;animation-delay:.04s;border-color:rgba(255,93,93,.4);background:linear-gradient(180deg,rgba(255,93,93,.06),var(--surface))">
         <h4 style="color:var(--fail)">âš  The core finding â€” remote access is unconsolidated and unprotected by MFA</h4>'''
if old not in html:
    old = '''<div class="note reveal" style="margin-top:16px;animation-delay:.04s;border-color:rgba(255,93,93,.4);background:linear-gradient(180deg,rgba(255,93,93,.06),var(--surface))">
         <h4 style="color:var(--fail)">⚠ The core finding — remote access is unconsolidated and unprotected by MFA</h4>'''
new_panel = '''<div class="panel reveal" style="overflow-x:auto;margin-top:16px">
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

       ''' + old
replace_once(old, new_panel, "Full inbound NAT rule table (new panel)")

# ---- 9. Update the "Do we need a new VPN" note to mention Fortigate ----
old = '''<b>Recommendation: configure and consolidate the existing WatchGuard â€” don\\'t replace it â€” unless the fitness check fails.</b>'''
if old not in html:
    old = '''<b>Recommendation: configure and consolidate the existing WatchGuard — don't replace it — unless the fitness check fails.</b>'''
new = '''<b>Update 8 Jul 2026:</b> Intercity have confirmed a <b>Fortigate migration is already planned</b>, which will include VPN role-scoping and Entra ID MFA. Given the M390\\'s <b>expired LiveSecurity subscription</b> and <b>no procured management/patching service</b>, the practical recommendation is to treat the Fortigate migration as the fix for these gaps, and prioritise it accordingly rather than trying to fully remediate the M390 in the interim.'''
replace_once(old, new, "VPN recommendation note (Fortigate update)")

# ---- 10. ESXi HA — update from "verify" to "confirmed NOT clustered" ----
old = '''<text x="372" y="386" text-anchor="middle" font-size="9" fill="#5fd08a" font-style="italic">Confirmed: 2 ESXi hosts (SDI-ESXi01 DL380 G10, SDI-ESXi02) + vCenter — HA-capable, clustering to verify</text>'''
new = '''<text x="372" y="386" text-anchor="middle" font-size="9" fill="#ff9d42" font-style="italic">Confirmed 8 Jul 2026: 2 ESXi hosts running STANDALONE, not clustered — no HA/vMotion failover</text>'''
replace_once(old, new, "ESXi HA status in architecture diagram (SVG text)")

# ---- 11. ESXi HA note in the "good foundations" or asset register text ----
old = '''<tr><td>SDI-ESXi02</td><td>Second ESXi host (ESXi 8, with iLO). <b>Two hosts = HA failover capability</b> — confirm cluster config.</td></tr>'''
new = '''<tr><td>SDI-ESXi02</td><td>Second ESXi host (ESXi 8, with iLO). <b style="color:var(--fail)">Confirmed 8 Jul 2026: running standalone, NOT clustered</b> — no automatic VM failover on host failure. VM storage is local per-host on RAID (tolerates disk failure, not host failure).</td></tr>'''
replace_once(old, new, "ESXi asset register row (standalone confirmed)")

# ---- 12. Backup ownership — add confirmed findings note ----
old = '''<h3 style="font-family:var(--disp);font-weight:700;font-size:17px;margin:34px 0 8px">Wider infrastructure &amp; asset register</h3>'''
new = '''<div class="note reveal" style="margin-top:16px;border-color:rgba(255,93,93,.4);background:linear-gradient(180deg,rgba(255,93,93,.06),var(--surface))">
        <h4 style="color:var(--fail)">⚠ Backup, DR &amp; ESXi HA — confirmed 8 Jul 2026, unresolved</h4>
        Intercity have confirmed the following are <b>owned and managed entirely by WaveNet</b>, not Intercity, and none of the following could be answered directly:
        <ul style="margin:8px 0 0 18px;line-height:1.9">
          <li>What Veeam protects vs what Datto protects, and the schedule/retention for each</li>
          <li>Whether backups are held off-site and immutable (ransomware-resilient)</li>
          <li>When a restore was last tested, and whether there is evidence of a successful test restore</li>
          <li>Expected recovery time for a single server, and for a full-site loss</li>
          <li>Recovery path and expected recovery time for ACCESS-DB01 (production ERP) specifically if that host fails — <b>ESXi hosts are confirmed standalone with no HA</b>, so this is a real, unquantified exposure</li>
        </ul>
        <b style="display:block;margin-top:10px">Action needed:</b> raise all five directly with WaveNet — this is the single largest unresolved DR gap in the estate.
      </div>

      <h3 style="font-family:var(--disp);font-weight:700;font-size:17px;margin:34px 0 8px">Wider infrastructure &amp; asset register</h3>'''
replace_once(old, new, "Backup/DR ownership note (new)")

# ---- 13. Monitoring & governance — add Ninja/CrowdStrike detail ----
old = '''<b>Endpoint security &amp; backup present</b> — CrowdStrike Falcon, Datto backup, NinjaRMM and Sysmon across the estate.'''
new = '''<b>Endpoint security &amp; backup present</b> — CrowdStrike Falcon, Datto backup, NinjaRMM and Sysmon across the estate. <b>Confirmed 8 Jul 2026:</b> NinjaRMM alerts on OS patches (CVSS &ge;7.0, 14+ days outstanding), device down 20 min, disk active time &gt;90% for 60 min, disk free &lt;15%, high CPU/memory, and SMART degraded status &mdash; visible to helpdesk engineers in the Ninja console. <b style="color:var(--warn)">No information available on CrowdStrike alerting/ownership.</b> Ninja covers endpoints and servers only &mdash; <b style="color:var(--warn)">network devices (switches, APs) are not monitored</b>. Windows server patching (once in full support) will be monthly via Ninja, delayed 7 days after Patch Tuesday.'''
replace_once(old, new, "NinjaRMM/CrowdStrike monitoring detail")

PORTAL.write_text(html, encoding="utf-8")
print(f"\nFile size: {len(html)} bytes")
if warnings:
    print(f"\n{len(warnings)} WARNING(S) — these did not apply cleanly, check manually:")
    for w in warnings:
        print(f"  - {w}")
else:
    print("\nAll edits applied cleanly.")
print(f"\nBackup at: {BACKUP}")
