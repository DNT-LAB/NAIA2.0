#!/usr/bin/env bash
# NAIA 2.0 Web Mode Linux Launcher
# 터미널에서 ./run_NAIA_web.sh 로 실행하는 Linux용 런처 스크립트 (웹 UI 모드)
# Windows의 run_NAIA_web.bat / macOS의 run_NAIA_web.command 와 동일한 사용자 경험 제공

# ANSI 색상 코드 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 터미널에서 직접 실행할 때만 입력을 기다린다 (파이프/CI 실행 시 멈추지 않도록).
pause_if_interactive() {
    if [ -t 0 ]; then
        read -r -p "$1"
    fi
}

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

# 화면 지우기 (터미널일 때만)
[ -t 1 ] && clear

echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║                        🌐 NAIA 2.0 Web Launcher                               ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 현재 스크립트 위치로 이동
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo -e "${CYAN}📁 프로젝트 디렉토리: ${NC}$(pwd)"
echo ""

# Linux 배포판 정보 확인
DISTRO_NAME="$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME")"
echo -e "${BLUE}🐧 시스템 정보:${NC}"
echo -e "   - 배포판: ${DISTRO_NAME:-알 수 없음}"
echo -e "   - 커널: $(uname -r)"
echo -e "   - 아키텍처: $(uname -m)"
echo ""

# --- 소스 업데이트 체크 ----------------------------------------------------
# 채널: clone 의 upstream 브랜치 (현재 origin/future02).
# WARNING: future02 가 main 브랜치로 force merge 되는 경우, 업데이트 기준점을
# 전부 함께 수정해야 한다: run_NAIA_* 런처 6종(.bat/.command/.sh)의 이 블록,
# 데스크톱 셸 업데이트 배너, 기존 clone 들의 upstream 브랜치.
if command -v git > /dev/null 2>&1 && [ -d ".git" ] && git rev-parse --abbrev-ref --symbolic-full-name '@{u}' > /dev/null 2>&1; then
    if git fetch --quiet 2>/dev/null; then
        BEHIND="$(git rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)"
        if [ "${BEHIND:-0}" -gt 0 ] 2>/dev/null && [ -t 0 ]; then
            echo -e "${YELLOW}⬆️  업데이트 가능: 원격 브랜치에 새 커밋 ${BEHIND}개${NC}"
            read -r -p "지금 git pull 로 업데이트할까요? (y/N): " DO_UPDATE
            if [[ "$DO_UPDATE" =~ ^[Yy]$ ]]; then
                # pull 이 이 스크립트 자신을 덮어쓰므로, 성공 시 같은 컴파운드
                # 블록 안에서 exec 로 새 스크립트를 즉시 재실행한다.
                if git pull --ff-only; then
                    echo -e "${GREEN}✅ 업데이트 완료 — 런처를 다시 시작합니다.${NC}"
                    exec bash "$0"
                else
                    echo -e "${RED}❌ git pull 실패 — 현재 버전으로 계속 진행합니다.${NC}"
                fi
            fi
        fi
    fi
fi

# Python 설치 확인
echo -e "${BLUE}🐍 Python 환경 확인 중...${NC}"

PYTHON_CMD="$(find_compatible_python)"

if [ -z "$PYTHON_CMD" ]; then
    CURRENT_PYTHON_VERSION="$(python3 --version 2>/dev/null || true)"
    if [ -n "$CURRENT_PYTHON_VERSION" ]; then
        echo -e "${RED}❌ 현재 Python 버전이 지원 범위 밖입니다: ${CURRENT_PYTHON_VERSION}${NC}"
        echo -e "${YELLOW}   NAIA 2.0은 Python 3.10 ~ 3.12 가 필요합니다 (3.13 이상은 아직 미지원).${NC}"
    else
        echo -e "${RED}❌ Python 3.10 ~ 3.12 가 설치되지 않았습니다 (3.13 이상은 아직 미지원).${NC}"
    fi
    echo -e "${YELLOW}📖 Python 설치 가이드 (배포판 패키지 관리자 사용):${NC}"
    echo "   - Ubuntu/Debian : sudo apt install python3.12 python3.12-venv"
    echo "                     (기본 저장소에 없으면 deadsnakes PPA 또는 pyenv 사용)"
    echo "   - Fedora        : sudo dnf install python3.12"
    echo "   - Arch          : pyenv 또는 AUR 의 python312 사용"
    echo "   설치 후 이 스크립트를 다시 실행해주세요."
    echo ""
    pause_if_interactive "엔터를 눌러 종료..."
    exit 1
fi

PYTHON_VERSION=$("$PYTHON_CMD" --version)
echo -e "${GREEN}✅ $PYTHON_VERSION 사용${NC}"
echo -e "   실행 파일: $(command -v "$PYTHON_CMD")"
echo ""

# 가상환경 확인 및 생성
echo -e "${BLUE}📦 가상환경 설정 중...${NC}"

# 기존 venv 가 지원 범위(3.10 ~ 3.12) 밖의 Python 으로 생성되어 있으면 재생성
if [ -x "venv/bin/python" ]; then
    if ! venv/bin/python -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; then
        echo -e "${YELLOW}⚠️  기존 가상환경이 지원 범위 밖의 Python 으로 생성되어 다시 만들어야 합니다.${NC}"
        RECREATE_VENV=""
        [ -t 0 ] && read -r -p "기존 venv 폴더를 삭제하고 ${PYTHON_VERSION} 기준으로 다시 생성할까요? (y/N): " RECREATE_VENV
        if [[ "$RECREATE_VENV" =~ ^[Yy]$ ]]; then
            rm -rf venv
            echo -e "${GREEN}✅ 기존 가상환경을 삭제했습니다.${NC}"
        else
            echo -e "${RED}❌ Python 3.10 ~ 3.12 로 생성된 가상환경이 필요합니다.${NC}"
            echo "   venv 폴더를 삭제한 뒤 다시 실행해주세요."
            pause_if_interactive "엔터를 눌러 종료..."
            exit 1
        fi
    fi
fi

if [ ! -d "venv" ]; then
    echo -e "${YELLOW}   가상환경이 없습니다. 새로 생성합니다...${NC}"
    if "$PYTHON_CMD" -m venv venv; then
        echo -e "${GREEN}✅ 가상환경 생성 완료${NC}"
    else
        rm -rf venv
        echo -e "${RED}❌ 가상환경 생성 실패${NC}"
        echo -e "${YELLOW}💡 Ubuntu/Debian 은 venv 모듈이 별도 패키지입니다:${NC}"
        echo "   sudo apt install ${PYTHON_CMD}-venv"
        pause_if_interactive "엔터를 눌러 종료..."
        exit 1
    fi
else
    echo -e "${GREEN}✅ 기존 가상환경 발견${NC}"
fi

# 가상환경 활성화
echo -e "${BLUE}🔄 가상환경 활성화 중...${NC}"
# shellcheck disable=SC1091
if source venv/bin/activate; then
    echo -e "${GREEN}✅ 가상환경 활성화 완료${NC}"
    echo -e "   Python 경로: $(command -v python)"
else
    echo -e "${RED}❌ 가상환경 활성화 실패${NC}"
    pause_if_interactive "엔터를 눌러 종료..."
    exit 1
fi

echo ""

# requirements-headless.txt 확인
if [ ! -f "requirements-headless.txt" ]; then
    echo -e "${RED}❌ requirements-headless.txt 파일이 없습니다.${NC}"
    echo "   NAIA 프로젝트 폴더에서 실행해주세요."
    pause_if_interactive "엔터를 눌러 종료..."
    exit 1
fi

# 의존성 설치
echo -e "${BLUE}📚 필요한 라이브러리를 확인하고 설치합니다...${NC}"
echo -e "${YELLOW}   (처음 실행 시 시간이 소요될 수 있습니다)${NC}"
echo ""

python -m pip install --upgrade pip --quiet

if python -m pip install -r requirements-headless.txt; then
    echo ""
    echo -e "${GREEN}✅ 모든 라이브러리 설치 완료${NC}"
else
    echo ""
    echo -e "${RED}❌ 라이브러리 설치 중 오류 발생${NC}"
    echo -e "${YELLOW}💡 해결 방법:${NC}"
    echo "   1. 인터넷 연결을 확인해주세요"
    echo "   2. 터미널에서 'venv/bin/python -m pip install -r requirements-headless.txt' 를 직접 실행해보세요"
    echo ""
    pause_if_interactive "엔터를 눌러 종료..."
    exit 1
fi

echo ""

# NAIA_web_headless.py 파일 확인
if [ ! -f "NAIA_web_headless.py" ]; then
    echo -e "${RED}❌ NAIA_web_headless.py 파일이 없습니다.${NC}"
    echo "   NAIA 프로젝트 폴더에서 실행해주세요."
    pause_if_interactive "엔터를 눌러 종료..."
    exit 1
fi

# NAIA 실행
echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║                 🚀 NAIA 2.0 Headless Web Session 을 시작합니다!                  ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}💡 웹 UI 주소: http://127.0.0.1:7243/ (7243 사용 중이면 다음 사용 가능 포트를 표시합니다)${NC}"
echo -e "${CYAN}💡 백엔드 준비가 끝나면 웹 UI를 자동으로 엽니다.${NC}"
echo -e "${CYAN}💡 터미널 창을 닫지 마세요. 백엔드가 함께 종료됩니다.${NC}"
echo ""

python NAIA_web_headless.py --auto-port "$@"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${PURPLE}🏁 NAIA 2.0 Web 이 정상 종료되었습니다${NC}"
else
    echo -e "${PURPLE}⚠️  NAIA 2.0 Web 이 오류와 함께 종료되었습니다 (종료 코드: $EXIT_CODE)${NC}"
fi
echo ""

deactivate

exit $EXIT_CODE
