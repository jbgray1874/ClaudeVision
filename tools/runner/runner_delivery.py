"""Local-first storage only. Never launches an engine or submits an estimating job.

Run identities and SHA-256 inventories survive a crash. Publishing is repeatable,
never overwrites different bytes, and does not make an unpriced workbook a price.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO


class Conflict(ValueError):
    pass


def enabled():
    return os.getenv("SDI_ESTIMATE_LOCAL_FIRST", "").strip().lower() in {"1", "true", "yes", "on"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name+".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def save(path, value):
    atomic(path, (json.dumps(value, sort_keys=True, ensure_ascii=True)+"\n").encode())


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def safe_name(name):
    if not name or name in {".", ".."} or any(c in str(name) for c in "/\\:\0"):
        raise ValueError("unsafe deliverable name")
    return str(name)


def local_root(engine_root, runner_id):
    root = Path(engine_root) / "output" / "runner_delivery" / digest(str(runner_id).encode())[:20]
    if str(root).startswith(("\\\\", "//")):
        raise ValueError("local-first storage must be on a local disk, not UNC")
    return root


def validate_template(raw):
    """Validate original template structure, not its commercial correctness.

    Never cache a rendered price sheet or a truncated/non-OOXML download. Templates
    requiring external workbook links must be made self-contained by estimating.
    """
    ns = {"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    relns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    try:
        if len(raw)>64*1024*1024: raise ValueError("template exceeds 64 MiB")
        with zipfile.ZipFile(BytesIO(raw)) as z:
            if sum(i.file_size for i in z.infolist()) > 128*1024*1024:
                raise ValueError("template expands beyond 128 MiB")
            if z.testzip(): raise ValueError("template CRC failed")
            if any(n.startswith("xl/externalLinks/") for n in z.namelist()):
                raise ValueError("template has external workbook links; make it self-contained before caching")
            book = ET.fromstring(z.read("xl/workbook.xml"))
            sheets = {s.attrib["name"]:s.attrib.get("{"+relns+"}id") for s in book.findall("s:sheets/s:sheet",ns)}
            required = {"Estimate", "Labour", "Material Price Break"}
            if not required.issubset(sheets): raise ValueError("template lacks Estimate / Labour / Material Price Break")
            relationships = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            targets = {r.attrib["Id"]:r.attrib["Target"] for r in relationships}
            for relationship in sheets.values():
                link=targets[relationship].replace('\\','/')
                if '..' in PurePosixPath(link).parts: raise ValueError('unsafe worksheet relationship')
                location=link.lstrip('/') if link.startswith('/') else 'xl/'+link
                ET.fromstring(z.read(location))
            target = targets[sheets["Estimate"]].replace("\\", "/")
            if ".." in PurePosixPath(target).parts: raise ValueError("unsafe workbook relationship")
            member = target.lstrip("/") if target.startswith("/") else "xl/"+target
            sheet = ET.fromstring(z.read(member))
            cells = {c.attrib["r"] for c in sheet.findall(".//s:c",ns)}
            formulas = [f.text or "" for f in sheet.findall(".//s:f",ns)]
            if not {"D3", "D5", "D6"}.issubset(cells): raise ValueError("template header cells missing")
            if not any(re.search(r"\$?D\$?6\b",f,re.I) for f in formulas):
                raise ValueError("template lacks order-quantity-driven formulas")
            return {"sheets":sorted(sheets),"formula_count":len(formulas),"external_workbook_links":False}
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("invalid estimating template OOXML") from exc


def template_copy(source, cache, max_age_hours=24, clock=time.time):
    cache = Path(cache); receipt = cache / (digest(str(source).casefold().encode())+".json")
    if max_age_hours <= 0: raise ValueError("template cache maximum age must be positive")
    try:
        raw = Path(source).read_bytes()
    except PermissionError:
        raise
    except OSError:
        if not receipt.is_file(): raise OSError("template unavailable and no previously validated local copy")
        record = load(receipt)
        age = clock()-float(record["verified_at"])
        if age < -300 or age > max_age_hours*3600: raise ValueError("validated template cache expired; reconnect to refresh")
        if record["source"] != str(source): raise Conflict("template receipt belongs to another source")
        local = cache / safe_name(record["file"])
        raw = local.read_bytes()
        if digest(raw) != record["sha256"]: raise Conflict("local template hash changed")
        validate_template(raw)
        return local, dict(record, offline_cache=True)
    # Readable but invalid source is NOT disguised as a VPN outage or replaced by an old copy.
    structural = validate_template(raw)
    hash_ = digest(raw)
    suffix = Path(source).suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}: raise ValueError("template must be xlsx or xlsm")
    local = cache / (hash_+suffix)
    if local.exists():
        if local.read_bytes() != raw: raise Conflict("content-addressed template copy changed")
    else:
        atomic(local,raw)
    if digest(local.read_bytes()) != hash_: raise OSError("local template copy verification failed")
    record = dict(schema="sdi_template_cache.v1",source=str(source),file=local.name,
                  sha256=hash_,bytes=len(raw),verified_at=clock(),structure=structural)
    save(receipt,record)
    return local, dict(record,offline_cache=False)


def pin_inputs(folder, pdf, destination):
    """Copy the already-staged job, not CAD libraries or external model references."""
    folder, destination = Path(folder), Path(destination)
    if not folder.is_dir(): raise OSError("staged job is not readable")
    if folder.absolute()==destination.absolute() or folder.absolute() in destination.absolute().parents:
        raise ValueError("local input destination cannot be inside its source")
    inventory = []
    total = 0
    for source in sorted(folder.rglob("*")):
        if source.is_symlink(): raise ValueError("staged input contains a symbolic link")
        if not source.is_file(): continue
        relative = source.relative_to(folder)
        raw = source.read_bytes(); total += len(raw)
        if total > 2*1024**3 or len(inventory) >= 10000:
            raise ValueError("staged job exceeds local-copy safety limit")
        target = destination/relative
        if target.exists() and target.read_bytes() != raw: raise Conflict("local staged input changed")
        atomic(target,raw)
        if digest(target.read_bytes()) != digest(raw): raise OSError("input copy failed verification")
        inventory.append({"name":relative.as_posix(),"sha256":digest(raw),"bytes":len(raw)})
    if not inventory: raise ValueError("no staged input files to pin locally")
    pinned_pdf = None
    if pdf is not None:
        try: relative = Path(pdf).relative_to(folder)
        except ValueError as exc: raise ValueError("selected PDF is outside its staged job") from exc
        pinned_pdf = destination/relative
        if not pinned_pdf.is_file(): raise OSError("selected PDF was not copied")
    return destination,pinned_pdf,inventory


def stage(root, job, runner_id, base, files, log, started_at, template):
    run_id = str(job["run_id"])
    if not re.fullmatch(r"[a-fA-F0-9]{8,64}",run_id): raise ValueError("invalid service run id")
    url = urllib.parse.urlsplit(base)
    if url.scheme not in {"http","https"} or not url.netloc or url.username or url.query or url.fragment:
        raise ValueError("invalid service destination")
    root = Path(root); folder=root/run_id
    if folder.is_symlink(): raise ValueError("unsafe local delivery folder")
    inventory=[]
    for item in files:
        name=safe_name(item["name"]); source=Path(item["path"])
        if source.name != name: raise Conflict("file name differs from collected path")
        raw=source.read_bytes(); target=folder/"files"/name
        if target.exists() and target.read_bytes()!=raw: raise Conflict("saved local run file differs")
        if source != target: atomic(target,raw)
        inventory.append({"name":name,"sha256":digest(raw),"bytes":len(raw)})
    if len({f['name'] for f in inventory}) != len(inventory): raise Conflict("duplicate deliverable name")
    keep={k:job.get(k) for k in ("run_id","drawing_number","client","units","output_path","archive_root",
                                "archive_stamp","parity_root","manual_workbook","compare_with_manual")}
    state=dict(schema="sdi_local_delivery.v1",run_id=run_id,runner_id=runner_id,base=base,
               job=keep,started_at=started_at,template=template,inventory=inventory,
               log=list(log),phase="pending",created_at=time.time())
    manifest=folder/"delivery.json"
    if manifest.exists():
        existing=load(manifest)
        for key in ("run_id","runner_id","base","job","started_at","inventory"):
            if existing[key]!=state[key]: raise Conflict("existing delivery identity/content differs")
        return manifest
    save(manifest,state)
    verify_local(manifest,state)
    return manifest


def verify_local(manifest,state):
    folder=Path(manifest).parent
    if state.get("schema")!="sdi_local_delivery.v1" or folder.name!=state["run_id"]:
        raise Conflict("local delivery identity invalid")
    files=[]
    seen=set()
    for item in state["inventory"]:
        name=safe_name(item["name"])
        if name in seen: raise Conflict("duplicate local file")
        seen.add(name)
        path=folder/"files"/name
        if path.is_symlink(): raise Conflict("local delivery file is a symbolic link")
        raw=path.read_bytes()
        if len(raw)!=item["bytes"] or digest(raw)!=item["sha256"]: raise Conflict("local run file hash mismatch")
        files.append({"name":name,"path":str(path)})
    return files


def publish(manifest,state,destination=None):
    """Repeat the copies, not the estimate. Different existing bytes are a hard conflict."""
    local=verify_local(manifest,state)
    dest=Path(destination or state["job"]["output_path"])
    if not dest.is_absolute() or ".." in dest.parts or dest.is_symlink(): raise ValueError("unsafe filing destination")
    dest.mkdir(parents=True,exist_ok=True)
    out=[]
    for source in local:
        raw=Path(source["path"]).read_bytes(); target=dest/source["name"]
        if target.is_symlink(): raise Conflict("filing target is a symbolic link")
        if target.exists():
            if target.read_bytes()!=raw: raise Conflict("filing would overwrite different existing bytes")
        else:
            # Exclusive installation: a competing writer cannot be silently overwritten.
            fd,temp=tempfile.mkstemp(prefix=target.name+".",suffix=".pending",dir=dest)
            try:
                with os.fdopen(fd,"wb") as f: f.write(raw);f.flush();os.fsync(f.fileno())
                try:
                    if os.name=='nt': os.rename(temp,target)  # Windows rename refuses an existing target
                    else: os.link(temp,target)              # same no-clobber guarantee on POSIX
                except FileExistsError:
                    if target.read_bytes()!=raw: raise Conflict("competing filing conflict")
            finally:
                if os.path.exists(temp): os.unlink(temp)
        if digest(target.read_bytes())!=digest(raw): raise OSError("shared copy verification failed")
        out.append({"name":source["name"],"path":str(target)})
    return out


def pending(root):
    return sorted(p for p in Path(root).glob("*/delivery.json") if load(p).get("phase")=="pending")


def acquire(manifest):
    """No stale-lock deletion: an operator must prove its owner ended first."""
    path=Path(manifest).with_suffix('.filing.lock'); token=uuid.uuid4().hex
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        json.dump({'pid':os.getpid(),'token':token,'started':time.time()},f);f.flush();os.fsync(f.fileno())
    return path,token


def release(claim):
    path,token=claim
    if load(path).get('token')==token: path.unlink()
