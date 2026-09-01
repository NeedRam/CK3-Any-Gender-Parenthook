from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agp_installer.core import Installer, frozen_package_root
from agp_installer.discovery import parse_libraryfolders, select_target


ROOT = Path(__file__).resolve().parents[3]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class EngineTests(unittest.TestCase):
    def test_frozen_exe_finds_release_root_and_development_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "Any-Gender Parenthook v1.0.2"
            installer_dir = package / "Installer"
            installer_dir.mkdir(parents=True)
            (installer_dir / "release-manifest.json").write_text("{}", encoding="utf-8")
            executables = (package / "AGP-Installer.exe", installer_dir / "AGPInstaller.exe")
            for executable in executables:
                with self.subTest(executable=executable), mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(sys, "executable", str(executable)):
                    self.assertEqual(frozen_package_root(), package.resolve())

    def make_manifest(self, directory: Path, ck3: bytes, steam: bytes) -> Path:
        manifest = json.loads((ROOT / "Installer" / "release-manifest.json").read_text(encoding="utf-8"))
        proxy = ROOT / "Native Hook" / "build" / "dxcompiler.dll"
        payload = ROOT / "Native Hook" / "build" / "AGP Native Hook" / "agp_parenthook.dll"
        proxy_hash = digest(proxy.read_bytes())
        payload_hash = digest(payload.read_bytes())
        manifest["target"]["supported_builds"][0].update({"executable_sha256": digest(ck3), "original_dxcompiler_sha256": digest(steam)})
        manifest["artifacts"][0].update({"sha256": proxy_hash, "size_bytes": proxy.stat().st_size})
        manifest["artifacts"][1].update({"sha256": payload_hash, "size_bytes": payload.stat().st_size})
        clean = next(item for item in manifest["compatibility"]["seeds"] if item["state"] == "known_clean")
        clean["match"]["required_files"][0].update({"sha256": digest(ck3), "size_bytes": len(ck3)})
        clean["match"]["required_files"][1].update({"sha256": digest(steam), "size_bytes": len(steam)})
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return directory / "manifest.json"

    def test_clean_install_and_uninstall_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            target = folder / "binaries"
            target.mkdir()
            ck3, steam = b"ck3 fixture", b"steam compiler fixture"
            (target / "ck3.exe").write_bytes(ck3)
            (target / "dxcompiler.dll").write_bytes(steam)
            engine = Installer(package_root=ROOT, manifest_path=self.make_manifest(folder, ck3, steam), process_checker=lambda: False)
            installed = engine.install(target)
            self.assertEqual(installed.decision, "proceed", installed.message)
            self.assertTrue((target / "AGP Native Hook" / "agp-install-state.json").is_file())
            self.assertEqual(engine.classify(target).state, "managed_agp")
            removed = engine.uninstall(target)
            self.assertEqual(removed.decision, "proceed", removed.message)
            self.assertEqual((target / "dxcompiler.dll").read_bytes(), steam)
            self.assertFalse((target / "dxcompiler_original.dll").exists())
            self.assertFalse((target / "AGP Native Hook" / "agp-install-state.json").exists())

    def test_unknown_requires_confirmation_and_preserves_displaced_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            target = folder / "binaries"
            target.mkdir()
            ck3, steam, foreign = b"ck3 fixture", b"steam compiler fixture", b"foreign compiler"
            (target / "ck3.exe").write_bytes(ck3)
            (target / "dxcompiler.dll").write_bytes(foreign)
            (target / "dxcompiler_original.dll").write_bytes(steam)
            (target / "AGP Native Hook").mkdir()
            (target / "AGP Native Hook" / "agp_parenthook.dll").write_bytes(b"foreign payload")
            engine = Installer(package_root=ROOT, manifest_path=self.make_manifest(folder, ck3, steam), process_checker=lambda: False)
            refused = engine.install(target)
            self.assertEqual(refused.decision, "abort")
            accepted = engine.install(target, "I_UNDERSTAND_UNKNOWN_CONFLICT")
            self.assertEqual(accepted.decision, "proceed", accepted.message)
            quarantine = target / "AGP Native Hook" / ".agp-quarantine"
            self.assertTrue(any(quarantine.rglob("dxcompiler.dll")))
            self.assertTrue(any(quarantine.rglob("*agp_parenthook.dll")))

    def test_library_parser_and_manual_selection(self) -> None:
        values = parse_libraryfolders('"libraryfolders" { "0" { "path" "C:\\\\Steam" } }')
        self.assertEqual(values, [Path("C:\\Steam")])
        self.assertEqual(select_target("C:/Games/Crusader Kings III").name, "binaries")


if __name__ == "__main__":
    unittest.main()
