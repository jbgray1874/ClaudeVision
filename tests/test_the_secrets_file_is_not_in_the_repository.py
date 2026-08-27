"""The file that holds the live credentials must not be a file git is tracking.

`.gitignore` has said `.env` since long before this test. It made no difference, because
**gitignore does not apply to a file already tracked** — `sdi-intelligence-backend/.env` had been
committed before the rule existed, so every edit to it was staged like source, and the ignore line
sat there looking like protection.

WHAT WAS IN IT. The live SQL login password and the BrightHR client secret. Not placeholders — the
real ones, in a repository that was public for four months.

WHY IT SURFACED WHEN IT DID. The plan for the next morning was "change the SDI live database
password and put it into .env only". With .env tracked, "into .env only" would have committed the
NEW password on the next commit that touched it — rotating a credential straight back into the
same exposure it was being rotated out of, and doing it in the belief that .env was the safe place
because that is what its own banner says:

    [config] sdi-intelligence-backend\\.env (secrets and local overrides, service-specific)

Service-specific and local is exactly right, and exactly what a tracked file cannot be. The same
file was being pulled onto two machines that need different values.

WHAT THIS TEST DOES NOT FIX, said plainly, because the distinction has cost time before:
untracking removes the file from the WORKING TREE'S index, not from HISTORY. Every password that
has been committed is still in this repository's history and still readable by anyone who has ever
had a copy. Making the repo private did not undo that either. The only thing that ends the
exposure is rotating the credential; this test only stops the NEXT one being added.

There is a companion to this in test_a_setting_we_read_is_a_setting_that_exists.py — a strict
xfail recording that the live password is a literal in thirteen tracked source files. That one
stays failing on purpose until the login is rotated. This one guards a different door.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Files that hold real values for one machine. Not templates — those are *.example.env and are
# meant to be tracked, because a setting nobody can see is a setting nobody can deploy.
_SECRET_FILES = (
    "sdi-intelligence-backend/.env",
    ".env",
    "src/.env",
)


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=_ROOT, capture_output=True, text=True)
    if out.returncode != 0:                                  # pragma: no cover
        pytest.skip("not a git checkout here")
    return set(out.stdout.splitlines())


@pytest.mark.parametrize("path", _SECRET_FILES)
def test_no_environment_file_is_tracked(path):
    """THE ASSERTION. A tracked .env is a credential in every clone, every fork and every
    history, whatever .gitignore says about it."""
    assert path not in _tracked(), (
        f"{path} is tracked by git. Untrack it — the values in it are for ONE machine, and "
        f"committing them publishes live credentials:\n"
        f"    git rm --cached {path}\n"
        f"The file stays on disk; only the tracking stops. Then take a copy on every other "
        f"machine BEFORE pulling, because the pull will delete their copy.")


def test_the_ignore_rule_actually_covers_them():
    """The rule existed and did nothing for a tracked file. Now that they are untracked it has
    to genuinely apply, or the next `git add -A` puts one straight back."""
    for path in _SECRET_FILES:
        out = subprocess.run(["git", "check-ignore", "-q", path], cwd=_ROOT)
        assert out.returncode == 0, f"{path} is not ignored — `git add -A` would re-add it"


def test_the_template_is_tracked_so_a_new_machine_can_be_set_up():
    """The counterpart, and the reason this is not simply 'ignore everything'. Somebody
    deploying a new machine needs the list of settings; what they must not get is the values."""
    tracked = _tracked()
    assert "sdi-intelligence-backend/config.example.env" in tracked


def test_the_template_names_every_setting_the_service_reads():
    """A template missing a key sends somebody to read the source to find out what to set — or,
    worse, to copy a colleague's .env, values and all. That is how a secret spreads."""
    example = (_ROOT / "sdi-intelligence-backend" / "config.example.env").read_text(
        encoding="utf-8")
    config = (_ROOT / "sdi-intelligence-backend" / "config.py").read_text(encoding="utf-8")

    import re
    read = {m.group(1) for m in re.finditer(r'_(?:opt|req)\("([A-Z0-9_]+)"', config)}
    documented = {m.group(1) for m in re.finditer(r"^([A-Z0-9_]+)=", example, re.M)}

    # Settings with a working default that no deployment has ever needed to set are allowed to
    # be absent — listing every one would bury the handful that actually have to be chosen.
    optional = {"SDI_HOST", "SDI_COMMIT", "SDI_MAX_OVERRIDE_UPLOAD_MB", "SDI_ENGINE_PYTHON",
                "SDI_STAGING_ROOT", "SDI_DM_OUTPUT_ROOT", "SDI_DM_API_BASE", "SDI_DM_API_KEY",
                "SDI_ESTIMATE_OUTPUT_ROOT", "SDI_DRIVE_MAP", "SDI_PRINT_OFFICE",
                "SDI_DWG_CONVERTER"}
    missing = read - documented - optional
    assert not missing, (
        "config.py reads these and config.example.env does not mention them: "
        + ", ".join(sorted(missing)))


def test_the_secret_values_are_not_hiding_in_the_template():
    """A template that has been filled in and committed is the same exposure wearing a
    different filename."""
    example = (_ROOT / "sdi-intelligence-backend" / "config.example.env").read_text(
        encoding="utf-8")
    for line in example.splitlines():
        if line.startswith(("SDI_DB_PASSWORD=", "BH_CLIENT_SECRET=", "BH_PAT=",
                            "SDI_API_KEY=", "DOCMGR_ACCESS_SECRET=")):
            value = line.split("=", 1)[1].strip()
            assert not value or value.startswith(("<", "CHANGE", "your-")), (
                f"{line.split('=')[0]} in the template carries what looks like a real value")


# ── a password that cannot survive the string it is pasted into ────────────────
#
# SDILive's AIBot login has is_policy_checked = 1, so the new password must meet domain
# complexity — which pushes people towards punctuation. But the password is pasted into an ODBC
# connection string:
#
#     DRIVER={...};SERVER=...;UID=AIBot;PWD=<here>;Encrypt=yes;TrustServerCertificate=yes
#
# A SEMICOLON ENDS THE PASSWORD AND STARTS A NEW KEYWORD. The server is handed a truncated
# password and answers "Login failed for user 'AIBot'" — which reads as the wrong password, not
# an unusable one, and sends somebody back to SSMS to set it again. Braces delimit ODBC values;
# a quote or a hash can be eaten by the .env parser before ODBC ever sees it.
#
# Checked rather than escaped: a service password is generated once and never typed, so the fix
# is to pick a different one and the cost of being told is a minute.


def _engine_config():
    """src/config.py specifically.

    There are TWO modules named `config` in this repository — the engine's and the backend
    service's — and a bare `import config` in a shared test interpreter returns whichever one
    another test imported first. Loading by path is the only way to be sure which one is under
    test, and the ambiguity has already cost a fixture elsewhere.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_engine_config", _ROOT / "src" / "config.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_password_that_would_truncate_the_connection_string_is_refused():
    engine_config = _engine_config()
    saved = engine_config.DB_PASSWORD
    try:
        for hostile in ("abc;def", "ab{cd}", 'has"quote', "has'apos", "has#hash"):
            engine_config.DB_PASSWORD = hostile
            with pytest.raises(RuntimeError) as exc:
                engine_config.require_db_password()
            assert "connection string" in str(exc.value)
    finally:
        engine_config.DB_PASSWORD = saved


def test_the_refusal_names_the_offending_character():
    """"Your password is invalid" sends somebody to the domain policy. Naming the character
    sends them to a new password, which is the actual fix."""
    engine_config = _engine_config()
    saved = engine_config.DB_PASSWORD
    try:
        engine_config.DB_PASSWORD = "abc;def"
        with pytest.raises(RuntimeError) as exc:
            engine_config.require_db_password()
        assert "';'" in str(exc.value)
        assert "semicolon" in str(exc.value).lower()
    finally:
        engine_config.DB_PASSWORD = saved


def test_an_ordinary_strong_password_is_left_alone():
    """The guard must not push people towards weak passwords. Letters and digits at length are
    the recommendation, and they have to pass."""
    engine_config = _engine_config()
    saved = engine_config.DB_PASSWORD
    try:
        for good in ("kQ7mZp2xR9tLvB4nHs6wY3dF", "AIAgent2026Replacement", "aB3" * 8):
            engine_config.DB_PASSWORD = good
            assert engine_config.require_db_password() == good
    finally:
        engine_config.DB_PASSWORD = saved
