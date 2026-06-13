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

**3) 켜기/끄기 — 두 단계**: 둘 다 즉시 발효(이벤트/훅/enqueue 무력화)지만 노출이
다릅니다.
- **Settings 토글(여기)**: 끄면 작동 정지 + **메인 UI 퀵 버튼까지 숨김**. 다시
  켜는 곳도 이 화면뿐.
- **퀵 팝업의 "Activate This Script"**: **작동만** 켜고 끕니다 — 꺼도 버튼은
  남고(흐림 표시) 설정도 계속 편집할 수 있어, 구성해 두고 필요할 때만 켜는
  용도입니다. Settings 행에는 "활성 · 작동 OFF" 칩으로 표시됩니다.

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
  고르면 그에 맞는 입력칸이 나타납니다 —
  `CFG Scale`·`PG.Rescale`(값 범위 "시작,끝,간격" — 예: `5,7,1` = 5·6·7 세 값
  3장) / `Sampler`(**현재 모드의 샘플러 목록에서 체크 선택** — 선택 수 = 생성
  수) / `프롬프트 강조`(**원본 프롬프트**(정확 매칭, 쉼표 포함 가능) + 시작/
  스텝/종료 **가중치 3칸** — 전부 필수. 문법은 모드 자동: NAI(NAID4/4.5)
  `w::원본::`, WEBUI/ComfyUI `(원본:w)`) / `프롬프트 스왑`(**3번째 칸이 열리며**
  [시작 프롬프트] + [Step n 대치 프롬프트] + [추가 +] 빌더로 구성 — Step 1개당
  1장). 시작/원본 프롬프트가 프롬프트 창에 없으면 **토스트로 안내**하고
  중단합니다. 두 축을 조합하면 Generate 1회로 그리드 전체가 **동일 시드**로
  큐에 쌓입니다(상한 32장). **원본 요청은 자동 취소되어 정확히 그리드 장수만
  생성됩니다.** **그리드 합성 저장**(기본 ON)을 켜두면 전 셀 완료 시 축
  타이틀·값 라벨이 붙은 **n×m 합성 PNG**가 저장 폴더의 `grid/` 아래 생성되며,
  "Grid 폴더 열기" 버튼으로 바로 열 수 있습니다. 활성 확장이 있으면 "자동화 /
  고급 기능" 헤더에 연주황 **E{n}** 칩이 표시됩니다(호버 시 활성 확장 목록).
- 공통 **캐릭터 프롬프트 고정**(NAI): 켜면 묶음 전체(원본 포함)가 지금 1회
  전개된 캐릭터 스냅샷을 공유합니다(캐릭터 와일드카드 재롤 방지) — Seed
  Fan-out에서는 원본을 취소·대체해 총 N장이 전부 같은 캐릭터가 됩니다.

### extension.json

```json
{
  "id": "my_extension",
  "name": "My Extension",
  "version": "1.0.0",
  "naia_ext_api": 1,
  "entry": "main.py",
  "description": "패널에 표시될 한 줄 설명 (선택)",
  "homepage": "https://... (선택, 패널에 링크 표시; source_url은 향후 업데이트 체크용 예약)",
  "python": {
    "requirements": ["rapidfuzz>=3.9", "orjson"],
    "max_install_mb": 200
  }
}
```

`naia_ext_api`는 호스트가 지원하는 확장 API 버전(현재 `1`)과 일치해야 하며, 불일치하면
해당 확장만 비활성화되고 앱은 정상 부팅합니다.

**설치 방법 두 가지**:
1. 폴더(`<id>/extension.json + main.py`)를 `<user-data>/extensions/`에 복사.
2. **GitHub URL** — Settings ▸ Extension 상단에 `https://github.com/owner/repo`를 넣고
   "GitHub에서 설치"(git 불필요, zip 다운로드). 설치는 **파일 배치까지만** 하며,
   목록에 "미승인"으로 떠서 직접 승인해야 코드가 실행됩니다(동의 모델).

**의존성(`python.requirements`) 정책** — SSOT를 지키기 위해 의도적으로 제한됩니다. `requirements`는
`["rapidfuzz>=3.9", "orjson"]` 같은 **PyPI 패키지 spec 문자열 배열**만 받습니다(직접 URL·경로·`-r`·옵션 금지):

| 케이스 | 동작 |
|---|---|
| 본체가 이미 가진 패키지(numpy·Pillow·scipy 등) | **재사용** (설치 안 함 — 단일 출처) |
| 본체에 없는 **경량 순수/wheel 패키지** | 확장 폴더 안 `.deps/`에 **격리 설치** (본체 미오염) |
| 본체에 있는데 **다른 버전** 요구 | **거부** (본체 버전을 바꾸지 않음 — fail-closed) |
| **무거운 ML**(torch·tensorflow·onnxruntime-gpu·transformers·nvidia-* 등) | **거부** — 추론은 백엔드(ComfyUI 등)에 위임 |
| **전이(transitive) 의존성**으로 무거운 ML/충돌 버전이 끌려옴 | **거부** — 설치 전 `pip --dry-run`으로 해석된 전체 집합을 검증 |
| **소스 빌드 / URL·VCS·로컬 경로 / `name @ url`** | **거부** — 미리 빌드된 wheel만 (`--only-binary=:all:`) |
| `.deps` 총 용량이 cap 초과(기본 300MB·hard 800MB) | **거부** |

의존성은 **승인 시 자동 설치**됩니다(신뢰 경고에 목록 표시 → 격리 `.deps/`로). 검증은 최상위 spec뿐
아니라 **전이 의존성까지** 본다 — 예: `sentence-transformers`처럼 겉보기 경량이어도 `torch`를 끌어오면
거부됩니다. `onnxruntime`(CPU)·rapidfuzz·orjson 같은 경량 유틸/추론은 잘 동작하지만, torch급 무거운 ML을
in-process로 돌리려는 시도는 (디스크·ABI 충돌·SSOT 때문에) 막힙니다 — 그런 추론은 ComfyUI 노드 등
**외부 백엔드의 몫**입니다. `.deps`는 `sys.modules` 전역 한계상 파일 격리이지 완전한 모듈 격리는 아닙니다
(같은 패키지를 다른 버전으로 쓰는 두 확장은 먼저 로드된 쪽이 이김 — host 충돌은 위처럼 차단).

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
| `ctx.register_panel(fields=[...], title=, on_action=)` | **선언적 설정 폼** 노출(JS 불필요). field: `{key, type: bool/int/float/select/multiselect/text/tags/list/action, label, default, min/max/step, options, help, placeholder, section, order, apply: immediate/next-generation/restart-required, scope: module/global, column: left/right/extra, visible_when: {field, in: [...]}}`. **scope가 노출 위치를 결정**: `"module"`(기본)=퀵 버튼 팝업, `"global"`=Settings 행. `column:"right"`가 보이면 **2단**, `"extra"`가 보이면 **3단**으로 펼쳐지고, `visible_when`은 계단식 조건부 표시. `type:"multiselect"`=체크 칩 다중 선택(값=문자열 배열, 옵션 외 값은 필터), `type:"list"`=동적 행 빌더([추가 +]/×, 값=문자열 배열), `type:"action"`=버튼 — 클릭 시 `on_action(key)` 호출(설정 저장 없음, 예외 격리). 재호출하면 폼이 교체된다(모드 전환 시 옵션 갱신 등). 값은 `settings.json` 라운드트립 |
| `ctx.show_toast(message, level="info")` | 연결된 웹 클라이언트 전원에게 토스트 표시(info/success/warning/error) — 검증 실패 안내 등 사용자 피드백용. 브릿지: 백엔드 `extension_toast` 이벤트 → WS `{type:"toast"}` |
| `ctx.get_api_mode()` | 현재 API 모드("NAI"/"WEBUI"/"COMFYUI") — 모드별 옵션 구성(샘플러 목록 등)에 사용 |
| `ctx.resolve_nai_characters()` | 현재 NAI 캐릭터 설정을 **지금 1회 전개**(와일드카드 포함)한 스냅샷 `{characters, uc, character_positions}` 또는 None. overrides에 실으면 그 요청은 늦은 바인딩(매장 재전개) 대신 스냅샷 사용 — 변형 묶음의 캐릭터 고정용 |
| `ctx.enqueue_generation(prompt=, negative_prompt=, api_mode=, prompt_run_id=, priority=, overrides=, allow_chain=False)` | 생성 요청을 큐에 추가. 반환 `{ok, request_id, message}`. 파생 요청에는 `ext_origin`과 체인 깊이가 찍히며, **확장 파생 이벤트를 처리 중인 동안의 호출은 기본 차단**(확장 간 무한 연쇄 방지 — 의도적 체인은 `allow_chain=True`). 단 체인 깊이 4 초과는 `allow_chain`과 무관하게 무조건 거부 |
| `ctx.cancel_generation(request_id)` | **대기(pending) 중인** 생성 요청을 큐에서 제거 → `{ok, skip_scheduled, message}`. `ok=True`=확정 제거. 큐에 없으면(소비 루프가 먼저 가져간 경합) **실행 전 건너뛰기 톰스톤**을 예약하고 `skip_scheduled=True` — 호출자는 ok와 거의 동일하게 취급하되 이미 실행이 시작된 마이크로초 윈도만 예외. 둘 다 False면 원본이 그대로 생성됨. 용례: X/Y Plot의 "그리드만 생성" |
| `ctx.get_result_image(request_id)` | 완료된 요청의 이미지 조회 → `{ok, image(PIL 사본), file_path, message}`. `generation_result_available` 콜백에서 이벤트의 request_id로 호출하는 패턴(저장 경로는 비동기라 ""일 수 있음 — 이미지는 항상 메모리에 있음). 용례: X/Y 그리드 합성 |
| `ctx.get_save_directory()` | 현재 세션의 자동 저장 디렉터리 경로(str). 확장 산출물(그리드 PNG 등)을 사용자 저장 폴더 곁에 두는 용도 |
| `ctx.load_settings(defaults)` / `ctx.save_settings(dict)` | `settings.json` 읽기(defaults 병합)/쓰기. save는 **무손실 여부**를 bool로 반환 — 직렬화 불가 값은 repr 문자열로 강등 기록하고 False(라운드트립 비보장) |
| `ctx.log(msg)` | `[ext:<id>]` 접두사 콘솔 로그 |
| `ctx.ext_id` `ctx.name` `ctx.version` `ctx.ext_dir` `ctx.api_version` | 식별/경로 |

**공식 이벤트 (v1)**:

| 이벤트 | 페이로드 | 시점 |
|--------|----------|------|
| `generation_request_dispatched` | `request_id`, `prompt_run_id`, `api_mode`, `priority`, `source`(명령 type — 메인 Generate 버튼 = `"generate"`), `ext_origin`(확장 파생 요청이면 그 확장 id), `ext_chain_depth`(파생 체인 깊이, 사용자 요청=0), `params`(자격증명·내부 키 제외 **안전 사본** — 변조해도 실 요청에 반영되지 않음) | 생성 요청이 큐에 들어갈 때 |
| `generation_result_available` | `request_id`, `prompt_run_id`, `api_mode`, `ext_origin`, `ext_chain_depth`(dispatched와 동일한 파생 lineage) | 생성 1장이 완료·저장될 때 |
| `prompt_generated` | PromptContext | 랜덤 프롬프트 파이프라인 완료 시 |

이외 이벤트도 수신되지만 이름/페이로드의 안정성은 보장하지 않습니다.

### 확장이 할 수 있는 것 / 없는 것 (능력 경계 — 에이전트용 레퍼런스)

> 확장은 보통 **코딩 에이전트**(Claude/Codex 등)가 이 문서를 읽고 작성합니다. 그래서 아래는 산문이 아니라
> **"무엇을 하려면 무엇을 쓰는가(의도 → API)"** 와 **"무엇이 구조적으로 불가능하고 host가 어떻게 강제하는가"** 의
> 매핑입니다. NAIA는 가벼운 **오케스트레이터**라 생성·ML은 백엔드(NovelAI/WEBUI/ComfyUI)에 위임합니다 —
> 확장은 "생성을 조합·가공"하되 "생성 엔진이 되지는" 않습니다.

#### ✅ 할 수 있는 것 — 의도 → API

| 하고 싶은 것 | 쓰는 API | 핵심 제약 |
|---|---|---|
| 프롬프트를 바꾼다 | `register_hook` + `execute_pipeline_hook(context)` | `context.{prefix,main,postfix}_tags`·`final_prompt` 수정 후 **`context` 반환**. `hook_point ∈ {pre_processing, post_processing, after_wildcard, final_hookpoint}`, `priority ≥ 100` |
| 변형/추가로 더 생성한다 | `enqueue_generation(prompt=, overrides={...})` | 파생 이벤트 처리 중 호출은 **차단**(재귀 가드). 의도한 체인만 `allow_chain=True`, 깊이 ≤ 4 |
| 대기 중 요청을 취소한다 | `cancel_generation(request_id)` | `pending`만. 경합 시 `skip_scheduled` 톰스톤. 용례: X/Y "그리드만 생성" |
| 완성 이미지를 가공·합성한다 | `get_result_image(request_id)` → PIL 사본 | `generation_result_available` 콜백에서. 저장은 `get_save_directory()` 아래 |
| 설정 화면을 만든다 | `register_panel(fields=[...])` | 선언적(JS 불필요). `scope:"module"`=퀵 팝업 / `"global"`=Settings 행 |
| 사용자에게 알린다 | `show_toast(msg, level)` | `info/success/warning/error` |
| 자체 상태를 저장한다 | `load_settings` / `save_settings` | `settings.json` 라운드트립 |
| 변형 묶음 캐릭터를 고정한다 | `resolve_nai_characters()` | NAI 캐릭터를 지금 1회 전개한 스냅샷 |
| 경량 라이브러리를 쓴다 | manifest `python.requirements` | wheel-only·`.deps` 격리(위 의존성 정책) |

#### ❌ 할 수 없는 것 — host가 강제하는 불변식 (우회 시도는 무의미)

| 못 하는 것 | host가 강제하는 방식 | 대신 이렇게 |
|---|---|---|
| 생성 엔진 교체 / 실제 API 호출 변조 | 엔진 호출은 NAIA가 소유. `params`는 **읽기 전용 안전 사본** | `overrides`·프롬프트 훅으로 조정 |
| API 토큰·자격증명 읽기 | 토큰/키/내부 식별자는 `params`에서 **제거**됨 | (불가 — 설계상 노출 안 함) |
| 무거운 ML을 in-process 실행(torch 등) | denylist + **전이 의존성까지** `pip --dry-run` 검증 | ComfyUI 태거 노드 등 백엔드에 맡기고 결과만 수신 |
| 본체 패키지 버전 바꾸기 | host-satisfied는 재사용, 다른 버전 요구는 거부 | 본체 버전에 맞추거나 자체 로직으로 대체 |
| 소스 빌드 / URL·VCS·로컬 경로 설치 | `--only-binary=:all:` + `name @ url` 직접 참조 거부 | PyPI에 올라온 wheel만 |
| 코어 내부 수정 / 다른 확장 간섭 | `ctx` 표면만 공식, 확장은 서로 격리 | `ctx` 공개 메서드만 사용 |

> `ctx` 표면 **밖의 내부 모듈 import**(예: `from core... import ...`)는 동작하더라도 **비공식**이라
> 릴리즈마다 깨질 수 있습니다. 공식 계약은 `register(ctx)`로 받는 `ctx`의 공개 메서드뿐입니다(`naia_ext_api=1`).

#### ⚠️ 작성 계약 (어기면 버그) — 에이전트 체크리스트

- **무한 루프 방지**: `generation_request_dispatched` 콜백 첫 줄에서 `if info.get("ext_origin"): return`
  (내가 만든 파생 요청을 또 처리하지 않도록).
- **`params`는 읽기 전용 스냅샷**: 직접 바꿔도 실제 생성에 반영되지 않습니다 — 프롬프트는 **훅**으로,
  파라미터는 `enqueue_generation(overrides=...)` 로.
- **훅은 반드시 `context`를 반환**하고, 코어 예약 우선순위(0~99)는 100으로 클램프됩니다.
- **콜백 예외는 격리**되지만 **연속 5회 실패 시 자동 음소거**됩니다 — 조용히 죽지 말고 `show_toast`/`log`로 알리세요.
- **무거운 작업은 자체 스레드/백엔드로**: 콜백은 이벤트 루프 인근에서 돌므로 블로킹 금지.
- **의존성은 manifest로 선언만**: 런타임에 직접 `pip`/`subprocess`로 설치하지 마세요(승인·격리·검증을 우회).

한 줄 요약 — **프롬프트·큐·결과·UI·자체 상태는 자유롭게 주무르되, 생성 엔진·자격증명·본체 환경은 건드리지
못합니다.** "이미지에서 프롬프트 추론" 같은 무거운 일은 ComfyUI 태거 노드에 맡기고 그 결과를 확장이 받아
조합하는 것이 NAIA 철학에 맞습니다.

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
