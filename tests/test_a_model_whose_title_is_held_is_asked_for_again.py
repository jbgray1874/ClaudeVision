"""A SolidWorks file refused because its title is open elsewhere is asked for again
(12674-02-GA 19:46, reviewer 11 Nov 2026).

"Two side panels remain £0. Their SolidWorks file failed with 'same title already open'; the
analyser could not retrieve it. This is a specific model-reading failure, not evidence the part
does not exist." Two runners take one SolidWorks in turn; a job that shares panels with another
holds a copy of the same file name. The holder closes it within seconds."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sw_native_analyse_title", ROOT / "tools/solidworks/sw_native_analyse.py")
sw = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sw
_spec.loader.exec_module(sw)
HELD = sw.SAME_TITLE_OPEN


def _opens(*answers):
    seq = list(answers)
    return lambda: seq.pop(0)


def test_it_opens_once_the_holder_has_closed():
    slept = []
    doc, how = sw.wait_for_a_held_title(_opens((None, HELD), (None, HELD), ("DOC", 0)),
                                        lambda: None, tries=5, wait_s=2.0, sleep=slept.append)
    assert doc == "DOC" and how.startswith("opened on try 4")
    assert slept == [2.0, 2.0, 2.0]


def test_a_document_that_turns_up_open_is_read_in_place():
    found = iter([None, "THEIRS"])
    doc, how = sw.wait_for_a_held_title(_opens((None, HELD), (None, HELD)), lambda: next(found),
                                        tries=5, wait_s=0, sleep=lambda s: None)
    assert doc == "THEIRS" and how.startswith("found open")


def test_it_stops_when_the_refusal_is_something_else():
    calls = []
    def again():
        calls.append(1)
        return None, 2          # file not found: waiting cannot help
    doc, how = sw.wait_for_a_held_title(again, lambda: None, tries=9, wait_s=0, sleep=lambda s: None)
    assert doc is None and len(calls) == 1 and "errs=2" in how


def test_it_gives_up_and_says_how_long_it_waited():
    doc, how = sw.wait_for_a_held_title(lambda: (None, HELD), lambda: None, tries=3, wait_s=5.0,
                                        sleep=lambda s: None)
    assert doc is None and "3 time(s) over 15s" in how


def test_the_open_path_waits_before_it_fails():
    text = (ROOT / "tools/solidworks/sw_native_analyse.py").read_text(encoding="utf-8")
    refusal = text.index("could not be retrieved; tried:")
    assert text.index("wait_for_a_held_title(\n                    _again") < refusal


# ── the open-document list is read whether it is a call or a property (12674-02-GA trace) ────
class _Doc:
    def __init__(self, path, title):
        self.GetPathName, self.GetTitle = path, title          # properties, as this binding gives them


class _SwProperty:
    """SolidWorks as the laptop's binding presents it: GetDocuments is the tuple itself."""
    def __init__(self, docs):
        self.GetDocuments = tuple(docs)
        self.GetFirstDocument = None

    def GetOpenDocumentByName(self, path):
        return None


def _session(sw_obj):
    s = sw.SolidWorksSession.__new__(sw.SolidWorksSession)
    s.sw = sw_obj
    return s


def test_a_part_held_under_another_folders_copy_is_found_by_its_title():
    held = _Doc("/packs/12674-01-GA/12674-01-02J.SLDPRT", "12674-01-02J.SLDPRT")
    other = _Doc("/packs/12674-01-GA/12674-01-03J.SLDPRT", "12674-01-03J.SLDPRT")
    trace = []
    got = _session(_SwProperty([other, held]))._get_open_document(
        "/packs/12674-02-GA/12674-01-02J.SLDPRT", trace)
    assert got is held, trace
    assert any("GetDocuments: 2 open" in t for t in trace) and "matched on title" in trace[-1]


def test_the_list_is_also_read_where_it_is_a_call():
    held = _Doc("/packs/a/X-01.SLDPRT", "X-01.SLDPRT")

    class _SwCall(_SwProperty):
        def __init__(self, docs):
            self.GetFirstDocument = None
            self._docs = tuple(docs)

        def GetDocuments(self):
            return self._docs
    assert _session(_SwCall([held]))._get_open_document("/packs/a/X-01.SLDPRT", []) is held
