@echo off

rem Python 3.12 버전이 설치되어 있는지 확인합니다.
py -3.12 --version > nul 2>&1
if %errorlevel% equ 0 (
    echo Python 3.12.x is installed.
    goto install
) else (
    echo Python 3.12.x is not installed.
    echo Opening https://www.python.org/downloads/release/python-3119/ for download...
    Powershell -Command "Start-Process https://www.python.org/downloads/release/python-3119/"
    exit /b
)

:install

if not exist "venv\" (
    echo Creating .venv environment with Python 3.13...
    rem [수정] py -3.12 플래그를 사용하여 3.12.x 버전으로 venv 생성을 강제합니다.
    py -3.12 -m venv venv
    echo.
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo Installing required packages from requirements.txt...
pip install -r requirements.txt

echo Starting NAIA...
python NAIA_cold_v4.py

rem 프로그램 종료 후에도 창을 닫지 않고 대기
pause