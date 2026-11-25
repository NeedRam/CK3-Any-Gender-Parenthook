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
        if ($State.schema_version -notin @(1,2) -or $State.kind -ne 'agp_install_state' -or $State.status -ne 'managed_agp') { return $false }
        if ([string]$State.transaction_id -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$') { return $false }
        if ($State.release.id -ne 'agp' -or $State.release.version -notmatch '^\d+\.\d+\.\d+$' -or -not (Test-Sha $State.release.manifest_sha256)) { return $false }
        if ($State.target.game_id -ne 'crusader_kings_iii' -or $State.target.binaries_relative_path -ne 'binaries' -or $State.target.executable_relative_path -ne 'ck3.exe') { return $false }
        if ($State.target.build_id -notmatch '^\d+\.\d+\.\d+\.\d+$') { return $false }
        $originalOwner = 'steam'
        if ($State.schema_version -eq 1) {
            if ($State.target.target_root_kind -ne 'steam_game_binaries') { return $false }
        } else {
            $originalOwner = 'game'
            if ($State.target.target_root_kind -ne 'ck3_game_binaries' -or $State.target.distribution -notin @('steam','gog') -or $State.target.profile_id -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') { return $false }
        }
        foreach ($base in @($State.baseline.original_dxcompiler, $State.baseline.executable)) {
            if (-not (Test-ValidRelative $base.relative_path) -or -not (Test-Sha $base.sha256) -or [int64]$base.size_bytes -lt 0 -or $base.ownership -ne $originalOwner) { return $false }
        }
        if ($State.baseline.original_dxcompiler.relative_path -ne 'dxcompiler_original.dll' -or $State.baseline.executable.relative_path -ne 'ck3.exe') { return $false }
        if (@($State.managed_files).Count -ne 2) { return $false }
        $roles = @($State.managed_files | ForEach-Object { $_.role } | Sort-Object -Unique)
        if ($roles.Count -ne 2 -or 'agp_proxy' -notin $roles -or 'agp_payload' -notin $roles) { return $false }
        foreach ($managed in @($State.managed_files)) {
            if (-not (Test-ValidRelative $managed.relative_path) -or $managed.ownership -ne 'managed' -or -not (Test-Sha $managed.installed_sha256) -or [int64]$managed.installed_size_bytes -lt 0) { return $false }
            if ($managed.role -notin @('agp_proxy', 'agp_payload')) { return $false }
            $expectedPath = if ($managed.role -eq 'agp_proxy') { 'dxcompiler.dll' } else { 'AGP Native Hook/agp_parenthook.dll' }
            if ($managed.relative_path -ne $expectedPath -or $managed.restore.action -ne 'remove_managed_file') { return $false }
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

function Test-UfgStateShape($State) {
    if ($null -eq $State) { return $false }
    try {
        if ($State.schema_version -ne 2 -or $State.kind -ne 'ufg_install_state' -or $State.status -notin @('managed_ufg','ufg_proxy_only')) { return $false }
        if ([string]$State.transaction_id -notmatch '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$') { return $false }
        if ($State.release.id -ne 'awow-ufg' -or $State.release.version -notin @('1.1.0','1.1.1') -or -not (Test-Sha $State.release.manifest_sha256)) { return $false }
        if ($State.target.game_id -ne 'crusader_kings_iii' -or $State.target.build_id -ne '1.21.0.3' -or $State.target.binaries_relative_path -ne 'binaries' -or $State.target.executable_relative_path -ne 'ck3.exe' -or $State.target.target_root_kind -ne 'ck3_game_binaries' -or $State.target.profile_id -ne 'ck3-1.21.0.3-x64') { return $false }
        foreach ($base in @($State.baseline.original_dxcompiler, $State.baseline.executable)) {
            if (-not (Test-Sha $base.sha256) -or [int64]$base.size_bytes -lt 0 -or $base.ownership -ne 'game') { return $false }
        }
        if ($State.baseline.original_dxcompiler.relative_path -ne 'dxcompiler_original.dll' -or $State.baseline.executable.relative_path -ne 'ck3.exe') { return $false }
        $dependency = $State.agp_dependency
        if ($dependency.build_id -notin @('agp-v1.1.0','agp-v1.1.1') -or $dependency.version -ne ([string]$dependency.build_id).Substring(5)) { return $false }
        if ($dependency.proxy_relative_path -ne 'dxcompiler.dll' -or $dependency.payload_relative_path -ne 'AGP Native Hook/agp_parenthook.dll' -or $dependency.state_relative_path -ne 'AGP Native Hook/agp-install-state.json' -or -not (Test-Sha $dependency.proxy_sha256) -or -not (Test-Sha $dependency.payload_sha256) -or -not (Test-Sha $dependency.original_dxcompiler_sha256)) { return $false }
        if ($dependency.state_sha256 -ne 'absent' -and -not (Test-Sha $dependency.state_sha256)) { return $false }
        if (@($State.managed_files).Count -ne 2) { return $false }
        $proxy = @($State.managed_files | Where-Object { $_.relative_path -eq 'dxcompiler.dll' }) | Select-Object -First 1
        $payload = @($State.managed_files | Where-Object { $_.relative_path -eq 'AWOW Universal Female Generation/awow_ufg.dll' }) | Select-Object -First 1
        if ($null -eq $proxy -or $null -eq $payload -or $proxy.role -ne 'ufg_proxy' -or $payload.role -ne 'ufg_payload') { return $false }
        foreach ($managed in @($proxy,$payload)) {
            if ($managed.ownership -ne 'managed' -or -not (Test-Sha $managed.installed_sha256) -or [int64]$managed.installed_size_bytes -lt 0 -or $managed.present -isnot [bool]) { return $false }
        }
        if (-not $proxy.present -or $payload.present -ne ($State.status -eq 'managed_ufg') -or $proxy.restore.action -ne 'leave_managed_file' -or $payload.restore.action -ne 'remove_managed_file') { return $false }
        if ($State.foreign_cleanup.kind -ne 'none' -or @($State.foreign_cleanup.removed_paths).Count -ne 0 -or $State.foreign_cleanup.uninstall_policy -ne 'none' -or -not (Test-ValidRelative $State.foreign_cleanup.quarantine_relative_path)) { return $false }
        if ($null -eq $State.quarantined_files -or $State.created_utc -isnot [string] -or $State.updated_utc -isnot [string]) { return $false }
        return $true
    }
    catch { return $false }
}

function Get-UfgPairs([hashtable]$Context) {
    $pairs = New-Object Collections.Generic.List[object]
    foreach ($seed in @($Context.Manifest.compatibility.seeds | Where-Object { $_.state -eq 'recognized_ufg' })) {
        $files = @($seed.match.required_files)
        $proxy = $files | Where-Object { $_.relative_path -eq 'dxcompiler.dll' } | Select-Object -First 1
        $original = $files | Where-Object { $_.relative_path -eq 'dxcompiler_original.dll' } | Select-Object -First 1
        $payload = $files | Where-Object { $_.relative_path -eq 'AWOW Universal Female Generation/awow_ufg.dll' } | Select-Object -First 1
        $agpPayload = $files | Where-Object { $_.relative_path -eq 'AGP Native Hook/agp_parenthook.dll' } | Select-Object -First 1
        if ($proxy -and $original -and $payload -and $agpPayload) {
            $agpArtifact = @($Context.Manifest.artifacts | Where-Object { $_.id -eq 'agp-proxy' }) | Select-Object -First 1
            if ($agpArtifact) { [void]$pairs.Add([ordered]@{ proxy = ([string]$proxy.sha256).ToLowerInvariant(); original = ([string]$original.sha256).ToLowerInvariant(); payload = ([string]$payload.sha256).ToLowerInvariant(); agp_payload = ([string]$agpPayload.sha256).ToLowerInvariant(); agp_proxy = ([string]$agpArtifact.sha256).ToLowerInvariant() }) }
        }
    }
    [void]$pairs.Add([ordered]@{ proxy = '6406c83ce1d31415e6e2c013e222d9098219ea912fa541ce4ece8f7b23f07c44'; original = '40e381d1d0ccf3bd725e30914b07d3d0cdaa907900e4d194da0e9cbd41d06e65'; payload = '796afce9e724b3ec48cfa31e08469335b895b8dc661de7974660676e776d276e'; agp_payload = 'e6bb03805e7caa4392210fa45e3253de769d082ccd59087475a50c24b420071c'; agp_proxy = 'e8365d61ffd80b4d8fcaf4d6d79ac00c8373831a0a86e66647a4fc1e4cef2e58' })
    return $pairs.ToArray()
}

function Get-UfgClassification([hashtable]$Context) {
    $Context.UfgBlocked = $false
    $Context.UfgReason = ''
    $statePath = Get-ContainedPath $Context 'AWOW Universal Female Generation/ufg-install-state.json'
    $statePresent = Test-Path -LiteralPath $statePath
    $state = if ($statePresent) { Get-JsonObject $statePath } else { $null }
    if ($statePresent -and -not (Test-UfgStateShape $state)) { $Context.UfgBlocked = $true; $Context.UfgReason = 'UFG state is malformed; manual recovery is required'; return 'unknown_conflicting' }
    $pairs = @(Get-UfgPairs $Context)
    if ($statePresent) {
        foreach ($pair in $pairs) {
            $dependency = $state.agp_dependency
            if ($dependency.proxy_sha256.ToLowerInvariant() -ne $pair.agp_proxy -or $dependency.payload_sha256.ToLowerInvariant() -ne $pair.agp_payload -or $dependency.original_dxcompiler_sha256.ToLowerInvariant() -ne $pair.original) { continue }
            $active = Get-Observation $Context 'dxcompiler.dll'
            $original = Get-Observation $Context 'dxcompiler_original.dll'
            $exe = Get-Observation $Context 'ck3.exe'
            $proxyItem = @($state.managed_files | Where-Object { $_.relative_path -eq 'dxcompiler.dll' }) | Select-Object -First 1
            $payloadItem = @($state.managed_files | Where-Object { $_.relative_path -eq 'AWOW Universal Female Generation/awow_ufg.dll' }) | Select-Object -First 1
            $payloadObs = Get-Observation $Context 'AWOW Universal Female Generation/awow_ufg.dll'
            $agpPayloadObs = Get-Observation $Context 'AGP Native Hook/agp_parenthook.dll'
            $agpStateObs = Get-Observation $Context $Context.Manifest.target.state_relative_path
            $actualStateSha = if ($agpStateObs.exists) { $agpStateObs.sha256 } else { 'absent' }
            if ($active.sha256 -ne $pair.proxy -or $original.sha256 -ne $state.baseline.original_dxcompiler.sha256 -or $original.sha256 -ne $pair.original -or $exe.sha256 -ne $state.baseline.executable.sha256 -or $agpPayloadObs.sha256 -ne $pair.agp_payload -or $proxyItem.installed_sha256.ToLowerInvariant() -ne $pair.proxy -or $payloadItem.installed_sha256.ToLowerInvariant() -ne $pair.payload -or $payloadItem.present -ne ($state.status -eq 'managed_ufg') -or $dependency.state_sha256.ToLowerInvariant() -ne $actualStateSha) { continue }
            if ($state.status -eq 'managed_ufg' -and $payloadObs.sha256 -ne $pair.payload) { continue }
            if ($state.status -eq 'ufg_proxy_only' -and $payloadObs.exists) { continue }
            if ($agpStateObs.exists) {
                $agpState = Get-JsonObject (Get-ContainedPath $Context $Context.Manifest.target.state_relative_path)
                if (-not (Test-StateShape $agpState)) { continue }
                if ($agpState.release.id -ne 'agp' -or $agpState.release.version -notin @('1.1.0','1.1.1') -or
                    $agpState.target.game_id -ne 'crusader_kings_iii' -or $agpState.target.build_id -ne [string]$Context.Build.id -or
                    $agpState.target.profile_id -ne [string]$Context.Build.profile_id -or $agpState.target.distribution -ne [string]$Context.Build.distribution) { continue }
                $agpPayload = @($agpState.managed_files | Where-Object { $_.role -eq 'agp_payload' }) | Select-Object -First 1
                if ($agpState.baseline.original_dxcompiler.sha256 -ne $pair.original -or $null -eq $agpPayload -or $agpPayload.installed_sha256.ToLowerInvariant() -ne $pair.agp_payload -or $agpPayloadObs.sha256 -ne $agpPayload.installed_sha256.ToLowerInvariant()) { continue }
            }
            $Context.UfgReason = "valid UFG v2 $($state.status) layout; UFG is $(if($state.status -eq 'managed_ufg'){'active'}else{'disabled'})"
            $Context.UfgState = $state
            return 'recognized_ufg'
        }
        $Context.UfgBlocked = $true; $Context.UfgReason = 'UFG state or its native dependency drifted; manual recovery is required'; return 'unknown_conflicting'
    }
    $active = Get-Observation $Context 'dxcompiler.dll'
    $original = Get-Observation $Context 'dxcompiler_original.dll'
    $payloadObs = Get-Observation $Context 'AWOW Universal Female Generation/awow_ufg.dll'
    $agpPayloadObs = Get-Observation $Context 'AGP Native Hook/agp_parenthook.dll'
    foreach ($pair in $pairs) {
        if ($active.sha256 -eq $pair.proxy -and $original.sha256 -eq $pair.original -and $agpPayloadObs.sha256 -eq $pair.agp_payload -and ($payloadObs.sha256 -eq $pair.payload -or -not $payloadObs.exists)) {
            $Context.UfgReason = if ($payloadObs.exists) { 'exact manual UFG active layout without UFG state' } else { 'exact manual UFG disabled proxy without UFG state' }
            return 'recognized_ufg'
        }
    }
    if ($payloadObs.exists) { $Context.UfgBlocked = $true; $Context.UfgReason = 'UFG files are present but do not match a canonical native pair; manual recovery is required'; return 'unknown_conflicting' }
    return $null
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
            $original = Get-Observation $Context $Context.State.baseline.original_dxcompiler.relative_path
            $payloads = @($Context.State.managed_files | Where-Object { $_.role -eq 'agp_payload' })
            $payloadMatches = $false
            if ($payloads.Count -eq 1) {
                $payload = Get-Observation $Context $payloads[0].relative_path
                $payloadMatches = $payload.exists -and $payload.kind -eq 'file' -and $payload.sha256 -eq $payloads[0].installed_sha256
            }
            if ($active.exists -and $active.kind -eq 'file' -and $active.sha256 -eq $supportedOriginal -and
                $original.exists -and $original.kind -eq 'file' -and $original.sha256 -eq $Context.State.baseline.original_dxcompiler.sha256 -and $payloadMatches) {
                $Context.Classification = 'game_updated'
                return $Context.Classification
            }
        }
    }
    $ufg = Get-UfgClassification $Context
    if ($null -ne $ufg) {
        $Context.Classification = $ufg
        return $Context.Classification
    }
    if (-not $statePresent) {
        $active = Get-Observation $Context $Context.Manifest.target.active_dxcompiler_relative_path
        $original = Get-Observation $Context $Context.Manifest.target.original_dxcompiler_relative_path
        $payload = Get-Observation $Context 'AGP Native Hook/agp_parenthook.dll'
        if ($active.exists -and $active.kind -eq 'file' -and $active.sha256 -eq $Context.Build.original_dxcompiler_sha256 -and -not $original.exists -and -not $payload.exists) {
            $Context.Classification = 'known_clean'
            return $Context.Classification
        }
    }
    foreach ($seed in @($Context.Manifest.compatibility.seeds)) {
        if ($seed.state -eq 'managed_agp' -or $seed.state -eq 'game_updated') { continue }
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
            New-Item -ItemType Directory -Path (Split-Path -Parent $stagePath) -Force | Out-Null
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

function Get-LayoutFingerprint([hashtable]$Context) {
    $paths = @(
        'ck3.exe',
        [string]$Context.Manifest.target.active_dxcompiler_relative_path,
        [string]$Context.Manifest.target.original_dxcompiler_relative_path,
        [string]$Context.Manifest.target.state_relative_path,
        'AGP Native Hook/agp_parenthook.dll',
        'AWOW Universal Female Generation/awow_ufg.dll',
        'AWOW Universal Female Generation/ufg-install-state.json',
        'awow_ufg.log',
        'awow_ufg_dxcompiler_loader.log',
        'agp_dxcompiler_loader.log',
        'agp_parenthook.log'
    )
    $fingerprint = [ordered]@{}
    foreach ($relative in ($paths | Select-Object -Unique)) { $fingerprint[$relative] = Get-Observation $Context $relative }
    return $fingerprint
}

function Test-LayoutUnchanged([hashtable]$Context) {
    $before = $Context.LayoutFingerprint | ConvertTo-Json -Depth 16 -Compress
    $after = Get-LayoutFingerprint $Context | ConvertTo-Json -Depth 16 -Compress
    return $before -eq $after
}

function Test-SnapshotsUnchanged([hashtable]$Context) {
    foreach ($snapshot in $Context.Snapshots.Values) {
        $before = $snapshot.before | ConvertTo-Json -Depth 16 -Compress
        $after = Get-Observation $Context ([string]$snapshot.relative_path) | ConvertTo-Json -Depth 16 -Compress
        if ($before -ne $after) { return $false }
    }
    return $true
}

function Remove-StagedTransaction([hashtable]$Context) {
    $journalDir = Split-Path -Parent $Context.JournalPath
    if (Test-Path -LiteralPath $journalDir) { Remove-Item -LiteralPath $journalDir -Recurse -Force }
    if (Test-Path -LiteralPath $Context.JournalPath) { Remove-Item -LiteralPath $Context.JournalPath -Force }
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
    if ([IO.Path]::GetFileName($root) -ieq 'ck3.exe') { $root = Split-Path -Parent $root }
    elseif (Test-Path -LiteralPath (Join-Path $root 'binaries/ck3.exe') -PathType Leaf) { $root = Join-Path $root 'binaries' }
    $package = Get-FullPath $PackageRoot
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { Fail "TargetRoot must be an existing directory: $root" }
    if (-not (Test-Path -LiteralPath $package -PathType Container)) { Fail "PackageRoot must be an existing directory: $package" }
    $manifestPath = Join-Path $package 'Installer\release-manifest.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { Fail "Missing release manifest: $manifestPath" }
    $manifest = Get-JsonObject $manifestPath
    if ($null -eq $manifest -or $manifest.schema_version -ne 2 -or $manifest.kind -ne 'agp_release_manifest') { Fail 'Release manifest is not schema-v2.' }
    $build = $null
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
        UfgBlocked = $false
        UfgReason = ''
        UfgState = $null
        Classification = $null
        LayoutFingerprint = $null
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
    $profiles = @($Context.Manifest.target.supported_builds | Where-Object { ([string]$_.executable_sha256).ToLowerInvariant() -eq $exeObs.sha256 })
    if ($profiles.Count -ne 1) { Fail 'Executable must match exactly one supported CK3 profile.' }
    $Context.Build = $profiles[0]
    foreach ($relative in @('AWOW Universal Female Generation/ufg-install-state.json', 'AWOW Universal Female Generation/.ufg-journal', 'AWOW Universal Female Generation/.ufg-quarantine', 'AWOW Universal Female Generation/awow_ufg.dll', 'awow_ufg.log', 'awow_ufg_dxcompiler_loader.log')) { [void](Get-ContainedPath $Context $relative) }
    $statePath = Get-ContainedPath $Context $Context.Manifest.target.state_relative_path
    if ((Test-Path -LiteralPath $statePath) -and -not (Test-StateShape (Get-JsonObject $statePath))) {
        Fail 'Install state is invalid or unreadable; manual recovery is required.'
    }
    $ufgStatePath = Get-ContainedPath $Context 'AWOW Universal Female Generation/ufg-install-state.json'
    if ((Test-Path -LiteralPath $ufgStatePath) -and -not (Test-UfgStateShape (Get-JsonObject $ufgStatePath))) { Fail 'UFG install state is invalid or unreadable; manual recovery is required.' }
    foreach ($recovery in @('AWOW Universal Female Generation/.ufg-journal', 'AWOW Universal Female Generation/.ufg-quarantine')) {
        $recoveryPath = Get-ContainedPath $Context $recovery
        if (Test-Path -LiteralPath $recoveryPath) {
            if (-not (Get-Item -LiteralPath $recoveryPath -Force).PSIsContainer -or @(Get-ChildItem -LiteralPath $recoveryPath -Force).Count -gt 0) { Fail 'An incomplete UFG recovery transaction exists; manual recovery is required.' }
        }
    }
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
            'game_updated' { return 'ACCEPT_GAME_UPDATE' }
            'unknown_conflicting' { return 'I_UNDERSTAND_UNKNOWN_CONFLICT' }
        }
    }
    else {
        if ($Context.Classification -eq 'recognized_ufg') { return 'REMOVE_AGP_AND_UFG' }
        if ($Context.Classification -in @('unknown_conflicting', 'legacy_agp', 'game_updated')) { return 'I_UNDERSTAND_UNKNOWN_CONFLICT' }
    }
    return $null
}

function Get-ConfirmationPrompt([hashtable]$Context) {
    $key = "$Operation/$($Context.Classification)"
    switch ($key) {
        'install/managed_agp' { return @('Replace installed AGP?', 'AGP is already installed. Click OK to replace it with this version.') }
        'install/legacy_agp' { return @('Upgrade older AGP?', 'An older AGP installation was found. Click OK to upgrade it safely.') }
        'install/recognized_ufg' { return @('Remove UFG and install AGP?', 'AWOW UFG and its proxy were found. Click OK to remove UFG and install AGP.') }
        'install/game_updated' { return @('Use updated game files?', "The game installation updated CK3 after AGP was installed. Click OK to update AGP's saved original file.") }
        'install/unknown_conflicting' { return @('Unknown proxy found', 'An unrecognized proxy is installed. Click OK to preserve it in quarantine and install AGP.') }
        'uninstall/recognized_ufg' { return @('Remove AGP and UFG?', 'AWOW UFG and its proxy were found. Click OK to remove both UFG and AGP components.') }
        'uninstall/legacy_agp' { return @('Remove older AGP?', "An older AGP installation was found. Click OK to remove it and restore the game's file.") }
        'uninstall/game_updated' { return @('Remove changed AGP files?', 'CK3 files changed after AGP was installed. Click OK to preserve conflicts and continue.') }
        'uninstall/unknown_conflicting' { return @('Unknown proxy found', 'An unrecognized proxy is installed. Click OK to preserve it in quarantine and continue.') }
    }
    return $null
}

function Show-ConfirmationDialog([hashtable]$Context) {
    $prompt = Get-ConfirmationPrompt $Context
    if ($null -eq $prompt) { return $false }
    Add-Type -AssemblyName System.Windows.Forms
    $choice = [Windows.Forms.MessageBox]::Show(
        [string]$prompt[1],
        [string]$prompt[0],
        [Windows.Forms.MessageBoxButtons]::OKCancel,
        [Windows.Forms.MessageBoxIcon]::Warning
    )
    return $choice -eq [Windows.Forms.DialogResult]::OK
}

function Confirm-Transition([hashtable]$Context) {
    if ($Context.UfgBlocked) {
        $Context.Result = [ordered]@{ operation = $Operation; classification = $Context.Classification; decision = 'reject'; next_state = $Context.Classification; message = $Context.UfgReason }
        return $false
    }
    $expected = Get-ExpectedConfirmation $Context
    if ($null -eq $expected) { return $true }
    $answer = $Confirmation
    if ([string]::IsNullOrEmpty($answer) -and $Interactive) {
        if (Show-ConfirmationDialog $Context) { $answer = $expected }
    }
    if ($answer -ne $expected) {
        $Context.Result = [ordered]@{ operation = $Operation; classification = $Context.Classification; decision = 'abort'; message = 'Confirmation was cancelled or not supplied.' }
        return $false
    }
    return $true
}

function Add-InstallPlan([hashtable]$Context) {
    $activeRel = $Context.Manifest.target.active_dxcompiler_relative_path
    $originalRel = $Context.Manifest.target.original_dxcompiler_relative_path
    $payloadRel = 'AGP Native Hook/agp_parenthook.dll'
    $stateRel = $Context.Manifest.target.state_relative_path
    foreach ($rel in @($activeRel, $originalRel, $payloadRel, $stateRel, 'AWOW Universal Female Generation/awow_ufg.dll', 'AWOW Universal Female Generation/ufg-install-state.json', 'awow_ufg.log', 'awow_ufg_dxcompiler_loader.log')) { Add-Snapshot $Context $rel }
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
            if ((Get-Observation $Context $activeRel).exists) { Add-Quarantine $Context $activeRel 'file' 'recognized_awow_ufg' 'do_not_restore_after_awow_ufg_commit' }
            foreach ($relative in @('AWOW Universal Female Generation/awow_ufg.dll', 'AWOW Universal Female Generation/ufg-install-state.json')) {
                if ((Get-Observation $Context $relative).exists) { Add-Quarantine $Context $relative 'file' 'recognized_awow_ufg' 'do_not_restore_after_awow_ufg_commit' }
            }
            foreach ($log in @($Context.Manifest.safety.ufg_cleanup.foreign_logs)) {
                if ((Get-Observation $Context $log).exists) { Add-Quarantine $Context $log 'file' 'recognized_awow_ufg' 'do_not_restore_after_awow_ufg_commit' }
            }
            if ((Get-Observation $Context $payloadRel).exists) { Add-Quarantine $Context $payloadRel 'file' 'recognized_awow_ufg' 'do_not_restore_after_awow_ufg_commit' }
        }
        'game_updated' {
            Add-Quarantine $Context $originalRel 'file' 'unknown_displaced' 'preserve_for_uninstall'
        }
    }
    if ($Context.Classification -eq 'known_clean') {
        $original = Get-Observation $Context $originalRel
        if ($original.exists) { Fail 'Clean install refuses an existing original compiler.' }
        $active = Get-Observation $Context $activeRel
        if ($active.sha256 -ne ([string]$Context.Build.original_dxcompiler_sha256).ToLowerInvariant()) { Fail 'Clean install active compiler is not the supported game original.' }
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
    if ($Context.Classification -eq 'known_clean') { [void]$entries.Add((New-JournalEntry $Context $activeRel 'file' 'rename' "$($Context.StageRelative)/snapshot/dxcompiler.dll" 'game')) }
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
        '$schema' = 'https://any-gender-parenthook.invalid/schema/install-journal-v2.json'
        schema_version = 2
        kind = 'agp_install_journal'
        transaction_id = $Context.TransactionId
        operation = 'install'
        source_state = $Context.Classification
        target_state = 'managed_agp'
        phase = 'journal'
        target = [ordered]@{ game_id = 'crusader_kings_iii'; build_id = [string]$Context.Build.id; binaries_relative_path = 'binaries'; target_root_kind = 'ck3_game_binaries'; profile_id = [string]$Context.Build.profile_id; distribution = [string]$Context.Build.distribution }
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
        $foreign = [ordered]@{ kind = 'recognized_awow_ufg'; quarantine_relative_path = $Context.QuarantineRelative; removed_paths = @('AWOW Universal Female Generation/awow_ufg.dll', 'AWOW Universal Female Generation/ufg-install-state.json', 'awow_ufg.log', 'awow_ufg_dxcompiler_loader.log'); uninstall_policy = 'do_not_restore_awow_ufg' }
    }
    $state = [ordered]@{
        '$schema' = 'https://any-gender-parenthook.invalid/schema/install-state-v2.json'
        schema_version = 2
        kind = 'agp_install_state'
        status = 'managed_agp'
        transaction_id = $Context.TransactionId
        release = [ordered]@{ id = [string]$Context.Manifest.release.id; version = [string]$Context.Manifest.release.version; manifest_sha256 = $Context.ManifestHash }
        target = [ordered]@{ game_id = 'crusader_kings_iii'; build_id = [string]$Context.Build.id; binaries_relative_path = 'binaries'; executable_relative_path = 'ck3.exe'; target_root_kind = 'ck3_game_binaries'; profile_id = [string]$Context.Build.profile_id; distribution = [string]$Context.Build.distribution }
        baseline = [ordered]@{
            original_dxcompiler = [ordered]@{ relative_path = $originalRel; sha256 = $original.sha256; size_bytes = [int64]$original.size_bytes; ownership = 'game' }
            executable = [ordered]@{ relative_path = $exeRel; sha256 = $exe.sha256; size_bytes = [int64]$exe.size_bytes; ownership = 'game' }
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
        $ufgDir = Get-ContainedPath $Context 'AWOW Universal Female Generation'
        if ((Test-Path -LiteralPath $ufgDir -PathType Container) -and @(Get-ChildItem -LiteralPath $ufgDir -Force).Count -eq 0) { Remove-Item -LiteralPath $ufgDir -Force }
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
    if (-not (Test-SnapshotsUnchanged $Context)) {
        Remove-StagedTransaction $Context
        $Context.Result = [ordered]@{ operation = 'install'; classification = $Context.Classification; decision = 'reject'; next_state = $Context.Classification; transaction_id = $Context.TransactionId; message = 'Target changed during transaction planning; no files were changed.' }
        return
    }
    New-InstallJournal $Context
    if (-not (Test-SnapshotsUnchanged $Context)) {
        Remove-StagedTransaction $Context
        $Context.Result = [ordered]@{ operation = 'install'; classification = $Context.Classification; decision = 'reject'; next_state = $Context.Classification; transaction_id = $Context.TransactionId; message = 'Target changed after journaling; no files were changed.' }
        return
    }
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
        elseif ($Context.Classification -eq 'game_updated') {
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
    foreach ($rel in @($activeRel, $originalRel, $payloadRel, $stateRel, 'AWOW Universal Female Generation/awow_ufg.dll', 'AWOW Universal Female Generation/ufg-install-state.json')) { Add-Snapshot $Context $rel }
    foreach ($log in @($Context.Manifest.target.logs)) {
        if ([string]$log.owner -eq 'agp_runtime') { Add-Snapshot $Context $log.relative_path }
    }
    if ($Context.Classification -eq 'recognized_ufg') {
        foreach ($relative in @($activeRel, $payloadRel)) {
            if ((Get-Observation $Context $relative).exists) {
                Add-Quarantine $Context $relative 'file' 'recognized_awow_ufg' 'remove_after_uninstall_commit'
            }
        }
        foreach ($relative in @('AWOW Universal Female Generation/awow_ufg.dll', 'AWOW Universal Female Generation/ufg-install-state.json')) {
            if ((Get-Observation $Context $relative).exists) { Add-Quarantine $Context $relative 'file' 'recognized_awow_ufg' 'remove_after_uninstall_commit' }
        }
        foreach ($log in @($Context.Manifest.safety.ufg_cleanup.foreign_logs)) {
            if ((Get-Observation $Context $log).exists) {
                Add-Quarantine $Context $log 'file' 'recognized_awow_ufg' 'remove_after_uninstall_commit'
            }
        }
        $original = Get-Observation $Context $originalRel
        if (-not $original.exists -or $original.kind -ne 'file' -or $original.sha256 -ne ([string]$Context.Build.original_dxcompiler_sha256).ToLowerInvariant()) {
            Fail 'Cannot uninstall safely: the canonical game original is missing or unsupported.'
        }
        $Context.State = [ordered]@{
            target = [ordered]@{ build_id = [string]$Context.Build.id }
            baseline = [ordered]@{ original_dxcompiler = [ordered]@{ sha256 = $original.sha256 } }
            managed_files = @()
        }
        return
    }
    if ($null -eq $Context.State) {
        foreach ($relative in @($activeRel, $payloadRel)) {
            if ((Get-Observation $Context $relative).exists) {
                Add-Quarantine $Context $relative 'file' 'unknown_displaced' 'preserve_for_uninstall'
            }
        }
        $original = Get-Observation $Context $originalRel
        if (-not $original.exists -or $original.kind -ne 'file' -or $original.sha256 -ne ([string]$Context.Build.original_dxcompiler_sha256).ToLowerInvariant()) {
            Fail 'Cannot uninstall safely: the canonical game original is missing or unsupported.'
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
    [void]$entries.Add((New-JournalEntry $Context $Context.Manifest.target.original_dxcompiler_relative_path 'file' 'restore' "$($Context.StageRelative)/snapshot/dxcompiler_original.dll" 'game'))
    $foreign = [ordered]@{ kind = 'none'; allowed = $false; quarantine_relative_path = $Context.QuarantineRelative; remove_after_commit = $false; uninstall_policy = 'none' }
    if ($Context.Classification -eq 'recognized_ufg') {
        $foreign = [ordered]@{ kind = 'recognized_awow_ufg'; allowed = $true; quarantine_relative_path = $Context.QuarantineRelative; remove_after_commit = $true; uninstall_policy = 'remove_with_agp' }
    }
    $Context.Journal = [ordered]@{
        '$schema' = 'https://any-gender-parenthook.invalid/schema/install-journal-v2.json'
        schema_version = 2
        kind = 'agp_install_journal'
        transaction_id = $Context.TransactionId
        operation = 'uninstall'
        source_state = $Context.Classification
        target_state = 'known_clean'
        phase = 'journal'
        target = [ordered]@{ game_id = 'crusader_kings_iii'; build_id = [string]$Context.State.target.build_id; binaries_relative_path = 'binaries'; target_root_kind = 'ck3_game_binaries'; profile_id = [string]$Context.Build.profile_id; distribution = [string]$Context.Build.distribution }
        entries = $entries.ToArray()
        foreign_cleanup = $foreign
    }
    Write-JsonFile $Context.JournalPath $Context.Journal
}

function Invoke-Uninstall([hashtable]$Context) {
    Add-UninstallPlan $Context
    New-Item -ItemType Directory -Path (Get-ContainedPath $Context $Context.StageRelative) -Force | Out-Null
    if (-not (Test-SnapshotsUnchanged $Context)) {
        Remove-StagedTransaction $Context
        $Context.Result = [ordered]@{ operation = 'uninstall'; classification = $Context.Classification; decision = 'reject'; next_state = $Context.Classification; transaction_id = $Context.TransactionId; message = 'Target changed during transaction planning; no files were changed.' }
        return
    }
    New-UninstallJournal $Context
    if (-not (Test-SnapshotsUnchanged $Context)) {
        Remove-StagedTransaction $Context
        $Context.Result = [ordered]@{ operation = 'uninstall'; classification = $Context.Classification; decision = 'reject'; next_state = $Context.Classification; transaction_id = $Context.TransactionId; message = 'Target changed after journaling; no files were changed.' }
        return
    }
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
        if ($Context.Classification -eq 'recognized_ufg') {
            Remove-Exact $Context $Context.QuarantineRelative $true
            $ufgDir = Get-ContainedPath $Context 'AWOW Universal Female Generation'
            if ((Test-Path -LiteralPath $ufgDir -PathType Container) -and @(Get-ChildItem -LiteralPath $ufgDir -Force).Count -eq 0) { Remove-Item -LiteralPath $ufgDir -Force }
        }
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
    $ctx.LayoutFingerprint = Get-LayoutFingerprint $ctx
    if (-not (Confirm-Transition $ctx)) { exit (Write-Result $ctx) }
    try {
        if (-not (Test-LayoutUnchanged $ctx)) {
            $ctx.Result = [ordered]@{ operation = $Operation; classification = $ctx.Classification; decision = 'reject'; next_state = $ctx.Classification; message = 'Target changed after recognition or confirmation; no files were changed.' }
            exit (Write-Result $ctx)
        }
    }
    catch {
        $ctx.Result = [ordered]@{ operation = $Operation; classification = $ctx.Classification; decision = 'reject'; next_state = $ctx.Classification; message = 'Target changed after recognition or confirmation; no files were changed.' }
        exit (Write-Result $ctx)
    }
    if ($Operation -eq 'uninstall' -and $ctx.Classification -eq 'known_clean') {
        $ctx.Result = [ordered]@{ operation = 'uninstall'; classification = 'known_clean'; decision = 'no_op'; next_state = 'known_clean' }
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
