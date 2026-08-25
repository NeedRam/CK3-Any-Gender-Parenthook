# AGP installer contract v1

This directory is the shared interface for the independent BAT/PowerShell and Python/Tkinter engines. The engines may have different UI and implementation details, but they must make the same classification, ownership, transition, and rollback decisions.

## Canonical files

- `../release-manifest.json` is the package manifest. It identifies the Windows x64 target, supported CK3 build, payload hashes, preserved Steam file, package exclusions, and safety confirmations.
- `release-manifest.schema.json` validates that manifest.
- `install-state.schema.json` validates the committed state at `AGP Native Hook/agp-install-state.json`.
- `install-journal.schema.json` validates the in-flight journal under `AGP Native Hook/.agp-journal/`.
- `state-transitions.json` is the authoritative state/action matrix.
- `package-layout.json` is the package inventory and target path policy.
- `../fixtures/scenarios.json` is the shared destructive-state fixture matrix. It is disposable test input, not a live target.
- `compatibility-evidence.schema.json` validates the evidence shape, and `../fixtures/compatibility-evidence.json` records the exact repository and installed-file observations used to seed v1.

All paths in these files use `/` and are relative to the declared root. Engines must reject absolute paths, drive-qualified paths, dot segments, reparse-point targets/ancestors, and any resolved path outside the selected CK3 `binaries` directory. A path is not authorized merely because it has a familiar basename.

## Runtime/package boundary

The package ships exactly the AGP proxy at `dxcompiler.dll` and payload at `AGP Native Hook/agp_parenthook.dll`, plus the contract and phase-2 entrypoints. On a clean install, the active Steam `dxcompiler.dll` is transactionally renamed to `dxcompiler_original.dll` before the AGP proxy is placed; an existing original is never overwritten. `ck3.exe` is never modified. The exact AGP runtime logs are removed on managed uninstall, while unknown contents under `AGP Native Hook` remain preserved. `native_test_mod`, AGP Dynastic Priority, native source/tools, script docs, repository metadata, and Lunacy control files are excluded by the package layout.

The target is the standard Steam CK3 `binaries` directory. The v1 native payload is gated to CK3 `1.19.0.6` and the seeded executable hash. File size is recorded as informational metadata; SHA-256 is the identity check.

## Classification precedence

Classify only after the preflight guards and before any stage/mutation. A valid schema-v1 state with matching managed hashes wins over static compatibility seeds. Then use exact-hash clean/legacy seeds, the exact AWOW UFG hash/path seed, and the exact Steam-updated seed. Anything else is `unknown_conflicting`.

- `known_clean`: the Steam executable and active compiler match a clean seed; no AGP state/payload is present.
- `managed_agp`: state is valid and every managed path has the recorded hash and ownership.
- `legacy_agp`: a known manual/older AGP layout is present without a valid state.
- `recognized_ufg`: the current AWOW UFG chained-loader proxy hash, canonical original hash, exact `AWOW Universal Female Generation/awow_ufg.dll` hash, and coexisting AGP payload hash all match. A generic foreign folder is not UFG.
- `steam_updated`: the exact state-plus-supported-Steam hash layout identifies a newly supported active original replacing a stale state-recorded backup.
- `unknown_conflicting`: fallback for all unrecognized or contradictory layouts.

Unknown conflict, invalid state, and manual recovery are non-mutating by default. `steam_updated` prompts with `ACCEPT_STEAM_UPDATE` before quarantining the stale state-recorded original and rebaselining to the newly supported original; a declined prompt is a zero-write abort. Unrecognized drift remains conservative and lossless.

## Transaction protocol

Both engines implement the same six observable boundaries:

1. **Validate**: close-CK3 check, target/ancestor reparse checks, path containment, compatibility classification, state/journal parsing, and complete before-hash inventory.
2. **Stage**: copy package artifacts and snapshots/quarantine entries into paths inside the target; never treat a staged copy as committed.
3. **Journal**: write a schema-v1 journal with transaction ID, source/target state, before observations, ownership, and intended operations. Flush it before mutation.
4. **Mutate**: perform only journaled operations. A clean install first renames the hash-checked active Steam compiler to `dxcompiler_original.dll`; only then may the AGP proxy occupy `dxcompiler.dll`.
5. **Verify**: recalculate every expected artifact/state hash and recheck ownership/path containment. Any mismatch enters rollback.
6. **Commit/rollback**: publish state only after verification, then remove the journal. On any earlier failure restore the preflight snapshot/quarantine and retain the journal until rollback is verified. If rollback cannot be verified, mark `manual_recovery_required` and delete nothing further.

## Destructive boundaries

- A legacy AGP install prompts with the exact token `UPGRADE_AGP_IN_PLACE`; decline is a zero-write abort.
- An unknown layout requires `I_UNDERSTAND_UNKNOWN_CONFLICT` for both install and uninstall. Every displaced or mismatched unknown file/directory is quarantined losslessly with its original relative path, SHA-256, size, and restore metadata. Unknown files are never silently deleted.
- Recognized AWOW UFG conversion requires `CONVERT_UFG_TO_AGP` and an explicit warning. It is the only recursive foreign-folder removal allowed: quarantine the exact `AWOW Universal Female Generation` directory and the exact `awow_ufg.log` and `awow_ufg_dxcompiler_loader.log`, install and verify AGP, then remove that quarantine after AGP commit. If AGP fails, restore the quarantine. AWOW UFG is deliberately not restored by a later AGP uninstall.
- Managed uninstall is allowed only when state-owned hashes still match. It restores the hash-checked Steam compiler to `dxcompiler.dll`, removes the two managed AGP artifacts, the exact `agp_dxcompiler_loader.log` and `agp_parenthook.log`, and state (state last), while preserving unknown contents under `AGP Native Hook`, unknown quarantine, and all other unmanaged paths. A mismatched unknown file requires the typed override and quarantine before removal.

No transition in `state-transitions.json` has an implicit destructive action: every mutating transition names its confirmation, scope, preservation/quarantine policy, and rollback result.
