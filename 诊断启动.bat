@echo off
setlocal
cd /d "%~dp0"

set "PY="

if exist "%~dp0python\python.exe" call :accept "%~dp0python\python.exe"
if defined PY goto found
call :scan "%APPDATA%\uv\python"
if defined PY goto found
call :scan "E:\Code\_tools\uv\python"
if defined PY goto found
for %%P in (python.exe) do call :accept "%%~$PATH:P"
if defined PY goto found

echo python.exe with tkinter not found.
echo   Install Python 3.10+ with tcl/tk, or put a portable python into .\python\
pause
exit /b 1

:found
echo Using Python: %PY%
echo ---- selftest ----
"%PY%" "%~dp0lynk_adb_tool.py" --selftest
echo ---- run ----
"%PY%" "%~dp0lynk_adb_tool.py"
echo.
echo Program exited with code %errorlevel%.
pause
exit /b 0

:scan
rem %1 = uv python root; version numbers change, so enumerate cpython-*
if not exist "%~1" goto :eof
for /d %%D in ("%~1\cpython-*") do (
    if not defined PY call :accept "%%~D\python.exe"
)
goto :eof

:accept
rem %1 = candidate python.exe; accept it only if tkinter imports
if not exist "%~1" goto :eof
"%~1" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof
