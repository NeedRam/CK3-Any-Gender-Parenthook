"""Validate profile/manifest agreement and report unfinished release acceptance."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root: Path = ROOT) -> dict:
    document = json.loads((root/"Native Hook/profiles/ck3-1.21.0.3.json").read_text(encoding="utf-8"))
    manifest = json.loads((root/"Installer/release-manifest.json").read_text(encoding="utf-8"))
    acceptance = json.loads((root/"release/validation.json").read_text(encoding="utf-8"))
    errors, pending = [], []
    profiles = document["profiles"]
    hashes = [profile["executable_sha256"] for profile in profiles]
    if len(set(hashes)) != len(hashes): errors.append("native executable identities are ambiguous")
    native_release = manifest.get("native_release", {})
    if native_release.get("version") != document["release_version"]: errors.append("native release and profile versions disagree")
    if manifest["release"]["version"] == document["release_version"]: errors.append("package release must be distinct from the pinned native release")
    if native_release.get("source_commit") != "0576adacd68073aa4462755c82cade14260f006c": errors.append("native source commit is not the pinned published release")
    if manifest["schema_version"] != 2: errors.append("release manifest must be schema-v2")
    expected = {(p["profile_id"],p["version"],p["distribution"],p["executable_sha256"],p["original_dxcompiler_sha256"]) for p in profiles}
    actual = {(p["profile_id"],p["id"],p["distribution"],p["executable_sha256"],p["original_dxcompiler_sha256"]) for p in manifest["target"]["supported_builds"]}
    if expected != actual: errors.append("installer/native profile identities disagree")
    if any(p["version"] != "1.21.0.3" for p in profiles): errors.append("new payload must target only CK3 1.21.0.3")
    if not profiles: errors.append("at least one verified executable profile is required")
    if document.get("compatibility_basis") != "exact_executable_and_original_dxcompiler_sha256":
        errors.append("compatibility must be gated by exact executable and compiler hashes")
    for profile in profiles:
        ident = profile["profile_id"]
        required_sites = {
            "female_effect_parent", "female_effect_real_parent", "male_effect_parent", "male_effect_real_parent",
            "female_pregnancy_a", "female_pregnancy_b", "male_carrier_a", "male_carrier_b",
            "female_native_parent", "male_native_parent", "female_native_override", "male_native_override",
            "create_mother", "create_father", "create_real_father", "history_parent",
            "father_persistence", "mother_persistence", "parent_reconstruction", "close_family", "reconstruction_resume",
            "family_role_writer", "family_role_reader", "family_role_reader_handled"
        }
        ids = [site["id"] for site in profile["sites"]]
        if len(ids) != len(set(ids)) or not required_sites.issubset(ids): errors.append(f"{ident}: incomplete or duplicate native sites")
        if {call["id"] for call in profile["call_targets"]} != {"set_father","set_mother","writer_begin","writer_token","writer_id","reader_id"}: errors.append(f"{ident}: incomplete parent call targets")
        if not profile["static_verified"]: pending.append(f"{ident}: disassembly/static verification pending")
        results = acceptance["profiles"].get(ident,{})
        evidence = results.get("runtime_log_evidence")
        if evidence:
            evidence_path = (root/evidence).resolve()
            if not evidence_path.is_relative_to(root.resolve()) or not evidence_path.is_file():
                errors.append(f"{ident}: runtime evidence file missing or outside repository")
            else:
                log = evidence_path.read_text(encoding="utf-8")
                if ident not in log or profile["executable_sha256"] not in log or "native patches committed" not in log:
                    errors.append(f"{ident}: runtime evidence does not identify the verified executable and patch commit")
        if not profile["gameplay_verified"] or not results.get("runtime_log_evidence"):
            pending.append(f"{ident}: full gameplay acceptance pending")
        for scenario in acceptance["required_scenarios"]:
            if results.get("scenarios",{}).get(scenario) != "pass": pending.append(f"{ident}: {scenario}")
    return {"source_checks_ok":not errors,"release_ready":not errors and not pending,"errors":errors,"pending":pending}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-incomplete",action="store_true",help="allow local draft assembly while clearly recording unfinished acceptance")
    args = parser.parse_args()
    result = check()
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["source_checks_ok"] and (args.allow_incomplete or result["release_ready"]) else 1)
