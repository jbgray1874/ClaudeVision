r"""
dxf_print_check.py — why is this DXF printing blank?

    python tools\dxf_print_check.py "K:\...\11908-21-01J.DXF"

RUNS THE ENGINE'S OWN CONVERTER, not a copy of it. The portal is a long-running Python
service: it imported printable_converters when it started, and a `git pull` does not change a
process that is already running. So a fix can be on disk, committed and pulled, and the page
that comes out of the portal is still yesterday's. This script is a fresh interpreter reading
the files as they are on disk now, which is the difference that settles it.

It prints, in order: the ezdxf in use, what the file holds and on which layers, whether those
layers are switched on, what the renderer actually recorded, and whether ink lands on the
page. Then it writes the PDF next to the DXF so it can be opened.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src = Path(argv[1]).expanduser()
    if not src.is_file():
        print(f"not a file: {src}")
        return 2

    import ezdxf
    import printable_converters as pc

    print(f"file          {src}")
    print(f"              {src.stat().st_size:,} bytes")
    print(f"ezdxf         {ezdxf.__version__}")
    print(f"converter     {Path(pc.__file__)}")
    # The one line that says whether the running portal has this fix in it at all.
    print(f"              blank-page check present: "
          f"{'yes' if hasattr(pc, '_ink_on_the_page') else 'NO — this checkout is older'}")
    print()

    try:
        doc = ezdxf.readfile(str(src))
    except Exception as exc:                                        # noqa: BLE001
        print(f"UNREADABLE: {type(exc).__name__}: {exc}")
        return 1

    msp = doc.modelspace()
    by_layer: dict = {}
    for e in msp:
        by_layer.setdefault(str(e.dxf.get("layer", "0")), []).append(e.dxftype())
    if not by_layer:
        print("MODEL SPACE IS EMPTY. Whatever is in this file is not in model space — check "
              "paper space, or the file is a stub.")

    print(f"{'layer':<28} {'state':<10} entities")
    for name, kinds in sorted(by_layer.items()):
        try:
            lay = doc.layers.get(name)
            state = ("OFF" if lay.is_off() else "frozen" if lay.is_frozen() else "on")
        except Exception:                                           # noqa: BLE001
            state = "?"
        counts = {}
        for k in kinds:
            counts[k] = counts.get(k, 0) + 1
        summary = ", ".join(f"{n}x{k}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        flag = "   <-- nothing on this layer will print" if state in ("OFF", "frozen") else ""
        print(f"{name:<28} {state:<10} {summary}{flag}")
    print()

    # What the RENDERER recorded, which is the only extents that matter. The DXF's own header
    # extents can be stale; this is measured from the entities as drawn.
    try:
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing import pymupdf as backend_mod
        from ezdxf.addons.drawing.config import (BackgroundPolicy, ColorPolicy,
                                                 Configuration)
        backend = backend_mod.PyMuPdfBackend()
        Frontend(RenderContext(doc), backend,
                 config=Configuration(background_policy=BackgroundPolicy.WHITE,
                                      color_policy=ColorPolicy.BLACK)
                 ).draw_layout(msp, finalize=True)
        box = backend.player().bbox()
        if not box.has_data:
            print("RECORDED NOTHING. The renderer drew no geometry at all — see the layer "
                  "states above.")
        else:
            w, h = box.size.x, box.size.y
            print(f"recorded      {w:,.1f} x {h:,.1f} drawing units")
            print(f"              from ({box.extmin.x:,.1f}, {box.extmin.y:,.1f}) "
                  f"to ({box.extmax.x:,.1f}, {box.extmax.y:,.1f})")
            if max(w, h) > 10_000:
                print("              ^ FAR LARGER THAN A PART. Something in this file sits a "
                      "long way from the geometry; fitted to a sheet it shrinks the part out "
                      "of sight. That is the blank page.")
    except Exception as exc:                                        # noqa: BLE001
        print(f"could not measure the drawing: {type(exc).__name__}: {exc}")
    print()

    out = src.with_name(src.stem + "_print_check.pdf")
    try:
        pc._dxf_to_pdf(src, out)
    except Exception as exc:                                        # noqa: BLE001
        print(f"CONVERSION REFUSED — {type(exc).__name__}")
        print(f"  {exc}")
        print("\nThis is the sentence that would appear on the pack's cover page.")
        return 1

    print(f"wrote         {out}")
    try:
        import pymupdf
        with pymupdf.open(str(out)) as pdf:
            r = pdf[0].rect
            print(f"page          {r.width / 72 * 25.4:.0f} x {r.height / 72 * 25.4:.0f} mm, "
                  f"{pdf.page_count} page(s)")
        ink = pc._ink_on_the_page(out)
        print(f"ink samples   {ink}")
        if ink == 0:
            print("\nTHE SHEET IS BLANK and the converter did not catch it. Send this output on.")
        elif ink:
            print("\nThe drawing is on the paper. If the portal still prints it blank, the "
                  "portal is running older code — restart the service.")
    except Exception as exc:                                        # noqa: BLE001
        print(f"could not inspect the PDF: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
