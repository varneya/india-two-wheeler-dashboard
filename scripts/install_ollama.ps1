# =============================================================================
# install_ollama.ps1 - Sets up Ollama for local LLM theme analysis on Windows
#
# Usage (from the repo root, in PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\install_ollama.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_ollama.ps1 mistral:7b
#
# If no model is specified, defaults to llama3.2:3b (fast, works on 8 GB RAM).
# Recommended models by RAM:
#   4  GB  -> phi3:mini    (2.2 GB)
#   8  GB  -> llama3.2:3b  (2.0 GB) or mistral:7b (4.1 GB)
#   16 GB  -> llama3.2:8b  (4.7 GB)  -- best balance of speed & quality
#   32 GB+ -> mixtral:8x7b (26 GB)   -- excellent quality
#
# Mirrors scripts/install_ollama.sh (macOS) so users on either OS see the
# same checkpoints. Sets OLLAMA_ORIGINS persistently at User scope so it
# survives reboots without manual System Properties edits.
# =============================================================================

param(
    [Parameter(Position = 0)]
    [string]$Model = "llama3.2:3b"
)

$ErrorActionPreference = "Stop"

function Write-Info    ($m) { Write-Host "[info]  $m"  -ForegroundColor Cyan }
function Write-Ok      ($m) { Write-Host "[ok]    $m"  -ForegroundColor Green }
function Write-WarnTag ($m) { Write-Host "[warn]  $m"  -ForegroundColor Yellow }
function Write-ErrTag  ($m) { Write-Host "[error] $m"  -ForegroundColor Red }
function Write-Step    ($m) { Write-Host ""; Write-Host $m -ForegroundColor White }

# -------------------------------------------------------------------
# 1. Detect OS
# -------------------------------------------------------------------
Write-Step "Step 1 - Checking operating system"
if (-not $IsWindows -and -not ($PSVersionTable.PSVersion.Major -lt 6)) {
    Write-ErrTag "This script is for Windows. On macOS run scripts/install_ollama.sh; on Linux run: curl -fsSL https://ollama.com/install.sh | sh"
    exit 1
}
Write-Ok "Windows detected"

# -------------------------------------------------------------------
# 2. Install Ollama
# -------------------------------------------------------------------
Write-Step "Step 2 - Installing Ollama"

$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    $version = & ollama --version 2>$null
    Write-Ok "Ollama already installed ($version)"
} else {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Info "Installing via winget..."
        winget install Ollama.Ollama --silent --accept-source-agreements --accept-package-agreements
        Write-Ok "Ollama installed via winget"
    } else {
        Write-Info "winget not found - downloading installer..."
        $tmpExe = Join-Path $env:TEMP "OllamaSetup.exe"
        try {
            Invoke-WebRequest "https://ollama.com/download/OllamaSetup.exe" -OutFile $tmpExe -UseBasicParsing
        } catch {
            Write-ErrTag "Download failed: $_"
            exit 1
        }
        Write-Info "Running installer (silent)..."
        Start-Process -FilePath $tmpExe -ArgumentList "/silent" -Wait
        Write-Ok "Ollama installer finished"
    }

    # Refresh PATH for this session so we can call `ollama` immediately.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-WarnTag "ollama still not on PATH for this shell. Open a new PowerShell window and re-run this script."
        exit 1
    }
}

# -------------------------------------------------------------------
# 3. Set OLLAMA_ORIGINS (persistent + this session) and start the server
# -------------------------------------------------------------------
Write-Step "Step 3 - Configuring OLLAMA_ORIGINS and starting the server"

$origin = "https://varneya.github.io"

# Persist for future PowerShell sessions
[Environment]::SetEnvironmentVariable("OLLAMA_ORIGINS", $origin, "User")
# Apply to this session
$env:OLLAMA_ORIGINS = $origin
Write-Ok "OLLAMA_ORIGINS set to $origin (persists for new PowerShell sessions)"

function Test-OllamaUp {
    try {
        Invoke-WebRequest "http://localhost:11434/api/tags" -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (Test-OllamaUp) {
    Write-WarnTag "An Ollama server is already running but may be using stale env vars."
    Write-WarnTag "Restart it (quit Ollama from the system tray, then run 'ollama serve') so it picks up OLLAMA_ORIGINS."
} else {
    Write-Info "Starting 'ollama serve' in the background..."
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 1; $i -le 20; $i++) {
        if (Test-OllamaUp) {
            Write-Ok "Ollama server is up after ${i}s"
            break
        }
        Start-Sleep -Seconds 1
        if ($i -eq 20) {
            Write-ErrTag "Ollama server did not start in time. Try running 'ollama serve' manually."
            exit 1
        }
    }
}

# -------------------------------------------------------------------
# 4. Pull the requested model
# -------------------------------------------------------------------
Write-Step "Step 4 - Pulling model: $Model"

$pulled = & ollama list 2>$null
if ($pulled -match [regex]::Escape($Model)) {
    Write-Ok "Model $Model is already pulled"
} else {
    Write-Info "Pulling $Model - this may take a few minutes depending on your connection..."
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) {
        Write-ErrTag "ollama pull failed with exit code $LASTEXITCODE"
        exit 1
    }
    Write-Ok "Model $Model pulled successfully"
}

# -------------------------------------------------------------------
# 5. Smoke test
# -------------------------------------------------------------------
Write-Step "Step 5 - Smoke test"
Write-Info "Sending a quick prompt to $Model..."
try {
    $resp = & ollama run $Model "Reply with only the word: ready" 2>$null | Select-Object -First 1
    if ($resp) {
        Write-Ok "Model responded: `"$resp`""
    } else {
        Write-WarnTag "No response from smoke test - model may still work; check manually."
    }
} catch {
    Write-WarnTag "Smoke test errored: $_"
}

# -------------------------------------------------------------------
# Done
# -------------------------------------------------------------------
Write-Host ""
Write-Host "Ollama is ready!" -ForegroundColor Green
Write-Host ""
Write-Host "  Model pulled : $Model"
Write-Host "  API base URL : http://localhost:11434"
Write-Host "  Origin       : $env:OLLAMA_ORIGINS"
Write-Host ""
Write-Host "In the dashboard, select LLM Analysis -> Local (Ollama) and pick $Model from the model list."
Write-Host ""
Write-Host "To pull a different model later:"
Write-Host "  ollama pull mistral:7b"
Write-Host ""
Write-Host "To change the allowlisted origin later:"
Write-Host "  [Environment]::SetEnvironmentVariable(""OLLAMA_ORIGINS"", ""https://your-host"", ""User"")"
