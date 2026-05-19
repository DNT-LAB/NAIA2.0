#!/bin/bash
# NAIA 2.0 Mac Launcher
# 더블클릭으로 실행 가능한 Mac용 런처 스크립트
# Windows의 .bat 파일과 동일한 사용자 경험 제공

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
                if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; }; then
                    echo "$candidate"
                    return 0
                fi
            fi
        fi
    done
    return 1
}

echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║                       🎨 NAIA 2.0 Legacy Desktop Launcher                      ║${NC}"
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

# macOS 버전 확인
echo -e "${BLUE}🍎 시스템 정보:${NC}"
echo -e "   - macOS: $(sw_vers -productVersion)"
echo -e "   - 아키텍처: $(uname -m)"
echo ""

# Python 설치 확인
echo -e "${BLUE}🐍 Python 환경 확인 중...${NC}"

PYTHON_CMD="$(find_compatible_python)"

if [ -z "$PYTHON_CMD" ]; then
    CURRENT_PYTHON_VERSION="$(python3 --version 2>/dev/null || true)"
    if [ -n "$CURRENT_PYTHON_VERSION" ]; then
        echo -e "${RED}❌ 현재 Python 버전이 너무 낮습니다: ${CURRENT_PYTHON_VERSION}${NC}"
        echo -e "${YELLOW}   NAIA 2.0은 Python 3.10 이상이 필요합니다.${NC}"
    else
        echo -e "${RED}❌ Python 3.10 이상이 설치되지 않았습니다.${NC}"
    fi
    echo -e "${YELLOW}📖 Python 설치 가이드:${NC}"
    echo "   1. 브라우저에서 Python 3.12 다운로드 페이지가 열립니다"
    echo "   2. macOS 설치 파일(.pkg)을 다운로드합니다"
    echo "   3. 다운로드된 .pkg 파일 실행"
    echo "   4. 설치 완료 후 이 스크립트를 다시 실행"
    echo ""
    echo -e "${CYAN}🔗 Python 다운로드 페이지를 열고 있습니다...${NC}"
    open "https://www.python.org/downloads/release/python-31210/"
    echo ""
    read -p "Python 3.10 이상 설치 후 엔터를 눌러주세요..."
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_CMD" --version)
echo -e "${GREEN}✅ $PYTHON_VERSION 사용${NC}"
echo -e "   실행 파일: $(command -v "$PYTHON_CMD")"

# pip 확인
if ! command -v pip3 &> /dev/null; then
    echo -e "${YELLOW}⚠️  pip3가 설치되지 않았습니다. pip를 설치합니다...${NC}"
    "$PYTHON_CMD" -m ensurepip --upgrade
fi

echo ""

# 가상환경 확인 및 생성
echo -e "${BLUE}📦 가상환경 설정 중...${NC}"

if [ -x "venv/bin/python" ]; then
    VENV_VERSION=$(venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)
    if [ -n "$VENV_VERSION" ]; then
        VENV_MAJOR="${VENV_VERSION%%.*}"
        VENV_MINOR="${VENV_VERSION##*.}"
        if [ "$VENV_MAJOR" -lt 3 ] || { [ "$VENV_MAJOR" -eq 3 ] && [ "$VENV_MINOR" -lt 10 ]; }; then
            echo -e "${YELLOW}⚠️  기존 가상환경이 Python ${VENV_VERSION}로 생성되어 다시 만들어야 합니다.${NC}"
            read -p "기존 venv 폴더를 삭제하고 ${PYTHON_VERSION} 기준으로 다시 생성할까요? (y/N): " RECREATE_VENV
            if [[ "$RECREATE_VENV" =~ ^[Yy]$ ]]; then
                rm -rf venv
                echo -e "${GREEN}✅ 기존 가상환경을 삭제했습니다.${NC}"
            else
                echo -e "${RED}❌ Python 3.10 이상으로 생성된 가상환경이 필요합니다.${NC}"
                echo "   venv 폴더를 삭제한 뒤 다시 실행해주세요."
                read -p "엔터를 눌러 종료..."
                exit 1
            fi
        fi
    fi
fi

if [ ! -d "venv" ]; then
    echo -e "${YELLOW}   가상환경이 없습니다. 새로 생성합니다...${NC}"
    "$PYTHON_CMD" -m venv venv
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ 가상환경 생성 완료${NC}"
    else
        echo -e "${RED}❌ 가상환경 생성 실패${NC}"
        read -p "엔터를 눌러 종료..."
        exit 1
    fi
else
    echo -e "${GREEN}✅ 기존 가상환경 발견${NC}"
fi

# 가상환경 활성화
echo -e "${BLUE}🔄 가상환경 활성화 중...${NC}"
source venv/bin/activate

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 가상환경 활성화 완료${NC}"
    echo -e "   Python 경로: $(which python)"
else
    echo -e "${RED}❌ 가상환경 활성화 실패${NC}"
    read -p "엔터를 눌러 종료..."
    exit 1
fi

echo ""

# requirements.txt 확인
if [ ! -f "requirements_mac.txt" ]; then
    echo -e "${RED}❌ requirements.txt 파일이 없습니다.${NC}"
    echo "   NAIA 프로젝트 폴더에서 실행해주세요."
    read -p "엔터를 눌러 종료..."
    exit 1
fi

# 의존성 설치
echo -e "${BLUE}📚 필요한 라이브러리를 확인하고 설치합니다...${NC}"
echo -e "${YELLOW}   (처음 실행 시 시간이 소요될 수 있습니다)${NC}"
echo ""

# pip 업그레이드
pip install --upgrade pip --quiet

# requirements 설치
pip install -r requirements_mac.txt

if [ $? -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ 모든 라이브러리 설치 완료${NC}"
else
    echo ""
    echo -e "${RED}❌ 라이브러리 설치 중 오류 발생${NC}"
    echo -e "${YELLOW}💡 해결 방법:${NC}"
    echo "   1. 인터넷 연결을 확인해주세요"
    echo "   2. 터미널에서 'pip install -r requirements.txt' 명령을 직접 실행해보세요"
    echo ""
    read -p "엔터를 눌러 종료..."
    exit 1
fi

echo ""

# NAIA_cold_v4.py 파일 확인
if [ ! -f "NAIA_cold_v4.py" ]; then
    echo -e "${RED}❌ NAIA_cold_v4.py 파일이 없습니다.${NC}"
    echo "   NAIA 프로젝트 폴더에서 실행해주세요."
    read -p "엔터를 눌러 종료..."
    exit 1
fi

# NAIA 실행
echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║                            🚀 NAIA 2.0을 시작합니다!                           ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}💡 터미널 창을 닫지 마세요. NAIA가 실행 중입니다...${NC}"
echo ""

# Python 스크립트 실행
python NAIA_cold_v4.py --desktop

# 실행 결과 확인
EXIT_CODE=$?

echo ""
echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${PURPLE}║                        🏁 NAIA 2.0이 정상 종료되었습니다                         ║${NC}"
else
    echo -e "${PURPLE}║                     ⚠️  NAIA 2.0이 오류와 함께 종료되었습니다                     ║${NC}"
    echo -e "${PURPLE}║                         종료 코드: $EXIT_CODE                                    ║${NC}"
fi

echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 가상환경 비활성화
deactivate

# 사용자 입력 대기
echo -e "${YELLOW}터미널을 닫으려면 엔터를 눌러주세요...${NC}"
read

# 터미널 창 닫기 (선택사항)
# osascript -e 'tell application "Terminal" to quit'
