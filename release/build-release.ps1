[CmdletBinding()]
param(
	[string]$Version = '1.0.0',
	[string]$OutputDirectory,
	[switch]$SkipNativeBuild
)

$ErrorActionPreference = 'Stop'

$releaseRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryRoot = Split-Path -Parent $releaseRoot
if (-not $OutputDirectory) {
	$OutputDirectory = Join-Path $releaseRoot 'out'
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)

function Copy-PackageFile {
	param(
		[string]$Source,
		[string]$Destination,
		[switch]$Required
	)

	if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
		if ($Required) { throw "Required release input is missing: $Source" }
		return $false
	}
	$parent = Split-Path -Parent $Destination
	New-Item -ItemType Directory -Force -Path $parent | Out-Null
	Copy-Item -LiteralPath $Source -Destination $Destination -Force
	return $true
}

function Copy-PackageDirectory {
	param(
		[string]$Source,
		[string]$Destination,
		[switch]$Required
	)

	if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
		if ($Required) { throw "Required release directory is missing: $Source" }
		return $false
	}
	New-Item -ItemType Directory -Force -Path $Destination | Out-Null
	Get-ChildItem -LiteralPath $Source -Recurse -File | Where-Object {
		$relative = $_.FullName.Substring($Source.TrimEnd('\').Length).TrimStart('\')
		$relative -notmatch '^(tests?|__pycache__|\.pytest_cache|build|dist|\.test-target)(\\|$)' -and
		$_.Extension -notin @('.pyc', '.pyo')
	} | ForEach-Object {
		$relative = $_.FullName.Substring($Source.TrimEnd('\').Length).TrimStart('\')
		$destinationPath = Join-Path $Destination $relative
		$destinationParent = Split-Path -Parent $destinationPath
		New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
		Copy-Item -LiteralPath $_.FullName -Destination $destinationPath -Force
	}
	return $true
}

function Assert-Hash {
	param(
		[string]$Path,
		[string]$Expected,
		[string]$Label
	)
	$actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
	if ($actual -ne $Expected.ToLowerInvariant()) {
		throw "$Label hash mismatch. Expected $Expected, got $actual."
	}
	return $actual
}

$manifestPath = Join-Path $repositoryRoot 'Installer\release-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
	throw "Release manifest is missing: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.release.version -ne $Version) {
	throw "Requested version $Version does not match manifest version $($manifest.release.version)."
}
if (-not $manifest.release.unsigned) {
	throw 'The v1 release must remain explicitly unsigned; refusing to package a signing claim.'
}

if (-not $SkipNativeBuild) {
	& (Join-Path $repositoryRoot 'Native Hook\build.ps1')
	if ($LASTEXITCODE -ne 0) { throw 'Native build failed.' }
}

$packageId = [string]$manifest.package.id
$stagingRoot = Join-Path $OutputDirectory "$packageId-staging"
$packageRoot = Join-Path $stagingRoot "Any-Gender Parenthook v$Version"
$zipPath = Join-Path $OutputDirectory "Any-Gender-Parenthook-v$Version-win64.zip"
$checksumPath = "$zipPath.sha256"
$provenancePath = Join-Path $OutputDirectory "Any-Gender-Parenthook-v$Version-provenance.json"

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
if (Test-Path -LiteralPath $stagingRoot) {
	Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
if (Test-Path -LiteralPath $checksumPath) { Remove-Item -LiteralPath $checksumPath -Force }
if (Test-Path -LiteralPath $provenancePath) { Remove-Item -LiteralPath $provenancePath -Force }
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null

$nativeProxy = Join-Path $repositoryRoot 'Native Hook\build\dxcompiler.dll'
$nativePayload = Join-Path $repositoryRoot 'Native Hook\build\AGP Native Hook\agp_parenthook.dll'
Copy-PackageFile $nativeProxy (Join-Path $packageRoot 'dxcompiler.dll') -Required | Out-Null
Copy-PackageFile $nativePayload (Join-Path $packageRoot 'AGP Native Hook\agp_parenthook.dll') -Required | Out-Null

$packageFiles = @(
	@{ Source = 'release\assets\Install AGP.bat'; Destination = 'Install AGP.bat' },
	@{ Source = 'release\assets\Uninstall AGP.bat'; Destination = 'Uninstall AGP.bat' },
	@{ Source = 'Installer\AGPInstaller.exe'; Destination = 'AGP-Installer.exe' },
	@{ Source = 'Installer\AGPUninstaller.exe'; Destination = 'AGP-Uninstaller.exe' },
	@{ Source = 'release\END_USER_README.md'; Destination = 'README.md' },
	@{ Source = 'release\RELEASE_NOTES.md'; Destination = 'RELEASE_NOTES.md' },
	@{ Source = 'Installer\release-manifest.json'; Destination = 'Installer\release-manifest.json' },
	@{ Source = 'Installer\install.ps1'; Destination = 'Installer\install.ps1' },
	@{ Source = 'Installer\uninstall.ps1'; Destination = 'Installer\uninstall.ps1' },
	@{ Source = 'LICENSE'; Destination = 'LICENSE' },
	@{ Source = 'PRIVACY.md'; Destination = 'PRIVACY.md' },
	@{ Source = 'SECURITY.md'; Destination = 'SECURITY.md' },
	@{ Source = 'SIGNING.md'; Destination = 'SIGNING.md' }
)
foreach ($mapping in $packageFiles) {
	$source = Join-Path $repositoryRoot $mapping.Source
	$destination = Join-Path $packageRoot $mapping.Destination
	Copy-PackageFile $source $destination -Required | Out-Null
}
Copy-PackageDirectory (Join-Path $repositoryRoot 'Installer\python') (Join-Path $packageRoot 'Installer\python') -Required | Out-Null
Copy-PackageDirectory (Join-Path $repositoryRoot 'Installer\powershell') (Join-Path $packageRoot 'Installer\powershell') -Required | Out-Null
Copy-PackageDirectory (Join-Path $repositoryRoot 'Installer\spec') (Join-Path $packageRoot 'Installer\spec') -Required | Out-Null

$forbiddenNames = @('native_test_mod', 'AGP Dynastic Priority', 'Lunacy', '.git', 'script_docs 1.19.0.6')
$forbiddenFound = Get-ChildItem -LiteralPath $packageRoot -Recurse -Force | Where-Object {
	$forbiddenNames -contains $_.Name
}
if ($forbiddenFound) {
	throw "Forbidden development content entered the package: $($forbiddenFound.Name -join ', ')"
}

$endUserRootFiles = @('AGP-Installer.exe', 'AGP-Uninstaller.exe', 'Install AGP.bat', 'Uninstall AGP.bat', 'README.md')
foreach ($relative in $endUserRootFiles) {
	if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $relative) -PathType Leaf)) {
		throw "End-user root entry is missing: $relative"
	}
}
$obsoleteNestedLaunchers = @(
	'Installer\AGPInstaller.exe',
	'Installer\AGPUninstaller.exe',
	'Installer\install.bat',
	'Installer\uninstall.bat',
	'release\README.md'
)
foreach ($relative in $obsoleteNestedLaunchers) {
	if (Test-Path -LiteralPath (Join-Path $packageRoot $relative)) {
		throw "Obsolete nested launcher entered the end-user package: $relative"
	}
}

$artifactByPath = @{}
foreach ($artifact in $manifest.artifacts) {
	$artifactByPath[[string]$artifact.relative_path] = $artifact
}
foreach ($entry in $artifactByPath.Keys) {
	$artifact = $artifactByPath[$entry]
	$packagedPath = Join-Path $packageRoot ($entry -replace '/', '\')
	if (-not (Test-Path -LiteralPath $packagedPath -PathType Leaf)) {
		throw "Manifest artifact is not present in the package: $entry"
	}
	Assert-Hash $packagedPath $artifact.sha256 $entry | Out-Null
}

$checksumLines = [System.Collections.Generic.List[string]]::new()
Get-ChildItem -LiteralPath $packageRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
	$relative = $_.FullName.Substring($packageRoot.Length).TrimStart('\').Replace('\', '/')
	$hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
	[void]$checksumLines.Add("$hash *$relative")
}
[System.IO.File]::WriteAllLines((Join-Path $packageRoot 'SHA256SUMS.txt'), $checksumLines, [System.Text.UTF8Encoding]::new($false))

Compress-Archive -Path (Join-Path $stagingRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText($checksumPath, "$zipHash *$(Split-Path -Leaf $zipPath)`n", [System.Text.UTF8Encoding]::new($false))

$commit = 'unavailable'
try {
	$commit = (& git -C $repositoryRoot rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
	if (-not $commit) { $commit = 'unavailable' }
} catch {
	$commit = 'unavailable'
}
$fileCount = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File).Count
$provenance = [ordered]@{
	'schema_version' = 1
	'kind' = 'agp_release_provenance'
	'release' = [ordered]@{
		'id' = $manifest.release.id
		'version' = $Version
		'channel' = $manifest.release.channel
		'unsigned' = $true
		'signing' = 'not_performed'
	}
	'source' = [ordered]@{
		repository = $manifest.release.source_repo
		commit = $commit
		workflow = 'release/build-release.ps1'
	}
	'artifact' = [ordered]@{
		file = (Split-Path -Leaf $zipPath)
		sha256 = $zipHash
		package_id = $packageId
		file_count = $fileCount
	}
	'safety' = [ordered]@{
		excluded = @('Native Hook/native_test_mod', 'AGP Dynastic Priority', '.git', 'Lunacy')
		credentials_used = $false
	}
}
$provenance | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $provenancePath -Encoding utf8

Write-Host "Created $zipPath"
Write-Host "SHA-256 $zipHash"
Write-Host "Created $checksumPath and $provenancePath"
