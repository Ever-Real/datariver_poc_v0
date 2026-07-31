param(
    [string]$DataHubToken,
    [string]$DataHubTokenFile,
    [string]$DataHubBaseUrl,
    [string]$DataHubEmbedOrigin,
    [string]$WebPublicOrigin = "http://localhost:8080",
    [switch]$HostDevelopment,
    [switch]$EnableCatalogExportWorker,
    [switch]$EnableKnowledgeSourceWorker
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).ProviderPath
$secretsDirectory = Join-Path $root "secrets"
$envFile = Join-Path $root ".env"
$runtimeDirectory = Join-Path $root "runtime"
$keycloakRuntimeDirectory = Join-Path $runtimeDirectory "keycloak"
$qualityRuntimeDirectory = Join-Path $runtimeDirectory "quality"
$qualitySourceSecretDirectory = Join-Path $secretsDirectory "quality-sources"
$knowledgeStudioRuntimeDirectory = Join-Path $runtimeDirectory "knowledge-studio"
$knowledgeStudioSourceSecretDirectory = Join-Path $secretsDirectory "knowledge-studio-sources"
$retentionControlFile = Join-Path $runtimeDirectory "retention-execution.enabled"
$nativeWindows = [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [Runtime.InteropServices.OSPlatform]::Windows
)

function Test-ReparsePoint([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    return [bool]((Get-Item -Force -LiteralPath $Path).Attributes -band
        [IO.FileAttributes]::ReparsePoint)
}

$managedPaths = @(
    $envFile,
    $secretsDirectory,
    $runtimeDirectory,
    $keycloakRuntimeDirectory,
    $qualityRuntimeDirectory,
    $qualitySourceSecretDirectory,
    $knowledgeStudioRuntimeDirectory,
    $knowledgeStudioSourceSecretDirectory,
    (Join-Path $keycloakRuntimeDirectory "datariver-realm.json"),
    $retentionControlFile
)
foreach ($managedPath in $managedPaths) {
    if (Test-ReparsePoint $managedPath) {
        throw "Bootstrap refuses reparse points for managed paths."
    }
}
if (Test-Path -LiteralPath $secretsDirectory -PathType Container) {
    foreach ($existingSecret in Get-ChildItem -Force -LiteralPath $secretsDirectory) {
        if ([bool]($existingSecret.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Bootstrap refuses reparse points in the secrets directory."
        }
    }
}

$dataHubTokenPath = Join-Path $secretsDirectory "datahub_token"
$dataHubTokenSourcePath = $null
if ($PSBoundParameters.ContainsKey("DataHubToken")) {
    throw "DataHub token values are not accepted as process arguments; use an approved token file."
}
if ($PSBoundParameters.ContainsKey("DataHubTokenFile")) {
    if (-not (Test-Path -LiteralPath $DataHubTokenFile -PathType Leaf) -or
        (Get-Item -LiteralPath $DataHubTokenFile).Length -eq 0) {
        throw "DataHub token file must be an existing non-empty regular file."
    }
    if (Test-ReparsePoint $DataHubTokenFile) {
        throw "DataHub token file must not be a reparse point."
    }
    $dataHubTokenSourcePath = (Resolve-Path -LiteralPath $DataHubTokenFile).ProviderPath
    try {
        $tokenProbe = [IO.File]::OpenRead($dataHubTokenSourcePath)
        $tokenProbe.Dispose()
    } catch {
        throw "DataHub token file must be readable before bootstrap creates any state."
    }
    if ((Test-Path -LiteralPath $dataHubTokenPath -PathType Leaf) -and
        $dataHubTokenSourcePath -eq
            (Resolve-Path -LiteralPath $dataHubTokenPath).ProviderPath) {
        $dataHubTokenSourcePath = $null
    }
} elseif (-not (Test-Path -LiteralPath $dataHubTokenPath -PathType Leaf) -or
    (Get-Item -LiteralPath $dataHubTokenPath).Length -eq 0) {
    throw "DataHub token file is required. Install it at secrets/datahub_token or use -DataHubTokenFile with an approved file path."
}

function Get-BootstrapEnvValue([string]$Name) {
    $pattern = "^$([Regex]::Escape($Name))=(.*)$"
    $value = $null
    foreach ($line in [IO.File]::ReadAllLines($envFile, [Text.Encoding]::UTF8)) {
        if ($line -match $pattern) {
            $value = $Matches[1].Trim()
        }
    }
    return $value
}

function Test-BootstrapEnvTrue([string]$Name) {
    return [string]::Equals(
        (Get-BootstrapEnvValue $Name),
        "true",
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Test-BootstrapEnvNonEmpty([string]$Name) {
    return -not [string]::IsNullOrWhiteSpace((Get-BootstrapEnvValue $Name))
}

function Test-KnowledgeInferenceReady {
    $localReady = (Test-BootstrapEnvTrue "LOCAL_OLLAMA_CHAT_ENABLED") -and
        (Test-BootstrapEnvTrue "LOCAL_OLLAMA_EMBEDDING_ENABLED") -and
        (Test-BootstrapEnvNonEmpty "LOCAL_OLLAMA_CHAT_BASE_URL") -and
        (Test-BootstrapEnvNonEmpty "LOCAL_OLLAMA_CHAT_MODEL") -and
        (Test-BootstrapEnvNonEmpty "LOCAL_OLLAMA_EMBEDDING_BASE_URL") -and
        (Test-BootstrapEnvNonEmpty "LOCAL_OLLAMA_EMBEDDING_MODEL")
    $intranetReady =
        (Test-BootstrapEnvTrue "INTRANET_OPENAI_COMPATIBLE_CHAT_ENABLED") -and
        (Test-BootstrapEnvTrue "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_ENABLED") -and
        (Test-BootstrapEnvNonEmpty "INTRANET_OPENAI_COMPATIBLE_ALLOWED_HOSTS") -and
        (Test-BootstrapEnvNonEmpty "INTRANET_OPENAI_COMPATIBLE_CHAT_BASE_URL") -and
        (Test-BootstrapEnvNonEmpty "INTRANET_OPENAI_COMPATIBLE_CHAT_MODEL") -and
        (Test-BootstrapEnvNonEmpty "INTRANET_OPENAI_COMPATIBLE_CHAT_API_KEY_SECRET_REF") -and
        (Test-BootstrapEnvNonEmpty "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_BASE_URL") -and
        (Test-BootstrapEnvNonEmpty "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_MODEL") -and
        (Test-BootstrapEnvNonEmpty "INTRANET_OPENAI_COMPATIBLE_EMBEDDING_API_KEY_SECRET_REF")
    return $localReady -or $intranetReady
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $root ".env.example") -Destination $envFile
}
if ($EnableKnowledgeSourceWorker -and -not (Test-KnowledgeInferenceReady)) {
    throw "EnableKnowledgeSourceWorker requires one complete Chat+Embedding pair in .env (local Ollama or intranet OpenAI-compatible)."
}

function Set-OwnerOnlyWindowsAcl([string]$Path, [switch]$Directory) {
    if (-not $nativeWindows) {
        return
    }
    $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
    if ($null -eq $owner) {
        throw "The current Windows user has no security identifier."
    }
    $system = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
    $acl = if ($Directory) {
        [Security.AccessControl.DirectorySecurity]::new()
    } else {
        [Security.AccessControl.FileSecurity]::new()
    }
    $acl.SetAccessRuleProtection($true, $false)
    $acl.SetOwner($owner)
    $inheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    } else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    foreach ($principal in @($owner, $system)) {
        $acl.AddAccessRule(
            [Security.AccessControl.FileSystemAccessRule]::new(
                $principal,
                [Security.AccessControl.FileSystemRights]::FullControl,
                $inheritance,
                [Security.AccessControl.PropagationFlags]::None,
                [Security.AccessControl.AccessControlType]::Allow
            )
        )
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
}

New-Item -ItemType Directory -Force -Path $secretsDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $keycloakRuntimeDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $qualityRuntimeDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $qualitySourceSecretDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $knowledgeStudioRuntimeDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $knowledgeStudioSourceSecretDirectory | Out-Null
Set-OwnerOnlyWindowsAcl -Path $secretsDirectory -Directory
Set-OwnerOnlyWindowsAcl -Path $keycloakRuntimeDirectory -Directory
Set-OwnerOnlyWindowsAcl -Path $qualityRuntimeDirectory -Directory
Set-OwnerOnlyWindowsAcl -Path $qualitySourceSecretDirectory -Directory
Set-OwnerOnlyWindowsAcl -Path $knowledgeStudioRuntimeDirectory -Directory
Set-OwnerOnlyWindowsAcl -Path $knowledgeStudioSourceSecretDirectory -Directory
if ($IsLinux -or $IsMacOS) {
    [IO.File]::SetUnixFileMode(
        $secretsDirectory,
        [IO.UnixFileMode]::UserRead -bor
            [IO.UnixFileMode]::UserWrite -bor
            [IO.UnixFileMode]::UserExecute
    )
}
if (-not (Test-Path -LiteralPath $retentionControlFile)) {
    [IO.File]::WriteAllText(
        $retentionControlFile,
        "DISABLED`n",
        [Text.UTF8Encoding]::new($false)
    )
}

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
} elseif ($nativeWindows) {
    Get-ChildItem -LiteralPath $secretsDirectory -File | ForEach-Object {
        Set-OwnerOnlyWindowsAcl -Path $_.FullName
    }
    $existingRealm = Join-Path $keycloakRuntimeDirectory "datariver-realm.json"
    if (Test-Path -LiteralPath $existingRealm) {
        Set-OwnerOnlyWindowsAcl -Path $existingRealm
    }
}

function New-RandomSecret([int]$Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    } finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($buffer)
}

function Write-Secret([string]$Name, [string]$Value) {
    $path = Join-Path $secretsDirectory $Name
    $temporaryPath = Join-Path $secretsDirectory ".$Name.tmp.$([Guid]::NewGuid().ToString('N'))"
    if (Test-Path -LiteralPath $path) {
        (Get-Item -LiteralPath $path).IsReadOnly = $false
    }
    try {
        [IO.File]::WriteAllText($temporaryPath, $Value, [Text.UTF8Encoding]::new($false))
        if ((Get-Item -LiteralPath $temporaryPath).Length -eq 0) {
            throw "Refusing to install an empty secret."
        }
        if ($IsLinux -or $IsMacOS) {
            [IO.File]::SetUnixFileMode(
                $temporaryPath,
                [IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite
            )
        } elseif ($nativeWindows) {
            Set-OwnerOnlyWindowsAcl -Path $temporaryPath
        }
        Move-Item -Force -LiteralPath $temporaryPath -Destination $path
    } finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -Force -LiteralPath $temporaryPath
        }
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

function Set-EnvValue([string]$Name, [string]$Value) {
    $lines = [Collections.Generic.List[string]]::new()
    $lines.AddRange([string[]][IO.File]::ReadAllLines($envFile, [Text.Encoding]::UTF8))
    $pattern = "^$([Regex]::Escape($Name))="
    $updated = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match $pattern) {
            $lines[$index] = "$Name=$Value"
            $updated = $true
        }
    }
    if (-not $updated) {
        $lines.Add("$Name=$Value")
    }
    [IO.File]::WriteAllLines($envFile, $lines, [Text.UTF8Encoding]::new($false))
}

$postgresPassword = Get-OrCreateSecret "postgres_password"
$postgresAppPassword = Get-OrCreateSecret "postgres_app_password"
$postgresRelayPassword = Get-OrCreateSecret "postgres_relay_password"
$postgresUploadPassword = Get-OrCreateSecret "postgres_upload_password"
$postgresGovernancePassword = Get-OrCreateSecret "postgres_governance_password"
$postgresKnowledgePassword = Get-OrCreateSecret "postgres_knowledge_password"
$postgresKnowledgeIngestionPassword = Get-OrCreateSecret "postgres_knowledge_ingestion_password"
$postgresQualityPassword = Get-OrCreateSecret "postgres_quality_password"
$postgresCatalogProfilePassword = Get-OrCreateSecret "postgres_catalog_profile_password"
$postgresExportPassword = Get-OrCreateSecret "postgres_export_password"
$postgresRetentionSchedulerPassword = Get-OrCreateSecret "postgres_retention_scheduler_password"
$postgresArchivePassword = Get-OrCreateSecret "postgres_archive_password"
$postgresBootstrapPassword = Get-OrCreateSecret "postgres_bootstrap_password"
$keycloakDatabasePassword = Get-OrCreateSecret "keycloak_db_password"
$airflowDatabasePassword = Get-OrCreateSecret "airflow_db_password"
$airflowApiSecret = Get-OrCreateSecret "airflow_api_secret" 48
$airflowClientSecret = Get-OrCreateSecret "airflow_client_secret"
$qualityDispatchClientSecret = Get-OrCreateSecret "quality_dispatch_client_secret"
$identityAdminClientSecret = Get-OrCreateSecret "keycloak_identity_admin_client_secret"
$airflowAdminPassword = Get-OrCreateSecret "airflow_admin_password" 24
$keycloakDemoPassword = Get-OrCreateSecret "keycloak_demo_password" 18
$keycloakAdminPassword = Get-OrCreateSecret "keycloak_admin_password" 24
$grafanaAdminPassword = Get-OrCreateSecret "grafana_admin_password" 24
$legacyCacheSecret = Join-Path $secretsDirectory "valkey_cache_password"
$redisCacheSecret = Join-Path $secretsDirectory "redis_cache_password"
if (-not (Test-Path -LiteralPath $redisCacheSecret) -and
    (Test-Path -LiteralPath $legacyCacheSecret)) {
    Copy-Item -LiteralPath $legacyCacheSecret -Destination $redisCacheSecret
    if ($IsLinux -or $IsMacOS) {
        [IO.File]::SetUnixFileMode(
            $redisCacheSecret,
            [IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite
        )
    } elseif ($nativeWindows) {
        Set-OwnerOnlyWindowsAcl -Path $redisCacheSecret
    }
}
$legacyDeliverySecret = Join-Path $secretsDirectory "valkey_queue_password"
$redisDeliverySecret = Join-Path $secretsDirectory "redis_delivery_password"
if (-not (Test-Path -LiteralPath $redisDeliverySecret) -and
    (Test-Path -LiteralPath $legacyDeliverySecret)) {
    Copy-Item -LiteralPath $legacyDeliverySecret -Destination $redisDeliverySecret
    if ($IsLinux -or $IsMacOS) {
        [IO.File]::SetUnixFileMode(
            $redisDeliverySecret,
            [IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite
        )
    } elseif ($nativeWindows) {
        Set-OwnerOnlyWindowsAcl -Path $redisDeliverySecret
    }
}
$cachePassword = Get-OrCreateSecret "redis_cache_password"
$queuePassword = Get-OrCreateSecret "redis_delivery_password"
$intranetLlmChatApiKey = Get-OrCreateSecret "intranet_llm_chat_api_key"
$intranetLlmEmbeddingApiKey = Get-OrCreateSecret "intranet_llm_embedding_api_key"
$intranetLlmRerankerApiKey = Get-OrCreateSecret "intranet_llm_reranker_api_key"
$s3AccessKeyPath = Join-Path $secretsDirectory "s3_access_key"
if ((Test-Path -LiteralPath $s3AccessKeyPath) -and
    (Get-Item -LiteralPath $s3AccessKeyPath).Length -gt 0) {
    $s3AccessKey = [IO.File]::ReadAllText($s3AccessKeyPath, [Text.Encoding]::UTF8)
} else {
    $s3AccessKey = (New-RandomSecret 18).Replace("/", "A").Replace("+", "B").TrimEnd("=")
    Write-Secret "s3_access_key" $s3AccessKey
}
$s3SecretKey = Get-OrCreateSecret "s3_secret_key" 36
$s3ExportAccessKeyPath = Join-Path $secretsDirectory "s3_export_access_key"
if ((Test-Path -LiteralPath $s3ExportAccessKeyPath) -and
    (Get-Item -LiteralPath $s3ExportAccessKeyPath).Length -gt 0) {
    $s3ExportAccessKey = [IO.File]::ReadAllText($s3ExportAccessKeyPath, [Text.Encoding]::UTF8)
} else {
    $s3ExportAccessKey = (New-RandomSecret 18).Replace("/", "A").Replace("+", "B").TrimEnd("=")
    Write-Secret "s3_export_access_key" $s3ExportAccessKey
}
$s3ExportSecretKey = Get-OrCreateSecret "s3_export_secret_key" 36
$s3KnowledgeAccessKeyPath = Join-Path $secretsDirectory "s3_knowledge_access_key"
if ((Test-Path -LiteralPath $s3KnowledgeAccessKeyPath) -and
    (Get-Item -LiteralPath $s3KnowledgeAccessKeyPath).Length -gt 0) {
    $s3KnowledgeAccessKey = [IO.File]::ReadAllText(
        $s3KnowledgeAccessKeyPath,
        [Text.Encoding]::UTF8
    )
} else {
    $s3KnowledgeAccessKey = (New-RandomSecret 18).Replace(
        "/",
        "A"
    ).Replace("+", "B").TrimEnd("=")
    Write-Secret "s3_knowledge_access_key" $s3KnowledgeAccessKey
}
$s3KnowledgeSecretKey = Get-OrCreateSecret "s3_knowledge_secret_key" 36
$s3ArchiveAccessKeyPath = Join-Path $secretsDirectory "s3_archive_access_key"
if ((Test-Path -LiteralPath $s3ArchiveAccessKeyPath) -and
    (Get-Item -LiteralPath $s3ArchiveAccessKeyPath).Length -gt 0) {
    $s3ArchiveAccessKey = [IO.File]::ReadAllText($s3ArchiveAccessKeyPath, [Text.Encoding]::UTF8)
} else {
    $s3ArchiveAccessKey = (New-RandomSecret 18).Replace("/", "A").Replace("+", "B").TrimEnd("=")
    Write-Secret "s3_archive_access_key" $s3ArchiveAccessKey
}
$s3ArchiveSecretKey = Get-OrCreateSecret "s3_archive_secret_key" 36

if ($null -ne $dataHubTokenSourcePath) {
    Write-Secret "datahub_token" (
        [IO.File]::ReadAllText($dataHubTokenSourcePath, [Text.Encoding]::UTF8)
    )
}

if ($HostDevelopment) {
    if (-not $PSBoundParameters.ContainsKey("WebPublicOrigin")) {
        $WebPublicOrigin = "http://localhost:38102"
    }
    Set-EnvValue "APP_PUBLIC_ORIGIN" $WebPublicOrigin
    Set-EnvValue "APP_CORS_ORIGINS" $WebPublicOrigin
    Set-EnvValue "API_PORT" "38101"
    Set-EnvValue "WEB_PORT" "38102"
    Set-EnvValue "POSTGRES_PORT" "5432"
    Set-EnvValue "KEYCLOAK_PORT" "18081"
    Set-EnvValue "APISIX_PORT" "9080"
    Set-EnvValue "OIDC_ISSUER" "http://localhost:18081/realms/datariver"
    Set-EnvValue "OIDC_PUBLIC_AUTHORITY" "http://localhost:18081/realms/datariver"
    Set-EnvValue "OIDC_PUBLIC_ORIGIN" "http://localhost:18081"
    Set-EnvValue "IDENTITY_ADMIN_ENABLED" "true"
    Set-EnvValue "IDENTITY_ADMIN_BASE_URL" "http://keycloak:8080"
    Set-EnvValue "IDENTITY_ADMIN_CLIENT_SECRET_REF" "file:/run/secrets/keycloak_identity_admin_client_secret"
    Set-EnvValue "IDENTITY_PASSWORD_CHANGE_ACTION_ENABLED" "true"
}
if ($PSBoundParameters.ContainsKey("DataHubBaseUrl") -and $DataHubBaseUrl.Length -gt 0) {
    Set-EnvValue "DATAHUB_BASE_URL" $DataHubBaseUrl
}
if ($PSBoundParameters.ContainsKey("DataHubEmbedOrigin") -and $DataHubEmbedOrigin.Length -gt 0) {
    $embedUri = [Uri]$DataHubEmbedOrigin
    if (-not $embedUri.IsAbsoluteUri -or $embedUri.UserInfo.Length -gt 0 -or
        $embedUri.AbsolutePath -notin @("", "/") -or $embedUri.Query.Length -gt 0 -or
        $embedUri.Fragment.Length -gt 0) {
        throw "DataHubEmbedOrigin must be one credential-free origin without a path, query, or fragment."
    }
    Set-EnvValue "DATAHUB_EMBED_BASE_URL" $embedUri.AbsoluteUri.TrimEnd("/")
    Set-EnvValue "DATAHUB_EMBED_ENABLED" "true"
}
if ($EnableCatalogExportWorker) {
    Set-EnvValue "EXPORT_DATABASE_URL" "postgresql+asyncpg://datariver_export@postgres:5432/datariver"
    Set-EnvValue "EXPORT_DATABASE_SECRET_REF" "file:/run/secrets/postgres_export_password"
    Set-EnvValue "S3_EXPORT_ACCESS_KEY_FILE" "/run/secrets/s3_export_access_key"
    Set-EnvValue "S3_EXPORT_SECRET_KEY_FILE" "/run/secrets/s3_export_secret_key"
    Set-EnvValue "CATALOG_EXPORT_WORKER_ENABLED" "true"
}
if ($EnableKnowledgeSourceWorker) {
    Set-EnvValue "KNOWLEDGE_DATABASE_URL" "postgresql+asyncpg://datariver_knowledge@postgres:5432/datariver"
    Set-EnvValue "KNOWLEDGE_DATABASE_SECRET_REF" "file:/run/secrets/postgres_knowledge_password"
    Set-EnvValue "S3_KNOWLEDGE_ACCESS_KEY_FILE" "/run/secrets/s3_knowledge_access_key"
    Set-EnvValue "S3_KNOWLEDGE_SECRET_KEY_FILE" "/run/secrets/s3_knowledge_secret_key"
    Set-EnvValue "KNOWLEDGE_SOURCE_WORKER_ENABLED" "true"
}

$realmTemplate = [IO.File]::ReadAllText(
    (Join-Path $root "infra/keycloak/datariver-realm.template.json"),
    [Text.Encoding]::UTF8
)
$realmDocument = $realmTemplate.Replace(
    "__DEMO_PASSWORD__", $keycloakDemoPassword
).Replace("__AIRFLOW_CLIENT_SECRET__", $airflowClientSecret
).Replace("__QUALITY_DISPATCH_CLIENT_SECRET__", $qualityDispatchClientSecret
).Replace("__IDENTITY_ADMIN_CLIENT_SECRET__", $identityAdminClientSecret
).Replace("__WEB_PUBLIC_ORIGIN__", $WebPublicOrigin)
$realmPath = Join-Path $keycloakRuntimeDirectory "datariver-realm.json"
if (Test-Path -LiteralPath $realmPath) {
    (Get-Item -LiteralPath $realmPath).IsReadOnly = $false
}
[IO.File]::WriteAllText(
    $realmPath,
    $realmDocument,
    [Text.UTF8Encoding]::new($false)
)
if ($IsLinux -or $IsMacOS) {
    $ownerDirectoryMode = [IO.UnixFileMode]::UserRead -bor
        [IO.UnixFileMode]::UserWrite -bor [IO.UnixFileMode]::UserExecute
    $readOnlyFileMode = [IO.UnixFileMode]::UserRead -bor
        [IO.UnixFileMode]::GroupRead -bor [IO.UnixFileMode]::OtherRead
    $readOnlyDirectoryMode = $readOnlyFileMode -bor
        [IO.UnixFileMode]::UserExecute -bor [IO.UnixFileMode]::GroupExecute -bor
        [IO.UnixFileMode]::OtherExecute
    [IO.File]::SetUnixFileMode($secretsDirectory, $ownerDirectoryMode)
    [IO.File]::SetUnixFileMode($keycloakRuntimeDirectory, $ownerDirectoryMode)
    [IO.File]::SetUnixFileMode($qualityRuntimeDirectory, $ownerDirectoryMode)
    [IO.File]::SetUnixFileMode($qualitySourceSecretDirectory, $ownerDirectoryMode)
    [IO.File]::SetUnixFileMode(
        $knowledgeStudioRuntimeDirectory,
        $readOnlyDirectoryMode
    )
    [IO.File]::SetUnixFileMode(
        $knowledgeStudioSourceSecretDirectory,
        $readOnlyDirectoryMode
    )
    foreach ($studioDirectory in @(
        $knowledgeStudioRuntimeDirectory,
        $knowledgeStudioSourceSecretDirectory
    )) {
        foreach ($studioFile in Get-ChildItem -Force -LiteralPath $studioDirectory) {
            if ([bool]($studioFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
                $studioFile.PSIsContainer) {
                throw "Knowledge Studio runtime inputs must be regular non-symlink files."
            }
            [IO.File]::SetUnixFileMode($studioFile.FullName, $readOnlyFileMode)
        }
    }
    [IO.File]::SetUnixFileMode(
        (Join-Path $keycloakRuntimeDirectory "datariver-realm.json"),
        $readOnlyFileMode
    )
    [IO.File]::SetUnixFileMode(
        $retentionControlFile,
        [IO.UnixFileMode]::UserRead -bor [IO.UnixFileMode]::UserWrite -bor
            [IO.UnixFileMode]::GroupRead -bor [IO.UnixFileMode]::OtherRead
    )
} elseif ($nativeWindows) {
    Set-OwnerOnlyWindowsAcl -Path $realmPath
}

Write-Output "Bootstrap files created. Keep the secrets directory private and out of Git."
