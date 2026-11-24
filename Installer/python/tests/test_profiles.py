from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import test_cross_engine as fixtures
from agp_installer.core import InstallError, Installer


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CrossEngineTests()

    def configure(self, root: Path, reverse: bool = False):
        package = self.fixture.make_package(root)
        target = self.fixture.make_clean_target(root)
        manifest_path = package / "Installer/release-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        first = manifest["target"]["supported_builds"][0]
        first.update(profile_id="fixture-steam", distribution="steam")
        second = copy.deepcopy(first)
        second.update(profile_id="fixture-gog", distribution="gog", executable_sha256=hashlib.sha256(b"gog executable").hexdigest(), original_dxcompiler_sha256=hashlib.sha256(b"gog compiler").hexdigest())
        manifest["target"]["supported_builds"] = [second, first] if reverse else [first, second]
        manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
        return package, target, manifest_path

    def test_both_profiles_and_array_orders_cross_engine(self):
        for reverse in (False, True):
            for distribution in ("steam", "gog"):
                for install_engine in ("python", "powershell"):
                    with self.subTest(reverse=reverse, distribution=distribution, install_engine=install_engine), tempfile.TemporaryDirectory() as temp:
                        package, target, _ = self.configure(Path(temp),reverse)
                        if distribution == "gog":
                            (target/"ck3.exe").write_bytes(b"gog executable")
                            (target/"dxcompiler.dll").write_bytes(b"gog compiler")
                        original = (target/"dxcompiler.dll").read_bytes()
                        engine = Installer(package_root=package,process_checker=lambda:False)
                        if install_engine == "python":
                            self.assertEqual(engine.install(target).decision,"proceed")
                        else:
                            code,result = self.fixture.run_ps("install",target,package)
                            self.assertEqual((code,result["decision"]),(0,"proceed"),result)
                        state = json.loads((target/"AGP Native Hook/agp-install-state.json").read_text())
                        self.assertEqual(state["schema_version"],2)
                        self.assertEqual(state["target"]["profile_id"],f"fixture-{distribution}")
                        self.fixture.assert_valid_state(target)
                        if install_engine == "python":
                            code,result = self.fixture.run_ps("uninstall",target,package)
                            self.assertEqual((code,result["decision"]),(0,"proceed"),result)
                        else:
                            self.assertEqual(engine.uninstall(target).decision,"proceed")
                        self.assertEqual((target/"dxcompiler.dll").read_bytes(),original)

    def test_ambiguous_executable_is_zero_write_abort(self):
        with tempfile.TemporaryDirectory() as temp:
            package,target,path = self.configure(Path(temp))
            manifest = json.loads(path.read_text())
            manifest["target"]["supported_builds"][1]["executable_sha256"] = manifest["target"]["supported_builds"][0]["executable_sha256"]
            path.write_text(json.dumps(manifest))
            with self.assertRaises(InstallError):
                Installer(package_root=package,process_checker=lambda:False).install(target)
            code,result = self.fixture.run_ps("install",target,package)
            self.assertEqual((code,result["decision"]),(2,"reject"))
            self.fixture.assert_clean(target)

    def test_v1_upgrade_after_executable_update_and_cross_engine_uninstall(self):
        for upgrade_engine in ("python","powershell"):
            with self.subTest(upgrade_engine=upgrade_engine),tempfile.TemporaryDirectory() as temp:
                package,target,path = self.configure(Path(temp))
                engine = Installer(package_root=package,process_checker=lambda:False)
                self.assertEqual(engine.install(target).decision,"proceed")
                state_path = target/"AGP Native Hook/agp-install-state.json"
                state = json.loads(state_path.read_text())
                state.update(schema_version=1)
                state["$schema"] = state["$schema"].replace("v2","v1")
                state["target"].update(build_id="1.19.0.6",target_root_kind="steam_game_binaries")
                state["target"].pop("profile_id"); state["target"].pop("distribution")
                for entry in state["baseline"].values(): entry["ownership"]="steam"
                state["baseline"]["executable"]["sha256"] = hashlib.sha256(b"old executable").hexdigest()
                state_path.write_text(json.dumps(state))
                before = state_path.read_bytes()
                self.assertEqual(engine.install(target).decision,"abort")
                self.assertEqual(state_path.read_bytes(),before)
                if upgrade_engine == "python":
                    result = engine.install(target,"UPGRADE_AGP_IN_PLACE")
                    self.assertEqual(result.decision,"proceed",result)
                    code,result = self.fixture.run_ps("uninstall",target,package)
                    self.assertEqual((code,result["decision"]),(0,"proceed"),result)
                else:
                    code,result = self.fixture.run_ps("install",target,package,"UPGRADE_AGP_IN_PLACE")
                    self.assertEqual((code,result["decision"]),(0,"proceed"),result)
                    self.assertEqual(json.loads(state_path.read_text())["schema_version"],2)
                    self.assertEqual(engine.uninstall(target).decision,"proceed")
                self.fixture.assert_clean(target)
