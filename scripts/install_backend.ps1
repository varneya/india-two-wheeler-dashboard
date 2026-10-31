# =============================================================================
# install_backend.ps1 - Bootstraps the FastAPI backend on Windows
#
# Idempotent: safe to re-run. Each step skips itself if already done.
#
# Usage (from the repo root, in PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\install_backend.ps1
#
# What it does:
#   1. Checks for Python 3.12+. If missing, offers to install 3.12 via winget.
#   2. Creates backend\venv if it doesn't exist.
#   3. Upgrades pip and installs everything in backend\requirements.txt.
#   4. Prints the command to actually run the server.
# =============================================================================

$ErrorActionPreference = "Stop"

function Write-Info    ($m) { Write-Host "[info]  $m"  -ForegroundColor Cyan }
function Write-Ok      ($m) { Write-Host "[ok]    $m"  -ForegroundColor Green }
function Write-WarnTag ($m) { Write-Host "[warn]  $m"  -ForegroundColor Yellow }
function Write-ErrTag  ($m) { Write-Host "[error] $m"  -ForegroundColor Red }
function Write-Step    ($m) { Write-Host ""; Write-Host $m -ForegroundColor White }

# Resolve repo root from script location so the user can run this from anywhere.
$repoRoot   = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendDir = Join-Path $repoRoot "backend"
$venvDir    = Join-Path $backendDir "venv"
$reqFile    = Join-Path $backendDir "requirements.txt"

if (-not (Test-Path $reqFile)) {
    Write-ErrTag "Could not find $reqFile - is this script being run from the repo?"
    exit 1
}

# -------------------------------------------------------------------
# 1. Python presence + version check
# -------------------------------------------------------------------
Write-Step "Step 1 - Checking Python"

function Get-PythonExe {
    foreach ($candidate in @("py", "python", "python3")) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

function Get-PythonVersion ($exe) {
    try {
        if ((Split-Path $exe -Leaf) -ieq "py.exe" -or (Split-Path $exe -Leaf) -ieq "py") {
            $out = & $exe -3 --version 2>&1
        } else {
            $out = & $exe --version 2>&1
        }
        if ($out -match "Python (\d+)\.(\d+)\.(\d+)") {
            return @{ major = [int]$matches[1]; minor = [int]$matches[2]; raw = $out.Trim() }
        }
    } catch {
        return $null
    }
    return $null
}

$pyExe = Get-PythonExe
$pyVer = if ($pyExe) { Get-PythonVersion $pyExe } else { $null }

$needsInstall = -not $pyVer -or $pyVer.major -ne 3 -or $pyVer.minor -lt 12
if ($needsInstall) {
    if ($pyVer) {
        Write-WarnTag "Found Python $($pyVer.raw) but need 3.12+."
    } else {
        Write-WarnTag "Python 3 not found on PATH."
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Write-ErrTag "winget not available. Install Python 3.12 manually from https://www.python.org/downloads/windows/ and re-run this script."
        exit 1
    }

    $resp = Read-Host "Install Python 3.12 via winget now? (y/N)"
    if ($resp -notmatch "^[Yy]") {
        Write-ErrTag "Aborting. Re-run after installing Python 3.12+ yourself."
        exit 1
    }

    Write-Info "Installing Python 3.12 via winget..."
    winget install Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements

    # Refresh PATH for this session so the new `python` is reachable.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")

    $pyExe = Get-PythonExe
    $pyVer = if ($pyExe) { Get-PythonVersion $pyExe } else { $null }
    if (-not $pyVer -or $pyVer.major -ne 3 -or $pyVer.minor -lt 12) {
        Write-ErrTag "Python install didn't take effect in this shell. Open a new PowerShell window and re-run this script."
        exit 1
    }
}

Write-Ok "Using $($pyVer.raw) at $pyExe"

# Decide which exe form to use for venv creation. The `py` launcher needs `-3.X`,
# while `python.exe` is invoked directly.
$venvCmd = @($pyExe)
$exeName = (Split-Path $pyExe -Leaf).ToLower()
if ($exeName -eq "py.exe" -or $exeName -eq "py") {
    $venvCmd = @($pyExe, "-3")
}

# -------------------------------------------------------------------
# 2. Create the virtualenv (backend\venv)
# -------------------------------------------------------------------
Write-Step "Step 2 - Creating virtualenv at backend\venv"

$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (Test-Path $venvPython) {
    $existingVersion = Get-PythonVersion $venvPython
    if (-not $existingVersion -or $existingVersion.major -ne 3 -or $existingVersion.minor -lt 12) {
        Write-ErrTag "Existing backend/venv needs Python 3.12+. Move it aside and re-run."
        exit 1
    }
    Write-Ok "venv already exists - reusing"
} else {
    Write-Info "Running '$($venvCmd -join ' ') -m venv $venvDir'..."
    $venvArgs = @("-m", "venv", $venvDir)
    if ($venvCmd.Length -gt 1) { $venvArgs = @($venvCmd[1]) + $venvArgs }
    & $venvCmd[0] @venvArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Write-ErrTag "venv creation failed. Check the output above."
        exit 1
    }
    Write-Ok "venv created"
}

# -------------------------------------------------------------------
# 3. Upgrade pip + install requirements.txt
# -------------------------------------------------------------------
Write-Step "Step 3 - Installing backend dependencies"

Write-Info "Upgrading pip inside the venv..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-ErrTag "pip upgrade failed."
    exit 1
}

Write-Info "Installing core requirements.txt (ML extras are optional)..."
& $venvPython -m pip install -r $reqFile
if ($LASTEXITCODE -ne 0) {
    Write-ErrTag "Dependency install failed. See the output above."
    exit 1
}
Write-Ok "All dependencies installed"

# Confirm core modules import without the optional ML stack.
Write-Info "Smoke-testing imports..."
& $venvPython -c "import fastapi, uvicorn, requests, bs4, anthropic, pydantic_settings, numpy, pandas, psutil, yt_dlp, youtube_transcript_api; print('imports OK')"
if ($LASTEXITCODE -ne 0) {
    Write-ErrTag "A core import failed - check the trace above."
    exit 1
}

# -------------------------------------------------------------------
# Done
# -------------------------------------------------------------------
Write-Host ""
Write-Host "Backend is ready!" -ForegroundColor Green
Write-Host ""
Write-Host "  venv   : $venvDir"
Write-Host "  Python : $($pyVer.raw)"
Write-Host ""
Write-Host "To start the FastAPI server in this PowerShell session:"
Write-Host "  cd $backendDir"
Write-Host "  .\venv\Scripts\activate"
Write-Host "  uvicorn main:app --port 8000"
Write-Host ""
Write-Host "Or in one line (no activation needed):"
Write-Host "  $venvPython -m uvicorn main:app --app-dir $backendDir --port 8000"
Write-Host ""
Write-Host "Optional ML methods: $venvPython -m pip install -r $backendDir/requirements-ml.txt"
Write-Host "Optional local LLM: scripts\install_ollama.ps1"
