# Email draft — SOLIDWORKS licences + server hardware

**To:** Managing Director; Finance Director
**CC:** Jack (IT cost rationalisation); Yogesh
**Subject:** SDI Intelligence — 3 × SOLIDWORKS licences and server hardware: approval request

---

Dear [MD], [FD],

I'm writing to request approval for two related items needed to keep SDI Estimating
Intelligence and SDI Design Intelligence moving toward the September / October go-live:
**three SOLIDWORKS Standard subscriptions**, and a **server to run the estimating engine**.

I've set out what each is for, the options, and indicative costs below. I'm conscious this
lands while Jack is working to reduce IT hardware and vendor spend, so I've included the
cheaper alternatives and what we lose by taking them.

---

## 1. SOLIDWORKS licences — the immediate item

**The free licences have expired.** Yogesh and I have been running on the introductory
subscription for six weeks (one month free plus a two-week extension). SOLIDWORKS have
confirmed they will not extend further, so continuing requires a paid subscription.

**We need three, not two:**

| # | Seat | What it does |
|---|------|--------------|
| 1 | **James** | SDI Estimating Intelligence development and the parallel run |
| 2 | **Yogesh** | SDI Design Intelligence — automated creation of technical drawings (.DXF and related) via the COM API, to fast-track design output |
| 3 | **The server** | The estimating engine drives SOLIDWORKS directly to read the models |

The third seat is the one that may not be obvious, so to be explicit: **SDI Estimating
Intelligence inspects `.sldprt`, `.sldasm`, `.dxf` and `.dwg` files using the native
SOLIDWORKS COM API.** That is what lets it read a part's true material, gauge, flat pattern
and weldment cut list rather than inferring them from a PDF — the difference between an
estimate built on measurements and one built on guesses. It also reads `.dxf` via the open
`ezdxf` library, but that covers flat geometry only; the model data needs SOLIDWORKS itself.

That automation runs as its own process on the server. SOLIDWORKS COM binds within a Windows
session, so a seat in use on a person's desktop cannot serve the engine — the server needs
its own.

*(Muhammed remains on his free subscription, and reports a student option at roughly $60/year
beyond that. We will see how far that goes; he is not part of this request.)*

### Licence options

Both from CAD Software Direct, SOLIDWORKS Design Standard:

| Option | Terms | Cost per seat | 3 seats |
|---|---|---|---|
| **Monthly subscription** (min. 12 months) | Monthly payment, 12-month commitment | £[  ] /month | £[  ] /month · £[  ] /yr |
| **Quarterly in advance** | Paid quarterly | £[  ] /quarter | £[  ] /quarter · £[  ] /yr |

- Monthly: <https://solidworks.cadsoftwaredirect.com/store/3dexperience-solidworks-standard-monthly-subscription-min-12-months/>
- Quarterly: <https://solidworks.cadsoftwaredirect.com/store/solidworks-standard-quarterly/>

**Recommendation:** [monthly / quarterly] — [monthly preserves cash flow and matches the
project's stage; quarterly is typically the lower annual figure. Confirm once the exact
figures are in.]

---

## 2. Server hardware

### Where we are now

The estimating engine currently runs on **my laptop** — 64GB RAM, Intel Core Ultra 9. A single
estimating job saturates it. Yogesh's drawing-creation automation is a second workload of
similar weight. Neither is sustainable on personal machines, and neither survives a laptop
being closed, taken to a meeting, or replaced.

### What the workload actually needs

This is worth stating plainly because it points away from a conventional server purchase:

- **High clock speed matters more than core count.** SOLIDWORKS is largely single-threaded for
  model rebuilds. A typical many-core, low-clock server CPU would be *slower* than my laptop.
- **Memory bandwidth matters for two concurrent users.** A standard desktop-class platform has
  two memory channels; two CAD workloads will contend for them. A workstation-class platform
  (8 channels) is the fix.
- **PCIe lanes** — needed for the GPU and fast storage together.
- **A GPU is required**, for SOLIDWORKS' viewport and for further processes we intend to host
  on the server. It is *not* needed for the AI itself: all language-model calls are made to
  external APIs, so nothing is computed on our hardware.

### Two options

**Option A — one shared server (recommended if we want a single managed asset)**

| Component | Specification | Indicative (ex VAT) |
|---|---|---|
| CPU | Workstation-class, high clock, 16–24 cores (AMD Threadripper PRO or Intel Xeon W-3500 class) | £2,000 – £2,800 |
| Motherboard | 8-channel, high PCIe lane count | £700 – £1,000 |
| Memory | 128GB ECC DDR5 | £700 – £1,200 |
| GPU | Professional card, certified for SOLIDWORKS | £500 – £1,400 |
| Storage | 2 × 2TB NVMe | £300 – £500 |
| PSU / chassis / cooling | Sized to accept a larger GPU later | £500 – £800 |
| Windows Server licence | If not covered by existing agreements | £700 – £1,000 |
| **Total (self-built)** | | **£5,400 – £8,700** |
| **Total (vendor-built, Dell/HP/Lenovo, with warranty)** | | **£8,000 – £12,000** |

**Option B — two separate machines (lower cost, lower risk)**

Two workstation-class machines at 64GB each, one per user, at roughly **£3,000 – £4,500 each
(£6,000 – £9,000 total)**.

This avoids the licensing and session complexity of two people driving SOLIDWORKS on one
machine, isolates failures, and lets either be rebooted without stopping the other. It gives up
the single managed asset and the shared GPU.

> **All hardware figures are indicative ranges based on component class, for budgeting only.
> They require supplier quotes before commitment.**

### Before we commit

I intend to measure a live estimating run — peak memory and whether the load falls on one core
or spreads — and ask Yogesh to do the same on a drawing-creation run. Two measurements will
confirm whether 128GB is headroom or necessity, and whether we are buying clock speed or cores.
That should sharpen these figures before any order is placed.

---

## 3. Summary of the ask

| Item | Indicative cost | Timing |
|---|---|---|
| 3 × SOLIDWORKS Design Standard | £[  ] per [month/quarter] | **Immediate** — licences have expired |
| Server hardware (Option A or B) | £5,400 – £12,000 one-off | Ahead of September / October go-live |

**The licences are the urgent item.** Both Yogesh and I are currently unable to work on the
SOLIDWORKS-dependent parts of the project, and the estimating engine cannot read model data
without a seat — it falls back to reading PDFs, which is materially less accurate.

The hardware can follow. In the meantime I can run the intranet portal and the engine from my
laptop; once we have the domain account and the hardware, the same deployment moves across
unchanged.

Happy to walk either of you through the detail, or to bring Jack in on the hardware options —
Option B in particular may fit the rationalisation work better than Option A.

Kind regards,

James Gray

---

## Notes before sending (delete this section)

- **SOLIDWORKS prices are placeholders.** Fill from the two links — I could not reach the
  vendor site from the build environment, and did not want estimated figures going to Finance.
- **Decide monthly vs quarterly** once the figures are in, and state the recommendation.
- **Confirm the Windows Server licence line** — may already be covered by an existing agreement,
  in which case remove it.
- **Consider whether to name Muhammed's student licence at all** — included for completeness,
  but it may invite a question you would rather not open yet.
- **Option A vs B**: I have not picked one for you. A is the better long-term asset; B is
  cheaper, lower-risk technically, and reads better against a cost-rationalisation programme.
- Your point about personally funding tokens beyond the company's xAI usage is not in the
  draft — worth raising, but it is a different conversation from a capital request and will
  land better on its own.
