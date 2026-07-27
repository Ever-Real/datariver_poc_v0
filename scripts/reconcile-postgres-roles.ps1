param(
    [string]$EnvFile = $(if ($env:DATARIVER_ENV_FILE) { $env:DATARIVER_ENV_FILE } else { ".env" })
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedEnvFile = if ([IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile
} else {
    Join-Path $root $EnvFile
}
if (-not (Test-Path -LiteralPath $resolvedEnvFile -PathType Leaf)) {
    throw "DataRiver environment file not found: $resolvedEnvFile"
}

& docker compose --env-file $resolvedEnvFile -f (Join-Path $root "compose.yaml") `
    exec -T postgres sh -ec `
    'export PGPASSWORD="$(tr -d "\r\n" </run/secrets/postgres_password)"; exec sh /docker-entrypoint-initdb.d/010_roles.sh'
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL role reconciliation failed with exit code $LASTEXITCODE."
}

Write-Output "PostgreSQL runtime roles reconciled with the mounted secret files."
