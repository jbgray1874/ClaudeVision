#!/usr/bin/env python3
"""
Live Enquiry drawing collector (provisional standalone agent).

Watches the manual Live Enquiry workbook. When new rows appear, searches
W:\\Production\\<Customer> for PDF/DXF files matching Drawing No., copies them
into K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\<folder>, and
emails a found / missing report.

Run continuously:
  python -u src\\live_enquiry_collector.py --watch

Process all unprocessed rows once (no loop):
  python -u src\\live_enquiry_collector.py --once

Dry-run (no copy, no email):
  python -u src\\live_enquiry_collector.py --once --dry-run

Configure via environment variables — see config/live_enquiry_collector.example.env
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import smtplib
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore

LOG = logging.getLogger("live_enquiry_collector")

DRAWING_EXTENSIONS = {".pdf", ".dxf"}
DEFAULT_CUSTOMER_ALIASES = {
    "TTI": "TTi",
    "TTI MILWAUKEE": "TTi",
    "M&S": "M&S",
    "MS": "M&S",
    "BOOTS": "Boots",
    "TESCO": "Tesco",
    "TIKTOK": "TikTok",
    "RYOBI": "Ryobi",
    "MILWAUKEE": "TTi",
}


@dataclass
class Settings:
    workbook: Path
    sheet_name: str
    production_root: Path
    dest_root: Path
    state_file: Path
    poll_seconds: int
    search_max_depth: int
    copy_dxf_subfolder: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    email_to: List[str]
    max_age_days: int
    customer_aliases: Dict[str, str]
    dry_run: bool = False


@dataclass
class EnquiryRow:
    row_index: int
    enquiry_received: Optional[str]
    account_manager: Optional[str]
    customer: str
    job_description: str
    drawing_no_raw: str
    requested_completion: Optional[str]
    drawing_tokens: List[str] = field(default_factory=list)

    @property
    def row_key(self) -> str:
        return "|".join(
            [
                str(self.row_index),
                self.customer.strip().upper(),
                self.drawing_no_raw.strip().upper(),
                (self.job_description or "").strip().upper()[:80],
            ]
        )


@dataclass
class FoundFile:
    drawing_token: str
    path: Path
    ext: str


@dataclass
class RowResult:
    row: EnquiryRow
    customer_folder: Optional[Path]
    dest_folder: Optional[Path]
    found: List[FoundFile] = field(default_factory=list)
    copied: List[str] = field(default_factory=list)
    missing_tokens: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    skipped_reason: Optional[str] = None


def _env_path(key: str, default: str) -> Path:
    return Path(os.getenv(key, default)).expanduser()


def load_settings(dry_run: bool = False) -> Settings:
    if load_dotenv is not None:
        root = Path(__file__).resolve().parents[1]
        load_dotenv(root / ".env")

    email_to = [
        item.strip()
        for item in (os.getenv("LIVE_ENQUIRY_EMAIL_TO") or "").split(",")
        if item.strip()
    ]

    aliases = dict(DEFAULT_CUSTOMER_ALIASES)
    extra = os.getenv("LIVE_ENQUIRY_CUSTOMER_ALIASES_JSON")
    if extra:
        try:
            aliases.update({k.upper(): v for k, v in json.loads(extra).items()})
        except json.JSONDecodeError as exc:
            LOG.warning("Invalid LIVE_ENQUIRY_CUSTOMER_ALIASES_JSON: %s", exc)

    return Settings(
        workbook=_env_path(
            "LIVE_ENQUIRY_WORKBOOK",
            r"K:\Estimating\Completed\Manual Estimates\Live Enquiry.xls",
        ),
        sheet_name=os.getenv("LIVE_ENQUIRY_SHEET", "Live Enquiries"),
        production_root=_env_path("PRODUCTION_ROOT", r"W:\Production"),
        dest_root=_env_path(
            "AI_ENQUIRY_DEST",
            r"K:\Estimating\Completed\AI Estimating\Live Enquiry",
        ),
        state_file=_env_path(
            "STATE_FILE",
            r"C:\ClaudeVision\output\live_enquiry_collector_state.json",
        ),
        poll_seconds=int(os.getenv("LIVE_ENQUIRY_POLL_SECONDS", "60")),
        search_max_depth=int(os.getenv("DRAWING_SEARCH_MAX_DEPTH", "12")),
        copy_dxf_subfolder=os.getenv("COPY_DXF_TO_SUBFOLDER", "0").lower()
        in {"1", "true", "yes"},
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "")),
        email_to=email_to,
        max_age_days=int(os.getenv("LIVE_ENQUIRY_MAX_AGE_DAYS", "14")),
        customer_aliases=aliases,
        dry_run=dry_run,
    )


def load_state(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"processed_row_keys": [], "last_workbook_mtime": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"processed_row_keys": [], "last_workbook_mtime": None}


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def workbook_mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _normalize_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _find_columns(header_row: Sequence[Any]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        key = _normalize_header(cell)
        if not key:
            continue
        if "customer" in key:
            mapping["customer"] = idx
        elif "drawing" in key and "no" in key:
            mapping["drawing_no"] = idx
        elif "job" in key and "desc" in key:
            mapping["job_description"] = idx
        elif "enquiry" in key and "received" in key:
            mapping["enquiry_received"] = idx
        elif "account" in key and "manager" in key:
            mapping["account_manager"] = idx
        elif "completion" in key or ("estimate" in key and "date" in key):
            mapping["requested_completion"] = idx
    return mapping


def _parse_excel_date(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%d %B %Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def read_enquiry_rows(settings: Settings) -> List[EnquiryRow]:
    path = settings.workbook
    if not path.is_file():
        raise FileNotFoundError(f"Workbook not found: {path}")

    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pandas is required: pip install pandas openpyxl xlrd") from exc

    suffix = path.suffix.lower()
    engine = None
    if suffix == ".xls":
        engine = "xlrd"

    df = pd.read_excel(path, sheet_name=settings.sheet_name, header=None, engine=engine)
    if df.empty:
        return []

    header_idx = None
    columns: Dict[str, int] = {}
    for i in range(min(10, len(df))):
        row = [df.iloc[i, j] for j in range(df.shape[1])]
        columns = _find_columns(row)
        if "customer" in columns and "drawing_no" in columns:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError(
            f"Could not find header row with Customer + Drawing No. on sheet {settings.sheet_name!r}"
        )

    rows: List[EnquiryRow] = []
    cutoff = None
    if settings.max_age_days > 0:
        cutoff = datetime.now() - timedelta(days=settings.max_age_days)

    for i in range(header_idx + 1, len(df)):
        def cell(col: str) -> Any:
            if col not in columns:
                return None
            return df.iloc[i, columns[col]]

        customer = str(cell("customer") or "").strip()
        drawing_raw = str(cell("drawing_no") or "").strip()
        job_desc = str(cell("job_description") or "").strip()
        if not customer and not drawing_raw and not job_desc:
            continue
        if not customer:
            continue

        received_dt = _parse_excel_date(cell("enquiry_received"))
        if cutoff and received_dt and received_dt < cutoff:
            continue

        tokens = parse_drawing_tokens(drawing_raw)
        rows.append(
            EnquiryRow(
                row_index=i + 1,
                enquiry_received=str(cell("enquiry_received") or "").strip() or None,
                account_manager=str(cell("account_manager") or "").strip() or None,
                customer=customer,
                job_description=job_desc,
                drawing_no_raw=drawing_raw,
                requested_completion=str(cell("requested_completion") or "").strip() or None,
                drawing_tokens=tokens,
            )
        )
    return rows


def parse_drawing_tokens(raw: str) -> List[str]:
    if not raw or not str(raw).strip():
        return []
    text = str(raw).upper().replace("&", "+")
    parts = re.split(r"\s*\+\s*|,|;", text)
    tokens: List[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Keep GA/detail style tokens and bare job numbers (e.g. 1282, 12473)
        for match in re.finditer(
            r"\b\d{4,5}(?:-[0-9]{2}(?:-[0-9A-Z]{1,4})?|-[A-Z]{2,4})?\b|\b\d{6,7}\b",
            part,
            flags=re.IGNORECASE,
        ):
            token = match.group(0).upper()
            if token not in tokens:
                tokens.append(token)
        if not re.search(r"\d", part):
            continue
        if part not in tokens and len(part) >= 4:
            tokens.append(part)
    return tokens


def resolve_customer_folder(production_root: Path, customer: str, aliases: Dict[str, str]) -> Optional[Path]:
    if not production_root.is_dir():
        return None
    key = customer.strip().upper()
    candidates = [customer.strip(), aliases.get(key, customer.strip())]
    # Also try without punctuation
    candidates.append(re.sub(r"[^A-Za-z0-9&]+", "", customer))
    seen: Set[str] = set()
    for name in candidates:
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        direct = production_root / name
        if direct.is_dir():
            return direct

    # Case-insensitive match against existing folders
    target = re.sub(r"\s+", "", key)
    for child in production_root.iterdir():
        if not child.is_dir():
            continue
        norm = re.sub(r"\s+", "", child.name.upper())
        if norm == target or target in norm or norm in target:
            return child
    return None


def _token_matches_name(token: str, name: str) -> bool:
    token_u = token.upper()
    name_u = name.upper()
    if token_u in name_u:
        return True
    # 12464-01-GA also matches filenames containing 12464
    lead = re.match(r"^(\d{4,5})", token_u)
    if lead and lead.group(1) in name_u:
        # Require word boundary style: avoid 128 matching 1282
        if re.search(rf"\b{re.escape(lead.group(1))}\b", name_u):
            return True
        if name_u.startswith(lead.group(1) + "-") or name_u.startswith(lead.group(1) + " "):
            return True
    return False


def search_drawings(
    customer_folder: Path,
    tokens: Sequence[str],
    max_depth: int,
) -> Tuple[List[FoundFile], List[str]]:
    found: List[FoundFile] = []
    missing: List[str] = []
    if not tokens:
        return found, ["(no drawing number in spreadsheet row)"]

    hits_by_token: Dict[str, List[Path]] = {t: [] for t in tokens}
    root_depth = len(customer_folder.parts)

    for dirpath, dirnames, filenames in os.walk(customer_folder):
        depth = len(Path(dirpath).parts) - root_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        # Skip obvious archive / backup trees
        dirnames[:] = [
            d
            for d in dirnames
            if d.lower() not in {"archive", "archived", "old", "backup", "superseded"}
        ]
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext not in DRAWING_EXTENSIONS:
                continue
            for token in tokens:
                if _token_matches_name(token, fname) or _token_matches_name(token, dirpath):
                    hits_by_token[token].append(Path(dirpath) / fname)

    for token, paths in hits_by_token.items():
        if not paths:
            missing.append(token)
            continue
        # Prefer shortest path (often job root) then newest mtime
        paths = sorted(
            paths,
            key=lambda p: (len(str(p)), -p.stat().st_mtime if p.exists() else 0),
        )
        seen_names: Set[str] = set()
        for path in paths:
            name_key = path.name.lower()
            if name_key in seen_names:
                continue
            seen_names.add(name_key)
            found.append(FoundFile(drawing_token=token, path=path, ext=path.suffix.lower()))

    return found, missing


def sanitize_folder_name(primary_token: str, job_description: str) -> str:
    desc = (job_description or "Live Enquiry").strip()
    desc = re.sub(r'[<>:"/\\|?*]+', " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip()
    token = (primary_token or "UNKNOWN").strip()
    name = f"{token} - {desc}" if desc else token
    return name[:120].strip(" .")


def ensure_unique_dest(dest_root: Path, folder_name: str) -> Path:
    candidate = dest_root / folder_name
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        alt = dest_root / f"{folder_name} ({n})"
        if not alt.exists():
            return alt
        n += 1


def copy_pack(
    found: Sequence[FoundFile],
    dest_folder: Path,
    copy_dxf_subfolder: bool,
    dry_run: bool,
) -> List[str]:
    copied: List[str] = []
    dest_folder.mkdir(parents=True, exist_ok=True)
    dxf_dir = dest_folder / "DXF"
    if copy_dxf_subfolder:
        dxf_dir.mkdir(parents=True, exist_ok=True)

    for item in found:
        target_dir = dxf_dir if copy_dxf_subfolder and item.ext == ".dxf" else dest_folder
        target = target_dir / item.path.name
        if target.exists():
            stem, suffix = item.path.stem, item.path.suffix
            target = target_dir / f"{stem}_{int(time.time())}{suffix}"
        if dry_run:
            copied.append(f"[dry-run] {item.path} -> {target}")
            continue
        shutil.copy2(item.path, target)
        copied.append(str(target))
    return copied


def build_folder_name(row: EnquiryRow) -> str:
    primary = row.drawing_tokens[0] if row.drawing_tokens else row.drawing_no_raw.split("+")[0].strip()
    if not primary:
        primary = "NO-DRAWING-NO"
    return sanitize_folder_name(primary, row.job_description)


def process_row(settings: Settings, row: EnquiryRow) -> RowResult:
    result = RowResult(row=row)
    if not row.drawing_tokens and not row.drawing_no_raw.strip():
        result.skipped_reason = "No drawing number — manual pack required"
        result.missing_tokens = ["(drawing number empty)"]
        return result

    customer_folder = resolve_customer_folder(
        settings.production_root, row.customer, settings.customer_aliases
    )
    result.customer_folder = customer_folder
    if not customer_folder:
        result.errors.append(f"No production folder for customer {row.customer!r} under {settings.production_root}")
        result.missing_tokens = list(row.drawing_tokens) or ["(customer folder missing)"]
        return result

    tokens = row.drawing_tokens or parse_drawing_tokens(row.drawing_no_raw)
    found, missing = search_drawings(customer_folder, tokens, settings.search_max_depth)
    result.found = found
    result.missing_tokens = missing

    if not found:
        result.skipped_reason = "No PDF/DXF files found"
        return result

    folder_name = build_folder_name(row)
    dest = ensure_unique_dest(settings.dest_root, folder_name)
    result.dest_folder = dest
    if not settings.dry_run:
        settings.dest_root.mkdir(parents=True, exist_ok=True)
    try:
        result.copied = copy_pack(
            found,
            dest,
            settings.copy_dxf_subfolder,
            settings.dry_run,
        )
    except OSError as exc:
        result.errors.append(f"Copy failed: {exc}")

    return result


def _result_to_dict(res: RowResult) -> Dict[str, Any]:
    return {
        "row_index": res.row.row_index,
        "customer": res.row.customer,
        "drawing_no": res.row.drawing_no_raw,
        "job_description": res.row.job_description,
        "drawing_tokens": res.row.drawing_tokens,
        "customer_folder": str(res.customer_folder) if res.customer_folder else None,
        "dest_folder": str(res.dest_folder) if res.dest_folder else None,
        "found": [
            {"token": f.drawing_token, "path": str(f.path), "ext": f.ext} for f in res.found
        ],
        "copied": res.copied,
        "missing_tokens": res.missing_tokens,
        "errors": res.errors,
        "skipped_reason": res.skipped_reason,
    }


def format_results_html(results: Sequence[RowResult], workbook: Path) -> str:
    rows_html = []
    for res in results:
        if res.skipped_reason and not res.found:
            status = f"SKIPPED — {res.skipped_reason}"
        elif res.missing_tokens and res.found:
            status = "PARTIAL"
        elif res.missing_tokens:
            status = "MISSING FILES"
        else:
            status = "OK"
        found_lines = "<br>".join(
            f"{f.drawing_token}: {f.path.name} ({f.ext})" for f in res.found[:30]
        ) or "—"
        if len(res.found) > 30:
            found_lines += f"<br>… +{len(res.found) - 30} more"
        missing_lines = ", ".join(res.missing_tokens) or "—"
        dest = str(res.dest_folder) if res.dest_folder else "—"
        rows_html.append(
            f"<tr>"
            f"<td>{res.row.row_index}</td>"
            f"<td>{res.row.customer}</td>"
            f"<td>{res.row.drawing_no_raw or '—'}</td>"
            f"<td>{res.row.job_description or '—'}</td>"
            f"<td>{status}</td>"
            f"<td>{dest}</td>"
            f"<td>{found_lines}</td>"
            f"<td>{missing_lines}</td>"
            f"</tr>"
        )
    body = f"""
    <html><body>
    <h2>Live Enquiry drawing pack report</h2>
    <p>Workbook: <code>{workbook}</code><br>
    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:13px;">
    <tr style="background:#eee;">
      <th>Row</th><th>Customer</th><th>Drawing No.</th><th>Job description</th>
      <th>Status</th><th>Destination folder</th><th>Files found</th><th>Missing tokens</th>
    </tr>
    {''.join(rows_html)}
    </table>
    <p style="color:#666;font-size:12px;">Provisional collector — verify packs before auto-estimate.</p>
    </body></html>
    """
    return body


def send_email(settings: Settings, subject: str, html_body: str) -> None:
    if not settings.email_to:
        LOG.warning("LIVE_ENQUIRY_EMAIL_TO not set — skipping email")
        return
    if not settings.smtp_host or not settings.smtp_user:
        LOG.warning("SMTP not configured — skipping email")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(settings.email_to)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if settings.dry_run:
        LOG.info("Dry-run: email not sent (%s)", subject)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=60) as server:
        server.starttls()
        if settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(msg["From"], settings.email_to, msg.as_string())
    LOG.info("Email sent to %s", settings.email_to)


def process_new_rows(settings: Settings, state: Dict[str, Any]) -> List[RowResult]:
    processed: Set[str] = set(state.get("processed_row_keys") or [])
    all_rows = read_enquiry_rows(settings)
    new_rows = [r for r in all_rows if r.row_key not in processed]
    if not new_rows:
        LOG.debug("No new rows to process")
        return []

    results: List[RowResult] = []
    for row in new_rows:
        LOG.info(
            "Processing row %s: %s / %s — %s",
            row.row_index,
            row.customer,
            row.drawing_no_raw,
            row.job_description,
        )
        results.append(process_row(settings, row))
        processed.add(row.row_key)

    state["processed_row_keys"] = sorted(processed)
    state["last_run"] = datetime.now().isoformat()
    if not settings.dry_run:
        save_state(settings.state_file, state)

    if results:
        subject = f"Live Enquiry packs — {len(results)} new row(s)"
        send_email(settings, subject, format_results_html(results, settings.workbook))
        manifest = settings.state_file.parent / f"live_enquiry_report_{datetime.now():%Y%m%d_%H%M%S}.json"
        manifest.write_text(
            json.dumps([_result_to_dict(r) for r in results], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return results


def run_once(settings: Settings) -> None:
    state = load_state(settings.state_file)
    mtime = workbook_mtime(settings.workbook)
    state["last_workbook_mtime"] = mtime
    results = process_new_rows(settings, state)
    LOG.info("Done — processed %s row(s)", len(results))


def run_watch(settings: Settings) -> None:
    LOG.info("Watching %s (poll every %ss)", settings.workbook, settings.poll_seconds)
    state = load_state(settings.state_file)
    last_mtime = state.get("last_workbook_mtime")

    while True:
        try:
            mtime = workbook_mtime(settings.workbook)
            if mtime is None:
                LOG.warning("Workbook not reachable: %s", settings.workbook)
            elif last_mtime is None or mtime > float(last_mtime):
                LOG.info("Workbook change detected — scanning for new rows")
                results = process_new_rows(settings, state)
                last_mtime = mtime
                state["last_workbook_mtime"] = mtime
                if not settings.dry_run:
                    save_state(settings.state_file, state)
                LOG.info("Cycle complete — %s new row(s)", len(results))
        except Exception:
            LOG.exception("Watcher cycle failed")
        time.sleep(max(5, settings.poll_seconds))


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Enquiry PDF/DXF collector")
    parser.add_argument("--watch", action="store_true", help="Poll workbook continuously")
    parser.add_argument("--once", action="store_true", help="Process unprocessed rows once")
    parser.add_argument("--dry-run", action="store_true", help="Search only; no copy/email")
    parser.add_argument("--reset-state", action="store_true", help="Clear processed-row state")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    settings = load_settings(dry_run=args.dry_run)
    if args.reset_state:
        save_state(settings.state_file, {"processed_row_keys": [], "last_workbook_mtime": None})
        LOG.info("State reset: %s", settings.state_file)

    if args.watch:
        run_watch(settings)
    else:
        run_once(settings)


if __name__ == "__main__":
    main()
