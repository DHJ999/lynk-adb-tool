@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0python\python.exe" call :accept "%~dp0python\python.exe"
if defined PY goto gotpy
call :scan_py "%APPDATA%\uv\python"
if defined PY goto gotpy
call :scan_py "E:\Code\_tools\uv\python"
if defined PY goto gotpy
for %%P in (python.exe) do call :accept "%%~$PATH:P"

:gotpy
if not defined PY (
    echo ERROR: python.exe with tkinter not found.
    echo   Install Python 3.10+ with tcl/tk, or put a portable python into .\python\
    pause
    exit /b 1
)

echo Using Python: %PY%

"%PY%" -m PyInstaller --version >nul 2>&1
if not errorlevel 1 goto have_pyinstaller

echo Installing PyInstaller into %PY% ...
"%PY%" -m pip install pyinstaller >nul 2>&1
"%PY%" -m PyInstaller --version >nul 2>&1
if not errorlevel 1 goto have_pyinstaller

rem uv-managed CPython refuses pip installs (PEP 668); build from a local venv instead
echo uv-managed Python blocks pip installs; creating a local .venv ...
"%PY%" -m venv "%~dp0.venv"
if errorlevel 1 (
    echo ERROR: failed to create .venv
    pause
    exit /b 1
)
set "PY=%~dp0.venv\Scripts\python.exe"
echo Using Python: %PY%
"%PY%" -m pip install --disable-pip-version-check pyinstaller
if errorlevel 1 (
    echo ERROR: PyInstaller install failed.
    pause
    exit /b 1
)

:have_pyinstaller

echo Building LynkAdbTool.exe ...
"%PY%" -m PyInstaller --noconfirm --clean LynkAdbTool.spec
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

set "OUT=release\LynkAdbTool"
if not exist "%OUT%" mkdir "%OUT%"
xcopy /e /i /y "dist\LynkAdbTool" "%OUT%" >nul

rem drop leftovers from the previous build (old adb/aapt2 would be packaged again)
if exist "%OUT%\tools\adb" rd /s /q "%OUT%\tools\adb"
if exist "%OUT%\tools\aapt2" rd /s /q "%OUT%\tools\aapt2"

set "ADB_DIR="
if exist "%ANDROID_HOME%\platform-tools\adb.exe" set "ADB_DIR=%ANDROID_HOME%\platform-tools"
if not defined ADB_DIR if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB_DIR=%LOCALAPPDATA%\Android\Sdk\platform-tools"
if not defined ADB_DIR if exist "D:\Android\Sdk\platform-tools\adb.exe" set "ADB_DIR=D:\Android\Sdk\platform-tools"
if not defined ADB_DIR if exist "C:\Android\Sdk\platform-tools\adb.exe" set "ADB_DIR=C:\Android\Sdk\platform-tools"
rem bare "for %%A in (adb.exe)" only looks in the current directory, so search PATH properly
if not defined ADB_DIR call :find_adb_in_path

if defined ADB_DIR (
    if not exist "%OUT%\tools\adb" mkdir "%OUT%\tools\adb"
    copy /y "%ADB_DIR%\adb.exe" "%OUT%\tools\adb\" >nul
    copy /y "%ADB_DIR%\AdbWinApi.dll" "%OUT%\tools\adb\" >nul
    copy /y "%ADB_DIR%\AdbWinUsbApi.dll" "%OUT%\tools\adb\" >nul
    echo Bundled adb from %ADB_DIR%
) else (
    echo WARNING: adb not found in ANDROID_HOME / LOCALAPPDATA / SDK / PATH
    echo The release will rely on PATH / Android SDK on the user's machine.
)

rem aapt2 powers app names and the Launch button; a portable build must ship it,
rem otherwise Launch stays greyed out on machines without an Android SDK
set "AAPT2="
if exist "%~dp0tools\aapt2\aapt2.exe" set "AAPT2=%~dp0tools\aapt2\aapt2.exe"
if not defined AAPT2 call :find_aapt2 "%ANDROID_HOME%"
if not defined AAPT2 call :find_aapt2 "%ANDROID_SDK_ROOT%"
if not defined AAPT2 call :find_aapt2 "%LOCALAPPDATA%\Android\Sdk"
if not defined AAPT2 call :find_aapt2 "D:\Android\Sdk"
if not defined AAPT2 call :find_aapt2 "C:\Android\Sdk"
if not defined AAPT2 call :find_aapt2 "E:\Android\Sdk"
rem derive from adb location: <sdk>\platform-tools\adb.exe or a sibling sdk\ directory
if defined ADB_DIR if not defined AAPT2 call :find_aapt2_near "%ADB_DIR%"

if defined AAPT2 (
    if not exist "%OUT%\tools\aapt2" mkdir "%OUT%\tools\aapt2"
    copy /y "%AAPT2%" "%OUT%\tools\aapt2\" >nul
    echo Bundled aapt2 from %AAPT2%
) else (
    echo WARNING: aapt2 not found, the release cannot parse app names / launch entries.
    echo   Put aapt2.exe into tools\aapt2\ or install Android build-tools.
)

copy /y README.md "%OUT%\" >nul
copy /y LICENSE "%OUT%\" >nul
if exist assets xcopy /e /i /y assets "%OUT%\assets" >nul

if exist "release\LynkAdbTool-win64.zip" del /q "release\LynkAdbTool-win64.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'release\LynkAdbTool\*' -DestinationPath 'release\LynkAdbTool-win64.zip' -Force"

echo.
echo Done:
echo   release\LynkAdbTool\
echo   release\LynkAdbTool-win64.zip
pause
exit /b 0

:scan_py
rem %1 = uv python root; enumerate cpython-* so a version bump cannot break it
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

:find_aapt2
rem %1 = SDK root; take the first existing build-tools dir in reverse name order
if not exist "%~1\build-tools" goto :eof
for /f "delims=" %%V in ('dir /b /ad /o-n "%~1\build-tools" 2^>nul') do (
    if not defined AAPT2 if exist "%~1\build-tools\%%V\aapt2.exe" set "AAPT2=%~1\build-tools\%%V\aapt2.exe"
)
goto :eof

:find_adb_in_path
for /f "delims=" %%P in ('where adb.exe 2^>nul') do (
    if not defined ADB_DIR set "ADB_DIR=%%~dpP"
)
goto :eof

:find_aapt2_near
rem %1 = platform-tools dir; try <parent>\build-tools and <parent>\sdk\build-tools
for %%D in ("%~1\..") do call :find_aapt2 "%%~fD"
if not defined AAPT2 for %%D in ("%~1\..\sdk") do call :find_aapt2 "%%~fD"
goto :eof
