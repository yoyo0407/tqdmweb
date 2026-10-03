"""Use Windows' file / folder dialogs, returning the actual local path."""

import json
import os
from pathlib import Path
import subprocess
from threading import Lock


DIALOG_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.TopMost = $true
try {
    $owner.Show()
    if ($request.kind -eq 'directory') {
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = 'Select Working Directory'
        $dialog.SelectedPath = $request.initial
    } else {
        $dialog = New-Object System.Windows.Forms.OpenFileDialog
        $dialog.InitialDirectory = $request.initial
        $dialog.CheckFileExists = $true
        $dialog.Multiselect = $false
        if ($request.kind -eq 'script') {
            $dialog.Title = 'Select Python Script'
            $dialog.Filter = 'Python Script (*.py)|*.py'
        } else {
            $dialog.Title = 'Select Python Executable'
            $dialog.Filter = 'Executable (*.exe)|*.exe'
        }
    }
    try {
        if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
            if ($request.kind -eq 'directory') { [Console]::Write($dialog.SelectedPath) }
            else { [Console]::Write($dialog.FileName) }
        }
    } finally { $dialog.Dispose() }
} finally { $owner.Dispose() }
'''


class NativePicker:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self._lock = Lock()
        self._process = None
        self._closed = False

    def pick(self, kind, initial=None):
        if kind not in ("script", "python", "directory"):
            raise ValueError("Unknown selection kind")
        if os.name != "nt":
            raise OSError("Native selection currently supports Windows")
        folder = Path(initial or self.directory).expanduser()
        if folder.is_file():
            folder = folder.parent
        if not folder.is_dir():
            folder = self.directory
        powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        with self._lock:
            if self._closed:
                raise ValueError("App is closing")
            if self._process is not None:
                raise ValueError("A selection dialog is already open")
            process = subprocess.Popen([str(powershell), "-NoProfile", "-STA", "-Command", DIALOG_SCRIPT],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
            self._process = process
        try:
            output, error = process.communicate(json.dumps({"kind": kind, "initial": str(folder.resolve())}))
            if process.returncode:
                raise OSError(error.strip() or "File selection was interrupted")
            if not output.strip():
                return None  # Cancel does not change launcher settings.
            path = Path(output.strip()).resolve(strict=True)
            if kind == "directory" and not path.is_dir():
                raise ValueError("Choose a directory")
            if kind != "directory" and (not path.is_file() or path.suffix.lower() != (".py" if kind == "script" else ".exe")):
                raise ValueError("Selected file has the wrong type")
            return str(path)
        finally:
            with self._lock:
                self._process = None

    def close(self):
        with self._lock:
            self._closed = True
            process = self._process
            if process is not None and process.poll() is None:
                process.terminate()
        if process is not None:
            process.wait(timeout=3)
