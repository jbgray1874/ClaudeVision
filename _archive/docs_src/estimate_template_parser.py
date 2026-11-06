import json
import re
from pathlib import Path
from typing import Any, Dict, List

from extractor_patterns import normalize_text
from spreadsheet_formula_parser import extract_workbook_formulas


def _dedupe(values: List[Any]) -> List[Any]:
    seen: List[Any] = []
    for value in values:
        if value not in (None, "", []) and value not in seen:
            seen.append(value)
    return seen


def _sheet_lookup(workbook_data: Dict[str, Any], target_name: str) -> Dict[str, Any]:
    for sheet in workbook_data.get("sheets", []):
        if sheet.get("sheet_name", "").lower() == target_name.lower():
            return sheet
    return {}


def _classify_formula_entry(sheet_name: str, entry: Dict[str, Any]) -> List[str]:
    formula = str(entry.get("formula", ""))
    labels = " ".join(
        [
            str(entry.get("label_left", "")),
            str(entry.get("label_left_2", "")),
            str(entry.get("label_right", "")),
        ]
    ).upper()
    sheet_upper = sheet_name.upper()
    formula_upper = formula.upper()
    tags: List[str] = []

    if "LOOKUP(" in formula_upper:
        tags.append("lookup")
    if "SUM(" in formula_upper:
        tags.append("sum")
    if any(token in formula_upper for token in ["ROUNDUP(", "*7.85", "/1000", "MATERIAL PRICE BREAK"]):
        tags.append("material_cost_logic")
    if any(token in labels for token in ["UNIT COST", "MATERIAL", "POWDER", "PALLET", "DELIVERY"]):
        tags.append("material_or_bought_in")
    if any(token in labels for token in ["LASM", "FOLD", "LABOUR", "ROUTE", "RATE"]) or sheet_upper == "LABOUR":
        tags.append("labour_or_operation")
    if re.search(r"ESTIMATE!\$H\$\d+:\$H\$\d+", formula_upper, flags=re.IGNORECASE):
        tags.append("operation_table_lookup")
    if "MATERIAL PRICE BREAK" in formula_upper or sheet_upper == "MATERIAL PRICE BREAK":
        tags.append("material_break_table")
    if any(token in formula_upper for token in ["IF(", "LOOKUP(", "ROUNDUP("]) and any(
        token in formula_upper for token in ["H38", "J38", "K38", "L38", "Q38", "V38"]
    ):
        tags.append("sheet_nesting_or_runrate")
    if any(token in formula_upper for token in ["*H", "/I", "/60", "SETUP", "MIN"]):
        tags.append("time_or_rate_logic")

    return _dedupe(tags)


def _summarize_key_formulas(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    summary = {
        "material_formulas": [],
        "labour_formulas": [],
        "total_formulas": [],
        "lookup_formulas": [],
    }

    for entry in entries:
        tags = entry.get("tags", [])
        compact = {
            "sheet": entry["sheet"],
            "address": entry["address"],
            "value": entry["value"],
            "formula": entry["formula"],
            "labels": entry["labels"],
            "tags": tags,
        }
        if "material_cost_logic" in tags or "material_or_bought_in" in tags or "material_break_table" in tags:
            summary["material_formulas"].append(compact)
        if "labour_or_operation" in tags or "operation_table_lookup" in tags or "time_or_rate_logic" in tags:
            summary["labour_formulas"].append(compact)
        if "sum" in tags and any(token in compact["address"] for token in ["60", "59", "106", "101", "105"]):
            summary["total_formulas"].append(compact)
        if "lookup" in tags:
            summary["lookup_formulas"].append(compact)

    for key in summary:
        summary[key] = summary[key][:40]
    return summary


def _extract_key_cells(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    key_cells = {
        "quantity_drivers": [],
        "material_unit_prices": [],
        "operation_rows": [],
        "totals": [],
    }

    for entry in entries:
        address = str(entry.get("address", "")).upper()
        sheet = str(entry.get("sheet", "")).upper()
        tags = entry.get("tags", [])
        compact = {
            "sheet": entry["sheet"],
            "address": entry["address"],
            "value": entry["value"],
            "formula": entry["formula"],
            "labels": entry["labels"],
            "tags": tags,
            "is_plain_text": bool(entry.get("is_plain_text", False)),
        }

        if sheet != "ESTIMATE":
            continue

        # Quantity driver — D6
        if address == "D6":
            key_cells["quantity_drivers"].append(compact)

        # Material — cols C, J, L rows 11-58 (description, unit price, line total)
        if re.match(r"[CJL](1[1-9]|[2-5][0-9])$", address):
            row_num = int(re.search(r"\d+$", address).group())
            if 11 <= row_num <= 58:
                key_cells["material_unit_prices"].append(compact)

        # Operations — col C (name) + cols I,J,K,L,M (rate/hours/setup/cost) rows 63-102
        if re.match(r"[CIJKLM](6[3-9]|[7-9]\d|10[0-2])$", address):
            row_num = int(re.search(r"\d+$", address).group())
            if 63 <= row_num <= 102:
                key_cells["operation_rows"].append(compact)

        # Totals — col L and M key summary cells
        if address in {
            "L59", "L60", "L101", "L103", "L105", "L106",
            "M59", "M60", "M101", "M103", "M105", "M106",
            "F6", "G6",
        }:
            key_cells["totals"].append(compact)

    return key_cells


def parse_estimate_template(workbook_path: str | Path) -> Dict[str, Any]:
    workbook = Path(workbook_path).resolve()
    workbook_data = extract_workbook_formulas(workbook)

    parsed_entries: List[Dict[str, Any]] = []
    for sheet in workbook_data.get("sheets", []):
        sheet_name = sheet.get("sheet_name", "")
        for entry in sheet.get("formulas", []):
            labels = {
                "left": normalize_text(str(entry.get("label_left", ""))),
                "left_2": normalize_text(str(entry.get("label_left_2", ""))),
                "right": normalize_text(str(entry.get("label_right", ""))),
            }
            parsed_entries.append(
                {
                    "sheet": sheet_name,
                    "address": entry.get("address"),
                    "value": entry.get("value"),
                    "formula": entry.get("formula"),
                    "number_format": entry.get("number_format"),
                    "labels": labels,
                    "tags": _classify_formula_entry(sheet_name, entry),
                    "is_plain_text": bool(entry.get("is_plain_text", False)),
                }
            )

    return {
        "schema_version": "estimate_template_parse.v1",
        "workbook_path": str(workbook),
        "workbook_name": workbook_data.get("workbook_name", workbook.name),
        "sheet_names": [sheet.get("sheet_name") for sheet in workbook_data.get("sheets", [])],
        "sheet_overview": [
            {
                "sheet_name": sheet.get("sheet_name"),
                "rows": sheet.get("rows"),
                "cols": sheet.get("cols"),
                "formula_count": len(sheet.get("formulas", [])),
            }
            for sheet in workbook_data.get("sheets", [])
        ],
        "estimate_sheet": _sheet_lookup(workbook_data, "Estimate"),
        "labour_sheet": _sheet_lookup(workbook_data, "Labour"),
        "material_price_break_sheet": _sheet_lookup(workbook_data, "Material Price Break"),
        "parsed_entries": parsed_entries,
        "key_formula_summary": _summarize_key_formulas(parsed_entries),
        "key_cells": _extract_key_cells(parsed_entries),
    }


def write_estimate_template_parse(workbook_path: str | Path, output_path: str | Path) -> Path:
    parsed = parse_estimate_template(workbook_path)
    output = Path(output_path).resolve()
    output.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
    return output
