# Khởi động nhanh — in hướng dẫn chạy dự án
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "=== RAG Knowledge Graph Assistant ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Chay theo thu tu:" -ForegroundColor Yellow
Write-Host ""
Write-Host "  1. Docker (Neo4j + ChromaDB):" -ForegroundColor White
Write-Host "     docker compose up -d" -ForegroundColor Green
Write-Host ""
Write-Host "  2. Backend (terminal rieng):" -ForegroundColor White
Write-Host "     cd backend; .\start.ps1" -ForegroundColor Green
Write-Host ""
Write-Host "  3. Frontend (terminal rieng):" -ForegroundColor White
Write-Host "     cd frontend; npm run dev" -ForegroundColor Green
Write-Host ""
Write-Host "  Mo: http://localhost:3000" -ForegroundColor Cyan
Write-Host "  API: http://127.0.0.1:8081/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Tai lieu: docs\ARCHITECTURE.md, docs\DEVELOPMENT.md" -ForegroundColor DarkGray
Write-Host ""

# Kiem tra Docker
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    $running = docker compose -f (Join-Path $Root "docker-compose.yml") ps --status running -q 2>$null
    if ($running) {
        Write-Host "Docker: Neo4j + ChromaDB dang chay." -ForegroundColor Green
    } else {
        Write-Host "Docker: chua chay. Go 'docker compose up -d' de bat." -ForegroundColor Yellow
    }
}
