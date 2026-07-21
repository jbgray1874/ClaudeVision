r"""READ-ONLY. Two logo bugs: (1) SDI logo renders massive (no size constraint on its inline SVG),
(2) Milwaukee customer logo not found. Diagnose the Milwaukee lookup: show what customer string
gets derived, its normalised key, and whether it matches milwaukee.svg's normalised stem. Also
check the SDI svg's own width/height attrs (why it's massive). No edits — then I fix both."""
import os, re, json
ASSETS=r"C:\ClaudeVision\assets\customer_logos"

def norm(s): return re.sub(r"[^a-z0-9]","",(s or "").lower())

S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
stem=S.get("job_output_stem","")

print("="*66); print("1 — what customer gets derived"); print("="*66)
hay=" ".join([str(S.get("job_folder") or ""), str(stem),
    str((S.get("pdf_metadata",{}) or {}).get("/Title","")),
    str((S.get("drawing_metadata",{}).get("pdf_metadata",{}) or {}).get("/Title",""))])
print("  haystack (normalised):", norm(hay)[:120], "...")
print("\n  logo files + whether their stem appears in haystack:")
matched=None
for fn in sorted(os.listdir(ASSETS)):
    stem_fn=os.path.splitext(fn)[0]
    nk=norm(stem_fn)
    if nk=="wearesdi":
        print(f"    {fn:<20} stem_key={nk:<12} (SDI own logo — skipped)"); continue
    hit = nk and nk in norm(hay)
    print(f"    {fn:<20} stem_key={nk:<12} in_haystack={hit}")
    if hit and matched is None: matched=stem_fn
print(f"\n  -> derived customer would be: {matched!r}")
print(f"  -> its normalised key: {norm(matched) if matched else None}")

print("\n"+"="*66); print("2 — does that key match milwaukee.svg?"); print("="*66)
for fn in os.listdir(ASSETS):
    st,ext=os.path.splitext(fn)
    if norm(st)==norm(matched or ""):
        print(f"  MATCH: {fn} (norm {norm(st)}) == customer key {norm(matched or '')}")
        break
else:
    print(f"  NO FILE matches customer key {norm(matched or '')!r} — that's why no logo.")
    print("  milwaukee.svg norm stem =", norm("milwaukee"))

print("\n"+"="*66); print("3 — SDI svg width/height (why massive)"); print("="*66)
for fn in os.listdir(ASSETS):
    if norm(os.path.splitext(fn)[0])=="wearesdi":
        head=open(os.path.join(ASSETS,fn),encoding="utf-8",errors="replace").read(300)
        m=re.search(r"<svg[^>]*>", head)
        print("  <svg> tag:", m.group(0)[:200] if m else "(not found)")
        w=re.search(r'width="([^"]+)"', m.group(0)) if m else None
        h=re.search(r'height="([^"]+)"', m.group(0)) if m else None
        print(f"  width={w.group(1) if w else 'NONE'}  height={h.group(1) if h else 'NONE'}")
        print("  -> massive because the <svg> has large/no explicit px size and my span max-height")
        print("     doesn't constrain an SVG that lacks width/height (SVG needs the attrs capped).")
        break
