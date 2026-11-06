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

## Phase 2, built 6 Nov 2026 (D-731): several runners on one desktop

JG, 6 Nov 2026: "we need to see the multi run on this laptop ... for any second or third runs,
we shouldn't stop unless the machine has insufficient compute available and we should use
document manager for all other runs. if we can't we run without solid works and document
manager and use what we have otherwise."

| Piece | What it does |
|---|---|
| Slot checkout | `install-runner-slot.ps1 -Slot N` makes `C:\ClaudeVision-sN`, a git worktree of the main checkout's HEAD, with its own `output\` and lock, the shared venv, the shared `cache\` (junction) and its own task `SDI Estimating Runner sN`. The runner id ends `-sN`. Run it again after every sync. |
| Desktop token | One lock file per machine (`%PROGRAMDATA%\SDI\solidworks.token`, or `SDI_SOLIDWORKS_TOKEN`). The run holding it reads models with SolidWorks as configured. |
| Other runs | Read models with the Document Manager when `SDI_SW_DOCMGR_KEY` is set, otherwise from the drawings, DXFs and any saved extract. Nobody waits. The run's console and the engine (`SDI_MODEL_READER`) say which. |
| Compute gate | While another run uses the desktop, a slot claims only when free memory is at least `SDI_SLOT_MIN_FREE_GB` (3) and CPU at most `SDI_SLOT_MAX_CPU_PCT` (85%). |
| Service | Runners that both declare `desktop_token` may run on one desktop at once, up to `SDI_MAX_CONCURRENT_RUNS`. A runner with no model reader takes a model job when no able runner is idle (`SDI_RUN_WITHOUT_MODEL_READER`, default on), and the run says so. A SolidWorks pack extract is offered only by a run that can take the token. |
| Checks | `restart-runner.ps1 -Slot N -Root C:\ClaudeVision-sN -TaskName "SDI Estimating Runner sN"` checks that slot, and lists every other runner on the desktop with its build. |

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
