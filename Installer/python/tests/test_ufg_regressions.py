from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[3]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UfgRegressionTests(unittest.TestCase):
    """Persistent UFG recognition/cleanup coverage shared by both engines."""

    def setUp(self) -> None:
        from test_cross_engine import CrossEngineTests

        self.fixtures = CrossEngineTests("runTest")

    def make_ufg_target(self, root: Path, *, status: str = "managed_ufg", state_version: str = "1.1.1") -> tuple[Path, Path, Path]:
        package = self.fixtures.make_package(root)
        target = self.fixtures.make_clean_target(root)
        (target / "dxcompiler.dll").write_bytes(self.fixtures.ufg_proxy)
        (target / "dxcompiler_original.dll").write_bytes(self.fixtures.steam)
        ufg = target / "AWOW Universal Female Generation"
        ufg.mkdir()
        if status == "managed_ufg":
            (ufg / "awow_ufg.dll").write_bytes(self.fixtures.ufg_payload)
        hook = target / "AGP Native Hook"
        hook.mkdir()
        shutil.copy2(package / "AGP Native Hook" / "agp_parenthook.dll", hook / "agp_parenthook.dll")
        manifest = json.loads((package / "Installer" / "release-manifest.json").read_text(encoding="utf-8"))
        agp_proxy = manifest["artifacts"][0]["sha256"]
        agp_payload = manifest["artifacts"][1]["sha256"]
        profile_id = "ck3-1.21.0.3-x64"
        state = {
            "$schema": "https://any-gender-parenthook.invalid/schema/ufg-install-state-v2.json",
            "schema_version": 2,
            "kind": "ufg_install_state",
            "status": status,
            "transaction_id": str(uuid.uuid4()),
            "release": {"id": "awow-ufg", "version": state_version, "manifest_sha256": "0" * 64},
            "target": {
                "game_id": "crusader_kings_iii",
                "build_id": "1.21.0.3",
                "binaries_relative_path": "binaries",
                "executable_relative_path": "ck3.exe",
                "target_root_kind": "ck3_game_binaries",
                "profile_id": profile_id,
            },
            "baseline": {
                "original_dxcompiler": {"relative_path": "dxcompiler_original.dll", "sha256": digest(self.fixtures.steam), "size_bytes": len(self.fixtures.steam), "ownership": "game"},
                "executable": {"relative_path": "ck3.exe", "sha256": digest(self.fixtures.ck3), "size_bytes": len(self.fixtures.ck3), "ownership": "game"},
            },
            "agp_dependency": {
                "build_id": "agp-v" + state_version,
                "version": state_version,
                "proxy_relative_path": "dxcompiler.dll",
                "payload_relative_path": "AGP Native Hook/agp_parenthook.dll",
                "state_relative_path": "AGP Native Hook/agp-install-state.json",
                "proxy_sha256": agp_proxy,
                "payload_sha256": agp_payload,
                "original_dxcompiler_sha256": digest(self.fixtures.steam),
                "state_sha256": "absent",
            },
            "managed_files": [
                {"relative_path": "dxcompiler.dll", "role": "ufg_proxy", "ownership": "managed", "installed_sha256": digest(self.fixtures.ufg_proxy), "installed_size_bytes": len(self.fixtures.ufg_proxy), "present": True, "restore": {"action": "leave_managed_file"}},
                {"relative_path": "AWOW Universal Female Generation/awow_ufg.dll", "role": "ufg_payload", "ownership": "managed", "installed_sha256": digest(self.fixtures.ufg_payload), "installed_size_bytes": len(self.fixtures.ufg_payload), "present": status == "managed_ufg", "restore": {"action": "remove_managed_file"}},
            ],
            "quarantined_files": [],
            "foreign_cleanup": {"kind": "none", "quarantine_relative_path": "AWOW Universal Female Generation/.ufg-quarantine", "removed_paths": [], "uninstall_policy": "none"},
            "created_utc": "2026-11-25T00:00:00Z",
            "updated_utc": "2026-11-25T00:00:00Z",
        }
        state_path = ufg / "ufg-install-state.json"
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        return package, target, state_path

    def run_frontend(self, frontend: str, operation: str, target: Path, package: Path, confirmation: str | None = None):
        if frontend == "python":
            from agp_installer.core import InstallError, Installer

            try:
                engine = Installer(package_root=package, process_checker=lambda: False)
                return engine.install(target, confirmation) if operation == "install" else engine.uninstall(target, confirmation)
            except InstallError as exc:
                return SimpleNamespace(decision="reject", message=str(exc))
        return self.fixtures.run_ps(operation, target, package, confirmation)

    def test_active_and_disabled_state_versions_are_recognized_by_both_engines(self) -> None:
        for status in ("managed_ufg", "ufg_proxy_only"):
            for version in ("1.1.0", "1.1.1"):
                for frontend in ("python", "powershell"):
                    with self.subTest(status=status, version=version, frontend=frontend), tempfile.TemporaryDirectory() as temp:
                        package, target, _ = self.make_ufg_target(Path(temp), status=status, state_version=version)
                        if frontend == "python":
                            result = self.run_frontend(frontend, "install", target, package)
                            self.assertEqual(result.decision, "abort", result.message)
                        else:
                            code, result = self.run_frontend(frontend, "install", target, package)
                            self.assertEqual((code, result["decision"]), (2, "abort"), result)
                        self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.fixtures.ufg_proxy)

    def test_corrupt_contradictory_and_native_drift_states_refuse_both_engines(self) -> None:
        for mutation in ("corrupt", "contradictory", "dependency_version", "profile", "native_drift"):
            for frontend in ("python", "powershell"):
                with self.subTest(mutation=mutation, frontend=frontend), tempfile.TemporaryDirectory() as temp:
                    package, target, state_path = self.make_ufg_target(Path(temp))
                    if mutation == "corrupt":
                        state_path.write_text("{not-json", encoding="utf-8")
                    elif mutation == "contradictory":
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                        state["agp_dependency"]["original_dxcompiler_sha256"] = "0" * 64
                        state_path.write_text(json.dumps(state), encoding="utf-8")
                    elif mutation == "dependency_version":
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                        state["agp_dependency"]["version"] = "9.9.9"
                        state_path.write_text(json.dumps(state), encoding="utf-8")
                    elif mutation == "profile":
                        state = json.loads(state_path.read_text(encoding="utf-8"))
                        state["target"]["profile_id"] = "gog-ck3-1.21.0.3"
                        state_path.write_text(json.dumps(state), encoding="utf-8")
                    else:
                        (target / "AGP Native Hook" / "agp_parenthook.dll").write_bytes(b"drifted native payload")
                    if frontend == "python":
                        result = self.run_frontend(frontend, "install", target, package, "CONVERT_UFG_TO_AGP")
                        self.assertEqual(result.decision, "reject", result.message)
                    else:
                        code, result = self.run_frontend(frontend, "install", target, package, "CONVERT_UFG_TO_AGP")
                        self.assertEqual((code, result["decision"]), (2, "reject"), result)
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.fixtures.ufg_proxy)

    def test_nonempty_recovery_dirs_refuse_without_mutation_in_both_engines(self) -> None:
        for recovery in (".ufg-journal", ".ufg-quarantine"):
            for frontend in ("python", "powershell"):
                with self.subTest(recovery=recovery, frontend=frontend), tempfile.TemporaryDirectory() as temp:
                    package, target, _ = self.make_ufg_target(Path(temp))
                    recovery_dir = target / "AWOW Universal Female Generation" / recovery
                    recovery_dir.mkdir()
                    (recovery_dir / "pending.bin").write_bytes(b"pending")
                    if frontend == "python":
                        result = self.run_frontend(frontend, "install", target, package, "CONVERT_UFG_TO_AGP")
                        self.assertEqual(result.decision, "reject", result.message)
                    else:
                        code, result = self.run_frontend(frontend, "install", target, package, "CONVERT_UFG_TO_AGP")
                        self.assertEqual((code, result["decision"]), (2, "reject"), result)
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.fixtures.ufg_proxy)
                    self.assertEqual((recovery_dir / "pending.bin").read_bytes(), b"pending")

    def test_confirmation_and_unknown_file_preservation_are_zero_write_and_cross_engine(self) -> None:
        for frontend in ("python", "powershell"):
            with self.subTest(frontend=frontend), tempfile.TemporaryDirectory() as temp:
                package, target, _ = self.make_ufg_target(Path(temp))
                keep = target / "AWOW Universal Female Generation" / "user-owned.cfg"
                keep.write_text("preserve me", encoding="utf-8")
                if frontend == "python":
                    refused = self.run_frontend(frontend, "install", target, package)
                    self.assertEqual(refused.decision, "abort")
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.fixtures.ufg_proxy)
                    result = self.run_frontend(frontend, "install", target, package, "CONVERT_UFG_TO_AGP")
                    self.assertEqual(result.decision, "proceed", result.message)
                else:
                    code, refused = self.run_frontend(frontend, "install", target, package)
                    self.assertEqual((code, refused["decision"]), (2, "abort"), refused)
                    self.assertEqual((target / "dxcompiler.dll").read_bytes(), self.fixtures.ufg_proxy)
                    code, result = self.run_frontend(frontend, "install", target, package, "CONVERT_UFG_TO_AGP")
                    self.assertEqual((code, result["decision"]), (0, "proceed"), result)
                self.assertTrue(keep.is_file())

    def test_python_rejects_confirmation_to_mutation_toctou_without_restoring_new_bytes(self) -> None:
        from agp_installer.core import Installer

        class MutatingConfirmationInstaller(Installer):
            def __init__(self, *args, active: Path, **kwargs):
                super().__init__(*args, **kwargs)
                self.active_for_test = active

            def _confirmation(self, expected: str, supplied: str | None) -> bool:
                self.active_for_test.write_bytes(b"new foreign bytes")
                return supplied == expected

        with tempfile.TemporaryDirectory() as temp:
            package, target, _ = self.make_ufg_target(Path(temp))
            active = target / "dxcompiler.dll"
            result = MutatingConfirmationInstaller(package_root=package, process_checker=lambda: False, active=active).install(target, "CONVERT_UFG_TO_AGP")
            self.assertEqual(result.decision, "reject", result.message)
            self.assertEqual(active.read_bytes(), b"new foreign bytes")
            self.assertTrue((target / "AWOW Universal Female Generation" / "awow_ufg.dll").is_file())

    def test_powershell_contains_matching_revalidation_guards(self) -> None:
        source = (ROOT / "Installer" / "powershell" / "engine.ps1").read_text(encoding="utf-8")
        self.assertIn("function Test-LayoutUnchanged", source)
        self.assertIn("function Test-SnapshotsUnchanged", source)
        self.assertIn("Target changed after recognition or confirmation", source)
        self.assertIn("Remove-StagedTransaction", source)
