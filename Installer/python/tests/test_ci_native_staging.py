from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class CleanRunnerNativeStagingTests(unittest.TestCase):
    """Keep the clean-runner native test-artifact ordering executable and narrow."""

    def test_workflow_stages_native_artifacts_before_tests(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release-draft.yml").read_text(encoding="utf-8")
        stage = workflow.index("Stage pinned native artifacts for installer tests")
        tests = workflow.index("Run installer contract and transition tests")
        self.assertLess(stage, tests)
        self.assertIn("prepare-native-test-artifacts.ps1", workflow)

    def test_empty_disposable_stage_is_prepared_from_pinned_archive(self) -> None:
        manifest = json.loads((ROOT / "Installer" / "release-manifest.json").read_text(encoding="utf-8"))
        native = manifest["native_release"]
        archive = ROOT / "Native Hook" / "build" / "published-v1.1.0" / "AGP.v1.1.0.Base.Files.Manual.Install.zip"
        helper = ROOT / "release" / "prepare-native-test-artifacts.ps1"
        self.assertTrue(archive.is_file(), "the pinned archive cache must be available before tests")
        with tempfile.TemporaryDirectory(prefix="agp-clean-stage-") as temp:
            stage = Path(temp)
            command = [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(helper),
                "-RepositoryRoot",
                str(ROOT),
                "-StageRoot",
                str(stage),
                "-ArchivePath",
                str(archive),
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["archive_sha256"], native["archive_sha256"])
            for artifact_id, relative in (("agp-proxy", "dxcompiler.dll"), ("agp-payload", "AGP Native Hook/agp_parenthook.dll")):
                artifact = next(item for item in manifest["artifacts"] if item["id"] == artifact_id)
                path = stage / relative
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), artifact["sha256"])
                self.assertEqual(path.stat().st_size, artifact["size_bytes"])
            self.assertTrue((stage / "published-v1.1.0" / archive.name).is_file())


if __name__ == "__main__":
    unittest.main()
