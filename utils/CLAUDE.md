# CLAUDE.md — utils/

> 순수 유틸리티 모듈 컬렉션. UI/컨트롤러에 의존하지 않는 독립적 기능을 제공합니다.

---

## 구조 및 원칙

```
utils/
  ├── image_info.py                    → 이미지 메타데이터 추출 (NAI/WebUI/ComfyUI)
  ├── token_calculator.py              → 프롬프트 토큰 계산 (CLIP 근사)
  ├── translator.py                    → 한글 → 영어 번역
  ├── load_generation_params.py        → 생성 파라미터 모드별 저장/로드
  ├── cloudflared.py                   → Cloudflared 터널 관리 (바이너리 다운로드 + Quick Tunnel)
  ├── character_asset_storage.py       → 캐릭터 에셋 이미지 저장/로드
  └── reference_inpaint_preprocess.py  → 레퍼런스 인셋 인페인트 캔버스/마스크 생성
```

**설계 원칙**:
- UI/컨트롤러에 의존하지 않음 (독립성, 재사용성)
- 전역 싱글톤 지양, 팩토리 패턴 또는 모듈 수준 함수 선호
- 예외 안전: 모든 유틸리티가 예외를 catch하고 None 또는 빈 값 반환
- 대형 연산은 호출부에서 스레딩/취소 제어

---

## 이미지 메타데이터 추출 (`image_info.py`)

### ImageMetadataExtractor

**지원 포맷**: NovelAI (Comment/Stealth PNG), WebUI (parameters/EXIF), ComfyUI (prompt API / workflow UI JSON), 일반 JSON

#### 주요 메서드

| 메서드 | 반환 | 설명 |
|--------|------|------|
| `has_metadata(image_path)` | `bool` | 메타데이터 존재 확인 (Comment → parameters → ComfyUI `prompt`/`workflow` → EXIF → Stealth 순) |
| `extract_metadata(image_path)` | `Optional[Dict]` | 메타데이터 추출 |
| `detect_software(metadata)` | `str` | `'nai'` / `'webui'` / `'comfyui'` / `'unknown'` |

#### 반환 구조

**NovelAI**: `{'type': 'nai', 'prompt': ..., 'uc': ..., 'parameters': {steps, scale, seed, sampler, ...}, 'characters': [...], 'characters_uc': [...]}`

**WebUI**: `{'type': 'webui', 'prompt': ..., 'negative': ..., 'parameters': {steps, sampler, cfg_scale, seed, size, model, ...}}`

**ComfyUI**: `{'type': 'comfyui', 'prompt': ..., 'negative': ..., 'parameters': {steps, seed, cfg_scale, sampler, scheduler, denoising_strength, width, height, batch_size, model, clip_model, vae, cfg_rescale, sampling_mode, workflow_type, ...}, 'prompt_api': {...}, 'workflow': {...}, 'workflow_nodes': int}`

#### ComfyUI 파서 동작

두 저장 포맷 지원:
- **prompt API 형식**: `{node_id: {class_type, inputs}}` — PNG `prompt` chunk에 저장
- **workflow UI 형식**: `{nodes: [...], links: [...]}` — PNG `workflow` chunk에 저장. 내부적으로 `links`와 `widgets_values`를 prompt API 모양으로 변환

메인 샘플러 탐색: `PreviewImage`/`SaveImage` → `VAEDecode` → `KSampler`/`SamplerCustom` 역추적. 실패 시 node id 오름차순 첫 샘플러 사용.

업스트림 BFS(`_find_upstream_node`)로 로더 체인 추적: `CheckpointLoaderSimple` / `UNETLoader` / `CLIPLoader` / `VAELoader` / `RescaleCFG` / `ModelSamplingDiscrete`. 커스텀 노드/비표준 토폴로지는 누락될 수 있음.

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

## 캐릭터 에셋 스토리지 (`character_asset_storage.py`)

### 저장 레이아웃

```
save/character_asset/
  ├── images/{sha256[:16]}.png    ← 유일한 영속 파일
  └── metadata/                    ← 레거시 (신규 저장은 사용하지 않음)
```

메타데이터 sidecar JSON은 더 이상 쓰지 않습니다. 캐릭터 프롬프트/UC는 저장된 PNG의 **NAI Comment**를 `ImageMetadataExtractor`로 런타임 복구합니다.

### 주요 함수

| 함수 | 설명 |
|------|------|
| `save_character_asset(raw_bytes=..., image=...)` | SHA-256 prefix로 파일명 생성, raw_bytes 우선 저장 |
| `build_character_asset_metadata(file_hash, file_name, extracted_metadata, ...)` | 저장/복원 시 통일된 메타데이터 dict 구성 |
| `load_character_asset_metadata(file_hash, image_path)` | 디스크 이미지에서 Comment 재추출 → metadata dict |
| `ensure_character_asset_storage_dirs()` | 저장 폴더 생성 |

### ⚠️ raw_bytes 계약

`save_character_asset`은 가능한 한 `raw_bytes`로 저장합니다. `image`만 넘기면 PIL 재인코딩되어 **NAI Comment가 사라지고** 이후 복원 시 `character_prompt`가 공백이 됩니다. 호출부(예: `CharacterAssetGenerationWindow._save_selected_asset`)는 `result.get("raw_bytes") or result.get("image_bytes")`를 우선 전달해야 합니다.

---

## 레퍼런스 인페인트 전처리 (`reference_inpaint_preprocess.py`)

NovelAI 공식 문서 기반 "레퍼런스 인셋" 인페인트 캔버스 생성기.

### 데이터클래스

| 클래스 | 용도 |
|--------|------|
| `ReferenceGenerationSpec` | 초기 레퍼런스 생성용 프롬프트 스캐폴드 (기본 768x1344, `1girl, solo, 1koma, ...`) |
| `ReferenceInsetPreprocessSpec` | 캔버스 레이아웃/마스크 규칙 (1152x896, 16px bleed, 8px seam overlap) |
| `ReferenceInsetPreprocessResult` | 결과 이미지 + 마스크 + 추천 파라미터 |
| `PlacementBox` | 캔버스 위 레퍼런스 배치 좌표 |

### 주요 함수

```python
from utils.reference_inpaint_preprocess import (
    ReferenceGenerationSpec,
    prepare_reference_inpaint_canvas,
)

# 1) 초기 레퍼런스 생성용 프롬프트
prompt = ReferenceGenerationSpec().build_prompt()

# 2) 생성된 레퍼런스 이미지를 캔버스에 배치 + 마스크 생성
result = prepare_reference_inpaint_canvas(pil_image)
# result.canvas_image, result.full_mask_image, result.small_mask_image
# result.recommended_strength == 1.0, result.recommended_noise == 0.0
```

### 마스크 규칙

- 레퍼런스 영역은 preserve(0), 외곽은 editable(255)
- 오른쪽 seam에 `seam_overlap_px=8` editable 스트립 재개방 → 경계 블렌딩
- 상하단 seam 코너에 `seam_corner_wrap_px=20` 타원형 editable lobe
- 최종 마스크는 NAI용 1/8 축소 버전도 함께 반환 (`mask_downscale=8`)

### strength/noise 권장값

`recommended_strength=1.0`, `recommended_noise=0.0`.
- NovelAI 레퍼런스 인페인트 가이드: strength=1 유지 권장
- NovelAI 인페인트 UI는 noise 슬라이더 미노출 → 엔지니어링 기본값 0
- Img2ImgPanel Comic Panel 모드의 강제 1.0/0.0 동작과 정합

---

## 다른 디렉터리와의 관계

| 디렉터리 | 관계 |
|----------|------|
| `modules/`, `tabs/` | token_calculator, image_info, translator, cloudflared 호출 |
| `core/` | load_generation_params (MainWindow 통합) |
| `ui/` | character_asset_storage, reference_inpaint_preprocess 호출 (에셋 생성/스토리지 창, `NAIA_cold_v4.apply_character_asset_reference_from_image`) |
| `interfaces/` | 독립 |

**예외**: `character_asset_storage.py`는 `utils/image_info.py`의 `ImageMetadataExtractor`에 의존합니다 (원래 utils 내부는 독립이지만, 이 파일은 utils 내 조합만 사용). UI/컨트롤러 비의존 원칙은 유지됩니다.
