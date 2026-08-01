[CmdletBinding()]
param(
    [int]$BackendPort = 18000,
    [int]$FrontendPort = 13000
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runId = [guid]::NewGuid().ToString("N")
$runDir = Join-Path $repoRoot ".tmp\tech-selection-e2e\$runId"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

$dbPath = (Join-Path $runDir "sparklearn-e2e.db").Replace("\", "/")
$backendOut = Join-Path $runDir "backend.out.log"
$backendErr = Join-Path $runDir "backend.err.log"
$frontendOut = Join-Path $runDir "frontend.out.log"
$frontendErr = Join-Path $runDir "frontend.err.log"
$backend = $null
$frontend = $null

function Wait-ForHealth {
    param([string]$Uri)
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri $Uri -TimeoutSec 2
            if ($health.status -eq "ok") {
                return $health
            }
        } catch {
            # The servers may still be starting.
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Local stack did not become ready: $Uri"
}

try {
    $env:DATABASE_URL = "sqlite:///$dbPath"
    $env:DEMO_MODE = "true"
    $env:AUTH_SECRET = "local-e2e-only-0123456789-abcdefghijklmnopqrstuvwxyz"
    $env:SPARK_API_PASSWORD = ""
    $env:DEEPSEEK_API_KEY = ""

    $backend = Start-Process `
        -FilePath (Join-Path $repoRoot "backend\.venv\Scripts\python.exe") `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort" `
        -WorkingDirectory (Join-Path $repoRoot "backend") `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOut `
        -RedirectStandardError $backendErr `
        -PassThru

    $env:BACKEND_URL = "http://127.0.0.1:$BackendPort"
    $frontend = Start-Process `
        -FilePath (Get-Command node).Source `
        -ArgumentList "node_modules/next/dist/bin/next", "start", "-p", "$FrontendPort" `
        -WorkingDirectory (Join-Path $repoRoot "frontend") `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr `
        -PassThru

    $baseUrl = "http://127.0.0.1:$FrontendPort"
    $health = Wait-ForHealth -Uri "$baseUrl/api/health"
    $email = "tech-selection-$runId@example.test"
    $password = "Local-E2E-Only-2026!"
    $registerBody = @{
        email = $email
        password = $password
        name = "Tech selection acceptance"
    } | ConvertTo-Json

    $register = Invoke-WebRequest `
        -Uri "$baseUrl/api/auth/register" `
        -Method POST `
        -ContentType "application/json" `
        -Body $registerBody `
        -UseBasicParsing `
        -SessionVariable firstSession
    $firstUser = Invoke-RestMethod -Uri "$baseUrl/api/auth/me" -WebSession $firstSession
    Invoke-WebRequest `
        -Uri "$baseUrl/api/auth/logout" `
        -Method POST `
        -WebSession $firstSession `
        -UseBasicParsing | Out-Null

    $loginBody = @{ email = $email; password = $password } | ConvertTo-Json
    $login = Invoke-WebRequest `
        -Uri "$baseUrl/api/auth/login" `
        -Method POST `
        -ContentType "application/json" `
        -Body $loginBody `
        -UseBasicParsing `
        -SessionVariable secondSession
    $secondUser = Invoke-RestMethod -Uri "$baseUrl/api/auth/me" -WebSession $secondSession

    $tutorBody = @{
        user_id = "spoofed-user"
        question = "Explain binary trees in one sentence."
        want = "text"
    } | ConvertTo-Json
    $tutor = Invoke-WebRequest `
        -Uri "$baseUrl/api/tutor" `
        -Method POST `
        -ContentType "application/json" `
        -Headers @{ Accept = "text/event-stream" } `
        -Body $tutorBody `
        -WebSession $secondSession `
        -UseBasicParsing `
        -TimeoutSec 60
    $events = @(
        foreach ($line in ($tutor.Content -split "`r?`n")) {
            if ($line.StartsWith("data: ")) {
                $line.Substring(6) | ConvertFrom-Json
            }
        }
    )
    $hasDone = @($events | Where-Object { $_.type -eq "done" }).Count -gt 0
    $hasTutor = @($events | Where-Object {
        ($_.type -eq "token" -and -not [string]::IsNullOrWhiteSpace([string]$_.delta)) -or
        ($_.type -eq "agent_token" -and $_.agent -eq "tutor")
    }).Count -gt 0

    $result = [ordered]@{
        ready = $health.status -eq "ok"
        register_status = $register.StatusCode
        relogin_status = $login.StatusCode
        same_user_after_relogin = $firstUser.id -eq $secondUser.id
        tutor_status = $tutor.StatusCode
        sse_events = $events.Count
        has_tutor_event = $hasTutor
        has_done_event = $hasDone
        logs = $runDir
    }
    $result | ConvertTo-Json -Compress

    if (-not $result.same_user_after_relogin -or -not $hasTutor -or -not $hasDone) {
        throw "Local end-to-end acceptance failed"
    }
} finally {
    if ($frontend -and -not $frontend.HasExited) {
        Stop-Process -Id $frontend.Id -Force
    }
    if ($backend -and -not $backend.HasExited) {
        Stop-Process -Id $backend.Id -Force
    }
}
