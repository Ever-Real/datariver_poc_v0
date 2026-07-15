param(
    [string]$SnapshotName = "datariver_v0_3_reference_20260714",
    [string]$LegacyRepositoryRoot = (Join-Path $PSScriptRoot "../../datariver_v0_3"),
    [switch]$ManifestOnly
)

$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath($LegacyRepositoryRoot)
$gitDirectory = Join-Path $repoRoot ".git"
if (-not (Test-Path -LiteralPath $gitDirectory)) {
    throw "LegacyRepositoryRoot must reference the legacy Git repository: $repoRoot"
}
$legacyRoot = Join-Path $repoRoot "legacy"
$destination = Join-Path $legacyRoot $SnapshotName
$expectedPrefix = $legacyRoot.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar

if (-not $destination.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Snapshot destination must remain inside the repository legacy directory."
}

New-Item -ItemType Directory -Force -Path $destination | Out-Null

$copied = 0
$skippedMissing = 0

if (-not $ManifestOnly) {
    $files = @(
        & git -C $repoRoot -c core.quotepath=false ls-files --cached --others --exclude-standard
    ) | Sort-Object -Unique

    if ($LASTEXITCODE -ne 0) {
        throw "git ls-files failed with exit code $LASTEXITCODE."
    }

    foreach ($relativePath in $files) {
        $normalized = $relativePath.Replace("\", "/")
        if (
            $normalized.StartsWith("legacy/") -or
            $normalized.StartsWith(".antigravitycli/") -or
            $normalized.StartsWith("datariver_v1/")
        ) {
            continue
        }

        $source = Join-Path $repoRoot $relativePath
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            $skippedMissing++
            continue
        }

        $target = Join-Path $destination $relativePath
        $targetDirectory = Split-Path -Parent $target
        New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
        $copied++
    }
}

$manifestName = "REFERENCE_MANIFEST.json"
$manifestPath = Join-Path $destination $manifestName
$manifestFiles = @(
    Get-ChildItem -LiteralPath $destination -Recurse -File |
        Where-Object { $_.FullName -ne $manifestPath } |
        Sort-Object FullName |
        ForEach-Object {
            $relative = $_.FullName.Substring($destination.Length).TrimStart("\", "/").Replace("\", "/")
            [PSCustomObject][ordered]@{
                path = $relative
                bytes = $_.Length
                sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
)
$manifest = [ordered]@{
    format_version = 1
    snapshot_name = $SnapshotName
    hash_algorithm = "SHA-256"
    file_count = $manifestFiles.Count
    total_bytes = ($manifestFiles | Measure-Object -Property bytes -Sum).Sum
    files = $manifestFiles
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8

[PSCustomObject]@{
    Destination = $destination
    Copied = $copied
    SkippedMissing = $skippedMissing
    ManifestFiles = $manifestFiles.Count
    Manifest = $manifestPath
}
