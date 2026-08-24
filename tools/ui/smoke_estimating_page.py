#!/usr/bin/env python3
"""A browser smoke test for the estimating page. Catches what a syntax check cannot.

WHY THIS EXISTS. "Add all" silently added one file of five. The page parsed, every function was
declared, node --check passed, and the whole 2400-test suite was green — because the fault was a
TEMPORAL DEAD ZONE: renderFiles() called refreshPrint(), which closed over a `const` declared
further down the file than renderFiles ever got to at load. The first render threw, the rest of
the script never executed, and the Add-all loop stopped after one item.

Nothing static finds that. Only running the page does. So this loads the real page against a
stubbed API, drives the picker, and asserts what an estimator would see.

    python tools/ui/smoke_estimating_page.py

Needs a Chromium. Set SDI_CHROME to point at one; the Playwright build is used by default.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html"
STUB = Path(__file__).with_name("_stub_api.py")
# WHERE THE BROWSER IS, LOOKED FOR RATHER THAN ASSUMED. The first version hard-coded the
# Linux container's Playwright build, so on a Windows laptop it printed "no Chromium" and
# exited 0 — a check that reports success because it did not run is the exact failure this
# script exists to catch. Any Chromium-family browser will do; Edge is on every SDI machine.
_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def _find_browser() -> str:
    explicit = os.getenv("SDI_CHROME", "").strip()
    if explicit:
        return explicit
    for c in _CANDIDATES:
        if Path(c).is_file():
            return c
    import shutil as _sh
    for name in ("chrome", "chromium", "msedge", "google-chrome"):
        found = _sh.which(name)
        if found:
            return found
    return ""


CHROME = _find_browser()
PORT = os.getenv("SDI_SMOKE_PORT", "8098")

DRIVER = """
<script>
window.addEventListener("load", async () => {
  const log = []; window.onerror = (m, s, l) => log.push("JS ERROR: " + m + " @" + l);
  const wait = ms => new Promise(r => setTimeout(r, ms));
  try {
    await openBrowser("files"); await wait(250);
    await navigate("/srv/Estimating/Live Enquiry"); await wait(250);
    log.push("shown=" + shown.length);
    dAll.click(); await wait(300);
    log.push("addall=" + drawings.length);
    log.push("printdisabled=" + $("printDrawings").disabled);
    dlg.close(); drawings.length = 0; renderFiles();
    await openBrowser("files"); await wait(200);
    await navigate("/srv/Estimating/Live Enquiry"); await wait(250);
    listing.children[0].click(); listing.children[2].click(); await wait(200);
    log.push("clicks=" + drawings.length);
  } catch (e) { log.push("THREW: " + e.message); }
  const d = document.createElement("div"); d.id = "RESULT"; d.textContent = log.join(" || ");
  document.body.appendChild(d);
});
</script>
"""


def main() -> int:
    if not CHROME or not Path(CHROME).is_file():
        print("SKIPPED — no Chrome, Chromium or Edge found. This is NOT a pass; the page was\n"
              "never loaded. Looked in:")
        for c in _CANDIDATES:
            print(f"    {c}")
        print("Set SDI_CHROME to a browser and run it again.")
        return 0
    print(f"browser: {CHROME}")

    drive = PAGE.with_name("_smoke_drive.html")
    drive.write_text(PAGE.read_text(encoding="utf-8").replace("</body>", DRIVER + "</body>"),
                     encoding="utf-8")
    server = subprocess.Popen([sys.executable, str(STUB)], cwd=str(PAGE.parent),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2)
        out = subprocess.run(
            [CHROME, "--headless", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=9000", "--dump-dom",
             f"http://127.0.0.1:{PORT}/_smoke_drive.html"],
            capture_output=True, text=True, timeout=90).stdout
    finally:
        server.terminate()
        drive.unlink(missing_ok=True)

    m = re.search(r'id="RESULT">([^<]*)', out)
    if not m:
        print("FAIL — the page produced no result at all.")
        return 1
    result = m.group(1)
    print(result)

    checks = [
        ("JS ERROR" not in result and "THREW" not in result, "no uncaught error on load or use"),
        ("shown=5" in result, "the folder listed its five drawings"),
        ("addall=5" in result, "ADD ALL added all five — one of five was the original bug"),
        ("printdisabled=false" in result, "the print button enabled once drawings were added"),
        ("clicks=2" in result, "clicking two files added exactly two"),
    ]
    bad = [why for ok, why in checks if not ok]
    for ok, why in checks:
        print(("  PASS  " if ok else "  FAIL  ") + why)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
