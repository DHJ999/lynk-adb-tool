@echo off
setlocal
cd /d "%~dp0"

set "PY=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
if not exist "%PY%" set "PY=python"

echo Using Python: %PY%
"%PY%" -c "import tkinter" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python has no tkinter.
    echo Install Python 3.10+ with tcl/tk, or fix the PY path in this script.
    pause
    exit /b 1
)

"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    "%PY%" -m pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: PyInstaller install failed.
        pause
        exit /b 1
    )
)

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

set "ADB_DIR="
if exist "%ANDROID_HOME%\platform-tools\adb.exe" set "ADB_DIR=%ANDROID_HOME%\platform-tools"
if not defined ADB_DIR if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "ADB_DIR=%LOCALAPPDATA%\Android\Sdk\platform-tools"
if not defined ADB_DIR if exist "D:\Android\Sdk\platform-tools\adb.exe" set "ADB_DIR=D:\Android\Sdk\platform-tools"
if not defined ADB_DIR if exist "C:\Android\Sdk\platform-tools\adb.exe" set "ADB_DIR=C:\Android\Sdk\platform-tools"
if not defined ADB_DIR for %%A in (adb.exe) do set "ADB_DIR=%%~dpA"

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
