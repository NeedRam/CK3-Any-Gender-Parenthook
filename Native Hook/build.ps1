[CmdletBinding()]
param(
	[string]$VsDevCmdPath,
	[switch]$Clean
)

$ErrorActionPreference = 'Stop'

function Resolve-VsDevCmd {
	param([string]$RequestedPath)

	if ($RequestedPath) {
		$resolved = [System.IO.Path]::GetFullPath($RequestedPath)
		if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
			throw "The requested Visual Studio developer command file was not found: $resolved"
		}
		return $resolved
	}

	$vswhereCandidates = @(
		(Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'),
		(Join-Path $env:ProgramFiles 'Microsoft Visual Studio\Installer\vswhere.exe')
	) | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) }

	foreach ($vswhere in $vswhereCandidates) {
		$installation = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath 2>$null | Select-Object -First 1)
		if ($LASTEXITCODE -eq 0 -and $installation) {
			$candidate = Join-Path $installation.Trim() 'Common7\Tools\VsDevCmd.bat'
			if (Test-Path -LiteralPath $candidate -PathType Leaf) {
				return [System.IO.Path]::GetFullPath($candidate)
			}
		}
	}

	$knownInstallations = @(
		${env:ProgramFiles},
		${env:ProgramFiles(x86)}
	) | Where-Object { $_ } | ForEach-Object {
		Join-Path $_ 'Microsoft Visual Studio\2022'
	} | Where-Object { Test-Path -LiteralPath $_ -PathType Container }

	foreach ($root in $knownInstallations) {
		foreach ($edition in @('Community', 'Professional', 'Enterprise', 'BuildTools')) {
			$candidate = Join-Path $root "$edition\Common7\Tools\VsDevCmd.bat"
			if (Test-Path -LiteralPath $candidate -PathType Leaf) {
				return [System.IO.Path]::GetFullPath($candidate)
			}
		}
	}

	throw 'Visual Studio 2022 x64 C++ build tools were not found. Install the VC x64 workload or pass -VsDevCmdPath.'
}

function Invoke-VsCommand {
	param(
		[string]$DeveloperCommand,
		[string]$CommandLine
	)

	$fullCommand = "call `"$DeveloperCommand`" -arch=x64 -host_arch=x64 && $CommandLine"
	& cmd.exe /d /s /c $fullCommand
	if ($LASTEXITCODE -ne 0) {
		throw "Native compiler command failed with exit code $LASTEXITCODE."
	}
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$vsDevCmd = Resolve-VsDevCmd $VsDevCmdPath
$buildDirectory = Join-Path $scriptRoot 'build'
$payloadDirectory = Join-Path $buildDirectory 'AGP Native Hook'
$payloadOutput = Join-Path $payloadDirectory 'agp_parenthook.dll'
$loaderOutput = Join-Path $buildDirectory 'dxcompiler.dll'
$definition = Join-Path $scriptRoot 'dxcompiler_proxy.def'

$payloadSources = @(
	'agp_parent_hook.cpp',
	'agp_patch_runtime.cpp',
	'agp_close_family.cpp',
	'agp_history.cpp',
	'agp_parent_roles.cpp',
	'agp_female_father.cpp',
	'agp_male_mother.cpp'
) | ForEach-Object { Join-Path $scriptRoot "src\$_" }
$loaderSource = Join-Path $scriptRoot 'src\agp_dxcompiler_loader.cpp'
$versionResourceSource = Join-Path $scriptRoot 'version.rc'
$versionResource = Join-Path $buildDirectory 'agp_version.res'

foreach ($source in @($payloadSources) + $loaderSource + $definition + $versionResourceSource) {
	if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
		throw "Required native build input is missing: $source"
	}
}

New-Item -ItemType Directory -Force -Path $payloadDirectory | Out-Null

$generatedFiles = @(
	'agp_parenthook.dll', 'agp_parenthook.exp', 'agp_parenthook.lib',
	'dxcompiler.exp', 'dxcompiler.lib',
	'agp_parent_hook.obj', 'agp_patch_runtime.obj', 'agp_close_family.obj',
	'agp_history.obj', 'agp_parent_roles.obj', 'agp_female_father.obj',
	'agp_male_mother.obj', 'agp_dxcompiler_loader.obj',
	'agp_version.res',
	'version.dll', 'version.exp', 'version.lib', 'version_proxy.obj'
) | ForEach-Object { Join-Path $buildDirectory $_ }

if ($Clean) {
	Remove-Item -LiteralPath $generatedFiles -Force -ErrorAction SilentlyContinue
}

$payloadArguments = ($payloadSources | ForEach-Object { '"' + $_ + '"' }) -join ' '
$payloadImportLibrary = Join-Path $buildDirectory 'agp_parenthook.lib'
$loaderImportLibrary = Join-Path $buildDirectory 'dxcompiler.lib'

Push-Location $buildDirectory
try {
	Invoke-VsCommand $vsDevCmd "rc.exe /nologo /fo `"$versionResource`" `"$versionResourceSource`""
	Invoke-VsCommand $vsDevCmd "cl.exe /nologo /std:c++17 /EHsc /LD /O2 $payloadArguments `"$versionResource`" /link /Brepro /OUT:`"$payloadOutput`" /IMPLIB:`"$payloadImportLibrary`""
	Invoke-VsCommand $vsDevCmd "cl.exe /nologo /std:c++17 /EHsc /LD /O2 `"$loaderSource`" `"$versionResource`" /link /Brepro /DEF:`"$definition`" /OUT:`"$loaderOutput`" /IMPLIB:`"$loaderImportLibrary`""
}
finally {
	Pop-Location
}

foreach ($output in @($loaderOutput, $payloadOutput)) {
	if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
		throw "Native build completed without producing $output"
	}
	$hash = (Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash.ToLowerInvariant()
	$size = (Get-Item -LiteralPath $output).Length
	Write-Host ("Built {0} ({1} bytes, SHA-256 {2})" -f $output, $size, $hash)
}

Remove-Item -LiteralPath $generatedFiles -Force -ErrorAction SilentlyContinue
