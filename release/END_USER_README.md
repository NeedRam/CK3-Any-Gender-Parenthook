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

## Manual installation (advanced users)

Use these steps only for a clean Steam installation where the game's `binaries`
folder contains Steam's original `dxcompiler.dll` and does not already contain
`dxcompiler_original.dll`. If a backup already exists, another `dxcompiler.dll`
proxy is installed, or AGP/UFG is being upgraded or converted, use
`AGP-Installer.exe` instead.

1. Close Crusader Kings III.
2. Open the game's `binaries` folder. The standard Steam location is
   `C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\binaries`.
3. Rename the existing Steam `dxcompiler.dll` to `dxcompiler_original.dll`.
   Never overwrite or delete an existing `dxcompiler_original.dll`.
4. Copy the package's `dxcompiler.dll` into `binaries`.
5. Copy the package's entire `AGP Native Hook` folder into `binaries`. The final
   payload path must be
   `...\Crusader Kings III\binaries\AGP Native Hook\agp_parenthook.dll`.
6. Start CK3. A successful load creates `agp_dxcompiler_loader.log` and
   `agp_parenthook.log` in `binaries`.

The included `AGP-Uninstaller.exe` recognizes the package's exact manual layout
and remains the safest way to remove AGP.

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
