#!/usr/bin/env python3
r"""report_pdf.py — a status report ships in BOTH formats, and can be taken away.

WHY THIS IS A TOOL AND NOT A COMMAND SOMEBODY REMEMBERS.

The status reports are opened from the SDI Intelligence portal, which serves a folder of
files. A report that exists only as HTML cannot be attached to an e-mail or read on a phone;
one that exists only as a PDF cannot be linked to, searched, or read in either theme. Both
formats, every time, or the reader gets whichever one the author happened to make.

Two jobs, in this order:

  1. INJECT THE DOWNLOAD BAR, once, into the HTML. It has to work in three places, because
     that is where these reports are actually opened:

       - from disk or the K: share       -> the PDF is the sibling file, "X.pdf"
       - from the portal, /api/file?path=... -> the PDF is the same query with the extension
                                            swapped, because a RELATIVE href would resolve
                                            against /api/ and 404
       - inside the artifact viewer      -> a sandbox that blocks page-driven downloads

     So the PDF link resolves its own href at run time from location.href, and "Save this
     page" builds a Blob from the document itself, which a sandbox with allow-downloads
     permits and a file:// page permits. The portal already serves these pages with
     `sandbox allow-downloads allow-popups`, which is what makes the second one work there.

     The bar is hidden in print, so the PDF never contains a control pointing at itself.

  2. PRINT THE PDF, with the same page setup every time. A4, backgrounds on, 14/12 mm
     margins — so the whole set looks like one set rather than six.

USAGE
    python tools/report_pdf.py --all                  # every report in reports/
    python tools/report_pdf.py reports/X.html         # one of them
    python tools/report_pdf.py --all --bar-only       # inject, don't print (no browser needed)

Files whose name starts with "_" are skipped: they are fragments and includes, not reports.

PLAYWRIGHT IS OPTIONAL AND ITS ABSENCE IS NOT A FAILURE. On a machine without it the bar is
still injected and the tool says plainly which PDFs it could not print, rather than dying
half-way and leaving a set where some reports have a twin and some do not.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

BAR_ID = "sdi-dlbar"

# Self-contained and palette-agnostic ON PURPOSE. These reports do not share a stylesheet --
# the programme status is a drawing sheet, the engine status is a different palette again --
# so the bar borrows the page's own text colour through `currentColor` and inherits its
# background. It then reads correctly in light and dark on every one of them without
# knowing anything about which tokens that report happens to define.
BAR_HTML = f"""
<div id="{BAR_ID}" style="font:500 13px/1.4 ui-sans-serif,-apple-system,'Segoe UI',sans-serif;
     display:flex;gap:10px;align-items:center;flex-wrap:wrap;
     max-width:940px;margin:0 auto;padding:10px 22px 0;color:inherit">
  <a id="{BAR_ID}-pdf" href="" target="_blank" rel="noopener"
     style="text-decoration:none;color:inherit;border:1px solid currentColor;border-radius:5px;
            padding:5px 11px;opacity:.75">PDF version</a>
  <button type="button" id="{BAR_ID}-save"
     style="font:inherit;color:inherit;background:transparent;border:1px solid currentColor;
            border-radius:5px;padding:5px 11px;opacity:.75;cursor:pointer">Save this page</button>
  <span id="{BAR_ID}-note" style="opacity:.6"></span>
</div>
<script>
(function () {{
  var bar = document.getElementById("{BAR_ID}");
  if (!bar) return;
  var link = document.getElementById("{BAR_ID}-pdf");
  var save = document.getElementById("{BAR_ID}-save");
  var note = document.getElementById("{BAR_ID}-note");

  // WHERE THE PDF IS, WHICH DEPENDS ENTIRELY ON HOW THIS PAGE WAS OPENED.
  var here = String(location.href).split("#")[0];
  var name = (here.split("/").pop() || "").split("?")[0];
  if (/[?&]path=/.test(here)) {{
    // The portal: /api/file?path=<dir>/<name>.html -> swap the extension inside the query.
    link.href = here.replace(/(\\.html?)(?=($|&))/i, ".pdf");
  }} else if (/\\.html?$/i.test(name)) {{
    link.href = name.replace(/\\.html?$/i, ".pdf");   // sibling file, on disk or on K:
  }} else {{
    link.hidden = true;                              // cannot work it out: offer nothing broken
  }}

  save.addEventListener("click", function () {{
    try {{
      bar.hidden = true;                             // the saved copy carries the report, not the bar
      var html = "<!doctype html>\\n" + document.documentElement.outerHTML;
      bar.hidden = false;
      var url = URL.createObjectURL(new Blob([html], {{type: "text/html;charset=utf-8"}}));
      var a = document.createElement("a");
      a.href = url;
      a.download = (name && /\\.html?$/i.test(name)) ? name : "sdi-status-report.html";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () {{ URL.revokeObjectURL(url); }}, 4000);
    }} catch (e) {{
      note.textContent = "Saving is blocked here — use the browser's own Save Page As.";
    }}
  }});
}})();
</script>
<style>@media print {{ #{BAR_ID} {{ display:none !important; }} }}</style>
"""

PDF_OPTS = dict(format="A4", print_background=True,
                margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})


def is_report(path: Path) -> bool:
    """A full report document, not a fragment or an include."""
    if path.name.startswith("_") or path.suffix.lower() not in (".html", ".htm"):
        return False
    head = path.read_text(encoding="utf-8", errors="ignore")[:4000].lower()
    return "<body" in head or "<!doctype" in head


def has_bar(html: str) -> bool:
    return f'id="{BAR_ID}"' in html


def inject_bar(path: Path) -> bool:
    """Put the bar just inside <body>, once. Returns True when the file changed."""
    html = path.read_text(encoding="utf-8")
    if has_bar(html):
        return False
    m = re.search(r"<body[^>]*>", html, flags=re.IGNORECASE)
    if not m:
        raise ValueError(f"{path.name}: no <body> to inject into")
    out = html[:m.end()] + BAR_HTML + html[m.end():]
    path.write_text(out, encoding="utf-8")
    return True


def print_pdf(paths: list[Path]) -> list[Path]:
    """Render each HTML to its PDF twin. Returns the ones that could not be printed."""
    try:
        from playwright.sync_api import sync_playwright     # noqa: PLC0415
    except ImportError:
        print("  ! playwright is not installed here, so no PDF was printed.\n"
              "    The download bar is still in place. To print them:\n"
              "        pip install playwright && playwright install chromium\n"
              "        python tools/report_pdf.py --all", file=sys.stderr)
        return list(paths)

    failed: list[Path] = []
    with sync_playwright() as pw:
        launch: dict = {}
        exe = Path("/opt/pw-browsers/chromium")
        if exe.exists():
            launch["executable_path"] = str(exe)
        browser = pw.chromium.launch(**launch)
        for src in paths:
            try:
                page = browser.new_page(viewport={"width": 1100, "height": 900})
                page.goto(src.resolve().as_uri(), wait_until="networkidle")
                page.emulate_media(media="print")
                page.pdf(path=str(src.with_suffix(".pdf")), **PDF_OPTS)
                page.close()
                print(f"  + {src.with_suffix('.pdf').name}")
            except Exception as exc:                        # noqa: BLE001
                print(f"  ! {src.name}: {exc}", file=sys.stderr)
                failed.append(src)
        browser.close()
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="report HTML files; omit with --all")
    ap.add_argument("--all", action="store_true", help=f"every report in {REPORTS.name}/")
    ap.add_argument("--bar-only", action="store_true",
                    help="inject the download bar and do not print")
    args = ap.parse_args()

    if args.all:
        targets = sorted(p for p in REPORTS.glob("*.htm*") if is_report(p))
    else:
        targets = [Path(p) for p in args.paths]
    if not targets:
        ap.error("nothing to do: pass report paths or --all")

    print(f"{len(targets)} report(s)")
    for t in targets:
        if inject_bar(t):
            print(f"  + download bar: {t.name}")

    if args.bar_only:
        return 0
    failed = print_pdf(targets)
    missing = [t for t in targets if not t.with_suffix(".pdf").is_file()]
    if missing:
        print(f"\n{len(missing)} report(s) still have no PDF twin: "
              + ", ".join(m.name for m in missing), file=sys.stderr)
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
