# CLAUDE.md — utils/

> 순수 유틸리티 모듈 컬렉션. UI/컨트롤러에 의존하지 않는 독립적 기능을 제공합니다.

---

## 구조 및 원칙

```
utils/
  ├── image_info.py           → 이미지 메타데이터 추출
  ├── token_calculator.py     → 프롬프트 토큰 계산 (CLIP 근사)
  ├── translator.py           → 한글 → 영어 번역
  ├── load_generation_params.py → 생성 파라미터 모드별 저장/로드
  └── cloudflared.py          → Cloudflared 터널 관리 (바이너리 다운로드 + Quick Tunnel)
```

**설계 원칙**:
- UI/컨트롤러에 의존하지 않음 (독립성, 재사용성)
- 전역 싱글톤 지양, 팩토리 패턴 또는 모듈 수준 함수 선호
- 예외 안전: 모든 유틸리티가 예외를 catch하고 None 또는 빈 값 반환
- 대형 연산은 호출부에서 스레딩/취소 제어

---

## 이미지 메타데이터 추출 (`image_info.py`)

### ImageMetadataExtractor

**지원 포맷**: NovelAI (Comment/Stealth PNG), WebUI (parameters/EXIF), 일반 JSON

#### 주요 메서드

| 메서드 | 반환 | 설명 |
|--------|------|------|
| `has_metadata(image_path)` | `bool` | 메타데이터 존재 확인 (Comment → parameters → EXIF → Stealth 순) |
| `extract_metadata(image_path)` | `Optional[Dict]` | 메타데이터 추출 |
| `detect_software(metadata)` | `str` | `'nai'` / `'webui'` / `'unknown'` |

#### 반환 구조

**NovelAI**: `{'type': 'nai', 'prompt': ..., 'uc': ..., 'parameters': {steps, scale, seed, sampler, ...}, 'characters': [...], 'characters_uc': [...]}`

**WebUI**: `{'type': 'webui', 'prompt': ..., 'negative': ..., 'parameters': {steps, sampler, cfg_scale, seed, size, model, ...}}`

#### Stealth PNG

알파 채널 LSB에 메타데이터를 숨기는 방식. RGBA 이미지만 지원.
동작: 시그니처 확인 → 길이 읽기 → 바이너리 → gzip 해제 → UTF-8 디코딩.

#### 주의사항

- 모든 텍스트 디코딩에 `errors='ignore'` 사용
- 큰 이미지(4K+)는 로드 시 느릴 수 있음
- 모든 메서드가 예외를 catch하고 None/False 반환

---

## 토큰 계산 (`token_calculator.py`)

### TokenCalculator

GPT-2 (tiktoken) 기반 토큰 카운트 + CLIP 근사 보정.

#### 주요 함수

```python
from utils.token_calculator import count_tokens, count_prompt_tokens, format_token_label

# 단일 텍스트
tokens = count_tokens("1girl, smile", current_mode="NAI")

# 메인 + 캐릭터 (반환: {'main': 15, 'character': 8, 'total': 23})
result = count_prompt_tokens(main_prompt, character_prompt, current_mode="NAI")

# UI 레이블 포맷 (반환: "Estimated Tokens : 23 (Main 15 + Character 8)")
label = format_token_label(result, mode="NAI")

# 싱글톤 인스턴스
calculator = get_token_calculator()
```

#### 모드별 전처리

**NAI**: `"1.55::artist:chihiro::"` → `"artist:chihiro"` (가중치 구문 제거, `artist:` = 2 토큰)

**WEBUI/COMFYUI**: `"(1girl:1.2), \\(text\\)"` → `"1girl, __ESCAPED_PAREN_TOKEN__ text __ESCAPED_PAREN_TOKEN__"` (escaped paren pair = 1 토큰)

#### CLIP 보정 계수

```python
CLIP_CORRECTION_FACTORS = {"NAI": 1.12, "WEBUI": 0.99, "COMFYUI": 0.99}
PATTERN_CORRECTIONS = {
    'parentheses': 0.02, 'underscores': 0.01, 'numbers': 0.02,
    'punctuation': 0.01, 'lora_tags': 0.03
}
```

---

## 번역 유틸리티 (`translator.py`)

### korean_to_english

```python
from utils.translator import korean_to_english
result = korean_to_english("웃는 소녀")  # "smiling girl" (소문자)
```

**번역 전략**: 1차 googletrans → 2차 Google Translate API 직접 호출 (fallback)

**특징**: 반환값 항상 소문자, 5초 타임아웃, 예외 시 None 반환

**제한**: 인터넷 필요, Google Translate 의존, 단일 API 호출만 지원

---

## 생성 파라미터 관리 (`load_generation_params.py`)

### GenerationParamsManager

메인 윈도우의 50+ 생성 파라미터를 모드별(NAI/WEBUI/COMFYUI)로 저장/로드.

#### 주요 메서드

| 메서드 | 설명 |
|--------|------|
| `collect_current_settings()` | UI에서 모든 파라미터 수집 → Dict |
| `apply_settings(settings)` | Dict를 UI에 적용 |
| `save_mode_settings(mode)` | `save/generation_params_{MODE}.json` 저장 |
| `load_mode_settings(mode)` | 파일 로드 → UI 업데이트 → 설정 적용 (실패 시 기본값) |
| `on_mode_changed(old, new)` | 이전 모드 저장 → 새 모드 로드 → UI 전환 |

#### 동적 옵션 로드

**WEBUI**: `/sdapi/v1/sd-models`, `/sdapi/v1/samplers`, `/sdapi/v1/schedulers`, `/sdapi/v1/upscalers`
**ComfyUI**: `/object_info`, `/system_stats`

#### UI 모드 전환

- NAI: NAID Option 표시, Hires 숨김, 고정 모델/샘플러/스케줄러 복원
- WEBUI: Hires Option 표시, NAID 숨김
- ComfyUI: ComfyUI Option 표시, NAI/WEBUI 숨김

#### 주의사항

- 콤보박스 설정 시 `findText()` 후 인덱스가 있는 경우에만 설정
- 슬라이더 값 변환 주의 (0-100 → 0.0-1.0 등)
- 새 파라미터 추가 시: `collect_current_settings()` + `apply_settings()` + `_get_default_settings()` 모두 수정

---

## Cloudflared 터널 관리 (`cloudflared.py`)

pycloudflared 대체 경량 구현. 바이너리 자동 다운로드 + Quick Tunnel 시작/종료.

#### 주요 함수

```python
from utils.cloudflared import start_tunnel, stop_tunnel, stop_all, remove_binary

# 터널 시작 (바이너리 없으면 자동 다운로드)
info = start_tunnel(port=7243, on_progress=print, timeout=30.0)
print(info.tunnel_url)   # https://xxx.trycloudflare.com
print(info.metrics_url)  # http://127.0.0.1:xxxxx/metrics

# 터널 종료
stop_tunnel(7243)

# 바이너리 삭제
remove_binary()
```

#### 멀티플랫폼 지원

Windows (amd64/x86), Linux (x86_64/i386/arm/arm64/aarch64), macOS (x86_64/arm64).
macOS는 tgz 아카이브 — `tarfile`로 바이너리만 추출.

#### 바이너리 저장 위치

`utils/.cloudflared_bin/` — `.gitignore`에 추가 권장.

#### 설계 결정

- **readline 타임아웃**: daemon Thread + `Event.wait(timeout)` — `ThreadPoolExecutor` 대비 thread leak 방지
- **atexit 관리**: 클로저 참조를 `_atexit_handlers` dict에 보관하여 동일 객체로 unregister 가능
- **전체 타임아웃**: 30초 deadline, 라인별 5초 타임아웃. 프로세스 종료 감지 포함

#### 주의사항

- 네트워크 필요 (바이너리 다운로드 + Cloudflare 터널)
- `start_tunnel()`은 블로킹 — 호출부에서 별도 스레드 사용 필수
- `_running` dict로 포트별 중복 시작 방지 (동일 포트 재호출 시 기존 info 반환)

---

## 다른 디렉터리와의 관계

| 디렉터리 | 관계 |
|----------|------|
| `modules/`, `tabs/` | token_calculator, image_info, translator, cloudflared 호출 |
| `core/` | load_generation_params (MainWindow 통합) |
| `interfaces/`, `ui/` | 독립 (utils는 이들에 의존하지 않음) |
