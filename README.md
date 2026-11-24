# Any-Gender Parenthook

> **1.1.0:** targets CK3 1.21.0.3 only. Native gameplay acceptance passed for the executable hash recorded in `Native Hook/profiles/ck3-1.21.0.3.json`. Compatibility follows exact game-file hashes, regardless of launcher storefront metadata. The previous 1.0.2 release targets CK3 1.19.0.6. Local packages remain unpublished; the optional Dynastic Priority add-on is excluded and its full rule matrix is unverified.

Any-Gender Parenthook (AGP) is a Windows x64 native hook for Crusader Kings III. It supplies parent-role handling used by compatible CK3 mods without shipping the development test mod or the optional Dynastic Priority addon.

## Install

Download the package for your preferred installation method and extract the
whole archive:

- `AGP v1.1.0 EXE Installer.zip` provides the graphical installer and
  uninstaller that can search Steam libraries or browse to Steam/GOG `ck3.exe`;
- `AGP v1.1.0 Batch File Installer.zip` provides the readable batch/PowerShell
  installer and uninstaller with a standard Steam default and a `-TargetRoot` override for other installations;
- `AGP v1.1.0 Base Files (Manual Install).zip` contains only the native files
  and manual instructions for advanced users with a clean matching game layout.

Close CK3 before installing. The installer renames the verified original `dxcompiler.dll` to `dxcompiler_original.dll`, installs AGP's proxy as `dxcompiler.dll`, and installs `AGP Native Hook\agp_parenthook.dll`. Exact hashes and persistent state—not file size—identify files that AGP owns.

If a recognized AWOW Universal Female Generation installation is found, the EXE
and batch installers explain that UFG and its proxy will be removed and ask for
confirmation with OK and Cancel buttons. Unknown proxy layouts are preserved in
quarantine after the same clear button-based confirmation; users never need to
type a confirmation phrase.

## Manual installation (advanced users)

Use these steps only for a clean matching game installation where the game's `binaries`
folder contains the game's original `dxcompiler.dll` and does not already contain
`dxcompiler_original.dll`. If a backup already exists, another `dxcompiler.dll`
proxy is installed, or AGP/UFG is being upgraded or converted, use
`AGP-Installer.exe` instead.

1. Close Crusader Kings III.
2. Open the game's `binaries` folder. The standard Steam location is
   `C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\binaries`.
3. Rename the existing game `dxcompiler.dll` to `dxcompiler_original.dll`.
   Never overwrite or delete an existing `dxcompiler_original.dll`.
4. Copy the package's `dxcompiler.dll` into `binaries`.
5. Copy the package's entire `AGP Native Hook` folder into `binaries`. The final
   payload path must be
   `...\Crusader Kings III\binaries\AGP Native Hook\agp_parenthook.dll`.
6. Start CK3. A successful load creates `agp_dxcompiler_loader.log` and
   `agp_parenthook.log` in `binaries`.

The separate EXE and batch packages recognize the exact manual layout and are
the safest way to remove AGP.

## Uninstall

Use `AGP-Uninstaller.exe` from the EXE package or `Uninstall AGP.bat` from the
batch package. Uninstall verifies the recorded state, removes only recognized
AGP files and logs, and restores the recorded original `dxcompiler.dll`. If a
recognized UFG installation is active, the uninstaller asks before also
removing its proxy, payload folder, and logs. Unknown or modified files are
preserved rather than silently deleted.

## Building a release

The repository's `release` folder is maintainer tooling, not the folder users
copy into CK3. Run `release\build-release.ps1` from PowerShell on Windows with
the exact toolchain in `Native Hook\toolchain.json` and the Python build
requirements installed. The script builds or verifies the native x64 DLLs,
assembles the three method-specific ZIPs, rejects cross-package and
development-only content, and writes checksums plus local provenance metadata.
Local output is for smoke testing; the GitHub Actions build from `main` is the
canonical release artifact.

Version 1.1.0 is intentionally unsigned and auditable. The planned SignPath process for a future signed release is documented in [SIGNING.md](SIGNING.md).

## Project policies

- [License](LICENSE)
- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Code signing policy](SIGNING.md)
- [SignPath application package](SIGNPATH_APPLICATION.md)

## Maintainer validation

Run `Native Hook/test.ps1`, `python -m unittest discover -s Installer/python/tests -v`, and `python release/check-release.py`. The release check requires passing native-package gameplay evidence in `release/validation.json` for every supported executable hash. Native profile data are compiled from the canonical JSON; executable SHA-256 selection applies to both automated and manual installations.
