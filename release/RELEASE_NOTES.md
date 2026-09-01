# v1.0.2 release

This unsigned Windows x64 maintenance release of Any-Gender Parenthook targets
Crusader Kings III `1.19.0.6`.

## Changed since v1.0.1

- replaced typed confirmation phrases with short OK/Cancel dialogs in both the
  graphical and PowerShell/BAT front ends;
- added exact recognition of the published AWOW UFG v1.0.0 proxy and payload,
  including UFG installed over a managed AGP state;
- made installation remove recognized UFG components before installing AGP;
- allowed the uninstaller to remove recognized AGP and UFG components together
  after explicit confirmation, then restore Steam's original compiler;
- normalized capitalization in displayed default Steam and CK3 paths;
- corrected PowerShell directory snapshot restoration so a failed UFG
  conversion rolls back to the original folder layout;
- updated all DLL and installer file-version metadata to `1.0.2.0`.

Unknown or modified proxies remain protected through hash-based recognition and
lossless quarantine. This release is intentionally unsigned. Verify the ZIP
with its adjacent `.sha256` file or use the bundled `SHA256SUMS.txt`.
