$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtimeDir = Join-Path $projectRoot ".runtime"
$pidFiles = @(
    (Join-Path $runtimeDir "api.pid"),
    (Join-Path $runtimeDir "ollama.pid"),
    (Join-Path $runtimeDir "ngrok.pid")
)

function Stop-ManagedProcess([string]$PidFile) {
    if (-not (Test-Path $PidFile)) {
        return
    }

    $pidText = Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $pidText) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return
    }

    $processId = 0
    if (-not [int]::TryParse($pidText.ToString().Trim(), [ref]$processId)) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        return
    }

    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
    } catch {
    }

    Start-Sleep -Milliseconds 500

    $stillRunning = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($stillRunning) {
        try {
            $stillRunning | Stop-Process -Force -ErrorAction Stop
        } catch {
        }
    }

    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

foreach ($pidFile in $pidFiles) {
    Stop-ManagedProcess -PidFile $pidFile
}

Write-Host "Stopped API/Ollama/ngrok processes started by this project."
