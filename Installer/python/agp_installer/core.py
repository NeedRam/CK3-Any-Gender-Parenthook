"""Transactional AGP installer/uninstaller core.

The core has no Tkinter or PowerShell dependency. Every mutating operation is
preflighted, journaled, snapshotted, verified, and either committed or
restored from the snapshot. The journal remains on disk when rollback cannot
be proven.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .paths import PathSafetyError, assert_no_reparse_ancestors, contained, is_reparse, validate_relative


class InstallError(RuntimeError):
    """A safe, user-facing operation failure."""


@dataclass(frozen=True)
class Classification:
    state: str
    reason: str = ""
    state_data: dict[str, Any] | None = None
    state_valid: bool = False


@dataclass
class Result:
    operation: str
    decision: str
    classification: str
    next_state: str
    transaction_id: str | None = None
    message: str = ""
    journal: Path | None = None
    changed: list[str] = field(default_factory=list)


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(path: Path) -> str:
    return _sha256(path)


def _observation(path: Path) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {"exists": False, "kind": "absent"}
    if is_reparse(path):
        raise InstallError(f"reparse point is not an authorized file: {path}")
    if path.is_dir():
        return {"exists": True, "kind": "directory", "is_reparse_point": False}
    if path.is_file():
        stat = path.stat()
        return {"exists": True, "kind": "file", "sha256": _sha256(path), "size_bytes": stat.st_size, "is_reparse_point": False}
    raise InstallError(f"unsupported target path: {path}")


def _same_file(path: Path, sha: str, size: int | None = None) -> bool:
    try:
        return path.is_file() and (size is None or path.stat().st_size == size) and _sha256(path) == sha
    except OSError:
        return False


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("JSON root is not an object")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise InstallError(f"invalid JSON: {path}") from exc


def _required(value: dict[str, Any], *keys: str) -> bool:
    return all(key in value for key in keys)


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _is_uuid(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", value) is not None


def _valid_baseline(item: object, relative: str, owner: str) -> bool:
    return (
        isinstance(item, dict)
        and item.get("relative_path") == relative
        and _is_sha(item.get("sha256"))
        and isinstance(item.get("size_bytes"), int)
        and item["size_bytes"] >= 0
        and item.get("ownership") == owner
    )


def _is_valid_state(data: dict[str, Any]) -> bool:
    try:
        if data.get("schema_version") not in (1, 2) or data.get("kind") != "agp_install_state" or data.get("status") != "managed_agp":
            return False
        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", data["transaction_id"]):
            return False
        release, target = data["release"], data["target"]
        if release["id"] != "agp" or not re.fullmatch(r"\d+\.\d+\.\d+", release["version"]) or not re.fullmatch(r"[0-9a-f]{64}", release["manifest_sha256"]):
            return False
        if target["game_id"] != "crusader_kings_iii" or target["executable_relative_path"] != "ck3.exe" or target["binaries_relative_path"] != "binaries" or not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", target["build_id"]):
            return False
        if data["schema_version"] == 1:
            if target["target_root_kind"] != "steam_game_binaries": return False
        elif target["target_root_kind"] != "ck3_game_binaries" or target["distribution"] not in ("steam", "gog") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}",target["profile_id"]):
            return False
        for key,relative in (("original_dxcompiler","dxcompiler_original.dll"),("executable","ck3.exe")):
            item = data["baseline"][key]
            if item["relative_path"] != relative or item["ownership"] != ("steam" if data["schema_version"] == 1 else "game") or not re.fullmatch(r"[0-9a-f]{64}",item["sha256"]) or not isinstance(item["size_bytes"],int) or item["size_bytes"] < 0:
                return False
        managed = data["managed_files"]
        expected = {"agp_proxy":"dxcompiler.dll","agp_payload":"AGP Native Hook/agp_parenthook.dll"}
        if len(managed) != 2 or {item["role"] for item in managed} != set(expected): return False
        for item in managed:
            if item["relative_path"] != expected[item["role"]] or item["ownership"] != "managed" or not re.fullmatch(r"[0-9a-f]{64}",item["installed_sha256"]) or not isinstance(item["installed_size_bytes"],int) or item["installed_size_bytes"] < 0 or item["restore"]["action"] != "remove_managed_file":
                return False
        for item in data["quarantined_files"]:
            validate_relative(item["original_relative_path"]); validate_relative(item["quarantine_relative_path"])
            if item["kind"] not in ("file","directory_manifest") or not re.fullmatch(r"[0-9a-f]{64}",item["sha256"]): return False
        cleanup = data["foreign_cleanup"]
        validate_relative(cleanup["quarantine_relative_path"])
        if cleanup["kind"] not in ("none","recognized_awow_ufg"): return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def _is_valid_ufg_state(data: object) -> bool:
    """Validate UFG's v2 state without trusting it for ownership."""

    try:
        if not isinstance(data, dict) or data.get("schema_version") != 2 or data.get("kind") != "ufg_install_state":
            return False
        if data.get("status") not in {"managed_ufg", "ufg_proxy_only"} or not _is_uuid(data.get("transaction_id")):
            return False
        release = data["release"]
        if release.get("id") != "awow-ufg" or release.get("version") not in {"1.1.0", "1.1.1"} or not _is_sha(release.get("manifest_sha256")):
            return False
        target = data["target"]
        if target.get("game_id") != "crusader_kings_iii" or target.get("build_id") != "1.21.0.3" or target.get("binaries_relative_path") != "binaries" or target.get("executable_relative_path") != "ck3.exe" or target.get("target_root_kind") != "ck3_game_binaries":
            return False
        if target.get("profile_id") != "ck3-1.21.0.3-x64":
            return False
        baseline = data["baseline"]
        if not _valid_baseline(baseline.get("original_dxcompiler"), "dxcompiler_original.dll", "game") or not _valid_baseline(baseline.get("executable"), "ck3.exe", "game"):
            return False
        dependency = data["agp_dependency"]
        dependency_build = dependency.get("build_id")
        dependency_version = dependency.get("version")
        if dependency_build not in {"agp-v1.1.0", "agp-v1.1.1"} or dependency_version != dependency_build.removeprefix("agp-v"):
            return False
        if dependency.get("proxy_relative_path") != "dxcompiler.dll" or dependency.get("payload_relative_path") != "AGP Native Hook/agp_parenthook.dll" or dependency.get("state_relative_path") != "AGP Native Hook/agp-install-state.json":
            return False
        if not all(_is_sha(dependency.get(key)) for key in ("proxy_sha256", "payload_sha256", "original_dxcompiler_sha256")):
            return False
        state_sha = dependency.get("state_sha256")
        if state_sha != "absent" and not _is_sha(state_sha):
            return False
        managed = data["managed_files"]
        if not isinstance(managed, list) or len(managed) != 2:
            return False
        by_path = {item.get("relative_path"): item for item in managed if isinstance(item, dict)}
        if set(by_path) != {"dxcompiler.dll", "AWOW Universal Female Generation/awow_ufg.dll"}:
            return False
        proxy, payload = by_path["dxcompiler.dll"], by_path["AWOW Universal Female Generation/awow_ufg.dll"]
        if proxy.get("role") != "ufg_proxy" or payload.get("role") != "ufg_payload":
            return False
        for item, restore in ((proxy, "leave_managed_file"), (payload, "remove_managed_file")):
            if item.get("ownership") != "managed" or not _is_sha(item.get("installed_sha256")) or not isinstance(item.get("installed_size_bytes"), int) or item["installed_size_bytes"] < 0 or not isinstance(item.get("present"), bool) or item.get("restore", {}).get("action") != restore:
                return False
        if not proxy["present"] or payload["present"] != (data["status"] == "managed_ufg"):
            return False
        foreign = data["foreign_cleanup"]
        if foreign.get("kind") != "none" or foreign.get("removed_paths") != [] or foreign.get("uninstall_policy") != "none":
            return False
        validate_relative(foreign["quarantine_relative_path"])
        if not isinstance(data.get("quarantined_files"), list) or not isinstance(data.get("created_utc"), str) or not isinstance(data.get("updated_utc"), str):
            return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError, PathSafetyError):
        return False


def _is_process_running() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ck3.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=3, check=False)
        return any("ck3.exe" in line.casefold() and "no tasks" not in line.casefold() for line in result.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        return False


def frozen_package_root() -> Path | None:
    """Locate the unpacked package from either release-root or dev EXEs."""
    if not getattr(sys, "frozen", False):
        return None
    executable_dir = Path(sys.executable).resolve().parent
    for candidate in (executable_dir, executable_dir.parent):
        if (candidate / "Installer" / "release-manifest.json").is_file():
            return candidate
    return executable_dir


class _Transaction:
    def __init__(self, engine: "Installer", target: Path, operation: str, source_state: str, target_state: str):
        self.engine = engine
        self.target = target
        self.operation = operation
        self.source_state = source_state
        self.target_state = target_state
        self.id = str(uuid.uuid4())
        self.journal_dir = contained(target, f"AGP Native Hook/.agp-journal/{self.id}")
        self.journal_path = contained(target, f"AGP Native Hook/.agp-journal/{self.id}.json")
        self.backup_dir = self.journal_dir / "before"
        self.stage_dir = self.journal_dir / "stage"
        self.snapshots: dict[str, bool] = {}
        self.snapshot_observations: dict[str, dict[str, Any]] = {}
        self.entries: list[dict[str, Any]] = []
        self.foreign_cleanup = {"kind": "none", "allowed": False, "quarantine_relative_path": "AGP Native Hook/.agp-quarantine", "remove_after_commit": False, "uninstall_policy": "none"}
        self.phase = "validate"

    def _path(self, relative: str) -> Path:
        return contained(self.target, relative)

    def snapshot(self, relative: str) -> None:
        validate_relative(relative)
        if relative in self.snapshots:
            return
        source = self._path(relative)
        observation = _observation(source)
        exists = observation["exists"]
        self.snapshots[relative] = exists
        self.snapshot_observations[relative] = observation
        if exists:
            destination = self.backup_dir / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)

    def snapshots_unchanged(self) -> bool:
        """Return false when any snapshotted target changed after planning.

        This guard is intentionally checked after confirmation and again after
        the journal is written, before the first target mutation. A changed
        target is rejected without rollback so a newly written foreign file is
        never replaced by an older snapshot.
        """

        try:
            return all(_observation(self._path(relative)) == expected for relative, expected in self.snapshot_observations.items())
        except (InstallError, OSError):
            return False

    def discard_without_mutation(self) -> None:
        """Discard staged snapshots/journal metadata without touching target files."""

        if self.journal_path.exists():
            self.journal_path.unlink()
        if self.journal_dir.exists():
            shutil.rmtree(self.journal_dir)
        parent = self.journal_dir.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()

    def entry(self, relative: str, operation: str, ownership: str | None = None, staged: str | None = None) -> None:
        path = self._path(relative)
        before = _observation(path)
        item: dict[str, Any] = {"relative_path": relative, "kind": before["kind"] if before["exists"] else "file", "operation": operation, "before": before, "staged_relative_path": staged or f"AGP Native Hook/.agp-journal/{self.id}/stage/{relative}"}
        if ownership:
            item["ownership"] = ownership
        self.entries.append(item)

    def write_journal(self) -> None:
        self.phase = "journal"
        journal = {
            "$schema": "https://any-gender-parenthook.invalid/schema/install-journal-v2.json",
            "schema_version": 2,
            "kind": "agp_install_journal",
            "transaction_id": self.id,
            "operation": self.operation,
            "source_state": self.source_state,
            "target_state": self.target_state,
            "phase": self.phase,
            "target": {"game_id": "crusader_kings_iii", "build_id": self.engine.build_id, "binaries_relative_path": "binaries", "target_root_kind": "ck3_game_binaries", "profile_id": self.engine.supported["profile_id"], "distribution": self.engine.supported["distribution"]},
            "entries": self.entries,
            "foreign_cleanup": self.foreign_cleanup,
        }
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.journal_path, journal)

    def update_phase(self, phase: str) -> None:
        self.phase = phase
        if self.journal_path.exists():
            data = _read_json(self.journal_path)
            data["phase"] = phase
            _write_json(self.journal_path, data)

    def rollback(self) -> bool:
        try:
            self.update_phase("rollback")
            quarantine = self.target / "AGP Native Hook" / ".agp-quarantine" / self.id
            if quarantine.exists():
                if quarantine.is_dir():
                    shutil.rmtree(quarantine)
                else:
                    quarantine.unlink()
            for relative in reversed(list(self.snapshots)):
                destination = self._path(relative)
                if destination.exists() or destination.is_symlink():
                    if destination.is_dir() and not destination.is_symlink():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                if self.snapshots[relative]:
                    source = self.backup_dir / Path(relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_dir():
                        shutil.copytree(source, destination)
                    else:
                        shutil.copy2(source, destination)
            if self.journal_path.exists():
                self.journal_path.unlink()
            if self.journal_dir.exists():
                shutil.rmtree(self.journal_dir)
            return True
        except Exception:
            return False

    def commit_cleanup(self) -> None:
        if self.journal_path.exists():
            self.journal_path.unlink()
        if self.journal_dir.exists():
            shutil.rmtree(self.journal_dir)
        parent = self.journal_dir.parent
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()


class Installer:
    """Independent engine. ``package_root`` is the unpacked release root."""

    def __init__(self, package_root: str | os.PathLike[str] | None = None, manifest_path: str | os.PathLike[str] | None = None, process_checker: Callable[[], bool] | None = None):
        here = Path(__file__).resolve()
        if package_root is None:
            package_root = frozen_package_root()
        self.package_root = Path(package_root or here.parents[3]).resolve()
        self.manifest_path = Path(manifest_path or self.package_root / "Installer" / "release-manifest.json").resolve()
        self.manifest = _read_json(self.manifest_path)
        self.process_checker = process_checker or _is_process_running
        self.target_manifest = self.manifest["target"]
        if self.manifest.get("schema_version") != 2:
            raise InstallError("release manifest is not schema-v2")
        self.build_id = ""
        self.supported: dict[str, Any] = {}
        self.artifacts = {item["id"]: item for item in self.manifest["artifacts"]}

    @property
    def active_rel(self) -> str:
        return self.target_manifest["active_dxcompiler_relative_path"]

    @property
    def original_rel(self) -> str:
        return self.target_manifest["original_dxcompiler_relative_path"]

    @property
    def state_rel(self) -> str:
        return self.target_manifest["state_relative_path"]

    @property
    def ufg_state_rel(self) -> str:
        return "AWOW Universal Female Generation/ufg-install-state.json"

    @property
    def ufg_payload_rel(self) -> str:
        return "AWOW Universal Female Generation/awow_ufg.dll"

    @property
    def ufg_journal_rel(self) -> str:
        return "AWOW Universal Female Generation/.ufg-journal"

    @property
    def ufg_quarantine_rel(self) -> str:
        return "AWOW Universal Female Generation/.ufg-quarantine"

    @property
    def ufg_log_rels(self) -> tuple[str, str]:
        return ("awow_ufg.log", "awow_ufg_dxcompiler_loader.log")

    def _target_preflight(self, target: Path) -> None:
        target = target.absolute()
        if not target.is_dir() or is_reparse(target):
            raise InstallError("selected target must be an existing, non-reparse directory")
        try:
            assert_no_reparse_ancestors(target)
            contained(target, "ck3.exe")
            contained(target, self.active_rel)
            contained(target, self.original_rel)
            contained(target, self.state_rel)
            for relative in (self.ufg_state_rel, self.ufg_payload_rel, self.ufg_journal_rel, self.ufg_quarantine_rel, *self.ufg_log_rels, "AGP Native Hook/agp-install-state.json"):
                contained(target, relative)
        except PathSafetyError as exc:
            raise InstallError(str(exc)) from exc
        executable = contained(target, "ck3.exe")
        if not executable.is_file():
            raise InstallError("selected target has no ck3.exe")
        executable_hash = _sha256(executable)
        matches = [build for build in self.target_manifest["supported_builds"] if build["executable_sha256"] == executable_hash]
        if len(matches) != 1:
            raise InstallError("selected target does not match exactly one supported CK3 executable profile")
        self.supported = matches[0]
        self.build_id = self.supported["id"]
        state_path = contained(target, self.state_rel)
        if state_path.exists():
            try:
                state_data = _read_json(state_path)
            except InstallError as exc:
                raise InstallError("install state is unreadable; manual recovery is required") from exc
            if not _is_valid_state(state_data):
                raise InstallError("install state is invalid; manual recovery is required")
        for relative, label in ((self.ufg_state_rel, "UFG install state"), (self.ufg_journal_rel, "UFG transaction journal"), (self.ufg_quarantine_rel, "UFG recovery quarantine")):
            path = contained(target, relative)
            if relative == self.ufg_state_rel:
                if path.exists():
                    try:
                        ufg_state = _read_json(path)
                    except InstallError as exc:
                        raise InstallError("UFG install state is unreadable; manual recovery is required") from exc
                    if not _is_valid_ufg_state(ufg_state):
                        raise InstallError("UFG install state is invalid; manual recovery is required")
            elif path.exists() and (not path.is_dir() or any(path.iterdir())):
                raise InstallError(f"{label} is unfinished; manual recovery is required")
        journal_root = contained(target, "AGP Native Hook/.agp-journal")
        if journal_root.exists():
            # A journal is an incomplete transaction. It is intentionally not
            # guessed at or deleted by a new invocation.
            if any(journal_root.iterdir()):
                raise InstallError("an incomplete transaction journal exists; manual recovery is required")
        if self.process_checker():
            raise InstallError("ck3.exe is running; close the game before changing binaries")

    def _state(self, target: Path) -> tuple[dict[str, Any] | None, bool]:
        path = contained(target, self.state_rel)
        if not path.exists():
            return None, True
        try:
            data = _read_json(path)
        except InstallError:
            return None, False
        return data, _is_valid_state(data)

    def _ufg_state(self, target: Path) -> tuple[dict[str, Any] | None, bool]:
        path = contained(target, self.ufg_state_rel)
        if not path.exists():
            return None, True
        try:
            data = _read_json(path)
        except InstallError:
            return None, False
        return data, _is_valid_ufg_state(data)

    def _ufg_pairs(self) -> list[dict[str, str]]:
        """Return known UFG/AGP native pair identities from the manifest."""

        pairs: list[dict[str, str]] = []
        for seed in self.manifest.get("compatibility", {}).get("seeds", []):
            if seed.get("state") != "recognized_ufg":
                continue
            files = {item.get("relative_path"): item for item in seed.get("match", {}).get("required_files", [])}
            try:
                pair = {
                    "proxy": files["dxcompiler.dll"]["sha256"].lower(),
                    "original": files["dxcompiler_original.dll"]["sha256"].lower(),
                    "payload": files[self.ufg_payload_rel]["sha256"].lower(),
                    "agp_payload": files["AGP Native Hook/agp_parenthook.dll"]["sha256"].lower(),
                    "agp_proxy": self.artifacts["agp-proxy"]["sha256"].lower(),
                }
            except (KeyError, TypeError, AttributeError):
                continue
            if pair not in pairs:
                pairs.append(pair)
        canonical = {
            "proxy": "6406c83ce1d31415e6e2c013e222d9098219ea912fa541ce4ece8f7b23f07c44",
            "original": "40e381d1d0ccf3bd725e30914b07d3d0cdaa907900e4d194da0e9cbd41d06e65",
            "payload": "796afce9e724b3ec48cfa31e08469335b895b8dc661de7974660676e776d276e",
            "agp_payload": "e6bb03805e7caa4392210fa45e3253de769d082ccd59087475a50c24b420071c",
            "agp_proxy": "e8365d61ffd80b4d8fcaf4d6d79ac00c8373831a0a86e66647a4fc1e4cef2e58",
        }
        if canonical not in pairs:
            pairs.append(canonical)
        return pairs

    def _ufg_pair_matches(self, target: Path, pair: dict[str, str], *, require_payload: bool) -> bool:
        if not _same_file(contained(target, self.active_rel), pair["proxy"]):
            return False
        if not _same_file(contained(target, self.original_rel), pair["original"]):
            return False
        if not _same_file(contained(target, "AGP Native Hook/agp_parenthook.dll"), pair["agp_payload"]):
            return False
        payload = contained(target, self.ufg_payload_rel)
        return _same_file(payload, pair["payload"]) if require_payload else not payload.exists()

    def _ufg_runtime_classification(self, target: Path) -> Classification | None:
        """Recognize only exact UFG layouts; drift remains a hard refusal."""

        data, valid = self._ufg_state(target)
        pairs = self._ufg_pairs()
        if data is not None:
            if not valid:
                return Classification("unknown_conflicting", "UFG state is malformed; manual recovery is required", data, False)
            dependency = data["agp_dependency"]
            status = data["status"]
            for pair in pairs:
                if dependency["proxy_sha256"].lower() != pair["agp_proxy"] or dependency["payload_sha256"].lower() != pair["agp_payload"] or dependency["original_dxcompiler_sha256"].lower() != pair["original"]:
                    continue
                if not _same_file(contained(target, "ck3.exe"), data["baseline"]["executable"]["sha256"], data["baseline"]["executable"]["size_bytes"]):
                    continue
                if not _same_file(contained(target, self.original_rel), data["baseline"]["original_dxcompiler"]["sha256"], data["baseline"]["original_dxcompiler"]["size_bytes"]):
                    continue
                if not self._ufg_pair_matches(target, pair, require_payload=status == "managed_ufg"):
                    continue
                proxy_item = next((item for item in data["managed_files"] if item.get("relative_path") == self.active_rel), None)
                payload_item = next((item for item in data["managed_files"] if item.get("relative_path") == self.ufg_payload_rel), None)
                if proxy_item is None or proxy_item["installed_sha256"].lower() != pair["proxy"] or not _same_file(contained(target, self.active_rel), proxy_item["installed_sha256"], proxy_item["installed_size_bytes"]):
                    continue
                if payload_item is None or payload_item["installed_sha256"].lower() != pair["payload"] or payload_item["present"] != (status == "managed_ufg"):
                    continue
                actual_agp_state = contained(target, self.state_rel)
                actual_state_sha = "absent" if not actual_agp_state.exists() else _sha256(actual_agp_state)
                if dependency["state_sha256"].lower() != actual_state_sha.lower():
                    continue
                if actual_agp_state.exists():
                    agp_state, agp_valid = self._state(target)
                    if not agp_valid or agp_state is None:
                        continue
                    agp_release = agp_state.get("release", {})
                    agp_target = agp_state.get("target", {})
                    # The dependency hashes identify the native bytes, but
                    # the embedded AGP state identity must also describe this
                    # exact supported build/profile. A well-shaped state from
                    # another package/profile is not an owned dependency.
                    if (
                        agp_release.get("id") != "agp"
                        or agp_release.get("version") not in {"1.1.0", "1.1.1"}
                        or agp_target.get("game_id") != "crusader_kings_iii"
                        or agp_target.get("build_id") != self.build_id
                        or agp_target.get("profile_id") != self.supported.get("profile_id")
                        or agp_target.get("distribution") != self.supported.get("distribution")
                    ):
                        continue
                    if agp_state.get("baseline", {}).get("original_dxcompiler", {}).get("sha256", "").lower() != pair["original"]:
                        continue
                    agp_payload = next((item for item in agp_state.get("managed_files", []) if item.get("role") == "agp_payload"), None)
                    if agp_payload is None or agp_payload.get("installed_sha256", "").lower() != pair["agp_payload"] or not _same_file(contained(target, agp_payload["relative_path"]), agp_payload["installed_sha256"], agp_payload.get("installed_size_bytes")):
                        continue
                return Classification("recognized_ufg", f"valid UFG v2 {status} layout; UFG is {'active' if status == 'managed_ufg' else 'disabled'}", data, True)
            return Classification("unknown_conflicting", "UFG state or its native dependency drifted; manual recovery is required", data, True)
        if not valid:
            return Classification("unknown_conflicting", "UFG state is unreadable; manual recovery is required", None, False)
        for pair in pairs:
            if self._ufg_pair_matches(target, pair, require_payload=True):
                return Classification("recognized_ufg", "exact manual UFG active layout without UFG state", None, True)
            if self._ufg_pair_matches(target, pair, require_payload=False) and _same_file(contained(target, self.active_rel), pair["proxy"]):
                return Classification("recognized_ufg", "exact manual UFG disabled proxy without UFG state", None, True)
        # A recognizable UFG path with the wrong bytes is not eligible for the
        # generic unknown-conflict override; replacing it could discard a mod.
        active = contained(target, self.active_rel)
        payload = contained(target, self.ufg_payload_rel)
        if payload.exists() or any(_same_file(active, pair["proxy"]) for pair in pairs):
            return Classification("unknown_conflicting", "UFG files are present but do not match a canonical native pair; manual recovery is required", None, False)
        return None

    def _match_seed(self, target: Path, seed: dict[str, Any]) -> bool:
        match = seed["match"]
        state_path = contained(target, self.state_rel)
        expected_state = match.get("state_file")
        if expected_state == "absent" and state_path.exists():
            return False
        if expected_state == "valid":
            data, valid = self._state(target)
            if not valid or data is None:
                return False
        for item in match.get("required_files", []):
            path = contained(target, item["relative_path"])
            if item["kind"] == "file":
                if not _same_file(path, item["sha256"], item.get("size_bytes")):
                    return False
        for item in match.get("required_paths", []):
            path = contained(target, item["relative_path"])
            if item["kind"] == "directory" and not path.is_dir():
                return False
            if item["kind"] == "path_marker" and not path.exists():
                return False
        for relative in match.get("absent_paths", []):
            if contained(target, relative).exists():
                return False
        return True

    def _managed_matches(self, target: Path, state: dict[str, Any]) -> bool:
        baseline = state.get("baseline", {})
        for key in ("original_dxcompiler",):
            item = baseline.get(key, {})
            path = contained(target, item.get("relative_path", "invalid"))
            if not _same_file(path, item.get("sha256", ""), item.get("size_bytes")):
                return False
        for item in state.get("managed_files", []):
            path = contained(target, item.get("relative_path", "invalid"))
            if not _same_file(path, item.get("installed_sha256", ""), item.get("installed_size_bytes")):
                return False
        return True

    def classify(self, target: str | os.PathLike[str]) -> Classification:
        root = Path(target).absolute()
        self._target_preflight(root)
        data, valid = self._state(root)
        if valid and data is not None and _is_valid_state(data):
            try:
                if self._managed_matches(root, data):
                    return Classification("managed_agp", "managed ownership and hashes match", data, True)
            except (InstallError, KeyError, TypeError):
                valid = False
        if valid and data is not None:
            original = data["baseline"]["original_dxcompiler"]
            payloads = [item for item in data["managed_files"] if item.get("role") == "agp_payload"]
            if (len(payloads) == 1 and _same_file(contained(root, self.active_rel), self.supported["original_dxcompiler_sha256"])
                    and _same_file(contained(root, original["relative_path"]), original["sha256"], original.get("size_bytes"))
                    and _same_file(contained(root, payloads[0]["relative_path"]), payloads[0]["installed_sha256"], payloads[0].get("installed_size_bytes"))):
                return Classification("game_updated", "supported original replaced the proxy; old payload and backup verified", data, True)
        ufg_classification = self._ufg_runtime_classification(root)
        if ufg_classification is not None:
            return ufg_classification
        if (data is None and valid and not contained(root, self.original_rel).exists()
                and not contained(root, "AGP Native Hook/agp_parenthook.dll").exists()
                and _same_file(contained(root, self.active_rel), self.supported["original_dxcompiler_sha256"])):
            return Classification("known_clean", "selected executable and original compiler match; no existing AGP layout", None, True)
        seeds = self.manifest.get("compatibility", {}).get("seeds", [])
        for seed in seeds:
            if seed["state"] in ("managed_agp", "game_updated"):
                continue
            if self._match_seed(root, seed):
                if seed["state"] == "game_updated":
                    # Legacy rebaseline requires a valid managed state;
                    # a random marker must remain an unknown conflict.
                    if data is None or not _is_valid_state(data):
                        continue
                return Classification(seed["state"], seed.get("description", ""), data, valid)
        if data is not None or not valid:
            return Classification("unknown_conflicting", "state is absent from a recognized complete layout or has drifted", data, valid)
        return Classification("unknown_conflicting", "no supported compatibility seed matched", None, valid)

    def _layout_signature(self, target: Path) -> dict[str, dict[str, Any]]:
        """Capture every path the transition can recognize or mutate."""

        relatives = (
            "ck3.exe",
            self.active_rel,
            self.original_rel,
            self.state_rel,
            "AGP Native Hook/agp_parenthook.dll",
            self.ufg_payload_rel,
            self.ufg_state_rel,
            *self.ufg_log_rels,
            "agp_dxcompiler_loader.log",
            "agp_parenthook.log",
        )
        return {relative: _observation(contained(target, relative)) for relative in dict.fromkeys(relatives)}

    def _stable_after_confirmation(self, target: Path, expected: Classification, before: dict[str, dict[str, Any]]) -> bool:
        """Reclassify and compare observations immediately before staging."""

        try:
            current = self.classify(target)
            return current.state == expected.state and self._layout_signature(target) == before
        except (InstallError, OSError):
            return False

    def _artifact_source(self, artifact_id: str) -> Path:
        artifact = self.artifacts[artifact_id]
        candidates = [
            self.package_root / artifact["source_relative_path"],
            self.package_root / artifact["relative_path"],
            # Development checkouts retain the pre-1.1.1 build output.  The
            # manifest hash still gates this compatibility fallback; release
            # assembly uses the pinned published-v1.1.0 cache instead.
            self.package_root / "Native Hook" / "build" / artifact["relative_path"],
        ]
        for path in candidates:
            if path.is_file():
                return path
        raise InstallError(f"package artifact is missing: {artifact_id}")

    def _confirmation(self, expected: str, supplied: str | None) -> bool:
        return supplied == expected

    def _state_for_commit(self, target: Path, tx: _Transaction, baseline_original: Path) -> dict[str, Any]:
        original_obs = _observation(baseline_original)
        executable = contained(target, "ck3.exe")
        exe_obs = _observation(executable)
        proxy = self._artifact_source("agp-proxy")
        payload = self._artifact_source("agp-payload")
        now = _utc()
        quarantine: list[dict[str, Any]] = getattr(tx, "quarantine_records", [])
        return {
            "$schema": "https://any-gender-parenthook.invalid/schema/install-state-v2.json",
            "schema_version": 2,
            "kind": "agp_install_state",
            "status": "managed_agp",
            "transaction_id": tx.id,
            "release": {"id": self.manifest["release"]["id"], "version": self.manifest["release"]["version"], "manifest_sha256": _json_hash(self.manifest_path)},
            "target": {"game_id": self.target_manifest["game_id"], "build_id": self.build_id, "binaries_relative_path": "binaries", "executable_relative_path": "ck3.exe", "target_root_kind": "ck3_game_binaries", "profile_id": self.supported["profile_id"], "distribution": self.supported["distribution"]},
            "baseline": {"original_dxcompiler": {"relative_path": self.original_rel, "sha256": original_obs["sha256"], "size_bytes": original_obs["size_bytes"], "ownership": "game"}, "executable": {"relative_path": "ck3.exe", "sha256": exe_obs["sha256"], "size_bytes": exe_obs["size_bytes"], "ownership": "game"}},
            "managed_files": [
                {"relative_path": self.active_rel, "role": "agp_proxy", "ownership": "managed", "installed_sha256": self.artifacts["agp-proxy"]["sha256"], "installed_size_bytes": proxy.stat().st_size, "restore": {"action": "remove_managed_file"}},
                {"relative_path": "AGP Native Hook/agp_parenthook.dll", "role": "agp_payload", "ownership": "managed", "installed_sha256": self.artifacts["agp-payload"]["sha256"], "installed_size_bytes": payload.stat().st_size, "restore": {"action": "remove_managed_file"}},
            ],
            "quarantined_files": quarantine,
            "foreign_cleanup": getattr(tx, "foreign_cleanup_state", {"kind": "none", "quarantine_relative_path": "AGP Native Hook/.agp-quarantine", "removed_paths": [], "uninstall_policy": "none"}),
            "created_utc": now,
            "updated_utc": now,
        }

    def _copy_artifact(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.stage")
        shutil.copy2(source, temporary)
        with temporary.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)

    def _quarantine(self, tx: _Transaction, relative: str, owner: str = "unknown_displaced", preserve: str = "preserve_for_uninstall") -> dict[str, Any]:
        source = tx._path(relative)
        if not source.exists() and not source.is_symlink():
            raise InstallError(f"cannot quarantine missing path: {relative}")
        safe_name = relative.replace("/", "__")
        qrelative = f"AGP Native Hook/.agp-quarantine/{tx.id}/{safe_name}"
        destination = tx._path(qrelative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        tx.snapshot(relative)
        if source.is_dir():
            shutil.copytree(source, destination)
            shutil.rmtree(source)
            kind = "directory_manifest"
            size = 0
            digest = hashlib.sha256((relative + ":directory").encode()).hexdigest()
        else:
            shutil.copy2(source, destination)
            size = source.stat().st_size
            digest = _sha256(source)
            source.unlink()
            kind = "file"
        return {"original_relative_path": relative, "quarantine_relative_path": qrelative, "kind": kind, "sha256": digest, "size_bytes": size, "ownership": owner, "restore_policy": preserve}

    def _prepare_transaction(self, target: Path, classification: Classification, operation: str) -> _Transaction:
        tx = _Transaction(self, target, operation, classification.state, "managed_agp" if operation == "install" else "known_clean")
        tx.quarantine_records = []
        tx.foreign_cleanup_state = {"kind": "none", "quarantine_relative_path": "AGP Native Hook/.agp-quarantine", "removed_paths": [], "uninstall_policy": "none"}
        return tx

    def install(self, target: str | os.PathLike[str], confirmation: str | None = None) -> Result:
        root = Path(target).absolute()
        classification = self.classify(root)
        layout_before_confirmation = self._layout_signature(root)
        if classification.state == "unknown_conflicting" and "UFG" in classification.reason and "manual recovery" in classification.reason:
            return Result("install", "reject", classification.state, classification.state, message=classification.reason)
        if classification.state == "managed_agp":
            required = "UPGRADE_AGP_IN_PLACE"
        elif classification.state == "legacy_agp":
            required = "UPGRADE_AGP_IN_PLACE"
        elif classification.state == "recognized_ufg":
            required = "CONVERT_UFG_TO_AGP"
        elif classification.state == "game_updated":
            required = "ACCEPT_GAME_UPDATE"
        elif classification.state == "unknown_conflicting":
            required = "I_UNDERSTAND_UNKNOWN_CONFLICT"
        elif classification.state == "known_clean":
            required = ""
        else:
            raise InstallError(f"cannot install from {classification.state}")
        if required != "" and classification.state != "known_clean" and not self._confirmation(required, confirmation):
            return Result("install", "abort", classification.state, classification.state, message="confirmation was cancelled or not supplied")
        if not self._stable_after_confirmation(root, classification, layout_before_confirmation):
            return Result("install", "reject", classification.state, classification.state, message="target changed after recognition or confirmation; no files were changed")
        tx = self._prepare_transaction(root, classification, "install")
        active = self.active_rel
        original = self.original_rel
        payload = "AGP Native Hook/agp_parenthook.dll"
        state_rel = self.state_rel
        try:
            # Snapshot all possible mutation targets before creating the journal.
            for relative in (active, original, payload, state_rel, self.ufg_payload_rel, self.ufg_state_rel, *self.ufg_log_rels, "agp_dxcompiler_loader.log", "agp_parenthook.log"):
                tx.snapshot(relative)
            source_state = classification.state
            # Record the complete intended mutation set before any rename or
            # quarantine. The later phase updates only the journal phase.
            if source_state in ("legacy_agp", "unknown_conflicting"):
                for relative in (active, payload):
                    if tx._path(relative).exists():
                        tx.entry(relative, "quarantine", "unknown_displaced", f"AGP Native Hook/.agp-quarantine/{tx.id}/{relative.replace('/', '__')}")
            elif source_state == "recognized_ufg":
                for relative in (active, self.ufg_payload_rel, self.ufg_state_rel, *self.ufg_log_rels, payload):
                    if tx._path(relative).exists():
                        tx.entry(relative, "quarantine", "recognized_awow_ufg", f"AGP Native Hook/.agp-quarantine/{tx.id}/{relative.replace('/', '__')}")
                tx.foreign_cleanup = {"kind": "recognized_awow_ufg", "allowed": True, "quarantine_relative_path": f"AGP Native Hook/.agp-quarantine/{tx.id}", "remove_after_commit": True, "uninstall_policy": "do_not_restore_awow_ufg"}
                tx.foreign_cleanup_state = {"kind": "recognized_awow_ufg", "quarantine_relative_path": f"AGP Native Hook/.agp-quarantine/{tx.id}", "removed_paths": [self.ufg_payload_rel, self.ufg_state_rel, *self.ufg_log_rels], "uninstall_policy": "do_not_restore_awow_ufg"}
            elif source_state == "game_updated" and tx._path(original).exists():
                tx.entry(original, "quarantine", "unknown_displaced", f"AGP Native Hook/.agp-quarantine/{tx.id}/{original.replace('/', '__')}")
            if source_state in ("known_clean", "game_updated"):
                tx.entry(active, "rename", "game")
            tx.entry(active, "replace", "managed", f"AGP Native Hook/.agp-journal/{tx.id}/stage/dxcompiler.dll")
            tx.entry(payload, "replace", "managed", f"AGP Native Hook/.agp-journal/{tx.id}/stage/AGP Native Hook/agp_parenthook.dll")
            tx.entry(state_rel, "create" if not tx._path(state_rel).exists() else "replace", "managed")
            if not tx.snapshots_unchanged():
                tx.discard_without_mutation()
                return Result("install", "reject", classification.state, classification.state, tx.id, "target changed during transaction planning; no files were changed")
            tx.write_journal()
            if not tx.snapshots_unchanged():
                tx.discard_without_mutation()
                return Result("install", "reject", classification.state, classification.state, tx.id, "target changed after journaling; no files were changed")
            if source_state in ("legacy_agp", "unknown_conflicting"):
                for relative in (active, payload):
                    if tx._path(relative).exists():
                        record = self._quarantine(tx, relative)
                        tx.quarantine_records.append(record)
            elif source_state == "recognized_ufg":
                for relative in (active, self.ufg_payload_rel, self.ufg_state_rel, *self.ufg_log_rels, payload):
                    if tx._path(relative).exists():
                        record = self._quarantine(tx, relative, "recognized_awow_ufg", "do_not_restore_after_awow_ufg_commit")
                        tx.quarantine_records.append(record)
            elif source_state == "game_updated":
                # The active supported game file becomes the new canonical original.
                if tx._path(original).exists():
                    record = self._quarantine(tx, original, "unknown_displaced", "preserve_for_uninstall")
                    tx.quarantine_records.append(record)
            if source_state == "known_clean":
                if tx._path(original).exists():
                    raise InstallError("clean install requires dxcompiler_original.dll to be absent")
                if not _same_file(tx._path(active), self.supported["original_dxcompiler_sha256"]):
                    raise InstallError("active game dxcompiler hash is not supported")
                tx._path(active).rename(tx._path(original))
            elif source_state == "game_updated":
                if not _same_file(tx._path(active), self.supported["original_dxcompiler_sha256"]):
                    raise InstallError("Game update active compiler hash is not supported")
                tx._path(active).rename(tx._path(original))
            elif source_state in ("managed_agp", "legacy_agp", "recognized_ufg", "unknown_conflicting"):
                if not tx._path(original).exists() or not _same_file(tx._path(original), self.supported["original_dxcompiler_sha256"]):
                    raise InstallError("canonical game original is missing or has an unsupported hash")
            tx.update_phase("stage")
            proxy = self._artifact_source("agp-proxy")
            payload_source = self._artifact_source("agp-payload")
            stage_proxy = tx.stage_dir / "dxcompiler.dll"
            stage_payload = tx.stage_dir / "AGP Native Hook" / "agp_parenthook.dll"
            stage_proxy.parent.mkdir(parents=True, exist_ok=True)
            stage_payload.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(proxy, stage_proxy)
            shutil.copy2(payload_source, stage_payload)
            tx.update_phase("mutate")
            self._copy_artifact(stage_proxy, tx._path(active))
            self._copy_artifact(stage_payload, tx._path(payload))
            if not _same_file(tx._path(active), self.artifacts["agp-proxy"]["sha256"], self.artifacts["agp-proxy"].get("size_bytes")) or not _same_file(tx._path(payload), self.artifacts["agp-payload"]["sha256"], self.artifacts["agp-payload"].get("size_bytes")):
                raise InstallError("installed artifact verification failed")
            tx.update_phase("verify")
            state = self._state_for_commit(root, tx, tx._path(original))
            if not _is_valid_state(state):
                raise InstallError("generated state failed schema-v2 structural validation")
            _write_json(tx._path(state_rel), state)
            if source_state == "recognized_ufg":
                qdir = tx._path(f"AGP Native Hook/.agp-quarantine/{tx.id}")
                if qdir.exists():
                    shutil.rmtree(qdir)
                ufg_dir = tx._path("AWOW Universal Female Generation")
                if ufg_dir.is_dir() and not any(ufg_dir.iterdir()):
                    ufg_dir.rmdir()
            tx.update_phase("commit")
            tx.commit_cleanup()
            return Result("install", "proceed", classification.state, "managed_agp", tx.id, "AGP installed", changed=[active, payload, state_rel])
        except Exception as exc:
            if not tx.journal_path.exists():
                # A failure before journaling still has a complete preflight snapshot.
                tx.write_journal()
            if tx.rollback():
                return Result("install", "rollback", classification.state, classification.state, tx.id, str(exc), tx.journal_path)
            raise InstallError(f"rollback could not be verified; manual recovery required: {exc}") from exc

    def uninstall(self, target: str | os.PathLike[str], confirmation: str | None = None) -> Result:
        root = Path(target).absolute()
        classification = self.classify(root)
        layout_before_confirmation = self._layout_signature(root)
        if classification.state == "unknown_conflicting" and "UFG" in classification.reason and "manual recovery" in classification.reason:
            return Result("uninstall", "reject", classification.state, classification.state, message=classification.reason)
        if classification.state == "recognized_ufg":
            if not self._confirmation("REMOVE_AGP_AND_UFG", confirmation):
                return Result("uninstall", "abort", classification.state, classification.state, message="confirmation was cancelled or not supplied")
        elif classification.state in ("unknown_conflicting", "legacy_agp", "game_updated"):
            if not self._confirmation("I_UNDERSTAND_UNKNOWN_CONFLICT", confirmation):
                return Result("uninstall", "abort", classification.state, classification.state, message="confirmation was cancelled or not supplied")
        if not self._stable_after_confirmation(root, classification, layout_before_confirmation):
            return Result("uninstall", "reject", classification.state, classification.state, message="target changed after recognition or confirmation; no files were changed")
        if classification.state == "known_clean":
            return Result("uninstall", "no_op", classification.state, classification.state, message="AGP is not installed")
        state = classification.state == "managed_agp" and classification.state_data
        if not isinstance(state, dict):
            # Legacy/unknown removal still uses the supported original hash.
            state = None
        tx = self._prepare_transaction(root, classification, "uninstall")
        active, original, payload, state_rel = self.active_rel, self.original_rel, "AGP Native Hook/agp_parenthook.dll", self.state_rel
        ufg_paths = [self.ufg_payload_rel, self.ufg_state_rel, *self.ufg_log_rels]
        changed = [active, original, payload, state_rel, "agp_dxcompiler_loader.log", "agp_parenthook.log"]
        if classification.state == "recognized_ufg":
            changed.extend(ufg_paths)
        try:
            for relative in changed:
                tx.snapshot(relative)
            if classification.state == "recognized_ufg":
                for relative in (active, payload, *ufg_paths):
                    if tx._path(relative).exists():
                        tx.entry(relative, "quarantine", "recognized_awow_ufg", f"AGP Native Hook/.agp-quarantine/{tx.id}/{relative.replace('/', '__')}")
                tx.foreign_cleanup = {"kind": "recognized_awow_ufg", "allowed": True, "quarantine_relative_path": f"AGP Native Hook/.agp-quarantine/{tx.id}", "remove_after_commit": True, "uninstall_policy": "remove_with_agp"}
            elif classification.state != "managed_agp":
                for relative in (active, payload):
                    if tx._path(relative).exists():
                        tx.entry(relative, "quarantine", "unknown_displaced", f"AGP Native Hook/.agp-quarantine/{tx.id}/{relative.replace('/', '__')}")
            tx.entry(active, "restore", "game")
            tx.entry(original, "remove", "game")
            tx.entry(payload, "remove", "managed")
            tx.entry(state_rel, "remove", "managed")
            if not tx.snapshots_unchanged():
                tx.discard_without_mutation()
                return Result("uninstall", "reject", classification.state, classification.state, tx.id, "target changed during transaction planning; no files were changed")
            tx.write_journal()
            if not tx.snapshots_unchanged():
                tx.discard_without_mutation()
                return Result("uninstall", "reject", classification.state, classification.state, tx.id, "target changed after journaling; no files were changed")
            # Preserve any path that is not demonstrably owned by this release.
            managed_paths = {item["relative_path"] for item in (state or {}).get("managed_files", [])}
            if classification.state == "managed_agp" and state:
                mismatched = []
                for item in state.get("managed_files", []):
                    path = tx._path(item["relative_path"])
                    if not _same_file(path, item.get("installed_sha256", ""), item.get("installed_size_bytes")):
                        mismatched.append(item["relative_path"])
                if mismatched:
                    if confirmation != "I_UNDERSTAND_UNKNOWN_CONFLICT":
                        return Result("uninstall", "abort", classification.state, classification.state, message="confirmation was cancelled or not supplied")
                    for relative in mismatched:
                        if tx._path(relative).exists():
                            record = self._quarantine(tx, relative)
                            tx.quarantine_records.append(record)
                # A drifted original is not safe to restore or delete.
                baseline = state.get("baseline", {}).get("original_dxcompiler", {})
                if not _same_file(tx._path(original), baseline.get("sha256", ""), baseline.get("size_bytes")):
                    if confirmation != "I_UNDERSTAND_UNKNOWN_CONFLICT":
                        return Result("uninstall", "abort", classification.state, classification.state, message="confirmation was cancelled or not supplied")
                    if tx._path(original).exists():
                        record = self._quarantine(tx, original)
                        tx.quarantine_records.append(record)
                    raise InstallError("state-owned original drifted; no safe game-file restore is available")
            elif classification.state == "recognized_ufg":
                for relative in (active, payload, *ufg_paths):
                    if tx._path(relative).exists():
                        record = self._quarantine(tx, relative, "recognized_awow_ufg", "remove_after_uninstall_commit")
                        tx.quarantine_records.append(record)
            else:
                for relative in (active, payload):
                    if tx._path(relative).exists():
                        record = self._quarantine(tx, relative)
                        tx.quarantine_records.append(record)
            if not tx._path(original).exists() or not _same_file(tx._path(original), self.supported["original_dxcompiler_sha256"]):
                raise InstallError("cannot uninstall safely: canonical original hash is not supported")
            tx.update_phase("mutate")
            if tx._path(active).exists():
                tx._path(active).unlink()
            tx._path(original).rename(tx._path(active))
            if tx._path(payload).exists():
                tx._path(payload).unlink()
            for log in ("agp_dxcompiler_loader.log", "agp_parenthook.log"):
                if tx._path(log).exists():
                    tx._path(log).unlink()
            if tx._path(state_rel).exists():
                tx._path(state_rel).unlink()
            tx.update_phase("verify")
            if not _same_file(tx._path(active), self.supported["original_dxcompiler_sha256"]):
                raise InstallError("restored game compiler verification failed")
            if classification.state == "recognized_ufg":
                qdir = tx._path(f"AGP Native Hook/.agp-quarantine/{tx.id}")
                if qdir.exists():
                    shutil.rmtree(qdir)
                ufg_dir = tx._path("AWOW Universal Female Generation")
                if ufg_dir.is_dir() and not any(ufg_dir.iterdir()):
                    ufg_dir.rmdir()
            tx.update_phase("commit")
            tx.commit_cleanup()
            return Result("uninstall", "proceed", classification.state, "known_clean", tx.id, "AGP uninstalled", changed=[active, payload, state_rel])
        except Exception as exc:
            if not tx.journal_path.exists():
                tx.write_journal()
            if tx.rollback():
                return Result("uninstall", "rollback", classification.state, classification.state, tx.id, str(exc), tx.journal_path)
            raise InstallError(f"rollback could not be verified; manual recovery required: {exc}") from exc
