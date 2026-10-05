# E-mail to the SOLIDWORKS reseller — licensing for the SDI Intelligence server

**To:** [reseller account manager], [reseller licensing desk]
**Cc:** Yogesh Kumar; Jack [surname]
**From:** James Gray, SDI
**Subject:** SOLIDWORKS 2026 licensing for a virtualised, automated server at SDI — three questions needing written answers

Dear [name],

SDI is building a new server for its estimating and technical-design work and we need your written confirmation on how our SOLIDWORKS licence may be used on it before the build is booked. The technical platform is on Dassault's supported list; the questions below are about the licence terms, which we do not want to infer from that list.

## What we are building

- One physical machine (Scan 3XS, AMD Threadripper PRO 9975WX, 32 cores, 128 GB, NVIDIA RTX 4000 Ada SFF 20 GB).
- The operating system on the machine is **Windows Server 2025**, running **Microsoft Hyper-V 2025**.
- **SOLIDWORKS 2026** is installed in one **Windows 11 Pro virtual machine** on that host, with the RTX 4000 Ada passed through to that VM (Discrete Device Assignment), so SOLIDWORKS sees the physical card with NVIDIA's RTX workstation driver.
- The **SolidNetWork Licence Manager**, if we move to a network licence, would run on the Windows Server 2025 host.
- A second virtual machine runs Linux (Ubuntu) and does not run SOLIDWORKS. It calls the Windows VM over HTTPS for anything that needs SOLIDWORKS or the SOLIDWORKS Document Manager API.

## How SOLIDWORKS is used on it

SOLIDWORKS is driven by SDI's own software through the SOLIDWORKS API (COM), with no person at the screen, during working hours, on one seat. It opens our own models and drawings, reads geometry, cut lists and bills of materials for estimating, and generates DXF flat patterns, drawings and STEP and PDF exports. The seat is kept open by the automation all day and is used by nobody else while it runs. The same software will also use the **SOLIDWORKS Document Manager API** (with its licence key) on the Windows VM to read file properties and references without opening SOLIDWORKS.

Our current licence is the permanent seat installed on the estimating laptop in September; the serial number is on your records under SDI's account. [Serial number, if known]

## The three questions

1. **Activation and use in a virtual machine.** May this licence be activated and used in a Windows 11 Pro VM under Hyper-V 2025 on Windows Server 2025? If a standalone licence is tied to the VM's identity and needs reactivating when the VM is rebuilt or moved, please say so. If a SolidNetWork (network) licence is the right form for this, please quote the cost of converting our seat, and confirm that the licence manager is supported on Windows Server 2025 with SOLIDWORKS 2026.
2. **Automated, server-side use.** Does the licence permit SOLIDWORKS to be driven by our own software through the API, unattended, as described above? If this needs a different licence type or an additional product, please name it and quote it.
3. **Unattended generation of STEP, PDF and DXF files.** What licence covers our software generating STEP, PDF and DXF files from our own models and drawings without a person present? If this is covered by the answer to question 2, please confirm that in writing; if not, please name and quote what is required.

And separately:

4. **The Document Manager API licence key.** Please confirm the terms that apply to SDI's use of the Document Manager API key inside our own internal application (internal use only, reading SDI's own files, no redistribution), and whether anything about the server arrangement above changes them.

## What we need back

Written answers to the four points, with any quotations, by **[date, two weeks from sending]**. The server build is booked once question 1 is answered, and the rest determine what we order with it.

Two confirmations would also help, if you can give them from Dassault's documentation: that SOLIDWORKS 2026 lists Hyper-V 2025 as a supported virtual environment, and that a certified card passed through to the VM meets the GPU recommendation for virtual machines.

Thank you. Happy to take a call if any of this is easier discussed; Yogesh Kumar, who leads the technical-design side, is copied.

Kind regards,

James Gray
SDI
[phone]
