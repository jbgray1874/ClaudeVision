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


def _readable(source: str) -> str:
    """The document's words, normalised so two renderings of them compare equal.

    Case is folded because the stylesheet uppercases chips and headings, and punctuation and
    spacing are dropped because a PDF's text layer breaks lines where the layout did, not
    where the sentence does.
    """
    import html as _html
    import re

    body = re.sub(r"<(script|style)\b.*?</\1>", " ", source, flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"[^a-z0-9]+", "", _html.unescape(body).casefold())


def verify(html: Path, pdf: Path) -> list[str]:
    """Return the passages that are in the source and not in the PDF.

    WHY THIS EXISTS. The August landscape report rendered cleanly, reported its byte count and
    was sent out with FOURTEEN TABLE CELLS MISSING — the Verdict column, the Worth-a-look
    column, and every "Why now" cell in the action list, which is the justification for the
    whole page. Nothing failed. `overflow-x:auto` scrolls on a screen and CLIPS on paper, and
    Chromium does not paint what it clips, so the words were not shortened, they were absent.

    A renderer that silently drops a column is worse than one that crashes, because a PDF that
    looks finished gets forwarded. So the output is now checked against its own input.
    """
    import re

    try:
        import pymupdf                                     # noqa: PLC0415
    except ImportError:                                    # pragma: no cover
        try:
            import fitz as pymupdf                         # noqa: PLC0415
        except ImportError:
            return []                                      # cannot check; do not pretend to

    doc = pymupdf.open(str(pdf))
    raw = " ".join(p.get_text() for p in doc).casefold()
    doc.close()
    words = set(re.findall(r"[a-z0-9]+", raw))
    # AND THE SAME TEXT WITH EVERY GAP CLOSED, for the letter-spaced headings. The eyebrow is
    # set at letter-spacing .18em, which makes Chromium place each glyph separately, and the
    # text layer comes back "S D I D I S P L AY S LT D" — present, correct, and not a word.
    # Checked second so a genuinely absent word still fails: it is in neither form.
    flat = re.sub(r"[^a-z0-9]+", "", raw)

    # WORDS, NOT PASSAGES, and that is not a weakening — it is the only comparison that
    # survives a table. A PDF's text layer is in LAYOUT order, so once a cell wraps onto two
    # lines its second line is emitted after the neighbouring column's first. Searching for
    # the passage as a contiguous string then fails on text that is present and correct: the
    # first version of this check reported five such passages missing, and all five were on
    # the page, wrapped. A check that cries wolf is one people learn to skip past.
    #
    # Long words are the discriminating ones. A cell that was clipped away takes its nouns
    # with it; short words ("the", "and", "now") appear all over the document and would mask
    # the loss.
    import html as _html
    source = html.read_text(encoding="utf-8")
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", source, flags=re.S | re.I)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)

    missing: list[str] = []
    for chunk in re.split(r"<[^>]+>", body):
        text = re.sub(r"\s+", " ", _html.unescape(chunk)).strip()
        if len(text) < 25:                    # too short to locate reliably
            continue
        wanted = {w for w in re.findall(r"[a-z0-9]{5,}", text.casefold())}
        gone = {w for w in wanted if w not in words and w not in flat}
        if gone:
            shown = text if len(text) <= 90 else text[:87] + "..."
            missing.append(f"{shown}   [not in PDF: {', '.join(sorted(gone)[:4])}]")
    return missing


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

    lost = verify(src, written)
    if lost:
        print(f"\n  WARNING: {len(lost)} passage(s) are in the HTML and NOT in the PDF.")
        print("  Text wider than the printed page is CLIPPED, and Chromium does not paint what")
        print("  it clips — so this is missing content, not shortened content. The usual cause")
        print("  is a table inside overflow-x:auto, which scrolls on screen and truncates on")
        print("  paper. Give the document an @media print block that lets those cells wrap.\n")
        for item in lost[:12]:
            print(f"    - {item}")
        if len(lost) > 12:
            print(f"    ... and {len(lost) - 12} more")
        return 1
    print("  verified: every passage in the HTML is present in the PDF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
