from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agp_installer import gui
from agp_installer.core import Result
from agp_installer.discovery import SteamTarget, default_target, select_target, standard_steam_executable


class GuiPathTests(unittest.TestCase):
    def test_default_target_uses_first_discovered_executable(self) -> None:
        discovered = [SteamTarget(Path("C:/Steam One/.../binaries"), Path("C:/Steam One"), "registry")]
        self.assertEqual(default_target(discovered), Path("C:/Steam One/.../binaries/ck3.exe"))

    def test_default_target_falls_back_to_program_files_steam(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"ProgramFiles(x86)": "C:/Program Files (x86)", "ProgramFiles": "C:/Program Files"},
            clear=True,
        ):
            self.assertEqual(
                standard_steam_executable(),
                Path("C:/Program Files (x86)/Steam/steamapps/common/Crusader Kings III/binaries/ck3.exe"),
            )

    def test_initial_target_normalizes_only_windows_drive_prefix(self) -> None:
        self.assertEqual(
            gui.normalize_drive_prefix(r"c:\Steam\steamapps\common\Crusader Kings III\binaries\ck3.exe"),
            r"C:\Steam\steamapps\common\Crusader Kings III\binaries\ck3.exe",
        )
        self.assertEqual(gui.normalize_drive_prefix("relative/path/ck3.exe"), "relative/path/ck3.exe")
        self.assertEqual(gui.normalize_drive_prefix(r"server\share\ck3.exe"), r"server\share\ck3.exe")

    def test_result_message_uses_exact_success_copy(self) -> None:
        self.assertEqual(
            gui._result_message(Result("install", "proceed", "known_clean", "managed_agp", message="technical detail")),
            "AGP installed successfully.",
        )
        self.assertEqual(
            gui._result_message(Result("uninstall", "proceed", "managed_agp", "known_clean", message="technical detail")),
            "AGP uninstalled successfully.",
        )

    def test_result_message_preserves_non_success_detail(self) -> None:
        cases = (
            (Result("install", "abort", "unknown_conflicting", "unknown_conflicting", message="typed confirmation required"), "install: abort\ntyped confirmation required"),
            (Result("uninstall", "reject", "recognized_ufg", "recognized_ufg", message="recognized AWOW UFG is foreign"), "uninstall: reject\nrecognized AWOW UFG is foreign"),
            (Result("install", "rollback", "known_clean", "known_clean", message="artifact verification failed"), "install: rollback\nartifact verification failed"),
            (Result("uninstall", "no_op", "known_clean", "known_clean", message="AGP is not installed"), "uninstall: no_op\nAGP is not installed"),
        )
        for result, expected in cases:
            with self.subTest(decision=result.decision):
                self.assertEqual(gui._result_message(result), expected)

    def test_executable_selection_normalizes_to_binaries_directory(self) -> None:
        self.assertEqual(
            select_target("C:/Steam/steamapps/common/Crusader Kings III/binaries/ck3.exe"),
            Path("C:/Steam/steamapps/common/Crusader Kings III/binaries"),
        )

    def test_browse_updates_only_for_ck3_executable(self) -> None:
        parent = mock.Mock()
        target_var = mock.Mock()
        target_var.get.return_value = "C:/Steam/steamapps/common/Crusader Kings III/binaries/ck3.exe"
        with mock.patch.object(gui.filedialog, "askopenfilename", return_value="D:/Games/Crusader Kings III/binaries/ck3.exe"):
            gui._browse_for_target(parent, target_var)
        target_var.set.assert_called_once_with("D:/Games/Crusader Kings III/binaries/ck3.exe")

        target_var.reset_mock()
        with mock.patch.object(gui.filedialog, "askopenfilename", return_value="D:/Games/other.exe"), mock.patch.object(gui.messagebox, "showerror") as showerror:
            gui._browse_for_target(parent, target_var)
        target_var.set.assert_not_called()
        showerror.assert_called_once()


if __name__ == "__main__":
    unittest.main()
