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


def _is_valid_state(data: dict[str, Any]) -> bool:
    if data.get("schema_version") != 1 or data.get("kind") != "agp_install_state" or data.get("status") != "managed_agp":
        return False
    if not isinstance(data.get("managed_files"), list) or len(data["managed_files"]) < 2:
        return False
    if not isinstance(data.get("baseline"), dict) or not _required(data["baseline"], "original_dxcompiler", "executable"):
        return False
    for item in data["managed_files"]:
        if not isinstance(item, dict) or not _required(item, "relative_path", "role", "ownership", "installed_sha256", "restore"):
            return False
        try:
            validate_relative(item["relative_path"])
            validate_relative(item["restore"].get("source_relative_path", "x")) if "source_relative_path" in item["restore"] else None
        except (ValueError, TypeError):
            return False
        if item["ownership"] != "managed" or len(str(item["installed_sha256"])) != 64:
            return False
    return True


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
        exists = source.exists() or source.is_symlink()
        self.snapshots[relative] = exists
        if exists:
            destination = self.backup_dir / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)

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
            "$schema": "https://any-gender-parenthook.invalid/schema/install-journal-v1.json",
            "schema_version": 1,
            "kind": "agp_install_journal",
            "transaction_id": self.id,
            "operation": self.operation,
            "source_state": self.source_state,
            "target_state": self.target_state,
            "phase": self.phase,
            "target": {"game_id": "crusader_kings_iii", "build_id": self.engine.build_id, "binaries_relative_path": "binaries", "target_root_kind": "steam_game_binaries"},
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
        self.build_id = self.manifest["target"]["supported_builds"][0]["id"]
        self.supported = self.manifest["target"]["supported_builds"][0]
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
        except PathSafetyError as exc:
            raise InstallError(str(exc)) from exc
        executable = contained(target, "ck3.exe")
        if not _same_file(executable, self.supported["executable_sha256"]):
            raise InstallError("selected target is not the supported CK3 executable build")
        state_path = contained(target, self.state_rel)
        if state_path.exists():
            try:
                state_data = _read_json(state_path)
            except InstallError as exc:
                raise InstallError("install state is unreadable; manual recovery is required") from exc
            if not _is_valid_state(state_data):
                raise InstallError("install state is not schema-v1; manual recovery is required")
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
        for key in ("original_dxcompiler", "executable"):
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
                    return Classification("managed_agp", "state-v1 ownership and hashes match", data, True)
            except (InstallError, KeyError, TypeError):
                valid = False
        seeds = self.manifest.get("compatibility", {}).get("seeds", [])
        for seed in seeds:
            if seed["state"] == "managed_agp":
                continue
            if self._match_seed(root, seed):
                if seed["state"] == "steam_updated":
                    # Steam rebaseline is valid only for a schema-v1 state;
                    # a random marker must remain an unknown conflict.
                    if data is None or not _is_valid_state(data):
                        continue
                return Classification(seed["state"], seed.get("description", ""), data, valid)
        if data is not None or not valid:
            return Classification("unknown_conflicting", "state is absent from a recognized complete layout or has drifted", data, valid)
        return Classification("unknown_conflicting", "no supported compatibility seed matched", None, valid)

    def _artifact_source(self, artifact_id: str) -> Path:
        artifact = self.artifacts[artifact_id]
        candidates = [self.package_root / artifact["source_relative_path"], self.package_root / artifact["relative_path"]]
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
            "$schema": "https://any-gender-parenthook.invalid/schema/install-state-v1.json",
            "schema_version": 1,
            "kind": "agp_install_state",
            "status": "managed_agp",
            "transaction_id": tx.id,
            "release": {"id": self.manifest["release"]["id"], "version": self.manifest["release"]["version"], "manifest_sha256": _json_hash(self.manifest_path)},
            "target": {"game_id": self.target_manifest["game_id"], "build_id": self.build_id, "binaries_relative_path": "binaries", "executable_relative_path": "ck3.exe", "target_root_kind": "steam_game_binaries"},
            "baseline": {"original_dxcompiler": {"relative_path": self.original_rel, "sha256": original_obs["sha256"], "size_bytes": original_obs["size_bytes"], "ownership": "steam"}, "executable": {"relative_path": "ck3.exe", "sha256": exe_obs["sha256"], "size_bytes": exe_obs["size_bytes"], "ownership": "steam"}},
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
        if classification.state == "managed_agp":
            required = "UPGRADE_AGP_IN_PLACE"
        elif classification.state == "legacy_agp":
            required = "UPGRADE_AGP_IN_PLACE"
        elif classification.state == "recognized_ufg":
            required = "CONVERT_UFG_TO_AGP"
        elif classification.state == "steam_updated":
            required = "ACCEPT_STEAM_UPDATE"
        elif classification.state == "unknown_conflicting":
            required = "I_UNDERSTAND_UNKNOWN_CONFLICT"
        elif classification.state == "known_clean":
            required = ""
        else:
            raise InstallError(f"cannot install from {classification.state}")
        if required != "" and classification.state != "known_clean" and not self._confirmation(required, confirmation):
            return Result("install", "abort", classification.state, classification.state, message=f"typed confirmation required: {required}")
        tx = self._prepare_transaction(root, classification, "install")
        active = self.active_rel
        original = self.original_rel
        payload = "AGP Native Hook/agp_parenthook.dll"
        state_rel = self.state_rel
        try:
            # Snapshot all possible mutation targets before creating the journal.
            for relative in (active, original, payload, state_rel, "agp_dxcompiler_loader.log", "agp_parenthook.log"):
                tx.snapshot(relative)
            source_state = classification.state
            # Record the complete intended mutation set before any rename or
            # quarantine. The later phase updates only the journal phase.
            if source_state in ("legacy_agp", "unknown_conflicting"):
                for relative in (active, payload):
                    if tx._path(relative).exists():
                        tx.entry(relative, "quarantine", "unknown_displaced", f"AGP Native Hook/.agp-quarantine/{tx.id}/{relative.replace('/', '__')}")
            elif source_state == "recognized_ufg":
                for relative in ("AWOW Universal Female Generation", "awow_ufg_dxcompiler_loader.log", "awow_ufg.log"):
                    if tx._path(relative).exists():
                        tx.entry(relative, "quarantine", "recognized_awow_ufg", f"AGP Native Hook/.agp-quarantine/{tx.id}/{relative.replace('/', '__')}")
                tx.foreign_cleanup = {"kind": "recognized_awow_ufg", "allowed": True, "quarantine_relative_path": f"AGP Native Hook/.agp-quarantine/{tx.id}", "remove_after_commit": True, "uninstall_policy": "do_not_restore_awow_ufg"}
                tx.foreign_cleanup_state = {"kind": "recognized_awow_ufg", "quarantine_relative_path": f"AGP Native Hook/.agp-quarantine/{tx.id}", "removed_paths": ["AWOW Universal Female Generation", "awow_ufg_dxcompiler_loader.log", "awow_ufg.log"], "uninstall_policy": "do_not_restore_awow_ufg"}
            elif source_state == "steam_updated" and tx._path(original).exists():
                tx.entry(original, "quarantine", "unknown_displaced", f"AGP Native Hook/.agp-quarantine/{tx.id}/{original.replace('/', '__')}")
            if source_state in ("known_clean", "steam_updated"):
                tx.entry(active, "rename", "steam")
            tx.entry(active, "replace", "managed", f"AGP Native Hook/.agp-journal/{tx.id}/stage/dxcompiler.dll")
            tx.entry(payload, "replace", "managed", f"AGP Native Hook/.agp-journal/{tx.id}/stage/AGP Native Hook/agp_parenthook.dll")
            tx.entry(state_rel, "create" if not tx._path(state_rel).exists() else "replace", "managed")
            tx.write_journal()
            if source_state in ("legacy_agp", "unknown_conflicting"):
                for relative in (active, payload):
                    if tx._path(relative).exists():
                        record = self._quarantine(tx, relative)
                        tx.quarantine_records.append(record)
            elif source_state == "recognized_ufg":
                for relative in ("AWOW Universal Female Generation", "awow_ufg_dxcompiler_loader.log", "awow_ufg.log"):
                    if tx._path(relative).exists():
                        record = self._quarantine(tx, relative, "recognized_awow_ufg", "do_not_restore_after_awow_ufg_commit")
                        tx.quarantine_records.append(record)
            elif source_state == "steam_updated":
                # The active supported Steam file becomes the new canonical original.
                if tx._path(original).exists():
                    record = self._quarantine(tx, original, "unknown_displaced", "preserve_for_uninstall")
                    tx.quarantine_records.append(record)
            if source_state == "known_clean":
                if tx._path(original).exists():
                    raise InstallError("clean install requires dxcompiler_original.dll to be absent")
                if not _same_file(tx._path(active), self.supported["original_dxcompiler_sha256"]):
                    raise InstallError("active Steam dxcompiler hash is not supported")
                tx._path(active).rename(tx._path(original))
            elif source_state == "steam_updated":
                if not _same_file(tx._path(active), self.supported["original_dxcompiler_sha256"]):
                    raise InstallError("Steam update active compiler hash is not supported")
                tx._path(active).rename(tx._path(original))
            elif source_state in ("managed_agp", "legacy_agp", "recognized_ufg", "unknown_conflicting"):
                if not tx._path(original).exists() or not _same_file(tx._path(original), self.supported["original_dxcompiler_sha256"]):
                    raise InstallError("canonical Steam original is missing or has an unsupported hash")
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
                raise InstallError("generated state failed schema-v1 structural validation")
            _write_json(tx._path(state_rel), state)
            if source_state == "recognized_ufg":
                qdir = tx._path(f"AGP Native Hook/.agp-quarantine/{tx.id}")
                if qdir.exists():
                    shutil.rmtree(qdir)
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
        if classification.state == "recognized_ufg":
            return Result("uninstall", "reject", classification.state, classification.state, message="recognized AWOW UFG is foreign; convert it before AGP uninstall")
        if classification.state in ("unknown_conflicting", "legacy_agp", "steam_updated"):
            if not self._confirmation("I_UNDERSTAND_UNKNOWN_CONFLICT", confirmation):
                return Result("uninstall", "abort", classification.state, classification.state, message="typed confirmation required: I_UNDERSTAND_UNKNOWN_CONFLICT")
        if classification.state == "known_clean":
            return Result("uninstall", "no_op", classification.state, classification.state, message="AGP is not installed")
        state = classification.state == "managed_agp" and classification.state_data
        if not isinstance(state, dict):
            # Legacy/unknown removal still uses the supported original hash.
            state = None
        tx = self._prepare_transaction(root, classification, "uninstall")
        active, original, payload, state_rel = self.active_rel, self.original_rel, "AGP Native Hook/agp_parenthook.dll", self.state_rel
        changed = [active, original, payload, state_rel, "agp_dxcompiler_loader.log", "agp_parenthook.log"]
        try:
            for relative in changed:
                tx.snapshot(relative)
            if classification.state != "managed_agp":
                for relative in (active, payload):
                    if tx._path(relative).exists():
                        tx.entry(relative, "quarantine", "unknown_displaced", f"AGP Native Hook/.agp-quarantine/{tx.id}/{relative.replace('/', '__')}")
            tx.entry(active, "restore", "steam")
            tx.entry(original, "remove", "steam")
            tx.entry(payload, "remove", "managed")
            tx.entry(state_rel, "remove", "managed")
            tx.write_journal()
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
                        return Result("uninstall", "abort", classification.state, classification.state, message="typed confirmation required: I_UNDERSTAND_UNKNOWN_CONFLICT")
                    for relative in mismatched:
                        if tx._path(relative).exists():
                            record = self._quarantine(tx, relative)
                            tx.quarantine_records.append(record)
                # A drifted original is not safe to restore or delete.
                baseline = state.get("baseline", {}).get("original_dxcompiler", {})
                if not _same_file(tx._path(original), baseline.get("sha256", ""), baseline.get("size_bytes")):
                    if confirmation != "I_UNDERSTAND_UNKNOWN_CONFLICT":
                        return Result("uninstall", "abort", classification.state, classification.state, message="typed confirmation required: I_UNDERSTAND_UNKNOWN_CONFLICT")
                    if tx._path(original).exists():
                        record = self._quarantine(tx, original)
                        tx.quarantine_records.append(record)
                    raise InstallError("state-owned original drifted; no safe Steam restore is available")
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
                raise InstallError("restored Steam compiler verification failed")
            tx.update_phase("commit")
            tx.commit_cleanup()
            return Result("uninstall", "proceed", classification.state, "known_clean", tx.id, "AGP uninstalled", changed=[active, payload, state_rel])
        except Exception as exc:
            if not tx.journal_path.exists():
                tx.write_journal()
            if tx.rollback():
                return Result("uninstall", "rollback", classification.state, classification.state, tx.id, str(exc), tx.journal_path)
            raise InstallError(f"rollback could not be verified; manual recovery required: {exc}") from exc
