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
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

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


def _dotenv_values() -> Tuple[Optional[Path], Dict[str, str]]:
    """What the .env file says, without touching this process's environment."""
    path = ROOT / ".env"
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--db", action="store_true",
                    help="also try to reach SDILive (slow when it is going to fail)")
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
