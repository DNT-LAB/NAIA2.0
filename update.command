#!/bin/bash
# NAIA 2.0 Update Launcher for macOS
# Git 업데이트 후 메인 런처를 이어서 실행한다.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

clear

echo -e "${PURPLE}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${PURPLE}║                           🔄 NAIA 2.0 Updater                                ║${NC}"
echo -e "${PURPLE}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

echo -e "${CYAN}📁 프로젝트 디렉토리: ${NC}$(pwd)"
echo ""

if ! command -v git > /dev/null 2>&1; then
    echo -e "${RED}❌ Git이 설치되어 있지 않습니다.${NC}"
    echo "   Xcode Command Line Tools 또는 Git을 먼저 설치해주세요."
    echo ""
    read -p "엔터를 눌러 종료..."
    exit 1
fi

if [ ! -d ".git" ]; then
    echo -e "${RED}❌ Git 저장소가 아닙니다.${NC}"
    echo "   NAIA 프로젝트 폴더에서 실행해주세요."
    echo ""
    read -p "엔터를 눌러 종료..."
    exit 1
fi

echo -e "${BLUE}🌐 원격 저장소에서 최신 변경사항을 가져오는 중...${NC}"
git pull
PULL_EXIT_CODE=$?

echo ""

if [ $PULL_EXIT_CODE -ne 0 ]; then
    echo -e "${RED}❌ 업데이트 중 오류가 발생했습니다.${NC}"
    echo -e "${YELLOW}💡 확인할 사항:${NC}"
    echo "   1. 인터넷 연결 상태"
    echo "   2. Git 인증 및 저장소 권한"
    echo "   3. 로컬 변경사항 충돌 여부"
    echo ""
    read -p "엔터를 눌러 종료..."
    exit $PULL_EXIT_CODE
fi

echo -e "${GREEN}✅ 업데이트가 완료되었습니다.${NC}"
echo ""

if [ ! -f "run_NAIA.command" ]; then
    echo -e "${RED}❌ run_NAIA.command 파일이 없습니다.${NC}"
    echo "   메인 런처 파일을 확인해주세요."
    echo ""
    read -p "엔터를 눌러 종료..."
    exit 1
fi

# Finder에서 직접 실행되지 못하더라도 업데이트 뒤에는 메인 런처를 바로 이어서 실행한다.
chmod +x "run_NAIA.command" 2>/dev/null || true

echo -e "${BLUE}🚀 업데이트된 NAIA 2.0을 실행합니다...${NC}"
echo ""

bash "$SCRIPT_DIR/run_NAIA.command"
RUN_EXIT_CODE=$?

echo ""
echo -e "${YELLOW}업데이트 런처를 닫으려면 엔터를 눌러주세요...${NC}"
read

exit $RUN_EXIT_CODE
