r"""READ-ONLY. CONTRADICTION: standalone probe FINDS 1282's manual, but the deployed helper said
'no manual found'. So the bug is in what the helper receives, not the glob. Prime suspect: the job
number extraction. scan_label = '1282 - Milwaukee Wall Bay'; split('-')[0] = '1282 ' (TRAILING
SPACE) -> glob '*1282 *' won't match '1282-' folders.
Reproduce EXACTLY what the deployed helper does with the real scan_label and show job_num + whether
its glob hits. No edits — confirm the trailing-space (or other) bug."""
import os, glob

# the scan_label for a --folder-as-job run is the folder name:
scan_label = "1282 - Milwaukee Wall Bay"
print("="*66); print("what the helper extracts"); print("="*66)
job_num = str(scan_label).split("-")[0].strip()   # helper HAS .strip()
job_num_nostrip = str(scan_label).split("-")[0]    # what it'd be WITHOUT strip
print(f"  scan_label          = {scan_label!r}")
print(f"  split('-')[0]        = {job_num_nostrip!r}  (len {len(job_num_nostrip)})")
print(f"  .strip() applied     = {job_num!r}  (len {len(job_num)})")
print(f"  -> helper uses job_num = {job_num!r}")

# now run the helper's EXACT glob logic with that job_num
share_root = r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates"
print("\n"+"="*66); print(f"helper's glob with job_num={job_num!r}"); print("="*66)
candidates=[]
for year_dir in sorted(glob.glob(os.path.join(share_root, "20*")), reverse=True):
    g1=glob.glob(os.path.join(year_dir, "*", "*"+job_num+"*", "*.xls"))
    g2=glob.glob(os.path.join(year_dir, "*"+job_num+"*", "*.xls"))
    candidates += g1 + g2
seen=[c for c in candidates if not os.path.basename(c).startswith("~$")]
print(f"  hits: {len(seen)}")
for s in seen[:4]: print(f"    {s}")
print(f"\n  -> helper returns: {seen[0] if seen else None}")

if seen:
    print("\n  *** So with job_num='1282' the glob WORKS. If the run still missed, the scan_label")
    print("      inside main.py at deliverables-time is DIFFERENT (maybe includes the .PDF stem or")
    print("      a path). Check: what is scan_label actually set to at line 428 vs 447? ***")
else:
    print("\n  *** Confirmed: this job_num doesn't match. Fix the extraction. ***")

# Also: could scan_label at deliverables time be a PDF filename (line 447) not the folder?
print("\n"+"="*66); print("is scan_label maybe a PDF stem, not the folder? (main.py 428 vs 447)"); print("="*66)
print("  line 428: scan_label = job_folder.name   (folder-as-job -> '1282 - Milwaukee Wall Bay')")
print("  line 447: scan_label = drawing_path.name  (single file -> '1282....PDF')")
print("  If the run took the single-file path, scan_label='1282 - Milwaukee 500mm...PDF' and")
print("  split('-')[0].strip()='1282' still OK... so job_num is probably fine. The real question")
print("  is whether _find_manual_workbook is even being REACHED with the right scan_label.")
