# Release tooling (maintainers only)

This repository folder is not the end-user download. It contains the scripts,
documentation sources, and launcher assets used to assemble and audit the
release ZIPs.

The release builder creates three end-user downloads:

- `AGP v1.1.0 Base Files (Manual Install).zip`
- `AGP v1.1.0 Batch File Installer.zip`
- `AGP v1.1.0 EXE Installer.zip`

Each archive contains only its selected installation method, the shared native
payload, a focused README, the MIT license, and internal checksums.

Maintainers use `build-release.ps1` to create local smoke-test candidates. The
canonical release ZIPs are built from `main` by GitHub Actions with the pinned
native toolchain in `Native Hook/toolchain.json`. The end-user README source is
the matching `README_MANUAL.md`, `README_BATCH.md`, or `README_EXE.md` file.
