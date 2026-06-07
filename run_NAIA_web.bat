@echo off
setlocal
cd /d "%~dp0"

REM ============================================================
REM  NAIA 2.0 - Headless Web Launcher (browser mode)
REM  Backend: Python venv (3.10 - 3.12)
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

if not exist "NAIA_web_headless.py" (
    echo NAIA_web_headless.py was not found.
    echo Run this launcher from the NAIA project directory.
    pause
    exit /b 1
)

REM --- Python venv + dependencies ---
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
echo Creating venv environment for NAIA 2.0...
%PY_CMD% -m venv venv
if errorlevel 1 (
    echo Failed to create the venv environment.
    pause
    exit /b 1
)

:venv_ok
call venv\Scripts\activate.bat

pip install -r requirements-headless.txt

echo Starting NAIA 2.0 Headless Web Session...
echo Web UI: http://127.0.0.1:7243/ ^(or the next available port if 7243 is busy^)
echo The Web UI will open automatically when the backend is ready.

python NAIA_web_headless.py --auto-port
exit /b %errorlevel%

REM ----------------------------------------------------------------
REM try_python <command>: keep the first command whose interpreter
REM reports a version inside the supported 3.10 - 3.12 window.
:try_python
if defined PY_CMD goto :eof
%~1 -c "import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" > nul 2>&1
if not errorlevel 1 set "PY_CMD=%~1"
goto :eof
