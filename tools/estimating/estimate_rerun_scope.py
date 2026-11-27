"""Freeze an explicit rerun scope and preserve previous issues. Never submits jobs.

prepare: select products from an existing reviewed plan, without rescanning drawings.
check: verify that plan and every original result remain byte-for-byte unchanged.
merge: accept reviewed replacement rows only for the selected products, to NEW JSON.

No customer references, prices, service calls or deployment actions live in this tool.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys


def drawing_key(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def long_path(path):
    value = str(path)
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + os.path.abspath(value)


def read_json(path):
    with open(long_path(path), encoding="utf-8-sig") as stream:
        return json.load(stream)


def digest(path):
    result = hashlib.sha256()
    with open(long_path(path), "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def write_new(path, data):
    # Exclusive creation: never overwrite a first issue or an existing result.
    with open(long_path(path), "x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")


def indexed(products, description):
    found = {}
    for product in products:
        key = drawing_key(product.get("drawing"))
        if not key or key in found:
            raise ValueError(f"Missing or duplicate drawing in {description}: {key}")
        found[key] = product
    if not found:
        raise ValueError(f"Empty product list: {description}")
    return found


def select_plan(plan, baseline, only):
    products = indexed(plan["products"], "reviewed plan")
    issued = indexed(baseline["products"], "first issue")
    selected = [drawing_key(x) for x in only]
    if not selected or any(not x for x in selected) or len(set(selected)) != len(selected):
        raise ValueError("Selection must be explicit, nonempty and unique")
    if set(products) != set(issued):
        raise ValueError("Plan and first issue do not contain exactly the same products")
    if not set(selected) <= set(products):
        raise ValueError("Selection contains a drawing outside the reviewed plan")
    if plan.get("files_expected") is None or plan.get("files_read") != plan["files_expected"]:
        raise ValueError("Reviewed plan has no complete file-accounting proof")
    result = copy.deepcopy(plan)
    for product in result["products"]:
        product["selected"] = drawing_key(product["drawing"]) in selected
    return result


def prepare(plan_path, baseline_path, sources_path, workbook_path, only, output_dir, journal_path):
    plan_path, baseline_path, sources_path, workbook_path = (
        Path(p).resolve() for p in (plan_path, baseline_path, sources_path, workbook_path)
    )
    baseline = read_json(baseline_path)
    plan = select_plan(read_json(plan_path), baseline, only)
    sources = indexed(read_json(sources_path)["sources"], "source inventory")
    issued = indexed(baseline["products"], "first issue")
    if set(sources) != set(issued):
        raise ValueError("Source inventory does not cover every first-issued product")
    if digest(workbook_path) != baseline["workbook_sha256"]:
        raise ValueError("First-issued consolidated workbook has changed")
    files = []
    for key, source in sources.items():
        for field, checksum in (("workbook", "book_sha256"), ("record", "record_sha256")):
            path = Path(source[field]).resolve()
            if digest(path) != source[checksum]:
                raise ValueError(f"Original result changed: {path}")
            files.append({"drawing": key, "kind": field, "path": str(path), "sha256": source[checksum]})
    for path in (plan_path, baseline_path, sources_path, workbook_path):
        files.append({"kind": "first_issue_input", "path": str(path), "sha256": digest(path)})
    output_dir = Path(output_dir).resolve()
    # Existing directories are refused, not silently recycled or cleaned.
    output_dir.mkdir(parents=True, exist_ok=False)
    scope_path = output_dir / "preservation-scope.json"
    selected_path = output_dir / "reviewed-rerun-plan.json"
    plan["preservation_scope"] = str(scope_path)
    write_new(selected_path, plan)
    selected = [drawing_key(p["drawing"]) for p in plan["products"] if p["selected"]]
    scope = {"schema": 1, "plan": str(selected_path), "plan_sha256": digest(selected_path),
             "baseline": str(baseline_path), "source_plan": str(plan_path),
             "selected": selected, "protected": sorted(set(issued) - set(selected)),
             "original_files": files,
             "historical_submission_journal": str(Path(journal_path).resolve()),
             "prepared_without_submission": True}
    write_new(scope_path, scope)
    return scope_path


def check(scope_path, plan_path=None):
    scope_path = Path(scope_path).resolve()
    scope = read_json(scope_path)
    actual_plan = Path(plan_path or scope["plan"]).resolve()
    if actual_plan != Path(scope["plan"]).resolve() or digest(actual_plan) != scope["plan_sha256"]:
        raise ValueError("Rerun plan changed or a different plan was supplied")
    plan = read_json(actual_plan)
    if Path(plan.get("preservation_scope", "")).resolve() != scope_path:
        raise ValueError("Rerun plan is not bound to this preservation scope")
    selected = [drawing_key(p["drawing"]) for p in plan["products"] if p.get("selected")]
    if set(selected) != set(scope["selected"]) or len(selected) != len(scope["selected"]):
        raise ValueError("Selected drawings differ from the frozen scope")
    original = indexed(read_json(scope["baseline"])["products"], "first issue")
    planned = indexed(plan["products"], "rerun plan")
    if set(planned) != set(original) or set(scope["protected"]) != set(original) - set(selected):
        raise ValueError("Protected products differ from the frozen first issue")
    failures = []
    for item in scope["original_files"]:
        try:
            unchanged = digest(item["path"]) == item["sha256"]
        except OSError:
            unchanged = False
        if not unchanged:
            failures.append(item["path"])
    if failures:
        raise ValueError("Original files changed or became unreadable: " + "; ".join(failures))
    return scope


def merge_reviewed(scope_path, replacements, issue):
    scope = check(scope_path)
    previous = read_json(scope["baseline"])
    revised = indexed(replacements, "reviewed replacement results")
    if set(revised) != set(scope["selected"]):
        raise ValueError("Reviewed replacements must cover exactly the selected products, no others")
    result = copy.deepcopy(previous)
    result["issue"] = issue
    changes = []
    for position, old in enumerate(previous["products"]):
        key = drawing_key(old["drawing"])
        if key not in revised:
            continue
        new = revised[key]
        cost = new.get("unit_cost")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
            raise ValueError(f"Invalid reviewed unit cost for {key}")
        for field in ("drawing", "title", "material", "manufacturing", "loading", "status", "basis"):
            if field not in new:
                raise ValueError(f"Reviewed result missing {field}: {key}")
        amounts = [new[field] for field in ("material", "manufacturing", "loading")]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in amounts):
            raise ValueError(f"Invalid reviewed cost breakdown for {key}")
        if abs(sum(amounts) - cost) > .03:
            raise ValueError(f"Reviewed cost breakdown does not reconcile for {key}")
        if not str(new.get("basis") or "").strip():
            raise ValueError(f"Reviewed result needs a scope/allowance basis: {key}")
        row = copy.deepcopy(new)
        row["drawing"] = old["drawing"]
        result["products"][position] = row
        changes.append({"drawing": old["drawing"], "previous_unit_cost": old["unit_cost"],
                        "revised_unit_cost": cost, "basis": row["basis"]})
    # Pure carried-forward rows, not a new latest-result lookup for unaffected products.
    for old, new in zip(previous["products"], result["products"]):
        if drawing_key(old["drawing"]) in scope["protected"] and old != new:
            raise ValueError("An unselected product was changed")
    # The first-issued workbook hash is not the hash of a not-yet-authored new workbook.
    result["previous_workbook_sha256"] = result.pop("workbook_sha256", None)
    result["changes"] = changes
    result["protected_products_unchanged"] = len(scope["protected"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    make = sub.add_parser("prepare")
    for name in ("plan", "baseline", "sources", "workbook", "only", "output-dir", "journal"):
        make.add_argument("--" + name, required=True)
    verify = sub.add_parser("check")
    verify.add_argument("--scope", required=True)
    verify.add_argument("--plan")
    merge = sub.add_parser("merge")
    for name in ("scope", "results", "issue", "output"):
        merge.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "prepare":
            path = prepare(args.plan, args.baseline, args.sources, args.workbook,
                           args.only.split(","), args.output_dir, args.journal)
            scope = check(path)
            print(f"PREPARED ONLY: {len(scope['selected'])} selected, {len(scope['protected'])} protected. {path}")
        elif args.mode == "check":
            scope = check(args.scope, args.plan)
            print(f"PRESERVED: {len(scope['original_files'])} original files; {len(scope['protected'])} unselected products unchanged.")
        else:
            result = merge_reviewed(args.scope, read_json(args.results)["products"], args.issue)
            write_new(args.output, result)
            print(f"NEW REVIEW DATA ONLY: {len(result['changes'])} replacements; {result['protected_products_unchanged']} carried forward unchanged.")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"NOT PROCESSED: {exc}\n")


if __name__ == "__main__":
    main()
