# AGP v1.0.2 Base Files (Manual Install)

This package contains only the Any-Gender Parenthook native files for a manual
installation on Windows x64 with Steam Crusader Kings III `1.19.0.6`.

Use these steps only when the game's `binaries` folder contains Steam's
original `dxcompiler.dll` and does not contain `dxcompiler_original.dll`. For
an upgrade, an existing proxy, or an AGP/UFG installation, use the EXE or batch
installer package instead.

## Install

1. Close Crusader Kings III.
2. Open the game's `binaries` folder. The standard location is
   `C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\binaries`.
3. Rename Steam's existing `dxcompiler.dll` to `dxcompiler_original.dll`.
   Never overwrite or delete an existing `dxcompiler_original.dll`.
4. Copy this package's `dxcompiler.dll` into `binaries`.
5. Copy the entire `AGP Native Hook` folder into `binaries`. The final payload
   path must be `binaries\AGP Native Hook\agp_parenthook.dll`.
6. Start CK3. A successful load creates `agp_dxcompiler_loader.log` and
   `agp_parenthook.log` in `binaries`.

## Manual removal

Close CK3, delete AGP's `dxcompiler.dll` and
`AGP Native Hook\agp_parenthook.dll`, remove `AGP Native Hook` only if it is
empty, then rename `dxcompiler_original.dll` back to `dxcompiler.dll`. Do this
only if the files still match this installation and no other proxy depends on
them.

This release is intentionally unsigned. `SHA256SUMS.txt` records the exact
files in this package.
