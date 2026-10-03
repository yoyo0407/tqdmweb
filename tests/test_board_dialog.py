import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from qtqdm.board_dialog import NativePicker, DIALOG_SCRIPT


@unittest.skipUnless(os.name == "nt", "Windows native dialogs")
class NativePickerTests(unittest.TestCase):
    def test_installed_windows_dialog_initialization_without_interaction(self):
        # Instantiate native controls and exercise Cancel without showing a modal window.
        script = DIALOG_SCRIPT.replace("$owner.Show()", "")
        script = script.replace("$dialog.ShowDialog($owner)", "[System.Windows.Forms.DialogResult]::Cancel")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        for kind in ("script", "python", "directory"):
            with self.subTest(kind=kind):
                result = subprocess.run([str(powershell), "-NoProfile", "-STA", "-Command", script],
                                        input=json.dumps({"kind": kind, "initial": str(Path.cwd())}),
                                        capture_output=True, text=True, encoding="utf-8", timeout=10,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")
    def test_unicode_path_is_passed_as_data_and_cancel_returns_none(self):
        with TemporaryDirectory(prefix="board picker ") as directory:
            root = Path(directory)
            script = root / "中文 script.py"
            script.write_text("", encoding="utf-8")
            process = Mock(returncode=0)
            process.communicate.return_value = (str(script), "")
            with patch("qtqdm.board_dialog.subprocess.Popen", return_value=process) as launch:
                picker = NativePicker(root)
                self.assertEqual(picker.pick("script", str(script)), str(script))
                command = launch.call_args.args[0]
                self.assertIn("-STA", command)
                self.assertEqual(command[-1], DIALOG_SCRIPT)
                request = json.loads(process.communicate.call_args.args[0])
                self.assertEqual(request, {"kind": "script", "initial": str(root)})
                process.communicate.return_value = ("", "")
                self.assertIsNone(picker.pick("directory"))
                picker.close()

    def test_invalid_selection_and_duplicate_dialog_are_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.txt"
            path.write_text("", encoding="utf-8")
            picker = NativePicker(directory)
            process = Mock(returncode=0)
            process.communicate.return_value = (str(path), "")
            with patch("qtqdm.board_dialog.subprocess.Popen", return_value=process):
                with self.assertRaises(ValueError):
                    picker.pick("script")
            with self.assertRaises(ValueError):
                picker.pick("unknown")
            picker._process = process
            with self.assertRaises(ValueError):
                picker.pick("script")
            process.poll.return_value = None
            picker.close()
            process.terminate.assert_called_once()
            with self.assertRaises(ValueError):
                picker.pick("script")
