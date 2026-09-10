# AGP v1.0.2 Batch File Installer

This package contains the Any-Gender Parenthook batch/PowerShell installer and
uninstaller for Windows x64 with Steam Crusader Kings III `1.19.0.6`.

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
Steam compiler. If recognized UFG files are active, it asks before removing
UFG and AGP components together.

Keep the extracted folder together; the batch files require the `Installer`
folder and native files beside them. This release is intentionally unsigned.
`SHA256SUMS.txt` records the exact files in this package.
