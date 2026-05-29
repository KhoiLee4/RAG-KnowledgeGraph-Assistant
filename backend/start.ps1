# Chạy backend FastAPI bằng venv của project (tránh lỗi thiếu pydantic_settings)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root "venv\Scripts\python.exe"
$VenvUvicorn = Join-Path $Root "venv\Scripts\uvicorn.exe"

if (-not (Test-Path $VenvUvicorn)) {
    Write-Host "Chua co venv. Chay tu thu muc goc:" -ForegroundColor Yellow
    Write-Host "  python -m venv venv" -ForegroundColor Cyan
    Write-Host "  .\venv\Scripts\pip install -r backend\requirements.txt" -ForegroundColor Cyan
    exit 1
}

Set-Location $PSScriptRoot

$Port = 8081
$InUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($InUse) {
    $Pid = $InUse[0].OwningProcess
    Write-Host "Cang $Port dang duoc dung boi PID $Pid." -ForegroundColor Yellow
    Write-Host "Neu la backend cu: taskkill /PID $Pid /F roi chay lai start.ps1" -ForegroundColor Yellow
    Write-Host "Hoac mo http://127.0.0.1:$Port/api/v1/health de kiem tra." -ForegroundColor Cyan
    exit 1
}

Write-Host "Backend: http://127.0.0.1:$Port (Ctrl+C de dung)" -ForegroundColor Green
& $VenvUvicorn main:app --host 127.0.0.1 --port $Port --reload
