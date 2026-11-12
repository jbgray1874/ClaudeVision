"""A SHARED PART ANOTHER RUN HOLDS OPEN IS READ WHEN IT IS THE SAME FILE (12 Nov 2026).

Two table jobs share a side panel. Each stages its own copy; SolidWorks holds one document of
that name. The second job's read was refused ("same title already open") and its recovery
found nothing: the documented lookup was asked by full path, which answers only for that
path, and both listing routes failed in this binding. The panel was priced at nothing, twice.

The run's own trace, 12 Nov 17:20:
    GetOpenDocumentByName2: raised AttributeError; GetOpenDocumentByName: None;
    GetDocuments: raised TypeError; GetFirstDocument walk: 0 document(s), no path match
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sw_native_analyse_shared", ROOT / "tools/solidworks/sw_native_analyse.py")
sw = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sw
_spec.loader.exec_module(sw)


class Doc:
    def __init__(self, path):
        self._path = str(path)

    def GetPathName(self):
        return self._path

    def GetTitle(self):
        return Path(self._path).name


class App:
    """The binding as the laptop's trace shows it: the by-path lookup answers None for another
    folder's copy, GetOpenDocumentByName2 does not exist, GetDocuments gives back something
    len() refuses, and the linked walk is empty."""

    def __init__(self, held):
        self.held = held
        self.asked = []

    def GetOpenDocumentByName(self, name):
        self.asked.append(name)
        if self.held is None:
            return None
        return self.held if name in (Path(self.held._path).name, Path(self.held._path).stem,
                                     self.held._path) else None

    @property
    def GetDocuments(self):
        return 7                      # not a sequence

    GetFirstDocument = None


def _session(app):
    s = object.__new__(sw.SolidWorksSession)
    s.sw = app
    return s


def _copies(tmp_path, same=True):
    a = tmp_path / "A" / "10000-01-GA" / "10000-01-02J.SLDPRT"
    b = tmp_path / "A" / "10000-02-GA" / "10000-01-02J.SLDPRT"
    a.parent.mkdir(parents=True), b.parent.mkdir(parents=True)
    a.write_bytes(b"the side panel" * 500)
    b.write_bytes(b"the side panel" * 500 if same else b"a later issue!" * 500)
    return a, b


def test_two_copies_are_the_same_file_only_when_their_bytes_agree(tmp_path):
    a, b = _copies(tmp_path)
    assert sw.same_file_by_content(str(a), str(b)) and sw.same_file_by_content(str(a), str(a))
    b.write_bytes(b"a later issue!" * 500)
    assert not sw.same_file_by_content(str(a), str(b)), "same size, other bytes"
    assert not sw.same_file_by_content(str(a), str(tmp_path / "gone.SLDPRT"))


def test_the_other_runs_open_copy_is_found_by_name_and_read_in_place(tmp_path):
    theirs, ours = _copies(tmp_path)
    app = App(Doc(theirs))
    trace = []
    got = _session(app)._get_open_document(str(ours), trace)
    assert got is app.held, trace
    assert "10000-01-02J.SLDPRT" in app.asked, "asked by its file name, not only its path"
    assert any("the same file is open from" in t and "read in place" in t for t in trace), trace


def test_a_different_file_of_the_same_name_is_not_read_for_this_one(tmp_path):
    theirs, ours = _copies(tmp_path, same=False)
    trace = []
    assert _session(App(Doc(theirs)))._get_open_document(str(ours), trace) is None
    assert any("a DIFFERENT file of this name is open" in t for t in trace), trace


def test_a_listing_that_is_not_a_sequence_no_longer_stops_the_search(tmp_path):
    _theirs, ours = _copies(tmp_path)
    trace = []
    assert _session(App(None))._get_open_document(str(ours), trace) is None
    assert not any("GetDocuments: raised TypeError" in t and "len" in t for t in trace)
    assert any(t.startswith("GetDocuments:") for t in trace) and any("GetFirstDocument walk" in t for t in trace)


def test_the_document_at_our_own_path_is_still_ours(tmp_path):
    _theirs, ours = _copies(tmp_path)
    app = App(Doc(ours))
    assert _session(app)._get_open_document(str(ours), []) is app.held
