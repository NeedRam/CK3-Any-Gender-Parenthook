"""Tkinter front end that delegates all safety decisions to :mod:`core`."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from .core import InstallError, Installer
from .discovery import default_target, discover_steam_targets, select_target


def _ask_confirmation(token: str, parent: tk.Misc | None = None) -> str | None:
    return simpledialog.askstring("Confirmation required", f"Type exactly:\n{token}", parent=parent)


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
        if classification.state == "recognized_ufg" and operation == "install":
            proceed = messagebox.askyesno(
                "AWOW UFG will be removed",
                "This CK3 installation uses the AWOW UFG chained loader. Installing AGP-only will remove the AWOW Universal Female Generation folder and logs. Reinstall the latest UFG later if you want UFG again. Continue?",
                parent=root,
            )
            if not proceed:
                return 1
        token = None
        if operation == "install":
            token = {"managed_agp": "UPGRADE_AGP_IN_PLACE", "legacy_agp": "UPGRADE_AGP_IN_PLACE", "recognized_ufg": "CONVERT_UFG_TO_AGP", "steam_updated": "ACCEPT_STEAM_UPDATE", "unknown_conflicting": "I_UNDERSTAND_UNKNOWN_CONFLICT"}.get(classification.state)
        elif operation == "uninstall" and classification.state in ("unknown_conflicting", "legacy_agp", "steam_updated"):
            token = "I_UNDERSTAND_UNKNOWN_CONFLICT"
        confirmation = _ask_confirmation(token, root) if token else None
        result = engine.install(selected, confirmation) if operation == "install" else engine.uninstall(selected, confirmation)
        messagebox.showinfo("Any-Gender Parenthook", f"{result.operation}: {result.decision}\n{result.message}".strip(), parent=root)
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
    target_var = tk.StringVar(root, value=str(default_target(options)))
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
