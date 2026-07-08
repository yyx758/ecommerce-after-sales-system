$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$taskflowRoot = "D:\taskflow_lab"
$venvPath = Join-Path $taskflowRoot "venv"
$requirementsPath = Join-Path $PSScriptRoot "requirements-taskflow-windows.txt"
$pythonCmd = $null

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed with exit code {0}: {1} {2}" -f $LASTEXITCODE, $FilePath, ($Arguments -join ' '))
    }
}

Write-Host "[1/5] Detecting local Python runtime..."
try {
    $pythonVersion = & python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pythonCmd = "python"
        Write-Host "Using $pythonVersion"
    }
} catch {
}

if (-not $pythonCmd) {
    throw "No usable Python runtime found. Please install Python first."
}

Write-Host "[2/5] Creating isolated virtual environment..."
New-Item -ItemType Directory -Path $taskflowRoot -Force | Out-Null
if (Test-Path -LiteralPath $venvPath) {
    Remove-Item -LiteralPath $venvPath -Recurse -Force
}
Invoke-CheckedCommand $pythonCmd -m venv $venvPath

Write-Host "[3/5] Upgrading pip..."
Invoke-CheckedCommand "$venvPath\Scripts\python.exe" -m pip install --upgrade pip

Write-Host "[4/5] Installing Taskflow-compatible packages..."
Invoke-CheckedCommand "$venvPath\Scripts\python.exe" -m pip install -r $requirementsPath

Write-Host "[5/5] Setup completed."
Write-Host "English-only workspace: $taskflowRoot"
Write-Host "Next run:"
Write-Host "powershell -ExecutionPolicy Bypass -File .\python_agent\test_taskflow_isolated.ps1"
