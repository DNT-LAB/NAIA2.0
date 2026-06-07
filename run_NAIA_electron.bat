@echo off
setlocal
cd /d "%~dp0"

REM ============================================================
REM  NAIA 2.0 - Electron Shell Launcher (source mode)
REM  Backend: Python venv (3.10 - 3.12)  /  Shell: Electron via npm
REM ============================================================

REM --- Locate a compatible Python (3.13+ is not supported yet) ---
set "PY_CMD="
call :try_python "py -3.12"
call :try_python "py -3.11"
call :try_python "py -3.10"
call :try_python "python"
if defined PY_CMD goto python_ok

echo NAIA requires Python 3.10 - 3.12. Python 3.13 or newer is not supported yet.
echo Install Python 3.12 and run this launcher again - it is found automatically
echo through the py launcher even when a newer Python stays on PATH.
echo Opening https://www.python.org/downloads/release/python-31210/ ...
Powershell -Command "Start-Process https://www.python.org/downloads/release/python-31210/"
pause
exit /b 1

:python_ok
for /f "delims=" %%v in ('%PY_CMD% --version 2^>^&1') do set "PY_VER=%%v"
echo Using %PY_VER% (%PY_CMD%)

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

REM --- Python venv + backend dependencies ---
if not exist "venv\Scripts\python.exe" goto create_venv

venv\Scripts\python.exe -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" > nul 2>&1
if not errorlevel 1 goto venv_ok

echo The existing venv was created with an unsupported Python version.
set /p RECREATE_VENV=Delete venv and recreate it with a supported Python now? [y/N]:
if /i "%RECREATE_VENV%"=="y" goto recreate_venv
echo Aborted. Delete the venv folder manually, then run this launcher again.
pause
exit /b 1

:recreate_venv
rmdir /s /q venv

:create_venv
echo Creating venv environment for the NAIA backend...
%PY_CMD% -m venv venv
if errorlevel 1 (
    echo Failed to create the venv environment.
    pause
    exit /b 1
)

:venv_ok
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
exit /b %errorlevel%

REM ----------------------------------------------------------------
REM try_python <command>: keep the first command whose interpreter
REM reports a version inside the supported 3.10 - 3.12 window.
:try_python
if defined PY_CMD goto :eof
%~1 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" > nul 2>&1
if not errorlevel 1 set "PY_CMD=%~1"
goto :eof
