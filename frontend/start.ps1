# Chay frontend Vite (cổng 3000, proxy /api -> backend :8081)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "node_modules")) {
    Write-Host "Cai dependencies..." -ForegroundColor Yellow
    npm install
}

Write-Host "Frontend: http://localhost:3000" -ForegroundColor Green
npm run dev
