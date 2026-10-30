import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


class SpreadsheetFormulaParserError(RuntimeError):
    pass


def _build_powershell_script(workbook_path: str, output_path: str, sheet_names: Optional[List[str]] = None) -> str:
    sheet_filter = ""
    if sheet_names:
        quoted = ",".join([f"'{name}'" for name in sheet_names])
        sheet_filter = f"$targetSheets = @({quoted})"
    else:
        sheet_filter = "$targetSheets = @()"

    return f"""$ErrorActionPreference = 'Stop'
{sheet_filter}
$workbookPath = '{workbook_path.replace("'", "''")}'
$outputPath = '{output_path.replace("'", "''")}'

function Get-ColLetter([int]$col) {{
    $result = ''
    while ($col -gt 0) {{
        $mod = ($col - 1) % 26
        $result = [char](65 + $mod) + $result
        $col = [math]::Floor(($col - 1) / 26)
    }}
    return $result
}}

# On the Estimate sheet, capture plain-text cells in these columns/rows
# in addition to formula cells everywhere.
# Col C rows 11-102: material descriptions (11-58) and operation names (63-102)
# Col G rows 11-102: alternative description/operation column
# These are typed plain text — no formula — but are critical for extraction.
function Should-CaptureCell([string]$sheetName, [int]$row, [int]$col, [string]$formula, [string]$text) {{
    # Always capture formula cells
    if ($formula -is [string] -and $formula.StartsWith('=')) {{
        return $true
    }}
    # On Estimate sheet, also capture plain-text cells in key columns/rows
    if ($sheetName -eq 'Estimate' -or $sheetName -eq 'ESTIMATE') {{
        $colLetter = Get-ColLetter $col
        # Col C or G, rows 11-102: descriptions and operation names
        if (($colLetter -eq 'C' -or $colLetter -eq 'G') -and $row -ge 11 -and $row -le 102) {{
            return ($text -ne $null -and $text.Trim() -ne '')
        }}
        # Col D rows 11-58: quantity/multiplier column (may be plain text)
        if ($colLetter -eq 'D' -and $row -ge 11 -and $row -le 58) {{
            return ($text -ne $null -and $text.Trim() -ne '')
        }}
        # Header cells: F6 (unit cost), G6 (mirror), D6 (quantity)
        if ($colLetter -in @('D','F','G') -and $row -eq 6) {{
            return ($text -ne $null -and $text.Trim() -ne '')
        }}
    }}
    return $false
}}

$excel = $null
$workbook = $null
try {{
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $workbook = $excel.Workbooks.Open($workbookPath)

    $result = [ordered]@{{
        workbook_path = $workbookPath
        workbook_name = $workbook.Name
        sheets = @()
    }}

    foreach ($worksheet in $workbook.Worksheets) {{
        if ($targetSheets.Count -gt 0 -and -not ($targetSheets -contains [string]$worksheet.Name)) {{
            continue
        }}

        $used = $worksheet.UsedRange
        $sheetData = [ordered]@{{
            sheet_name = [string]$worksheet.Name
            rows = [int]$used.Rows.Count
            cols = [int]$used.Columns.Count
            formulas = @()
        }}

        for ($row = 1; $row -le $used.Rows.Count; $row++) {{
            for ($col = 1; $col -le $used.Columns.Count; $col++) {{
                $cell = $used.Cells.Item($row, $col)
                $formula = $cell.Formula
                $cellText = [string]$cell.Text
                $colLetter = Get-ColLetter $col
                $sheetName = [string]$worksheet.Name

                if (-not (Should-CaptureCell $sheetName $row $col $formula $cellText)) {{
                    continue
                }}

                $address = $colLetter + $row
                $left1 = if ($col -gt 1) {{ [string]$used.Cells.Item($row, $col - 1).Text }} else {{ '' }}
                $left2 = if ($col -gt 2) {{ [string]$used.Cells.Item($row, $col - 2).Text }} else {{ '' }}
                $right1 = if ($col -lt $used.Columns.Count) {{ [string]$used.Cells.Item($row, $col + 1).Text }} else {{ '' }}

                # For plain text cells, formula is the cell value itself
                $captureFormula = if ($formula -is [string] -and $formula.StartsWith('=')) {{ $formula }} else {{ '' }}
                $captureValue = if ($formula -is [string] -and $formula.StartsWith('=')) {{ $cellText }} else {{ [string]$cell.Value2 }}

                $sheetData.formulas += [ordered]@{{
                    address = $address
                    row = $row
                    col = $col
                    value = $captureValue
                    formula = $captureFormula
                    number_format = [string]$cell.NumberFormat
                    label_left = $left1
                    label_left_2 = $left2
                    label_right = $right1
                    is_plain_text = (-not ($formula -is [string] -and $formula.StartsWith('=')))
                }}
            }}
        }}

        $result.sheets += $sheetData
    }}

    $json = $result | ConvertTo-Json -Depth 8
    Set-Content -Path $outputPath -Value $json -Encoding UTF8
}}
finally {{
    if ($workbook -ne $null) {{
        $workbook.Close($false)
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) | Out-Null
    }}
    if ($excel -ne $null) {{
        $excel.Quit()
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
    }}
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}}
"""


def extract_workbook_formulas(workbook_path: str | Path, sheet_names: Optional[List[str]] = None) -> Dict[str, Any]:
    workbook = Path(workbook_path).resolve()
    if not workbook.exists():
        raise SpreadsheetFormulaParserError(f"Workbook not found: {workbook}")

    if os.name != "nt":
        raise SpreadsheetFormulaParserError("Legacy Excel workbook parsing is only supported on Windows.")

    with tempfile.TemporaryDirectory(prefix="xls_formula_parse_") as temp_dir:
        temp_path = Path(temp_dir)
        script_path = temp_path / "extract_formulas.ps1"
        output_path = temp_path / "formulas.json"
        script_path.write_text(
            _build_powershell_script(str(workbook), str(output_path), sheet_names),
            encoding="utf-8",
        )

        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise SpreadsheetFormulaParserError(
                "Failed to extract workbook formulas.\n"
                f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
            )

        if not output_path.exists():
            raise SpreadsheetFormulaParserError("Formula extraction did not produce an output file.")

        return json.loads(output_path.read_text(encoding="utf-8-sig"))
