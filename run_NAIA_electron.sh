#!/usr/bin/env bash
# NAIA 2.0 Electron Shell Linux Launcher (source mode)
# 터미널에서 ./run_NAIA_electron.sh 로 실행하는 Linux용 런처 스크립트 (Electron 데스크톱 셸 모드)
# Windows의 run_NAIA_electron.bat / macOS의 run_NAIA_electron.command 와 동일한 사용자 경험 제공

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
echo -e "${PURPLE}║                     🖥️  NAIA 2.0 Electron Launcher                            ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 현재 스크립트 위치로 이동
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo -e "${CYAN}📁 프로젝트 디렉토리: ${NC}$(pwd)"
echo ""

# --- 소스 업데이트 체크 ----------------------------------------------------
# 채널: clone 의 upstream 브랜치 (현재 origin/future02).
# WARNING: future02 가 main 브랜치로 force merge 되는 경우, 업데이트 기준점을
# 전부 함께 수정해야 한다: run_NAIA_* 런처 6종(.bat/.command/.sh)의 이 블록,
# 소스모드 업데이트 배너 (app/electron/main/main.cjs + updateBannerControls.mjs),
# 기존 clone 들의 upstream 브랜치.
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
    echo -e "${RED}❌ Python 3.10 ~ 3.12 가 필요합니다 (3.13 이상은 아직 미지원).${NC}"
    echo -e "${YELLOW}📖 Python 설치 가이드 (배포판 패키지 관리자 사용):${NC}"
    echo "   - Ubuntu/Debian : sudo apt install python3.12 python3.12-venv"
    echo "                     (기본 저장소에 없으면 deadsnakes PPA 또는 pyenv 사용)"
    echo "   - Fedora        : sudo dnf install python3.12"
    echo "   - Arch          : pyenv 또는 AUR 의 python312 사용"
    echo ""
    pause_if_interactive "Python 3.12 설치 후 엔터를 눌러주세요..."
    exit 1
fi

echo -e "${GREEN}✅ $("$PYTHON_CMD" --version) 사용${NC}"

# Node.js / npm 설치 확인
echo -e "${BLUE}🟢 Node.js 환경 확인 중...${NC}"

if ! command -v npm &> /dev/null; then
    echo -e "${RED}❌ Node.js 가 설치되지 않았습니다. Electron 셸은 Node.js 18 이상이 필요합니다.${NC}"
    echo "   - 권장: nvm (https://github.com/nvm-sh/nvm) 으로 LTS 설치"
    echo "   - 또는 배포판 패키지: sudo apt install nodejs npm / sudo dnf install nodejs"
    echo ""
    pause_if_interactive "Node.js 설치 후 엔터를 눌러주세요..."
    exit 1
fi

echo -e "${GREEN}✅ Node.js $(node --version) / npm $(npm --version) 사용${NC}"
echo ""

# 그래픽 세션 확인 (Electron 은 X11 또는 Wayland 디스플레이가 필요)
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    echo -e "${YELLOW}⚠️  DISPLAY / WAYLAND_DISPLAY 가 비어 있습니다. 데스크톱 세션에서 실행해주세요.${NC}"
    echo "   (SSH/서버 환경이라면 브라우저 모드인 ./run_NAIA_web.sh 를 사용하세요)"
    echo ""
fi

# NAIA_web_headless.py 파일 확인
if [ ! -f "NAIA_web_headless.py" ]; then
    echo -e "${RED}❌ NAIA_web_headless.py 파일이 없습니다.${NC}"
    echo "   NAIA 프로젝트 폴더에서 실행해주세요."
    pause_if_interactive "엔터를 눌러 종료..."
    exit 1
fi

# 가상환경 확인 및 생성
echo -e "${BLUE}📦 가상환경 설정 중...${NC}"

# 기존 venv 가 지원 범위(3.10 ~ 3.12) 밖의 Python 으로 생성되어 있으면 재생성
if [ -x "venv/bin/python" ]; then
    if ! venv/bin/python -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)' 2>/dev/null; then
        echo -e "${YELLOW}⚠️  기존 venv 가 지원되지 않는 Python 버전으로 생성되어 있습니다.${NC}"
        RECREATE_VENV=""
        [ -t 0 ] && read -r -p "venv 를 삭제하고 $("$PYTHON_CMD" --version) 기준으로 다시 생성할까요? (y/N): " RECREATE_VENV
        if [[ "$RECREATE_VENV" =~ ^[Yy]$ ]]; then
            rm -rf venv
        else
            echo -e "${RED}❌ venv 폴더를 직접 삭제한 뒤 다시 실행해주세요.${NC}"
            pause_if_interactive "엔터를 눌러 종료..."
            exit 1
        fi
    fi
fi

if [ ! -d "venv" ]; then
    echo -e "${YELLOW}   가상환경이 없습니다. 새로 생성합니다...${NC}"
    if ! "$PYTHON_CMD" -m venv venv; then
        rm -rf venv
        echo -e "${RED}❌ 가상환경 생성 실패${NC}"
        echo -e "${YELLOW}💡 Ubuntu/Debian 은 venv 모듈이 별도 패키지입니다:${NC}"
        echo "   sudo apt install ${PYTHON_CMD}-venv"
        pause_if_interactive "엔터를 눌러 종료..."
        exit 1
    fi
fi

# 의존성 설치
echo -e "${BLUE}📚 백엔드 라이브러리를 확인하고 설치합니다...${NC}"
if ! venv/bin/python -m pip install -r requirements-headless.txt; then
    echo -e "${RED}❌ 라이브러리 설치 중 오류 발생${NC}"
    pause_if_interactive "엔터를 눌러 종료..."
    exit 1
fi

echo ""

# Electron 셸 의존성 설치 (첫 실행에만)
cd app/electron || exit 1

if [ ! -d "node_modules/electron" ]; then
    echo -e "${BLUE}⚡ Electron 셸 의존성을 설치합니다 (첫 실행에만 수행)...${NC}"
    if ! npm ci --no-audit --no-fund; then
        echo -e "${RED}❌ npm ci 실패. 네트워크 연결을 확인 후 다시 실행해주세요.${NC}"
        pause_if_interactive "엔터를 눌러 종료..."
        exit 1
    fi
fi

# 첫 실행 시 태그 데이터 설치 마법사를 표시 (portable 빌드와 동일한 데이터 흐름)
# user-data 는 기본적으로 run_NAIA_web.sh 와 공유됩니다.
export NAIA_ELECTRON_RUNTIME_INSTALL=1

# File/Edit/View/Window 개발자 메뉴 숨김 (portable 빌드와 동일한 UX).
# 개발자 메뉴가 필요하면 이 줄을 지우세요.
export NAIA_ELECTRON_HIDE_MENU=1

echo ""
echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║              🚀 NAIA 2.0 Electron 셸 (소스 모드) 을 시작합니다!                  ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 추가 인자는 Electron 으로 전달된다 (예: --no-sandbox, --remote-debugging-port=9336)
npm start -- "$@"
EXIT_CODE=$?

exit $EXIT_CODE
