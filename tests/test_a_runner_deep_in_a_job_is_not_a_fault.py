"""A runner deep in a job is not a fault (21 Nov 2026).

The first live concept proof stopped the moment one job finished beside another still
running: "Runner build/health mismatch". A working runner reaches its service only through
the job's console, which named no process, so after ninety seconds the service reported its
process count as unknown. The fix is at the source (reviewer's package): the runner names its process on every
progress post and the service keeps it on record. The batch's guard is unchanged and never
reads unknown as one.
Made-up runners; a fake service."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
import tti_concept_batch as batch
import tti_concept_inputs as inp
import tti_concept_proof as proof
from test_tti_concept_batch import setup, run

BUILD = 'abcdef12'


def runner(n, **over):
    r = {'online': True, 'runner_id': f'r{n}', 'build': BUILD + ' · src test', 'process_count': 1, 'conflict': False, 'run_id': ''}
    r.update(over)
    return r


@pytest.fixture()
def routes():
    sys.path.insert(0, str(ROOT/'sdi-intelligence-backend'))
    import estimate_routes
    estimate_routes._RUNS.clear(); estimate_routes._RUNNERS.clear()
    yield estimate_routes
    estimate_routes._RUNS.clear(); estimate_routes._RUNNERS.clear()


def working(routes, claimed_by='pid-4711', silent_for=200.0):
    """A runner that claimed a run, and has since spoken only through that run's console."""
    then = routes.time.time() - silent_for
    run = routes.Run(run_id='r1', client='Made Up', drawing_number='TTI-C-0000', units=1, job_folder='J', output_path='O')
    run.status = 'running'; run.runner = 'RUNNER-1'; run.lease_until = 9e18; run.claimed_by_process = claimed_by
    routes._RUNS['r1'] = run
    routes._RUNNERS['RUNNER-1'] = routes.Runner(runner_id='RUNNER-1', hostname='RUNNER-1', run_id='r1',
                                                last_seen=then, processes={'pid-4711': then})
    return routes._RUNNERS['RUNNER-1']


def test_the_service_keeps_a_working_runners_process_on_record(routes):
    r = working(routes)
    assert r.as_json()['process_count'] is None, 'the fault: silent for 200 s, the count was unknown'
    routes.progress('r1', routes.ProgressRequest(runner_id='RUNNER-1', lines=[]))
    said = r.as_json()
    assert said['process_count'] == 1 and said['conflict'] is False and said['online'] is True
    batch.check_build([runner(1), dict(said, build=BUILD + ' · src test')], BUILD)


def test_a_run_whose_claiming_process_was_never_named_is_still_unknown(routes):
    r = working(routes, claimed_by='')
    routes.progress('r1', routes.ProgressRequest(runner_id='RUNNER-1', lines=[]))
    assert r.as_json()['process_count'] is None, 'nothing is invented for a runner that never said'


def test_a_second_process_on_the_same_runner_is_still_a_conflict(routes):
    r = working(routes)
    r.processes['pid-9999'] = routes.time.time()
    routes.progress('r1', routes.ProgressRequest(runner_id='RUNNER-1', lines=[]))
    assert r.as_json()['conflict'] is True and r.as_json()['process_count'] == 2


@pytest.mark.parametrize('fault', [
    dict(process_count=None),                                   # nobody knows its process
    dict(process_count=None, run_id='0597a2c90980'),            # unknown is never read as one, working or not
    dict(process_count=2),
    dict(conflict=True),
    dict(build='99999999 · src test'),
    dict(build=BUILD + ' +local edits'),
])
def test_the_guard_is_as_strict_as_it_was(fault):
    with pytest.raises(RuntimeError, match='mismatch'):
        batch.check_build([runner(1), runner(2, **fault)], BUILD)
