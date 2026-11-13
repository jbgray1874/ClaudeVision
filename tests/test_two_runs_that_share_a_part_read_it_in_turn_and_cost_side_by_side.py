"""TWO RUNS THAT SHARE A PART READ IT IN TURN AND COST SIDE BY SIDE (13 Nov 2026).

Reviewer: "Track which run owns each opened document. Close only engine-owned documents.
Protect conflicting model operations without serialising whole estimates. Proof: two
runners work concurrently without interfering with each other or user-open models."

Two real processes stand in for the two runners. Each has its own pack folder holding a
byte-identical copy of one shared part. A small file plays the desktop's one SolidWorks: it
lists the titles open and who opened them, and refuses a title that is already open, as
SolidWorks does (errs 65536). Each process takes the engine's real SolidWorks turn
(src/solidworks_turn.py) for its model read only, closes only what it opened, and does its
costing outside the turn. A third title is left open by "the designer" throughout.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

WORKER = textwrap.dedent('''
    import json, os, sys, time
    sys.path.insert(0, sys.argv[1])
    name, state, token, pack, use_turn = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6] == "turn"
    import solidworks_turn as T

    def desk(change=None):
        # one writer at a time on the stand-in desktop: an exclusive lock file
        lock = state + ".lock"
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(fd); break
            except FileExistsError:
                time.sleep(0.002)
        try:
            d = json.load(open(state))
            out = change(d) if change else None
            json.dump(d, open(state, "w"))
            return d if change is None else out
        finally:
            os.unlink(lock)

    print("ready", flush=True)
    while not os.path.exists(state + ".go"):       # both runs start together, whatever the load
        time.sleep(0.005)
    log = {"name": name, "read": [], "refused": [], "saw_others_open": [], "closed": []}

    def read_models():
        log["read_from"] = time.time()
        mine = []
        for f in sorted(os.listdir(pack)):
            title = f
            def _open(d):
                if title in d["open"]:
                    return d["open"][title]
                d["open"][title] = name
                return None
            holder = desk(_open)
            if holder is not None:
                log["refused"].append({"title": title, "held_by": holder})
                continue
            mine.append(title)
            others = [t for t, who in desk()["open"].items() if who not in (name, "designer")]
            log["saw_others_open"] += others
            time.sleep(0.15)                       # the read itself
            log["read"].append(title)
        for title in mine:                         # close ONLY what this run opened
            def _close(d):
                if d["open"].get(title) == name:
                    del d["open"][title]
            desk(_close)
            log["closed"].append(title)
        log["read_to"] = time.time()

    if use_turn:
        with T.solidworks_turn(path=token, wait_s=30, poll_s=0.02, say=lambda *_: None) as turn:
            log["turn"] = turn["state"]
            read_models()
    else:
        log["turn"] = "none"
        read_models()
    log["cost_from"] = time.time()
    time.sleep(0.6)                                # costing, pricing, workbook: no SolidWorks
    log["cost_to"] = time.time()
    print(json.dumps(log))
''')


def _two_runs(tmp_path, mode):
    worker = tmp_path / "worker.py"
    worker.write_text(WORKER, encoding="utf-8")
    state = tmp_path / "desktop.json"
    state.write_text(json.dumps({"open": {"DESIGNERS-OWN.SLDPRT": "designer"}}), encoding="utf-8")
    token = tmp_path / "solidworks.token"
    packs = []
    for job in ("JOB-A", "JOB-B"):
        pack = tmp_path / job
        pack.mkdir()
        (pack / "SHARED-PANEL.SLDPRT").write_bytes(b"the same side panel, byte for byte")
        (pack / f"{job}-OWN.SLDPRT").write_bytes(job.encode())
        packs.append(pack)
    env = dict(os.environ, SDI_SOLIDWORKS_TOKEN=str(token))
    procs = [subprocess.Popen([sys.executable, str(worker), str(ROOT / "src"), f"run-{i}",
                               str(state), str(token), str(pack), mode],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
             for i, pack in enumerate(packs, 1)]
    for p in procs:
        assert p.stdout.readline().strip() == "ready"
    (tmp_path / "desktop.json.go").write_text("go", encoding="utf-8")
    logs = []
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
        logs.append(json.loads(out.strip().splitlines()[-1]))
    return logs, json.loads(state.read_text(encoding="utf-8"))


def _overlap(a, b, x, y):
    return min(a[y], b[y]) - max(a[x], b[x])


def test_both_runs_read_the_shared_part_and_neither_meets_the_others_documents(tmp_path):
    (a, b), desk = _two_runs(tmp_path, "turn")
    assert a["turn"] == b["turn"] == "held"
    for log in (a, b):
        assert "SHARED-PANEL.SLDPRT" in log["read"] and len(log["read"]) == 2, log
        assert log["refused"] == [] and log["saw_others_open"] == [], log
        assert sorted(log["closed"]) == sorted(log["read"])
    assert _overlap(a, b, "read_from", "read_to") <= 0, "the two model reads never overlap"


def test_the_designers_open_document_is_still_open_and_nothing_else_is(tmp_path):
    _logs, desk = _two_runs(tmp_path, "turn")
    assert desk["open"] == {"DESIGNERS-OWN.SLDPRT": "designer"}


def test_only_the_model_read_takes_turns_the_costing_runs_side_by_side(tmp_path):
    (a, b), _desk = _two_runs(tmp_path, "turn")
    assert _overlap(a, b, "cost_from", "cost_to") > 0.2, "both runners cost at the same time"


def test_without_the_turn_the_shared_part_is_refused(tmp_path):
    # The contrast: the same two runs with no turn collide on the shared title, which is the
    # 12674 failure. It is the turn, not luck, that keeps them apart.
    (a, b), _desk = _two_runs(tmp_path, "none")
    refused = a["refused"] + b["refused"]
    assert refused and refused[0]["title"] == "SHARED-PANEL.SLDPRT"
    assert len(a["read"]) + len(b["read"]) == 3


def test_the_engine_reads_models_only_while_it_holds_the_turn():
    conn = (ROOT / "src/source_connectors/solidworks.py").read_text(encoding="utf-8")
    pack = (ROOT / "src/pack_extract.py").read_text(encoding="utf-8")
    assert "import solidworks_turn as _sw_turn" in conn and "_sw_turn." in conn
    assert "with solidworks_turn.solidworks_turn() as turn:" in pack
