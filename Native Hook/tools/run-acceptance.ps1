[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GameExecutable,
    [ValidateSet('setup','reload','birth_setup','birth_check','no_checks_setup','no_checks_check')][string]$Mode = 'setup',
    [switch]$NormalMode,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$SaveName = 'agp_121_acceptance',
    [switch]$ParentInteractionUI
)
$ErrorActionPreference = 'Stop'
$nativeRoot = Split-Path -Parent $PSScriptRoot
$userRoot = Join-Path $nativeRoot 'build/ck3-user'
$modRoot = Join-Path $userRoot 'mod/agp-autorun'
New-Item -ItemType Directory -Path (Join-Path $modRoot 'gui/scripted_widgets') -Force | Out-Null
$encoding = [Text.UTF8Encoding]::new($true)
$fixturePath = (Join-Path $nativeRoot 'native_test_mod') -replace '\\','/'
$autorunPath = $modRoot -replace '\\','/'
[IO.File]::WriteAllText((Join-Path $userRoot 'mod/agp-native-test.mod'), "name=`"AGP Native Acceptance Fixtures`"`nsupported_version=`"1.21.0.3`"`npath=`"$fixturePath`"`n", $encoding)
[IO.File]::WriteAllText((Join-Path $userRoot 'mod/agp-autorun.mod'), "name=`"AGP Disposable Autorun`"`nsupported_version=`"1.21.0.3`"`npath=`"$autorunPath`"`n", $encoding)
[IO.File]::WriteAllText((Join-Path $userRoot 'dlc_load.json'), '{"enabled_mods":["mod/agp-native-test.mod","mod/agp-autorun.mod"],"disabled_dlcs":[]}', [Text.UTF8Encoding]::new($false))
# Retire the earlier GUI-trigger experiment only inside this disposable mod.
foreach ($relative in @('gui/scripted_widgets/agp_autorun.txt','gui/agp_autorun.gui')) {
    $oldFile = Join-Path $modRoot $relative
    if (Test-Path -LiteralPath $oldFile) { Remove-Item -LiteralPath $oldFile }
}
& python (Join-Path $PSScriptRoot 'generate_acceptance.py') (Join-Path $nativeRoot 'native_test_mod/tests/agp_native_121_tests.txt') $modRoot --mode $Mode
if ($LASTEXITCODE -ne 0) { throw 'Acceptance runner generation failed.' }
if ($ParentInteractionUI) {
    # Reopen stored parents without resetting the interaction-result flags.
    $panel = [IO.File]::ReadAllText((Join-Path $nativeRoot 'native_test_mod/gui/agp_acceptance.gui'))
    $panel = $panel.Replace('scripted_tests agp_native_121','event agp_native_father_test.0012')
    $panel = $panel.Replace('scripted_tests agp_reload_121','event agp_native_father_test.0010')
    $panel = $panel.Replace('AGP: Run scope assertions','AGP: Show parent test')
    $panel = $panel.Replace('AGP: Check reloaded roles','AGP: Check interaction results')
    [IO.File]::WriteAllText((Join-Path $modRoot 'gui/agp_acceptance.gui'), $panel, $encoding)
}
$arguments = @('-skip_checksum','-suppress_error_log','-disable_encyclopedia',('-userdir="'+$userRoot+'"'),'-window_title="AGP 1.21 Acceptance"')
if (-not $NormalMode) { $arguments += '-debug_mode' }
if ($Mode -eq 'setup') { $arguments += @('-skip','-play=k_england','-bookmark=bm_1066_hastings') }
else {
    $savePath = Join-Path $userRoot "save games/$SaveName.ck3"
    if (-not (Test-Path -LiteralPath $savePath -PathType Leaf)) { throw "Acceptance save is missing: $savePath" }
    $arguments += "-loadsave=$SaveName"
}
$process = Start-Process -FilePath $GameExecutable -ArgumentList $arguments -WorkingDirectory (Split-Path -Parent $GameExecutable) -PassThru
Write-Output "Acceptance process: $($process.Id); mode: $Mode; isolated user data: $userRoot"
