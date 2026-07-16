# patch_app_py.ps1
# Adds the missing "/" route into app.py so the backend serves the portal at
# http://localhost:8071/.  Backs up the original to app.py.bak first.
#
# Usage (from the sdi-intelligence-backend folder):
#     .\patch_app_py.ps1
# If PowerShell blocks the script (execution policy):
#     powershell -ExecutionPolicy Bypass -File .\patch_app_py.ps1

if (-not (Test-Path .\app.py)) {
    Write-Host "ERROR: app.py not found in $PWD" -ForegroundColor Red
    Write-Host "       cd to the sdi-intelligence-backend folder and try again." -ForegroundColor Red
    exit 1
}

$content = Get-Content .\app.py -Raw -Encoding UTF8

if ($content -match '_PORTAL') {
    Write-Host "Already patched - '_PORTAL' is present in app.py. Nothing to do." -ForegroundColor Yellow
}
elseif ($content -match 'if __name__ == "__main__":') {

    # Backup
    Copy-Item .\app.py .\app.py.bak -Force
    Write-Host "Backup saved to app.py.bak" -ForegroundColor Cyan

    $insert = @'

# Serve the portal at "/" so the site and API are same-origin
_PORTAL = Path(__file__).with_name("sdi-intelligence-portal.html")

@app.get("/")
def home():
    if _PORTAL.exists():
        return FileResponse(str(_PORTAL))
    return JSONResponse({"status": "backend up",
                         "note": "place sdi-intelligence-portal.html next to app.py"})


'@

    $pattern = [regex]::Escape('if __name__ == "__main__":')
    $patched = $content -replace $pattern, ($insert + 'if __name__ == "__main__":')

    [System.IO.File]::WriteAllText(
        (Resolve-Path .\app.py).Path,
        $patched,
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Host "Patched app.py." -ForegroundColor Green
}
else {
    Write-Host "ERROR: Could not find the line  if __name__ == ""__main__"":  in app.py" -ForegroundColor Red
    Write-Host "       Open app.py and check the bottom of the file." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Verification (findstr _PORTAL):"
findstr "_PORTAL" app.py

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  python app.py        # restart the server"
Write-Host "  Then open:  http://localhost:8071/"
