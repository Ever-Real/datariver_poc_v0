[CmdletBinding()]
param(
    [ValidateSet("start", "stop", "status")]
    [string]$Action = "start",
    [string]$DataHubBaseUrl = "http://127.0.0.1:8080",
    [int]$PostgresPort = 5432,
    [int]$ValkeyCachePort = 6379,
    [int]$ValkeyQueuePort = 6380,
    [int]$KeycloakPort = 18081,
    [int]$ApiPort = 38101,
    [int]$WebPort = 38102,
    [int]$GatewayPort = 9080,
    [bool]$EnableEphemeralAdminChat = $true
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$runtimeDirectory = Join-Path $root "runtime/host-dev"
$stateFile = Join-Path $runtimeDirectory "processes.json"

function Get-ProcessRecords {
    if (-not (Test-Path -LiteralPath $stateFile)) {
        return @()
    }
    return @((Get-Content -Encoding utf8 -Raw -LiteralPath $stateFile | ConvertFrom-Json))
}

function Get-MatchingProcess($Record) {
    $process = Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }
    $startedAt = $process.StartTime.ToUniversalTime().ToString("o")
    if ($startedAt -ne $Record.started_at) {
        return $null
    }
    return $process
}

function Stop-ProcessTree($Process) {
    $taskkill = Join-Path $env:SystemRoot "System32/taskkill.exe"
    & $taskkill /PID $Process.Id /T /F 2>$null | Out-Null
}

function Show-Status {
    $rows = foreach ($record in Get-ProcessRecords) {
        $process = Get-MatchingProcess $record
        [PSCustomObject]@{
            Name = $record.name
            PID = $record.pid
            State = if ($null -eq $process) { "stopped" } else { "running" }
            Stdout = $record.stdout
            Stderr = $record.stderr
        }
    }
    if ($rows.Count -eq 0) {
        Write-Output "No registered DataRiver host-development processes."
        return
    }
    $rows | Format-Table -AutoSize
}

if ($Action -eq "status") {
    Show-Status
    exit 0
}

if ($Action -eq "stop") {
    foreach ($record in Get-ProcessRecords) {
        $process = Get-MatchingProcess $record
        if ($null -ne $process) {
            Stop-ProcessTree $process
        }
    }
    Remove-Item -LiteralPath $stateFile -Force -ErrorAction SilentlyContinue
    Write-Output "DataRiver host-development processes stopped."
    exit 0
}

$running = @(
    foreach ($record in Get-ProcessRecords) {
        if ($null -ne (Get-MatchingProcess $record)) {
            $record
        }
    }
)
if ($running.Count -gt 0) {
    throw "DataRiver host-development processes are already running. Use './scripts/dev.ps1 status'."
}

$python = Join-Path $root ".venv/Scripts/python.exe"
$npmCommand = (Get-Command npm.cmd -ErrorAction Stop).Source
$requiredFiles = @(
    $python,
    (Join-Path $root "secrets/postgres_app_password"),
    (Join-Path $root "secrets/postgres_relay_password"),
    (Join-Path $root "secrets/postgres_upload_password"),
    (Join-Path $root "secrets/postgres_governance_password"),
    (Join-Path $root "secrets/valkey_cache_password"),
    (Join-Path $root "secrets/valkey_queue_password"),
    (Join-Path $root "secrets/datahub_token"),
    (Join-Path $root "secrets/s3_access_key"),
    (Join-Path $root "secrets/s3_secret_key")
)
foreach ($path in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required host-development file is missing: $path"
    }
}

New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null

function Set-ProcessEnvironment([string]$Name, [string]$Value) {
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

$secret = {
    param([string]$Name)
    return "file:$((Join-Path $root "secrets/$Name"))"
}
Set-ProcessEnvironment "APP_PUBLIC_ORIGIN" "http://localhost:$WebPort"
Set-ProcessEnvironment "APP_CORS_ORIGINS" "http://localhost:$WebPort"
Set-ProcessEnvironment "APP_TRUSTED_HOSTS" "localhost,127.0.0.1,host.docker.internal,apisix"
Set-ProcessEnvironment "DATABASE_URL" "postgresql+asyncpg://datariver_app@127.0.0.1:$PostgresPort/datariver"
Set-ProcessEnvironment "DATABASE_SECRET_REF" (& $secret "postgres_app_password")
Set-ProcessEnvironment "RELAY_DATABASE_URL" "postgresql+asyncpg://datariver_relay@127.0.0.1:$PostgresPort/datariver"
Set-ProcessEnvironment "RELAY_DATABASE_SECRET_REF" (& $secret "postgres_relay_password")
Set-ProcessEnvironment "UPLOAD_DATABASE_URL" "postgresql+asyncpg://datariver_upload@127.0.0.1:$PostgresPort/datariver"
Set-ProcessEnvironment "UPLOAD_DATABASE_SECRET_REF" (& $secret "postgres_upload_password")
Set-ProcessEnvironment "GOVERNANCE_DATABASE_URL" "postgresql+asyncpg://datariver_governance@127.0.0.1:$PostgresPort/datariver"
Set-ProcessEnvironment "GOVERNANCE_DATABASE_SECRET_REF" (& $secret "postgres_governance_password")
Set-ProcessEnvironment "VALKEY_CACHE_URL" "redis://127.0.0.1:$ValkeyCachePort/0"
Set-ProcessEnvironment "VALKEY_QUEUE_URL" "redis://127.0.0.1:$ValkeyQueuePort/0"
Set-ProcessEnvironment "VALKEY_CACHE_SECRET_REF" (& $secret "valkey_cache_password")
Set-ProcessEnvironment "VALKEY_QUEUE_SECRET_REF" (& $secret "valkey_queue_password")
Set-ProcessEnvironment "S3_ENDPOINT_URL" "http://127.0.0.1:8333"
Set-ProcessEnvironment "S3_PUBLIC_ENDPOINT_URL" "http://localhost:8333"
Set-ProcessEnvironment "S3_ACCESS_KEY_FILE" (Join-Path $root "secrets/s3_access_key")
Set-ProcessEnvironment "S3_SECRET_KEY_FILE" (Join-Path $root "secrets/s3_secret_key")
Set-ProcessEnvironment "OIDC_ISSUER" "http://localhost:$KeycloakPort/realms/datariver"
Set-ProcessEnvironment "OIDC_JWKS_URL" "http://localhost:$KeycloakPort/realms/datariver/protocol/openid-connect/certs"
Set-ProcessEnvironment "DATAHUB_BASE_URL" $DataHubBaseUrl
Set-ProcessEnvironment "DATAHUB_SECRET_REF" (& $secret "datahub_token")
Set-ProcessEnvironment "SEED_PROFILE" "none"
Set-ProcessEnvironment "CHAT_EPHEMERAL_ADMIN_WITHOUT_RETENTION_ENABLED" $EnableEphemeralAdminChat.ToString().ToLowerInvariant()
# The repository may be served from the WSL filesystem while Uvicorn runs on
# Windows.  Native file notifications do not cross that boundary reliably;
# use polling so the source process behind APISIX always reflects the checked
# out backend rather than an earlier import snapshot.
Set-ProcessEnvironment "WATCHFILES_FORCE_POLLING" "true"
Set-ProcessEnvironment "VITE_API_BASE_URL" "/api/v1"
Set-ProcessEnvironment "VITE_API_PROXY_TARGET" "http://localhost:$GatewayPort"
Set-ProcessEnvironment "VITE_USE_POLLING" "true"
Set-ProcessEnvironment "VITE_OIDC_AUTHORITY" "http://localhost:$KeycloakPort/realms/datariver"
Set-ProcessEnvironment "VITE_OIDC_CLIENT_ID" "datariver-web"
Set-ProcessEnvironment "VITE_OIDC_REDIRECT_URI" "http://localhost:$WebPort"
Set-ProcessEnvironment "VITE_OIDC_HIGH_ASSURANCE_ACR" "2"
Set-ProcessEnvironment "VITE_OIDC_PASSWORD_REAUTH_ACR" "1"

$records = [Collections.Generic.List[object]]::new()
function Start-HostProcess(
    [string]$Name,
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$WorkingDirectory
) {
    $stdout = Join-Path $runtimeDirectory "$Name.out.log"
    $stderr = Join-Path $runtimeDirectory "$Name.err.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $records.Add([PSCustomObject]@{
        name = $Name
        pid = $process.Id
        started_at = $process.StartTime.ToUniversalTime().ToString("o")
        stdout = $stdout
        stderr = $stderr
    })
}

try {
    Start-HostProcess "api" $python @(
        "-m", "uvicorn", "datariver.main:app", "--host", "0.0.0.0",
        "--port", "$ApiPort", "--reload", "--reload-dir", "backend/src", "--no-access-log"
    ) $root
    $apiReady = $false
    $readyUri = "http://127.0.0.1:$ApiPort/api/v1/health/ready"
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($null -eq (Get-MatchingProcess $records[0])) {
            throw "The host API exited before readiness. Check runtime/host-dev logs."
        }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $readyUri -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                $apiReady = $true
                break
            }
        } catch {
            # Startup connection errors and bounded 503 responses are retried below.
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $apiReady) {
        throw "The host API did not become schema-ready within 30 seconds. Run migration and inspect runtime/host-dev logs."
    }
    Start-HostProcess "outbox-relay" $python @("-m", "datariver.workers.outbox_relay") $root
    Start-HostProcess "upload-worker" $python @("-m", "datariver.workers.upload_worker") $root
    Start-HostProcess "upload-validation-worker" $python @(
        "-m", "datariver.workers.upload_validation"
    ) $root
    Start-HostProcess "governance-apply-worker" $python @(
        "-m", "datariver.workers.governance_apply"
    ) $root
    $viteWorkingDirectory = Join-Path $root "frontend"
    $viteFilePath = $npmCommand
    $viteArguments = @(
        "run", "dev", "--", "--host", "127.0.0.1", "--port", "$WebPort", "--strictPort"
    )
    # npm.cmd launches through cmd.exe, which cannot use a UNC directory as
    # its working directory. A checkout entered from WSL reaches PowerShell as
    # \\wsl.localhost\..., so let cmd's built-in pushd map that one process to a
    # temporary drive rather than falling back to C:\\Windows and reading an
    # unrelated package.json. Python processes keep their original directory.
    if ($viteWorkingDirectory.StartsWith("\\")) {
        $viteFilePath = Join-Path $env:SystemRoot "System32/cmd.exe"
        $viteArguments = @(
            "/d", "/s", "/c",
            "pushd `"$viteWorkingDirectory`" && call `"$npmCommand`" run dev -- --host 127.0.0.1 --port $WebPort --strictPort"
        )
        $viteWorkingDirectory = $env:SystemRoot
    }
    Start-HostProcess "vite" $viteFilePath $viteArguments $viteWorkingDirectory
    $records | ConvertTo-Json -Depth 3 | Set-Content -Encoding utf8 -LiteralPath $stateFile
    Start-Sleep -Seconds 3
    $failed = @(
        foreach ($record in $records) {
            if ($null -eq (Get-MatchingProcess $record)) {
                $record
            }
        }
    )
    if ($failed.Count -gt 0) {
        throw "One or more host-development processes exited during startup. Check runtime/host-dev logs."
    }
} catch {
    foreach ($record in $records) {
        $process = Get-MatchingProcess $record
        if ($null -ne $process) {
            Stop-ProcessTree $process
        }
    }
    throw
}

Show-Status
