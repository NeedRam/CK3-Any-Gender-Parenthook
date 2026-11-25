[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$StageRoot,
    [string]$ArchivePath
)

$ErrorActionPreference = 'Stop'

function Resolve-ContainedPath {
    param([string]$BaseDirectory, [string]$Candidate, [string]$Label)
    $base = [IO.Path]::GetFullPath($BaseDirectory).TrimEnd('\') + '\'
    $resolved = [IO.Path]::GetFullPath($Candidate)
    if (-not $resolved.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label resolved outside its allowed directory: $resolved"
    }
    return $resolved
}

function Assert-HashAndSize {
    param([string]$Path, [string]$ExpectedHash, [int64]$ExpectedSize, [string]$Label)
    $item = Get-Item -LiteralPath $Path -Force
    $actualHash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $ExpectedHash.ToLowerInvariant() -or [int64]$item.Length -ne $ExpectedSize) {
        throw "$Label hash or size mismatch: $Path"
    }
}

$repository = [IO.Path]::GetFullPath($RepositoryRoot)
if (-not $StageRoot) { $StageRoot = Join-Path $repository 'Native Hook\build' }
$stageRoot = [IO.Path]::GetFullPath($StageRoot)
$manifestPath = Join-Path $repository 'Installer\release-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "Release manifest is missing: $manifestPath" }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$native = $manifest.native_release
if ($null -eq $native -or $native.version -ne '1.1.0' -or [string]::IsNullOrWhiteSpace([string]$native.archive_url)) { throw 'Pinned native release metadata is missing or unsupported.' }
$proxyArtifact = @($manifest.artifacts | Where-Object { $_.id -eq 'agp-proxy' }) | Select-Object -First 1
$payloadArtifact = @($manifest.artifacts | Where-Object { $_.id -eq 'agp-payload' }) | Select-Object -First 1
if ($null -eq $proxyArtifact -or $null -eq $payloadArtifact) { throw 'Pinned AGP artifacts are missing from the release manifest.' }

$cacheDirectory = Join-Path $stageRoot "published-v$($native.version)"
$cacheArchive = Join-Path $cacheDirectory "AGP.v$($native.version).Base.Files.Manual.Install.zip"
New-Item -ItemType Directory -Force -Path $cacheDirectory | Out-Null
if ($ArchivePath) {
    $sourceArchive = [IO.Path]::GetFullPath($ArchivePath)
    if (-not (Test-Path -LiteralPath $sourceArchive -PathType Leaf)) { throw "Supplied native archive is missing: $sourceArchive" }
    Assert-HashAndSize $sourceArchive ([string]$native.archive_sha256) ([int64](Get-Item -LiteralPath $sourceArchive).Length) 'Supplied native archive'
    if (-not (Test-Path -LiteralPath $cacheArchive -PathType Leaf)) {
        Copy-Item -LiteralPath $sourceArchive -Destination $cacheArchive -Force
    }
}
elseif (-not (Test-Path -LiteralPath $cacheArchive -PathType Leaf)) {
    $download = Join-Path $cacheDirectory ".native-$($native.version)-$PID.download"
    Resolve-ContainedPath $cacheDirectory $download 'Native archive download' | Out-Null
    try {
        Invoke-WebRequest -Uri ([string]$native.archive_url) -OutFile $download -UseBasicParsing
        Move-Item -LiteralPath $download -Destination $cacheArchive -Force
    }
    finally {
        if (Test-Path -LiteralPath $download) { Remove-Item -LiteralPath $download -Force }
    }
}
Assert-HashAndSize $cacheArchive ([string]$native.archive_sha256) ([int64](Get-Item -LiteralPath $cacheArchive).Length) 'Pinned native archive'

$extractDirectory = Join-Path $cacheDirectory ".native-$($native.version)-extract-$PID"
Resolve-ContainedPath $cacheDirectory $extractDirectory 'Native archive extraction' | Out-Null
if (Test-Path -LiteralPath $extractDirectory) { Remove-Item -LiteralPath $extractDirectory -Recurse -Force }
try {
    Expand-Archive -LiteralPath $cacheArchive -DestinationPath $extractDirectory -Force
    $proxy = @(Get-ChildItem -LiteralPath $extractDirectory -Recurse -File -Filter 'dxcompiler.dll')
    $payload = @(Get-ChildItem -LiteralPath $extractDirectory -Recurse -File -Filter 'agp_parenthook.dll')
    if ($proxy.Count -ne 1 -or $payload.Count -ne 1) { throw 'Pinned native archive must contain exactly one proxy and payload DLL.' }
    Assert-HashAndSize $proxy[0].FullName ([string]$proxyArtifact.sha256) ([int64]$proxyArtifact.size_bytes) 'Pinned AGP proxy'
    Assert-HashAndSize $payload[0].FullName ([string]$payloadArtifact.sha256) ([int64]$payloadArtifact.size_bytes) 'Pinned AGP payload'

    New-Item -ItemType Directory -Force -Path (Join-Path $stageRoot 'AGP Native Hook') | Out-Null
    $proxyTarget = Join-Path $stageRoot 'dxcompiler.dll'
    $payloadTarget = Join-Path $stageRoot 'AGP Native Hook\agp_parenthook.dll'
    foreach ($pair in @(
        @($proxy[0].FullName, $proxyTarget, [string]$proxyArtifact.sha256, [int64]$proxyArtifact.size_bytes, 'test proxy'),
        @($payload[0].FullName, $payloadTarget, [string]$payloadArtifact.sha256, [int64]$payloadArtifact.size_bytes, 'test payload')
    )) {
        $source, $destination, $expectedHash, $expectedSize, $label = $pair
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            Assert-HashAndSize $destination $expectedHash $expectedSize $label
        }
        elseif (Test-Path -LiteralPath $destination) {
            throw "$label destination is not a file: $destination"
        }
        else {
            Copy-Item -LiteralPath $source -Destination $destination -Force
            Assert-HashAndSize $destination $expectedHash $expectedSize $label
        }
    }
    [ordered]@{
        archive = $cacheArchive
        archive_sha256 = ([string]$native.archive_sha256).ToLowerInvariant()
        proxy = $proxyTarget
        proxy_sha256 = ([string]$proxyArtifact.sha256).ToLowerInvariant()
        payload = $payloadTarget
        payload_sha256 = ([string]$payloadArtifact.sha256).ToLowerInvariant()
    } | ConvertTo-Json -Depth 4
}
finally {
    if (Test-Path -LiteralPath $extractDirectory) { Remove-Item -LiteralPath $extractDirectory -Recurse -Force }
}
