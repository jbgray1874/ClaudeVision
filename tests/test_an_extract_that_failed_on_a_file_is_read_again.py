"""AN EXTRACT THAT FAILED ON A FILE IS READ AGAIN (6364-01 18:24 and 12674-02-GA, 12 Nov 2026).

6364-01 ran alone and still reported three models "open under the same title". The extract
beside its pack was an earlier run's: the models had not changed, so it was reused with its
three failures. A reader fix can never reach a job whose failed read is inherited.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "sdi-intelligence-backend"))

from source_connectors import solidworks as S  # noqa: E402


def _pack(tmp_path, failed):
    (tmp_path / "A-01.SLDPRT").write_bytes(b"model one")
    (tmp_path / "A-02.SLDPRT").write_bytes(b"model two")
    errors = [{"path": str(tmp_path / "A-02.SLDPRT"),
               "errors": ["OpenDoc6 failed: errs=65536 warns=0"]}] if failed else []
    extract = tmp_path / "_sw_native_extract.json"
    extract.write_text(json.dumps({
        "schema_version": 99,
        "_manifest": {"schema_version": 99,
                      "native_files_fingerprint": S.native_files_state(tmp_path)["fingerprint"],
                      "files_seen": 2, "files_read": 2 - len(errors), "files_failed": len(errors),
                      "errors": errors},
        "records": []}), encoding="utf-8")
    return extract


def test_a_complete_extract_of_unchanged_models_is_reused(tmp_path):
    extract = _pack(tmp_path, failed=False)
    assert S.files_the_extract_left_unread(extract) == 0
    assert S._should_run(extract, tmp_path) is False


def test_an_extract_with_a_failed_file_is_run_again_though_the_models_are_unchanged(tmp_path):
    extract = _pack(tmp_path, failed=True)
    assert S.files_the_extract_left_unread(extract) == 1
    assert S._should_run(extract, tmp_path) is True


def test_the_service_sends_that_job_to_a_runner_that_can_read_models(tmp_path):
    import estimate_routes as er
    done = tmp_path / "done"; done.mkdir()
    _pack(done, failed=False)
    assert er._needs_model_reader(str(done)) is False
    again = tmp_path / "again"; again.mkdir()
    _pack(again, failed=True)
    assert er._needs_model_reader(str(again)) is True


def test_an_unreadable_extract_counts_no_failures_and_is_left_to_the_other_rules(tmp_path):
    bad = tmp_path / "_sw_native_extract.json"
    bad.write_text("{not json", encoding="utf-8")
    assert S.files_the_extract_left_unread(bad) == 0


def test_the_extract_says_which_reader_wrote_it_and_when():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sw_native_analyse_build", ROOT / "tools/solidworks/sw_native_analyse.py")
    sw = importlib.util.module_from_spec(spec); sys.modules[spec.name] = sw; spec.loader.exec_module(sw)
    build = sw.reader_build()
    assert build.startswith("sw_native_analyse ") and len(build.split()[-1]) == 12 and build == sw.reader_build()
    text = (ROOT / "tools/solidworks/sw_native_analyse.py").read_text(encoding="utf-8")
    assert '"written_at":' in text and '"reader_build": reader_build()' in text
    conn = (ROOT / "src/source_connectors/solidworks.py").read_text(encoding="utf-8")
    assert 'job.meta["extract_reader_build"]' in conn and 'job.meta["extract_written_at"]' in conn
