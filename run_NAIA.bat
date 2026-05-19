@echo off

python --version > nul 2>&1
if %errorlevel% equ 0 (
    goto install
) else (
    echo Python 3.10.6 is not installed.
    echo Opening https://www.python.org/downloads/release/python-3106/ for download...
    Powershell -Command "Start-Process https://www.python.org/downloads/release/python-3106/"
    exit /b
)

:install

if not exist "venv\" (
    echo Creating .venv environment for execute NAIA2.0...
    python -m venv venv
    echo.
)

call venv\Scripts\activate.bat

pip install -r requirements-headless.txt

if not exist "NAIA_web_headless.py" (
    echo NAIA_web_headless.py was not found.
    echo Run this launcher from the NAIA project directory.
    exit /b 1
)

echo Starting NAIA 2.0 Headless Web Session...
echo Web UI: http://127.0.0.1:7243/ ^(or the next available port if 7243 is busy^)

python NAIA_web_headless.py --auto-port
