param(
    [string]$EnvFile = $(if ($env:DATARIVER_ENV_FILE) {
        $env:DATARIVER_ENV_FILE
    } else {
        ".env"
    }),
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ComposeArguments
)

$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath Variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$resolvedEnvFile = if ([IO.Path]::IsPathRooted($EnvFile)) {
    $EnvFile
} else {
    Join-Path $root $EnvFile
}
if (-not (Test-Path -LiteralPath $resolvedEnvFile -PathType Leaf)) {
    throw "Missing deployment environment file: $resolvedEnvFile"
}

$connectorNetwork = "datariver-connectors"
$pattern = "^DATARIVER_CONNECTOR_NETWORK=(.*)$"
foreach ($line in [IO.File]::ReadAllLines($resolvedEnvFile, [Text.Encoding]::UTF8)) {
    $networkMatch = [Regex]::Match(
        $line,
        $pattern,
        [Text.RegularExpressions.RegexOptions]::CultureInvariant
    )
    if ($networkMatch.Success) {
        $connectorNetwork = $networkMatch.Groups[1].Value.Trim()
    }
}
if ([string]::IsNullOrWhiteSpace($connectorNetwork) -or
    $connectorNetwork.StartsWith("-", [StringComparison]::Ordinal) -or
    $connectorNetwork -in @(".", "..") -or
    -not [Regex]::IsMatch(
        $connectorNetwork,
        "^[A-Za-z0-9_.-]+$",
        [Text.RegularExpressions.RegexOptions]::CultureInvariant
    )) {
    throw "DATARIVER_CONNECTOR_NETWORK contains unsupported characters."
}

$stateChangingCommands = @("up", "run", "create", "start")
$requiresConnectorNetwork = $false
foreach ($argument in $ComposeArguments) {
    if ($argument -cin $stateChangingCommands) {
        $requiresConnectorNetwork = $true
        break
    }
}
if ($requiresConnectorNetwork) {
    $inspectArguments = @("network", "inspect", $connectorNetwork)
    & docker $inspectArguments *> $null
    if ($LASTEXITCODE -ne 0) {
        $createArguments = @("network", "create", "--driver", "bridge", $connectorNetwork)
        & docker $createArguments *> $null
        if ($LASTEXITCODE -ne 0) {
            & docker $inspectArguments *> $null
            if ($LASTEXITCODE -ne 0) {
                throw "Could not create connector network: $connectorNetwork"
            }
        } else {
            Write-Output "Created connector network: $connectorNetwork"
        }
    }
}

$env:DATARIVER_ENV_FILE = $resolvedEnvFile
$dockerComposeArguments = @("compose", "--env-file", $resolvedEnvFile) + $ComposeArguments
& docker $dockerComposeArguments
exit $LASTEXITCODE
