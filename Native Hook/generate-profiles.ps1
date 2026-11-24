[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
$document = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'profiles/ck3-1.21.0.3.json') -Raw | ConvertFrom-Json
if ($document.schema_version -ne 1 -or $document.release_version -ne '1.1.0') { throw 'Unsupported native profile document.' }
$lines = [Collections.Generic.List[string]]::new()
$lines.Add('// Generated from profiles/ck3-1.21.0.3.json. Do not edit.')
$lines.Add('#pragma once')
$lines.Add('namespace agp {')
$index = 0
foreach ($profile in $document.profiles) {
    if ($profile.profile_id -notmatch '^[A-Za-z0-9._-]+$' -or $profile.executable_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid native profile identity.' }
    $lines.Add("inline const NativeSite kSites$index[] = {")
    foreach ($site in $profile.sites) {
        if ($site.id -notmatch '^[a-z_]+$' -or $site.original -notmatch '^[0-9a-f ]+$') { throw 'Invalid native site.' }
        $resume = 0
        if ($site.PSObject.Properties.Name -contains 'resume_offset') { $resume = [int]$site.resume_offset }
        $lines.Add(('{{"{0}","{1}","{2}",{3},"{4}",{5},"{6}",{7}}},' -f $site.id,$site.module,$site.kind,$site.rva,$site.original,$site.patch_offset,$site.replacement,$resume))
    }
    $lines.Add('};')
    $lines.Add("inline const NativeCall kCalls$index[] = {")
    foreach ($call in $profile.call_targets) {
        $lines.Add(('{{"{0}",{1},{2},"{3}"}},' -f $call.id,$call.call_rva,$call.target_rva,$call.prologue))
    }
    $lines.Add('};')
    $index++
}
$lines.Add('inline const NativeProfile kProfiles[] = {')
$index = 0
foreach ($profile in $document.profiles) {
    $o = $profile.offsets
    $lines.Add(('{{"{0}","{1}","{2}",{{{3},{4},{5},{6},{7},{8},{9}}},{{{11},{12}}},kSites{10},sizeof(kSites{10})/sizeof(NativeSite),kCalls{10},sizeof(kCalls{10})/sizeof(NativeCall)}},' -f $profile.profile_id,$profile.distribution,$profile.executable_sha256,$o.character_id,$o.gender,$o.family_data,$o.mother,$o.father,$o.real_father_override,$o.real_mother_override,$index,$profile.parent_tokens.father,$profile.parent_tokens.mother))
    $index++
}
$lines.Add('};')
$lines.Add('}')
[IO.File]::WriteAllLines($OutputPath,$lines,[Text.UTF8Encoding]::new($false))
