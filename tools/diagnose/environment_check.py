r"""
environment_check.py — is this machine set up to run an estimate, and where did each
setting come from?

WHY THIS EXISTS. Every environment fault this project has hit looked like something else.
SDI_SW_RUN_ANALYSER was read in one place and set nowhere, so SolidWorks extraction was off
for weeks and the estimates just looked drawings-only. A console left elevated made the
database time out while the same test from a normal window succeeded instantly. The runner
took SDI_ENGINE_ROOT from whichever PowerShell window launched it, so the web page could
estimate with a checkout nobody had pulled while reporting itself healthy.

None of those announced themselves. Each was found days later by someone chasing a wrong
number, and in every case the machine could have said so in a second if anything had asked.

So this asks. It DISCOVERS the switches by reading the source rather than carrying a list --
a hardcoded list is the thing that drifts, and a checker that reports on last year's
variables is worse than none. For each one it says the effective value, WHERE it came from,
and whether that is a problem.

    .\.venv\Scripts\python.exe tools\diagnose\environment_check.py
    ... --db          also try to reach SDILive (slow if it is going to fail)

Exit code 0 when nothing is wrong, 1 when something is. Safe to run any time: it reads,
resolves and reports, and changes nothing.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple, List

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

# os.environ.get("X"), os.getenv("X"), os.environ["X"] -- every way this codebase asks.
_READS = re.compile(
    r"""os\.(?:environ\.get|getenv)\(\s*["']([A-Z][A-Z0-9_]{2,})["']"""
    r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]{2,})["']\s*\]""")

# Names whose VALUE must never be printed. The point is to say which variable is in play;
# printing its value would put a live credential into every console log and screenshot.
_SECRET = ("KEY", "SECRET", "PASSWORD", "TOKEN", "PWD", "CONNECTION")

# Set by the operating system or by Python itself. Reading them is not a configuration
# decision and listing them would bury the handful that are.
_NOT_OURS = {
    "PATH", "PYTHONPATH", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA",
    "COMPUTERNAME", "USERNAME", "OS", "COMSPEC", "SYSTEMROOT", "PROGRAMFILES", "PYTHONHOME",
    "PYTHONDONTWRITEBYTECODE", "PYTEST_CURRENT_TEST", "VIRTUAL_ENV", "HTTPS_PROXY",
    "HTTP_PROXY", "NO_PROXY", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
}


def switches_the_code_reads(*trees: str) -> Dict[str, str]:
    """Every environment variable the shipped code reads -> the first file that reads it.

    DISCOVERED, NOT DECLARED. A hardcoded list is exactly what drifts: this project already
    shipped a switch that was read in one place, set nowhere, and documented in neither
    README. A checker carrying its own list would have reported that setup as healthy.

    Probes, patches and one-off diagnostics are skipped. They come and go, and holding them
    to the same standard would bury the handful of switches that decide what an estimate does.
    """
    found: Dict[str, str] = {}
    for tree in trees or ("src", "tools"):
        for path in sorted((ROOT / tree).rglob("*.py")):
            if not path.is_file() or "_archive" in path.parts:
                continue
            if path.name.startswith(("_", "patch_", "diag_", "probe_", "test_")):
                continue
            try:
                text = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            for a, b in _READS.findall(text):
                name = a or b
                if name and name not in _NOT_OURS:
                    found.setdefault(name, str(path.relative_to(ROOT)))
    return found


def _every_name_the_source_mentions() -> Dict[str, str]:
    """Same scan, but sparing nothing -- probes, patches, diagnostics, tests.

    Used only to tell "nothing reads this" apart from "only a diagnostic reads this". A key
    in .env that no shipped module reads is dead weight; a key that NOTHING mentions anywhere
    is almost always a misspelling of one that does, and that is the finding worth shouting.
    """
    found: Dict[str, str] = {}
    for tree in ("src", "tools", "tests"):
        base = ROOT / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            for a, b in _READS.findall(text):
                name = a or b
                if name:
                    found.setdefault(name, str(path.relative_to(ROOT)))
    return found


def keys_nothing_reads(on_file: Dict[str, str], reads: Dict[str, str],
                       mentioned: Dict[str, str]) -> Dict[str, Optional[str]]:
    """.env keys the engine never asks for -> the nearest name it DOES ask for, if any.

    WHY THIS IS A CHECK AND NOT A TIDY-UP. Setting a switch and having it ignored looks
    identical, from the console, to not setting it: the run proceeds, the default applies,
    nothing complains. SERPAPI_API_KEY spelt SERP_API_KEY is a working .env, a healthy log,
    and web price lookup silently off. The whole point of moving settings into .env is that
    the file decides -- so a line in the file that decides NOTHING has to be said out loud.

    A key mentioned only by a probe or a test is reported separately: it is not a typo, it
    is just not wired to anything that ships.
    """
    out: Dict[str, Optional[str]] = {}
    for key in on_file:
        if key in reads or key in _NOT_OURS:
            continue
        if key in mentioned:
            out[key] = mentioned[key]                # read, but only by something unshipped
            continue
        # Candidates are the SHIPPED readers only. Suggesting a name that itself is read
        # solely by a probe would send someone to rename one dead key into another.
        near = difflib.get_close_matches(key, list(reads), n=1, cutoff=0.75)
        out[key] = None if not near else f"~{near[0]}"
    return out


def _dotenv_values(path: Optional[Path] = None) -> Tuple[Optional[Path], Dict[str, str]]:
    """What a .env file says, without touching this process's environment."""
    path = path or (ROOT / ".env")
    if not path.exists():
        return None, {}
    try:
        from dotenv import dotenv_values
        return path, {k: v for k, v in (dotenv_values(path) or {}).items() if v is not None}
    except ImportError:
        # Good enough to REPORT with. Parsing it ourselves is not a second implementation of
        # dotenv -- it is a fallback so the diagnosis still works on a machine where the
        # library is missing, which is itself one of the faults being looked for.
        out: Dict[str, str] = {}
        for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
        return path, out


def _show(name: str, value: Optional[str]) -> str:
    if value is None:
        return "(not set)"
    if any(t in name.upper() for t in _SECRET):
        return f"<set, {len(value)} chars>" if value else "<set but EMPTY>"
    return repr(value)



# ── WHAT THE HEALTH BADGE IS ACTUALLY COMPLAINING ABOUT ────────────────────────────────
#
# "BACKEND DEGRADED" in the portal header is /api/health saying the service is UP but NOT
# READY: one of five things it needs is missing. The badge shows only the summary, and until
# now this diagnostic could not help, because it scans src/ and tools/ and the three settings
# that decide the answer are read by the BACKEND — SDI_FILE_ROOTS and SDI_STAGING_ROOT in
# sdi-intelligence-backend/config.py, SDI_WB_TEMPLATE straight from os.environ in app.py.
#
# So the tool printed "Nothing wrong found" while the header said DEGRADED. Two things that
# both look authoritative, disagreeing, and no way from either to find out which was right.
#
# This computes the same five checks the endpoint does, from the same settings, without the
# service running and without the network — so it answers the question on a machine where the
# portal will not even start.

_WB_TEMPLATE_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                        r"\AI Estimating\AISheets\Blank Estimate Sheet  WB 2026.xlsx")
_STAGING_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                    r"\AI Estimating\AISheets\SDIIntelligenceAISheet")


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p.strip().strip('"')))


def report_backend_readiness(problems: List[str], notes: List[str],
                             _db_requested: bool = False) -> None:
    """The five checks behind the badge, named one by one."""
    be_path, be = _dotenv_values(ROOT / "sdi-intelligence-backend" / ".env")
    src = "sdi-intelligence-backend/.env" if be_path else "defaults (no backend .env found)"

    def setting(key, default):
        v = os.environ.get(key) or be.get(key) or ""
        v = v.strip().strip('"')
        return (v, True) if v else (default, False)

    print()
    print(f"BACKEND READINESS — the five checks behind the header badge   [{src}]")
    # FOUR OF FIVE, AND SAYING SO. The database is the fifth condition and testing it needs a
    # VPN round trip, which is what --db is for. A report that quietly covered four and read
    # as covering five is the same fault as the all-clear this section was added to fix.
    print("  database          "
          + ("tested below (--db)" if _db_requested
             else "NOT TESTED — pass --db. It is the fifth condition behind the badge."))

    roots_raw, roots_set = setting("SDI_FILE_ROOTS", "")
    roots = [r.strip() for r in roots_raw.split("|") if r.strip()]
    if not roots:
        print("  file roots        NOT SET")
        problems.append("SDI_FILE_ROOTS is not set for the backend, so /api/health reports "
                        "DEGRADED and every file the portal serves is refused.")
    else:
        for r in roots:
            ok = os.path.isdir(r)
            print(f"  file root         {'OK    ' if ok else 'MISSING'} {r}")
            if not ok:
                problems.append(f"file root not reachable from this machine: {r} — this alone "
                                f"makes the header say BACKEND DEGRADED.")

    staging, from_env = setting("SDI_STAGING_ROOT", _STAGING_DEFAULT)
    reach = os.path.isdir(staging)
    inside = any(_norm(staging).startswith(_norm(r)) for r in roots) if roots else False
    print(f"  staging root      {'OK    ' if (reach and inside) else 'PROBLEM'} {staging}")
    print(f"                    {'from .env' if from_env else 'DEFAULT — SDI_STAGING_ROOT not set'}"
          f" · reachable={reach} · inside file roots={inside}")
    if staging[:2].endswith(":"):
        problems.append("SDI_STAGING_ROOT is a mapped drive letter. A drive letter belongs to a "
                        "login session, so a service account has no such drive. Use the "
                        "\\\\server\\share form.")
    elif not reach:
        problems.append(f"staging root not reachable: {staging} — runs are refused and the "
                        f"header says DEGRADED.")
    elif not inside:
        problems.append("the staging root is not inside SDI_FILE_ROOTS, so every run is refused "
                        "on containment even though the folder exists. Add it to the roots.")

    tpl, from_env = setting("SDI_WB_TEMPLATE", _WB_TEMPLATE_DEFAULT)
    ok = os.path.isfile(tpl)
    print(f"  workbook template {'OK    ' if ok else 'MISSING'} {tpl}")
    print(f"                    {'from .env' if from_env else 'DEFAULT — SDI_WB_TEMPLATE not set'}")
    if not ok:
        problems.append("the workbook template is not reachable. EVERY deliverable hangs off it "
                        "— estimate, quote, job report, Decision Report, AI Provenance — so a "
                        "run would burn its minutes and produce a summary and no estimate. Note "
                        "the DOUBLE SPACE in 'Blank Estimate Sheet  WB 2026.xlsx' is real.")
    if not from_env:
        notes.append("SDI_WB_TEMPLATE is not set, so the template is looked for at one exact "
                     "UNC path. Setting it to a copy this machine can read is the quickest way "
                     "to clear a DEGRADED badge caused by the template.")


def _http_probe(url: str, headers: Dict[str, str]) -> Tuple[str, str]:
    """("REACHED"|"REFUSED"|"UNREACHABLE", detail) for an auth/metadata endpoint."""
    import json as _json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(4000).decode("utf-8", "replace")
            detail = ""
            try:
                data = _json.loads(body)
                if isinstance(data, dict):
                    detail = str(data.get("plan_name") or data.get("plan") or
                                 (f"{len(data.get('data') or data.get('models') or [])} model(s)"
                                  if (data.get("data") or data.get("models")) else ""))[:60]
            except ValueError:
                pass
            return "REACHED", detail
    except urllib.error.HTTPError as exc:
        return "REFUSED", f"HTTP {exc.code} {exc.reason} — the ACCOUNT or key, not the query"
    except Exception as exc:                                     # noqa: BLE001
        return "UNREACHABLE", f"{type(exc).__name__}: {str(exc)[:80]}"


def probe_pricing_rungs(problems: List[str]) -> None:
    """Say, per rung the pricing ladder falls through, whether THIS machine can ask it."""
    print()
    k = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not k:
        print("SerpAPI (web price search)   : NOT CONFIGURED — SERPAPI_API_KEY unset")
    else:
        state, detail = _http_probe(f"https://serpapi.com/account?api_key={k}", {})
        print(f"SerpAPI (web price search)   : {state}" + (f" — {detail}" if detail else ""))
        if state != "REACHED":
            problems.append(f"SerpAPI {state}: web price search will refuse every query this "
                            f"run ({detail}). A 429 is the account's rate limit — wait or "
                            f"raise the plan; a new query cannot fix it.")
    k = os.environ.get("XAI_API_KEY", "").strip()
    if not k:
        print("xAI / Grok (LLM fallback)    : NOT CONFIGURED — XAI_API_KEY unset")
        problems.append("XAI_API_KEY is unset, so the xAI pricing fallback cannot run; with "
                        "SerpAPI also down, unmatched lines fall to Anthropic or go unpriced.")
    else:
        state, detail = _http_probe("https://api.x.ai/v1/models",
                                    {"Authorization": f"Bearer {k}"})
        print(f"xAI / Grok (LLM fallback)    : {state}" + (f" — {detail}" if detail else ""))
        if state != "REACHED":
            problems.append(f"xAI {state} ({detail}) — the LLM market fallback is dead on this "
                            f"machine.")
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not k:
        print("Anthropic (LLM + web tool)   : NOT CONFIGURED — ANTHROPIC_API_KEY unset")
    else:
        state, detail = _http_probe("https://api.anthropic.com/v1/models",
                                    {"x-api-key": k, "anthropic-version": "2023-06-01"})
        print(f"Anthropic (LLM + web tool)   : {state}" + (f" — {detail}" if detail else ""))
        if state != "REACHED":
            problems.append(f"Anthropic {state} ({detail}) — the vision read and the LLM "
                            f"estimate both need it.")
    try:
        import pyodbc                                            # noqa: F401
        print("pyodbc (SDI Live driver)     : importable (reach it with --db)")
    except Exception as exc:                                     # noqa: BLE001
        print(f"pyodbc (SDI Live driver)     : MISSING — {type(exc).__name__}")
        problems.append("pyodbc is missing in THIS python, so SDI Live is unreachable from it: "
                        "every catalogue and history figure would be carried or missing. Use "
                        "the runner's venv python.")


def probe_one_real_pricing_request(problems: List[str]) -> None:
    """One request through the engine's own ladder (D-457): end-to-end proof, not connectivity.

    Asks the exact question the shipment rung asks — a per-pallet haulage rate — and reports
    whether anything answered, who, at what price, and IN WHAT UNIT, because the unit is what
    the engine accepts or refuses. One paid call at most."""
    print()
    try:
        from web_ai_price_lookup import lookup_web_ai_price
        found = lookup_web_ai_price(
            {"material": "Delivery", "part_code": "DELIVERY",
             "description": ("Palletised haulage of a standard UK pallet (1200 x 1000), "
                             "about 150 kg, display goods, one UK mainland delivery, per pallet"),
             "quantity": 1, "wanted_unit": "pallet",
             "ask": "Current UK trade cost PER PALLET. Give the carrier or supplier and the date."},
            enable_web_search=True, enable_llm_estimate=True) or {}
    except Exception as exc:                                     # noqa: BLE001
        print(f"Real pricing request         : FAILED before asking — {type(exc).__name__}: "
              f"{str(exc)[:100]}")
        problems.append("the pricing ladder itself raised before any provider was asked — "
                        "the engine cannot research prices from this machine")
        return
    if not found.get("found") or not found.get("price_gbp"):
        print(f"Real pricing request         : NO ANSWER — {str(found.get('error') or 'no provider returned a price')[:120]}")
        problems.append("no pricing provider completed a real request: a run on this machine "
                        "prices research-dependent lines from history or leaves them, and "
                        "the line must say so")
        return
    unit = str(found.get("unit") or "?")
    src = str(found.get("source_type") or "?") + (f"/{found.get('llm_provider')}"
                                                  if found.get("llm_provider") else "")
    print(f"Real pricing request         : ANSWERED — GBP {float(found['price_gbp']):,.2f} "
          f"per {unit} from {src}")
    norm = unit.strip().lower().replace("_", " ").removeprefix("per ").rstrip("s")
    if norm != "pallet":
        problems.append(f"the provider answered per {unit!r}, not per pallet — the engine "
                        f"would REFUSE this answer, so the rung is reachable but not yet "
                        f"usable for the shipment basis")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--db", action="store_true",
                    help="also try to reach SDILive (slow when it is going to fail)")
    ap.add_argument("--rungs", action="store_true",
                    help="CONNECTIVITY of each pricing rung — SDI Live, SerpAPI, xAI, "
                         "Anthropic — REACHED / REFUSED / NOT CONFIGURED. Credentials and "
                         "reachability only; it proves no completed pricing request")
    ap.add_argument("--rungs-live", action="store_true",
                    help="ONE REAL pricing request through the engine's own ladder (a per-"
                         "pallet haulage ask): proves the selected model completes, has "
                         "quota, and answers in the unit asked. Spends one paid call")
    args = ap.parse_args()

    problems: list = []
    notes: list = []

    print(f"\nENGINE   {ROOT}")
    venv = ROOT / ".venv" / "Scripts" / "python.exe"
    print(f"PYTHON   {sys.executable}")
    if venv.exists() and Path(sys.executable).resolve() != venv.resolve():
        notes.append(f"running under {sys.executable}, not the engine venv at {venv}")

    # ── the file ────────────────────────────────────────────────────────────────────
    env_path, on_file = _dotenv_values()
    try:
        import dotenv  # noqa: F401
        has_dotenv = True
    except ImportError:
        has_dotenv = False
        problems.append("python-dotenv is NOT installed, so .env is never loaded by the "
                        "engine and every switch falls back to this shell")
    if env_path is None:
        problems.append(f"no .env at {ROOT / '.env'} — every switch comes from the shell, so "
                        f"two windows can produce two different estimates")
    else:
        print(f".env     {env_path}  ({len(on_file)} setting(s))"
              f"{'' if has_dotenv else '   NOT LOADED — python-dotenv missing'}")

    # ── every switch the code reads ─────────────────────────────────────────────────
    reads = switches_the_code_reads()
    # WIDE ENOUGH FOR THE LONGEST NAME. Fixed columns wrapped
    # ESTIMATE_PART_CONFIDENCE_REVIEW_BELOW into the next field and the table stopped being
    # readable at exactly the row somebody would be squinting at.
    _w = max([len(n) for n in reads] + [len("SWITCH")]) + 2
    print(f"\n{'SWITCH':<{_w}}{'FROM':<9}{'VALUE':<28}WHO READS IT")
    print("-" * (_w + 9 + 28 + 30))
    for name in sorted(reads):
        in_shell = os.environ.get(name)
        in_file = on_file.get(name)
        if in_shell is not None and in_file is not None and in_shell != in_file:
            origin = "SHELL*"
            problems.append(f"{name} is set in this shell AND in .env, and they DISAGREE. "
                            f"The shell wins, so this run does not match the file.")
        elif in_shell is not None and in_file is not None:
            origin = ".env"
        elif in_shell is not None:
            origin = "shell"
            notes.append(f"{name} comes only from this shell — put it in .env or the next "
                         f"window behaves differently")
        elif in_file is not None:
            origin = ".env" if has_dotenv else "FILE!"
        else:
            origin = "unset"
        effective = in_shell if in_shell is not None else in_file
        print(f"{name:<{_w}}{origin:<9}{_show(name, effective):<28}{reads[name]}")

    # ── lines in .env that decide nothing ───────────────────────────────────────────
    orphans = keys_nothing_reads(on_file, reads, _every_name_the_source_mentions())
    if orphans:
        print(f"\n{'IN .env BUT NOT READ BY THE ENGINE':<{_w + 9}}WHY THAT MATTERS")
        print("-" * (_w + 9 + 60))
        for key in sorted(orphans):
            where = orphans[key]
            if where is None:
                print(f"{key:<{_w + 9}}nothing anywhere reads this name")
                problems.append(f"{key} is set in .env and NOTHING reads it. A setting that "
                                f"is ignored looks exactly like a setting that is absent.")
            elif where.startswith("~"):
                print(f"{key:<{_w + 9}}nothing reads it; closest name read is {where[1:]}")
                problems.append(f"{key} is set in .env, nothing reads it, and the engine "
                                f"does read {where[1:]}. If that is a misspelling then the "
                                f"feature behind it is OFF while the file looks correct.")
            else:
                print(f"{key:<{_w + 9}}only {where} reads it (not shipped code)")
                notes.append(f"{key} is read only by {where}, which is a probe or a test — "
                             f"setting it changes nothing about an estimate")

    # ── the ones that have actually bitten ──────────────────────────────────────────
    print()
    analyser = os.environ.get("SDI_SW_RUN_ANALYSER", on_file.get("SDI_SW_RUN_ANALYSER"))
    off = str(analyser or "").strip().lower() in {"0", "false", "no", "off"}
    print(f"SolidWorks native extraction : {'OFF' if off else 'ON'}"
          f"   (SDI_SW_RUN_ANALYSER={_show('SDI_SW_RUN_ANALYSER', analyser)}; "
          f"unset means ON)")
    if off:
        problems.append("SDI_SW_RUN_ANALYSER is switched OFF, so models are not read and "
                        "every estimate is drawings-only without saying so")

    if str(os.environ.get("SDI_OFFLINE") or "").strip():
        problems.append("SDI_OFFLINE is set, so no price lookup will run at all")

    if args.db:
        try:
            import config
            cn = config.get_connection(timeout=10)
            cn.close()
            print("Price source (SDILive)       : REACHED")
        except Exception as exc:                             # noqa: BLE001
            print(f"Price source (SDILive)       : NOT REACHED — {type(exc).__name__}: "
                  f"{str(exc)[:120]}")
            problems.append("SDILive could not be reached from this window. Every catalogue "
                            "and history price would be MISSING, not nil, and the estimate "
                            "would come out low.")
    else:
        print("Price source (SDILive)       : not tested (pass --db)")

    # ── the pricing rungs (D-456) ───────────────────────────────────────────────────
    # "confirm the runner can reach SDI Live and the xAI pricing fallback. Today's replay did
    # not establish that." — the 15:43 replay priced on carried figures because its python had
    # no pyodbc and SerpAPI was refusing the ACCOUNT (429), and nothing could say so in one
    # place. Each probe is an auth/metadata call, not a paid query, so this is safe any time.
    if args.rungs:
        probe_pricing_rungs(problems)
        print("  (connectivity only — a reachable endpoint proves credentials, not a "
              "completed pricing request; pass --rungs-live for one real ask)")
    else:
        print("Pricing rungs (web/LLM)      : not tested (pass --rungs for connectivity, "
              "--rungs-live for one real request)")
    if args.rungs_live:
        probe_one_real_pricing_request(problems)

    report_backend_readiness(problems, notes, args.db)

    # ── the verdict ─────────────────────────────────────────────────────────────────
    print()
    for n in dict.fromkeys(notes):
        print(f"  note     {n}")
    for p in dict.fromkeys(problems):
        print(f"  PROBLEM  {p}")
    if not problems:
        print("  Nothing wrong found. Every switch above came from somewhere named.")
    print()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
