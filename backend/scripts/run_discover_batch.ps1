# Chay discover hang loat tu questions_v2.json (tranh loi encoding tieng Viet trong .ps1)
# Cach dung (tu thu muc backend):
#   powershell -ExecutionPolicy Bypass -File scripts\run_discover_batch.ps1
#
# Hoac dung Python (khuyen nghi, nhanh hon):
#   ..\venv\Scripts\python.exe scripts\discover_chunks.py --write

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot\..

$py = "..\venv\Scripts\python.exe"
$dataset = "evaluation\questions_v2.json"
$out = "evaluation\discover_output.txt"

if (-not (Test-Path $dataset)) {
    Write-Error "Khong tim thay $dataset"
    exit 1
}

$json = Get-Content $dataset -Raw -Encoding UTF8 | ConvertFrom-Json
$questions = @($json.questions | Where-Object { -not $_.should_refuse })

Write-Host "=== DISCOVER BATCH ($($questions.Count) cau, bo qua edge_case) ===" -ForegroundColor Cyan
"" | Set-Content $out -Encoding utf8

$i = 0
foreach ($item in $questions) {
    $i++
    $header = "`n========== [$($item.id)] ($i/$($questions.Count)) ==========`n"
    Write-Host $header -ForegroundColor Yellow
    Add-Content $out $header -Encoding utf8

    & $py scripts\evaluate.py discover -q $item.question --mode rag 2>&1 | Tee-Object -FilePath $out -Append
    Write-Host ""
}

Write-Host "Xong! Ket qua ghi tai: $out" -ForegroundColor Green
Write-Host "Tip: dung discover_chunks.py --write de tu dong dien expected_chunks" -ForegroundColor DarkGray
