@echo off
setlocal
cd /d "%~dp0"

set "APP=%~dp0lynk_adb_tool.py"

set "PYW=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\pythonw.exe"
if exist "%PYW%" goto check

set "PYW=%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\pythonw.exe"
if exist "%PYW%" goto check

set "PYW=%~dp0python\pythonw.exe"
if exist "%PYW%" goto check

set "PYW=pythonw.exe"
goto check

:check
"%PYW%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Cannot start: the selected pythonw.exe does not have tkinter.
    echo   %PYW%
    echo.
    echo Run the environment check script, or install Python 3.10+ with tcl/tk.
    pause
    exit /b 1
)

start "" "%PYW%" "%APP%"
exit /b 0
