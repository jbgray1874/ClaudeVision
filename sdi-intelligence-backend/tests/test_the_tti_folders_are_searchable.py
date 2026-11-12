"""Liam's TTi folders, searched by name: Design, Production and Prototype.

The folders are built here as a small tree, indexed, and searched through the
module and over HTTP through the same gate as the despatch views. Fictional
job numbers and names.
"""
import os
from urllib.parse import quote
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tti_files                                                    # noqa: E402


def touch(path: Path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    design = tmp_path / "W" / "Design" / "Customers April 08 Onwards" / "TTi"
    production = tmp_path / "W" / "Production" / "TTi"
    prototype = tmp_path / "W" / "Prototype" / "TTi"
    touch(design / "9287 Milwaukee Gondola" / "9287-01 GA.pdf")
    touch(design / "9287 Milwaukee Gondola" / "9287-01 header.SLDPRT")
    touch(design / "9301 Ryobi Bay" / "9301-02_rev_B.dxf")
    touch(production / "9287 Milwaukee Gondola" / "Cutting list 9287.xlsx")
    touch(production / "9287 Milwaukee Gondola" / "photo 1.jpg")
    touch(prototype / "Proto 50% scale" / "notes.txt")
    touch(prototype / "500 units.pdf")
    monkeypatch.setenv("SDI_TTI_FOLDERS", f"Design={design}|Production={production}|Prototype={prototype}")
    monkeypatch.setenv("SDI_TTI_FOLDER_INDEX", str(tmp_path / "index.sqlite3"))
    result = tti_files.build(log=lambda *a: None)
    assert result["entries"] > 0
    return tmp_path


def test_every_word_must_match_and_names_come_first(tree):
    r = tti_files.search("9287 GA")
    assert [m["name"] for m in r["matches"]] == ["9287-01 GA.pdf"]


def test_a_job_number_finds_files_in_every_folder(tree):
    folders = {m["folder"] for m in tti_files.search("9287")["matches"]}
    assert folders == {"Design", "Production"}


def test_narrowing_by_kind(tree):
    kinds = {m["name"]: m["kind"] for m in tti_files.search("9287", kind="models")["matches"]}
    assert kinds == {"9287-01 header.SLDPRT": "models"}
    assert all(m["is_folder"] for m in tti_files.search("9287", kind="folders")["matches"])


def test_narrowing_by_folder_and_a_wrong_folder_is_explained(tree):
    r = tti_files.search("9287", folder="production")
    assert {m["folder"] for m in r["matches"]} == {"Production"}
    with pytest.raises(ValueError, match="No TTi folder called"):
        tti_files.search("9287", folder="Accounts")


def test_wildcards_typed_are_taken_literally(tree):
    names = {m["name"] for m in tti_files.search("50%")["matches"]}
    assert names == {"Proto 50% scale", "notes.txt"}          # the folder, and the file in it
    assert "500 units.pdf" not in names                       # % is a character, not "anything"
    assert tti_files.search("_rev_")["match_count"] == 1


def test_paths_are_shown_as_people_know_them(tree):
    (m,) = tti_files.search("9301-02")["matches"]
    assert m["path"].endswith("9301 Ryobi Bay\\9301-02_rev_B.dxf")


def test_an_empty_search_is_refused(tree):
    with pytest.raises(ValueError):
        tti_files.search("   ")


def test_no_index_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_TTI_FOLDER_INDEX", str(tmp_path / "missing.sqlite3"))
    with pytest.raises(tti_files.NotReady, match="has not been built"):
        tti_files.search("9287")


def test_a_missing_folder_is_reported_not_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_TTI_FOLDERS", str(tmp_path / "nowhere"))
    monkeypatch.setenv("SDI_TTI_FOLDER_INDEX", str(tmp_path / "i.sqlite3"))
    tti_files.build(log=lambda *a: None)
    (f,) = tti_files.status()["folders"]
    assert "could not be opened" in f["problem"]


def test_w_drive_needs_its_network_path(monkeypatch):
    monkeypatch.setenv("SDI_DRIVE_MAP", r"K=\\sdi-dc01\shareddata$\Shared")
    unc, problem = tti_files.to_unc(r"W:\Production\TTi")
    assert "SDI_DRIVE_MAP" in problem
    monkeypatch.setenv("SDI_DRIVE_MAP", r"K=\\dc\k;W=\\sdi-fs01\work")
    unc, problem = tti_files.to_unc(r"W:\Production\TTi")
    assert unc == r"\\sdi-fs01\work\Production\TTi" and problem is None


def test_two_folders_with_one_label_stay_apart(monkeypatch):
    monkeypatch.setenv("SDI_TTI_FOLDERS", r"\\fs\a\TTi\One|\\fs\a\TTi\Two")
    assert [f["label"] for f in tti_files.folders()] == ["TTi", "TTi 2"]


def test_the_default_folders_are_liams_three(monkeypatch):
    monkeypatch.delenv("SDI_TTI_FOLDERS", raising=False)
    monkeypatch.setenv("SDI_DRIVE_MAP", r"W=\\sdi-fs01\work")
    got = [(f["label"], f["shown"]) for f in tti_files.folders()]
    assert got == [("Design", r"W:\Design\Customers April 08 Onwards\TTi"),
                   ("Production", r"W:\Production\TTi"),
                   ("Prototype", r"W:\Prototype\TTi")]


# ── over HTTP, through the TTI gate ───────────────────────────────────────────

from test_the_tti_views_end_to_end import SOMEBODY_ELSE, client  # noqa: E402,F401


def test_the_search_is_behind_the_same_list_as_the_despatch_views(client, tree):
    assert client.get("/api/tti/despatch/files?q=9287").status_code == 200
    assert client.get("/api/tti/despatch/files/status").json()["entries"] > 0
    client.who["user"] = SOMEBODY_ELSE
    assert client.get("/api/tti/despatch/files?q=9287").status_code == 403
    assert client.get("/api/tti/despatch/files/status").status_code == 403


def test_bad_requests_come_back_as_sentences(client, tree):
    r = client.get("/api/tti/despatch/files?q=9287&kind=spreadsheets")
    assert r.status_code == 400 and "Kind must be one of" in r.json()["detail"]


def test_no_index_over_http_is_a_503_with_a_reason(client, tmp_path, monkeypatch):
    monkeypatch.setenv("SDI_TTI_FOLDER_INDEX", str(tmp_path / "missing.sqlite3"))
    r = client.get("/api/tti/despatch/files?q=9287")
    assert r.status_code == 503 and "has not been built" in r.json()["detail"]


# ── opening a file a search found ─────────────────────────────────────────────
#
# Liam's drawings, on his phone, off site. Only a file the index lists inside
# the three folders opens; everything else is refused with the reason.

def first_path(name):
    (m,) = [m for m in tti_files.search(name)["matches"] if m["name"] == name]
    return m["path"]


def test_a_pdf_the_search_found_opens_on_screen(tree):
    found = tti_files.locate(first_path("9287-01 GA.pdf"))
    assert found["inline"] and found["media_type"] == "application/pdf"
    assert Path(found["unc"]).read_bytes() == b"x" * 10


def test_a_model_or_spreadsheet_downloads_rather_than_showing(tree):
    found = tti_files.locate(first_path("9287-01 header.SLDPRT"))
    assert not found["inline"] and found["media_type"] == "application/octet-stream"


def test_a_web_page_on_the_share_downloads_and_never_runs_here(tree):
    design = Path(os.environ["SDI_TTI_FOLDERS"].split("|")[0].split("=", 1)[1])
    touch(design / "9287 Milwaukee Gondola" / "viewer.html")
    tti_files.build(log=lambda *a: None)
    assert not tti_files.locate(first_path("viewer.html"))["inline"]


def test_the_path_must_be_in_one_of_the_folders(tree):
    touch(tree / "W" / "Accounts" / "payroll.pdf")
    with pytest.raises(tti_files.NotFound, match="Only files in the TTi folders"):
        tti_files.locate(str(tree / "W" / "Accounts" / "payroll.pdf"))


def test_dot_dot_cannot_climb_out(tree):
    touch(tree / "W" / "secret.pdf")
    sneaky = first_path("9287-01 GA.pdf").rsplit("\\", 1)[0] + "\\..\\..\\..\\..\\secret.pdf"
    with pytest.raises(tti_files.NotFound, match=r"\.\."):
        tti_files.locate(sneaky)


def test_a_file_the_index_does_not_list_is_not_opened(tree):
    gondola = Path(first_path("9287-01 GA.pdf").replace("\\", "/")).parent
    touch(gondola / "added later.pdf")                     # on disk, not yet indexed
    with pytest.raises(tti_files.NotFound, match="not in the TTi folder index"):
        tti_files.locate(first_path("9287-01 GA.pdf").replace("9287-01 GA.pdf", "added later.pdf"))


def test_a_link_inside_a_folder_cannot_lead_outside_it(tree):
    outside = tree / "elsewhere.pdf"
    touch(outside)
    design = Path(os.environ["SDI_TTI_FOLDERS"].split("|")[0].split("=", 1)[1])
    try:
        os.symlink(outside, design / "shortcut.pdf")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")
    tti_files.build(log=lambda *a: None)
    with pytest.raises(tti_files.NotFound, match="outside the TTi folders"):
        tti_files.locate(first_path("shortcut.pdf"))


def test_a_folder_is_not_a_file(tree):
    folder = [m for m in tti_files.search("Ryobi")["matches"] if m["is_folder"]][0]
    with pytest.raises(tti_files.NotFound):
        tti_files.locate(folder["path"])


def test_chatgpt_gets_a_link_through_the_published_address(monkeypatch):
    monkeypatch.delenv("SDI_TTI_OPEN_BASE", raising=False)
    monkeypatch.setenv("SDI_PUBLIC_HOSTS", "portal.example.test, other.example.test")
    url = tti_files.open_url(r"W:\Production\TTi\9287 GA.pdf")
    assert url == ("https://portal.example.test/api/tti/despatch/files/open"
                   "?path=W%3A%5CProduction%5CTTi%5C9287%20GA.pdf")
    monkeypatch.delenv("SDI_PUBLIC_HOSTS")
    assert tti_files.open_url(r"W:\x.pdf") == ""


def test_opening_is_behind_the_same_list(client, tree):
    url = "/api/tti/despatch/files/open?path=" + quote(first_path("9287-01 GA.pdf"))
    opened = client.get(url)
    assert opened.status_code == 200 and opened.content == b"x" * 10
    assert opened.headers["content-type"].startswith("application/pdf")
    assert opened.headers["content-disposition"].startswith("inline")
    assert opened.headers["x-content-type-options"] == "nosniff"
    client.who["user"] = SOMEBODY_ELSE
    assert client.get(url).status_code == 403


def test_not_signed_in_is_sent_to_sign_in_and_back(client, tree):
    client.who["user"] = None
    url = "/api/tti/despatch/files/open?path=" + quote(first_path("9287-01 GA.pdf"))
    went = client.get(url, follow_redirects=False)
    assert went.status_code == 302
    assert went.headers["location"].startswith("/auth/login?next=%2Fapi%2Ftti%2Fdespatch%2Ffiles%2Fopen")


def test_a_refused_path_says_why_over_http(client, tree):
    r = client.get("/api/tti/despatch/files/open?path=" + quote(r"C:\Windows\win.ini"))
    assert r.status_code == 404 and "Only files in the TTi folders" in r.json()["detail"]
