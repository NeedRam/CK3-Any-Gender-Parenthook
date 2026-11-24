# Any-Gender Parenthook - Native Hook

This directory is the native runtime component of Any-Gender Parenthook (AGP). It contains the DXCompiler proxy loader, the AGP payload DLL, a disposable CK3 test mod, and the reverse-engineering helpers used to maintain version-specific patches.

The Native Hook is not the AGP script layer and is not a complete standalone gameplay mod. The future AGP script mod will provide the player-facing framework behavior; this directory provides the native CK3 support that makes gender-independent native parent roles possible.

## What it provides

The payload removes or redirects CK3 gender checks around the native parent paths currently required by AGP:

- Runtime `set_father`, `set_real_father`, `set_mother`, and `set_real_mother` paths
- Selected `create_character` and `make_pregnant` parent/carrier paths
- History-character parent validation
- Save/load reconstruction of native parent roles
- Role-aware reconstruction for female fathers and male mothers
- Explicit serialization of ordinary parent roles alongside distinct real-parent overrides
- Role-aware native parent and grandparent recognition for `is_close_family_of`

The Native Hook changes CK3's native parent-role validation, pregnancy gates, persistence, and close-family recognition. It does not decide when pregnancy occurs, which partners or carriers are selected, how dynasties are handled, or what script API the AGP framework exposes.

## Compatibility

Version 1.1.0 targets Windows x64 CK3 `1.21.0.3`. Binary audit and native gameplay acceptance passed for the recorded executable hash. The profile name records the inspected installation's GOG metadata; selection uses the executable hash, so identical files do not need separate Steam/GOG gameplay runs. Different or unknown executable hashes are rejected even with manual installation. AGP v1.0.2 remains the separate release for CK3 1.19.0.6.

The payload performs a signature preflight before writing patches. Each required original instruction context must match its profile address and occur exactly once in `.text`; reconstruction call targets and continuation bytes are also checked. If a preflight check fails, the payload logs the failure and makes no patch writes. All writes and relay allocations are staged before game-code mutation. A failed write stops the transaction and restores and verifies the original bytes. Exit without saving after any write or rollback failure; a failed rollback is reported explicitly.

## Runtime architecture

The loader uses CK3's shipped `dxcompiler.dll` proxy route:

1. The original game `dxcompiler.dll` is renamed to `dxcompiler_original.dll`.
2. The AGP-built `dxcompiler.dll` takes the original filename and exports `DxcCreateInstance` and `DxcCreateInstance2`.
3. Those exports are forwarded to the untouched original DXCompiler DLL.
4. A background loader thread loads `AGP Native Hook\agp_parenthook.dll` beside it.
5. The payload starts its patch thread, scans CK3's `.text` section, performs preflight, and applies the native patches.

## Source layout

```text
Native Hook\
  build.ps1                         # Builds the loader and payload
  dxcompiler_proxy.def              # DXCompiler proxy exports
  src\
    agp_parent_hook.cpp             # DLL entrypoint and patch coordinator
    agp_patch_runtime.cpp/.h        # Scanning, memory writes, branches, logging
    agp_close_family.cpp/.h         # Role-aware close-family recognition
    agp_parent_roles.cpp/.h         # Native parent-role reconstruction
    agp_history.cpp/.h               # History parent validation
    agp_female_father.cpp/.h         # Female-father runtime, pregnancy, persistence
    agp_male_mother.cpp/.h           # Male-mother runtime, pregnancy, persistence
    agp_dxcompiler_loader.cpp        # DXCompiler proxy and payload loader
  native_test_mod\                  # Disposable acceptance-test mod
  tools\ghidra\                    # Read-only reverse-engineering helpers
  build\                            # Build outputs
```

The gender-specific translation units intentionally keep the related runtime, pregnancy, and persistence patches together. `agp_parent_hook.cpp` only coordinates the modules and owns the DLL entrypoint.

## Building

Requirements:

- Windows x64
- Visual Studio 2022 x64 build tools with the MSVC and SDK versions pinned in `toolchain.json`
- The AGP Native Hook source tree

From this directory, run:

```powershell
.\build.ps1
```

The build produces:

```text
build\dxcompiler.dll
build\AGP Native Hook\agp_parenthook.dll
```

The script builds all payload translation units as one DLL, builds the DXCompiler proxy separately, and removes compiler intermediates from `build\` after a successful build.

## Installation for maintainer testing

Close CK3 before changing the game binaries. In the CK3 `binaries` directory, make a reversible backup by renaming the original file:

```text
dxcompiler.dll  ->  dxcompiler_original.dll
```

Copy the two build outputs into the same directory:

```text
Crusader Kings III\binaries\
  ck3.exe
  dxcompiler.dll
  dxcompiler_original.dll
  AGP Native Hook\
    agp_parenthook.dll
```

The loader expects the original DLL to have exactly the `dxcompiler_original.dll` name and expects the payload at exactly `AGP Native Hook\agp_parenthook.dll`.

To roll back / uninstall, close CK3, remove the AGP proxy and payload, and rename `dxcompiler_original.dll` back to `dxcompiler.dll`.

## Logs and failure handling

Both DLLs write logs beside `ck3.exe`:

- `agp_dxcompiler_loader.log` - original DXCompiler loading and payload loading
- `agp_parenthook.log` - payload discovery, preflight, and patch results

For a valid matching executable, the loader log should show the original DXCompiler and payload loading successfully, followed by payload patch messages. If a signature count or address check fails, preserve the log and do not save or continue the test session as though the patch loaded successfully.

## Test mod

`native_test_mod\` is a disposable standalone CK3 test mod. It contains targeted history fixtures, debug events, interactions, and localization for checking the native behavior without requiring the future AGP script mod.

The test fixtures cover:

- Female-father setter and real-father paths
- Male-mother setter and real-mother paths
- Native parent creation and pregnancy/carrier paths
- Parent and grandparent scope resolution
- Bidirectional `is_close_family_of` recognition
- Native parent persistence across save/load
- History loading with male mothers and female-fathers

Run `test.ps1` for native executable tests, including emitted machine-code stubs and write-failure rollback. Run `python tools/audit_binary.py <ck3.exe>` for the read-only PE audit. `profiles/ck3-1.21.0.3.json` is the canonical source of executable identities, offsets, original bytes, and resolved call targets; `generate-profiles.ps1` generates the compiled header. No installed game files are inputs to the normal build.

See [`native_test_mod\README.md`](native_test_mod/README.md) for fixture IDs, installation details, and the required UI, log, and save/load checks. A successful DLL build is not gameplay validation; run the relevant fixtures on the matching CK3 version before treating a behavior as verified.

## Reverse-engineering helpers

`tools\ghidra\` contains read-only scripts for future signature work:

- `FindParentValidation.java` finds the parent-sex validation string and its cross-references.
- `FindGenderChecks.java` reports likely comparisons against the character gender field.
- `InspectFunction.java` prints a bounded disassembly for a candidate function.
- `run_ghidra_analysis.cmd` provides the shared headless runner.

See [`tools\ghidra\README.md`](tools/ghidra/README.md) for configuration and usage. These tools identify candidates; they do not modify CK3 or automatically prove that a candidate is safe to patch.

## Validation standard

For a new CK3 build or a substantial payload change, validate in separate stages:

1. Confirm the C++ payload and DXCompiler proxy build cleanly.
2. Confirm every signature resolves exactly as expected and inspect the payload log.
3. Start CK3 with the disposable test mod and inspect `error.log` and `database_conflicts.log`.
4. Check native parent scopes and UI data immediately after creation.
5. Save, reload, and repeat the relevant parent, grandparent, and close-family checks.
6. Record the exact CK3 executable version and fixture results before publishing.

## Release acceptance

`release/validation.json` tracks the required in-game scenarios. `release/check-release.py` prevents canonical packaging until every supported executable profile and its native-package acceptance evidence are complete. Incomplete local candidates require the explicit `-AllowIncompleteValidation` release-builder option and carry an incomplete-candidate notice.

Distinct real-parent reassignment must be tested again after save/reload: a runtime scope check alone cannot prove that the reciprocal-child reconstruction preserves it.

The 1.21 serializer writes ordinary `father` and `mother` IDs in `family_data`
through CK3's persistent writer; the matching reader consumes those fields before
reciprocal-child reconstruction. This uses the native text/binary serialization
primitives; binary-save acceptance still requires evidence. The real-parent
override fields remain separate. Older saves that already lost ambiguous role
information cannot be repaired from that missing information alone.
