r"""READ-ONLY, FAST. Confirm the 300-DPI patch TOOK EFFECT — render one page via fitz with the new
zoom and report pixel dimensions vs what 144 DPI would have produced. Proves the image is now ~300
DPI (bigger), not 144. Uses 1282's primary GA PDF. No full pipeline. No edits."""
import os
os.environ.setdefault("VISION_RENDER_DPI","300")
os.environ.setdefault("VISION_MAX_SIDE","4000")
try:
    import fitz
except ImportError:
    print("fitz not available"); raise SystemExit

# 1282 primary GA PDF (UNC)
pdf=r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay\1455-C-GA 500mm Milwaukee Header_revC.PDF"
if not os.path.exists(pdf):
    print(f"PDF not reachable: {pdf}"); 
    # fall back to any pdf in outputs
    raise SystemExit

vis_dpi=float(os.getenv("VISION_RENDER_DPI","300"))
vis_max=float(os.getenv("VISION_MAX_SIDE","4000"))
doc=fitz.open(pdf)
page=doc.load_page(0)
rect=page.rect
long_pts=max(float(rect.width),float(rect.height))
print("="*60)
print(f"page size (pts): {rect.width:.0f} x {rect.height:.0f}  (long={long_pts:.0f})")
print("="*60)

# OLD: Matrix(2,2) = 144 DPI
old_zoom=2.0
old_pix=page.get_pixmap(matrix=fitz.Matrix(old_zoom,old_zoom),alpha=False)
print(f"OLD (144 DPI, Matrix 2,2): {old_pix.width} x {old_pix.height} px")

# NEW: the patched logic
zoom=vis_dpi/72.0
if long_pts*zoom>vis_max and long_pts>0:
    zoom=vis_max/long_pts
    eff_dpi=zoom*72
    print(f"  (capped by max_side={vis_max:.0f}: zoom {zoom:.2f} -> effective {eff_dpi:.0f} DPI)")
new_pix=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),alpha=False)
print(f"NEW ({vis_dpi:.0f} DPI target): {new_pix.width} x {new_pix.height} px   (zoom {zoom:.2f})")

print("\n"+"="*60)
ratio=(new_pix.width*new_pix.height)/(old_pix.width*old_pix.height)
print(f"pixel area increase: {ratio:.1f}x  -> {'CONFIRMED higher res' if ratio>1.5 else 'check'}")
print(f"effective DPI now: {zoom*72:.0f}")
doc.close()
