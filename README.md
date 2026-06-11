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

## 🧩 Extensions (사용자 확장) — experimental

NAIA의 **메인 코드를 수정하지 않고** Python으로 기능을 추가하는 공식 방법입니다.
확장은 user-data 아래에 두므로 **앱을 업데이트해도 그대로 유지**됩니다.

> ⚠️ **신뢰 경고**: 확장은 NAIA와 같은 프로세스에서 실행되는 임의의 Python 코드이며
> 샌드박스가 없습니다. 생성 파이프라인과 API 토큰 등 자격증명에 접근할 수 있으므로,
> **제작자를 신뢰할 수 있는 확장만** 설치하세요.

### 설치 위치

```
<user-data>/extensions/<확장-id>/
├── extension.json    # 매니페스트 (필수)
├── main.py           # 진입점 — register(ctx) 함수를 export (필수)
└── settings.json     # 확장별 설정 (선택)
```

`<user-data>` 위치: 설치형(A/B) = Windows `%APPDATA%\NAIA`, Portable(C) = `<설치 폴더>\user-data`.
백엔드를 한 번 실행하면 `extensions/` 폴더가 자동 생성됩니다.

### 사용 매뉴얼 — Settings ▸ Extension

확장 관리는 우측 탭 바의 **⚙ Settings** 탭에 있습니다. 좌측 카테고리에서 **Extension**을
선택하세요 (Global은 추후 전역 설정이 들어올 자리입니다).

**1) 설치**: 위 `extensions/` 폴더에 확장 폴더를 넣고 Settings ▸ Extension을 열면 즉시
"미승인"으로 나타납니다 — 이 단계에선 매니페스트만 읽으며 **확장 코드는 한 줄도 실행되지
않습니다**.

**2) 활성화(최초 승인)**: 토글 클릭 → 신뢰 경고 확인("신뢰하고 활성화") → **재시작 없이
그 자리에서 로드**됩니다.

**3) 켜기/끄기(soft)**: 로드된 확장의 토글은 즉시 발효 — 이벤트/훅/enqueue가 모두
무력화되고 다시 켜면 곧바로 복귀합니다. **끄면 메인 UI의 퀵 버튼도 함께 사라지며**,
다시 켜는 곳은 이 설정 화면뿐입니다(퀵 팝업의 "Activate This Script" 스위치와 같은
플래그 — 팝업에서 끄는 순간 버튼·팝업이 사라집니다).

**4) 퀵 버튼 위치**: 켜진 확장은 행의 **"퀵 버튼 위치"** 선택으로 메인 UI 어디에 버튼을
둘지 정합니다 — **도구바(Tools)**(TOOLS & ASSISTANTS 아래, 기본값) / **자동화·고급
기능**(런처 카테고리 메뉴 안) / **없음**. 버튼을 누르면 해당 확장의 **퀵 팝업**이 열립니다:
`Activate This Script` 스위치 + 확장이 선언한 설정 폼(아래 `register_panel`) — 설정
변경은 저장 즉시 `settings.json`에 반영됩니다.

> **노출 계약**: Settings ▸ Extension 행은 확장의 **전역 설정**(켜기/끄기·버튼 위치·차단,
> `scope:"global"` 필드 — 저장 경로 등)만 다루고, **실제 동작 설정**(`scope:"module"`,
> 기본값)은 퀵 버튼 팝업에만 그려집니다. 두 화면은 서로의 영역을 침범하지 않습니다.

**5) 차단(hard)**: ⋯ 메뉴의 차단은 다음 부팅부터 import 자체를 막습니다. 확장 코드
업데이트 반영도 재시작이 필요합니다(Python은 안전한 리로드가 불가).

**6) 오류 복구**: 오류 확장은 적색 칩+사유가 표시되고 **재시도** 버튼으로 수정 후 즉시
재로드할 수 있습니다.

> 기존 설치 사용자: 이 기능 도입 후 첫 실행에서 이미 설치돼 있던 확장은 자동 승인됩니다
> (1회 안내 토스트). 이후 새로 설치하는 확장부터 승인 절차가 적용됩니다.

**Seed Fan-out으로 따라하기**: 샘플을 설치하면 도구바에 `🧩 Seed Fan-out` 버튼이
나타납니다. 두 가지 모드가 있습니다(설정은 **다음 생성부터** 적용):

- **Seed Fan-out**: Generate 1회 → 동일 프롬프트 총 **생성 수**만큼(원본 포함) 큐에
  쌓입니다. 시드 방식 = `random` / `+1` / `-1` / `fixed`(전부 원본과 같은 시드 —
  입력창 와일드카드 변주 비교용).
- **X/Y Plot**: 모드를 바꾸면 팝업 우측에 X/Y 축 설정이 펼쳐집니다. 축 **종류**를
  고르면 그에 맞는 입력칸이 나타납니다 — `CFG Scale`·`PG.Rescale`(값 범위
  "시작,끝,간격" — 예: `5,7,1` = 5·6·7 세 값 3장) / `Sampler`(쉼표 목록, 1개당
  1장) / `프롬프트 강조`(키워드 가중 사다리 — `{kw}`/`[kw]`) / `프롬프트
  스왑`(키워드를 대체값들로 치환, `^`=콤마). 두 축을 조합하면 Generate 1회로
  그리드 전체가 **동일 시드**로 큐에 쌓입니다(상한 32장).
- 공통 **캐릭터 프롬프트 고정**(NAI): 켜면 파생 장들이 지금 1회 전개된 캐릭터
  스냅샷을 공유합니다(캐릭터 와일드카드 재롤 방지).

### extension.json

```json
{
  "id": "my_extension",
  "name": "My Extension",
  "version": "1.0.0",
  "naia_ext_api": 1,
  "entry": "main.py",
  "description": "패널에 표시될 한 줄 설명 (선택)",
  "homepage": "https://... (선택, 패널에 링크 표시; source_url은 향후 업데이트 체크용 예약)"
}
```

`naia_ext_api`는 호스트가 지원하는 확장 API 버전(현재 `1`)과 일치해야 하며, 불일치하면
해당 확장만 비활성화되고 앱은 정상 부팅합니다.

### main.py — 최소 예제

```python
def register(ctx):
    # 1) 생성 요청 구독 (큐에 들어가는 모든 생성)
    ctx.subscribe("generation_request_dispatched", on_dispatched)

    # 2) 프롬프트 파이프라인 훅 (프롬프트를 직접 변조)
    ctx.register_hook(MyHook())

    ctx.log("loaded!")   # 콘솔에 [ext:my_extension] loaded!

def on_dispatched(info):
    if info.get("ext_origin"):       # 확장이 만든 파생 요청이면 무시 (무한 재귀 방지!)
        return
    seed = info["params"]["seed"]    # params = 읽기 전용 스냅샷
    # 추가 생성을 큐에 넣기:
    # ctx.enqueue_generation(prompt=..., overrides={"seed": seed + 1})

class MyHook:
    def get_pipeline_hook_info(self):
        # hook_point: pre_processing | post_processing | after_wildcard | final_hookpoint
        return {"target_pipeline": "PromptProcessor", "hook_point": "final_hookpoint", "priority": 100}
    def execute_pipeline_hook(self, context):
        context.postfix_tags.append("masterpiece")   # 태그 변조
        return context                               # 반드시 context 반환
```

### ExtensionContext API (naia_ext_api = 1)

`register(ctx)`로 전달되는 `ctx`의 공개 메서드가 **유일한 공식 표면**입니다.
그 외 내부 모듈 import는 동작하더라도 다음 릴리즈에서 깨질 수 있습니다.

| 메서드 | 설명 |
|--------|------|
| `ctx.subscribe(event, fn)` / `ctx.unsubscribe(event, fn)` | 이벤트 구독. 콜백 예외는 격리되며 연속 5회 실패 시 자동 음소거 |
| `ctx.register_hook(hook)` | 프롬프트 파이프라인 훅 등록. priority < 100은 100으로 클램프(0~99 = 코어 예약) |
| `ctx.register_panel(fields=[...], title=)` | **선언적 설정 폼** 노출(JS 불필요). field: `{key, type: bool/int/float/select/text/tags (+action 예약), label, default, min/max/step, options, help, section, order, apply: immediate/next-generation/restart-required, scope: module/global, column: left/right, visible_when: {field, in: [...]}}`. **scope가 노출 위치를 결정**: `"module"`(기본)=퀵 버튼 팝업(실제 동작 설정), `"global"`=Settings ▸ Extension 행(전역 설정 — 저장 경로 등). `column:"right"` 필드가 표시되면 **2단**으로 펼쳐지고, `visible_when`으로 모드별 조건부 표시(예: 복잡 모드 선택 시 우측 패널 등장). 값은 `settings.json` 라운드트립 — `ctx.load_settings()`와 같은 파일 |
| `ctx.resolve_nai_characters()` | 현재 NAI 캐릭터 설정을 **지금 1회 전개**(와일드카드 포함)한 스냅샷 `{characters, uc, character_positions}` 또는 None. overrides에 실으면 그 요청은 늦은 바인딩(매장 재전개) 대신 스냅샷 사용 — 변형 묶음의 캐릭터 고정용 |
| `ctx.enqueue_generation(prompt=, negative_prompt=, api_mode=, prompt_run_id=, priority=, overrides=, allow_chain=False)` | 생성 요청을 큐에 추가. 반환 `{ok, request_id, message}`. 파생 요청에는 `ext_origin`과 체인 깊이가 찍히며, **확장 파생 이벤트를 처리 중인 동안의 호출은 기본 차단**(확장 간 무한 연쇄 방지 — 의도적 체인은 `allow_chain=True`). 단 체인 깊이 4 초과는 `allow_chain`과 무관하게 무조건 거부 |
| `ctx.load_settings(defaults)` / `ctx.save_settings(dict)` | `settings.json` 읽기(defaults 병합)/쓰기 |
| `ctx.log(msg)` | `[ext:<id>]` 접두사 콘솔 로그 |
| `ctx.ext_id` `ctx.name` `ctx.version` `ctx.ext_dir` `ctx.api_version` | 식별/경로 |

**공식 이벤트 (v1)**:

| 이벤트 | 페이로드 | 시점 |
|--------|----------|------|
| `generation_request_dispatched` | `request_id`, `prompt_run_id`, `api_mode`, `priority`, `source`(명령 type — 메인 Generate 버튼 = `"generate"`), `ext_origin`(확장 파생 요청이면 그 확장 id), `ext_chain_depth`(파생 체인 깊이, 사용자 요청=0), `params`(자격증명·내부 키 제외 **안전 사본** — 변조해도 실 요청에 반영되지 않음) | 생성 요청이 큐에 들어갈 때 |
| `generation_result_available` | `request_id`, `prompt_run_id`, `api_mode`, `ext_origin`, `ext_chain_depth`(dispatched와 동일한 파생 lineage) | 생성 1장이 완료·저장될 때 |
| `prompt_generated` | PromptContext | 랜덤 프롬프트 파이프라인 완료 시 |

이외 이벤트도 수신되지만 이름/페이로드의 안정성은 보장하지 않습니다.

### 샘플: Seed Fan-out

[`release_assets/samples/extensions/seed_fanout/`](release_assets/samples/extensions/seed_fanout/)
— Generate 버튼을 누르면 **동일 프롬프트에서 시드만 바꾼 변형 n장**(Random / +1 / -1 방식)을
큐에 추가하는 완전한 예제입니다. 폴더를 `<user-data>/extensions/`로 복사하고 재시작하면
바로 동작하며, `settings.json`으로 장수/방식을 조정합니다(재시작 불필요).
구독·재귀 가드·enqueue·설정 영속까지 확장 API 전체를 시연하므로 새 확장의 출발점으로 쓰세요.

### 관리/문제해결

- **끄기(개별)**: `<user-data>/config/extensions.json`에 `{"disabled": ["확장id"]}`
- **끄기(전체)**: 환경변수 `NAIA_DISABLE_EXTENSIONS=1`
- **로그**: 확장 로드/오류는 백엔드 콘솔에 `Remote Web: extension ...` / `[ext:<id>] ...`로 출력
- 깨진 확장은 **그 확장만** 비활성화되고 부팅·생성은 계속됩니다(per-extension 격리)

---

## 더 읽어보기

- 레이아웃·런타임 경계 정책: [`PROJECT_LAYOUT_POLICY.md`](PROJECT_LAYOUT_POLICY.md)
- 에이전트/기여 가이드: [`AGENTS.md`](AGENTS.md)

> 참고: `CLAUDE.md`와 각 디렉터리의 상세 가이드는 local-development-only(`*.md` 미추적) 정책이라
> 배포 소스에는 포함되지 않습니다.
