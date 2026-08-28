# Any-Gender Parenthook

Any-Gender Parenthook (AGP) is a Windows x64 native hook for Crusader Kings III. It supplies parent-role handling used by compatible CK3 mods without shipping the development test mod or the optional Dynastic Priority addon.

## Install

Download `Any-Gender-Parenthook-v1.0.0-win64.zip`, extract the whole archive, and then use either:

- `AGP-Installer.exe` to search Steam libraries or browse to `ck3.exe`;
- `Install AGP.bat` for the standard Steam location.

Close CK3 before installing. The installer renames Steam's `dxcompiler.dll` to `dxcompiler_original.dll`, installs AGP's proxy as `dxcompiler.dll`, and installs `AGP Native Hook\agp_parenthook.dll`. Exact hashes and persistent state—not file size—identify files that AGP owns.

If a recognized AWOW Universal Female Generation installation is found, the installer warns that conversion disables UFG and requires typed confirmation. Unknown proxy layouts are preserved in quarantine and also require typed confirmation.

## Uninstall

Use `AGP-Uninstaller.exe` or `Uninstall AGP.bat`. Uninstall verifies the recorded state, removes only AGP-owned files and logs, and restores the recorded Steam `dxcompiler.dll`. Unknown or modified files are preserved rather than silently deleted.

## Building a release

The repository's `release` folder is maintainer tooling, not the folder users copy into CK3. Run `release\build-release.ps1` from PowerShell on Windows with Visual Studio 2022 C++ build tools and the Python build requirements installed. The script builds or verifies the native x64 DLLs, assembles the end-user ZIP with its four launchers at the top level, rejects development-only content, and writes checksums plus local provenance metadata.

Version 1.0.0 is intentionally unsigned and auditable. The planned SignPath process for signed releases is documented in [SIGNING.md](SIGNING.md).

## Project policies

- [License](LICENSE)
- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Code signing policy](SIGNING.md)
- [SignPath application package](SIGNPATH_APPLICATION.md)
