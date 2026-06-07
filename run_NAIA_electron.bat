@echo off
setlocal
cd /d "%~dp0"

REM ============================================================
REM  NAIA 2.0 - Electron Shell Launcher (source mode)
REM  Backend: Python venv  /  Shell: Electron via npm
REM ============================================================

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed. NAIA 2.0 requires Python 3.10 or newer.
    echo Opening https://www.python.org/downloads/ for download...
    Powershell -Command "Start-Process https://www.python.org/downloads/"
    pause
    exit /b 1
)

where npm > nul 2>&1
if %errorlevel% neq 0 (
    echo Node.js is not installed. The Electron shell requires Node.js 18 or newer.
    echo Opening https://nodejs.org/ for download...
    Powershell -Command "Start-Process https://nodejs.org/"
    pause
    exit /b 1
)

if not exist "NAIA_web_headless.py" (
    echo NAIA_web_headless.py was not found.
    echo Run this launcher from the NAIA project directory.
    pause
    exit /b 1
)

if not exist "venv\" (
    echo Creating venv environment for the NAIA backend...
    python -m venv venv
    echo.
)

venv\Scripts\python.exe -m pip install -r requirements-headless.txt
if %errorlevel% neq 0 (
    echo Failed to install Python dependencies.
    pause
    exit /b 1
)

cd app\electron

if not exist "node_modules\electron\" (
    echo Installing Electron shell dependencies - first run only...
    call npm ci --no-audit --no-fund
    if errorlevel 1 (
        echo npm ci failed. Check your network connection and try again.
        pause
        exit /b 1
    )
)

REM First run shows the tag-data install wizard, same flow as the portable build.
REM User data is shared with run_NAIA_web.bat by default: %%APPDATA%%\NAIA
set NAIA_ELECTRON_RUNTIME_INSTALL=1

REM Hide the File/Edit/View/Window dev menu for portable-parity UX.
REM Delete this line if you want the developer menu back.
set NAIA_ELECTRON_HIDE_MENU=1

echo Starting NAIA 2.0 - Electron shell, source mode...
call npm start
