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
page. The PDFs it writes go to your TEMP folder, never into the job folder — a
diagnostic that adds files to a drawing pack changes the thing it is diagnosing.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
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

    # NOT BESIDE THE DRAWING. Written into the job folder, these land in the next run's
    # drawing pack and get read as drawings: 11908-21 was estimated from four PDFs where the
    # pack has two, both extras at geometry reliability 0.25. A diagnostic that changes the
    # thing it is diagnosing is worse than no diagnostic.
    out = Path(tempfile.gettempdir()) / (src.stem + "_print_check.pdf")
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

        # AND THE SAME QUESTION OF THE MERGED PACK, which is the file the estimator opens.
        # Asking only the intermediate is what let this report "the drawing is on the paper"
        # over a pack that was blank in Edge: ezdxf writes DXF layers as PDF optional content
        # groups, insert_pdf leaves the group definitions behind, and a viewer that honours
        # optional content hides every mark that points at a group the document no longer has.
        # MuPDF draws it regardless, so no measurement on the intermediate could ever see it.
        pack = out.with_name(out.stem + "_merged.pdf")
        merged = pymupdf.open()
        with pymupdf.open(str(out)) as one:
            merged.insert_pdf(one)
        merged.save(str(pack))
        merged.close()
        with pymupdf.open(str(out)) as one:
            groups_before = len(one.layer_ui_configs())
        with pymupdf.open(str(pack)) as many:
            groups_after = len(many.layer_ui_configs())
        print(f"pdf layers    {groups_before} on the page, {groups_after} after merging")
        if groups_before:
            print("              ^ THESE DO NOT SURVIVE THE MERGE. Every mark on the merged "
                  "page then points at a group the document no longer defines, and Acrobat "
                  "and Edge hide it. This checkout predates the fix — pull and re-run.")
        print(f"merged ink    {pc._ink_on_the_page(pack)}   ({pack.name})")

        if ink == 0:
            print("\nTHE SHEET IS BLANK and the converter did not catch it. Send this output on.")
        elif ink and not groups_before:
            print("\nThe drawing is on the paper and survives the merge.")
    except Exception as exc:                                        # noqa: BLE001
        print(f"could not inspect the PDF: {type(exc).__name__}: {exc}")

    _as_the_portal(src, out.with_name(out.stem + "_as_the_portal.pdf"))
    return 0


def _as_the_portal(src: Path, out: Path) -> None:
    """Run the command the PORTAL runs, with the interpreter the PORTAL uses.

    THE CONVERTER BEING RIGHT IS NOT THE SAME AS THE PORTAL USING IT. /api/drawings/print
    does not import anything — it shells out to src/drawings_print.py with _ENGINE_PYTHON,
    which is os.getenv("SDI_ENGINE_PYTHON", <repo>\\.venv\\Scripts\\python.exe). Set that
    variable to another interpreter, or to another checkout, and every fix lands in a copy of
    the code nothing runs, while the page keeps printing whatever the other one produces.

    Nothing above this line could ever see that: everything above runs in THIS interpreter.
    """
    print()
    print("── as the portal runs it " + "─" * 46)
    engine_python = os.getenv("SDI_ENGINE_PYTHON") or ""
    where_from = "the SDI_ENGINE_PYTHON environment variable"
    if not engine_python:
        for env_file in (ROOT / "sdi-intelligence-backend" / ".env", ROOT / ".env"):
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    if line.strip().startswith("SDI_ENGINE_PYTHON"):
                        engine_python = line.split("=", 1)[1].strip().strip('"').strip("'")
                        where_from = str(env_file)
            except OSError:
                continue
    if not engine_python:
        engine_python = str(ROOT / ".venv" / "Scripts" / "python.exe")
        where_from = "the built-in default (no SDI_ENGINE_PYTHON set)"

    print(f"engine python {engine_python}")
    print(f"              from {where_from}")
    print(f"this python   {sys.executable}")
    if Path(engine_python).resolve() != Path(sys.executable).resolve():
        print("              ^ DIFFERENT INTERPRETER FROM THE ONE THAT JUST PASSED. "
              "Everything above was measured in this one; the portal uses that one.")
    if not Path(engine_python).is_file():
        print("              ^ AND IT DOES NOT EXIST. The portal's print endpoint cannot "
              "run at all — set SDI_ENGINE_PYTHON to a real interpreter.")
        return

    cli = ROOT / "src" / "drawings_print.py"
    cmd = [engine_python, str(cli), str(src), "--out", str(out), "--json"]
    print("command       " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as exc:                                        # noqa: BLE001
        print(f"              FAILED TO RUN: {type(exc).__name__}: {exc}")
        return
    if proc.returncode != 0:
        print(f"              exit {proc.returncode}")
    for stream, label in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        for line in (stream or "").strip().splitlines()[-8:]:
            print(f"  {label}      {line}")
    if not out.is_file():
        print("              no file produced — the reason is above.")
        return
    try:
        import pymupdf
        import printable_converters as pc
        with pymupdf.open(str(out)) as doc:
            r = doc[0].rect
            print(f"portal pdf    {r.width / 72 * 25.4:.0f} x {r.height / 72 * 25.4:.0f} mm, "
                  f"{doc.page_count} page(s), {len(doc.layer_ui_configs())} pdf layer(s)")
        print(f"portal ink    {pc._ink_on_the_page(out)}   ({out.name})")
        print("\nOPEN THAT FILE in the reader you print from. It is byte-for-byte what the "
              "portal hands you. If it shows the drawing and the portal does not, the fault "
              "is in the portal's delivery, not in the drawing or the converter.")
    except Exception as exc:                                        # noqa: BLE001
        print(f"              could not inspect it: {type(exc).__name__}: {exc}")
    except Exception as exc:                                        # noqa: BLE001
        print(f"could not inspect the PDF: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
