# NAIA 2.0

Headless Remote Web 중심 AI 이미지 생성 앱. **NovelAI / Stable Diffusion WebUI / ComfyUI** 백엔드를 지원합니다.

브라우저에서 접속하는 Remote Web UI가 기본 제품 경로이며, 데스크톱 GUI(PyQt6)는 active source에서 제거되었습니다(필요 시 git history 참조).

---

## 사용 방법 — 세 가지 경로

### A. Python으로 직접 실행 (clone 사용자, 브라우저 모드)

소스를 clone 해서 실행합니다. Python **3.10 ~ 3.12** (3.13 이상은 아직 미지원, 3.12 권장).

```bash
pip install -r requirements-headless.txt
python NAIA_web_headless.py
```

Windows는 `run_NAIA_web.bat`, macOS는 `run_NAIA_web.command` 로도 실행할 수 있습니다.
실행 후 표시되는 로컬 주소를 브라우저에서 열면 됩니다.

### B. 소스에서 Electron 데스크톱 셸 실행 (clone 사용자 + Node.js)

A와 같은 Python 백엔드를 Electron 데스크톱 창에서 실행합니다 (Danbooru 임베드 뷰 등
셸 전용 기능 포함). Python **3.10 ~ 3.12** (3.13 이상 미지원) + **Node.js 18 이상**이 필요합니다.
런처가 `py` 런처로 설치된 3.12 를 자동으로 찾으므로, PATH 기본 Python 이 3.13+ 여도 됩니다.

```bash
# Windows
run_NAIA_electron.bat
# macOS
./run_NAIA_electron.command
```

런처가 venv 생성 → `pip install -r requirements-headless.txt` → `app/electron`에서
`npm ci`(첫 실행에만) → `npm start`를 자동으로 수행합니다.
수동으로 하려면: 위 A의 venv 셋업 후 `cd app/electron && npm ci && npm start`.

- 첫 실행 시 태그 검색 데이터(약 1.4GB) 설치 화면이 표시됩니다 (Portable 빌드와 동일한 흐름).
- user-data는 기본적으로 A(브라우저 모드)와 **공유**됩니다 (Windows: `%APPDATA%\NAIA`).
  A에서 쓰던 설정·토큰·저장물을 그대로 이어서 사용합니다.

### C. Portable 앱 (Release 사용자)

Python 설치 없이 쓰려면 [Releases](../../releases)에서 `NAIA-Portable.zip`을 받습니다.
번들된 Python 런타임 + Electron 셸이 포함되어 있어 압축만 풀면 바로 실행됩니다.

```powershell
# 무결성 검증 (권장)
Get-FileHash .\NAIA-Portable.zip -Algorithm SHA256
Get-Content  .\SHA256SUMS.txt
```

> 이 portable 빌드는 unsigned 베타입니다. 첫 실행 시 Windows SmartScreen 경고가 나타날 수 있으며,
> 배포 아티팩트는 로컬 Microsoft Defender 스캔을 통과하고 `SHA256SUMS.txt`로 검증 가능합니다.

업데이트: A/B(소스) 런처는 시작 시 새 커밋을 자동 확인하고 `git pull`을 제안합니다.
Portable(C)은 앱 내 업데이트(다운로드+검증+재시작)를 지원합니다.

---

## 저장소 구조 — 런타임 vs 개발/릴리스 인프라

clone 하면 실행에 필요한 소스 **외에** maintainer용 빌드/릴리스 인프라도 함께 받습니다.
**그냥 실행만** 하려면 아래 "런타임"만 알면 되고, 나머지는 무시해도 됩니다.

| 구분 | 디렉터리 | 용도 |
|------|----------|------|
| **런타임** (실행에 필요) | `core/` `app/backend/` `app/web/` `interfaces/` `utils/` `data/` `workflows/` `NAIA_web_headless.py` `requirements-headless.txt` | clone 해서 바로 실행 |
| **Electron 셸** (선택) | `app/electron/` | B(소스 Electron 실행)와 Portable 빌드에 사용. A(브라우저 모드)에는 불필요 |
| **개발/릴리스 인프라** (maintainer 전용) | `tools/` `tests/` `release_assets/` `docs/` | 게이트 검증·패키징·릴리스 빌드. 실행에는 불필요 |

- 무엇이 런타임이고 무엇이 개발 전용인지의 **authoritative 정의**는
  [`release_assets/manifests/release_include_exclude_draft.json`](release_assets/manifests/release_include_exclude_draft.json) 입니다.
  Portable Release 패키지는 이 매니페스트에 따라 **런타임만** 포함하며, `tools/` · `tests/` · `docs/` 등은 제외됩니다.
- 기여(contribute)하려면 `tests/`(테스트)와 `tools/`(빌드·게이트)가 필요합니다.

---

## 더 읽어보기

- 레이아웃·런타임 경계 정책: [`PROJECT_LAYOUT_POLICY.md`](PROJECT_LAYOUT_POLICY.md)
- 에이전트/기여 가이드: [`AGENTS.md`](AGENTS.md)

> 참고: `CLAUDE.md`와 각 디렉터리의 상세 가이드는 local-development-only(`*.md` 미추적) 정책이라
> 배포 소스에는 포함되지 않습니다.
