"""A job's pack is classed and frozen, and replays with no share (JG and the reviewer, 12 Nov 2026).

"Turn the independently checked packs into regression fixtures for normal estimates, Self-Running
and TTI. Report each job as scope supported, provisional with named gaps, or incorrect pack -
repair required."

The synthetic cases here run everywhere. The real fixtures live on the estimating machine under
tests/pack_fixtures_local and are replayed when present; SDI_PACK_FIXTURES_REQUIRED=1 makes
their absence a failure."""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pack_fixture as pf  # noqa: E402
import pack_resolver as pr  # noqa: E402

SHARE = Path("/share/Design/Customers April 08 Onwards")


def _f(folder, name, size=100, mtime=1000.0):
    return (folder / name, size, mtime)


def _job(extra=(), ga_text="DRAWING No 4242-01-GA REV B\n1 4242-01-01M PANEL 2\n2 4242-01-02M SHELF 4"):
    tech = SHARE / "Client" / "4242 - Unit" / "4242-Technical"
    files = [_f(tech, "4242-01-GA_RevB.pdf"), _f(tech, "4242-01-GA.SLDASM"),
             _f(tech, "4242-01-01M_RevA.pdf"), _f(tech, "4242-01-01M.SLDPRT"),
             _f(tech, "4242-01-02M_RevA.pdf")] + [_f(tech, n) for n in extra]
    texts = {"4242-01-GA_RevB.pdf": ga_text}
    return [(tech, files, False)], (lambda p: texts.get(p.name, ""))


def _capture(rows, read):
    return pf.capture("4242-01-GA", "Client", folders=rows, read_text=read, area_rank=lambda f: 0)


def test_a_pack_with_everything_its_ga_calls_for_is_scope_supported():
    fx = _capture(*_job())
    assert fx["expected"]["class"] == pf.SUPPORTED and fx["expected"]["gaps"] == []
    assert set(fx["expected"]["members"]) == {"4242-01-GA", "4242-01-01M", "4242-01-02M"}


def test_a_missing_drawing_and_a_stray_file_are_named_gaps():
    rows, read = _job(extra=["Sketch of bracket.DXF"],
                      ga_text="DRAWING No 4242-01-GA REV B\n1 4242-01-01M PANEL\n2 4242-01-09M BRACKET")
    e = _capture(rows, read)["expected"]
    assert e["class"] == pf.PROVISIONAL
    assert any("4242-01-09M" in g for g in e["gaps"]) and any("Sketch of bracket.DXF" in g for g in e["gaps"])


def test_a_ga_nobody_read_is_an_incorrect_pack():
    rows, _read = _job()
    e = _capture(rows, lambda p: "")["expected"]
    assert e["class"] == pf.INCORRECT and "parts list was not read" in e["gaps"][0]


def test_no_pack_at_all_is_an_incorrect_pack():
    e = pf.capture("9999-01-GA", "Client", folders=[], read_text=lambda p: "", area_rank=lambda f: 0)["expected"]
    assert e["class"] == pf.INCORRECT


def test_a_fixture_replays_without_the_share_and_says_what_changed():
    fx = json.loads(json.dumps(_capture(*_job())))            # as saved and read back
    assert pf.differences(fx["expected"], pf.replay(fx)) == []
    fx["folders"][0][1] = [f for f in fx["folders"][0][1] if not f[0].startswith("4242-01-02M")]
    diff = pf.differences(fx["expected"], pf.replay(fx))
    assert any("no longer gathered: 4242-01-02M" in d for d in diff)
    assert any("class was" in d for d in diff)


def test_a_saved_fixture_is_not_called_checked_until_a_person_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SDI_PACK_FIXTURES", str(tmp_path))
    fx = _capture(*_job())
    (tmp_path / "4242-01-GA.json").write_text(json.dumps(fx), encoding="utf-8")
    assert pf.main(["verify"]) == 0
    assert "NOT CHECKED by a person" in capsys.readouterr().out
    assert pf.main(["checked", "4242-01-GA", "--by", "an estimator", "--note", "against the hand pack"]) == 0
    pf.main(["verify"])
    assert "checked by an estimator" in capsys.readouterr().out


def test_the_fixtures_are_never_committed():
    assert "tests/pack_fixtures_local/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_the_real_packs_on_this_machine_still_resolve_as_frozen():
    rows = pf.verify_all() if pf.fixtures_dir().is_dir() else []
    if not rows:
        if os.environ.get("SDI_PACK_FIXTURES_REQUIRED") == "1":
            pytest.fail(f"no pack fixtures under {pf.fixtures_dir()}")
        pytest.skip("no real pack fixtures on this machine (they are kept on the estimating machine)")
    changed = [f"{r['drawing']}: {'; '.join(r['differences'])}" for r in rows if not r["ok"]]
    assert not changed, "\n".join(changed)
