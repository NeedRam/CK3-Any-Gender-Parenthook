[CmdletBinding()]
param(
	[string]$Version = '1.1.1',
	[string]$OutputDirectory,
	[switch]$SkipNativeBuild,
	[switch]$AllowIncompleteValidation,
	[switch]$RequireCanonicalCi
)

$ErrorActionPreference = 'Stop'

$releaseRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repositoryRoot = Split-Path -Parent $releaseRoot
$isCanonicalCi = $env:GITHUB_ACTIONS -eq 'true'
if ($AllowIncompleteValidation -and $isCanonicalCi) {
    throw 'Canonical releases require completed acceptance; incomplete candidates are local-only.'
}
$validationArguments = @((Join-Path $releaseRoot 'check-release.py'))
if ($AllowIncompleteValidation) { $validationArguments += '--allow-incomplete' }
& python @validationArguments
if ($LASTEXITCODE -ne 0) { throw 'Release acceptance/profile validation failed.' }
if ($RequireCanonicalCi -and -not $isCanonicalCi) {
	throw 'Canonical release assembly is restricted to GitHub Actions.'
}
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
		$relative -notmatch '^(tests?|__pycache__|\.pytest_cache|\.venv|venv|build|dist|\.test-target)(\\|$)' -and
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
	throw 'Native rebuilds are forbidden for the 1.1.1 compatibility patch; use the verified published 1.1.0 archive.'
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$nativeRelease = $manifest.native_release
if ($null -eq $nativeRelease -or $nativeRelease.version -ne '1.1.0') { throw 'The pinned native release metadata is missing or unsupported.' }
$nativeCache = Join-Path $repositoryRoot ("Native Hook\build\published-v{0}\AGP.v{0}.Base.Files.Manual.Install.zip" -f $nativeRelease.version)
if (-not (Test-Path -LiteralPath $nativeCache -PathType Leaf)) {
	$nativeCache = Join-Path $OutputDirectory ".native-$($nativeRelease.version).zip"
	Invoke-WebRequest -Uri ([string]$nativeRelease.archive_url) -OutFile $nativeCache
}
Assert-Hash $nativeCache ([string]$nativeRelease.archive_sha256) 'Pinned native archive' | Out-Null
$nativeStage = Join-Path $OutputDirectory ".native-$($nativeRelease.version)-stage"
function Assert-ContainedPath {
	param(
		[string]$BaseDirectory,
		[string]$Candidate,
		[string]$Label
	)
	$baseResolved = [IO.Path]::GetFullPath($BaseDirectory).TrimEnd('\') + '\'
	$candidateResolved = [IO.Path]::GetFullPath($Candidate)
	if (-not $candidateResolved.StartsWith($baseResolved, [StringComparison]::OrdinalIgnoreCase)) {
		throw "$Label resolved outside its allowed directory: $candidateResolved"
	}
}
Assert-ContainedPath -BaseDirectory $OutputDirectory -Candidate $nativeStage -Label 'Native archive staging directory'
if (Test-Path -LiteralPath $nativeStage) { Remove-Item -LiteralPath $nativeStage -Recurse -Force }
Expand-Archive -LiteralPath $nativeCache -DestinationPath $nativeStage -Force
$nativeProxy = Get-ChildItem -LiteralPath $nativeStage -Recurse -File -Filter 'dxcompiler.dll' | Select-Object -First 1
$nativePayload = Get-ChildItem -LiteralPath $nativeStage -Recurse -File -Filter 'agp_parenthook.dll' | Select-Object -First 1
if ($null -eq $nativeProxy -or $null -eq $nativePayload) { throw 'Pinned native archive does not contain both required DLLs.' }
Assert-Hash $nativeProxy.FullName ([string]$manifest.artifacts[0].sha256) 'Pinned AGP proxy' | Out-Null
Assert-Hash $nativePayload.FullName ([string]$manifest.artifacts[1].sha256) 'Pinned AGP payload' | Out-Null
if ($nativeProxy.Length -ne [int64]$manifest.artifacts[0].size_bytes -or $nativePayload.Length -ne [int64]$manifest.artifacts[1].size_bytes) { throw 'Pinned native DLL size mismatch.' }
$legacyOutputs = @(
	"Any-Gender-Parenthook-v$Version-win64.zip",
	"Any-Gender-Parenthook-v$Version-win64.zip.sha256",
	"Any-Gender-Parenthook-v$Version-provenance.json"
)
foreach ($legacyName in $legacyOutputs) {
	$legacyPath = Join-Path $OutputDirectory $legacyName
	if (Test-Path -LiteralPath $legacyPath -PathType Leaf) {
		Remove-Item -LiteralPath $legacyPath -Force
	}
}
$nativeProxy = $nativeProxy.FullName
$nativePayload = $nativePayload.FullName
$forbiddenNames = @('native_test_mod', 'AGP Dynastic Priority', 'Lunacy', '.git', '.venv', 'venv', 'reference_files', 'profiles')
$commit = 'unavailable'
try {
	$commit = (& git -C $repositoryRoot rev-parse HEAD 2>$null | Select-Object -First 1).Trim()
	if (-not $commit) { $commit = 'unavailable' }
} catch {
	$commit = 'unavailable'
}
$toolchainPath = Join-Path $repositoryRoot 'Native Hook\toolchain.json'
$toolchain = Get-Content -LiteralPath $toolchainPath -Raw | ConvertFrom-Json

$packageDefinitions = @(
	@{
		Id = 'manual'
		Name = "AGP v$Version Base Files (Manual Install)"
		Readme = 'release\README_MANUAL.md'
		Files = @()
		Directories = @()
		RequiredRootFiles = @('dxcompiler.dll', 'AGP Native Hook\agp_parenthook.dll', 'README.md', 'LICENSE')
		ForbiddenRootFiles = @('AGP-Installer.exe', 'AGP-Uninstaller.exe', 'Install AGP.bat', 'Uninstall AGP.bat', 'Installer')
	}
	@{
		Id = 'batch'
		Name = "AGP v$Version Batch File Installer"
		Readme = 'release\README_BATCH.md'
		Files = @(
			@{ Source = 'release\assets\Install AGP.bat'; Destination = 'Install AGP.bat' },
			@{ Source = 'release\assets\Uninstall AGP.bat'; Destination = 'Uninstall AGP.bat' },
			@{ Source = 'Installer\release-manifest.json'; Destination = 'Installer\release-manifest.json' },
			@{ Source = 'Installer\install.ps1'; Destination = 'Installer\install.ps1' },
			@{ Source = 'Installer\uninstall.ps1'; Destination = 'Installer\uninstall.ps1' }
		)
		Directories = @(
			@{ Source = 'Installer\powershell'; Destination = 'Installer\powershell' }
		)
		RequiredRootFiles = @('dxcompiler.dll', 'AGP Native Hook\agp_parenthook.dll', 'Install AGP.bat', 'Uninstall AGP.bat', 'README.md', 'LICENSE')
		ForbiddenRootFiles = @('AGP-Installer.exe', 'AGP-Uninstaller.exe', 'Installer\python')
	}
	@{
		Id = 'exe'
		Name = "AGP v$Version EXE Installer"
		Readme = 'release\README_EXE.md'
		Files = @(
			@{ Source = 'Installer\AGPInstaller.exe'; Destination = 'AGP-Installer.exe' },
			@{ Source = 'Installer\AGPUninstaller.exe'; Destination = 'AGP-Uninstaller.exe' },
			@{ Source = 'Installer\release-manifest.json'; Destination = 'Installer\release-manifest.json' }
		)
		Directories = @()
		RequiredRootFiles = @('dxcompiler.dll', 'AGP Native Hook\agp_parenthook.dll', 'AGP-Installer.exe', 'AGP-Uninstaller.exe', 'README.md', 'LICENSE')
		ForbiddenRootFiles = @('Install AGP.bat', 'Uninstall AGP.bat', 'Installer\install.ps1', 'Installer\uninstall.ps1', 'Installer\powershell', 'Installer\python')
	}
)

foreach ($definition in $packageDefinitions) {
	$stagingRoot = Join-Path $OutputDirectory "$($manifest.package.id)-$($definition.Id)-staging"
	$packageRoot = Join-Path $stagingRoot $definition.Name
	$zipPath = Join-Path $OutputDirectory "$($definition.Name).zip"
	$checksumPath = "$zipPath.sha256"
	$provenancePath = Join-Path $OutputDirectory "$($definition.Name)-provenance.json"

    $outputPrefix = $OutputDirectory.TrimEnd('\') + '\'
    foreach ($candidatePath in @($stagingRoot, $zipPath, $checksumPath, $provenancePath)) {
        $resolvedOutput = [IO.Path]::GetFullPath($candidatePath)
        if (-not $resolvedOutput.StartsWith($outputPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Release output escaped the selected output directory: $resolvedOutput"
        }
    }

	if (Test-Path -LiteralPath $stagingRoot) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force }
	foreach ($outputPath in @($zipPath, $checksumPath, $provenancePath)) {
		if (Test-Path -LiteralPath $outputPath) { Remove-Item -LiteralPath $outputPath -Force }
	}
	New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null

	Copy-PackageFile $nativeProxy (Join-Path $packageRoot 'dxcompiler.dll') -Required | Out-Null
	Copy-PackageFile $nativePayload (Join-Path $packageRoot 'AGP Native Hook\agp_parenthook.dll') -Required | Out-Null
	Copy-PackageFile (Join-Path $repositoryRoot $definition.Readme) (Join-Path $packageRoot 'README.md') -Required | Out-Null
    if ($AllowIncompleteValidation) {
        $candidateReadme = Join-Path $packageRoot 'README.md'
        $existingReadme = [IO.File]::ReadAllText($candidateReadme)
        [IO.File]::WriteAllText($candidateReadme, "# Development candidate - acceptance incomplete`r`n`r`nThis local package is not a verified public release. See the source release/validation.json for remaining tests.`r`n`r`n" + $existingReadme, [Text.UTF8Encoding]::new($false))
    }
	Copy-PackageFile (Join-Path $repositoryRoot 'LICENSE') (Join-Path $packageRoot 'LICENSE') -Required | Out-Null
	foreach ($mapping in $definition.Files) {
		Copy-PackageFile (Join-Path $repositoryRoot $mapping.Source) (Join-Path $packageRoot $mapping.Destination) -Required | Out-Null
	}
	foreach ($mapping in $definition.Directories) {
		Copy-PackageDirectory (Join-Path $repositoryRoot $mapping.Source) (Join-Path $packageRoot $mapping.Destination) -Required | Out-Null
	}

	$packageManifest = $manifest | ConvertTo-Json -Depth 20 | ConvertFrom-Json
	$packagedArtifactById = @{}
	foreach ($artifact in $packageManifest.artifacts) {
		$packagedPath = Join-Path $packageRoot ([string]$artifact.relative_path -replace '/', '\')
		if (-not (Test-Path -LiteralPath $packagedPath -PathType Leaf)) {
			throw "Built artifact is not present in $($definition.Name): $($artifact.relative_path)"
		}
		$artifact.sha256 = (Get-FileHash -LiteralPath $packagedPath -Algorithm SHA256).Hash.ToLowerInvariant()
		$artifact.size_bytes = [int64](Get-Item -LiteralPath $packagedPath).Length
		$packagedArtifactById[[string]$artifact.id] = $artifact
	}
	$manualSeed = $packageManifest.compatibility.seeds | Where-Object { $_.id -eq "agp-v$Version-manual-layout" } | Select-Object -First 1
	if ($manualSeed) {
		foreach ($file in $manualSeed.match.required_files) {
			if ($file.relative_path -eq 'dxcompiler.dll') {
				$file.sha256 = $packagedArtifactById['agp-proxy'].sha256
				$file.size_bytes = $packagedArtifactById['agp-proxy'].size_bytes
			} elseif ($file.relative_path -eq 'AGP Native Hook/agp_parenthook.dll') {
				$file.sha256 = $packagedArtifactById['agp-payload'].sha256
				$file.size_bytes = $packagedArtifactById['agp-payload'].size_bytes
			}
		}
	}

	$packagedManifestPath = Join-Path $packageRoot 'Installer\release-manifest.json'
	if (Test-Path -LiteralPath $packagedManifestPath -PathType Leaf) {
		$packageManifest.package.id = "$($manifest.package.id)-$($definition.Id)"
		$packageManifest.package.entrypoints = @($packageManifest.package.entrypoints | Where-Object {
			Test-Path -LiteralPath (Join-Path $packageRoot ([string]$_.relative_path -replace '/', '\'))
		})
		[System.IO.File]::WriteAllText($packagedManifestPath, ($packageManifest | ConvertTo-Json -Depth 20) + "`n", [System.Text.UTF8Encoding]::new($false))
	}

	$forbiddenFound = Get-ChildItem -LiteralPath $packageRoot -Recurse -Force | Where-Object { $forbiddenNames -contains $_.Name -or $_.Name -like 'script_docs*' -or $_.Name -eq 'ck3.exe' }
	if ($forbiddenFound) { throw "Forbidden development content entered $($definition.Name): $($forbiddenFound.Name -join ', ')" }
	foreach ($relative in $definition.RequiredRootFiles) {
		if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $relative))) { throw "$($definition.Name) is missing: $relative" }
	}
	foreach ($relative in $definition.ForbiddenRootFiles) {
		if (Test-Path -LiteralPath (Join-Path $packageRoot $relative)) { throw "$($definition.Name) unexpectedly contains: $relative" }
	}
	foreach ($artifact in $packageManifest.artifacts) {
		$packagedPath = Join-Path $packageRoot ([string]$artifact.relative_path -replace '/', '\')
		Assert-Hash $packagedPath $artifact.sha256 $artifact.relative_path | Out-Null
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
	$fileCount = @(Get-ChildItem -LiteralPath $packageRoot -Recurse -File).Count
	$provenance = [ordered]@{
		'schema_version' = 1
		'kind' = 'agp_release_provenance'
		'release' = [ordered]@{ 'id' = $manifest.release.id; 'version' = $Version; 'channel' = $manifest.release.channel; 'unsigned' = $true; 'signing' = 'not_performed' }
		'validation' = [ordered]@{ acceptance_complete = (-not $AllowIncompleteValidation); status = $(if ($AllowIncompleteValidation) { 'incomplete_local_candidate' } else { 'accepted' }) }
		'source' = [ordered]@{ package_repository = $manifest.release.source_repo; package_commit = $commit; native_repository = $nativeRelease.repository; native_tag = $nativeRelease.tag; native_source_commit = $nativeRelease.source_commit; native_archive_url = $nativeRelease.archive_url; native_archive_sha256 = $nativeRelease.archive_sha256; workflow = 'release/build-release.ps1' }
		'build' = [ordered]@{ authority = $(if ($isCanonicalCi) { 'canonical_github_actions' } else { 'local_smoke_test' }); canonical_release_artifact = $isCanonicalCi; github_actions_runner = $toolchain.github_actions_runner; vc_tools_version = $toolchain.vc_tools_version; windows_sdk_version = $toolchain.windows_sdk_version; host_architecture = $toolchain.host_architecture; target_architecture = $toolchain.target_architecture; toolchain_contract = 'Native Hook/toolchain.json' }
		'artifact' = [ordered]@{ file = (Split-Path -Leaf $zipPath); sha256 = $zipHash; package_id = "$($manifest.package.id)-$($definition.Id)"; package_kind = $definition.Id; file_count = $fileCount }
		'safety' = [ordered]@{ excluded = @('Native Hook/native_test_mod', 'AGP Dynastic Priority', '.git', 'Lunacy'); credentials_used = $false }
	}
	[System.IO.File]::WriteAllText($provenancePath, ($provenance | ConvertTo-Json -Depth 8) + "`n", [System.Text.UTF8Encoding]::new($false))

	Write-Host "Created $zipPath"
	Write-Host "SHA-256 $zipHash"
	Write-Host "Created $checksumPath and $provenancePath"
}
