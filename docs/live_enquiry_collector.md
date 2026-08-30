# Live Enquiry drawing collector

Provisional agent that watches the manual **Live Enquiry** workbook, finds PDF/DXF files under `W:\Production\<Customer>`, copies them into `K:\Estimating\Completed\AI Estimating\Live Enquiry\<Drawing - Description>`, and emails a **found / missing** report.

## Setup

1. From `C:\ClaudeVision` with venv active:

   ```powershell
   pip install pandas openpyxl xlrd python-dotenv
   ```

   (`xlrd` is required if the workbook is `.xls`.)

2. Copy `config\live_enquiry_collector.example.env` values into `C:\ClaudeVision\.env` (or set Windows environment variables).

3. Set **SMTP** and **LIVE_ENQUIRY_EMAIL_TO** so you receive reports.

## Commands

```powershell
cd C:\ClaudeVision
.\.venv\Scripts\python.exe -u src\live_enquiry_collector.py --once --dry-run
.\.venv\Scripts\python.exe -u src\live_enquiry_collector.py --once
.\.venv\Scripts\python.exe -u src\live_enquiry_collector.py --watch
```

| Flag | Meaning |
|------|---------|
| `--watch` | Poll the workbook every 60s (configurable); on change, process **new** rows only |
| `--once` | Process all rows not yet in state file, then exit |
| `--dry-run` | Search and report only — no copy, no email |
| `--reset-state` | Clear processed-row memory (re-run all rows on next cycle) |
| `-v` | Verbose logging |

## Behaviour

- Reads sheet **Live Enquiries** (configurable); finds columns **Customer**, **Drawing No.**, **Job Description**.
- Splits drawing cells like `10886 + 11030` into separate search tokens.
- Maps customer names to folders under `W:\Production` (aliases: TTI→`TTi`, Boots→`Boots`, etc.).
- Recursively searches for `.pdf` / `.dxf` (skips `Archive` / `Old` folders).
- Creates destination folder: `{first drawing token} - {job description}` (same style as `1282 - Milwaukee Wall Bay`).
- Tracks processed rows in `output\live_enquiry_collector_state.json` so the same line is not copied twice.

## Run at logon (optional)

Task Scheduler → trigger at logon → action:

`C:\ClaudeVision\.venv\Scripts\python.exe -u C:\ClaudeVision\src\live_enquiry_collector.py --watch`

Start in: `C:\ClaudeVision`

## Limits (provisional)

- Rows with **empty Drawing No.** are reported as skipped (e.g. large Boots line lists).
- Search is filename/path based — unusual storage layouts may need deeper paths or aliases.
- Excel file must be saved/closed periodically so mtime updates while watching.
- Does not run ClaudeVision estimating — only **collects** drawing packs.
