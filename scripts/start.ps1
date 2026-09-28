param([switch]$WithAI)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

try {
    $dockerCommand = (Get-Command docker -ErrorAction SilentlyContinue).Source
    if (-not $dockerCommand) {
        $dockerCandidate = Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'
        if (Test-Path -LiteralPath $dockerCandidate) {
            $dockerCommand = $dockerCandidate
        } else {
            throw 'Docker Desktop is not installed. Install it once, then run this file again.'
        }
    }

    & $dockerCommand info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        $desktopPath = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (-not (Test-Path -LiteralPath $desktopPath)) {
            throw 'Docker Engine is not ready and Docker Desktop was not found. Open Docker Desktop and try again.'
        }
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Write-Host 'Starting Docker Desktop...'
            Start-Process -FilePath $desktopPath -WindowStyle Hidden
        }
        Write-Host 'Waiting for Docker Engine...'
        $engineReady = $false
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            Start-Sleep -Seconds 2
            & $dockerCommand info --format '{{.ServerVersion}}' *> $null
            if ($LASTEXITCODE -eq 0) {
                $engineReady = $true
                break
            }
        }
        if (-not $engineReady) {
            throw 'Docker Engine did not start. Open Docker Desktop once to complete its setup, then try again.'
        }
    }

    & $dockerCommand compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose v2 is required. Update Docker Desktop.'
    }

    if ($WithAI) {
        $secureKey = Read-Host 'OpenRouter API key' -AsSecureString
        $env:OPENROUTER_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
        if ([string]::IsNullOrWhiteSpace($env:OPENROUTER_API_KEY)) {
            throw 'An OpenRouter API key is required for this launcher.'
        }
    }

    & $dockerCommand compose up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw 'The container could not start. Check the Docker output above.'
    }

    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/api/health' -TimeoutSec 2
            if ($health.ok -eq $true) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }

    if (-not $ready) {
        throw 'The server did not become ready. Run: docker compose logs --tail=100 app'
    }

    Start-Process -FilePath 'http://127.0.0.1:5000/'
    Write-Host 'PM Radar is ready at http://127.0.0.1:5000/'
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
} finally {
    if ($WithAI) {
        Remove-Item Env:OPENROUTER_API_KEY -ErrorAction SilentlyContinue
    }
}
