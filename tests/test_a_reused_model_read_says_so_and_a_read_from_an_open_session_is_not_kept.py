"""A REUSED MODEL READ SAYS SO, AND A READ FROM AN OPEN SESSION IS NOT KEPT (13 Nov 2026).

Reviewer: "failed or incomplete reads must be retried; successful reused reads must be
identified as reused and checked against file/configuration identity and reader
compatibility." And: "Check file identity, configuration and unsaved state."
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from source_connectors import solidworks as S  # noqa: E402

_spec = importlib.util.spec_from_file_location("sw_native_analyse_owner", ROOT / "tools/solidworks/sw_native_analyse.py")
sw = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sw
_spec.loader.exec_module(sw)


class _Cfg:
    def __init__(self, name):
        self.Name = name


class _Mgr:
    def __init__(self, name):
        self.ActiveConfiguration = _Cfg(name)


class _Doc:
    def __init__(self, dirty, configs, active="Default"):
        self.GetTitle, self.GetPathName = "P-01.SLDPRT", r"C:\packs\a\P-01.SLDPRT"
        self.GetSaveFlag = dirty
        self.ConfigurationManager = _Mgr(active)
        self.GetConfigurationNames = tuple(configs)


def _extract(tmp_path, **manifest):
    (tmp_path / "P-01.SLDPRT").write_bytes(b"a model")
    man = {"schema_version": 99, "files_failed": 0, "errors": [],
           "native_files_fingerprint": S.native_files_state(tmp_path)["fingerprint"]}
    man.update(manifest)
    e = tmp_path / "_sw_native_extract.json"
    e.write_text(json.dumps({"schema_version": 99, "_manifest": man, "records": []}), encoding="utf-8")
    return e


# ── what an already-open document is showing ────────────────────────────────────────────
def test_a_saved_single_configuration_document_carries_no_caution():
    state = sw.open_document_state(_Doc(False, ["Default"]))
    assert state["unsaved"] is False and state["configuration"] == "Default"
    assert state["configuration_unverified"] is False
    assert sw.cautions_for_an_open_document(state) == []


def test_unsaved_changes_are_said():
    said = sw.cautions_for_an_open_document(sw.open_document_state(_Doc(True, ["Default"])))
    assert len(said) == 1 and "unsaved changes" in said[0] and "P-01.SLDPRT" in said[0]


def test_a_document_with_several_configurations_is_not_assumed_to_show_the_right_one():
    state = sw.open_document_state(_Doc(False, ["Default", "LH", "RH"], active="LH"))
    said = sw.cautions_for_an_open_document(state)
    assert state["configuration_unverified"] and len(said) == 1
    assert "'LH'" in said[0] and "3 available" in said[0]


def test_a_document_that_will_not_say_is_not_taken_as_clean():
    class _Mute:
        GetTitle, GetPathName = "Q.SLDPRT", ""
    state = sw.open_document_state(_Mute())
    assert state["unsaved"] is None and state["configuration_unverified"] is True
    assert len(sw.cautions_for_an_open_document(state)) == 2


def test_each_read_records_whose_document_it_was():
    text = (ROOT / "tools/solidworks/sw_native_analyse.py").read_text(encoding="utf-8")
    assert 'result["document_owner"] = "already open before this run"' in text
    assert 'result["document_owner"] = "opened and closed by this run"' in text
    assert "self.sw.CloseDoc(title)" in text and "for title in reversed(self._open_titles)" in text


# ── reuse ───────────────────────────────────────────────────────────────────────────────
def test_a_clean_read_of_unchanged_models_is_reused(tmp_path):
    assert S._should_run(_extract(tmp_path), tmp_path) is False


def test_a_read_out_of_an_open_session_is_made_again(tmp_path):
    e = _extract(tmp_path, read_cautions=["P-01.SLDPRT was read from an open session with unsaved changes"])
    assert S.read_cautions_of(e) and S._should_run(e, tmp_path) is True


def test_a_changed_model_is_read_again(tmp_path):
    e = _extract(tmp_path)
    (tmp_path / "P-01.SLDPRT").write_bytes(b"a model, revised")
    assert S._should_run(e, tmp_path) is True


def test_a_reused_read_says_reused_and_whether_this_reader_wrote_it():
    mine = S.this_reader_build()
    assert mine == sw.reader_build()
    reused = S.how_the_read_was_obtained(False, {"written_at": "2026-11-12T16:00:00Z", "reader_build": mine})
    assert reused["evidence"] == "reused" and reused["reader_is_this_build"] is True
    assert "reused" in reused["said"] and "2026-11-12T16:00:00Z" in reused["said"] and len(reused["checked"]) == 4
    older = S.how_the_read_was_obtained(False, {"written_at": "2026-11-11T09:00:00Z", "reader_build": "sw_native_analyse 000000000000"})
    assert older["reader_is_this_build"] is False and "different reader build" in older["said"]
    unknown = S.how_the_read_was_obtained(False, {})
    assert unknown["reader_is_this_build"] is None and "does not record" in unknown["said"]


def test_a_fresh_read_says_fresh():
    fresh = S.how_the_read_was_obtained(True, {"reader_build": S.this_reader_build()})
    assert fresh["evidence"] == "fresh" and fresh["said"] == "The models were read by this run."


def test_the_record_carries_how_the_read_was_obtained():
    scan = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    assert '"read_obtained": _sw_job.meta.get("read_obtained")' in scan
    assert '"read_cautions": _sw_job.meta.get("read_cautions")' in scan


# ── the Document Manager reader follows the same rules ──────────────────────────────────
def test_the_document_manager_read_is_stamped_and_retried_the_same_way(tmp_path):
    text = (ROOT / "tools/solidworks/sw_docmgr_analyse.py").read_text(encoding="utf-8")
    assert '"reader_build": reader_build()' in text and '"written_at":' in text
    conn = (ROOT / "src/source_connectors/solidworks.py").read_text(encoding="utf-8")
    assert "_should_run(djp, analyse_from)" in conn and "_should_run(tp, analyse_from)" in conn
    failed = _extract(tmp_path, files_failed=1,
                      errors=[{"path": str(tmp_path / "P-01.SLDPRT"), "errors": ["unreadable"]}])
    assert S._should_run(failed, tmp_path) is True
