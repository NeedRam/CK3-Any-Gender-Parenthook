# Any-Gender Parenthook

Any-Gender Parenthook (AGP) is a Windows x64 native hook for Crusader Kings III. It supplies parent-role handling used by compatible CK3 mods without shipping the development test mod or the optional Dynastic Priority addon.

## Install

Download `Any-Gender-Parenthook-v1.0.2-win64.zip`, extract the whole archive, and then use either:

- `AGP-Installer.exe` to search Steam libraries or browse to `ck3.exe`;
- `Install AGP.bat` for the standard Steam location.

Close CK3 before installing. The installer renames Steam's `dxcompiler.dll` to `dxcompiler_original.dll`, installs AGP's proxy as `dxcompiler.dll`, and installs `AGP Native Hook\agp_parenthook.dll`. Exact hashes and persistent state—not file size—identify files that AGP owns.

If a recognized AWOW Universal Female Generation installation is found, the installer explains that UFG and its proxy will be removed and asks for confirmation with OK and Cancel buttons. Unknown proxy layouts are preserved in quarantine after the same clear button-based confirmation; users never need to type a confirmation phrase.

## Manual installation (advanced users)

Use these steps only for a clean Steam installation where the game's `binaries`
folder contains Steam's original `dxcompiler.dll` and does not already contain
`dxcompiler_original.dll`. If a backup already exists, another `dxcompiler.dll`
proxy is installed, or AGP/UFG is being upgraded or converted, use
`AGP-Installer.exe` instead.

1. Close Crusader Kings III.
2. Open the game's `binaries` folder. The standard Steam location is
   `C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\binaries`.
3. Rename the existing Steam `dxcompiler.dll` to `dxcompiler_original.dll`.
   Never overwrite or delete an existing `dxcompiler_original.dll`.
4. Copy the package's `dxcompiler.dll` into `binaries`.
5. Copy the package's entire `AGP Native Hook` folder into `binaries`. The final
   payload path must be
   `...\Crusader Kings III\binaries\AGP Native Hook\agp_parenthook.dll`.
6. Start CK3. A successful load creates `agp_dxcompiler_loader.log` and
   `agp_parenthook.log` in `binaries`.

The included `AGP-Uninstaller.exe` recognizes the package's exact manual layout
and remains the safest way to remove AGP.

## Uninstall

Use `AGP-Uninstaller.exe` or `Uninstall AGP.bat`. Uninstall verifies the recorded state, removes only recognized AGP files and logs, and restores the recorded Steam `dxcompiler.dll`. If a recognized UFG installation is active, the uninstaller asks before also removing its proxy, payload folder, and logs. Unknown or modified files are preserved rather than silently deleted.

## Building a release

The repository's `release` folder is maintainer tooling, not the folder users copy into CK3. Run `release\build-release.ps1` from PowerShell on Windows with the exact toolchain in `Native Hook\toolchain.json` and the Python build requirements installed. The script builds or verifies the native x64 DLLs, assembles the end-user ZIP with its four launchers at the top level, rejects development-only content, and writes checksums plus local provenance metadata. Local output is for smoke testing; the GitHub Actions build from `main` is the canonical release artifact.

Version 1.0.2 is intentionally unsigned and auditable. The planned SignPath process for a future signed release is documented in [SIGNING.md](SIGNING.md).

## Project policies

- [License](LICENSE)
- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Code signing policy](SIGNING.md)
- [SignPath application package](SIGNPATH_APPLICATION.md)
