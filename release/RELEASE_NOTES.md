# v1.0.0 draft release

This is the first unsigned, auditable Windows x64 release of Any-Gender
Parenthook. It targets Crusader Kings III `1.19.0.6` and includes:

- schema-v1 state, journal, compatibility, and package manifest;
- independent BAT/PowerShell and Python/Tkinter installer engines;
- clean install, managed uninstall, upgrade, unknown-conflict, Steam-update,
  and recognized AWOW UFG safety transitions;
- SHA-256 package checksums and GitHub build provenance.

The native payload is version-specific. Test the intended install/uninstall
matrix before using it with an active campaign. Authenticode signing is not
claimed for this release; the future SignPath path is documented in
`SIGNING.md`.
