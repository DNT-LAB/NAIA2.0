# NAIA 2.0

Headless Remote Web 중심 AI 이미지 생성 앱. **NovelAI / Stable Diffusion WebUI / ComfyUI** 백엔드를 지원합니다.

브라우저에서 접속하는 Remote Web UI가 기본 제품 경로이며, 데스크톱 GUI(PyQt6)는 active source에서 제거되었습니다(필요 시 git history 참조).

---

## 사용 방법 — 두 가지 경로

### A. Python으로 직접 실행 (clone 사용자)

소스를 clone 해서 실행합니다. Python **3.12** 권장.

```bash
pip install -r requirements-headless.txt
python NAIA_web_headless.py
```

Windows는 `run_NAIA_web.bat`, macOS는 `run_NAIA_web.command` 로도 실행할 수 있습니다.
실행 후 표시되는 로컬 주소를 브라우저에서 열면 됩니다.

### B. Portable 앱 (Release 사용자)

Python 설치 없이 쓰려면 [Releases](../../releases)에서 `NAIA-Portable.zip`을 받습니다.
번들된 Python 런타임 + Electron 셸이 포함되어 있어 압축만 풀면 바로 실행됩니다.

```powershell
# 무결성 검증 (권장)
Get-FileHash .\NAIA-Portable.zip -Algorithm SHA256
Get-Content  .\SHA256SUMS.txt
```

> 이 portable 빌드는 unsigned 베타입니다. 첫 실행 시 Windows SmartScreen 경고가 나타날 수 있으며,
> 배포 아티팩트는 로컬 Microsoft Defender 스캔을 통과하고 `SHA256SUMS.txt`로 검증 가능합니다.

---

## 저장소 구조 — 런타임 vs 개발/릴리스 인프라

clone 하면 실행에 필요한 소스 **외에** maintainer용 빌드/릴리스 인프라도 함께 받습니다.
**그냥 실행만** 하려면 아래 "런타임"만 알면 되고, 나머지는 무시해도 됩니다.

| 구분 | 디렉터리 | 용도 |
|------|----------|------|
| **런타임** (실행에 필요) | `core/` `app/backend/` `app/web/` `interfaces/` `utils/` `data/` `workflows/` `NAIA_web_headless.py` `requirements-headless.txt` | clone 해서 바로 실행 |
| **개발/릴리스 인프라** (maintainer 전용) | `tools/` `tests/` `release_assets/` `app/electron/` `docs/` | 게이트 검증·패키징·Electron 빌드. 실행에는 불필요 |

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
