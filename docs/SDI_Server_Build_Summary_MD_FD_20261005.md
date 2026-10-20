# SDI Intelligence server — summary for the Managing Director and Finance Director

**Date:** Monday 5 October 2026
**From:** James Gray (software design lead); Jack, SDI's hardware advisor, builds the machine
**What this is:** the machine we are ordering today, what it carries, the one decision still open with the supplier, what it costs beyond the hardware, and the dates

Matt, Charlotte,

## What we are building, and why

The SDI Intelligence services run today on one estimating laptop. That laptop prices jobs, serves the estimating portal, holds the only SOLIDWORKS seat the engine can use, and is also my development machine. It cannot be left running for the estimators and the studio, it cannot be reached from their desks reliably, and when it is busy with one estimate nothing else happens.

The new machine, a Scan 3XS workstation (AMD Threadripper PRO, 32 cores, 128 GB, an NVIDIA RTX 4000 Ada graphics card, 4 TB of fast storage), replaces that laptop as the production machine. Jack and I are placing the order today on Scan's 14-day lead time. It carries four things:

- **AI estimating.** The estimating engine and its queue: an estimator starts a job from the portal at their desk, the server prices it, and the book and report come back.
- **Client Briefing Intelligence.** A brief arrives by e-mail, call or voice note and comes back as one structured brief with the gaps named.
- **Drawing Search.** The Fixture Library: 455,000 fixtures across 188 brands, searchable by name, by brand or by a photograph, opening the drawing, the CAD model and the job folder in one click.
- **Technical Design Intelligence.** The Document Manager that reads SOLIDWORKS project data directly, and the SDI Design Vault, our own product-data management, which goes to a go or no-go against the Dassault product at the end of October.

The 29 September programme note promised the first three live on the server by the end of October. With delivery on 19 October, go-live is Monday 2 November with a week in hand: a few days later than that note said.

## How it is set up, and the one decision still open

Three things are required of this machine: the graphics card must sit inside a Windows 11 virtual machine, SOLIDWORKS must run inside that virtual machine, and Jack and I must be able to log in from our desks without interrupting an estimate. Virtual machines are what let SOLIDWORKS be rebuilt, backed up and moved without touching the operating system underneath, and let Technical Design's Linux services share the same box.

Windows 11 Pro, the operating system Scan supplies with the machine, cannot give a graphics card to a virtual machine. So the machine runs a hypervisor underneath, with a Windows 11 virtual machine holding the card and everything people use, and a Linux virtual machine for Technical Design. There are two ways to do that, and Scan's answer today decides which:

1. **Windows Server 2025** as the operating system on the machine. Dassault lists it for SOLIDWORKS, Microsoft supports it, and it gives two administrator log-ins at once. Scan has told us the board in the quoted build does not support it, so we have asked them today for the same build on a board that does, at the same lead time.
2. **A Linux hypervisor (Proxmox) on the quoted workstation**, if Scan cannot offer a Windows Server board at the same lead time. The board supports Linux, the card passes through to the Windows virtual machine, and we log in from our desks the same way. It costs nothing in licences. What it gives up is Dassault's formal support statement for the virtual environment: SOLIDWORKS runs this way widely, but if it ever misbehaved the problem would be ours to prove.

Either way the hardware order goes today and the dates hold. The choice changes one licence line below and nothing else.

## What it costs beyond the hardware

Indicative, ex VAT, to be confirmed by the suppliers' quotes. The hardware is as quoted by Scan and is not repeated.

| Item | Indicative cost | Note |
|---|---|---|
| Windows Server 2025 Standard, licensed per core, two 16-core packs, plus client access licences at about £40 each | about £2,000 plus CALs, **only if route 1** | Nothing if we build on Proxmox. Bought only after the operating system has installed cleanly on the delivered machine. |
| Windows 11 Pro licence for the virtual machine | about £200 one-off | The free copy with the workstation licenses the machine itself, not a virtual machine. |
| Microsoft Office for the virtual machine | per our existing agreement | Excel is what the estimate books run in. |
| Linux virtual machine, and Proxmox if route 2 | nothing | Both are free. |
| SOLIDWORKS: a possible change of licence if unattended automated use needs one | unknown until settled | See below. The one figure we cannot give yet. |
| Second graphics card | not in this build | Only if Technical Design later runs models on the Linux side. |

## The SOLIDWORKS licence: ours to settle

Dassault's published requirements confirm the technical platform. They do not say what our licence permits, and that is for us to establish from our own licence agreement, not for a vendor. Three points are being settled this fortnight: that the licence may be activated in a virtual machine; whether it permits SOLIDWORKS to be driven by our own software, unattended, as the estimating engine does all day; and what covers our software generating STEP, PDF and DXF files without a person present. The reseller is asked only where the agreement is silent.

The honest position is that SOLIDWORKS licences are written for a person at a screen, and we drive it by machine. The answer may be "yes, as we are", or it may point to a different licence with a cost. It does not hold up the order or the build; it gates the moment SOLIDWORKS automation goes live, and if it carries a cost that comes back to you with the figure before we commit.

## Timeline

[[GANTT]]

| Step | When |
|---|---|
| Order placed with Scan; 14-day lead time; Scan's answer on a Windows Server board | Monday 5 October |
| SOLIDWORKS licence position settled; accounts, firewall rules and installers prepared | 5 to 16 October |
| Hardware arrives on site | Monday 19 October |
| The operating system installed and proved on the delivered machine; the Server licence bought only on a clean result | 19 and 20 October |
| Jack builds the host and the two virtual machines; handover checks | 20 to 23 October |
| I install the estimating services, Client Briefing, Drawing Search and SOLIDWORKS; the Technical Design team installs its services | 23 to 29 October |
| Proving: known jobs re-run and compared with the laptop; a full restart | 29 and 30 October |
| Live for estimators and the studio; the laptop stood down | Monday 2 November, with a week in hand |

## What could go wrong, and what we have done about it

- **Delivery slips.** Every later date moves with it; go-live holds in the week commencing 2 November with a week in hand. Jack has Scan's delivery date in writing.
- **Windows Server will not install cleanly on the delivered board.** We find out on day one with the free evaluation edition, before the licence is bought, and build on Proxmox instead. Nothing bought today is wasted.
- **The licence does not permit automated use.** We establish this ourselves before SOLIDWORKS automation goes live. The choice is then the right licence at its price, or a different way of reading models. Nothing else in the build changes.
- **One estimate at a time.** There is one runner, as today. If the queue backs up, a second Windows virtual machine with a runner can be added later for the cost of its Windows and Office licences; it is designed for and not built.
- **Everything in the Windows virtual machine restarts together.** A Windows update mid-estimate loses that estimate. Updates are scheduled out of hours and I am told first.
- **Run time.** An estimate currently takes much longer than it should on the laptop. The server will be faster but will not fix that by itself; the engine's own timing table is being used to find where the minutes go, and that work is separate from the build.

## What we need from you

1. Approval in principle of the Windows Server licence spend, about £2,000 plus client access licences, to be spent only if Scan supplies a Windows Server board and it installs cleanly; nothing if we build on Proxmox.
2. Agreement in principle that if the SOLIDWORKS licence position on automation carries a cost, it comes back to you with the figure before we commit.
3. A note of the go-live date, Monday 2 November, for the estimators and the studio.

James
