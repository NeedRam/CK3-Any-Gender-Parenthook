from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agp_installer import gui
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
