#!/bin/bash
# NAIA 2.0 Electron Shell Mac Launcher (source mode)
# 더블클릭으로 실행 가능한 Mac용 런처 스크립트 (Electron 데스크톱 셸 모드)
# Windows의 run_NAIA_electron.bat 과 동일한 사용자 경험 제공

# ANSI 색상 코드 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 화면 지우기
clear

find_compatible_python() {
    for candidate in python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" &> /dev/null; then
            version_info=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
            if [ -n "$version_info" ]; then
                major="${version_info%%.*}"
                minor="${version_info##*.}"
                if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ] && [ "$minor" -le 12 ]; then
                    echo "$candidate"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║                     🖥️  NAIA 2.0 Electron Launcher                            ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 현재 스크립트 위치로 이동
SCRIPT_DIR="$(dirname "$0")"
cd "$SCRIPT_DIR"

echo -e "${CYAN}📁 프로젝트 디렉토리: ${NC}$(pwd)"
echo ""

# 권한이 없으면 자동으로 설정
if [ ! -x "$0" ]; then
    echo -e "${YELLOW}🔧 첫 실행입니다. 실행 권한을 설정합니다...${NC}"
    chmod +x "$0"
    echo -e "${GREEN}✅ 권한 설정 완료! 다시 더블클릭해주세요.${NC}"
    echo ""
    read -p "엔터를 눌러 종료하고 다시 실행해주세요..."
    exit 0
fi

# Python 설치 확인
echo -e "${BLUE}🐍 Python 환경 확인 중...${NC}"

PYTHON_CMD="$(find_compatible_python)"

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}❌ Python 3.10 ~ 3.12 가 필요합니다 (3.13 이상은 아직 미지원).${NC}"
    echo -e "${CYAN}🔗 Python 3.12 다운로드 페이지를 열고 있습니다...${NC}"
    open "https://www.python.org/downloads/release/python-31210/"
    echo ""
    read -p "Python 3.12 설치 후 엔터를 눌러주세요..."
    exit 1
fi

echo -e "${GREEN}✅ $("$PYTHON_CMD" --version) 사용${NC}"

# Node.js / npm 설치 확인
echo -e "${BLUE}🟢 Node.js 환경 확인 중...${NC}"

if ! command -v npm &> /dev/null; then
    echo -e "${RED}❌ Node.js 가 설치되지 않았습니다. Electron 셸은 Node.js 18 이상이 필요합니다.${NC}"
    echo -e "${CYAN}🔗 Node.js 다운로드 페이지를 열고 있습니다...${NC}"
    open "https://nodejs.org/"
    echo ""
    read -p "Node.js 설치 후 엔터를 눌러주세요..."
    exit 1
fi

echo -e "${GREEN}✅ Node.js $(node --version) / npm $(npm --version) 사용${NC}"
echo ""

# NAIA_web_headless.py 파일 확인
if [ ! -f "NAIA_web_headless.py" ]; then
    echo -e "${RED}❌ NAIA_web_headless.py 파일이 없습니다.${NC}"
    echo "   NAIA 프로젝트 폴더에서 실행해주세요."
    read -p "엔터를 눌러 종료..."
    exit 1
fi

# 가상환경 확인 및 생성
echo -e "${BLUE}📦 가상환경 설정 중...${NC}"

# 기존 venv 가 지원 범위(3.10 ~ 3.12) 밖의 Python 으로 생성되어 있으면 재생성
if [ -x "venv/bin/python" ]; then
    if ! venv/bin/python -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; then
        echo -e "${YELLOW}⚠️  기존 venv 가 지원되지 않는 Python 버전으로 생성되어 있습니다.${NC}"
        read -p "venv 를 삭제하고 $("$PYTHON_CMD" --version) 기준으로 다시 생성할까요? (y/N): " RECREATE_VENV
        if [[ "$RECREATE_VENV" =~ ^[Yy]$ ]]; then
            rm -rf venv
        else
            echo -e "${RED}❌ venv 폴더를 직접 삭제한 뒤 다시 실행해주세요.${NC}"
            read -p "엔터를 눌러 종료..."
            exit 1
        fi
    fi
fi

if [ ! -d "venv" ]; then
    echo -e "${YELLOW}   가상환경이 없습니다. 새로 생성합니다...${NC}"
    "$PYTHON_CMD" -m venv venv

    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ 가상환경 생성 실패${NC}"
        read -p "엔터를 눌러 종료..."
        exit 1
    fi
fi

# 의존성 설치
echo -e "${BLUE}📚 백엔드 라이브러리를 확인하고 설치합니다...${NC}"
venv/bin/python -m pip install -r requirements-headless.txt

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 라이브러리 설치 중 오류 발생${NC}"
    read -p "엔터를 눌러 종료..."
    exit 1
fi

echo ""

# Electron 셸 의존성 설치 (첫 실행에만)
cd app/electron

if [ ! -d "node_modules/electron" ]; then
    echo -e "${BLUE}⚡ Electron 셸 의존성을 설치합니다 (첫 실행에만 수행)...${NC}"
    npm ci --no-audit --no-fund

    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ npm ci 실패. 네트워크 연결을 확인 후 다시 실행해주세요.${NC}"
        read -p "엔터를 눌러 종료..."
        exit 1
    fi
fi

# 첫 실행 시 태그 데이터 설치 마법사를 표시 (portable 빌드와 동일한 데이터 흐름)
# user-data 는 기본적으로 run_NAIA_web.command 와 공유됩니다.
export NAIA_ELECTRON_RUNTIME_INSTALL=1

# File/Edit/View/Window 개발자 메뉴 숨김 (portable 빌드와 동일한 UX).
# 개발자 메뉴가 필요하면 이 줄을 지우세요.
export NAIA_ELECTRON_HIDE_MENU=1

echo ""
echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║              🚀 NAIA 2.0 Electron 셸 (소스 모드) 을 시작합니다!                  ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

npm start

EXIT_CODE=$?

echo ""
echo -e "${YELLOW}터미널을 닫으려면 엔터를 눌러주세요...${NC}"
read

exit $EXIT_CODE
