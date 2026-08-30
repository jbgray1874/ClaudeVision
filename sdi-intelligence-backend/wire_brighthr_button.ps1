# ============================================================
# Wire the BrightHR "Pull only" button into the live portal
# Run on SDI-APP01. Backs up first, then does a targeted replace.
# ============================================================
$portal = "C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal.html"
$backup = "C:\ClaudeVision\sdi-intelligence-backend\sdi-intelligence-portal_prebutton.html"

# 1. Back up
Copy-Item $portal $backup -Force
Write-Host "Backed up to $backup"

$html = Get-Content $portal -Raw

# 2. Replace the COO-controls block (disabled buttons) with the wired version
$old = @'
       +'<div style="margin-top:18px;padding:14px;background:var(--bg);border:1px solid var(--line)">'
       +'<div style="font-family:var(--mono);font-size:10px;color:var(--ink-dim);letter-spacing:2px;text-transform:uppercase;margin-bottom:10px">COO controls</div>'
       +'<div style="display:flex;gap:10px;flex-wrap:wrap">'
       +'<button class="run" disabled title="Enabled once BrightHR API access is configured in .env" style="opacity:.5;cursor:not-allowed">Run Sync (Pull + Load)</button>'
       +'<button class="run" disabled title="Pull only \u2014 writes a timestamped JSON snapshot, no CSV" style="opacity:.5;cursor:not-allowed;background:transparent;color:var(--ink);border:1px solid var(--line)">Pull only</button>'
       +'<button class="run" disabled title="Load only \u2014 writes the latest snapshot to the InVentry watched folder" style="opacity:.5;cursor:not-allowed;background:transparent;color:var(--ink);border:1px solid var(--line)">Load only</button>'
       +'</div>'
       +'<div class="muted" style="margin-top:10px;font-size:12px">Buttons activate as soon as BrightHR credentials and the employee endpoint are populated in <code>.env</code>. They call <code>POST /api/hr/sync</code>, <code>/api/hr/pull</code> and <code>/api/hr/load</code> respectively.</div>'
       +'</div>',
'@

$new = @'
       +'<div style="margin-top:18px;padding:14px;background:var(--bg);border:1px solid var(--line)">'
       +'<div style="font-family:var(--mono);font-size:10px;color:var(--ink-dim);letter-spacing:2px;text-transform:uppercase;margin-bottom:10px">COO controls</div>'
       +'<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">'
       +'<button class="run" id="hr-pull-btn" onclick="hrPull()">Pull staff from BrightHR</button>'
       +'<a class="run" style="text-decoration:none;background:transparent;color:var(--ink);border:1px solid var(--line)" data-view="files" onclick="setTimeout(function(){var n=document.querySelector(\'.nav a[data-view=files]\');if(n)n.click();},0)">View HR output folder \u2192</a>'
       +'<button class="run" disabled title="Load to InVentry \u2014 in development" style="opacity:.5;cursor:not-allowed;background:transparent;color:var(--ink);border:1px solid var(--line)">Load to InVentry (soon)</button>'
       +'</div>'
       +'<div id="hr-pull-result" class="muted" style="margin-top:12px;font-size:12px;font-family:var(--mono);white-space:pre-wrap"></div>'
       +'<div class="muted" style="margin-top:10px;font-size:12px">Pull fetches the active staff roster from BrightHR and writes a dated file to the HR output folder (<code>HRSystemsOutput</code>), browsable under <b>Files &amp; Directories</b>. Calls <code>POST /api/hr/pull</code>.</div>'
       +'</div>',
'@

if($html.Contains($old)){
    $html = $html.Replace($old, $new)
    Write-Host "COO-controls block replaced OK"
} else {
    Write-Host "WARN: COO-controls block not found verbatim - no change made. Check the file manually." -ForegroundColor Yellow
}

# 3. Inject the hrPull() function just before the closing </script>
$fnAnchor = '</script>'
$fn = @'
  // ---- BrightHR Pull (COO control) ----
  async function hrPull(){
    var btn=document.getElementById('hr-pull-btn');
    var out=document.getElementById('hr-pull-result');
    if(!btn||!out) return;
    var orig=btn.textContent;
    btn.disabled=true; btn.textContent='Pulling\u2026';
    out.style.color='var(--ink-dim)'; out.textContent='Contacting BrightHR\u2026';
    try{
      var r=await fetch(API_BASE+'/api/hr/pull',{method:'POST',headers:_hdr()});
      if(!r.ok) throw new Error(r.status+' '+(await r.text()).slice(0,200));
      var d=await r.json();
      var when=(d.timestamp||'').replace('T',' ').slice(0,19);
      var file=d.output_file ? d.output_file.split('\\').pop() : '(no output file)';
      var warn=(d.warnings&&d.warnings.length)?('\n\u26a0 '+d.warnings.join('; ')):'';
      out.style.color = d.status==='ok' ? 'var(--ok)' : 'var(--warn)';
      out.textContent='Status: '+d.status.toUpperCase()
        +'\nPulled '+d.pulled+'  \u00b7  Active '+d.active+'  \u00b7  Skipped '+d.skipped
        +'\nFile: '+file
        +'\nAt: '+when+' UTC'+warn;
    }catch(e){
      out.style.color='var(--fail)';
      out.textContent='Pull failed: '+e.message;
    }finally{
      btn.disabled=false; btn.textContent=orig;
    }
  }
'@
# insert before the LAST </script>
$idx = $html.LastIndexOf($fnAnchor)
if($idx -ge 0){
    $html = $html.Substring(0,$idx) + $fn + "`r`n" + $html.Substring($idx)
    Write-Host "hrPull() function injected OK"
} else {
    Write-Host "WARN: closing </script> not found" -ForegroundColor Yellow
}

# 4. Write back
Set-Content -Path $portal -Value $html -NoNewline -Encoding UTF8
Write-Host "Portal updated. Hard-refresh (Ctrl+Shift+R) to see the button."
