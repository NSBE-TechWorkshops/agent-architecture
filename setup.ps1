<#
 One-time setup check for Windows (PowerShell).

   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Yes        # answer yes to install questions
   powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoBuild    # skip the slow image build

 macOS / Linux users: run ./setup.sh instead.
#>
param([switch]$Yes, [switch]$NoBuild)

Set-Location -Path $PSScriptRoot
$ErrorActionPreference = "Continue"

function Ok($m)   { Write-Host "[ok]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[warn] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[fail] $m" -ForegroundColor Red }
function Step($m) { Write-Host ""; Write-Host $m -ForegroundColor Cyan }
function Ask($q) {
    if ($Yes) { return $true }
    $r = Read-Host "$q [y/N]"
    return ($r -match '^(y|yes)$')
}
function DockerRunning { docker info *> $null; return ($LASTEXITCODE -eq 0) }

Write-Host "Internship Agent: setup check (Windows)" -ForegroundColor Cyan

# ---- 1. Is Docker installed? ----
Step "1/5  Checking that Docker is installed"
if (Get-Command docker -ErrorAction SilentlyContinue) {
    Ok ("Docker found: " + (docker --version))
} else {
    Warn "Docker is not installed."
    if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Ask "Install Docker Desktop with winget now?")) {
        winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
        Warn "Docker Desktop is installed. You may need to RESTART your computer (it enables WSL 2)."
        Warn "After restarting, open Docker Desktop once, accept the terms, then run this script again."
        exit 0
    } else {
        Fail "Install Docker Desktop from https://www.docker.com/products/docker-desktop/ then run this script again."
        exit 1
    }
}

# ---- 2. Is the Docker engine running? ----
Step "2/5  Checking that Docker is running"
if (DockerRunning) {
    Ok "Docker engine is running."
} else {
    Warn "Docker Desktop is not running. Starting it..."
    $exe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $exe) { Start-Process $exe } else { Fail "Could not find Docker Desktop. Start it from the Start menu, then run this script again."; exit 1 }
    Write-Host -NoNewline "Waiting for Docker to start (up to 2 minutes)"
    for ($i = 0; $i -lt 60; $i++) {
        if (DockerRunning) { break }
        Write-Host -NoNewline "."; Start-Sleep -Seconds 2
    }
    Write-Host ""
    if (DockerRunning) { Ok "Docker engine is running." }
    else { Fail "Docker did not start in time. Open Docker Desktop, wait until it says 'running', then run this script again."; exit 1 }
}

# ---- 3. Docker Compose v2 ----
Step "3/5  Checking Docker Compose"
docker compose version *> $null
if ($LASTEXITCODE -eq 0) { Ok ("Docker Compose found: " + (docker compose version --short)) }
else { Fail "'docker compose' (v2) is missing. Update Docker Desktop to the latest version."; exit 1 }

# ---- 4. .env file ----
Step "4/5  Checking the .env settings file"
if (Test-Path .env) {
    Ok ".env already exists (leaving it alone)."
} else {
    Copy-Item .env.example .env
    Ok "Created .env from .env.example (works as-is in mock mode, no keys needed)."
}
if (Select-String -Path .env -Pattern '^OPENAI_API_KEY=.+' -Quiet) { Ok "OPENAI_API_KEY is set: the agent will use the LLM." }
else { Warn "No OPENAI_API_KEY in .env: the agent will run in mock/keyword mode (fine for a first run)." }

# ---- 5. Port 8000 + build ----
Step "5/5  Checking port 8000 and building the image"
$running = docker compose ps --status running --services 2>$null
if ($running -contains "api") {
    Ok "The API is already running from this project."
} elseif (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    Warn 'Port 8000 is used by another program. Stop it, or change "8000:8000" in docker-compose.yml (e.g. "8001:8000").'
} else {
    Ok "Port 8000 is free."
}

if (-not $NoBuild) {
    Write-Host "Building the image (first time takes a few minutes)..."
    docker compose build
    if ($LASTEXITCODE -eq 0) { Ok "Image built." } else { Fail "Build failed. Check your internet connection and the error above."; exit 1 }
} else {
    Warn "Skipped the build (-NoBuild). It will build on first 'docker compose up --build'."
}

Write-Host ""
Write-Host "You are ready. Run these two commands in two separate terminals:" -ForegroundColor Green
Write-Host ""
Write-Host "  Terminal 1:  docker compose up"
Write-Host "  Terminal 2:  docker compose run --rm tui"
Write-Host ""
Write-Host "Then press 'r' in the UI. API docs: http://localhost:8000/docs"
