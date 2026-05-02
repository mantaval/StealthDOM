# ============================================================================
# StealthDOM Uninstaller (Windows)
# ============================================================================
# This script reverses backend changes made by install.ps1:
#   1. Removes bridge auto-start task
#   2. Stops the bridge server
# Does NOT uninstall Python or pip packages.
# ============================================================================

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectDir = Split-Path -Parent $ScriptDir
$ExtensionDir = Join-Path $ProjectDir "extension"

# --- Helpers ---

function Write-Banner {
    param([string]$Text)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Magenta
    Write-Host "  $Text" -ForegroundColor Magenta
    Write-Host "============================================================" -ForegroundColor Magenta
}

function Write-Ok {
    param([string]$Text)
    Write-Host "     [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "     [!!] $Text" -ForegroundColor DarkYellow
}

function Write-Info {
    param([string]$Text)
    Write-Host "     $Text" -ForegroundColor Gray
}

$results = @()
function Add-Result {
    param([string]$Name, [bool]$Success, [string]$Detail = "")
    $script:results += [PSCustomObject]@{ Name = $Name; Success = $Success; Detail = $Detail }
}

# ============================================================================
# Step 1: Remove Auto-Start
# ============================================================================
Write-Banner "Step 1/2: Removing Bridge Auto-Start"

$startupBat = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\StealthDOM_Bridge.bat"
$taskName = "StealthDOM Bridge Server"

# Remove Startup folder script (new approach)
if (Test-Path $startupBat) {
    Remove-Item $startupBat -Force -ErrorAction SilentlyContinue
    Write-Ok "Removed startup script: StealthDOM_Bridge.bat"
    Add-Result "Auto-Start" $true "Removed from Startup folder"
} else {
    # Also try removing old Task Scheduler task (from earlier installs)
    try {
        $existing = schtasks /query /tn "$taskName" 2>&1
        if ($LASTEXITCODE -eq 0) {
            schtasks /delete /tn "$taskName" /f 2>&1 | Out-Null
            Write-Ok "Removed legacy startup task: '$taskName'"
            Add-Result "Auto-Start" $true "Removed legacy task"
        } else {
            Write-Info "No auto-start entry found (already clean)"
            Add-Result "Auto-Start" $true "Already clean"
        }
    } catch {
        Write-Info "No auto-start entry found (already clean)"
        Add-Result "Auto-Start" $true "Already clean"
    }
}

# ============================================================================
# Step 2: Stop Bridge Server
# ============================================================================
Write-Banner "Step 2/2: Stopping Bridge Server"

$bridgeKilled = $false
$bridgeProcesses = Get-Process -Name "python*", "pythonw*" -ErrorAction SilentlyContinue

foreach ($proc in $bridgeProcesses) {
    try {
        # Check command line for bridge_server
        $wmi = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue
        if ($wmi -and $wmi.CommandLine -match "bridge_server") {
            Stop-Process -Id $proc.Id -Force
            $bridgeKilled = $true
            Write-Ok "Stopped bridge server (PID $($proc.Id))"
        }
    } catch {
        Write-Warn "Could not stop process $($proc.Id): $_"
    }
}

if ($bridgeKilled) {
    Add-Result "Bridge" $true "Stopped"
} else {
    Write-Info "Bridge server was not running"
    Add-Result "Bridge" $true "Was not running"
}

# ============================================================================
# Summary
# ============================================================================
Write-Host ""
Write-Host ""
Write-Host "  +=========================================================+" -ForegroundColor Magenta
Write-Host "  |         StealthDOM Uninstall Complete                    |" -ForegroundColor Magenta
Write-Host "  +=========================================================+" -ForegroundColor Magenta
Write-Host ""

foreach ($r in $results) {
    $icon = if ($r.Success) { "[OK]" } else { "[!!]" }
    $color = if ($r.Success) { "Green" } else { "DarkYellow" }
    $detail = if ($r.Detail) { " -- $($r.Detail)" } else { "" }
    Write-Host "    $icon $($r.Name)$detail" -ForegroundColor $color
}

Write-Host ""
Write-Host "  !!!  ACTION REQUIRED  !!!" -ForegroundColor Red -BackgroundColor Black
Write-Host "  >>> Don't forget to manually remove the extension and MCP config: <<<" -ForegroundColor White
Write-Host "      1. Go to brave://extensions or chrome://extensions and click Remove" -ForegroundColor White
Write-Host "      2. Remove the `"stealth_dom`" JSON block from your IDE's MCP settings" -ForegroundColor White
Write-Host ""
Write-Host "  Python and pip packages were NOT removed (they may be used by other apps)." -ForegroundColor Gray
Write-Host "  The StealthDOM folder itself was NOT deleted. Remove it manually if desired." -ForegroundColor Gray
Write-Host ""
Write-Host "  Press ENTER to exit..." -ForegroundColor Gray
Read-Host
