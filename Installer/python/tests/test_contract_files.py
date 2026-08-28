from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[3]


class ContractFileTests(unittest.TestCase):
    def validate_pair(self, document: str, schema: str) -> None:
        data = json.loads((ROOT / document).read_text(encoding="utf-8"))
        contract = json.loads((ROOT / schema).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(contract)
        Draft202012Validator(contract).validate(data)

    def test_release_manifest(self) -> None:
        self.validate_pair("Installer/release-manifest.json", "Installer/spec/release-manifest.schema.json")

    def test_scenario_fixtures(self) -> None:
        self.validate_pair("Installer/fixtures/scenarios.json", "Installer/spec/scenario-fixtures.schema.json")

    def test_compatibility_evidence(self) -> None:
        self.validate_pair(
            "Installer/fixtures/compatibility-evidence.json",
            "Installer/spec/compatibility-evidence.schema.json",
        )

    def test_end_user_entrypoints_are_at_package_root(self) -> None:
        manifest = json.loads((ROOT / "Installer" / "release-manifest.json").read_text(encoding="utf-8"))
        entrypoints = {item["relative_path"] for item in manifest["package"]["entrypoints"]}
        self.assertTrue(
            {
                "AGP-Installer.exe",
                "AGP-Uninstaller.exe",
                "Install AGP.bat",
                "Uninstall AGP.bat",
            }.issubset(entrypoints)
        )
        self.assertFalse(any(path.startswith("Installer/AGP") or path.endswith("/install.bat") or path.endswith("/uninstall.bat") for path in entrypoints))


if __name__ == "__main__":
    unittest.main()
