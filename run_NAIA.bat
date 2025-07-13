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

pip install -r requirements.txt

python NAIA_cold_v4.py