# v1.0.1 release

This unsigned Windows x64 maintenance release of Any-Gender Parenthook targets
Crusader Kings III `1.19.0.6`.

## Changed since v1.0.0

- pinned canonical native release builds to GitHub's `windows-2022` runner,
  MSVC `14.44.35207`, and Windows SDK `10.0.22621.0`;
- made the GitHub Actions build from `main` the canonical release artifact;
- marked locally assembled packages as smoke-test candidates in their
  provenance instead of treating them as publication artifacts;
- preserved exact recognition of the published v1.0.0 CI binaries for safe
  upgrades, including installations that were copied manually without state;
- updated all DLL and installer file-version metadata to `1.0.1.0`.

The transactional installer behavior is unchanged: Steam's original
`dxcompiler.dll` is preserved, unknown files are quarantined rather than
deleted, and uninstall restores the recorded pre-install layout.

This release is intentionally unsigned. Verify the ZIP with its adjacent
`.sha256` file or use the bundled `SHA256SUMS.txt`. SignPath preparation remains
documented in `SIGNING.md`, but no Authenticode signature is claimed for
v1.0.1.
