[CmdletBinding()]
param([string]$ToolchainPath)
$ErrorActionPreference = 'Stop'
# Reuse the exact toolchain resolver and build contract used by the DLLs.
. (Join-Path $PSScriptRoot 'build.ps1') -ToolchainPath $ToolchainPath
$testSource = Join-Path $scriptRoot 'tests/native_tests.cpp'
$runtimeSource = Join-Path $scriptRoot 'src/agp_patch_runtime.cpp'
$testOutput = Join-Path $buildDirectory 'agp-native-tests.exe'
Push-Location $buildDirectory
try {
    Invoke-VcCommand $vcVarsAll "cl.exe /nologo /std:c++17 /EHsc /O2 /I `"$buildDirectory`" `"$testSource`" `"$runtimeSource`" /link bcrypt.lib /OUT:`"$testOutput`"" $toolchain
    & $testOutput
    if ($LASTEXITCODE -ne 0) { throw 'Native runtime tests failed.' }
} finally { Pop-Location }
