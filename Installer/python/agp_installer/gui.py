"""Tkinter front end that delegates all safety decisions to :mod:`core`."""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from .core import InstallError, Installer, Result
from .discovery import default_target, discover_steam_targets, select_target


_WINDOWS_DRIVE_PREFIX = re.compile(r"^([A-Za-z]):")


def normalize_drive_prefix(value: str) -> str:
    """Uppercase only an alphabetic Windows drive prefix for GUI display."""

    return _WINDOWS_DRIVE_PREFIX.sub(lambda match: f"{match.group(1).upper()}:", value, count=1)


def _result_message(result: Result) -> str:
    """Return a user-facing result without claiming success for non-commits."""

    successful_states = {"install": "managed_agp", "uninstall": "known_clean"}
    if result.operation in successful_states and result.decision == "proceed" and result.next_state == successful_states[result.operation]:
        return {
            "install": "AGP installed successfully.",
            "uninstall": "AGP uninstalled successfully.",
        }[result.operation]
    details = f"{result.operation}: {result.decision}"
    return f"{details}\n{result.message}".strip() if result.message else details


def _confirmation_prompt(operation: str, state: str) -> tuple[str, str, str] | None:
    """Return short end-user copy and the internal engine authorization token."""

    prompts = {
        ("install", "managed_agp"): (
            "Replace installed AGP?",
            "AGP is already installed. Click OK to replace it with this version.",
            "UPGRADE_AGP_IN_PLACE",
        ),
        ("install", "legacy_agp"): (
            "Upgrade older AGP?",
            "An older AGP installation was found. Click OK to upgrade it safely.",
            "UPGRADE_AGP_IN_PLACE",
        ),
        ("install", "recognized_ufg"): (
            "Remove UFG and install AGP?",
            "AWOW UFG and its proxy were found. Click OK to remove UFG and install AGP.",
            "CONVERT_UFG_TO_AGP",
        ),
        ("install", "steam_updated"): (
            "Use updated Steam files?",
            "Steam updated CK3 after AGP was installed. Click OK to update AGP's saved original file.",
            "ACCEPT_STEAM_UPDATE",
        ),
        ("install", "unknown_conflicting"): (
            "Unknown proxy found",
            "An unrecognized proxy is installed. Click OK to preserve it in quarantine and install AGP.",
            "I_UNDERSTAND_UNKNOWN_CONFLICT",
        ),
        ("uninstall", "recognized_ufg"): (
            "Remove AGP and UFG?",
            "AWOW UFG and its proxy were found. Click OK to remove both UFG and AGP components.",
            "REMOVE_AGP_AND_UFG",
        ),
        ("uninstall", "legacy_agp"): (
            "Remove older AGP?",
            "An older AGP installation was found. Click OK to remove it and restore Steam's file.",
            "I_UNDERSTAND_UNKNOWN_CONFLICT",
        ),
        ("uninstall", "steam_updated"): (
            "Remove changed AGP files?",
            "CK3 files changed after AGP was installed. Click OK to preserve conflicts and continue.",
            "I_UNDERSTAND_UNKNOWN_CONFLICT",
        ),
        ("uninstall", "unknown_conflicting"): (
            "Unknown proxy found",
            "An unrecognized proxy is installed. Click OK to preserve it in quarantine and continue.",
            "I_UNDERSTAND_UNKNOWN_CONFLICT",
        ),
    }
    return prompts.get((operation, state))


def _ask_confirmation(operation: str, state: str, parent: tk.Misc | None = None) -> str | None:
    prompt = _confirmation_prompt(operation, state)
    if prompt is None:
        return None
    title, message, token = prompt
    return token if messagebox.askokcancel(title, message, parent=parent) else None


def _browse_for_target(parent: tk.Misc, target_var: tk.StringVar) -> None:
    """Select an executable and put its full path into the editable field."""

    current = target_var.get().strip()
    initial = str(Path(current).parent) if current else str(default_target().parent)
    selected = filedialog.askopenfilename(
        parent=parent,
        title="Select Crusader Kings III executable",
        initialdir=initial,
        filetypes=(("Crusader Kings III executable", "ck3.exe"), ("Executable files", "*.exe"), ("All files", "*.*")),
    )
    if not selected:
        return
    if Path(selected).name.casefold() != "ck3.exe":
        messagebox.showerror("Invalid CK3 executable", "Select the Crusader Kings III executable named ck3.exe.", parent=parent)
        return
    target_var.set(selected)


def _run_operation(root: tk.Misc, operation: str, package_root: str | None, target_text: str) -> int:
    """Run one operation after the user submits the path field."""

    if not target_text.strip():
        messagebox.showerror("Missing CK3 path", "Enter the path to ck3.exe or its binaries directory.", parent=root)
        return 2
    selected = select_target(target_text.strip())
    if selected is None:
        messagebox.showerror("Missing CK3 path", "Select a CK3 installation before continuing.", parent=root)
        return 2
    engine = Installer(package_root=package_root)
    try:
        classification = engine.classify(Path(selected))
        prompt = _confirmation_prompt(operation, classification.state)
        confirmation = _ask_confirmation(operation, classification.state, root)
        if prompt is not None and confirmation is None:
            return 1
        result = engine.install(selected, confirmation) if operation == "install" else engine.uninstall(selected, confirmation)
        messagebox.showinfo("Any-Gender Parenthook", _result_message(result), parent=root)
        return 0 if result.decision in ("proceed", "no_op") else 1
    except InstallError as exc:
        messagebox.showerror("Any-Gender Parenthook", str(exc), parent=root)
        return 1


def _close(root: tk.Misc, result: dict[str, int], code: int = 2) -> None:
    result["code"] = code
    root.destroy()


def run(operation: str = "install", package_root: str | None = None) -> int:
    root = tk.Tk()
    options = discover_steam_targets()
    root.title(f"Any-Gender Parenthook - {'Install' if operation == 'install' else 'Uninstall'}")
    root.minsize(720, 170)
    root.columnconfigure(0, weight=1)
    frame = tk.Frame(root, padx=16, pady=16)
    frame.grid(row=0, column=0, sticky="nsew")
    frame.columnconfigure(0, weight=1)
    tk.Label(frame, text="Crusader Kings III executable or path:").grid(row=0, column=0, columnspan=2, sticky="w")
    target_var = tk.StringVar(root, value=normalize_drive_prefix(str(default_target(options))))
    entry = tk.Entry(frame, textvariable=target_var, width=90)
    entry.grid(row=1, column=0, padx=(0, 8), pady=(6, 12), sticky="ew")
    tk.Button(frame, text="Browse...", command=lambda: _browse_for_target(root, target_var)).grid(row=1, column=1, pady=(6, 12))
    result = {"code": 2}
    action = "Install" if operation == "install" else "Uninstall"
    tk.Button(frame, text=action, command=lambda: _close(root, result, _run_operation(root, operation, package_root, target_var.get()))).grid(row=2, column=0, columnspan=2, sticky="e")
    root.protocol("WM_DELETE_WINDOW", lambda: _close(root, result))
    entry.focus_set()
    root.mainloop()
    return result["code"]
