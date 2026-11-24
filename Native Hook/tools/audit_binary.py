"""Read-only audit of an exact CK3 PE against AGP's native profiles.

No game files are distributed or modified. The audit uses only Python's standard
library; disassembly provenance and gameplay evidence are recorded separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

DEFAULT_PROFILES = Path(__file__).resolve().parents[1] / "profiles" / "ck3-1.21.0.3.json"


class PE:
    def __init__(self, data: bytes):
        self.data = data
        if data[:2] != b"MZ":
            raise ValueError("not a PE executable")
        header = struct.unpack_from("<I", data, 0x3C)[0]
        if data[header:header + 4] != b"PE\0\0":
            raise ValueError("invalid PE signature")
        machine, count = struct.unpack_from("<HH", data, header + 4)
        optional_size = struct.unpack_from("<H", data, header + 20)[0]
        if machine != 0x8664 or struct.unpack_from("<H", data, header + 24)[0] != 0x20B:
            raise ValueError("AGP requires Windows x64 PE32+")
        self.sections = []
        for index in range(count):
            offset = header + 24 + optional_size + index * 40
            name = data[offset:offset + 8].rstrip(b"\0").decode("ascii")
            virtual_size, rva, raw_size, raw = struct.unpack_from("<IIII", data, offset + 8)
            self.sections.append((name, rva, min(virtual_size, raw_size), raw))
        text = next(section for section in self.sections if section[0] == ".text")
        self.text_rva, size, raw = text[1:]
        self.text = data[raw:raw + size]

    def at(self, rva: int, size: int) -> bytes:
        for _, start, count, raw in self.sections:
            if start <= rva and rva + size <= start + count:
                return self.data[raw + rva - start:raw + rva - start + size]
        raise ValueError(f"RVA {rva:#x} is outside file-backed sections")


def audit(path: Path, document: dict) -> dict:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    matches = [profile for profile in document["profiles"] if profile["executable_sha256"] == digest]
    result = {"executable_sha256": digest, "ok": False, "checks": []}
    if len(matches) != 1:
        result["error"] = "executable must match exactly one recorded profile"
        return result
    profile = matches[0]
    result["profile_id"] = profile["profile_id"]
    pe = PE(data)
    for site in profile["sites"]:
        expected = bytes.fromhex(site["original"])
        rva = int(site["rva"], 0)
        count = pe.text.count(expected)
        valid = pe.at(rva, len(expected)) == expected and count == 1
        valid = valid and pe.text_rva <= rva and rva + len(expected) <= pe.text_rva + len(pe.text)
        if site["kind"] == "bytes":
            replacement = bytes.fromhex(site["replacement"])
            valid = valid and 0 <= site["patch_offset"] and site["patch_offset"] + len(replacement) <= len(expected)
        if site["kind"] == "near_jump":
            offset = site["patch_offset"]
            valid = valid and expected[offset:offset + 2] in (b"\x0f\x84", b"\x0f\x85")
            target = rva + offset + 6 + struct.unpack_from("<i", expected, offset + 2)[0]
            valid = valid and pe.text_rva <= target < pe.text_rva + len(pe.text)
        result["checks"].append({"id": site["id"], "rva": site["rva"], "matches": count, "ok": valid})
    for target in profile["call_targets"]:
        rva = int(target["call_rva"], 0)
        instruction = pe.at(rva, 5)
        destination = rva + 5 + struct.unpack_from("<i", instruction, 1)[0]
        expected = bytes.fromhex(target["prologue"])
        valid = instruction[0] == 0xE8 and destination == int(target["target_rva"], 0)
        valid = valid and pe.at(destination, len(expected)) == expected
        result["checks"].append({"id": target["id"], "resolved_rva": hex(destination), "ok": valid})
    result["ok"] = bool(result["checks"]) and all(check["ok"] for check in result["checks"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.executable, json.loads(args.profiles.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, StopIteration, struct.error) as exc:
        result = {"ok": False, "error": str(exc)}
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
