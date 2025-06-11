#!/usr/bin/env pwsh

# Treat all errors as terminating
$ErrorActionPreference = 'Stop'

function Handle-Error {
    param($ErrorRecord)
    Write-Error "❌ ERROR: $($ErrorRecord.Exception.Message)"
    Exit 1
}

try {
    # Activate the virtual environment
    if (Test-Path .\.venv\Scripts\Activate.ps1) {
        . .\.venv\Scripts\Activate.ps1
        Write-Host "✅ Virtual environment activated."
    } else {
        throw "Virtual environment activation script not found at .\.venv\Scripts\Activate.ps1"
    }

    # Change into the app/ folder
    if (Test-Path .\app) {
        Set-Location -Path .\app
        Write-Host "📂 Changed directory to 'app\'."
    } else {
        throw "Directory '.\app' not found."
    }

    # Run the Python script
    if (Test-Path .\main.py) {
        Write-Host "🔄 Running main.py..."
        python .\main.py
        Write-Host "✅ main.py completed successfully."
    } else {
        throw "File 'main.py' not found in '.\app'."
    }
}
catch {
    Handle-Error $_
}
