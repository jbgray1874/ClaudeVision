"""The pack resolver finds a drawing's pack, proves it from the drawing and explains it (SCRUM-199).

Built on how the design share names a pack (11896-01-00-GA, sub-assembly 11896-01-01-GA, parts
11896-01-01-01M, exports tagged _RevE), but the rules are generic: candidates from the index,
the GA proved by its own text, revisions compared within their scheme, archives as evidence only,
conflicts never settled by a date, missing children kept visible, one member per drawing however
many formats it exists in.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pack_resolver as pr  # noqa: E402

GA = "11896-01-00-GA"


def _f(folder: Path, name: str, size: int = 100, mtime: float = 1000.0):
    return (folder / name, size, mtime)


def _pack(base: Path, rev: str = "E", archive: bool = False, size: int = 100, mtime: float = 1000.0):
    files = [_f(base, f"{GA}.SLDASM", size, mtime), _f(base, f"{GA}.SLDDRW", size, mtime),
             _f(base, f"{GA}_Generic Workstation Wall Unit_Rev{rev}.pdf", size, mtime),
             _f(base, f"{GA}_Generic Workstation Wall Unit_Rev{rev}.DWG", size, mtime),
             _f(base, "11896-01-01-GA.SLDASM"), _f(base, f"11896-01-01-GA_Frame_Rev{rev}.pdf"),
             _f(base, "11896-01-01-01M.SLDPRT"), _f(base, f"11896-01-01-01M_60x30x1.5mm ERW BS_Rev{rev}.IGS"),
             _f(base, "11896-01-01-02M.SLDPRT"), _f(base, f"11896-01-01-02M_1.2mm MS_Rev{rev}.DXF"),
             _f(base, "11896-01-01-02M_1.2mm MS_RevC.DXF"),
             _f(base, "11896-01-02-01G_Header_RevB.pdf"),
             _f(base, "12000-99-01M_unrelated.pdf")]
    return (base, files, archive)


def _text(rev: str = "E", refs=("11896-01-01-GA", "11896-01-02-01G"),
          sub_refs=("11896-01-01-01M", "11896-01-01-02M")):
    """The top GA references its sub-assembly and a part; the sub-assembly's OWN drawing references
    its parts, so they are only found by following it (SCRUM-199 acceptance 2)."""
    def read(path: Path) -> str:
        if path.name.startswith(GA):
            return f"DRAWING No {GA}  TITLE GENERIC WORKSTATION WALL UNIT  REV {rev}\nREV A REV B\n" + "\n".join(refs)
        if path.name.startswith("11896-01-01-GA"):
            return "DRAWING No 11896-01-01-GA FRAME REV E\n" + "\n".join(sub_refs)
        return ""
    return read


def test_the_pack_is_the_ga_and_its_family_one_member_per_drawing_every_format_kept(tmp_path):
    m = pr.resolve(GA, [_pack(tmp_path / "TTI" / "11896-01-00-GA")], client="TTI", read_text=_text())
    assert m["status"] == "verified" and m["price_ok"] and m["revision"] == "E" and m["revision_from"] == "drawing"
    by = {x["drawing"]: x for x in m["members"]}
    assert set(by) == {GA, "11896-01-01-GA", "11896-01-01-01M", "11896-01-01-02M", "11896-01-02-01G"}
    assert "12000-99-01M" not in by, "a drawing outside the family is not part of the pack"
    assert sorted(f["format"] for f in by[GA]["files"]) == ["dwg", "pdf", "sldasm", "slddrw"]
    assert by["11896-01-01-02M"]["revision"] == "E" and by["11896-01-01-02M"]["superseded_revisions"] == ["C"]
    assert all("RevC" not in f["path"] for f in by["11896-01-01-02M"]["files"]), "a superseded export is not priced"
    assert by["11896-01-01-02M"]["parent"] == "11896-01-01-GA" and by["11896-01-02-01G"]["parent"] == GA
    assert all(f["fingerprint"].startswith(("sha1:", "stat:")) for x in m["members"] for f in x["files"])


def test_the_right_ga_wins_over_similar_names_older_revisions_and_archives(tmp_path):
    old = _pack(tmp_path / "TTI" / "11896 old issue", rev="C", mtime=9_000_000)
    arch = _pack(tmp_path / "TTI" / "Archive" / "11896-01-00-GA", rev="F", archive=True, mtime=9_999_999)
    cur = _pack(tmp_path / "TTI" / "11896-01-00-GA" / "Technical", rev="E")
    ga2 = (tmp_path / "TTI" / "11896-01-00-GA2", [_f(tmp_path / "TTI" / "11896-01-00-GA2", "11896-01-00-GA2_RevG.pdf")], False)
    def read(path: Path) -> str:
        rev = "C" if "old issue" in str(path) else "F" if "Archive" in str(path) else "E"
        return f"{GA} REV {rev}" if path.name.startswith(GA + "_") else ""
    m = pr.resolve(GA, [old, arch, cur, ga2], read_text=read)
    assert m["selected_folder"] == str(tmp_path / "TTI" / "11896-01-00-GA" / "Technical")
    assert m["revision"] == "E", "a newer date or an archive's later letter never wins"
    assert any("superseded by E" in a for a in m["assumptions"])
    assert len(m["candidates"]) == 3, "GA2 is a different drawing, not a candidate"


def test_two_different_files_claiming_the_same_revision_are_a_conflict_not_settled_by_date(tmp_path):
    a = _pack(tmp_path / "A" / "11896-01-00-GA", rev="E", size=100, mtime=1000)
    b = _pack(tmp_path / "B" / "11896-01-00-GA", rev="E", size=222, mtime=9_999_999)
    m = pr.resolve(GA, [a, b], read_text=_text())
    assert m["status"] == "ambiguous" and not m["price_ok"]
    assert m["conflicts"] and m["question"].startswith("Which copy is the issued one?")


def test_a_referenced_child_with_no_file_stays_visible_and_the_pack_is_priced_provisionally(tmp_path):
    read = _text(refs=("11896-01-01-GA", "11896-01-03-01M"))
    m = pr.resolve(GA, [_pack(tmp_path / "11896-01-00-GA")], read_text=read)
    assert m["missing"] == ["11896-01-03-01M"] and m["price_ok"]
    assert any("labelled allowances" in a for a in m["assumptions"])
    assert "11896-01-02-01G" in m["unreferenced"], "a family file no drawing references is kept and flagged"


def test_a_shared_library_part_the_ga_references_is_found_outside_the_job(tmp_path):
    lib = tmp_path / "Library" / "Fixings"
    read = _text(refs=("11896-01-01-GA", "40012-00-07B", "2400-1200"))
    m = pr.resolve(GA, [_pack(tmp_path / "11896-01-00-GA"), (lib, [_f(lib, "40012-00-07B_Bracket_RevA.pdf")], False)],
                   read_text=read)
    assert m["library"] == ["40012-00-07B"] and "40012-00-07B" not in m["missing"]
    assert "2400-1200" not in m["missing"], "a dimension pair is not a drawing reference"


def test_a_name_only_match_is_provisional_and_says_why(tmp_path):
    m = pr.resolve(GA, [_pack(tmp_path / "11896-01-00-GA")], read_text=lambda p: "")
    assert m["status"] == "provisional" and m["price_ok"] and m["revision_from"] == "file name"
    assert any("matched by its file name" in a for a in m["assumptions"])


def test_only_archive_copies_are_used_when_nothing_current_exists_and_it_is_said(tmp_path):
    m = pr.resolve(GA, [_pack(tmp_path / "Archive" / "x", archive=True)], read_text=_text())
    assert m["selected_folder"].endswith("x") and m["status"] == "provisional"
    assert any("only archive copies exist" in a for a in m["assumptions"])


def test_revisions_compare_within_their_scheme():
    assert pr.later("E", "B") and not pr.later("B", "E") and pr.later("AA", "Z")
    assert pr.later("A", "P3"), "a preliminary is below any issued letter"
    assert pr.later("3", "2") and pr.later("3", "B") is None, "numbers and letters are not compared"
    assert pr.family_prefix("12181-00-GA") == "12181-" and pr.family_prefix("7758C-GA") == "7758C-"
    assert pr.drawing_id("11896-01-01-02M_1.2mm MS_RevE.DXF") == "11896-01-01-02M"


# ── where the pack is kept ───────────────────────────────────────────────────────────────

import pack_store as ps  # noqa: E402


def _real_pack(base: Path, rev: str = "E", body: str = "x"):
    base.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in (f"{GA}.SLDASM", f"{GA}_Generic Workstation Wall Unit_Rev{rev}.pdf", "11896-01-01-02M_1.2mm MS_Rev{0}.DXF".format(rev)):
        p = base / name
        p.write_text(body + name)
        st = p.stat()
        rows.append((p, st.st_size, st.st_mtime))
    return (base, rows, False)


def test_the_pack_is_saved_once_reused_when_unchanged_and_versioned_when_changed(tmp_path):
    share = tmp_path / "W" / "TTI" / "11896-01-00-GA"
    store = tmp_path / "LiveEnquiry"
    m1 = pr.resolve(GA, [_real_pack(share)], read_text=_text())
    first = ps.store(m1, "TTI", root=store)
    assert first["state"] == "new" and first["folder"] == str(store / "TTI" / GA)
    assert (store / "TTI" / GA / ps.MANIFEST).exists() and len(ps.stored_files(first, m1)) == 3
    again = ps.store(pr.resolve(GA, [_real_pack(share)], read_text=_text()), "TTI", root=store)
    assert again["state"] == "unchanged" and again["folder"] == first["folder"]
    (share / "11896-01-01-02M_1.2mm MS_RevE.DXF").write_text("a changed flat pattern")
    st = (share / "11896-01-01-02M_1.2mm MS_RevE.DXF").stat()
    m3 = pr.resolve(GA, [(share, [(p, p.stat().st_size, p.stat().st_mtime) for p in sorted(share.iterdir())], False)],
                    read_text=_text())
    third = ps.store(m3, "TTI", root=store)
    assert third["state"] == "changed" and third["folder"] == str(store / "TTI" / f"{GA} v2")
    assert third["changes"]["changed"] == ["11896-01-01-02m_1.2mm ms_reve.dxf"] and third["previous"] == first["folder"]
    assert (store / "TTI" / GA / f"{GA}.SLDASM").exists(), "the earlier set is never overwritten"


def test_a_folder_filled_by_hand_is_reused_when_its_files_match(tmp_path):
    share = tmp_path / "W" / "11896-01-00-GA"
    pack = _real_pack(share)
    store = tmp_path / "LiveEnquiry"
    by_hand = store / "TTI" / GA
    by_hand.mkdir(parents=True)
    for p, _s, _m in pack[1]:
        (by_hand / p.name).write_bytes(p.read_bytes())
    got = ps.store(pr.resolve(GA, [pack], read_text=_text()), "TTI", root=store)
    assert got["state"] == "unchanged" and (by_hand / ps.MANIFEST).exists()


def test_the_store_root_is_the_live_enquiry_folder_by_its_network_path():
    assert str(ps.store_root({})) == r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry"
    assert str(ps.store_root({"AI_ENQUIRY_DEST": r"K:\x"})) == r"\\sdi-dc01\shareddata$\Shared\x"


# ── the estimating page's Find drawing pack, end to end through the service ─────────────

import pytest  # noqa: E402

ROUTES = (ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")
PAGE = (ROOT / "sdi-intelligence-backend" / "sdi-estimating-intelligence.html").read_text(encoding="utf-8")


def test_the_page_finds_a_pack_and_adds_the_kept_copies():
    assert '@router.post("/pack/find")' in ROUTES and '"--store"' in ROUTES
    assert 'id="findPack"' in PAGE and '"/api/estimate/pack/find"' in PAGE and 'id="packAuto"' in PAGE
    assert 'source: "pack"' in PAGE, "kept copies join the same drawings list as every other source"


@pytest.fixture
def service(tmp_path, monkeypatch):
    pytest.importorskip("fastapi", reason="fastapi not installed")
    monkeypatch.setenv("SDI_STATE_DIR", str(tmp_path / "state"))
    clash = ("config", "estimate_routes", "log_filters", "hr_routes", "docmgr",
             "self_running_switch", "estimate_email", "staging", "estimate_history")
    saved = {n: sys.modules.pop(n) for n in clash if n in sys.modules}
    backend = str(ROOT / "sdi-intelligence-backend")
    sys.path.insert(0, backend)
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import estimate_routes as er
        monkeypatch.setattr(er, "_ENGINE_PYTHON", sys.executable)
        monkeypatch.setattr(er.config, "FILE_ROOTS", [str(tmp_path)])
        app = FastAPI()
        app.include_router(er.router)
        tc = TestClient(app)
        key = getattr(er.config, "API_KEY", "") or ""
        if key:
            tc.headers.update({"X-SDI-Key": key})
        yield tc, tmp_path
    except Exception as exc:                                            # noqa: BLE001
        pytest.skip(f"backend not importable here: {exc}")
    finally:
        sys.path.remove(backend)
        for n in clash:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_find_shows_the_pack_and_use_keeps_it(service, monkeypatch):
    import drawing_index as di
    tc, tmp = service
    share = tmp / "CAD" / "Design" / "Customers April 08 Onwards"
    _real_pack(share / "TTI" / "11896-01-00-GA")
    monkeypatch.setenv("SDI_DRAWING_INDEX", str(tmp / "ix.json.gz"))
    monkeypatch.setenv("SDI_DRAWING_INDEX_ROOTS", str(share))
    monkeypatch.setenv("SDI_PACK_STORE", str(tmp / "LiveEnquiry"))
    di.refresh([share], tmp / "ix.json.gz")
    look = tc.post("/api/estimate/pack/find", json={"drawing": GA, "client": "TTI"}).json()
    assert look["status"] == "provisional" and look["price_ok"] and "stored" not in look
    use = tc.post("/api/estimate/pack/find", json={"drawing": GA, "client": "TTI", "store": True}).json()
    assert use["stored"]["state"] == "new" and len(use["usable_files"]) == 3
    assert all(f.startswith(str(tmp / "LiveEnquiry" / "TTI" / GA)) for f in use["usable_files"])
    assert tc.post("/api/estimate/pack/find", json={"drawing": "x"}).status_code == 400


def test_children_are_followed_through_sub_assemblies_in_other_folders_of_the_job(tmp_path):
    job = tmp_path / "TTi" / "11896 - Winnenden Training Centre [401646]" / "11896-Technical"
    gas = job / "11896-01 - Generic Workstation Wall Frame" / "11896-01-00 - GAs"
    frame = job / "11896-01 - Generic Workstation Wall Frame" / "11896-01-01 - Frame"
    rows = [(gas, [_f(gas, f"{GA}_Generic Workstation Wall Unit_RevE.pdf"), _f(gas, f"{GA}.SLDASM")], False),
            (frame, [_f(frame, "11896-01-01-GA_Frame_RevE.pdf"), _f(frame, "11896-01-01-01M.SLDPRT"),
                     _f(frame, "11896-01-01-01M_60x30x1.5mm ERW BS_RevE.IGS"), _f(frame, "11896-01-01-02M_1.2mm MS_RevE.DXF"),
                     _f(frame, "11896-01-01-02M.SLDPRT")], False)]
    m = pr.resolve(GA, rows, read_text=_text(refs=("11896-01-01-GA",)))
    by = {x["drawing"]: x for x in m["members"]}
    assert set(by) == {GA, "11896-01-01-GA", "11896-01-01-01M", "11896-01-01-02M"}
    assert by["11896-01-01-01M"]["parent"] == "11896-01-01-GA" and by["11896-01-01-GA"]["parent"] == GA
    assert m["missing"] == []


def test_the_design_area_wins_and_a_prototype_copy_is_never_a_conflict(tmp_path):
    design = _pack(tmp_path / "CAD" / "Design" / "TTi" / "11896-01-00 - GAs", size=100)
    proto = _pack(tmp_path / "CAD" / "Prototype" / "TTi" / "11896-01-00 - GAs", size=999)
    def rank(folder: Path) -> int:
        return 1 if "Prototype" in str(folder) else 0
    m = pr.resolve(GA, [proto, design], read_text=_text(), area_rank=rank)
    assert m["status"] != "ambiguous" and m["price_ok"] and not m["conflicts"]
    assert "Design" in m["selected_folder"]
    assert any("later search area" in a for a in m["assumptions"])
    alone = pr.resolve(GA, [proto], read_text=_text(), area_rank=rank)
    assert "Prototype" in alone["selected_folder"], "Prototype is used when design has nothing"


def test_only_a_ga_that_could_be_chosen_is_read(tmp_path):
    design = _pack(tmp_path / "CAD" / "Design" / "TTi" / "11896-01-00 - GAs")
    proto = _pack(tmp_path / "CAD" / "Prototype" / "TTi" / "11896-01-00 - GAs")
    arch = _pack(tmp_path / "CAD" / "Design" / "TTi" / "Archive" / "11896-01-00 - GAs", rev="D", archive=True)
    read = []
    base = _text()

    def counting(path: Path) -> str:
        read.append(str(path))
        return base(path)
    m = pr.resolve(GA, [proto, arch, design], read_text=counting,
                   area_rank=lambda f: 1 if "Prototype" in str(f) else 0)
    ga_reads = [p for p in read if Path(p).name.startswith(GA)]
    assert len(ga_reads) == 1 and "Design" in ga_reads[0] and "Archive" not in ga_reads[0]
    assert "Design" in m["selected_folder"]


def test_a_customer_item_number_in_front_does_not_hide_the_drawing_number():
    """JG, 10 Nov 2026: 12674-01-GA's GA PDF is "0359829_12674-01-GA_Smart Shirt Table_revB.PDF"
    (M&S item 0359829). Read as drawing "0359829" it was left out of the pack, and the pack
    reached the engine with no drawing to price from."""
    assert pr.drawing_id("0359829_12674-01-GA_Smart Shirt Table_revB.PDF") == "12674-01-GA"
    assert pr.drawing_id("12424-02-GA_revC 0359681.dxf") == "12424-02-GA"
    assert pr.drawing_id("12739 Stand.pdf") == "12739", "a bare number alone is still the number"
    assert pr.drawing_id("0359829 Smart Shirt Table.pdf") == "0359829"


def test_a_revision_table_heading_is_not_the_revision_and_the_title_block_value_wins():
    """12736-00-01: "ZONE REV. CN REASON DATE" and the title block "... 12736-00-01 B". CN, the
    change-note column heading, was read as the GA's revision (JG, 10 Nov 2026)."""
    text = ("REVISIONS\nZONE REV. CN REASON DATE APPROVED ON APPROVED BY\n"
            "DWG NO. REVISION:\nSANDER DEMO ASSY TTI 12736-00-01 B\n1 12736-01-GA FRAME 1")
    got = pr.read_drawing(Path("x.pdf"), "12736-00-01", read_text=lambda p: text)
    assert got["revision"] == "B" and got["carries_number"]
