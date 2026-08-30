# Any-Gender Parenthook v1.0.1

This is the Windows x64 AGP package for Steam Crusader Kings III `1.19.0.6`.
Keep the extracted folder together: the four launchers at this folder's top
level use the files under `Installer` and must not be moved out individually.

## Install

1. Close Crusader Kings III.
2. Extract the entire ZIP.
3. Run `AGP-Installer.exe` to search Steam libraries or browse to `ck3.exe`.
   If CK3 is installed at Steam's standard location, `Install AGP.bat` is the
   readable script alternative.
4. Confirm that the displayed CK3 path is correct. Upgrades, recognized AWOW
   UFG conversion, and unknown layouts require an explicit confirmation.

The installer validates the game build and file hashes before changing
anything. On a clean install it renames Steam's `dxcompiler.dll` to
`dxcompiler_original.dll`, then installs AGP's proxy and
`AGP Native Hook\agp_parenthook.dll`. File size is informational only; it is
not used to decide which DLL is the original.

## Uninstall

Run `AGP-Uninstaller.exe`, or use `Uninstall AGP.bat` for the standard Steam
location. Uninstall verifies the persistent installation state, removes only
AGP-owned files and exact AGP logs, and restores the recorded Steam compiler.
Unknown or modified files are preserved rather than silently deleted.

If an operation reports rollback or manual recovery, do not start CK3 and do
not delete the journal or quarantine contents. Preserve
`agp_dxcompiler_loader.log` and `agp_parenthook.log` when reporting a load
failure.

## Package scope

This package intentionally excludes the native test mod, the optional AGP
Dynastic Priority addon, native source, reverse-engineering tools, script
documentation, and repository metadata. `Installer` contains the auditable
installer engines and contract used by the four top-level launchers; end users
normally do not need to open it.

Version 1.0.1 is intentionally unsigned. Verify the ZIP with its adjacent
`.sha256` file or use the included `SHA256SUMS.txt` for individual files.
