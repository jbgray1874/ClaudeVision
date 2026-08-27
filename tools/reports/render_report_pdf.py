"""Render a report HTML file to PDF, because HTML is not a document you can send someone.

WHY THIS EXISTS. The combined status report was sent as an .html file, put in a Teams chat, and
opened on a phone — where it displayed as RAW SOURCE, starting `<!doctype html>`. Nothing was
wrong with the file. SharePoint and Teams do not render an uploaded .html attachment: serving
user-uploaded HTML from a corporate tenant is a cross-site-scripting route, so the preview shows
it as plain text and the download hands it to whatever the phone thinks .html means.

That is not a bug to fix in the HTML. It is the wrong container for the audience. A person who
is going to read something on a phone, from a chat message, needs a PDF — it renders identically
everywhere, needs no server, no VPN and no rendering policy, and it prints.

So the HTML stays the working format (it is what the artifact publishes and what a browser opens
from disk), and this produces the thing you actually send to somebody.

    python tools/reports/render_report_pdf.py reports/SDI-Programme-Status-2026-08-27.html

WHAT IT FORCES, AND WHY EACH ONE MATTERS.

  print media       the report carries an @media print block — hides the contents nav, stops
                    Gantt bars and callouts breaking across a page boundary. Rendering with
                    screen media would ignore all of it.
  light colours     the palette follows prefers-color-scheme. A dark PDF is unreadable on paper
                    and expensive to print, and nobody choosing "print" wants the dark one.
  backgrounds on    Chromium drops background colours from print by default. Without this every
                    status chip, every Gantt bar and every callout comes out as white space,
                    which removes precisely the information the chart exists to carry.
  networkidle       the page pulls Google Fonts. Screenshotting before they land produces a
                    document set in the fallback stack, which is legible but is not the report.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Where the environment keeps its browser. Playwright's own default path is not used here
# because these containers ship Chromium at a fixed location and re-downloading it is blocked.
_CHROMIUM_CANDIDATES = (
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
)


def _chromium() -> str | None:
    for path in _CHROMIUM_CANDIDATES:
        if Path(path).exists():
            return path
    for parent in Path("/opt/pw-browsers").glob("chromium*"):
        hit = parent / "chrome-linux" / "chrome"
        if hit.exists():
            return str(hit)
    return None                      # let Playwright find its own; it may well have one


def render(html: Path, pdf: Path | None = None, *, title: str = "") -> Path:
    from playwright.sync_api import sync_playwright

    html = html.resolve()
    pdf = pdf or html.with_suffix(".pdf")
    stamp = title or html.stem.replace("-", " ")

    with sync_playwright() as p:
        exe = _chromium()
        browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe \
            else p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.emulate_media(media="print", color_scheme="light")
        page.goto(html.as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(pdf), format="A4", print_background=True,
            margin={"top": "16mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
            display_header_footer=True,
            header_template=(
                '<div style="width:100%;font-size:7pt;color:#999;padding:0 12mm;'
                f'font-family:sans-serif">{stamp}</div>'),
            footer_template=(
                '<div style="width:100%;font-size:7pt;color:#999;padding:0 12mm;'
                'text-align:right;font-family:sans-serif">'
                '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'),
        )
        browser.close()
    return pdf


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[0])
        print("\nUsage: python tools/reports/render_report_pdf.py <report.html> [out.pdf]")
        return 2
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"ERROR: no such file: {src}")
        return 2
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    try:
        written = render(src, out)
    except ImportError:
        print("ERROR: playwright is not installed in this interpreter.\n"
              "       pip install playwright\n"
              "       (the browser itself is already on this machine; do NOT run "
              "`playwright install`)")
        return 1
    print(f"{written}  ({written.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
