# SDI Intelligence server — build summary for Jack and James

**Date:** Monday 5 October 2026
**Status:** plan agreed in principle; waiting on the reseller's licensing answers before the build week is booked
**The full plan:** `docs/SDI_Intelligence_Server_Build_Who_Does_What.html` (and `.pdf`) in the repository, revision of 5 October

## The decision, in one paragraph

The machine runs **Windows Server 2025** on the metal, with Hyper-V. Everything people use runs inside one **Windows 11 Pro virtual machine (VM 1)** that owns the graphics card: the estimating engine and its runner, the estimating portal and queue, Client Briefing Intelligence, Drawing Search, Excel, SOLIDWORKS, and Technical Design's Windows parts (the SOLIDWORKS Document Manager API, the CAD Validator, the COM tools). A second virtual machine runs **Linux (VM 2)** for Technical Design's server side: PostgreSQL, GitLab with LFS, and the FastAPI services, which call VM 1 over HTTPS. The host runs Hyper-V and the SOLIDWORKS licence manager and nothing else. There is no third VM.

A Windows 11 Pro host was considered and set aside. It cannot hand a graphics card to a VM (Discrete Device Assignment is a Server feature), SOLIDWORKS would then have to run on the metal rather than in a VM, and it allows one Remote Desktop session. Those were the three things asked of this machine, and only a Server host gives all three.

## What runs where

| What | Where | Why there |
|---|---|---|
| Estimating engine, runner, Excel, SOLIDWORKS, the RTX 4000 Ada | VM 1 Windows | Excel and SOLIDWORKS are driven over COM, which needs a logged-in desktop; the card is here |
| Estimating portal and queue (port 8071) | VM 1 Windows | One box for everything estimating; the runner points at localhost |
| Client Briefing Intelligence | VM 1 Windows | Moves as it is |
| Drawing Search (port 5000), including the image search | VM 1 Windows | Indexes W: and opens files on it; the image search uses the card |
| SOLIDWORKS Document Manager API, CAD Validator, COM tools | VM 1 Windows | SOLIDWORKS libraries; Windows only; exposed to VM 2 over HTTPS on one port |
| FastAPI services: Document Manager intelligence layer, Production Design Extraction | VM 2 Linux | Python; no Windows need |
| SDI Design Vault: GitLab with LFS, PostgreSQL | VM 2 Linux | Linux-native; needs its own large disk |
| Hyper-V, SolidNetWork licence manager | Host | Supported on Windows Server; stays up when VM 1 restarts |
| Estimating shares and W: | The file server, as now | This machine is not a file server |

## Sizing

| Where | Cores | Memory | Disk |
|---|---|---|---|
| VM 1 Windows | 16 vCPU | 64 GB, Dynamic Memory off | 500 GB+ NVMe |
| VM 2 Linux | 8 vCPU | 32 GB | 1 TB+ NVMe, growable |
| Host | the remaining 8 | the remaining 32 GB | the OS drive |

The Linux VM's disk is the one figure still open: it depends on how much of W:'s history the Design Vault will hold. The NVMe is 4 TB in total.

## Jack's list, in build order

**Host (Windows Server 2025)**

1. Confirm with Scan that Server 2025 drivers exist for the 3XS board, or where to get them.
2. BIOS: latest firmware; power on after AC loss; virtualisation (SVM) and IOMMU on.
3. Storage: the two NVMe drives (mirror or split OS / VMs, Jack's call); install Windows Server 2025.
4. Fixed IP, DNS name, domain join.
5. Hyper-V role, and an External virtual switch on the machine's network port so both VMs sit on the office network.
6. SolidNetWork licence manager on the host (if the licence is a network one), ports 25734 and 25735 open to VM 1 and to designers' PCs if they share the pool.
7. Admin access for James: Remote Desktop to the host (two sessions), the admin share.

**VM 1 (Windows 11 Pro)**

8. Generation 2, Secure Boot, virtual TPM.
9. 16 vCPU, 64 GB with Dynamic Memory off, 500 GB+ disk; automatic start; automatic stop action "turn off" (DDA requires it).
10. Pass the RTX 4000 through (disable on host, dismount, assign to VM), then NVIDIA's RTX workstation driver inside the VM.
11. Windows 11 Pro, fixed IP and DNS name, domain, fully updated.
12. Runner account: a dedicated domain user with auto-logon (Sysinternals Autologon, Windows Hello off); read/write to the estimating shares, read to W:, by UNC path.
13. No sleep, no hibernate, no lock, no screensaver, exempt from the domain lock policy.
14. Firewall: 8071, 5000 and Client Briefing's port from the office network; the COM tools' port from VM 2 only.
15. Windows Update restarts scheduled out of hours and announced.
16. A `tscon` hand-back script on the runner's desktop; James shown the Hyper-V console route in.

**VM 2 (Linux)**

17. Generation 2, Secure Boot on the Microsoft UEFI Certificate Authority template, no vTPM; 8 vCPU, 32 GB, 1 TB+ growable; automatic start.
18. Ubuntu LTS server, fixed IP and DNS name, SSH for James and Yogesh with sudo accounts.
19. Firewall: GitLab (80/443 and its git-over-SSH port) and the FastAPI port from the office network; PostgreSQL 5432 from VM 1 only.
20. A read-only mount of W: for the FastAPI services, credentials on the VM, not in scripts.

**Running it**

21. Licences: Server 2025 Standard per core (two 16-core packs), client access licences; Windows 11 Pro and Office for VM 1; nothing for Linux.
22. Backups: host and both VMs, plus GitLab's own backup; one restore of each tested before go-live.
23. Updates: host and VM 1 on different nights, James told first; Ubuntu security updates unattended, reboots announced.
24. Antivirus exclusions as James supplies.
25. UPS, power-on after a cut, both VMs auto-start.

## Handover checks (Jack confirms, then it is James's)

- VM 1's Device Manager shows NVIDIA RTX 4000 Ada with the NVIDIA driver.
- After a full host restart, both VMs start themselves; VM 1 is logged in as the runner account and still unlocked an hour later.
- As the runner account, VM 1 opens and saves a file on the estimating share and opens a file on W: by UNC path.
- From VM 1, the licence manager answers on 25734.
- From a desk, VM 1 answers on 8071 and 5000; from VM 2, VM 1 answers on the COM tools' port.
- From James's laptop: Remote Desktop to the host with another admin already connected; the Hyper-V console shows VM 1's desktop; SSH into VM 2 by name, and the W: mount lists a job folder.

## James's list

**VM 1**

1. SOLIDWORKS, pointed at the licence manager; one model opened to confirm the card is in use.
2. Office / Excel; one estimate book opened.
3. PDM / Design Vault client if models come from the vault.
4. Python, Git, the repository, the engine's `.venv`.
5. The `.env` file written by hand for this machine.
6. The estimating portal service on 8071; loads from a desk.
7. The runner as a scheduled task at logon, pointing at the portal on this machine.
8. Client Briefing Intelligence as a service, its approval step tested end to end.
9. Drawing Search on 5000, W: by UNC path, the Fixture Library index built on local disk (allow a day), image search confirmed on the card.
10. The Document Manager API (with its licence key), the CAD Validator and the COM tools beside SOLIDWORKS, exposed to VM 2 over HTTPS; one DXF flat pattern tested from a model on W:.
11. Antivirus exclusion paths and the ports, handed to Jack.

**VM 2, with Yogesh**

12. GitLab with LFS, backups scheduled, the Design Vault repositories created.
13. PostgreSQL, reachable from VM 1 only.
14. The FastAPI services as systemd services, reading W: through the mount, calling VM 1 over HTTPS.
15. One import proven end to end, and one flat pattern requested from VM 1 and received.

**Proving the whole**

16. One known job (12645 or 12173) run on VM 1; book and run time compared with the laptop's.
17. Host restarted; both VMs, the portal, the runner, Client Briefing, Drawing Search and the Linux services all back without anyone logging in.
18. Remote in and out through the Hyper-V console during a short job; the job finishes.
19. The laptop's installed service and runner stopped, so there is one queue.

## The gotchas we have agreed to live with

- The card belongs to VM 1. Touching it means stopping VM 1; the host runs on basic display, which is expected.
- VM 1 allows one desktop. Remote in as the runner account or through the Hyper-V console; never as another user while a job runs.
- Everything on VM 1 restarts together, and a restart mid-run loses that estimate.
- Server 2025 drivers for a workstation board may have to come from the board maker.
- Licences add up: Server Standard per core plus CALs, Windows 11 Pro and Office for VM 1. Nothing for Linux.
- GitLab wants 80/443 and a git-over-SSH port that must not collide with admin SSH on 22.

## Open questions, with owners

| Question | Owner | Blocks |
|---|---|---|
| The reseller's written answers on licensing (activation in a VM; automated use; unattended STEP/PDF/DXF; Document Manager key terms) | James, with the reseller | Booking the build week |
| Server 2025 drivers for the 3XS board | Jack, with Scan | The host install |
| The Linux VM's disk size (how much of W: the vault holds) | James and Yogesh | VM 2 creation |
| Ports and names (James proposes; Yogesh's names UAT-SDI-CAD01 and UAT-SDI-PDM01) | James gives, Jack opens | Firewall rules, every link |
| Who is told before restarts; the remote-access rule | Jack and James | Day-to-day running |

## Sequence and dates

1. This week: the licensing e-mail goes to the reseller; Jack asks Scan about Server drivers.
2. On the reseller's answer to question 1: Jack books the build week.
3. Build week: Jack's list 1 to 25, then the handover checks.
4. The following week: James's list on VM 1, Yogesh and James on VM 2.
5. Proving: known jobs, the host restart, the laptop stood down.
6. Target: the estimating engine, Drawing Search and the Technical Design services live on the server by the end of October, as promised in the 29 September programme note.
