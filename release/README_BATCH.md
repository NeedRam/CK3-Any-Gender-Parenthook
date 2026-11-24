> CK3 1.21.0.3 only. Compatibility uses exact verified game-file hashes, regardless of launcher storefront metadata. The optional Dynastic Priority add-on is not included.

# AGP v1.1.0 Batch File Installer

This package contains the Any-Gender Parenthook batch/PowerShell installer and
uninstaller for Windows x64 with Crusader Kings III `1.21.0.3`.

## Install

1. Close Crusader Kings III and extract the entire ZIP.
2. Run `Install AGP.bat`.
3. Review the detected standard Steam path and confirm any requested safe
   transition.

The installer validates the game build and exact file hashes before changing
anything. It safely handles supported upgrades and recognized AWOW UFG
layouts. Unknown or modified proxies are preserved rather than silently
deleted.

## Uninstall

Close CK3 and run `Uninstall AGP.bat`. The uninstaller verifies AGP's recorded
state, removes only recognized AGP files and logs, and restores the recorded
original game compiler. If recognized UFG files are active, it asks before removing
UFG and AGP components together.

Keep the extracted folder together; the batch files require the `Installer`
folder and native files beside them. This release is intentionally unsigned.
`SHA256SUMS.txt` records the exact files in this package.

For GOG or another installation path, pass `-TargetRoot "D:\Games\Crusader Kings III\binaries"` to either batch entrypoint. The path may also identify the game directory or `ck3.exe`. The executable hash determines compatibility.
