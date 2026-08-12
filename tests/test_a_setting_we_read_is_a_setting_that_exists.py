r"""
test_a_setting_we_read_is_a_setting_that_exists.py

THE BUG THIS EXISTS TO STOP, WHICH IS BORING AND EXPENSIVE.

udef_supplier_profile.py was written to answer "which suppliers should we integrate and
which should we email" -- the question that aims the whole bought-in pricing effort. It was
committed, pulled onto the estimating machine, and run against live UDEF, where it died on
line 76:

    AttributeError: module 'config' has no attribute 'SQL_CONNECTION_STRING'

before reading a single row. That name has never existed on any branch. Nothing caught it,
because reading an attribute off a module is only checked when the line runs, and the only
machine that can run this one is behind the VPN with the database on it. The round trip from
"committed" to "we know it is broken" was a day and somebody else's time.

The general fault underneath it: thirteen tracked scripts hand-roll their own
DRIVER={...};UID=...;PWD=... connection string rather than calling config.get_connection(),
so there was no single obvious answer to "how does a tool reach UDEF" to copy. A plausible
name got invented to fill the gap and read exactly like a real one.

So this asserts the boring thing on every module that reads settings: A NAME WE READ OFF
config IS A NAME config HAS. It is an import and a walk of the AST -- it needs no database,
no VPN and no Windows, so it runs here, in CI, on the commit, instead of on Tim's morning.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402


# Modules that reach settings through `config.` and are meant to run for real. Scripts
# archived under _archive are excluded: they are kept as history, not as code we run.
def _modules():
    for base in ("src", "tools"):
        for path in sorted((ROOT / base).rglob("*.py")):
            # src/load_drawings_rewrite.py IS A DIRECTORY. rglob("*.py") matches on the name
            # and does not care what the thing is, so reading it raises IsADirectoryError and
            # the guard dies before checking anything.
            if "_archive" in path.parts or "site-packages" in path.parts \
                    or not path.is_file():
                continue
            yield path


# ONE PARSE, AND A FILE THAT WILL NOT PARSE IS NOT A FILE THAT PASSED.
# The first version of this read every file with encoding="utf-8" and did `except SyntaxError:
# continue`. Six scripts -- count.py, check_D.py, fix_source_url.py among them -- start with a
# UTF-8 BOM, which ast.parse rejects as "invalid non-printable character U+FEFF", so the guard
# skipped them silently and reported them as carrying no credential. They carry the live UDEF
# password on line 2. An absence reported as a clean answer, in the guard written to stop
# exactly that. utf-8-sig eats the BOM; _UNPARSEABLE records anything still unreadable so it
# is visible rather than quietly excused.
_UNPARSEABLE: dict[str, str] = {}


def _tree(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    except SyntaxError as exc:
        _UNPARSEABLE[str(path.relative_to(ROOT))] = f"{type(exc).__name__}: {exc}"
        return None


def _config_aliases(tree: ast.AST) -> set[str]:
    """Every local name bound to the config MODULE in this file.

    `import config`, `import config as cfg`, `from src import config` -- all of them mean a
    later `<alias>.NAME` is a settings read. Matching only the literal word "config" would
    miss `import config as _cfg`, which is what catalogue_loader does.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[-1] == "config":
                    names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "config":
                    names.add(a.asname or a.name)
    return names


def _reads(path: Path):
    """(alias.attribute, line) for every settings read in this file.

    ATTRIBUTES ONLY, and only where the attribute is looked up directly on the module.
    config.PRICE_SOURCE_CONFIG.get("sqlserver") reads PRICE_SOURCE_CONFIG off config and then
    a KEY off the dict it returns; the key is data and cannot be checked here, the attribute
    is a name in a module and can be.
    """
    tree = _tree(path)
    if tree is None:
        return
    aliases = _config_aliases(tree)
    if not aliases:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id in aliases:
            yield node.attr, node.lineno


# A read guarded by getattr(config, "X", default) or hasattr is a DELIBERATE optional
# setting -- probe_pipeline does this so config stays loadable without the web block -- and
# is not a typo. Those go through ast.Call, not ast.Attribute, so they never reach _reads.
def _guarded_names(path: Path) -> set[str]:
    tree = _tree(path)
    if tree is None:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in {"getattr", "hasattr"} and len(node.args) >= 2 \
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
            out.add(node.args[1].value)
    return out


def test_every_setting_read_off_config_is_a_setting_config_has():
    missing = []
    for path in _modules():
        guarded = _guarded_names(path)
        for attr, line in _reads(path):
            if attr in guarded or attr.startswith("__"):
                continue
            if not hasattr(config, attr):
                missing.append(f"{path.relative_to(ROOT)}:{line} reads config.{attr}")
    assert not missing, (
        "These modules read settings that config does not define. Each one is an "
        "AttributeError the moment that line runs -- which, for a tool that needs the "
        "database, is on the estimating machine and not here:\n  " + "\n  ".join(missing))


def test_a_file_the_guard_cannot_read_is_reported_not_excused():
    """A guard that skips what it cannot parse reports a clean pass on what it never saw.

    Six BOM-prefixed scripts were skipped exactly this way by the first version of this file
    and came back clean while carrying the live password on line 2. Run the walks, then
    assert nothing was quietly dropped.
    """
    for path in _modules():          # populates _UNPARSEABLE as a side effect
        list(_reads(path))
    assert not _UNPARSEABLE, (
        "The guard could not parse these, so it checked nothing in them and said nothing:\n  "
        + "\n  ".join(f"{k} — {v}" for k, v in sorted(_UNPARSEABLE.items())))


def test_the_profiler_reads_a_real_name():
    """The specific regression, pinned so the file cannot drift back to an invented name."""
    body = (ROOT / "tools" / "pricing" / "udef_supplier_profile.py").read_text(encoding="utf-8")
    tree = ast.parse(body)
    names = {a for a, _ in _reads(ROOT / "tools" / "pricing" / "udef_supplier_profile.py")}
    assert names, "the profiler no longer reads config at all -- has it stopped connecting?"
    assert names <= set(dir(config)), f"invented config name(s): {names - set(dir(config))}"
    assert "get_connection" in names, (
        "the profiler must reach UDEF through config.get_connection(), the one connector "
        "that also bounds the query, rather than assembling its own string")
    del tree, body


# ── and the reason the name was invented in the first place ──────────────────────────
# THIRTEEN TRACKED SCRIPTS CARRY THE LIVE UDEF PASSWORD AS A STRING LITERAL. That is a
# credential-in-source problem in its own right and it is reported separately, but it is
# also why config.get_connection() was not the obvious thing to call: most of the examples
# in the tree do not call it. This records the count so it goes DOWN and never up, and so a
# new tool cannot add the fourteenth.
_CONNECTOR = "get_connection"


def _hand_rolled_connection_strings():
    """Files assembling their own SQL Server connection string with a literal password.

    READS THE AST-PARSED BODY, NOT THE RAW TEXT. The sixth time this codebase has been bitten
    by a guard grepping source: the first version of this one read the file as text and
    flagged udef_supplier_profile.py, whose only offence is a COMMENT explaining the
    DRIVER={...};PWD=... form it deliberately does not use. ast.unparse drops comments and
    keeps string literals, which is exactly the split that matters here -- the credential is
    a literal, the explanation is prose.
    """
    out = []
    for path in _modules():
        tree = _tree(path)
        if tree is None:
            continue
        body = ast.unparse(tree)
        # The password immediately after PWD= as a literal, not an f-string substitution:
        # "PWD={c.get('password')}" is the config-driven form and is fine.
        for line in body.splitlines():
            if "PWD=" in line and "{" not in line.split("PWD=", 1)[1][:2]:
                out.append(str(path.relative_to(ROOT)))
                break
    return sorted(set(out))


# The known set on the day this was written. Fixing one means deleting its line here; adding
# one fails. A bare count would let a fix and a regression cancel each other out.
_KNOWN_LITERAL_PASSWORD_FILES = {
    "src/EstimatingTableOutput.py", "src/Estimatingtables.py", "src/check_D.py",
    "src/check_tube_provenance.py", "src/check_tubes.py", "src/count.py",
    "src/find_base_table.py", "src/fix_source_url.py",
    "src/ingest_historical_to_db.py", "src/ingest_historical_to_qdrant.py",
    "src/migrate_bought_in_catalogue.py", "src/test_conn.py",
    "src/_udef_electrical_check.py",
}


def test_no_new_script_hard_codes_the_database_password():
    found = set(_hand_rolled_connection_strings())
    new = found - _KNOWN_LITERAL_PASSWORD_FILES
    assert not new, (
        "New file(s) embed the live UDEF password as a literal instead of calling "
        f"config.{_CONNECTOR}():\n  " + "\n  ".join(sorted(new)) +
        "\nA credential in source is in git history the moment it is pushed, and deleting "
        "it later does not remove it from history -- only rotation does.")
    stale = _KNOWN_LITERAL_PASSWORD_FILES - found
    assert not stale, (
        "These are recorded as carrying a literal password and no longer do. Delete them "
        f"from _KNOWN_LITERAL_PASSWORD_FILES so the list stays true:\n  " +
        "\n  ".join(sorted(stale)))


@pytest.mark.xfail(strict=True, reason=(
    "The live UDEF password is a string literal in 13 tracked source files and is therefore "
    "in git history. It CANNOT be fixed by editing the files: history keeps it. The fix is "
    "to rotate the SQL login, then replace every literal with config.get_connection(). Left "
    "failing on purpose so the suite keeps saying so until the credential is rotated."))
def test_the_database_password_is_not_in_the_source_tree():
    assert not _hand_rolled_connection_strings()
