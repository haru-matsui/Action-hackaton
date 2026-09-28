param([switch]$WithAI)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker is not installed. Install and start Docker Desktop first.'
    }

    & docker info --format '{{.ServerVersion}}' *> $null
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Engine is not ready. Start Docker Desktop and try again.'
    }

    & docker compose version *> $null
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

    & docker compose up -d --build
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
