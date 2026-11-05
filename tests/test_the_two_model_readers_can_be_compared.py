"""The Document Manager read can be held against the SolidWorks read of the same models (D-710).

SCRUM-184's acceptance: a pack read by both readers gives the same BOM, quantities, materials
and properties, and any differences are listed. A value the Document Manager could not supply
because the file never saved it is expected, and is reported as not saved, not as a difference.
And run by hand, the reader finds its key in the engine's .env, as an engine run does.

Synthetic records and made-up part numbers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "solidworks"))

import compare_extracts as ce  # noqa: E402
import sw_docmgr_analyse as dm  # noqa: E402


def _rec(title, **signals):
    bom = signals.pop("bom", [])
    return {"title": title, "route_signals": signals, "errors": [],
            "bom": [{"part_number": p, "qty": q} for p, q in bom]}


def _write(path, records):
    path.write_text(json.dumps({"records": records}), encoding="utf-8")
    return path


def test_agreeing_reads_agree_and_an_unsaved_value_is_not_a_difference(tmp_path, capsys):
    sw = _write(tmp_path / "sw.json", [
        _rec("J-01M.SLDPRT", material="MILD STEEL", thickness_mm=1.5, flat_length_mm=126.39,
             flat_width_mm=82.2, bend_count=2, mass_kg=0.12),
        _rec("J-GA.SLDASM", bom=[("J-01M", 2)])])
    dmx = _write(tmp_path / "dm.json", [
        _rec("J-01M.SLDPRT", material="Mild Steel", thickness_mm=1.5, flat_length_mm=126.4,
             flat_width_mm=82.2, bend_count=2, mass_kg=None),
        _rec("J-GA.SLDASM", bom=[("J-01M", 2)])])
    assert ce.main([str(sw), str(dmx)]) == 0
    out = capsys.readouterr().out
    assert "agree on everything both supplied" in out
    assert "not saved in the file (expected): mass kg on 1 part(s)" in out


def test_a_disagreement_and_a_missing_part_are_listed(tmp_path, capsys):
    sw = _write(tmp_path / "sw.json", [
        _rec("J-01M", material="MILD STEEL", thickness_mm=1.5),
        _rec("J-02M", material="MILD STEEL"),
        _rec("J-GA", bom=[("J-01M", 2), ("J-02M", 1)])])
    dmx = _write(tmp_path / "dm.json", [
        _rec("J-01M", material="STAINLESS 304", thickness_mm=2.0),
        _rec("J-GA", bom=[("J-01M", 4)])])
    assert ce.main([str(sw), str(dmx)]) == 1
    out = capsys.readouterr().out
    assert "only SolidWorks:       J-02M" in out
    assert "material" in out and "STAINLESS 304" in out
    assert "BOM J-01M qty" in out and "BOM J-02M qty" in out, "a doubled quantity shows"


def test_an_unreadable_file_stops_with_its_reason(tmp_path, capsys):
    assert ce.main([str(tmp_path / "none.json"), str(tmp_path / "none2.json")]) == 2
    assert "STOP" in capsys.readouterr().out


def test_run_by_hand_the_reader_finds_its_key_in_the_engines_env(monkeypatch):
    monkeypatch.delenv(dm.KEY_ENV, raising=False)
    seen = {}

    def fake_load(path, override=False):
        seen["path"] = str(path)
        monkeypatch.setenv(dm.KEY_ENV, "TEST-KEY-not-real-0000")
        return True
    import types
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(load_dotenv=fake_load))
    monkeypatch.setattr(Path, "exists", lambda self: str(self).endswith(".env"))
    dm._load_engine_env()
    assert dm._key_from_env() == "TEST-KEY-not-real-0000"
    assert seen["path"].endswith(".env")


def test_a_key_already_in_the_shell_is_not_replaced(monkeypatch):
    monkeypatch.setenv(dm.KEY_ENV, "FROM-THE-SHELL-0000")
    import types
    monkeypatch.setitem(sys.modules, "dotenv", types.SimpleNamespace(
        load_dotenv=lambda *a, **k: (_ for _ in ()).throw(AssertionError("not loaded"))))
    dm._load_engine_env()
    assert dm._key_from_env() == "FROM-THE-SHELL-0000"
