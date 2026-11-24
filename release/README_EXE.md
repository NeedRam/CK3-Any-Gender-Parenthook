> CK3 1.21.0.3 only. Compatibility uses exact verified game-file hashes, regardless of launcher storefront metadata. The optional Dynastic Priority add-on is not included.

# AGP v1.1.0 EXE Installer

This package contains the Any-Gender Parenthook graphical installer and
uninstaller for Windows x64 with Crusader Kings III `1.21.0.3`.

## Install

1. Close Crusader Kings III and extract the entire ZIP.
2. Run `AGP-Installer.exe`.
3. Let it search Steam libraries or browse to `ck3.exe`, then confirm the
   displayed CK3 path and any requested safe transition.

The installer validates the game build and exact file hashes before changing
anything. It safely handles supported upgrades and recognized AWOW UFG
layouts. Unknown or modified proxies are preserved rather than silently
deleted.

## Uninstall

Close CK3 and run `AGP-Uninstaller.exe`. The uninstaller verifies AGP's
recorded state, removes only recognized AGP files and logs, and restores the
recorded original game compiler. If recognized UFG files are active, it asks before
removing UFG and AGP components together.

Keep the extracted folder together; the EXEs require the `Installer` manifest
and native files beside them. This release is intentionally unsigned.
`SHA256SUMS.txt` records the exact files in this package.
