[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('install', 'uninstall')]
    [string]$Operation,
    [Parameter(Mandatory = $true)]
    [string]$TargetRoot,
    [string]$PackageRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$Confirmation,
    [switch]$Interactive,
    [switch]$Json,
    [string]$WriteFaultAt
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Fail([string]$Message) {
    throw [InvalidOperationException]::new($Message)
}

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path)
}

function Get-CanonicalRelative([string]$Path) {
    return ($Path -replace '\\', '/')
}

function Test-RelativePath([string]$RelativePath) {
    if ([string]::IsNullOrWhiteSpace($RelativePath)) { return $false }
    if ([IO.Path]::IsPathRooted($RelativePath)) { return $false }
    if ($RelativePath -match '^[A-Za-z]:') { return $false }
    if ($RelativePath -match '(^|[\\/])\.\.?(?:[\\/]|$)') { return $false }
    if ($RelativePath -match '[<>:"|?*\x00-\x1f]') { return $false }
    return $true
}

function Get-ContainedPath([hashtable]$Context, [string]$RelativePath) {
    if (-not (Test-RelativePath $RelativePath)) {
        Fail "Rejected non-relative path: $RelativePath"
    }
    $root = Get-FullPath $Context.Root
    $candidate = Get-FullPath (Join-Path $root ($RelativePath -replace '/', '\'))
    $prefix = $root.TrimEnd('\') + '\'
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        Fail "Path escapes target root: $RelativePath"
    }
    Test-PathSafety $Context $candidate
    return $candidate
}

function Test-PathSafety([hashtable]$Context, [string]$Path) {
    $root = Get-FullPath $Context.Root
    $candidate = Get-FullPath $Path
    $prefix = $root.TrimEnd('\') + '\'
    if (-not ($candidate.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
              $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase))) {
        Fail "Resolved path is outside target root: $Path"
    }

    $current = $candidate
    while ($null -ne $current -and $current.Length -ge $root.Length) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                Fail "Reparse point is not an authorized installer path: $current"
            }
        }
        if ($current.Equals($root, [StringComparison]::OrdinalIgnoreCase)) { break }
        $parent = Split-Path -Parent $current
        if ([string]::IsNullOrEmpty($parent) -or $parent.Equals($current, [StringComparison]::OrdinalIgnoreCase)) { break }
        $current = $parent
    }
}

function Get-RelativeToRoot([hashtable]$Context, [string]$Path) {
    $rootUri = [Uri]::new((Get-FullPath $Context.Root).TrimEnd('\') + '\')
    $pathUri = [Uri]::new((Get-FullPath $Path))
    $relative = $rootUri.MakeRelativeUri($pathUri).ToString()
    return (Get-CanonicalRelative ([Uri]::UnescapeDataString($relative)))
}

function Get-Observation([hashtable]$Context, [string]$RelativePath) {
    $path = Get-ContainedPath $Context $RelativePath
    if (-not (Test-Path -LiteralPath $path)) {
        return [ordered]@{ exists = $false; kind = 'absent'; is_reparse_point = $false }
    }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer) {
        return [ordered]@{ exists = $true; kind = 'directory'; size_bytes = 0; is_reparse_point = $false }
    }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    return [ordered]@{ exists = $true; kind = 'file'; sha256 = $hash; size_bytes = [int64]$item.Length; is_reparse_point = $false }
}

function Get-DirectoryFingerprint([hashtable]$Context, [string]$RelativePath) {
    $root = Get-ContainedPath $Context $RelativePath
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { Fail "Expected directory: $RelativePath" }
    $lines = New-Object Collections.Generic.List[string]
    $total = [int64]0
    foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse -Force | Sort-Object FullName)) {
        Test-PathSafety $Context $file.FullName
        $rel = Get-RelativeToRoot $Context $file.FullName
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        [void]$lines.Add("$rel|$hash|$([int64]$file.Length)")
        $total += [int64]$file.Length
    }
    $text = ($lines -join "`n")
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($text)
    $sha = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    $hex = ([BitConverter]::ToString($sha) -replace '-', '').ToLowerInvariant()
    return [ordered]@{ sha256 = $hex; size_bytes = $total }
}

function Write-JsonFile([string]$Path, $Value) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $json = $Value | ConvertTo-Json -Depth 32
    $encoding = [Text.UTF8Encoding]::new($false)
    $stream = [IO.FileStream]::new($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $writer = [IO.StreamWriter]::new($stream, $encoding)
        try { $writer.Write($json); $writer.Flush(); $stream.Flush($true) }
        finally { $writer.Dispose() }
    }
    finally { $stream.Dispose() }
}

function Get-JsonObject([string]$Path) {
    try { return (Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json) }
    catch { return $null }
}

function Test-Sha([object]$Value) {
    return ($null -ne $Value -and [string]$Value -match '^[0-9a-fA-F]{64}$')
}

function Test-ValidRelative([object]$Value) {
    return ($null -ne $Value -and (Test-RelativePath ([string]$Value)))
}

function Test-StateShape($State) {
    if ($null -eq $State) { return $false }
    try {
        if ($State.schema_version -ne 1 -or $State.kind -ne 'agp_install_state' -or $State.status -ne 'managed_agp') { return $false }
        if ([string]$State.transaction_id -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$') { return $false }
        if ($State.release.id -ne 'agp' -or $State.release.version -notmatch '^\d+\.\d+\.\d+$' -or -not (Test-Sha $State.release.manifest_sha256)) { return $false }
        if ($State.target.game_id -ne 'crusader_kings_iii' -or $State.target.binaries_relative_path -ne 'binaries' -or $State.target.executable_relative_path -ne 'ck3.exe') { return $false }
        if ($State.target.target_root_kind -ne 'steam_game_binaries' -or $State.target.build_id -notmatch '^\d+\.\d+\.\d+\.\d+$') { return $false }
        foreach ($base in @($State.baseline.original_dxcompiler, $State.baseline.executable)) {
            if (-not (Test-ValidRelative $base.relative_path) -or -not (Test-Sha $base.sha256) -or [int64]$base.size_bytes -lt 0 -or $base.ownership -ne 'steam') { return $false }
        }
        if (@($State.managed_files).Count -lt 2) { return $false }
        foreach ($managed in @($State.managed_files)) {
            if (-not (Test-ValidRelative $managed.relative_path) -or $managed.ownership -ne 'managed' -or -not (Test-Sha $managed.installed_sha256) -or [int64]$managed.installed_size_bytes -lt 0) { return $false }
            if ($managed.role -notin @('agp_proxy', 'agp_payload')) { return $false }
        }
        foreach ($q in @($State.quarantined_files)) {
            if (-not (Test-ValidRelative $q.original_relative_path) -or -not (Test-ValidRelative $q.quarantine_relative_path) -or -not (Test-Sha $q.sha256) -or $q.kind -notin @('file', 'directory_manifest')) { return $false }
        }
        if ($State.foreign_cleanup.kind -notin @('none', 'recognized_awow_ufg')) { return $false }
        if (-not (Test-ValidRelative $State.foreign_cleanup.quarantine_relative_path)) { return $false }
        return $true
    }
    catch { return $false }
}

function Test-ManagedHashes([hashtable]$Context, $State) {
    if (-not (Test-StateShape $State)) { return $false }
    foreach ($managed in @($State.managed_files)) {
        $obs = Get-Observation $Context $managed.relative_path
        if (-not $obs.exists -or $obs.kind -ne 'file' -or $obs.sha256 -ne ([string]$managed.installed_sha256).ToLowerInvariant()) { return $false }
    }
    $original = Get-Observation $Context $State.baseline.original_dxcompiler.relative_path
    if (-not $original.exists -or $original.kind -ne 'file' -or $original.sha256 -ne ([string]$State.baseline.original_dxcompiler.sha256).ToLowerInvariant()) { return $false }
    return $true
}

function Test-SeedMatch([hashtable]$Context, $Seed, [bool]$StatePresent) {
    $stateMode = [string]$Seed.match.state_file
    if ($stateMode -eq 'absent' -and $StatePresent) { return $false }
    if ($stateMode -eq 'valid' -and -not $Context.StateValid) { return $false }
    if ($stateMode -eq 'present_but_drifted' -and -not $StatePresent) { return $false }
    foreach ($required in @($Seed.match.required_files)) {
        $obs = Get-Observation $Context $required.relative_path
        if (-not $obs.exists -or $obs.kind -ne 'file' -or $obs.sha256 -ne ([string]$required.sha256).ToLowerInvariant()) { return $false }
    }
    foreach ($requiredPath in @($Seed.match.required_paths)) {
        $obs = Get-Observation $Context $requiredPath.relative_path
        if (-not $obs.exists -or $obs.kind -ne [string]$requiredPath.kind) { return $false }
    }
    foreach ($absent in @($Seed.match.absent_paths)) {
        if ((Get-Observation $Context $absent).exists) { return $false }
    }
    return $true
}

function Get-Classification([hashtable]$Context) {
    $statePath = Get-ContainedPath $Context $Context.Manifest.target.state_relative_path
    $statePresent = Test-Path -LiteralPath $statePath
    $Context.StatePresent = $statePresent
    $Context.State = $null
    $Context.StateValid = $false
    if ($statePresent) {
        $Context.State = Get-JsonObject $statePath
        $Context.StateValid = Test-StateShape $Context.State
        if ($Context.StateValid -and (Test-ManagedHashes $Context $Context.State)) {
            $Context.Classification = 'managed_agp'
            return $Context.Classification
        }
        if ($Context.StateValid) {
            $active = Get-Observation $Context $Context.Manifest.target.active_dxcompiler_relative_path
            $supportedOriginal = [string]$Context.Build.original_dxcompiler_sha256
            if ($active.exists -and $active.kind -eq 'file' -and $active.sha256 -eq $supportedOriginal -and
                $Context.State.baseline.original_dxcompiler.sha256 -ne $supportedOriginal) {
                $Context.Classification = 'steam_updated'
                return $Context.Classification
            }
        }
    }
    foreach ($seed in @($Context.Manifest.compatibility.seeds)) {
        if ($seed.state -eq 'managed_agp' -or $seed.state -eq 'steam_updated') { continue }
        if (Test-SeedMatch $Context $seed $statePresent) {
            $Context.Classification = [string]$seed.state
            return $Context.Classification
        }
    }
    $Context.Classification = [string]$Context.Manifest.compatibility.fallback_state
    return $Context.Classification
}

function New-JournalEntry([hashtable]$Context, [string]$RelativePath, [string]$Kind, [string]$Op, [string]$Staged, [string]$Owner) {
    $entry = [ordered]@{
        relative_path = Get-CanonicalRelative $RelativePath
        kind = $Kind
        operation = $Op
        before = Get-Observation $Context $RelativePath
        staged_relative_path = Get-CanonicalRelative $Staged
    }
    if ($Owner) { $entry.ownership = $Owner }
    return $entry
}

function Add-Snapshot([hashtable]$Context, [string]$RelativePath) {
    if ($Context.Snapshots.ContainsKey($RelativePath)) { return }
    $obs = Get-Observation $Context $RelativePath
    $safe = ($RelativePath -replace '/', '__')
    $stageRel = "$($Context.StageRelative)/snapshot/$safe"
    $stagePath = Get-ContainedPath $Context $stageRel
    $snapshot = [ordered]@{ relative_path = $RelativePath; stage_relative_path = $stageRel; before = $obs }
    if ($obs.exists) {
        if ($obs.kind -eq 'directory') {
            New-Item -ItemType Directory -Path $stagePath -Force | Out-Null
            Copy-Item -LiteralPath (Get-ContainedPath $Context $RelativePath) -Destination $stagePath -Recurse -Force
        }
        else {
            $parent = Split-Path -Parent $stagePath
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
            Copy-Item -LiteralPath (Get-ContainedPath $Context $RelativePath) -Destination $stagePath -Force
        }
    }
    $Context.Snapshots[$RelativePath] = $snapshot
}

function Add-Quarantine([hashtable]$Context, [string]$RelativePath, [string]$Kind, [string]$Owner, [string]$Policy) {
    Add-Snapshot $Context $RelativePath
    $source = Get-ContainedPath $Context $RelativePath
    if (-not (Test-Path -LiteralPath $source)) { Fail "Cannot quarantine absent path: $RelativePath" }
    $obs = $Context.Snapshots[$RelativePath].before
    if ($Kind -eq 'directory_manifest') {
        $fingerprint = Get-DirectoryFingerprint $Context $RelativePath
    }
    else {
        $fingerprint = [ordered]@{ sha256 = $obs.sha256; size_bytes = $obs.size_bytes }
    }
    $destRel = "$($Context.QuarantineRelative)/$RelativePath"
    $dest = Get-ContainedPath $Context $destRel
    if (Test-Path -LiteralPath $dest) { Fail "Quarantine destination already exists: $destRel" }
    $record = [ordered]@{
        original_relative_path = Get-CanonicalRelative $RelativePath
        quarantine_relative_path = Get-CanonicalRelative $destRel
        kind = $Kind
        sha256 = ([string]$fingerprint.sha256).ToLowerInvariant()
        size_bytes = [int64]$fingerprint.size_bytes
        ownership = $Owner
        restore_policy = $Policy
    }
    [void]$Context.Quarantined.Add($record)
    [void]$Context.Touched.Add($RelativePath)
}

function Invoke-PlannedQuarantine([hashtable]$Context) {
    foreach ($record in $Context.Quarantined) {
        $source = Get-ContainedPath $Context $record.original_relative_path
        $destination = Get-ContainedPath $Context $record.quarantine_relative_path
        if (-not (Test-Path -LiteralPath $source)) { Fail "Quarantine source disappeared: $($record.original_relative_path)" }
        if (Test-Path -LiteralPath $destination) { Fail "Quarantine destination already exists: $($record.quarantine_relative_path)" }
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Move-Item -LiteralPath $source -Destination $destination
    }
}

function New-Context {
    $root = Get-FullPath $TargetRoot
    $package = Get-FullPath $PackageRoot
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { Fail "TargetRoot must be an existing directory: $root" }
    if (-not (Test-Path -LiteralPath $package -PathType Container)) { Fail "PackageRoot must be an existing directory: $package" }
    $manifestPath = Join-Path $package 'Installer\release-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { Fail "Missing release manifest: $manifestPath" }
    $manifest = Get-JsonObject $manifestPath
    if ($null -eq $manifest -or $manifest.schema_version -ne 1 -or $manifest.kind -ne 'agp_release_manifest') { Fail 'Release manifest is not schema-v1.' }
    $build = @($manifest.target.supported_builds)[0]
    if ($null -eq $build) { Fail 'Manifest has no supported build.' }
    $ctx = @{
        Root = $root
        PackageRoot = $package
        Manifest = $manifest
        ManifestPath = $manifestPath
        ManifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
        Build = $build
        State = $null
        StateValid = $false
        StatePresent = $false
        Classification = $null
        TransactionId = [Guid]::NewGuid().ToString()
        StageRelative = ''
        QuarantineRelative = ''
        JournalPath = $null
        Journal = $null
        Snapshots = @{}
        Touched = New-Object Collections.Generic.List[string]
        Quarantined = New-Object Collections.Generic.List[object]
        ArtifactSources = @{}
        Result = $null
    }
    Test-PathSafety $ctx $root
    $ctx.StageRelative = "$($manifest.target.journal_relative_directory)/$($ctx.TransactionId)/stage"
    $ctx.QuarantineRelative = "$($manifest.target.quarantine_relative_directory)/$($ctx.TransactionId)"
    $ctx.JournalPath = Get-ContainedPath $ctx "$($manifest.target.journal_relative_directory)/$($ctx.TransactionId).json"
    foreach ($artifact in @($manifest.artifacts)) {
        $source = Join-Path $package ($artifact.relative_path -replace '/', '\')
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            $fallback = Join-Path $package ($artifact.source_relative_path -replace '/', '\')
            if (Test-Path -LiteralPath $fallback -PathType Leaf) { $source = $fallback }
        }
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { Fail "Missing package artifact: $($artifact.relative_path)" }
        $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$artifact.sha256).ToLowerInvariant()) { Fail "Package artifact hash mismatch: $($artifact.relative_path)" }
        $ctx.ArtifactSources[[string]$artifact.relative_path] = $source
    }
    return $ctx
}

function Test-Preflight([hashtable]$Context) {
    if (Get-Process -Name 'ck3' -ErrorAction SilentlyContinue) { Fail 'Crusader Kings III is running; close ck3.exe before installation changes.' }
    $rootItem = Get-Item -LiteralPath $Context.Root -Force
    if (-not $rootItem.PSIsContainer) { Fail 'Target root is not a directory.' }
    Test-PathSafety $Context $Context.Root
    $exeRel = $Context.Manifest.target.executable_relative_path
    $exeObs = Get-Observation $Context $exeRel
    if (-not $exeObs.exists -or $exeObs.kind -ne 'file') { Fail 'Target ck3.exe is missing.' }
    if ($exeObs.sha256 -ne ([string]$Context.Build.executable_sha256).ToLowerInvariant()) { Fail 'Unsupported CK3 executable hash.' }
    $active = Get-Observation $Context $Context.Manifest.target.active_dxcompiler_relative_path
    if ($Operation -eq 'install' -and (-not $active.exists -or $active.kind -ne 'file')) { Fail 'Active dxcompiler.dll is missing.' }
    $journalRoot = Get-ContainedPath $Context $Context.Manifest.target.journal_relative_directory
    if (Test-Path -LiteralPath $journalRoot -PathType Container) {
        if (@(Get-ChildItem -LiteralPath $journalRoot -Force).Count -gt 0) {
            Fail 'An incomplete transaction journal exists; manual recovery is required.'
        }
    }
}

function Get-ExpectedConfirmation([hashtable]$Context) {
    if ($Operation -eq 'install') {
        switch ($Context.Classification) {
            'managed_agp' { return 'UPGRADE_AGP_IN_PLACE' }
            'legacy_agp' { return 'UPGRADE_AGP_IN_PLACE' }
            'recognized_ufg' { return 'CONVERT_UFG_TO_AGP' }
            'steam_updated' { return 'ACCEPT_STEAM_UPDATE' }
            'unknown_conflicting' { return 'I_UNDERSTAND_UNKNOWN_CONFLICT' }
        }
    }
    else {
        if ($Context.Classification -in @('unknown_conflicting', 'legacy_agp', 'steam_updated')) { return 'I_UNDERSTAND_UNKNOWN_CONFLICT' }
    }
    return $null
}

function Confirm-Transition([hashtable]$Context) {
    $expected = Get-ExpectedConfirmation $Context
    if ($null -eq $expected) { return $true }
    $answer = $Confirmation
    if ([string]::IsNullOrEmpty($answer) -and $Interactive) {
        $answer = Read-Host "Type $expected to continue (anything else aborts)"
    }
    if ($answer -ne $expected) {
        $Context.Result = [ordered]@{ operation = $Operation; classification = $Context.Classification; decision = 'abort'; message = "Required confirmation was not supplied: $expected" }
        return $false
    }
    return $true
}

function Add-InstallPlan([hashtable]$Context) {
    $activeRel = $Context.Manifest.target.active_dxcompiler_relative_path
    $originalRel = $Context.Manifest.target.original_dxcompiler_relative_path
    $payloadRel = 'AGP Native Hook/agp_parenthook.dll'
    $stateRel = $Context.Manifest.target.state_relative_path
    foreach ($rel in @($activeRel, $originalRel, $payloadRel, $stateRel)) { Add-Snapshot $Context $rel }
    foreach ($log in @($Context.Manifest.target.logs)) {
        if ([string]$log.owner -eq 'agp_runtime') { Add-Snapshot $Context $log.relative_path }
    }
    switch ($Context.Classification) {
        'legacy_agp' {
            Add-Quarantine $Context $activeRel 'file' 'unknown_displaced' 'preserve_for_uninstall'
            Add-Quarantine $Context $payloadRel 'file' 'unknown_displaced' 'preserve_for_uninstall'
        }
        'unknown_conflicting' {
            $active = Get-Observation $Context $activeRel
            if ($active.exists) { Add-Quarantine $Context $activeRel 'file' 'unknown_displaced' 'preserve_for_uninstall' }
            $payload = Get-Observation $Context $payloadRel
            if ($payload.exists) { Add-Quarantine $Context $payloadRel 'file' 'unknown_displaced' 'preserve_for_uninstall' }
        }
        'recognized_ufg' {
            $ufgDir = [string]$Context.Manifest.safety.ufg_cleanup.foreign_payload_directory
            if ((Get-Observation $Context $ufgDir).exists) { Add-Quarantine $Context $ufgDir 'directory_manifest' 'recognized_awow_ufg' 'do_not_restore_after_awow_ufg_commit' }
            foreach ($log in @($Context.Manifest.safety.ufg_cleanup.foreign_logs)) {
                if ((Get-Observation $Context $log).exists) { Add-Quarantine $Context $log 'file' 'recognized_awow_ufg' 'do_not_restore_after_awow_ufg_commit' }
            }
        }
        'steam_updated' {
            Add-Quarantine $Context $originalRel 'file' 'unknown_displaced' 'preserve_for_uninstall'
        }
    }
    if ($Context.Classification -eq 'known_clean') {
        $original = Get-Observation $Context $originalRel
        if ($original.exists) { Fail 'Clean install refuses an existing original compiler.' }
        $active = Get-Observation $Context $activeRel
        if ($active.sha256 -ne ([string]$Context.Build.original_dxcompiler_sha256).ToLowerInvariant()) { Fail 'Clean install active compiler is not the supported Steam original.' }
    }
}

function Stage-Install([hashtable]$Context) {
    New-Item -ItemType Directory -Path (Get-ContainedPath $Context $Context.StageRelative) -Force | Out-Null
    foreach ($artifact in @($Context.Manifest.artifacts)) {
        $source = $Context.ArtifactSources[[string]$artifact.relative_path]
        $stageRel = "$($Context.StageRelative)/package/$($artifact.relative_path)"
        $stagePath = Get-ContainedPath $Context $stageRel
        New-Item -ItemType Directory -Path (Split-Path -Parent $stagePath) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $stagePath -Force
        $hash = (Get-FileHash -LiteralPath $stagePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$artifact.sha256).ToLowerInvariant()) { Fail "Staged artifact hash mismatch: $($artifact.relative_path)" }
    }
}

function New-InstallJournal([hashtable]$Context) {
    $entries = New-Object Collections.Generic.List[object]
    $activeRel = $Context.Manifest.target.active_dxcompiler_relative_path
    $originalRel = $Context.Manifest.target.original_dxcompiler_relative_path
    $payloadRel = 'AGP Native Hook/agp_parenthook.dll'
    $stateRel = $Context.Manifest.target.state_relative_path
    if ($Context.Classification -eq 'known_clean') { [void]$entries.Add((New-JournalEntry $Context $activeRel 'file' 'rename' "$($Context.StageRelative)/snapshot/dxcompiler.dll" 'steam')) }
    foreach ($record in $Context.Quarantined) { [void]$entries.Add((New-JournalEntry $Context $record.original_relative_path $record.kind 'quarantine' $record.quarantine_relative_path $record.ownership)) }
    foreach ($artifact in @($Context.Manifest.artifacts)) {
        $op = 'replace'
        if (-not (Get-Observation $Context $artifact.relative_path).exists) { $op = 'create' }
        [void]$entries.Add((New-JournalEntry $Context $artifact.relative_path 'file' $op "$($Context.StageRelative)/package/$($artifact.relative_path)" 'managed'))
    }
    [void]$entries.Add((New-JournalEntry $Context $stateRel 'file' 'create' "$($Context.StageRelative)/state.json" 'managed'))
    $foreign = [ordered]@{ kind = 'none'; allowed = $false; quarantine_relative_path = $Context.QuarantineRelative; remove_after_commit = $false; uninstall_policy = 'none' }
    if ($Context.Classification -eq 'recognized_ufg') { $foreign = [ordered]@{ kind = 'recognized_awow_ufg'; allowed = $true; quarantine_relative_path = $Context.QuarantineRelative; remove_after_commit = $true; uninstall_policy = 'do_not_restore_awow_ufg' } }
    $Context.Journal = [ordered]@{
        '$schema' = 'https://json-schema.org/draft/2020-12/schema'
        schema_version = 1
        kind = 'agp_install_journal'
        transaction_id = $Context.TransactionId
        operation = 'install'
        source_state = $Context.Classification
        target_state = 'managed_agp'
        phase = 'journal'
        target = [ordered]@{ game_id = 'crusader_kings_iii'; build_id = [string]$Context.Build.id; binaries_relative_path = 'binaries'; target_root_kind = 'steam_game_binaries' }
        entries = $entries.ToArray()
        foreign_cleanup = $foreign
    }
    Write-JsonFile $Context.JournalPath $Context.Journal
}

function Copy-StagedArtifact([hashtable]$Context, [string]$RelativePath) {
    if ($WriteFaultAt -and $WriteFaultAt -eq $RelativePath) { Fail "Simulated write failure at $RelativePath" }
    $dest = Get-ContainedPath $Context $RelativePath
    Test-PathSafety $Context $dest
    $stage = Get-ContainedPath $Context "$($Context.StageRelative)/package/$RelativePath"
    if (Test-Path -LiteralPath $dest) {
        $item = Get-Item -LiteralPath $dest -Force
        if ($item.PSIsContainer) { Fail "Artifact destination is a directory: $RelativePath" }
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $dest) -Force | Out-Null
    Copy-Item -LiteralPath $stage -Destination $dest -Force
}

function New-State([hashtable]$Context, [string]$CreatedUtc) {
    $originalRel = $Context.Manifest.target.original_dxcompiler_relative_path
    $exeRel = $Context.Manifest.target.executable_relative_path
    $original = Get-Observation $Context $originalRel
    $exe = Get-Observation $Context $exeRel
    if (-not $original.exists -or $original.kind -ne 'file') { Fail 'Cannot commit state without canonical original compiler.' }
    if (-not $exe.exists -or $exe.kind -ne 'file') { Fail 'Cannot commit state without ck3.exe.' }
    $managed = New-Object Collections.Generic.List[object]
    foreach ($artifact in @($Context.Manifest.artifacts)) {
        $obs = Get-Observation $Context $artifact.relative_path
        [void]$managed.Add([ordered]@{
            relative_path = Get-CanonicalRelative $artifact.relative_path
            role = [string]$artifact.role
            ownership = 'managed'
            installed_sha256 = $obs.sha256
            installed_size_bytes = [int64]$obs.size_bytes
            restore = [ordered]@{ action = 'remove_managed_file' }
        })
    }
    $foreign = [ordered]@{ kind = 'none'; quarantine_relative_path = $Context.QuarantineRelative; removed_paths = @(); uninstall_policy = 'none' }
    if ($Context.Classification -eq 'recognized_ufg') {
        $foreign = [ordered]@{ kind = 'recognized_awow_ufg'; quarantine_relative_path = $Context.QuarantineRelative; removed_paths = @('AWOW Universal Female Generation', 'awow_ufg.log', 'awow_ufg_dxcompiler_loader.log'); uninstall_policy = 'do_not_restore_awow_ufg' }
    }
    $state = [ordered]@{
        '$schema' = 'https://any-gender-parenthook.invalid/schema/install-state-v1.json'
        schema_version = 1
        kind = 'agp_install_state'
        status = 'managed_agp'
        transaction_id = $Context.TransactionId
        release = [ordered]@{ id = [string]$Context.Manifest.release.id; version = [string]$Context.Manifest.release.version; manifest_sha256 = $Context.ManifestHash }
        target = [ordered]@{ game_id = 'crusader_kings_iii'; build_id = [string]$Context.Build.id; binaries_relative_path = 'binaries'; executable_relative_path = 'ck3.exe'; target_root_kind = 'steam_game_binaries' }
        baseline = [ordered]@{
            original_dxcompiler = [ordered]@{ relative_path = $originalRel; sha256 = $original.sha256; size_bytes = [int64]$original.size_bytes; ownership = 'steam' }
            executable = [ordered]@{ relative_path = $exeRel; sha256 = $exe.sha256; size_bytes = [int64]$exe.size_bytes; ownership = 'steam' }
        }
        managed_files = $managed.ToArray()
        quarantined_files = $Context.Quarantined.ToArray()
        foreign_cleanup = $foreign
        created_utc = $CreatedUtc
        updated_utc = ([DateTime]::UtcNow.ToString('o'))
    }
    return $state
}

function Verify-Install([hashtable]$Context, $State) {
    foreach ($artifact in @($Context.Manifest.artifacts)) {
        $obs = Get-Observation $Context $artifact.relative_path
        if (-not $obs.exists -or $obs.sha256 -ne ([string]$artifact.sha256).ToLowerInvariant()) { Fail "Installed artifact verification failed: $($artifact.relative_path)" }
    }
    $statePath = Get-ContainedPath $Context $Context.Manifest.target.state_relative_path
    Write-JsonFile $statePath $State
    $readBack = Get-JsonObject $statePath
    if (-not (Test-StateShape $readBack)) { Fail 'Committed state failed schema-v1 shape verification.' }
    if (-not (Test-ManagedHashes $Context $readBack)) { Fail 'Committed managed ownership/hash verification failed.' }
}

function Remove-Exact([hashtable]$Context, [string]$RelativePath, [bool]$Recursive) {
    $path = Get-ContainedPath $Context $RelativePath
    if (-not (Test-Path -LiteralPath $path)) { return }
    if ($Recursive) { Remove-Item -LiteralPath $path -Recurse -Force }
    else { Remove-Item -LiteralPath $path -Force }
}

function Commit-Install([hashtable]$Context) {
    if ($Context.Classification -eq 'recognized_ufg') {
        Remove-Exact $Context $Context.QuarantineRelative $true
    }
    $journalDir = Split-Path -Parent $Context.JournalPath
    if (Test-Path -LiteralPath $journalDir) { Remove-Item -LiteralPath $journalDir -Recurse -Force }
    $Context.Result = [ordered]@{ operation = 'install'; classification = $Context.Classification; decision = 'proceed'; next_state = 'managed_agp'; transaction_id = $Context.TransactionId }
}

function Restore-Snapshots([hashtable]$Context) {
    $ordered = @($Context.Snapshots.Values | Sort-Object { $_.relative_path.Length } -Descending)
    foreach ($snapshot in $ordered) {
        $target = Get-ContainedPath $Context $snapshot.relative_path
        if (Test-Path -LiteralPath $target) {
            $item = Get-Item -LiteralPath $target -Force
            if ($item.PSIsContainer) { Remove-Item -LiteralPath $target -Recurse -Force }
            else { Remove-Item -LiteralPath $target -Force }
        }
    }
    foreach ($snapshot in ($Context.Snapshots.Values | Sort-Object { $_.relative_path.Length })) {
        if (-not $snapshot.before.exists) { continue }
        $source = Get-ContainedPath $Context $snapshot.stage_relative_path
        $target = Get-ContainedPath $Context $snapshot.relative_path
        New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
        if ($snapshot.before.kind -eq 'directory') { Copy-Item -LiteralPath $source -Destination $target -Recurse -Force }
        else { Copy-Item -LiteralPath $source -Destination $target -Force }
    }
}

function Invoke-Install([hashtable]$Context) {
    Add-InstallPlan $Context
    Stage-Install $Context
    New-InstallJournal $Context
    $createdUtc = [DateTime]::UtcNow.ToString('o')
    try {
        $activeRel = $Context.Manifest.target.active_dxcompiler_relative_path
        $originalRel = $Context.Manifest.target.original_dxcompiler_relative_path
        $active = Get-Observation $Context $activeRel
        $original = Get-Observation $Context $originalRel
        Invoke-PlannedQuarantine $Context
        if ($Context.Classification -eq 'known_clean') {
            Move-Item -LiteralPath (Get-ContainedPath $Context $activeRel) -Destination (Get-ContainedPath $Context $originalRel)
        }
        elseif ($Context.Classification -eq 'steam_updated') {
            Move-Item -LiteralPath (Get-ContainedPath $Context $activeRel) -Destination (Get-ContainedPath $Context $originalRel)
        }
        foreach ($artifact in @($Context.Manifest.artifacts)) { Copy-StagedArtifact $Context ([string]$artifact.relative_path) }
        $state = New-State $Context $createdUtc
        Verify-Install $Context $state
        Commit-Install $Context
    }
    catch {
        try {
            Restore-Snapshots $Context
            if (Test-Path -LiteralPath $Context.JournalPath) { Remove-Item -LiteralPath $Context.JournalPath -Force }
            $Context.Result = [ordered]@{ operation = 'install'; classification = $Context.Classification; decision = 'rollback'; next_state = 'known_clean'; transaction_id = $Context.TransactionId; message = $_.Exception.Message }
        }
        catch {
            $Context.Result = [ordered]@{ operation = 'install'; classification = $Context.Classification; decision = 'manual_recovery_required'; transaction_id = $Context.TransactionId; message = $_.Exception.Message }
        }
    }
}

function Add-UninstallPlan([hashtable]$Context) {
    $activeRel = $Context.Manifest.target.active_dxcompiler_relative_path
    $originalRel = $Context.Manifest.target.original_dxcompiler_relative_path
    $payloadRel = 'AGP Native Hook/agp_parenthook.dll'
    $stateRel = $Context.Manifest.target.state_relative_path
    foreach ($rel in @($activeRel, $originalRel, $payloadRel, $stateRel)) { Add-Snapshot $Context $rel }
    foreach ($log in @($Context.Manifest.target.logs)) {
        if ([string]$log.owner -eq 'agp_runtime') { Add-Snapshot $Context $log.relative_path }
    }
    if ($null -eq $Context.State) {
        foreach ($relative in @($activeRel, $payloadRel)) {
            if ((Get-Observation $Context $relative).exists) {
                Add-Quarantine $Context $relative 'file' 'unknown_displaced' 'preserve_for_uninstall'
            }
        }
        $original = Get-Observation $Context $originalRel
        if (-not $original.exists -or $original.kind -ne 'file' -or $original.sha256 -ne ([string]$Context.Build.original_dxcompiler_sha256).ToLowerInvariant()) {
            Fail 'Cannot uninstall safely: the canonical Steam original is missing or unsupported.'
        }
        $Context.State = [ordered]@{
            target = [ordered]@{ build_id = [string]$Context.Build.id }
            baseline = [ordered]@{ original_dxcompiler = [ordered]@{ sha256 = $original.sha256 } }
            managed_files = @()
        }
        return
    }
    foreach ($managed in @($Context.State.managed_files)) {
        $obs = Get-Observation $Context $managed.relative_path
        if (-not $obs.exists -or $obs.kind -ne 'file' -or $obs.sha256 -ne ([string]$managed.installed_sha256).ToLowerInvariant()) {
            if ($obs.exists) { Add-Quarantine $Context $managed.relative_path 'file' 'unknown_displaced' 'preserve_for_uninstall' }
        }
    }
    $original = Get-Observation $Context $originalRel
    if (-not $original.exists -or $original.kind -ne 'file' -or $original.sha256 -ne ([string]$Context.State.baseline.original_dxcompiler.sha256).ToLowerInvariant()) {
        if ($original.exists) { Add-Quarantine $Context $originalRel 'file' 'unknown_displaced' 'preserve_for_uninstall' }
        Fail 'State-owned original compiler hash does not match.'
    }
}

function New-UninstallJournal([hashtable]$Context) {
    $entries = New-Object Collections.Generic.List[object]
    foreach ($record in $Context.Quarantined) { [void]$entries.Add((New-JournalEntry $Context $record.original_relative_path $record.kind 'quarantine' $record.quarantine_relative_path $record.ownership)) }
    foreach ($managed in @($Context.State.managed_files)) { [void]$entries.Add((New-JournalEntry $Context $managed.relative_path 'file' 'remove' "$($Context.StageRelative)/snapshot/$($managed.relative_path -replace '/', '__')" 'managed')) }
    foreach ($log in @($Context.Manifest.target.logs)) {
        if ([string]$log.owner -eq 'agp_runtime') { [void]$entries.Add((New-JournalEntry $Context $log.relative_path 'file' 'remove' "$($Context.StageRelative)/snapshot/$($log.relative_path -replace '/', '__')" 'managed')) }
    }
    [void]$entries.Add((New-JournalEntry $Context $Context.Manifest.target.original_dxcompiler_relative_path 'file' 'restore' "$($Context.StageRelative)/snapshot/dxcompiler_original.dll" 'steam'))
    $foreign = [ordered]@{ kind = 'none'; allowed = $false; quarantine_relative_path = $Context.QuarantineRelative; remove_after_commit = $false; uninstall_policy = 'none' }
    $Context.Journal = [ordered]@{
        '$schema' = 'https://json-schema.org/draft/2020-12/schema'
        schema_version = 1
        kind = 'agp_install_journal'
        transaction_id = $Context.TransactionId
        operation = 'uninstall'
        source_state = $Context.Classification
        target_state = 'known_clean'
        phase = 'journal'
        target = [ordered]@{ game_id = 'crusader_kings_iii'; build_id = [string]$Context.State.target.build_id; binaries_relative_path = 'binaries'; target_root_kind = 'steam_game_binaries' }
        entries = $entries.ToArray()
        foreign_cleanup = $foreign
    }
    Write-JsonFile $Context.JournalPath $Context.Journal
}

function Invoke-Uninstall([hashtable]$Context) {
    Add-UninstallPlan $Context
    New-Item -ItemType Directory -Path (Get-ContainedPath $Context $Context.StageRelative) -Force | Out-Null
    New-UninstallJournal $Context
    try {
        Invoke-PlannedQuarantine $Context
        $activeRel = $Context.Manifest.target.active_dxcompiler_relative_path
        $originalRel = $Context.Manifest.target.original_dxcompiler_relative_path
        $active = Get-Observation $Context $activeRel
        if ($active.exists) { Remove-Exact $Context $activeRel $false }
        foreach ($managed in @($Context.State.managed_files)) {
            $path = Get-ContainedPath $Context $managed.relative_path
            if (Test-Path -LiteralPath $path) { Remove-Exact $Context $managed.relative_path $false }
        }
        foreach ($log in @($Context.Manifest.target.logs)) {
            if ([string]$log.owner -eq 'agp_runtime') { Remove-Exact $Context $log.relative_path $false }
        }
        Move-Item -LiteralPath (Get-ContainedPath $Context $originalRel) -Destination (Get-ContainedPath $Context $activeRel)
        $stateRel = $Context.Manifest.target.state_relative_path
        Remove-Exact $Context $stateRel $false
        $journalDir = Split-Path -Parent $Context.JournalPath
        if (Test-Path -LiteralPath $journalDir) { Remove-Item -LiteralPath $journalDir -Recurse -Force }
        $Context.Result = [ordered]@{ operation = 'uninstall'; classification = $Context.Classification; decision = 'proceed'; next_state = 'known_clean'; transaction_id = $Context.TransactionId }
    }
    catch {
        try {
            Restore-Snapshots $Context
            if (Test-Path -LiteralPath $Context.JournalPath) { Remove-Item -LiteralPath $Context.JournalPath -Force }
            $Context.Result = [ordered]@{ operation = 'uninstall'; classification = $Context.Classification; decision = 'rollback'; next_state = 'managed_agp'; transaction_id = $Context.TransactionId; message = $_.Exception.Message }
        }
        catch {
            $Context.Result = [ordered]@{ operation = 'uninstall'; classification = $Context.Classification; decision = 'manual_recovery_required'; transaction_id = $Context.TransactionId; message = $_.Exception.Message }
        }
    }
}

function Write-Result([hashtable]$Context) {
    if ($null -eq $Context.Result) { $Context.Result = [ordered]@{ operation = $Operation; classification = $Context.Classification; decision = 'abort' } }
    if ($Json) { [Console]::Out.WriteLine(($Context.Result | ConvertTo-Json -Depth 12)) }
    else {
        $r = $Context.Result
        [Console]::Out.WriteLine(("AGP {0}: {1} ({2})" -f $r.operation, $r.decision, $r.classification))
        if ($r.PSObject.Properties.Name -contains 'message' -and $r.message) {
            [Console]::Out.WriteLine([string]$r.message)
        }
    }
    if ($Context.Result.decision -in @('proceed', 'no_op')) { return 0 }
    if ($Context.Result.decision -eq 'abort' -or $Context.Result.decision -eq 'reject') { return 2 }
    return 1
}

$ctx = $null
try {
    $ctx = New-Context
    Test-Preflight $ctx
    Get-Classification $ctx | Out-Null
    if (-not (Confirm-Transition $ctx)) { exit (Write-Result $ctx) }
    if ($Operation -eq 'uninstall' -and $ctx.Classification -eq 'known_clean') {
        $ctx.Result = [ordered]@{ operation = 'uninstall'; classification = 'known_clean'; decision = 'no_op'; next_state = 'known_clean' }
        exit (Write-Result $ctx)
    }
    if ($Operation -eq 'uninstall' -and $ctx.Classification -eq 'recognized_ufg') {
        $ctx.Result = [ordered]@{ operation = 'uninstall'; classification = 'recognized_ufg'; decision = 'reject'; next_state = 'recognized_ufg'; message = 'AWOW UFG is foreign until explicit conversion; uninstall performs no mutation.' }
        exit (Write-Result $ctx)
    }
    if ($Operation -eq 'uninstall') { Invoke-Uninstall $ctx } else { Invoke-Install $ctx }
    exit (Write-Result $ctx)
}
catch {
    if ($env:AGP_DEBUG) { Write-Output ($_ | Format-List * -Force | Out-String) }
    $result = [ordered]@{ operation = $Operation; decision = 'reject'; message = $_.Exception.Message }
    if ($Json) { [Console]::Out.WriteLine(($result | ConvertTo-Json -Depth 8)) } else { [Console]::Out.WriteLine(("AGP {0}: reject" -f $Operation)); [Console]::Out.WriteLine([string]$_.Exception.Message) }
    exit 2
}
