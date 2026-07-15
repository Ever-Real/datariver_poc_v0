param(
    [Parameter(Mandatory = $true)]
    [string]$DataHubToken
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$secretsDirectory = Join-Path $root "secrets"
$envFile = Join-Path $root ".env"
$keycloakRuntimeDirectory = Join-Path $root "runtime/keycloak"

New-Item -ItemType Directory -Force -Path $secretsDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $keycloakRuntimeDirectory | Out-Null

if ($IsLinux -or $IsMacOS) {
    Get-ChildItem -LiteralPath $secretsDirectory -File | ForEach-Object {
        [IO.File]::SetUnixFileMode(
            $_.FullName,
            [IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite
        )
    }
    $existingRealm = Join-Path $keycloakRuntimeDirectory "datariver-realm.json"
    if (Test-Path -LiteralPath $existingRealm) {
        [IO.File]::SetUnixFileMode(
            $existingRealm,
            [IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite
        )
    }
}

function New-RandomSecret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    return [Convert]::ToBase64String($buffer)
}

function Write-Secret([string]$Name, [string]$Value) {
    $path = Join-Path $secretsDirectory $Name
    [IO.File]::WriteAllText($path, $Value, [Text.UTF8Encoding]::new($false))
    if ($IsLinux -or $IsMacOS) {
        [IO.File]::SetUnixFileMode(
            $path,
            [IO.UnixFileMode]::UserRead -bor
                [IO.UnixFileMode]::GroupRead -bor
                [IO.UnixFileMode]::OtherRead
        )
    }
}

function Get-OrCreateSecret([string]$Name, [int]$Bytes = 32) {
    $path = Join-Path $secretsDirectory $Name
    if ((Test-Path -LiteralPath $path) -and (Get-Item -LiteralPath $path).Length -gt 0) {
        return [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
    }
    $value = New-RandomSecret $Bytes
    Write-Secret $Name $value
    return $value
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $root ".env.example") -Destination $envFile
}

$postgresPassword = Get-OrCreateSecret "postgres_password"
$postgresAppPassword = Get-OrCreateSecret "postgres_app_password"
$postgresRelayPassword = Get-OrCreateSecret "postgres_relay_password"
$postgresUploadPassword = Get-OrCreateSecret "postgres_upload_password"
$postgresGovernancePassword = Get-OrCreateSecret "postgres_governance_password"
$postgresBootstrapPassword = Get-OrCreateSecret "postgres_bootstrap_password"
$keycloakDatabasePassword = Get-OrCreateSecret "keycloak_db_password"
$airflowDatabasePassword = Get-OrCreateSecret "airflow_db_password"
$airflowApiSecret = Get-OrCreateSecret "airflow_api_secret" 48
$airflowClientSecret = Get-OrCreateSecret "airflow_client_secret"
$airflowAdminPassword = Get-OrCreateSecret "airflow_admin_password" 24
$keycloakDemoPassword = Get-OrCreateSecret "keycloak_demo_password" 18
$keycloakAdminPassword = Get-OrCreateSecret "keycloak_admin_password" 24
$cachePassword = Get-OrCreateSecret "valkey_cache_password"
$queuePassword = Get-OrCreateSecret "valkey_queue_password"
$s3AccessKeyPath = Join-Path $secretsDirectory "s3_access_key"
if ((Test-Path -LiteralPath $s3AccessKeyPath) -and
    (Get-Item -LiteralPath $s3AccessKeyPath).Length -gt 0) {
    $s3AccessKey = [IO.File]::ReadAllText($s3AccessKeyPath, [Text.Encoding]::UTF8)
} else {
    $s3AccessKey = (New-RandomSecret 18).Replace("/", "A").Replace("+", "B").TrimEnd("=")
    Write-Secret "s3_access_key" $s3AccessKey
}
$s3SecretKey = Get-OrCreateSecret "s3_secret_key" 36

Write-Secret "datahub_token" $DataHubToken

$seaweedConfig = @{
    identities = @(
        @{
            name = "datariver"
            credentials = @(@{ accessKey = $s3AccessKey; secretKey = $s3SecretKey })
            actions = @("Admin", "Read", "Write", "List", "Tagging")
        }
    )
} | ConvertTo-Json -Depth 6
Write-Secret "seaweed_s3_config.json" $seaweedConfig

$realmTemplate = [IO.File]::ReadAllText(
    (Join-Path $root "infra/keycloak/datariver-realm.template.json"),
    [Text.Encoding]::UTF8
)
$realmDocument = $realmTemplate.Replace(
    "__DEMO_PASSWORD__", $keycloakDemoPassword
).Replace("__AIRFLOW_CLIENT_SECRET__", $airflowClientSecret)
[IO.File]::WriteAllText(
    (Join-Path $keycloakRuntimeDirectory "datariver-realm.json"),
    $realmDocument,
    [Text.UTF8Encoding]::new($false)
)
if ($IsLinux -or $IsMacOS) {
    $ownerDirectoryMode = [IO.UnixFileMode]::UserRead -bor
        [IO.UnixFileMode]::UserWrite -bor [IO.UnixFileMode]::UserExecute
    $readOnlyFileMode = [IO.UnixFileMode]::UserRead -bor
        [IO.UnixFileMode]::GroupRead -bor [IO.UnixFileMode]::OtherRead
    [IO.File]::SetUnixFileMode($secretsDirectory, $ownerDirectoryMode)
    [IO.File]::SetUnixFileMode($keycloakRuntimeDirectory, $ownerDirectoryMode)
    [IO.File]::SetUnixFileMode(
        (Join-Path $keycloakRuntimeDirectory "datariver-realm.json"),
        $readOnlyFileMode
    )
}

Write-Output "Bootstrap files created. Keep the secrets directory private and out of Git."
