# Code signing policy

AGP `v1.0.0` is an unsigned, auditable release ZIP. The release workflow records
SHA-256 checksums and GitHub build provenance; it does not create, embed, or
claim an Authenticode signature.

The intended path for later signed releases is SignPath Foundation for eligible
open-source projects. The maintainer must personally submit the application,
connect and authorize the GitHub account, configure reviewers/approvers, and
accept the provider's terms. No private key or password belongs in this
repository, a GitHub secret, an issue, or a support request to this project.

For approved signed releases: **Free code signing provided by
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

After approval, a future workflow may sign and timestamp the two installer
executables and both native DLLs, verify every Authenticode signature, and only
then publish a signed version (planned as `v1.0.1`). The unsigned workflow must
remain usable as the auditable fallback and must never label an unsigned asset
as signed.

Any signing integration must keep origin verification, protected approvals,
reproducible package assembly, and post-signing hash/provenance publication.
