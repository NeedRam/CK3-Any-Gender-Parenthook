"""PyInstaller entry point for the independent graphical uninstaller."""

import sys
from pathlib import Path

from agp_installer.cli import main
from agp_installer.gui import run


if __name__ == "__main__":
    package_root = Path(sys.executable).resolve().parent.parent if getattr(sys, "frozen", False) else None
    if len(sys.argv) > 1:
        arguments = list(sys.argv[1:])
        if package_root and "--package-root" not in arguments:
            arguments.extend(["--package-root", str(package_root)])
        raise SystemExit(main("uninstall", arguments))
    raise SystemExit(run("uninstall", str(package_root) if package_root else None))
