$ErrorActionPreference = 'Stop'
Set-Location 'C:\ClaudeVision'
Copy-Item -LiteralPath 'c:\Users\james.gray\Documents\Downloads\document_builder (26).py' -Destination 'src\document_builder.py' -Force
python -m py_compile 'src\document_builder.py'
$env:SKIP_VISION_EXTRACTION = '1'
$env:SDI_SKIP_WB_TEMPLATE = '1'
$pdf = 'input\drawings\M&S\M&SChinaPriced\0359148 Fruit & Nut Base Cap 1240mm Foods 2.0 12360-03.PDF'
$log = 'output\logs\mdf_rescan_agent.log'
python -u src\main.py --pdf $pdf 2>&1 | Tee-Object -FilePath $log
Select-String -Path $log -Pattern 'Unit estimate|Operations|Thicknesses|Part numbers|done estimate|TIMBER-BASED|12360-03-01'
Select-String -Path 'output\json\0359148*.json' -Pattern 'TIMBER-BASED|normalized_thickness_mm|textual_operations|operations' | Select-Object -First 40
