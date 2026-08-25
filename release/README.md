# Any-Gender Parenthook release package

This is the Windows x64 AGP v1 package for the Steam Crusader Kings III
`1.19.0.6` build. It contains the proxy and payload DLLs, the schema-v1
installer contract, both script entry points, the Tkinter/Python engine, and a
GUI front end.

## Install

1. Close Crusader Kings III and make sure the package was downloaded from the
   project release page.
2. Verify the adjacent `.sha256` file before extracting the ZIP. The package
   also contains `SHA256SUMS.txt` for its individual files.
3. For the standard Steam location, run `Installer\install.bat` as needed by
   the selected Windows permissions. For Steam-library discovery and Browse,
   run `Installer\AGPInstaller.exe`. Use `Installer\AGPUninstaller.exe` to
   remove AGP and restore the recorded original compiler.
4. Accept a prompt only when the displayed CK3 path and compatibility state
   are understood. A typed confirmation is required for upgrades, UFG
   conversion, and unknown layouts.

The installer first validates CK3 is closed, the target is contained and not a
reparse path, and all hashes/state data are readable. A clean install renames
the original Steam `dxcompiler.dll` to `dxcompiler_original.dll` before
placing the AGP proxy. The original DLL is never overwritten.

## Uninstall and recovery

Use the matching GUI uninstall action or `Installer\uninstall.bat`. Managed
uninstall restores the recorded Steam compiler only after a hash check and
removes AGP-owned files and exact AGP runtime logs. Unknown files in `AGP
Native Hook` are preserved. Recognized AWOW UFG conversion is deliberately not
restored by AGP uninstall.

If an operation reports rollback or manual recovery, keep the journal and
quarantine contents, do not start CK3, and follow the displayed recovery path.
Keep `agp_dxcompiler_loader.log` and `agp_parenthook.log` when reporting a
native load failure.

## Scope

This package does not include the disposable native test mod, the optional AGP
Dynastic Priority addon, native source, reverse-engineering tools, script
documentation, or repository/run metadata. See `Installer/release-manifest.json`
and `SIGNING.md` for the compatibility and signing boundaries.
