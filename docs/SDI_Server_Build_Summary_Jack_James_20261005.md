# SDI Intelligence server — build summary for Jack and James

**Date:** Monday 5 October 2026
**Roles:** James leads the software design; Jack is SDI's hardware advisor and builds the machine; the Technical Design team installs its own services on the Linux VM
**Status:** ordered from Scan today on a 14-day lead time; on site Monday 19 October; go-live Monday 2 November with a week in hand. Open with Scan today: the quoted board does not support Windows Server 2025, so the order asks for the same build on a board that does; if Scan cannot supply one at the same lead time, the quoted workstation is built on Proxmox and this summary is rewritten with Proxmox as the plan of record
**The full plan:** `docs/SDI_Intelligence_Server_Build_Who_Does_What.html` (and `.pdf`) in the repository, revision of 5 October

## The decision, in one paragraph

The machine runs **Windows Server 2025** on the metal, with Hyper-V. Everything people use runs inside one **Windows 11 Pro virtual machine (VM 1)** that owns the graphics card: the estimating engine and its runner, the estimating portal and queue, Client Briefing Intelligence, Drawing Search, Excel, SOLIDWORKS, and Technical Design's Windows parts (the SOLIDWORKS Document Manager API, the CAD Validator, the COM tools). A second virtual machine runs **Linux (VM 2)** for Technical Design's server side: PostgreSQL, GitLab with LFS, and the FastAPI services, which call VM 1 over HTTPS. The host runs Hyper-V and the SOLIDWORKS licence manager and nothing else. There is no third VM.

Three things are required of the machine: the graphics card inside the Windows 11 VM, SOLIDWORKS inside that VM, and Jack and James logging in from their desks. Windows 11 Pro on the metal cannot give the card to a VM in any supported way, so the host is Windows Server (or a Linux hypervisor as the fallback). It is the same workstation whichever operating system goes on it; nothing about the hardware order changes.

## How Jack and James log in from their desks

| Where | How | Rule |
|---|---|---|
| The host (Windows Server 2025) | Remote Desktop as administrators from each desk, two sessions at once | The normal way in. Nothing a person uses runs on the host, so nothing is interrupted |
| VM 1's desktop (Windows 11 Pro) | From the host: the Hyper-V console, which shows the runner's live desktop without a second log-on | Remote Desktop straight into VM 1 is for the runner account only, when nothing is running, left with the `tscon` hand-back. Any other account pushes the runner off: disabled |
| The Linux VM | SSH by name, from any desk | No desktop there; nothing to interrupt |

## If Windows Server will not drive the board

The board Scan usually fits lists Windows 11 and Linux. Server 2025 shares its driver model with Windows 11 24H2 and the host needs few drivers (no graphics driver at all, since the card is dismounted for pass-through), so it normally runs; normally is not supported. So today's order asks Scan for a board the maker lists for Windows Server 2025 if they can supply one, and the install is proved before the licence is bought.

1. **Prove it first.** On day one Jack installs the free 180-day Windows Server 2025 evaluation and checks Device Manager: no unknown devices, both network ports driven. Clean: the licence is bought and keyed in place.
2. **Fallback that keeps the card in the VM:** Proxmox VE (Linux, KVM) on the metal, which the board maker supports, with the card passed to the Windows 11 VM by VFIO. Jack and James log in to the Proxmox web console and SSH. Loses Dassault's listing: KVM is not on their supported-hypervisor list, so a SOLIDWORKS graphics fault is ours to prove.
3. **Fallback that gives up the VM:** Windows 11 Pro on the metal, SOLIDWORKS on it with the card, the Linux VM under Hyper-V, a console-sharing tool for two-desk access.

Decided now, so day one is a check and not a meeting.

## What runs where

| What | Where | Why there |
|---|---|---|
| Estimating engine, runner, Excel, SOLIDWORKS, the RTX 4000 Ada | VM 1 Windows | COM needs a logged-in desktop; the card is here; SOLIDWORKS does not run on Windows Server |
| Estimating portal and queue (port 8071) | VM 1 Windows | One box for everything estimating; the runner points at localhost |
| Client Briefing Intelligence | VM 1 Windows | Moves as it is |
| Drawing Search (port 5000), including the image search | VM 1 Windows | Indexes W: and opens files on it; the image search uses the card |
| SOLIDWORKS Document Manager API, CAD Validator, COM tools | VM 1 Windows | SOLIDWORKS libraries, Windows only; exposed to the Linux VM over HTTPS on one port |
| FastAPI services: Document Manager intelligence layer, Production Design Extraction | VM 2 Linux | Python; no Windows need |
| SDI Design Vault: GitLab with LFS, PostgreSQL | VM 2 Linux | Linux-native; needs its own large disk |
| Hyper-V, SolidNetWork licence manager, Remote Desktop for Jack and James | Host | Supported on Windows Server; two admin sessions |
| Estimating shares and W: | The file server, as now | This machine is not a file server |

## Sizing

| Where | Cores | Memory | Disk |
|---|---|---|---|
| VM 1 Windows | 16 vCPU | 64 GB, Dynamic Memory off | 500 GB+ NVMe |
| VM 2 Linux | 8 vCPU | 32 GB | 1 TB+ NVMe, growable |
| Host | the remaining 8 | the remaining 32 GB | the OS drive |

## Jack's list, in build order

**Before it arrives (5 to 16 October)**

1. The order to Scan today: the quoted build, on a board the maker lists for Windows Server 2025 if Scan can supply one, else written confirmation of the board model and its Server 2025 driver source; delivery date, a free slot and power for a second card, storage mirroring, memory population, a management controller if the board has one, and warranty, all in writing.
2. Server media ready: the Windows Server 2025 evaluation ISO, the board maker's driver package, NVIDIA's RTX workstation driver for VM 1, the Ubuntu LTS server ISO.
3. Accounts and names: the portal's service account, the runner account, the host's and both VMs' names and fixed IPs; firewall rules drafted from James's port list; Jack's and James's Remote Desktop access to the host on the domain.

**The host (Windows Server 2025), from 19 October**

4. BIOS: latest firmware; power on after AC loss; virtualisation (SVM), IOMMU and above-4G decoding on.
5. Prove it: the Server 2025 evaluation on the first NVMe, the drivers applied, Device Manager clean and both network ports driven. Clean: licence bought and keyed; not clean: stop and take the fallback ladder with James.
6. Storage: the second NVMe for the VMs.
7. Fixed IP, DNS name, domain join; Remote Desktop for Jack and James as administrators.
8. Hyper-V role, and an External virtual switch on the machine's network port.
9. SolidNetWork licence manager on the host if the licence becomes a network one, ports 25734 and 25735 open to VM 1.
10. The admin share for James.

**VM 1 (Windows 11 Pro)**

11. Generation 2, Secure Boot, virtual TPM.
12. 16 vCPU, 64 GB with Dynamic Memory off, 500 GB+ disk; automatic start; automatic stop action "turn off" (DDA requires it).
13. Pass the RTX 4000 through (disable on host, dismount, assign to VM), then NVIDIA's RTX workstation driver inside the VM.
14. Windows 11 Pro, fixed IP and DNS name, domain, fully updated.
15. Runner account with auto-logon (Sysinternals Autologon, Windows Hello off); read/write to the estimating shares, read to W:, by UNC path.
16. No sleep, no hibernate, no lock, no screensaver, exempt from the domain lock policy.
17. Remote access into VM 1: Remote Desktop for the runner account only; a `tscon` hand-back script on its desktop; the Hyper-V console route shown.
18. Firewall: 8071, 5000 and Client Briefing's port from the office network; the COM tools' port from the Linux VM only.
19. Windows Update restarts scheduled out of hours and announced.

**VM 2 (Linux)**

20. Generation 2, Secure Boot on the Microsoft UEFI Certificate Authority template, no vTPM; 8 vCPU, 32 GB, 1 TB+ growable; automatic start.
21. Ubuntu LTS server, fixed IP and DNS name, SSH for James and the Technical Design team with sudo accounts.
22. Firewall: GitLab (80/443 and its git-over-SSH port) and the FastAPI port from the office network; PostgreSQL 5432 from VM 1 only.
23. A read-only mount of W: for the FastAPI services, credentials on the VM, not in scripts.

**Running it**

24. Licences: Server 2025 Standard per core (two 16-core packs) and client access licences, bought on the clean driver check; Windows 11 Pro and Office for VM 1; nothing for Linux.
25. Backups: host and both VMs, plus GitLab's own backup; one restore of each tested before go-live.
26. Updates: host and VM 1 on different nights, James told first; Ubuntu security updates unattended, reboots announced.
27. Antivirus exclusions as James supplies.
28. UPS, power-on after a cut, both VMs auto-start.

## Handover checks (Jack confirms, then it is James's)

- The host's Device Manager shows no unknown devices and both network ports driven; the licence is keyed in.
- VM 1's Device Manager shows NVIDIA RTX 4000 Ada with the NVIDIA driver.
- After a full host restart, both VMs start themselves; VM 1 is logged in as the runner account and still unlocked an hour later.
- As the runner account, VM 1 opens and saves a file on the estimating share and opens a file on W: by UNC path.
- From VM 1, the licence manager answers on 25734 (if the licence is a network one).
- From a desk, VM 1 answers on 8071 and 5000; from VM 2, VM 1 answers on the COM tools' port.
- From Jack's desk and from James's at the same time: Remote Desktop to the host; the Hyper-V console shows VM 1's desktop with the runner still logged in; SSH into VM 2 by name, and the W: mount lists a job folder.

## James's list

**Before it arrives (5 to 16 October)**

1. The SOLIDWORKS licence position, settled from SDI's licence agreement: activation in a Hyper-V VM; automated, server-side use; unattended STEP, PDF and DXF generation; the Document Manager API key terms. The reseller is asked only where the agreement is silent. This gates SOLIDWORKS automation going live, not the order.
2. Installers, the port list and the antivirus exclusion paths ready for Jack.

**VM 1, from 23 October**

3. SOLIDWORKS installed and activated (or pointed at the licence manager); one model opened to confirm the card is in use.
4. Office / Excel; one estimate book opened.
5. PDM / Design Vault client if models come from the vault.
6. Python, Git, the repository, the engine's `.venv`.
7. The `.env` file written by hand for this machine.
8. The estimating portal service on 8071; loads from a desk.
9. The runner as a scheduled task at logon, pointing at the portal on this machine.
10. Client Briefing Intelligence as a service, its approval step tested end to end.
11. Drawing Search on 5000, W: by UNC path, the Fixture Library index built on local disk (allow a day), image search confirmed on the card.
12. The Document Manager API (with its licence key), the CAD Validator and the COM tools beside SOLIDWORKS, exposed to the Linux VM over HTTPS; one DXF flat pattern tested from a model on W:.
13. Antivirus exclusion paths and the ports, handed to Jack.

**VM 2, with the Technical Design team**

14. GitLab with LFS on its own port, backups scheduled, the Design Vault repositories created.
15. PostgreSQL, reachable from VM 1 only.
16. The FastAPI services as systemd services, reading W: through the mount, calling VM 1 over HTTPS.
17. One import proven end to end, and one flat pattern requested from VM 1 and received.

**Proving the whole (29 and 30 October)**

18. One known job (12645 or 12173) run on VM 1; book and run time compared with the laptop's.
19. Host restarted; both VMs, the portal, the runner, Client Briefing, Drawing Search and the Linux services all back without anyone logging in.
20. Remote in and out through the Hyper-V console during a short job on VM 1; the job finishes.
21. The laptop's installed service and runner stopped, so there is one queue.

## The gotchas we have agreed to live with

- The card belongs to VM 1. Touching it means stopping VM 1; the host runs on basic display, which is expected.
- VM 1 allows one desktop. Reach it through the Hyper-V console, or by Remote Desktop as the runner with the `tscon` hand-back; never another user while a job runs.
- Prove Server before paying for it: the evaluation first, the licence on a clean Device Manager, the fallback ladder otherwise.
- Everything on VM 1 restarts together, and a restart mid-run loses that estimate.
- Licences add up: Server Standard per core plus CALs, Windows 11 Pro and Office for VM 1. Nothing for Linux.
- GitLab wants 80/443 and a git-over-SSH port that must not collide with admin SSH on 22.

## Open questions, with owners

| Question | Owner | Blocks |
|---|---|---|
| Scan's written confirmations with today's order: a Server-listed board or the board model and its driver source; delivery date; second-card slot and power; storage mirroring; memory; management controller; warranty | Jack, with Scan | Whether day one is a formality or a gamble; every date |
| SOLIDWORKS licensing, ours to answer from the licence agreement | James | SOLIDWORKS automation going live |
| The fallback decision rule on day one: Server on a clean check; otherwise Proxmox (keeps the card in the VM) or Windows 11 Pro on the metal (gives it up) | Jack and James | Day one |
| The Linux VM's disk size (how much of W: the vault holds) | James, with Technical Design | VM 2 creation |
| Ports and names | James gives, Jack opens | Firewall rules, every link |
| Who is told before restarts; the remote-access rule into VM 1 | Jack and James | Day-to-day running |

## Sequence and dates

[[GANTT]]

| Step | Who | When |
|---|---|---|
| Order placed with Scan, on a Server-listed board if offered | Jack and James | Mon 5 October |
| 14-day lead time | Scan | 5 to 18 October |
| SOLIDWORKS licence and activation position settled | James | 5 to 16 October |
| Preparation: Server media, accounts, firewall rules, installers, Linux build scripts | Jack, James, Technical Design | 6 to 16 October |
| Hardware arrives on site | Scan | Mon 19 October |
| Server 2025 evaluation installed; every device driven, or the fallback | Jack | 19 and 20 October |
| Server licence and CALs bought on a clean driver check | James | Tue 20 October |
| Host, VM 1 with the card (DDA), the Linux VM built; handover checks | Jack | 20 to 23 October |
| VM 1 services: estimating, portal, Client Briefing, Drawing Search, DM API tools | James | 23 to 29 October |
| Linux VM services: GitLab, PostgreSQL, FastAPI | Technical Design | 23 to 29 October |
| Proving: known jobs, full restart, remote in-and-out test | James | 29 and 30 October |
| Go-live; the laptop stood down as the production machine | James | Mon 2 November |

The delivery date is the only thing that moves every other date. A later delivery moves the bars right; go-live holds in the week commencing 2 November with a week in hand.
