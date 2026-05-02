# ============================================================================
# StealthDOM Installer (Windows)
# ============================================================================
# This script installs Python dependencies and sets up the bridge auto-start.
# Browser and IDE configuration is left as a manual step for the user.
# ============================================================================

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
$ExtensionDir = Join-Path $ProjectDir "extension"

# --- Helpers ---

function Write-Banner {
    param([string]$Text)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Write-Step {
    param([string]$Text)
    Write-Host ""
    Write-Host "  >> $Text" -ForegroundColor Yellow
}

function Write-Ok {
    param([string]$Text)
    Write-Host "     [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "     [!!] $Text" -ForegroundColor DarkYellow
}

function Write-Err {
    param([string]$Text)
    Write-Host "     [FAIL] $Text" -ForegroundColor Red
}

function Write-Info {
    param([string]$Text)
    Write-Host "     $Text" -ForegroundColor Gray
}

# Track results for summary
$results = @()
function Add-Result {
    param([string]$Name, [bool]$Success, [string]$Detail = "")
    $script:results += [PSCustomObject]@{ Name = $Name; Success = $Success; Detail = $Detail }
}

# ============================================================================
# Step 1: Check Python
# ============================================================================
Write-Banner "Step 1/4: Checking Python"

$pythonCmd = $null
$pythonVersion = $null

# Try 'python' first, then 'python3', then 'py'
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 10) {
                $pythonCmd = $cmd
                $pythonVersion = $ver.ToString().Trim()
                break
            }
        }
    } catch {}
}

if ($pythonCmd) {
    Write-Ok "$pythonVersion found (command: $pythonCmd)"
    Add-Result "Python" $true $pythonVersion
} else {
    Write-Step "Python 3.10+ not found. Attempting to install..."

    $installerUrl = "https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-installer.exe"

    try {
        Write-Info "Downloading Python 3.12.4..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

        Write-Info "Installing Python (this may take a minute)..."
        Start-Process -FilePath $installerPath -ArgumentList "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0" -Wait

        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

        # Verify
        $ver = & python --version 2>&1
        if ($ver -match "Python 3") {
            $pythonCmd = "python"
            $pythonVersion = $ver.ToString().Trim()
            Write-Ok "$pythonVersion installed successfully"
            Add-Result "Python" $true "Installed $pythonVersion"
        } else {
            throw "Python installed but not found in PATH"
        }
    } catch {
        Write-Err "Could not install Python automatically: $_"
        Write-Info "Please install Python 3.10+ from https://python.org and re-run this installer."
        Add-Result "Python" $false "Install failed"
    } finally {
        if (Test-Path $installerPath) { Remove-Item $installerPath -Force -ErrorAction SilentlyContinue }
    }
}

if (-not $pythonCmd) {
    Write-Host ""
    Write-Err "Cannot continue without Python. Exiting."
    exit 1
}

# ============================================================================
# Step 2: Install Dependencies
# ============================================================================
Write-Banner "Step 2/4: Installing Python Dependencies"

try {
    $reqFile = Join-Path $ProjectDir "requirements.txt"
    if (-not (Test-Path $reqFile)) {
        # Create requirements.txt if it doesn't exist
        "websockets`nmcp" | Out-File -FilePath $reqFile -Encoding utf8
    }

    & $pythonCmd -m pip install -q -r $reqFile 2>&1 | ForEach-Object {
        if ($_ -match "Successfully installed") { Write-Info $_ }
    }

    # Verify
    $check = & $pythonCmd -c "import websockets; import mcp; print('ok')" 2>&1
    if ($check -match "ok") {
        Write-Ok "websockets and mcp installed"
        Add-Result "Dependencies" $true "websockets, mcp"
    } else {
        throw "Import check failed"
    }
} catch {
    Write-Err "Dependency installation failed: $_"
    Write-Info "Try manually: $pythonCmd -m pip install websockets mcp"
    Add-Result "Dependencies" $false "$_"
}

# ============================================================================
# Step 3: Bridge Auto-Start
# ============================================================================
Write-Banner "Step 3/4: Setting Up Bridge Auto-Start"

$taskName = "StealthDOM Bridge Server"
$bridgeScript = Join-Path $ProjectDir "bridge_server.py"

# Find pythonw (windowless Python)
$pythonwCmd = $null
try {
    $pythonPath = (Get-Command $pythonCmd -ErrorAction Stop).Source
    $pythonwPath = $pythonPath -replace "python\.exe$", "pythonw.exe"
    if (Test-Path $pythonwPath) {
        $pythonwCmd = $pythonwPath
    } else {
        # Try alongside the python command
        $pythonDir = Split-Path $pythonPath
        $pythonwAlt = Join-Path $pythonDir "pythonw.exe"
        if (Test-Path $pythonwAlt) { $pythonwCmd = $pythonwAlt }
    }
} catch {}

if (-not $pythonwCmd) {
    # Fallback: use python.exe (will show a console window)
    $pythonwCmd = (Get-Command $pythonCmd -ErrorAction SilentlyContinue).Source
    if (-not $pythonwCmd) { $pythonwCmd = $pythonCmd }
    Write-Warn "pythonw.exe not found, bridge will run with a visible console window"
}

try {
    # Use the Windows Startup folder — no admin required
    $startupDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    $startupBat = Join-Path $startupDir "StealthDOM_Bridge.bat"

    # Create a small batch file that launches the bridge silently
    $batContent = @"
@echo off
cd /d "$ProjectDir"
start /min "" "$pythonwCmd" "$bridgeScript"
"@
    [System.IO.File]::WriteAllText($startupBat, $batContent, [System.Text.Encoding]::ASCII)

    if (Test-Path $startupBat) {
        Write-Ok "Bridge will auto-start on login"
        Write-Info "Startup script: $startupBat"
        Add-Result "Auto-Start" $true "Startup folder"
    } else {
        throw "Failed to create startup script"
    }
} catch {
    Write-Warn "Could not create startup entry: $_"
    Write-Info "You can set this up manually by running scripts\windows_startup_install.bat as administrator."
    Add-Result "Auto-Start" $false "$_"
}

# ============================================================================
# Step 4: Start Bridge
# ============================================================================
Write-Banner "Step 4/4: Starting Bridge Server"

# Check if bridge is already running
$bridgeRunning = Get-Process -Name "python*" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "bridge_server" }

if ($bridgeRunning) {
    Write-Ok "Bridge server is already running"
    Add-Result "Bridge" $true "Already running"
} else {
    try {
        Start-Process -FilePath $pythonwCmd -ArgumentList "`"$bridgeScript`"" -WindowStyle Hidden
        Start-Sleep -Seconds 2

        # Quick check — try to connect
        $check = & $pythonCmd -c "
import asyncio, websockets
async def test():
    try:
        ws = await asyncio.wait_for(websockets.connect('ws://127.0.0.1:9878'), timeout=3)
        await ws.close()
        print('ok')
    except: print('fail')
asyncio.run(test())
" 2>&1

        if ($check -match "ok") {
            Write-Ok "Bridge server started and accepting connections"
            Add-Result "Bridge" $true "Running on port 9878"
        } else {
            Write-Warn "Bridge started but not yet accepting connections."
            Write-Info "It may need a browser tab to be opened first."
            Add-Result "Bridge" $true "Started (waiting for browser)"
        }
    } catch {
        Write-Warn "Could not start bridge: $_"
        Write-Info "Start it manually: python bridge_server.py"
        Add-Result "Bridge" $false "$_"
    }
}

# ============================================================================
# Summary & Manual Instructions
# ============================================================================
Write-Host ""
Write-Host ""
Write-Host "  +=========================================================+" -ForegroundColor Cyan
Write-Host "  |         StealthDOM Backend Installation Complete         |" -ForegroundColor Cyan
Write-Host "  +=========================================================+" -ForegroundColor Cyan
Write-Host ""

foreach ($r in $results) {
    $icon = if ($r.Success) { "[OK]" } else { "[!!]" }
    $color = if ($r.Success) { "Green" } else { "DarkYellow" }
    $detail = if ($r.Detail) { " -- $($r.Detail)" } else { "" }
    Write-Host "    $icon $($r.Name)$detail" -ForegroundColor $color
}

Write-Host ""
Write-Host "  !!!  MANUAL SETUP REQUIRED  !!!" -ForegroundColor Red -BackgroundColor Black
Write-Host "  The browser extension and IDE MCP must be configured manually:" -ForegroundColor White
Write-Host ""

Write-Host "  1. INSTALL BROWSER EXTENSION" -ForegroundColor Yellow
Write-Host "     - Open brave://extensions or chrome://extensions" -ForegroundColor Gray
Write-Host "     - Enable 'Developer Mode' (top right)" -ForegroundColor Gray
Write-Host "     - Click 'Load Unpacked' and select this folder:" -ForegroundColor Gray
Write-Host "       $ExtensionDir" -ForegroundColor Cyan
Write-Host ""

$bridgePathEscaped = $bridgeScript -replace '\\', '\\'
Write-Host "  2. CONFIGURE YOUR IDE (MCP)" -ForegroundColor Yellow
Write-Host "     - Copy the JSON below into your IDE's MCP settings" -ForegroundColor Gray
Write-Host "       (e.g., Antigravity, Cursor, Windsurf, Claude Desktop):" -ForegroundColor Gray
Write-Host ""
Write-Host "{" -ForegroundColor White
Write-Host "  `"mcpServers`": {" -ForegroundColor White
Write-Host "    `"stealth_dom`": {" -ForegroundColor White
Write-Host "      `"command`": `"python`"," -ForegroundColor White
Write-Host "      `"args`": [`"$bridgePathEscaped`"]" -ForegroundColor White
Write-Host "    }" -ForegroundColor White
Write-Host "  }" -ForegroundColor White
Write-Host "}" -ForegroundColor White
Write-Host ""

Write-Host "  To uninstall: double-click uninstall.bat" -ForegroundColor Gray
Write-Host ""
Write-Host "  Press ENTER to exit..." -ForegroundColor Gray
Read-Host
