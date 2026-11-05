@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if not defined PY if exist "%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe" set "PY=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
if not defined PY if exist "%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe" set "PY=%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe"
if not defined PY for %%P in (python.exe) do set "PY=%%~$PATH:P"

if not defined PY (
    echo [X] python.exe not found.
    echo     Install Python 3.10+ with tcl/tk.
    pause
    exit /b 1
)

echo Python: %PY%
"%PY%" --version
"%PY%" -c "import tkinter; print('tkinter: OK')" 2>&1
echo.
"%PY%" "%~dp0lynk_adb_tool.py" --selftest
echo.
echo If adb is empty, install Android platform-tools or add adb to PATH.
pause
