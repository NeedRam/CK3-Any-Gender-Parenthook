"""Optional Tkinter GUI entry point for local development."""

import argparse

from agp_installer.gui import run


parser = argparse.ArgumentParser()
parser.add_argument("operation", choices=("install", "uninstall"), default="install", nargs="?")
parser.add_argument("--package-root")
args = parser.parse_args()
raise SystemExit(run(args.operation, args.package_root))
