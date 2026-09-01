# Code signing policy

AGP `v1.0.2` is an unsigned, auditable release. SHA-256 checksums and GitHub
build-provenance attestations identify its release ZIP; the project does not
create, embed, or claim an Authenticode signature for this version.

## Release authority and build provenance

The canonical release artifact is built by `.github/workflows/release-draft.yml`
from a commit reachable from `main`. Native compilation is pinned by the
repository's `Native Hook/toolchain.json`, bundled as `BUILD_TOOLCHAIN.json`, to
GitHub's `windows-2022` runner, MSVC `14.44.35207`, Windows SDK
`10.0.22621.0`, and an x64 host/target. The build fails if that exact native
toolchain cannot be selected.

Repository and local `Native Hook\build` files are developer outputs, not
release authority. A local `release\build-release.ps1` package is explicitly
labelled `local_smoke_test` in its provenance. Only the package emitted by the
canonical GitHub Actions job may be attached to a GitHub Release.

The checked-in release manifest is the contract template. During canonical
assembly, hashes and sizes are regenerated from the exact staged DLL bytes
before `SHA256SUMS.txt`, the ZIP checksum, provenance, and GitHub attestation
are created.

## Future SignPath signing

The intended path for a future signed release is SignPath Foundation for
eligible open-source projects. The maintainer must personally submit the
application, connect and authorize the GitHub account, configure
reviewers/approvers, and accept the provider's terms. No private key or
password belongs in this repository, a GitHub secret, an issue, or a support
request to this project.

For an approved signed release: **Free code signing provided by
[SignPath.io](https://signpath.io/), certificate by
[SignPath Foundation](https://signpath.org/).**

## Team roles

- Authors/committers: [NeedRam](https://github.com/NeedRam), the repository owner.
- Reviewers: NeedRam reviews changes from contributors before merge.
- Approvers: NeedRam manually approves each release signing request.

All role holders must use multi-factor authentication for both GitHub and
SignPath. Role assignments will be updated here before another maintainer is
granted signing authority.

## Privacy statement

This program will not transfer any information to other networked systems
unless specifically requested by the user or the person installing or
operating it. See [PRIVACY.md](PRIVACY.md) for the complete policy.

After SignPath approval, a later workflow may sign and timestamp the two
installer executables and both native DLLs, verify every Authenticode signature,
and only then generate final manifests and checksums. That work will use a new
version number; `v1.0.1` and `v1.0.2` must remain identified as unsigned.

Any signing integration must retain source-origin verification, protected
manual approval, the pinned native toolchain, canonical CI assembly, and
post-signing hash/provenance publication. It must never label an unsigned asset
as signed.
