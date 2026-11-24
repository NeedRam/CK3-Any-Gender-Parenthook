from __future__ import annotations

import hashlib
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("agp_binary_audit",ROOT/"Native Hook/tools/audit_binary.py")
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)
release_spec = importlib.util.spec_from_file_location("agp_release_check",ROOT/"release/check-release.py")
release_module = importlib.util.module_from_spec(release_spec)
release_spec.loader.exec_module(release_module)


class NativeProfileTests(unittest.TestCase):
    def executable(self, duplicate=False):
        data=bytearray(0x400)
        data[:2]=b"MZ";struct.pack_into("<I",data,0x3c,0x80)
        data[0x80:0x84]=b"PE\0\0";struct.pack_into("<HH",data,0x84,0x8664,1)
        struct.pack_into("<H",data,0x94,0xf0);struct.pack_into("<H",data,0x98,0x20b)
        section=0x80+24+0xf0;data[section:section+8]=b".text\0\0\0"
        struct.pack_into("<IIII",data,section+8,0x200,0x1000,0x200,0x200)
        original=bytes.fromhex("80 b8 a1 01 00 00 00 74 05 cc")
        data[0x210:0x210+len(original)]=original
        if duplicate:data[0x240:0x240+len(original)]=original
        profile={"profile_id":"fixture","executable_sha256":hashlib.sha256(data).hexdigest(),"sites":[{"id":"setter","rva":"0x1010","kind":"bytes","patch_offset":7,"original":original.hex(" "),"replacement":"eb"}],"call_targets":[]}
        return bytes(data),{"profiles":[profile]}

    def test_pe_audit_rejects_duplicate_sites_and_unknown_hashes(self):
        for duplicate in (False,True):
            data,document=self.executable(duplicate)
            with tempfile.TemporaryDirectory() as temp:
                executable=Path(temp)/"ck3.exe";executable.write_bytes(data)
                self.assertEqual(audit_module.audit(executable,document)["ok"],not duplicate)
                document["profiles"][0]["executable_sha256"]="0"*64
                self.assertFalse(audit_module.audit(executable,document)["ok"])

    def test_pe_audit_rejects_site_outside_text(self):
        data,document=self.executable()
        document["profiles"][0]["sites"][0]["rva"]="0x1011"
        with tempfile.TemporaryDirectory() as temp:
            executable=Path(temp)/"ck3.exe";executable.write_bytes(data)
            self.assertFalse(audit_module.audit(executable,document)["ok"])

    def test_canonical_profile_manifest_agreement(self):
        result=release_module.check()
        self.assertTrue(result["source_checks_ok"],result)
        # Missing executable/runtime evidence must never become implicit approval.
        if result["pending"]:self.assertFalse(result["release_ready"])

    def test_release_gate_requires_matching_runtime_evidence(self):
        document=json.loads((ROOT/"Native Hook/profiles/ck3-1.21.0.3.json").read_text(encoding="utf-8"))
        manifest=json.loads((ROOT/"Installer/release-manifest.json").read_text(encoding="utf-8"))
        acceptance=json.loads((ROOT/"release/validation.json").read_text(encoding="utf-8"))
        steam=copy.deepcopy(document["profiles"][0])
        steam.update(profile_id="fixture-steam",distribution="steam",executable_sha256="ab"*32)
        document["profiles"].append(steam)
        target=copy.deepcopy(manifest["target"]["supported_builds"][0])
        target.update(profile_id=steam["profile_id"],distribution="steam",executable_sha256=steam["executable_sha256"])
        manifest["target"]["supported_builds"].append(target)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for profile in document["profiles"]:
                profile.update(static_verified=True,gameplay_verified=True)
                acceptance["profiles"][profile["profile_id"]]={
                    "runtime_log_evidence":f"release/evidence/{profile['profile_id']}.log",
                    "scenarios":dict.fromkeys(acceptance["required_scenarios"],"pass"),
                }
            for relative,data in (("Native Hook/profiles/ck3-1.21.0.3.json",document),
                                  ("Installer/release-manifest.json",manifest),
                                  ("release/validation.json",acceptance)):
                path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(data),encoding="utf-8")
            self.assertFalse(release_module.check(root)["source_checks_ok"])
            for profile in document["profiles"]:
                path=root/acceptance["profiles"][profile["profile_id"]]["runtime_log_evidence"]
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(f"{profile['profile_id']}\n{profile['executable_sha256']}\nnative patches committed\n",encoding="utf-8")
            # Identical game files do not need duplicate storefront acceptance.
            self.assertTrue(release_module.check(root)["release_ready"])
            path.write_text("wrong executable; native patches committed\n",encoding="utf-8")
            self.assertFalse(release_module.check(root)["source_checks_ok"])

    def test_release_gate_uses_file_identity_instead_of_storefront_label(self):
        relatives = ("Native Hook/profiles/ck3-1.21.0.3.json", "Installer/release-manifest.json", "release/validation.json")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            documents = {relative: json.loads((ROOT/relative).read_text(encoding="utf-8")) for relative in relatives}
            document = documents[relatives[0]]
            manifest = documents[relatives[1]]
            acceptance = documents[relatives[2]]
            self.assertEqual(len(document["profiles"]), 1)
            # Changing launcher metadata does not create a new native binary.
            document["profiles"][0]["distribution"] = "steam"
            manifest["target"]["supported_builds"][0]["distribution"] = "steam"
            for relative, data in documents.items():
                path = root/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data), encoding="utf-8")
            profile = document["profiles"][0]
            relative = acceptance["profiles"][profile["profile_id"]]["runtime_log_evidence"]
            path = root/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT/relative).read_bytes())
            self.assertTrue(release_module.check(root)["release_ready"])
            profile["executable_sha256"] = "ab"*32
            manifest["target"]["supported_builds"][0]["executable_sha256"] = profile["executable_sha256"]
            for relative in relatives[:2]:
                (root/relative).write_text(json.dumps(documents[relative]), encoding="utf-8")
            self.assertFalse(release_module.check(root)["source_checks_ok"])

    def test_descriptor_versions_and_localization_format(self):
        for rel in ("Native Hook/native_test_mod/descriptor.mod","Native Hook/native_test_mod/AGP Native Parent Test.mod"):
            self.assertIn('supported_version="1.21.0.3"',(ROOT/rel).read_text())
        for directory in (ROOT/"Native Hook/native_test_mod/localization",ROOT/"AGP Dynastic Priority/localization"):
            for path in directory.rglob("*.yml"):
                data=path.read_bytes()
                self.assertTrue(data.startswith(b"\xef\xbb\xbf"),str(path))
                quoted=False;escaped=False
                for char in data.decode("utf-8-sig"):
                    if char=='"' and not escaped:quoted=not quoted
                    if char=='\n':self.assertFalse(quoted,str(path))
                    escaped=char=='\\' and not escaped
                self.assertFalse(quoted,str(path))
