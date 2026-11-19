"""Sage X3 web UI automation: open a screen, set its filters, export, save the file - no API needed.

Until Acuity give API / batch-server access, this does what a user does in the browser, on a schedule:
for each data set in datasets.json it opens the X3 function, fills the selection criteria, presses
Search and the export button (Excel / CSV on the right-hand panel, or an Exports template), and saves
the downloaded file into a dated folder. build_live_orders.py (through an X3 source adapter) and the
migration checks then read those files.

Runs on James's PC (X3 isn't reachable from the cloud session). Read-only by design: it only opens
enquiries / exports and downloads; any click whose target looks like Save / Create / Delete / Post /
Validate is refused. Imports (which write into X3) are NOT automated here: they stay a manual,
agreed step until the access question with Acuity is settled.

Setup, once:
    pip install playwright
    python -m playwright install chromium
    python x3_ui.py login          # a browser opens: sign in to X3 (and Sage ID / MFA) yourself;
                                   # the session is saved in your user profile, never in git
Capture a screen once (Playwright's recorder shows the exact selector for each box and button):
    python x3_ui.py record CONSCSP # opens that X3 function with the recorder; copy the selectors
                                   # into datasets.json
Then, whenever needed (or from Windows Task Scheduler):
    python x3_ui.py export                     # every data set marked "enabled"
    python x3_ui.py export so_lines boms       # just these
    python x3_ui.py list                       # what's configured, and what still needs capturing

Settings: datasets.json beside this file (site, folder, data sets). Output: X3_EXPORT_DIR (default
%USERPROFILE%\\SDI_X3_exports\\<yyyy-mm-dd>\\<name>.<ext>) plus run_log.json and a screenshot of any
step that fails. Session: X3_SESSION (default %USERPROFILE%\\.sdi\\x3_session.json).

Step types in datasets.json ("steps" list, run in order after the function opens):
    {"fill": "<selector or label=...>", "value": "<text>"}      value may use {today}, {today-90}, {first_of_month}
    {"click": "<selector or text=...>"}
    {"check" / "uncheck": "<selector or label=...>"}
    {"press": "<key>"}                                           e.g. Enter
    {"wait": <milliseconds>}  /  {"wait_for": "<selector>"}
    {"download": "<selector or text=...>"}                       the click that starts the file download
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "datasets.json"
HOME = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
SESSION = Path(os.environ.get("X3_SESSION", HOME / ".sdi" / "x3_session.json"))
OUT_ROOT = Path(os.environ.get("X3_EXPORT_DIR", HOME / "SDI_X3_exports"))
FORBIDDEN = re.compile(r"\b(save|create|delete|post|validate|cancel order|close order)\b", re.I)


def load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def function_url(cfg, code):
    """The X3 URL that opens a function directly (format in datasets.json, e.g. .../$sessions?f=CODE/2//M//)."""
    return cfg["site"].rstrip("/") + cfg["function_url"].format(folder=cfg["folder"], code=code)


def expand(value):
    today = dt.date.today()
    def rep(m):
        base, sign, n = m.group(1), m.group(2), m.group(3)
        d = today.replace(day=1) if base == "first_of_month" else today
        if sign:
            d += dt.timedelta(days=int(n) * (1 if sign == "+" else -1))
        return d.strftime(load_config().get("date_format", "%d/%m/%y"))
    return re.sub(r"\{(today|first_of_month)(?:([+-])(\d+))?\}", rep, str(value))


def locate(page, target):
    if target.startswith("label="):
        return page.get_by_label(target[6:], exact=False).first
    if target.startswith("text="):
        return page.get_by_text(target[5:], exact=False).first
    if target.startswith("role="):
        role, _, name = target[5:].partition(":")
        return page.get_by_role(role, name=name or None).first
    return page.locator(target).first


def browser(play, headless):
    exe = os.environ.get("X3_BROWSER_PATH")              # optional: a specific Chromium (testing)
    b = play.chromium.launch(headless=headless, **({"executable_path": exe} if exe else {}))
    ctx = b.new_context(storage_state=str(SESSION) if SESSION.exists() else None, accept_downloads=True,
                        viewport={"width": 1500, "height": 950})
    return b, ctx


def cmd_login(cfg):
    from playwright.sync_api import sync_playwright
    SESSION.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b, ctx = browser(p, headless=False)
        page = ctx.new_page()
        page.goto(cfg["site"])
        input("Sign in to Sage X3 in the browser window (and Sage ID / MFA if asked). "
              "When you can see the X3 home page, press Enter here... ")
        ctx.storage_state(path=str(SESSION))
        b.close()
    try:
        os.chmod(SESSION, 0o600)
    except OSError:
        pass
    print("session saved:", SESSION, "(your login - keep it private; delete it to sign out)")


def cmd_record(cfg, code):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b, ctx = browser(p, headless=False)
        page = ctx.new_page()
        page.goto(function_url(cfg, code))
        print("The Playwright inspector is open. Use 'Pick locator' on each criteria box and on the "
              "Search and export buttons, and copy the selectors into datasets.json. Close the inspector to finish.")
        page.pause()
        b.close()


def run_dataset(ctx, cfg, name, ds, out):
    page = ctx.new_page()
    page.set_default_timeout(cfg.get("timeout_ms", 30000))
    log = {"name": name, "function": ds.get("function"), "started": dt.datetime.now().isoformat(timespec="seconds")}
    try:
        page.goto(function_url(cfg, ds["function"]))
        page.wait_for_load_state("networkidle")
        if "login" in page.url.lower() or "signin" in page.url.lower():
            raise RuntimeError("not signed in - run: python x3_ui.py login")
        saved = None
        for i, st in enumerate(ds["steps"], 1):
            kind, target = next(((k, v) for k, v in st.items() if k != "value"), (None, None))
            if kind in ("click", "download") and FORBIDDEN.search(str(target)):
                raise RuntimeError(f"step {i}: '{target}' looks like an update action - exports only")
            if kind == "fill":
                el = locate(page, target)
                el.fill(expand(st.get("value", "")))
            elif kind == "click":
                locate(page, target).click()
            elif kind in ("check", "uncheck"):
                getattr(locate(page, target), kind)()
            elif kind == "press":
                page.keyboard.press(target)
            elif kind == "wait":
                page.wait_for_timeout(int(target))
            elif kind == "wait_for":
                locate(page, target).wait_for()
            elif kind == "download":
                with page.expect_download(timeout=cfg.get("download_timeout_ms", 300000)) as dl:
                    locate(page, target).click()
                d = dl.value
                ext = Path(d.suggested_filename).suffix or ds.get("ext", ".csv")
                saved = out / f"{name}{ext}"
                d.save_as(saved)
            else:
                raise RuntimeError(f"step {i}: unknown step {st}")
        if not saved:
            raise RuntimeError("no download step ran")
        log.update(ok=True, file=str(saved), bytes=saved.stat().st_size)
    except Exception as e:  # keep going with the other data sets; the screenshot shows where it stopped
        shot = out / f"{name}_FAILED.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
        except Exception:
            pass
        log.update(ok=False, error=str(e)[:500], screenshot=str(shot))
    finally:
        log["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        page.close()
    return log


def cmd_export(cfg, names, headless):
    from playwright.sync_api import sync_playwright
    if not SESSION.exists():
        sys.exit("No saved session - run: python x3_ui.py login")
    sets = cfg["datasets"]
    pick = names or [n for n, d in sets.items() if d.get("enabled")]
    bad = [n for n in pick if n not in sets]
    if bad:
        sys.exit(f"unknown data set(s): {bad}. Configured: {list(sets)}")
    todo = [n for n in pick if not sets[n].get("steps")]
    if todo:
        print("not captured yet (no steps), skipped:", todo)
    out = OUT_ROOT / dt.date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    logs = []
    with sync_playwright() as p:
        b, ctx = browser(p, headless=headless)
        for n in pick:
            if sets[n].get("steps"):
                logs.append(run_dataset(ctx, cfg, n, sets[n], out))
                print(("OK  " if logs[-1]["ok"] else "FAIL"), n, logs[-1].get("file") or logs[-1].get("error"))
                time.sleep(cfg.get("pause_between_s", 3))     # be gentle with the server
        ctx.storage_state(path=str(SESSION))                   # keep the session fresh
        b.close()
    (out / "run_log.json").write_text(json.dumps(logs, indent=2), encoding="utf-8")
    ok = sum(l["ok"] for l in logs)
    print(f"{ok} of {len(logs)} exported to {out}")
    return 0 if ok == len(logs) else 1


def cmd_list(cfg):
    print(f"site {cfg['site']}  folder {cfg['folder']}  session {'saved' if SESSION.exists() else 'NOT saved'}")
    for n, d in cfg["datasets"].items():
        state = "ready" if d.get("steps") else "to capture"
        print(f"  {n:<16} {d.get('function', ''):<12} {'enabled' if d.get('enabled') else 'off':<8} {state:<11} {d.get('what', '')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    r = sub.add_parser("record")
    r.add_argument("function")
    e = sub.add_parser("export")
    e.add_argument("names", nargs="*")
    e.add_argument("--show", action="store_true", help="watch the browser while it runs")
    sub.add_parser("list")
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "login":
        cmd_login(cfg)
    elif a.cmd == "record":
        cmd_record(cfg, a.function)
    elif a.cmd == "export":
        sys.exit(cmd_export(cfg, a.names, headless=not a.show))
    else:
        cmd_list(cfg)


if __name__ == "__main__":
    main()
