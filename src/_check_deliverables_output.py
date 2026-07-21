r"""READ-ONLY. JG sees a client quote + spreadsheet in output\estimates but NO parity report. Find
out exactly what's there and why parity didn't generate. Two likely causes:
  (a) the --deliverables run's parity branch hit 'no manual found' (the lookup glob didn't match
      1282's folder), OR
  (b) the parity generator errored (failure-isolated, so it logged + continued).
Check:
  1) List output\estimates — what files exist, with timestamps (which run produced them).
  2) Test the manual-lookup DIRECTLY: does _find_manual_workbook's glob find 1282's .xls?
     (1282 manual: \\sdi-dc01\...\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\...xls)
  3) Show what the glob patterns actually match for job number '1282'.
No edits — diagnose why parity is missing."""
import os, glob, datetime

def ts(p):
    try: return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M:%S")
    except: return "?"

print("="*66); print("1 — what's in output\\estimates (recent files)"); print("="*66)
d=r"C:\ClaudeVision\output\estimates"
if os.path.isdir(d):
    fs=sorted(glob.glob(os.path.join(d,"*")), key=os.path.getmtime, reverse=True)
    for p in fs[:15]:
        print(f"  {ts(p)}  {os.path.basename(p)}")
else:
    print("  (dir not found)")

print("\n"+"="*66); print("2 — does the manual-lookup glob find 1282's .xls?"); print("="*66)
share_root = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
print(f"  share root exists: {os.path.isdir(share_root)}")
job_num = "1282"
if os.path.isdir(share_root):
    years=sorted(glob.glob(os.path.join(share_root,"20*")), reverse=True)
    print(f"  year dirs found: {[os.path.basename(y) for y in years][:6]}")
    hits=[]
    for year_dir in years:
        g1=os.path.join(year_dir, "*", "*"+job_num+"*", "*.xls")
        g2=os.path.join(year_dir, "*"+job_num+"*", "*.xls")
        m1=glob.glob(g1); m2=glob.glob(g2)
        if m1 or m2:
            print(f"  {os.path.basename(year_dir)}:")
            print(f"    pattern <year>\\*\\*1282*\\*.xls  -> {len(m1)} hit(s)")
            for x in m1[:3]: print(f"       {x}")
            print(f"    pattern <year>\\*1282*\\*.xls    -> {len(m2)} hit(s)")
            for x in m2[:3]: print(f"       {x}")
            hits+=m1+m2
    if not hits:
        print("  NO HITS — the glob didn't match. Let's see WHY: list 2026\\TTI contents:")
        tti=os.path.join(share_root,"2026","TTI")
        if os.path.isdir(tti):
            for sub in sorted(os.listdir(tti))[:20]:
                subp=os.path.join(tti,sub)
                print(f"    2026\\TTI\\{sub}")
                if os.path.isdir(subp) and "1282" in sub:
                    for f in os.listdir(subp)[:10]:
                        print(f"       -> {f}  (ext={os.path.splitext(f)[1]})")
        else:
            print(f"    2026\\TTI not found. 2026 contents:")
            y2026=os.path.join(share_root,"2026")
            if os.path.isdir(y2026):
                for sub in sorted(os.listdir(y2026))[:20]: print(f"       {sub}")
    else:
        # apply the same de-dupe as the helper
        seen=[c for c in hits if not os.path.basename(c).startswith("~$")]
        print(f"\n  -> helper would return: {seen[0] if seen else None}")
