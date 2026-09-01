# Release tooling (maintainers only)

This repository folder is not the end-user download. It contains the scripts,
documentation sources, and launcher assets used to assemble and audit the
release ZIP.

End users download `Any-Gender-Parenthook-v1.0.2-win64.zip` from GitHub
Releases. After extraction, its top level contains:

- `AGP-Installer.exe`
- `AGP-Uninstaller.exe`
- `Install AGP.bat`
- `Uninstall AGP.bat`
- `README.md`

Maintainers use `build-release.ps1` to create local smoke-test candidates. The
canonical release ZIP is built from `main` by GitHub Actions with the pinned
native toolchain in `Native Hook/toolchain.json`. The end-user README source is
`END_USER_README.md`; it is copied to the package root as `README.md`.
