"""
SDI Intelligence — go-live preflight.

Run this on the portal host before publishing the app portal to the company:

    C:\\ClaudeVision\\.venv\\Scripts\\python.exe preflight.py

It checks what can be checked mechanically and names what cannot. Exit code 0
means every automatic check passed; 1 means at least one FAIL.

It reads .env but never prints a secret. Rotation is verified by comparing the
live value against the one committed to git — if they are identical, the
credential in the repository is still the live credential.

Nothing here changes anything. It only reports.
"""

import os
import re
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ENV = HERE / ".env"
REPO_ENV_PATH = "sdi-intelligence-backend/.env"

PASS, FAIL, WARN, MANUAL = "PASS", "FAIL", "WARN", "MANUAL"
results: list[tuple[str, str, str]] = []


def check(state: str, title: str, detail: str = "") -> None:
    results.append((state, title, detail))


def read_env(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def keys_in_portal_history() -> set[str]:
    """Every API key value that has ever been committed in the portal page.

    The key lived in the HTML, not in .env, so checking .env alone would give a
    false pass. Removing it from the current file does not un-publish it.
    """
    found: set[str] = set()
    path = "sdi-intelligence-backend/sdi-intelligence-portal.html"
    try:
        revs = subprocess.run(["git", "rev-list", "--max-count=50", "HEAD", "--", path],
                              cwd=HERE.parent, capture_output=True, text=True, timeout=30)
        for rev in revs.stdout.split():
            blob = subprocess.run(["git", "show", f"{rev}:{path}"],
                                  cwd=HERE.parent, capture_output=True, text=True, timeout=30)
            found.update(re.findall(r'API_KEY\s*=\s*["\']([0-9a-fA-F]{16,})["\']', blob.stdout))
    except (OSError, subprocess.SubprocessError):
        pass
    return found


def git_available() -> bool:
    """Whether this machine can answer questions about history at all.

    The portal host is a file-copy deployment with no git and no .git directory,
    so the rotation checks cannot run there. Saying so is the point: a check that
    silently passes because the tool is missing is worse than no check.
    """
    try:
        ok = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=HERE.parent,
                            capture_output=True, text=True, timeout=15).returncode == 0
        return ok
    except (OSError, subprocess.SubprocessError):
        return False


def committed_env() -> tuple[dict[str, str], str, bool] | None:
    """The most recent .env in git history, where it came from, and whether it is
    still tracked.

    History is what matters, not HEAD. Untracking the file stops it being
    redistributed but leaves every previously committed value recoverable, so the
    rotation check has to keep comparing against the last version that existed.
    """
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", REPO_ENV_PATH],
                                 cwd=HERE.parent, capture_output=True, text=True,
                                 timeout=20).returncode == 0
        revs = subprocess.run(["git", "rev-list", "--max-count=50", "HEAD", "--", REPO_ENV_PATH],
                              cwd=HERE.parent, capture_output=True, text=True, timeout=30)
        for rev in revs.stdout.split():
            blob = subprocess.run(["git", "show", f"{rev}:{REPO_ENV_PATH}"],
                                  cwd=HERE.parent, capture_output=True, text=True, timeout=20)
            if blob.returncode == 0 and blob.stdout.strip():
                return read_env(blob.stdout), rev[:8], tracked
    except (OSError, subprocess.SubprocessError):
        pass
    return None


# ── 1. Credential rotation ───────────────────────────────────────────────────
def check_rotation(live: dict) -> None:
    if not git_available():
        check(MANUAL, "Credential rotation cannot be checked on this machine",
              "No git repository here — this looks like a file-copy deployment. Run "
              "preflight.py on the machine that holds the git checkout to verify the "
              "database and BrightHR credentials were actually rotated.")
        return

    repo = committed_env()

    # The portal key was committed in the HTML, so check that separately.
    exposed_keys = keys_in_portal_history()
    live_key = live.get("SDI_API_KEY", "")
    if exposed_keys:
        if live_key and live_key in exposed_keys:
            check(FAIL, "SDI_API_KEY has NOT been rotated",
                  "The key still in git history (it was hardcoded in the portal page) is "
                  "the live one. Removing it from the page did not un-publish it.")
        elif live_key:
            check(PASS, "SDI_API_KEY has been rotated",
                  f"{len(exposed_keys)} old key(s) in history are no longer live.")
        else:
            check(PASS, "SDI_API_KEY is unset",
                  "The gate is off; sign-in is the only way in.")

    if repo is None:
        check(PASS, "`.env` has never been committed", "Nothing to compare.")
        return

    repo_env, rev, tracked = repo
    if tracked:
        check(WARN, "`.env` is still tracked in git",
              "Run `git rm --cached sdi-intelligence-backend/.env` and commit.")
    else:
        check(PASS, "`.env` is no longer tracked",
              f"Still recoverable from history (last seen in {rev}), so the values below "
              "must be rotated regardless.")

    watched = {
        "SDI_DB_PASSWORD": "AIBot SQL login",
        "BH_PAT": "BrightHR personal access token",
        "BH_CLIENT_SECRET": "BrightHR client secret",
    }
    if not exposed_keys:
        watched["SDI_API_KEY"] = "portal / service key"
    for key, what in watched.items():
        live_v, repo_v = live.get(key, ""), repo_env.get(key, "")
        if not repo_v or repo_v.startswith("<"):
            check(PASS, f"{key} — nothing exposed in git", f"({what})")
        elif not live_v:
            check(WARN, f"{key} is not set locally", f"({what}) — set it, or remove the feature.")
        elif live_v == repo_v:
            check(FAIL, f"{key} has NOT been rotated",
                  f"The {what} in commit {rev} is still the live one. Anyone with the "
                  "repository can recover it.")
        else:
            check(PASS, f"{key} has been rotated", f"({what})")


# ── 2. SSO and the shared key ────────────────────────────────────────────────
def check_sso(live: dict) -> None:
    required = ["SDI_TENANT_ID", "SDI_CLIENT_ID", "SDI_CLIENT_SECRET", "SDI_SESSION_SECRET"]
    missing = [k for k in required if not live.get(k) or live[k].startswith("<")]
    if missing:
        check(FAIL, "Entra SSO is not configured", "Missing: " + ", ".join(missing))
        return
    check(PASS, "Entra SSO is configured", "All four settings present.")

    secret = live.get("SDI_SESSION_SECRET", "")
    if len(secret) < 24:
        check(WARN, "SDI_SESSION_SECRET is short",
              f"{len(secret)} characters. It signs session cookies — use 32+ random characters.")

    # Can this host actually reach Entra for this tenant?
    try:
        import urllib.request
        url = (f"https://login.microsoftonline.com/{live['SDI_TENANT_ID']}"
               "/v2.0/.well-known/openid-configuration")
        with urllib.request.urlopen(url, timeout=15) as resp:
            ok = resp.status == 200 and b"authorization_endpoint" in resp.read(4000)
        check(PASS if ok else FAIL, "Entra is reachable for this tenant",
              "" if ok else "The discovery document did not look right.")
    except Exception as exc:  # noqa: BLE001 — any failure here is the answer
        check(FAIL, "Cannot reach Entra for this tenant",
              f"Check SDI_TENANT_ID and outbound access to login.microsoftonline.com. ({exc})")

    if live.get("SDI_ALLOW_API_KEY", "yes").lower() in ("no", "false", "0", "off"):
        check(PASS, "Shared X-SDI-Key is retired", "Every request is now attributable to a person.")
    else:
        check(WARN, "Shared X-SDI-Key is still accepted",
              "Fine during changeover. Set SDI_ALLOW_API_KEY=no once scheduled scripts are moved.")


# ── 3. HTTPS and exposure ────────────────────────────────────────────────────
def check_exposure(live: dict) -> None:
    redirect = live.get("SDI_REDIRECT_URI", "")
    origins = live.get("SDI_ALLOWED_ORIGINS", "")
    local = ("localhost" in redirect) or ("127.0.0.1" in redirect)

    if redirect.startswith("https://"):
        check(PASS, "Redirect URI is HTTPS", redirect)
    elif local:
        check(WARN, "Redirect URI is still localhost",
              "Expected before the tunnel. The PWA will not install on a phone until this "
              "is the HTTPS hostname.")
    else:
        check(FAIL, "Redirect URI is plain HTTP and not localhost", redirect or "(unset)")

    secure = live.get("SDI_COOKIE_SECURE", "yes").lower()
    if secure in ("no", "false", "0", "off"):
        state = WARN if local else FAIL
        check(state, "SDI_COOKIE_SECURE is disabled",
              "Session cookies may be sent over insecure connections. Remove this line "
              "once the portal is on HTTPS.")
    else:
        check(PASS, "Session cookies are marked Secure")

    if origins and "http://" in origins and not local:
        check(WARN, "SDI_ALLOWED_ORIGINS contains a plain-http origin", origins)


# ── 4. Catalogue surfaces ────────────────────────────────────────────────────
def check_surfaces() -> None:
    path = HERE / "services.json"
    if not path.exists():
        check(FAIL, "services.json is missing")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    services = data.get("services", [])

    # An app with live controls must not be listed off-network.
    bad = []
    for s in services:
        blob = json.dumps(s)
        if "<button" in blob and s.get("surface") != "intranet":
            bad.append(s["id"])
    if bad:
        check(FAIL, "Apps with live controls are shown off-network",
              "Set surface=intranet for: " + ", ".join(bad))
    else:
        check(PASS, "No app with live controls is exposed off-network")

    # Infrastructure detail would be cached on personal devices.
    leaks = []
    for s in services:
        blob = json.dumps(s)
        for pattern, label in ((r"10\.0\.0\.\d+", "internal IP"),
                               (r"[A-Z]:\\\\", "drive path"),
                               (r"\\\\\\\\[\w.]+", "UNC path")):
            if re.search(pattern, blob):
                leaks.append(f"{s['id']} ({label})")
    if leaks:
        check(WARN, "Catalogue text contains infrastructure detail",
              "Cached on every device that opens the portal: " + ", ".join(leaks))
    else:
        check(PASS, "No internal addresses or share paths in the catalogue")

    counts: dict[str, int] = {}
    for s in services:
        counts[s.get("surface", "both")] = counts.get(s.get("surface", "both"), 0) + 1
    check(PASS, f"{len(services)} apps in the catalogue",
          ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))


# ── 5. The portal page itself ────────────────────────────────────────────────
def check_portal() -> None:
    page = HERE / "sdi-intelligence-portal.html"
    if not page.exists():
        check(WARN, "Portal page not found")
        return
    text = page.read_text(encoding="utf-8", errors="replace")
    if re.search(r'API_KEY\s*=\s*["\'][0-9a-f]{16,}', text):
        check(FAIL, "The portal page still ships a hardcoded API key",
              "Every visitor's browser receives it.")
    else:
        check(PASS, "No hardcoded key in the portal page")


# ── Manual items ─────────────────────────────────────────────────────────────
def manual_items() -> None:
    check(MANUAL, "Enterprise app: Assignment required = Yes",
          "entra.microsoft.com -> Enterprise applications -> SDI Intelligence Portal -> "
          "Properties. Then Users and groups -> assign your group. Cannot be verified "
          "from here without granting this app directory-read permission it does not need.")
    check(MANUAL, "Admin consent granted for the Graph scopes",
          "App registrations -> API permissions. A missing consent shows up as a prompt "
          "users cannot approve.")
    check(MANUAL, "git history still contains the old secrets",
          "Rotation handles this. Rewriting history is only worth it if the repository "
          "is ever shared beyond the current audience.")


def main() -> int:
    if not ENV.exists():
        print(f"No .env at {ENV} — nothing to check.")
        return 1

    live = read_env(ENV.read_text(encoding="utf-8", errors="replace"))
    # .env wins here: we are auditing the file that will be deployed.
    check_rotation(live)
    check_sso(live)
    check_exposure(live)
    check_surfaces()
    check_portal()
    manual_items()

    width = max(len(t) for _, t, _ in results) + 2
    icons = {PASS: "[ ok ]", FAIL: "[FAIL]", WARN: "[warn]", MANUAL: "[ you ]"}
    print("\nSDI Intelligence — go-live preflight")
    print("=" * (width + 10))
    for state, title, detail in results:
        print(f"{icons[state]} {title}")
        if detail:
            for line in _wrap(detail, 74):
                print(f"         {line}")
    fails = sum(1 for s, _, _ in results if s == FAIL)
    warns = sum(1 for s, _, _ in results if s == WARN)
    print("=" * (width + 10))
    print(f"{fails} failed, {warns} warnings, "
          f"{sum(1 for s, _, _ in results if s == MANUAL)} for you to confirm in the portal.")
    if fails:
        print("\nDo not publish company-wide until the failures above are cleared.")
    return 1 if fails else 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    sys.exit(main())
