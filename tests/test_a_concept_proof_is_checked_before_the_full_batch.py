"""A CONCEPT PROOF IS CHECKED, NOT ASSUMED, BEFORE THE FULL BATCH (21 Nov 2026).

The overnight stage must require a successful proof, not merely that earlier jobs have ended
(reviewer). tools/check_tti_concept_proof.py passes only when, for each proof row, both archives
hold the pictures that were found and sent, the effective quantity, the workbook, one engine
record and the price audit, and the tracker's AiCost cell holds that unit price.
"""
import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import tti_concept_batch as batch  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fx = _load("_concept_fx2", ROOT / "tests" / "test_tti_concept_batch.py")
proof = _load("check_tti_concept_proof", ROOT / "tools" / "check_tti_concept_proof.py")


def _done(tmp_path, monkeypatch):
    path, plan, pics, archive, api = _fx.setup(tmp_path)
    assert _fx.run(plan, pics, archive, api) == 0
    key = batch.sha(str(Path(path).resolve()).casefold().encode())[:20]
    for root, name in zip(archive.roots, ("local", "shared")):
        shutil.copytree(root, tmp_path / name / key)          # the tool's own layout: <root>/<key>
    return path, plan, tmp_path / "local", tmp_path / "shared", key


def test_a_good_proof_passes(tmp_path, monkeypatch):
    path, plan, c, k, key = _done(tmp_path, monkeypatch)
    said = []
    assert proof.check(path, c, k, [3, 4], out=said.append) is True
    assert said[-1] == "PROOF CHECK OK"
    assert any("2 picture(s) in the plan, 2 archived, 2 sent" in s for s in said)


def test_a_picture_missing_from_the_shared_archive_fails(tmp_path, monkeypatch):
    path, plan, c, k, key = _done(tmp_path, monkeypatch)
    ref = next(r["reference"] for r in plan["rows"] if r["row"] == 3)
    pic = next(f for f in (k / key / ref / "inputs").iterdir() if f.suffix == ".png")
    pic.unlink()
    said = []
    assert proof.check(path, c, k, [3], out=said.append) is False
    assert said[-1] == "PROOF CHECK FAILED"


def test_a_row_never_run_fails(tmp_path, monkeypatch):
    path, plan, pics, archive, api = _fx.setup(tmp_path)
    assert _fx.run(plan, pics, archive, api, selected_rows=[3]) == 0
    key = batch.sha(str(Path(path).resolve()).casefold().encode())[:20]
    for root, name in zip(archive.roots, ("local", "shared")):
        shutil.copytree(root, tmp_path / name / key)
    assert proof.check(path, tmp_path / "local", tmp_path / "shared", [3, 4], out=lambda s: None) is False
