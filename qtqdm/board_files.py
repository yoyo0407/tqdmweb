"""Folder browsing and Python command validation for the local app."""

import ctypes
import os
from pathlib import Path
import shlex
import sys


def split_arguments(text):
    if not text.strip():
        return []
    if os.name != "nt":
        return shlex.split(text)
    # Use Windows' parser so quoted paths keep their backslashes.
    parser = ctypes.windll.shell32.CommandLineToArgvW
    parser.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    parser.restype = ctypes.POINTER(ctypes.c_wchar_p)
    count = ctypes.c_int()
    pointer = parser("tqdmboard " + text, ctypes.byref(count))
    if not pointer:
        raise ValueError("Unable to parse command arguments")
    try:
        return [pointer[index] for index in range(1, count.value)]
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free(pointer)


def python_environments(folder):
    candidates = []
    for parent in [folder, *folder.parents]:
        for name in (".venv", "venv"):
            executable = parent / name / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if executable.is_file():
                candidates.append(str(executable))
    candidates.append(sys.executable)
    return list(dict.fromkeys(candidates))


def browse_folder(path):
    folder = Path(path).expanduser().resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("Choose a directory")
    entries = []
    for item in folder.iterdir():
        if item.name.startswith(".") or item.name == "__pycache__":
            continue
        if item.is_dir() or item.suffix.lower() == ".py":
            entries.append({"name": item.name, "path": str(item), "directory": item.is_dir()})
    entries.sort(key=lambda item: (not item["directory"], item["name"].lower()))
    return {"path": str(folder), "parent": str(folder.parent), "entries": entries,
            "python_environments": python_environments(folder)}


def validate_launch(data):
    if not isinstance(data, dict):
        raise ValueError("Expected a launch configuration")
    paths = {}
    for name in ("script", "python", "working_directory"):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        paths[name] = Path(value).expanduser().resolve(strict=True)
    if not paths["script"].is_file() or paths["script"].suffix.lower() != ".py":
        raise ValueError("Choose a Python .py script")
    if not paths["python"].is_file():
        raise ValueError("Python executable does not exist")
    if not paths["working_directory"].is_dir():
        raise ValueError("Working directory does not exist")
    arguments = data.get("arguments", "")
    if not isinstance(arguments, str):
        raise ValueError("Arguments must be command-line text")
    return {**{name: str(value) for name, value in paths.items()},
            "arguments": arguments, "argv": split_arguments(arguments)}
