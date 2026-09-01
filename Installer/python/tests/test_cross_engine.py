from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "Installer" / "python"))

from agp_installer.core import InstallError, Installer


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class CrossEngineTests(unittest.TestCase):
    ck3 = b"fixture ck3 executable"
    steam = b"fixture steam dxcompiler"
    ufg_proxy = b"fixture ufg proxy"
    ufg_payload = b"fixture ufg payload"

    def make_package(self, root: Path) -> Path:
        package = root / "release package with spaces"
        (package / "Installer").mkdir(parents=True)
        (package / "AGP Native Hook").mkdir()
        shutil.copy2(ROOT / "Native Hook" / "build" / "dxcompiler.dll", package / "dxcompiler.dll")
        shutil.copy2(
            ROOT / "Native Hook" / "build" / "AGP Native Hook" / "agp_parenthook.dll",
            package / "AGP Native Hook" / "agp_parenthook.dll",
        )
        manifest = json.loads((ROOT / "Installer" / "release-manifest.json").read_text(encoding="utf-8"))
        proxy = package / "dxcompiler.dll"
        payload = package / "AGP Native Hook" / "agp_parenthook.dll"
        manifest["target"]["supported_builds"][0].update(
            {"executable_sha256": digest(self.ck3), "original_dxcompiler_sha256": digest(self.steam)}
        )
        manifest["artifacts"][0].update({"sha256": digest(proxy.read_bytes()), "size_bytes": proxy.stat().st_size})
        manifest["artifacts"][1].update({"sha256": digest(payload.read_bytes()), "size_bytes": payload.stat().st_size})
        for seed in manifest["compatibility"]["seeds"]:
            files = seed["match"].get("required_files", [])
            for item in files:
                relative = item["relative_path"]
                if relative == "ck3.exe":
                    item.update({"sha256": digest(self.ck3), "size_bytes": len(self.ck3)})
                elif relative == "dxcompiler_original.dll":
                    item.update({"sha256": digest(self.steam), "size_bytes": len(self.steam)})
                elif relative == "AGP Native Hook/agp_parenthook.dll":
                    item.update({"sha256": digest(payload.read_bytes()), "size_bytes": payload.stat().st_size})
                elif relative == "AWOW Universal Female Generation/awow_ufg.dll":
                    item.update({"sha256": digest(self.ufg_payload), "size_bytes": len(self.ufg_payload)})
                elif relative == "dxcompiler.dll" and seed["state"] in ("known_clean", "steam_updated"):
                    item.update({"sha256": digest(self.steam), "size_bytes": len(self.steam)})
                elif relative == "dxcompiler.dll" and seed["state"] == "recognized_ufg":
                    item.update({"sha256": digest(self.ufg_proxy), "size_bytes": len(self.ufg_proxy)})
                elif relative == "dxcompiler.dll" and seed["state"] == "legacy_agp":
                    item.update({"sha256": digest(proxy.read_bytes()), "size_bytes": proxy.stat().st_size})
        (package / "Installer" / "release-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return package

    def make_clean_target(self, root: Path) -> Path:
        target = root / "Steam Library" / "steamapps" / "common" / "Crusader Kings III" / "binaries"
        target.mkdir(parents=True)
        (target / "ck3.exe").write_bytes(self.ck3)
        (target / "dxcompiler.dll").write_bytes(self.steam)
        return target

    def run_ps(self, operation: str, target: Path, package: Path, confirmation: str | None = None, fault: str | None = None):
        script = ROOT / "Installer" / ("install.ps1" if operation == "install" else "uninstall.ps1")
        command = [
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
            "-TargetRoot", str(target), "-PackageRoot", str(package), "-SkipElevationCheck", "-Json",
        ]
        if confirmation:
            command.extend(["-Confirmation", confirmation])
        if fault:
            command.extend(["-WriteFaultAt", fault])
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        output = completed.stdout.strip()
        self.assertTrue(output, completed.stderr)
        start, end = output.find("{"), output.rfind("}")
        self.assertGreaterEqual(start, 0, output)
        return completed.returncode, json.loads(output[start : end + 1])

    def assert_clean(self, target: Path) -> None:
        self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.steam)
        self.assertFalse((target / "dxcompiler_original.dll").exists())
        self.assertFalse((target / "AGP Native Hook" / "agp_parenthook.dll").exists())
        self.assertFalse((target / "AGP Native Hook" / "agp-install-state.json").exists())

    def assert_valid_state(self, target: Path) -> None:
        state = json.loads((target / "AGP Native Hook" / "agp-install-state.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "Installer" / "spec" / "install-state.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(state)

    def set_supported_steam(self, package: Path, steam: bytes) -> None:
        path = package / "Installer" / "release-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["target"]["supported_builds"][0]["original_dxcompiler_sha256"] = digest(steam)
        for seed in manifest["compatibility"]["seeds"]:
            if seed["state"] not in ("known_clean", "steam_updated"):
                continue
            for item in seed["match"].get("required_files", []):
                if item["relative_path"] == "dxcompiler.dll":
                    item.update({"sha256": digest(steam), "size_bytes": len(steam)})
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def test_python_install_powershell_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            engine = Installer(package_root=package, process_checker=lambda: False)
            self.assertEqual(engine.install(target).decision, "proceed")
            self.assert_valid_state(target)
            code, result = self.run_ps("uninstall", target, package)
            self.assertEqual((code, result["decision"]), (0, "proceed"), result)
            self.assert_clean(target)

    def test_powershell_install_python_uninstall(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            code, result = self.run_ps("install", target, package)
            self.assertEqual((code, result["decision"]), (0, "proceed"), result)
            self.assert_valid_state(target)
            engine = Installer(package_root=package, process_checker=lambda: False)
            self.assertEqual(engine.uninstall(target).decision, "proceed")
            self.assert_clean(target)

    def test_powershell_fault_rolls_back_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            code, result = self.run_ps("install", target, package, fault="AGP Native Hook/agp_parenthook.dll")
            self.assertEqual((code, result["decision"]), (1, "rollback"), result)
            self.assert_clean(target)

    def test_incomplete_journal_blocks_both_engines(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            journal = target / "AGP Native Hook" / ".agp-journal"
            journal.mkdir(parents=True)
            (journal / "pending.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(InstallError):
                Installer(package_root=package, process_checker=lambda: False).install(target)
            code, result = self.run_ps("install", target, package)
            self.assertEqual(code, 2)
            self.assertEqual(result["decision"], "reject")
            self.assert_clean(target)

    def test_wrong_ck3_build_is_a_hard_stop_in_both_engines(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            (target / "ck3.exe").write_bytes(b"unsupported executable")
            with self.assertRaises(InstallError):
                Installer(package_root=package, process_checker=lambda: False).install(target)
            code, result = self.run_ps("install", target, package, "I_UNDERSTAND_UNKNOWN_CONFLICT")
            self.assertEqual(code, 2)
            self.assertEqual(result["decision"], "reject")
            self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.steam)

    def test_recognized_ufg_conversion_in_both_engines(self) -> None:
        for frontend in ("python", "powershell"):
            with self.subTest(frontend=frontend), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                package, target = self.make_package(root), self.make_clean_target(root)
                (target / "dxcompiler.dll").write_bytes(self.ufg_proxy)
                (target / "dxcompiler_original.dll").write_bytes(self.steam)
                ufg = target / "AWOW Universal Female Generation"
                ufg.mkdir()
                (ufg / "awow_ufg.dll").write_bytes(self.ufg_payload)
                (target / "AGP Native Hook").mkdir()
                shutil.copy2(package / "AGP Native Hook" / "agp_parenthook.dll", target / "AGP Native Hook" / "agp_parenthook.dll")
                (target / "awow_ufg.log").write_bytes(b"log")
                (target / "awow_ufg_dxcompiler_loader.log").write_bytes(b"loader log")
                engine = Installer(package_root=package, process_checker=lambda: False)
                if frontend == "python":
                    result = engine.install(target, "CONVERT_UFG_TO_AGP")
                    self.assertEqual(result.decision, "proceed", result.message)
                else:
                    code, result = self.run_ps("install", target, package, "CONVERT_UFG_TO_AGP")
                    self.assertEqual((code, result["decision"]), (0, "proceed"), result)
                self.assertFalse(ufg.exists())
                self.assertFalse((target / "awow_ufg.log").exists())
                self.assertFalse((target / "awow_ufg_dxcompiler_loader.log").exists())
                self.assertEqual(engine.uninstall(target).decision, "proceed")
                self.assert_clean(target)

    def test_recognized_ufg_uninstall_in_both_engines(self) -> None:
        for frontend in ("python", "powershell"):
            with self.subTest(frontend=frontend), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                package, target = self.make_package(root), self.make_clean_target(root)
                (target / "dxcompiler.dll").write_bytes(self.ufg_proxy)
                (target / "dxcompiler_original.dll").write_bytes(self.steam)
                ufg = target / "AWOW Universal Female Generation"
                ufg.mkdir()
                (ufg / "awow_ufg.dll").write_bytes(self.ufg_payload)
                (target / "AGP Native Hook").mkdir()
                shutil.copy2(package / "AGP Native Hook" / "agp_parenthook.dll", target / "AGP Native Hook" / "agp_parenthook.dll")
                (target / "awow_ufg.log").write_bytes(b"log")
                (target / "awow_ufg_dxcompiler_loader.log").write_bytes(b"loader log")
                engine = Installer(package_root=package, process_checker=lambda: False)

                if frontend == "python":
                    refused = engine.uninstall(target)
                    self.assertEqual(refused.decision, "abort")
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.ufg_proxy)
                    self.assertTrue((ufg / "awow_ufg.dll").is_file())
                    result = engine.uninstall(target, "REMOVE_AGP_AND_UFG")
                    self.assertEqual(result.decision, "proceed", result.message)
                else:
                    code, refused = self.run_ps("uninstall", target, package)
                    self.assertEqual((code, refused["decision"]), (2, "abort"), refused)
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.ufg_proxy)
                    self.assertTrue((ufg / "awow_ufg.dll").is_file())
                    code, result = self.run_ps("uninstall", target, package, "REMOVE_AGP_AND_UFG")
                    self.assertEqual((code, result["decision"]), (0, "proceed"), result)

                self.assertFalse(ufg.exists())
                self.assertFalse((target / "awow_ufg.log").exists())
                self.assertFalse((target / "awow_ufg_dxcompiler_loader.log").exists())
                self.assert_clean(target)

    def test_ufg_proxy_and_payload_are_restored_if_agp_install_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            (target / "dxcompiler.dll").write_bytes(self.ufg_proxy)
            (target / "dxcompiler_original.dll").write_bytes(self.steam)
            ufg = target / "AWOW Universal Female Generation"
            ufg.mkdir()
            (ufg / "awow_ufg.dll").write_bytes(self.ufg_payload)
            (target / "AGP Native Hook").mkdir()
            shutil.copy2(package / "AGP Native Hook" / "agp_parenthook.dll", target / "AGP Native Hook" / "agp_parenthook.dll")
            (target / "awow_ufg.log").write_bytes(b"log")
            (target / "awow_ufg_dxcompiler_loader.log").write_bytes(b"loader log")

            code, result = self.run_ps(
                "install",
                target,
                package,
                "CONVERT_UFG_TO_AGP",
                fault="AGP Native Hook/agp_parenthook.dll",
            )
            self.assertEqual((code, result["decision"]), (1, "rollback"), result)
            self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.ufg_proxy)
            self.assertEqual((ufg / "awow_ufg.dll").read_bytes(), self.ufg_payload)
            self.assertTrue((target / "awow_ufg.log").is_file())
            self.assertTrue((target / "awow_ufg_dxcompiler_loader.log").is_file())

    def test_ufg_over_managed_agp_state_is_recognized(self) -> None:
        for frontend in ("python", "powershell"):
            with self.subTest(frontend=frontend), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                package, target = self.make_package(root), self.make_clean_target(root)
                engine = Installer(package_root=package, process_checker=lambda: False)
                self.assertEqual(engine.install(target).decision, "proceed")
                (target / "dxcompiler.dll").write_bytes(self.ufg_proxy)
                ufg = target / "AWOW Universal Female Generation"
                ufg.mkdir()
                (ufg / "awow_ufg.dll").write_bytes(self.ufg_payload)
                self.assertEqual(engine.classify(target).state, "recognized_ufg")

                if frontend == "python":
                    result = engine.uninstall(target, "REMOVE_AGP_AND_UFG")
                    self.assertEqual(result.decision, "proceed", result.message)
                else:
                    code, result = self.run_ps("uninstall", target, package, "REMOVE_AGP_AND_UFG")
                    self.assertEqual((code, result["decision"]), (0, "proceed"), result)
                self.assert_clean(target)

    def test_unknown_proxy_is_preserved_by_powershell(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            foreign_proxy, foreign_payload = b"unknown proxy", b"unknown payload"
            (target / "dxcompiler.dll").write_bytes(foreign_proxy)
            (target / "dxcompiler_original.dll").write_bytes(self.steam)
            (target / "AGP Native Hook").mkdir()
            (target / "AGP Native Hook" / "agp_parenthook.dll").write_bytes(foreign_payload)
            before = {"active": (target / "dxcompiler.dll").read_bytes(), "payload": (target / "AGP Native Hook" / "agp_parenthook.dll").read_bytes()}
            code, result = self.run_ps("install", target, package)
            self.assertEqual((code, result["decision"]), (2, "abort"), result)
            self.assertEqual((target / "dxcompiler.dll").read_bytes(), before["active"])
            code, result = self.run_ps("install", target, package, "I_UNDERSTAND_UNKNOWN_CONFLICT")
            self.assertEqual((code, result["decision"]), (0, "proceed"), result)
            quarantine = target / "AGP Native Hook" / ".agp-quarantine"
            preserved = [path.read_bytes() for path in quarantine.rglob("*") if path.is_file()]
            self.assertIn(foreign_proxy, preserved)
            self.assertIn(foreign_payload, preserved)

    def test_upgrade_requires_confirmation_in_both_engines(self) -> None:
        for frontend in ("python", "powershell"):
            with self.subTest(frontend=frontend), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                package, target = self.make_package(root), self.make_clean_target(root)
                engine = Installer(package_root=package, process_checker=lambda: False)
                self.assertEqual(engine.install(target).decision, "proceed")
                state_path = target / "AGP Native Hook" / "agp-install-state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                state["release"]["version"] = "0.9.0"
                state_path.write_text(json.dumps(state), encoding="utf-8")
                before = (target / "dxcompiler.dll").read_bytes()
                if frontend == "python":
                    refused = engine.install(target)
                    self.assertEqual(refused.decision, "abort")
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), before)
                    accepted = engine.install(target, "UPGRADE_AGP_IN_PLACE")
                    self.assertEqual(accepted.decision, "proceed", accepted.message)
                else:
                    code, refused = self.run_ps("install", target, package)
                    self.assertEqual((code, refused["decision"]), (2, "abort"), refused)
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), before)
                    code, accepted = self.run_ps("install", target, package, "UPGRADE_AGP_IN_PLACE")
                    self.assertEqual((code, accepted["decision"]), (0, "proceed"), accepted)

    def test_legacy_uninstall_preserves_displaced_files_in_powershell(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package, target = self.make_package(root), self.make_clean_target(root)
            (target / "dxcompiler_original.dll").write_bytes(self.steam)
            shutil.copy2(package / "dxcompiler.dll", target / "dxcompiler.dll")
            (target / "AGP Native Hook").mkdir()
            shutil.copy2(package / "AGP Native Hook" / "agp_parenthook.dll", target / "AGP Native Hook" / "agp_parenthook.dll")
            code, result = self.run_ps("uninstall", target, package, "I_UNDERSTAND_UNKNOWN_CONFLICT")
            self.assertEqual((code, result["decision"]), (0, "proceed"), result)
            self.assert_clean(target)
            quarantine = target / "AGP Native Hook" / ".agp-quarantine"
            self.assertTrue(any(path.is_file() for path in quarantine.rglob("*")))

    def test_steam_update_rebaseline_in_both_engines(self) -> None:
        updated = b"fixture updated steam dxcompiler"
        for frontend in ("python", "powershell"):
            with self.subTest(frontend=frontend), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                package, target = self.make_package(root), self.make_clean_target(root)
                engine = Installer(package_root=package, process_checker=lambda: False)
                self.assertEqual(engine.install(target).decision, "proceed")
                (target / "dxcompiler.dll").write_bytes(updated)
                self.set_supported_steam(package, updated)
                engine = Installer(package_root=package, process_checker=lambda: False)
                self.assertEqual(engine.classify(target).state, "steam_updated")
                if frontend == "python":
                    refused = engine.install(target)
                    self.assertEqual(refused.decision, "abort")
                    accepted = engine.install(target, "ACCEPT_STEAM_UPDATE")
                    self.assertEqual(accepted.decision, "proceed", accepted.message)
                else:
                    code, refused = self.run_ps("install", target, package)
                    self.assertEqual((code, refused["decision"]), (2, "abort"), refused)
                    code, accepted = self.run_ps("install", target, package, "ACCEPT_STEAM_UPDATE")
                    self.assertEqual((code, accepted["decision"]), (0, "proceed"), accepted)
                self.assertEqual(engine.uninstall(target).decision, "proceed")
                self.assertEqual((target / "dxcompiler.dll").read_bytes(), updated)
                self.assertFalse((target / "dxcompiler_original.dll").exists())


if __name__ == "__main__":
    unittest.main()
