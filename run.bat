@echo off
setlocal
cd /d "%~dp0"

set "APP=%~dp0lynk_adb_tool.py"
set "PYW="

rem 1) Portable python first: drop a tkinter-enabled build into .\python\
if exist "%~dp0python\pythonw.exe" call :accept "%~dp0python\pythonw.exe"
if defined PYW goto run

rem 2) uv-managed CPython: enumerate cpython-* (version numbers change), keep
rem    the first candidate that can actually import tkinter
call :scan "%APPDATA%\uv\python"
if defined PYW goto run
call :scan "E:\Code\_tools\uv\python"
if defined PYW goto run

rem 3) PATH fallback
for %%P in (pythonw.exe) do call :accept "%%~$PATH:P"
if defined PYW goto run

echo.
echo Cannot start: no pythonw.exe with tkinter found.
echo   Install Python 3.10+ with tcl/tk, or put a portable python into .\python\
echo   Run the debug launcher (see README) to see the full traceback.
echo.
pause
exit /b 1

:run
echo Using pythonw: %PYW%
start "" "%PYW%" "%APP%"
exit /b 0

:scan
rem %1 = uv python root, containing cpython-<ver>-windows-*\pythonw.exe
if not exist "%~1" goto :eof
for /d %%D in ("%~1\cpython-*") do (
    if not defined PYW call :accept "%%~D\pythonw.exe"
)
goto :eof

:accept
rem %1 = candidate pythonw.exe; accept it only if tkinter imports
if not exist "%~1" goto :eof
"%~1" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :eof
set "PYW=%~1"
goto :eof
