# SDI Intelligence server — summary for the Managing Director and Finance Director

**Date:** Monday 5 October 2026
**From:** James Gray
**What this asks for:** approval of the operating-system and licensing approach, and of the licence spend set out below, so the build can be booked as soon as the SOLIDWORKS reseller answers.

Matt, Charlotte,

## What we are building, and why

The SDI Intelligence services run today on one estimating laptop. That laptop prices jobs, serves the estimating portal, holds the only SOLIDWORKS seat the engine can use, and is also James's development machine. It cannot be left running for the estimators and the studio, it cannot be reached from their desks reliably, and when it is busy with one estimate nothing else happens.

The new machine, a Scan 3XS workstation (AMD Threadripper PRO, 32 cores, 128 GB, NVIDIA RTX 4000 Ada graphics card, 4 TB of fast storage), replaces that laptop as the production machine. It will carry four things:

- **AI estimating.** The estimating engine and its queue: an estimator starts a job from the portal at their desk, the server prices it, and the book and report come back.
- **Client Briefing Intelligence.** A client brief arrives by e-mail, call or voice note and comes back as one structured brief with the gaps named.
- **Drawing Search.** The Fixture Library: 455,000 fixtures across 188 brands, searchable by name, by brand or by a photograph, opening the drawing, the CAD model and the job folder in one click.
- **Technical Design Intelligence.** Yogesh's work: the Document Manager that reads SOLIDWORKS project data directly, and the SDI Design Vault, our own product-data management, which goes to a go / no-go against the Dassault product at the end of October.

The 29 September programme note promised the first three live on the server by the end of October. This machine is what that promise rests on.

## The decision we have made, and why it matters to the cost

The machine will run **Windows Server 2025** as its operating system, with everything people use inside a **Windows 11 virtual machine**, and a second **Linux virtual machine** for Technical Design.

We looked hard at the cheaper alternative, running Windows 11 Pro directly on the machine, because Windows 11 Pro comes free with the workstation and Windows Server does not. It was set aside for three reasons, each of which is a requirement, not a preference:

1. **The graphics card must be usable inside a virtual machine.** SOLIDWORKS needs it, and SOLIDWORKS must run in a virtual machine so it can be rebuilt, backed up and moved without touching the operating system underneath. Only Windows Server can hand a graphics card to a virtual machine. Windows 11 Pro cannot.
2. **SOLIDWORKS must run in a virtual machine.** Dassault supports SOLIDWORKS 2026 on Windows 11 and on Hyper-V 2025, which is what Windows Server 2025 provides. It is not supported on Windows Server itself.
3. **More than one person must be able to administer the machine remotely** without interrupting the estimating run. Windows Server allows two administrator sessions; Windows 11 Pro allows one, and it is the one the estimating engine is using.

Yogesh reviewed this independently on 5 October and reached the same design.

## What it costs

Indicative figures, ex VAT, to be confirmed by the suppliers' quotes. The hardware itself is as quoted by Scan and is not repeated here.

| Item | Indicative cost | Note |
|---|---|---|
| Windows Server 2025 Standard, licensed per core, two 16-core packs for the 32-core processor | about £2,000 one-off | The cost of choosing Server over Windows 11 Pro. Windows 11 Pro would have been free with the machine. |
| Windows Server client access licences | about £40 each, number to confirm | Microsoft requires one per user or device that uses the server; Jack and the reseller will confirm the count. |
| Windows 11 Pro licence for the virtual machine | about £200 one-off | The free copy with the workstation licenses the machine itself, not a virtual machine. |
| Microsoft Office for the virtual machine | per our existing agreement | Excel is what the estimate books run in. |
| SOLIDWORKS: possible conversion of our seat to a network licence, and any licence needed for unattended automated use | unknown until the reseller answers | This is the one figure we cannot give yet. The questions have gone to the reseller in writing. |
| Linux virtual machine | nothing | Ubuntu is free. |
| Second graphics card | not in this build | Only if Technical Design later runs models on the Linux side. |

The Server licence is the only cost that the operating-system decision adds, and it buys the three requirements above.

## What we are asking the SOLIDWORKS reseller, and why it matters

Dassault's published requirements confirm the technical platform. They do not say what our licence permits. Three questions have gone to the reseller in writing, at Yogesh's prompting:

1. May our licence be activated and used in a virtual machine?
2. Does it permit SOLIDWORKS to be driven by our own software, unattended, as the estimating engine does all day?
3. What licence covers our software generating STEP, PDF and DXF files without a person present?

The honest position is that SOLIDWORKS licences are written for a person at a screen, and we drive it by machine. The answer may be "yes, as you are", or it may name a different licence with a cost. We will not book the build until question 1 is answered, and we will bring the answer to the other two to you with its price before we commit to it.

## Timeline

| Step | When |
|---|---|
| Licensing questions to the reseller; Scan asked about Server drivers | This week |
| Build week booked (Jack) | On the reseller's answer to question 1 |
| Jack builds the host and the two virtual machines; handover checks | Build week |
| James installs the estimating services, Client Briefing and Drawing Search; James and Yogesh install the Technical Design services | The following week |
| Proving: known jobs re-run and compared with the laptop; a full restart; the laptop stood down as the production machine | The week after |
| Live for estimators and the studio | End of October, as in the 29 September note |

## What could go wrong, and what we have done about it

- **The licence does not permit automated use.** We learn this from the reseller before any money is spent on the build, and the choice is then the right licence at its price, or a different way of reading models. Nothing else in the build changes.
- **One estimate at a time.** There is one runner, as today. If the queue backs up, a second Windows virtual machine with a runner can be added later for the cost of its Windows and Office licences; it is designed for and not built.
- **Everything on the Windows virtual machine restarts together.** A Windows update mid-estimate loses that estimate. Updates are scheduled out of hours and James is told first.
- **Run time.** An estimate currently takes much longer than it should on the laptop, and the server will be faster but will not fix that by itself. The engine's own timing table is being used to find where the minutes go; that work is separate from the build.
- **Drivers.** Scan supplies Windows 11 drivers for this workstation; the Server install may need the board maker's. Jack is confirming before the build week.

## What we need from you

1. Approval of the Windows Server 2025 approach and the licence spend in the table above, about £2,200 plus client access licences, plus Office under our existing agreement.
2. Agreement in principle that if the reseller's answer to the automation questions carries a cost, it comes back to you with the figure before we commit.
3. Nothing else is needed from you for the build to proceed on the reseller's answer.

James
