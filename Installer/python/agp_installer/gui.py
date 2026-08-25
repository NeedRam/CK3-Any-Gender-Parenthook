"""Small Tkinter UI. It delegates all safety decisions to :mod:`core`."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from .core import InstallError, Installer
from .discovery import discover_steam_targets, select_target


def _ask_confirmation(token: str) -> str | None:
    return simpledialog.askstring("Confirmation required", f"Type exactly:\n{token}")


def run(operation: str = "install", package_root: str | None = None) -> int:
    root = tk.Tk()
    root.withdraw()
    options = discover_steam_targets()
    target = ""
    if options:
        choices = "\n".join(f"{index + 1}. {item.binaries}" for index, item in enumerate(options))
        answer = simpledialog.askstring(
            "Select Crusader Kings III",
            f"Detected Steam installations:\n\n{choices}\n\nEnter a number, or leave blank to Browse.",
        )
        if answer and answer.isdigit() and 1 <= int(answer) <= len(options):
            target = str(options[int(answer) - 1].binaries)
    if not target:
        initial = str(options[0].binaries) if options else None
        target = filedialog.askdirectory(title="Select Crusader Kings III binaries directory", initialdir=initial, mustexist=True)
    if not target:
        root.destroy()
        return 2
    selected = select_target(target)
    if selected is None:
        root.destroy()
        return 2
    target = str(selected)
    engine = Installer(package_root=package_root)
    try:
        classification = engine.classify(Path(target))
        if classification.state == "recognized_ufg" and operation == "install":
            proceed = messagebox.askyesno(
                "AWOW UFG will be removed",
                "This CK3 installation uses the AWOW UFG chained loader. Installing AGP-only will remove the AWOW Universal Female Generation folder and logs. Reinstall the latest UFG later if you want UFG again. Continue?",
            )
            if not proceed:
                return 1
        token = None
        if operation == "install":
            token = {"managed_agp": "UPGRADE_AGP_IN_PLACE", "legacy_agp": "UPGRADE_AGP_IN_PLACE", "recognized_ufg": "CONVERT_UFG_TO_AGP", "steam_updated": "ACCEPT_STEAM_UPDATE", "unknown_conflicting": "I_UNDERSTAND_UNKNOWN_CONFLICT"}.get(classification.state)
        elif operation == "uninstall" and classification.state in ("unknown_conflicting", "legacy_agp", "steam_updated"):
            token = "I_UNDERSTAND_UNKNOWN_CONFLICT"
        confirmation = _ask_confirmation(token) if token else None
        result = engine.install(target, confirmation) if operation == "install" else engine.uninstall(target, confirmation)
        messagebox.showinfo("Any-Gender Parenthook", f"{result.operation}: {result.decision}\n{result.message}".strip())
        return 0 if result.decision in ("proceed", "no_op") else 1
    except InstallError as exc:
        messagebox.showerror("Any-Gender Parenthook", str(exc))
        return 1
    finally:
        root.destroy()
