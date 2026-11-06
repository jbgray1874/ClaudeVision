import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


class SpreadsheetFormulaParserError(RuntimeError):
    pass


# Safety clamp: estimate templates are ~106 rows. UsedRange is frequently inflated
# by stray formatting (thousands of phantom rows), so never read beyond this.
MAX_ROWS = 2000
MAX_COLS = 200


def _build_powershell_script(workbook_path: str, output_path: str, sheet_names: Optional[List[str]] = None) -> str:
    if sheet_names:
        quoted = ",".join([f"'{name}'" for name in sheet_names])
        sheet_filter = f"$targetSheets = @({quoted})"
    else:
        sheet_filter = "$targetSheets = @()"

    return f"""$ErrorActionPreference = 'Stop'
{sheet_filter}
$workbookPath = '{workbook_path.replace("'", "''")}'
$outputPath = '{output_path.replace("'", "''")}'
$MaxRows = {MAX_ROWS}
$MaxCols = {MAX_COLS}

function Get-ColLetter([int]$col) {{
    $result = ''
    while ($col -gt 0) {{
        $mod = ($col - 1) % 26
        $result = [char](65 + $mod) + $result
        $col = [math]::Floor(($col - 1) / 26)
    }}
    return $result
}}

# Decide whether a cell is worth capturing. Operates on already-extracted
# (in-memory) formula/text values — NO COM calls in here.
# Col C/G rows 11-102: material descriptions (11-58) and operation names (63-102)
# Col D rows 11-58 + D/F/G row 6: quantity / unit-cost headers.
function Should-CaptureCell([string]$sheetName, [int]$row, [int]$col, $formula, $text) {{
    if ($formula -is [string] -and $formula.StartsWith('=')) {{
        return $true
    }}
    if ($sheetName -eq 'Estimate' -or $sheetName -eq 'ESTIMATE') {{
        $colLetter = Get-ColLetter $col
        if (($colLetter -eq 'C' -or $colLetter -eq 'G') -and $row -ge 11 -and $row -le 102) {{
            return ($text -ne $null -and ([string]$text).Trim() -ne '')
        }}
        if ($colLetter -eq 'D' -and $row -ge 11 -and $row -le 58) {{
            return ($text -ne $null -and ([string]$text).Trim() -ne '')
        }}
        if ($colLetter -in @('D','F','G') -and $row -eq 6) {{
            return ($text -ne $null -and ([string]$text).Trim() -ne '')
        }}
    }}
    return $false
}}

# COM ranges return a [,] 2D array for multi-cell ranges but a SCALAR for a 1x1
# range. Normalise element access so a single-cell sheet does not blow up.
function Get-ArrItem($arr, [int]$r, [int]$c) {{
    if ($arr -is [Array]) {{ return $arr.GetValue($r, $c) }}
    if ($r -eq 1 -and $c -eq 1) {{ return $arr }}
    return $null
}}

$excel = $null
$workbook = $null
try {{
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.ScreenUpdating = $false
    $excel.EnableEvents = $false
    $excel.AskToUpdateLinks = $false

    # Open hardened against the two indefinite-hang modes:
    #   UpdateLinks = 0  -> never prompt / chase external links
    #   ReadOnly    = $true -> no write-lock or read-only-recommended prompt
    $workbook = $excel.Workbooks.Open($workbookPath, 0, $true)

    # Manual calc AFTER open avoids a recalc-on-open storm on volatile books.
    try {{ $excel.Calculation = -4135 }} catch {{ }}  # xlCalculationManual

    $result = [ordered]@{{
        workbook_path = $workbookPath
        workbook_name = $workbook.Name
        sheets = @()
    }}

    foreach ($worksheet in $workbook.Worksheets) {{
        if ($targetSheets.Count -gt 0 -and -not ($targetSheets -contains [string]$worksheet.Name)) {{
            continue
        }}

        $sheetName = [string]$worksheet.Name
        $used = $worksheet.UsedRange
        $usedRows = [int]$used.Rows.Count
        $usedCols = [int]$used.Columns.Count
        $baseRow = [int]$used.Row
        $baseCol = [int]$used.Column

        # Clamp before reading so an inflated UsedRange can't pull a giant array.
        $nRows = [Math]::Min($usedRows, $MaxRows)
        $nCols = [Math]::Min($usedCols, $MaxCols)

        $sheetData = [ordered]@{{
            sheet_name = $sheetName
            rows = $usedRows
            cols = $usedCols
            clamped = ($nRows -lt $usedRows -or $nCols -lt $usedCols)
            formulas = @()
        }}

        if ($nRows -ge 1 -and $nCols -ge 1) {{
            $readRange = $worksheet.Range(
                $worksheet.Cells.Item($baseRow, $baseCol),
                $worksheet.Cells.Item($baseRow + $nRows - 1, $baseCol + $nCols - 1)
            )

            # TWO bulk COM reads. IMPORTANT: only .Formula and .Value2 return a
            # 2D array for a multi-cell range. .Text and .NumberFormat return Null
            # on any non-uniform range, so they CANNOT be bulk-read — we use
            # .Value2 for the value (gives computed numbers AND text descriptions).
            $fArr = $readRange.Formula
            $vArr = $readRange.Value2

            for ($r = 1; $r -le $nRows; $r++) {{
                for ($c = 1; $c -le $nCols; $c++) {{
                    $formula = [string](Get-ArrItem $fArr $r $c)
                    $value = Get-ArrItem $vArr $r $c
                    $text = [string]$value
                    $absRow = $baseRow + $r - 1
                    $absCol = $baseCol + $c - 1

                    if (-not (Should-CaptureCell $sheetName $absRow $absCol $formula $text)) {{
                        continue
                    }}

                    $isFormula = ($formula -is [string] -and $formula.StartsWith('='))

                    $colLetter = Get-ColLetter $absCol
                    $address = $colLetter + $absRow
                    # .Value2 gives the cell's underlying value: the computed result
                    # for a formula, the string for a description. Both are what the
                    # distiller needs; formatted text (£, dp) is not.
                    $left1 = if ($c -gt 1) {{ [string](Get-ArrItem $vArr $r ($c - 1)) }} else {{ '' }}
                    $left2 = if ($c -gt 2) {{ [string](Get-ArrItem $vArr $r ($c - 2)) }} else {{ '' }}
                    $right1 = if ($c -lt $nCols) {{ [string](Get-ArrItem $vArr $r ($c + 1)) }} else {{ '' }}

                    $sheetData.formulas += [ordered]@{{
                        address = $address
                        row = $absRow
                        col = $absCol
                        value = $text
                        formula = if ($isFormula) {{ $formula }} else {{ '' }}
                        number_format = ''
                        label_left = $left1
                        label_left_2 = $left2
                        label_right = $right1
                        is_plain_text = (-not $isFormula)
                    }}
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
