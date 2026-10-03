@echo off
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0tqdmboard.py" %*
) else (
    python "%~dp0tqdmboard.py" %*
)
