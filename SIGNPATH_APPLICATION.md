# SignPath Foundation application package

This is the maintainer-ready application record for Any-Gender Parenthook. Submission and GitHub authorization must be completed personally by the repository owner; no credential, private key, or password should be shared or committed here.

## Project

- Project name: Any-Gender Parenthook
- Repository: https://github.com/NeedRam/CK3-Any-Gender-Parenthook
- Unsigned prerequisite release: https://github.com/NeedRam/CK3-Any-Gender-Parenthook/releases/tag/v1.0.0
- License: [MIT](LICENSE)
- Privacy policy: [PRIVACY.md](PRIVACY.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Code signing policy and roles: [SIGNING.md](SIGNING.md)

AGP is an offline Windows x64 native hook for Crusader Kings III. It installs a small `dxcompiler.dll` proxy and `AGP Native Hook/agp_parenthook.dll`, preserving and restoring Steam's original compiler through two independent transactional installer engines. It performs no telemetry or network communication.

## Build and release evidence

- Workflow: `.github/workflows/release-draft.yml`
- Local reproducible builder: `release/build-release.ps1`
- Contract and exact hashes: `Installer/release-manifest.json`
- Installer state/transaction schemas: `Installer/spec/`
- Automated state-transition tests: `Installer/python/tests/`
- Unsigned v1 package: `Any-Gender-Parenthook-v1.0.0-win64.zip`
- GitHub build-provenance attestation was generated for the published release.

The package excludes the native test mod, native source/tools, CK3 script documentation, and the optional Dynastic Priority addon. The four future signing subjects are `AGP-Installer.exe`, `AGP-Uninstaller.exe`, `dxcompiler.dll`, and `AGP Native Hook/agp_parenthook.dll`. All carry `Any-Gender Parenthook` product metadata and the same release version.

## Maintainer submission checklist

1. Publish the audited unsigned v1.0.0 release and verify its ZIP checksum and GitHub provenance attestation.
2. Enable multi-factor authentication on GitHub now and on the SignPath account when invited.
3. Submit the SignPath Foundation open-source application using the project and release links above.
4. Authorize SignPath's GitHub connection and configure source-origin verification.
5. Configure the authors/committers, reviewers, and approvers listed in `SIGNING.md`.
6. Require a manual approver decision for every signing request.
7. After approval, add the SignPath workflow identifiers and store the API token only as a GitHub Actions secret; no private signing key is provided to or stored by the project.
8. Sign and timestamp the two EXEs and two DLLs, verify all four Authenticode chains, then generate the final v1.0.1 manifest/checksums and publish it.

Approval and certificate use are controlled by SignPath Foundation. The certificate publisher is SignPath Foundation, not the repository owner.
