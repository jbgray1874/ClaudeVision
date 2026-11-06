# Parallel estimating runners: design note (SCRUM-183)

5 Nov 2026. Goal: two or three estimates running at once. This raises jobs per hour; each
estimate takes as long as it does today.

## What stops it today

| Constraint | Where | Why it exists |
|---|---|---|
| The service hands out one running job across all runners | `sdi-intelligence-backend/estimate_routes.py`, `claim()` refuses while `_busy_runner()` finds any run `running` | Written when there was one runner. Its own docstring says "capacity comes from more runners"; the code allows only one run. |
| One runner per machine | `tools/runner/sdi_estimate_runner.py`, `claim_the_machine()` takes `output/.runner.lock` per checkout; runner id is host + MAC | SolidWorks is one application per desktop; two runs reading models at once would collide. |
| SolidWorks reads attach to the one running SolidWorks | `tools/solidworks/sw_native_analyse.py`, `Dispatch("SldWorks.Application")` | The real one-per-desktop resource. |

Not constraints, checked:

| Shared thing | Why it is already safe |
|---|---|
| Excel recalculation | `DispatchEx("Excel.Application")` starts its own Excel per run. Memory is the cost. |
| Read cache | `src/read_store.py` writes through a temp file and `os.replace`. |
| Completed-briefs filing | `archive_folder()` makes `"<stamp> vN"` with an exclusive `mkdir`, retrying the next N. Two runs of one pack get two folders. |
| Duplicate submissions | `_active_run_for(client, drawing)` refuses a second run of a job already queued or running. |

## Phase 1: one run per runner (now, before the new server)

Service:
- `claim()` refuses a runner only when (a) that runner already has a run, (b) another runner on
  the same desktop (same hostname) has one, or (c) the number of running jobs has reached
  `SDI_MAX_CONCURRENT_RUNS`. Default `1`, so nothing changes until it is set.
- A job whose pack needs a model reader (SolidWorks files in the pack, or a staged pointer to
  them, with no extract newer than the models) is not handed to a runner that declares it
  cannot read models (`no_models` capability). Older runners declare nothing and are treated
  as able, as today.

Runner:
- Declares `no_models` when it will not drive SolidWorks (`SDI_SW_RUN_ANALYSER=0`) and has no
  Document Manager backup (`SDI_SW_DOCMGR` not set, SCRUM-184).

What this allows before the new server:

| Machine | Runner | Reads models with |
|---|---|---|
| Laptop | The existing runner | SolidWorks |
| Server downstairs | A second runner | The Document Manager backup (SCRUM-184), or no models: then it takes only jobs without model files, or with a fresh extract |

Both poll the same service. With `SDI_MAX_CONCURRENT_RUNS=2` two jobs run at once.

What the server needs before it can run one: the engine checkout on the same build as the
service (`push-to-server.ps1`, the server has no git), the virtualenv, a licensed Excel, a
logged-in session for COM (`install-runner-task.ps1`), the shares, and the `.env` keys.

## Phase 2, built 6 Nov 2026 (D-731): two runners on one desktop, one SolidWorks in turn

The agreed design, restated by JG on 6 Nov 2026 after a first build that switched readers:
"two estimating workers would share one SolidWorks reader, waiting briefly for their turn."
The same job always gets the same model evidence, whatever else is running. The Document
Manager stays off (`SDI_SW_DOCMGR` unset) until its acceptance checks pass.

| Piece | What it does |
|---|---|
| Slot checkout | `install-runner-slot.ps1 -Slot N` makes `C:\ClaudeVision-sN`, a git worktree of the main checkout's HEAD, with its own `output\` and lock, the shared venv, the shared `cache\` (junction) and its own task `SDI Estimating Runner sN`. The runner id ends `-sN`. Run it again after every sync. |
| SolidWorks turn | One lock file per machine (`%PROGRAMDATA%\SDI\solidworks.token`, or `SDI_SOLIDWORKS_TOKEN`), taken by the ENGINE around each model read (`src/solidworks_turn.py`: the engine's analyser call and the pack extract). Held for the read only, so a second run waits for one model read, never a whole estimate. The run's console says it is waiting and when its turn comes, and the job's meta records `solidworks_turn` (held, waited seconds). |
| Same evidence | Every run reads its models exactly as it would alone. Nothing switches reader because SolidWorks is busy. |
| A turn that never comes | After `SDI_SW_TURN_WAIT_MINUTES` (35, just beyond the analyser's own 30-minute limit) the read fails in its own words and is not handed to the Document Manager backup. The invariant layer stops a run whose models were left unread; the job is run again. |
| Compute gate | Slot 2 or more claims only when free memory is at least `SDI_SLOT_MIN_FREE_GB` (3) and CPU at most `SDI_SLOT_MAX_CPU_PCT` (85%). Slot 1 is never held back. |
| Service | Runners that both declare `desktop_token` may run on one desktop at once, up to `SDI_MAX_CONCURRENT_RUNS`. The strict model-reader rule stands: a job with models is never given to a runner that declares `no_models`. |
| Checks | `restart-runner.ps1 -Slot N -Root C:\ClaudeVision-sN -TaskName "SDI Estimating Runner sN"` checks that slot, and lists every other runner on the desktop with its build. |

### Later: the Document Manager and a third run

The Document Manager acceptance work goes on alongside. A third run is where it becomes
valuable: a run that would otherwise wait for SolidWorks could read with it instead. That is
safe only once the acceptance checks show the Document Manager gives the same priced evidence
as SolidWorks on the same models (`compare_extracts.py`), so a job's book does not depend on
which reader it got. Until then it is not wired into the slots.

## Phase 2 as first designed: several runners on one machine (the new server)

- Runner slots in one checkout: `--slot N` gives each process its own lock
  (`output/.runner.<N>.lock`), its own runner id (`<host>-<mac>-s<N>`) and its own work folders.
- A SolidWorks token: one file lock per desktop. A slot takes it only for the model read and
  releases it after; other slots read models from the extract or the Document Manager.
- The same-desktop rule in phase 1 is relaxed for slots that declare the token.
- The cap stays a setting; measured CPU, memory and AI call limits decide it.

## Phase 3: Self-Running queues several rows at once

Today Self-Running starts a row and waits for it. With the queue able to run two or three, it
queues up to the cap and polls each. The Live Enquiry write-back already has one writer with
retries (D-608a) and stays single.

## Acceptance (from SCRUM-183)

- Three different jobs queued together run at once. Each book's charged cells match the same
  job run alone.
- Two runs of one pack each file to their own version folder.
- Stopping one runner mid-run leaves the others running. The stopped job is recovered once,
  with one filing and one email.
- Jobs per hour measured with one, two and three runners.

## Risks

- Builds: every runner must be on the service's build. Today's three-build runs show this
  drifts; a runner should refuse a claim from a service on another build (separate guard).
- A runner without models pricing a model job: blocked by the `no_models` rule.
- AI rate limits at three times the load: not yet measured.
