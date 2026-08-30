# Security policy

## Supported release

The current release target is the Windows x64 Steam build of Crusader Kings
III `1.19.0.6`, as identified by the SHA-256 values in
`Installer/release-manifest.json`. The native payload is version-specific.
Do not bypass the compatibility prompts for a different game build.

The installer validates path containment, reparse points, ownership, and hashes
before mutation. Unknown files are preserved in a lossless quarantine after an
explicit typed confirmation. Close CK3 before installing or uninstalling.

## Reporting a vulnerability

Please report suspected security issues privately to the repository maintainer
through the contact or private security-reporting channel listed on the project
repository. Include the release version, Windows/CK3 versions, reproduction
steps, and relevant installer or runtime log excerpts. Do not attach save files,
credentials, private keys, or other personal data unless specifically needed.

Until a fix is available, do not weaken hash prompts, path checks, rollback,
or quarantine behavior to work around an installation failure.

## Scope and disclosure

The installer and native loader are in scope. CK3 itself, Steam, third-party
mods, and the optional Dynastic Priority addon are not controlled by this
project. Coordinated disclosure and a release-specific advisory are preferred
for confirmed issues.
