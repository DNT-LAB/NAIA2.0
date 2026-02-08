# CLAUDE.md — utils/

> **목적**: 순수 유틸리티 모듈 컬렉션. UI/컨트롤러에 의존하지 않는 독립적 기능을 제공합니다. 테스트 용이성과 재사용성이 최우선입니다.

---

## 목차

1. [개요](#개요)
2. [주요 파일 및 역할](#주요-파일-및-역할)
3. [이미지 메타데이터 추출](#이미지-메타데이터-추출)
4. [토큰 계산](#토큰-계산)
5. [번역 유틸리티](#번역-유틸리티)
6. [생성 파라미터 관리](#생성-파라미터-관리)
7. [실전 예제](#실전-예제)
8. [문제 해결](#문제-해결)
9. [체크리스트](#체크리스트)
10. [참고 자료](#참고-자료)
11. [요약](#요약)

---

## 개요

### utils/ 디렉터리의 역할

utils/는 NAIA 2.0의 **유틸리티 계층**입니다:

- 🔧 **독립성**: UI나 컨트롤러에 의존하지 않음
- ♻️ **재사용성**: 다양한 컴포넌트에서 사용 가능
- 🧪 **테스트 용이성**: 순수 함수/가벼운 클래스 구조
- 📦 **단일 책임**: 각 유틸리티는 하나의 명확한 기능만 제공

### 아키텍처

```
utils/
  ├── image_info.py           → 이미지 메타데이터 추출
  ├── token_calculator.py     → 프롬프트 토큰 계산
  ├── translator.py           → 한글 → 영어 번역
  └── load_generation_params.py → 생성 파라미터 저장/로드
```

**특징**:
- 전역 싱글톤 지양 (팩토리 패턴 또는 모듈 수준 함수 선호)
- 상태 최소화 (불변성 선호)
- 대형 연산은 호출부에서 제어 (스레딩/취소)
- 예외 안전 (None 반환 또는 빈 값 반환)

### 다른 디렉터리와의 관계

| 디렉터리 | 관계 | 설명 |
|----------|------|------|
| **modules/** | 사용 | token_calculator, image_info 호출 |
| **tabs/** | 사용 | image_info, translator 호출 |
| **core/** | 사용 | load_generation_params (메인 윈도우 통합) |
| **interfaces/** | 독립 | utils는 계약에 의존하지 않음 |
| **ui/** | 독립 | UI 위젯을 직접 조작하지 않음 |

### 언제 utils/를 수정/추가하는가?

| 작업 | 파일 |
|------|------|
| **메타데이터 파싱 추가** | `utils/image_info.py` 확장 |
| **토큰 계산 로직 수정** | `utils/token_calculator.py` 수정 |
| **번역 엔진 변경** | `utils/translator.py` 수정 |
| **파라미터 저장 로직 수정** | `utils/load_generation_params.py` 수정 |
| **새 유틸리티 추가** | 새 파일 생성 (`utils/new_utility.py`) |

---

## 주요 파일 및 역할

### utils/ 파일 목록

| 파일 | 크기 | 역할 | 주요 클래스/함수 |
|------|------|------|-----------------|
| **image_info.py** | 18K | AI 생성 이미지 메타데이터 추출 | `ImageMetadataExtractor` |
| **token_calculator.py** | 14K | 프롬프트 토큰 계산 (CLIP 근사) | `TokenCalculator`, `count_tokens()` |
| **translator.py** | 2.9K | 한글 → 영어 번역 | `korean_to_english()` |
| **load_generation_params.py** | 35K | 메인 생성 파라미터 모드별 저장/로드 | `GenerationParamsManager` |

---

## 이미지 메타데이터 추출

### ImageMetadataExtractor 클래스

**파일**: `utils/image_info.py:20-460`

**목적**: AI 생성 이미지에서 프롬프트, 파라미터 등의 메타데이터를 추출합니다.

#### 지원 포맷

1. **NovelAI**:
   - Comment 필드 (PNG tEXt chunk)
   - JSON 형식 또는 NAI 텍스트 형식
   - Stealth PNG (알파 채널 숨김 데이터)

2. **Stable Diffusion WebUI**:
   - parameters 필드 (PNG tEXt chunk)
   - EXIF UserComment (JPEG/PNG)
   - GIF comment field

3. **기타**:
   - 일반 JSON 메타데이터
   - Custom Comment 필드

### 주요 메서드

#### has_metadata(image_path) → bool

**파일**: `image_info.py:23-62`

**목적**: 이미지에 메타데이터가 있는지 확인

```python
from utils.image_info import ImageMetadataExtractor
from pathlib import Path

image_path = Path("output/example.png")

if ImageMetadataExtractor.has_metadata(image_path):
    print("✅ 메타데이터 있음")
else:
    print("❌ 메타데이터 없음")
```

**체크 순서**:
1. Comment 필드 확인
2. parameters 필드 확인
3. EXIF 데이터 확인
4. Stealth PNG 확인 (RGBA 이미지만)

#### extract_metadata(image_path) → Optional[Dict[str, Any]]

**파일**: `image_info.py:64-120`

**목적**: 이미지에서 메타데이터 추출

```python
from utils.image_info import ImageMetadataExtractor

metadata = ImageMetadataExtractor.extract_metadata("output/example.png")

if metadata:
    print(f"타입: {metadata.get('type')}")
    print(f"프롬프트: {metadata.get('prompt')}")
    print(f"Negative: {metadata.get('negative') or metadata.get('uc')}")
    print(f"파라미터: {metadata.get('parameters')}")
```

**반환 구조 (NovelAI)**:
```python
{
    'type': 'nai',
    'prompt': '1girl, smile, blue eyes',
    'uc': 'nsfw, lowres',
    'parameters': {
        'steps': 28,
        'scale': 5.0,
        'uncond_scale': 1.0,
        'cfg_rescale': 0.0,
        'seed': 1234567890,
        'sampler': 'k_euler_ancestral',
        'sm': True,
        'sm_dyn': False,
        'noise_schedule': 'native'
    },
    'characters': ['1girl, long hair, blue eyes'],
    'characters_uc': []
}
```

**반환 구조 (WebUI)**:
```python
{
    'type': 'webui',
    'prompt': '1girl, smile, blue eyes',
    'negative': 'nsfw, lowres',
    'parameters': {
        'steps': 20,
        'sampler': 'Euler a',
        'cfg_scale': 7.0,
        'seed': 1234567890,
        'size': '512x768',
        'model_hash': 'abc123',
        'model': 'SD 1.5'
    }
}
```

#### detect_software(metadata) → str

**파일**: `image_info.py:442-459`

**목적**: 메타데이터에서 소프트웨어 타입 감지

```python
software = ImageMetadataExtractor.detect_software(metadata)
# 반환값: 'nai', 'webui', 'unknown'

if software == 'nai':
    print("NovelAI 이미지")
elif software == 'webui':
    print("Stable Diffusion WebUI 이미지")
```

### Stealth PNG 지원

**파일**: `image_info.py:332-412`

Stealth PNG는 **알파 채널의 LSB(Least Significant Bit)**에 메타데이터를 숨기는 방식입니다.

**작동 원리**:
1. 시그니처 확인 ('stealth_pngcomp', 120 bits)
2. 데이터 길이 읽기 (32 bits)
3. 바이너리 데이터 읽기
4. gzip 압축 해제
5. UTF-8 디코딩

**지원 조건**:
- RGBA 이미지만 (RGB는 불가)
- 시그니처가 정확해야 함
- gzip으로 압축된 데이터

### 주의사항

**파일 크기**:
- EXIF 데이터가 큰 파일은 메모리 많이 사용
- 이미지 자체를 로드하므로 큰 이미지(4K+)는 느릴 수 있음

**Unicode 안전성**:
- 모든 텍스트 디코딩에 `errors='ignore'` 사용
- 손상된 메타데이터도 부분적으로 읽기 시도

**예외 처리**:
- 모든 메서드가 예외를 catch하고 None 또는 False 반환
- 호출부에서 추가 예외 처리 불필요

---

## 토큰 계산

### TokenCalculator 클래스

**파일**: `utils/token_calculator.py:11-321`

**목적**: 프롬프트의 토큰 수를 계산하여 CLIP 토크나이저 동작을 근사합니다.

#### 동작 원리

1. **GPT-2 인코딩**: tiktoken을 사용한 토큰 카운트
2. **모드별 전처리**: NAI/WEBUI/COMFYUI 가중치 구문 처리
3. **CLIP 근사 보정**: 모드별 보정 계수 적용
4. **패턴 보정**: 괄호, 언더스코어, 숫자, LoRA 태그 등

### 주요 메서드

#### count_tokens(text, use_clip_approximation=True, current_mode="NAI") → int

**파일**: `token_calculator.py:215-280`

**목적**: 텍스트의 토큰 수 계산

```python
from utils.token_calculator import count_tokens

# NAI 모드
nai_tokens = count_tokens("1girl, smile, 0.8::artist:某个作者::", current_mode="NAI")
print(f"NAI 토큰 수: {nai_tokens}")  # NAI weight syntax 제거 후 계산

# WEBUI 모드
webui_tokens = count_tokens("(1girl:1.2), smile, \\(escaped\\)", current_mode="WEBUI")
print(f"WEBUI 토큰 수: {webui_tokens}")  # 괄호 가중치 제거, escaped paren = 1 token
```

**모드별 전처리**:

**NAI 모드**:
```python
# 입력: "1.55::artist:chihiro::"
# 전처리 후: "artist:chihiro"
# ⚠️ artist: 는 2 토큰 추가
```

**WEBUI/COMFYUI 모드**:
```python
# 입력: "(1girl:1.2), smile, \\(text\\)"
# 전처리 후: "1girl, smile, __ESCAPED_PAREN_TOKEN__ text __ESCAPED_PAREN_TOKEN__"
# ⚠️ escaped paren pair = 1 token 추가
```

#### count_prompt_tokens(main_prompt, character_prompt=None, current_mode="NAI") → Dict

**파일**: `token_calculator.py:282-304`

**목적**: 메인 프롬프트 + 캐릭터 프롬프트 토큰 계산

```python
from utils.token_calculator import count_prompt_tokens

result = count_prompt_tokens(
    main_prompt="1girl, smile, blue eyes",
    character_prompt="long hair, school uniform",
    current_mode="NAI"
)

print(f"메인: {result['main']} 토큰")
print(f"캐릭터: {result['character']} 토큰")
print(f"전체: {result['total']} 토큰")
```

**반환 구조**:
```python
{
    'main': 15,
    'character': 8,
    'total': 23
}
```

#### format_token_label(token_counts, mode="NAI") → str

**파일**: `token_calculator.py:306-320`

**목적**: UI 레이블 형식으로 포맷

```python
from utils.token_calculator import format_token_label

label_text = format_token_label(
    {'main': 15, 'character': 8, 'total': 23},
    mode="NAI"
)
print(label_text)
# "Estimated Tokens : 23 (Main 15 + Character 8)"
```

### CLIP 보정 계수

**파일**: `token_calculator.py:19-32`

```python
CLIP_CORRECTION_FACTORS = {
    "NAI": 1.12,      # GPT-2 대비 12% 더 많이 토큰화
    "WEBUI": 0.99,    # GPT-2 대비 거의 동일
    "COMFYUI": 0.99,  # GPT-2 대비 거의 동일
}

PATTERN_CORRECTIONS = {
    'parentheses': 0.02,   # 괄호 많으면 +2%
    'underscores': 0.01,   # 언더스코어 많으면 +1%
    'numbers': 0.02,       # 숫자 많으면 +2%
    'punctuation': 0.01,   # 구두점 많으면 +1%
    'lora_tags': 0.03,     # <lora:...> 태그 +3%
}
```

### 글로벌 편의 함수

**파일**: `token_calculator.py:326-381`

```python
# 싱글톤 팩토리
from utils.token_calculator import get_token_calculator

calculator = get_token_calculator()  # 전역 인스턴스

# 편의 함수
from utils.token_calculator import count_tokens, count_prompt_tokens, format_token_label

tokens = count_tokens("1girl, smile", current_mode="NAI")
```

---

## 번역 유틸리티

### korean_to_english 함수

**파일**: `utils/translator.py:20-81`

**목적**: 한글을 영어로 번역

#### 사용법

```python
from utils.translator import korean_to_english

korean_text = "웃는 소녀"
english_text = korean_to_english(korean_text)

if english_text:
    print(f"번역 결과: {english_text}")  # "smiling girl"
else:
    print("번역 실패")
```

#### 번역 전략

**1차 시도**: googletrans 라이브러리

```python
from googletrans import Translator as GoogleTranslator

translator = GoogleTranslator()
result = translator.translate(text, src='ko', dest='en')
```

**2차 시도 (Fallback)**: Google Translate API 직접 호출

```python
import requests

base_url = "https://translate.googleapis.com/translate_a/single"
params = {
    'client': 'gtx',
    'sl': 'ko',
    'tl': 'en',
    'dt': 't',
    'q': text
}
response = requests.get(base_url, params=params, headers=headers, timeout=5)
```

#### 특징

- **소문자 변환**: 반환값은 항상 소문자 (`.lower()`)
- **경고 억제**: googletrans의 비동기 관련 경고 필터링
- **타임아웃**: requests는 5초 타임아웃
- **안전성**: 모든 예외를 catch하고 None 반환

#### 제한사항

- 인터넷 연결 필요
- Google Translate API 의존 (외부 서비스)
- 긴 텍스트는 여러 번 호출 필요 (단일 API 호출만 지원)
- 번역 품질 보장 없음 (Google Translate에 의존)

---

## 생성 파라미터 관리

### GenerationParamsManager 클래스

**파일**: `utils/load_generation_params.py:8-962`

**목적**: 메인 윈도우의 생성 파라미터를 모드별로 저장/로드합니다.

#### 주요 책임

1. **파라미터 수집**: 메인 윈도우 UI에서 모든 생성 설정 수집
2. **파라미터 적용**: 저장된 설정을 UI에 복원
3. **모드별 저장**: NAI/WEBUI/COMFYUI별 별도 파일
4. **동적 옵션 로드**: API에서 모델/샘플러/스케줄러 목록 가져오기
5. **UI 전환**: 모드별 UI 표시/숨김 제어

### 주요 메서드

#### collect_current_settings() → Dict[str, Any]

**파일**: `load_generation_params.py:24-233`

**목적**: 현재 UI 상태에서 모든 파라미터 수집

```python
from utils.load_generation_params import GenerationParamsManager

manager = GenerationParamsManager(main_window)
settings = manager.collect_current_settings()

print(f"프롬프트: {settings['input']}")
print(f"모델: {settings['model']}")
print(f"Steps: {settings['steps']}")
print(f"CFG Scale: {settings['cfg_scale']}")
```

**수집 항목** (50+ 파라미터):
- 프롬프트 (main, negative)
- 모델, 샘플러, 스케줄러
- 해상도 (width, height)
- 생성 파라미터 (steps, cfg_scale, cfg_rescale, seed)
- NAI 옵션 (SMEA, DYN, VAR+, DECRISP)
- WEBUI 옵션 (enable_hr, hr_scale, hr_upscaler, denoising_strength)
- ComfyUI 옵션 (v_prediction, zsnr)
- 체크박스들 (프롬프트 고정, 자동 생성, 터보 옵션, etc.)

#### apply_settings(settings: Dict[str, Any])

**파일**: `load_generation_params.py:303-442`

**목적**: 저장된 설정을 UI에 적용

```python
manager.apply_settings(loaded_settings)
```

**적용 과정**:
1. 텍스트 필드 설정 (프롬프트, negative)
2. 콤보박스 설정 (모델, 샘플러, 스케줄러) - 목록에 있는 항목만
3. 슬라이더 설정 (CFG Scale, CFG Rescale) - 값 변환 적용
4. 스핀박스 설정 (Steps, HR Scale)
5. 체크박스 설정 (모든 옵션)

**주의**: 콤보박스는 `findText()` 후 인덱스가 있는 경우에만 설정

#### save_mode_settings(mode: str)

**파일**: `load_generation_params.py:444-463`

**목적**: 현재 모드 설정을 파일에 저장

```python
manager.save_mode_settings("NAI")
# save/generation_params_NAI.json 생성
```

#### load_mode_settings(mode: str)

**파일**: `load_generation_params.py:465-531`

**목적**: 지정 모드 설정을 파일에서 로드

```python
manager.load_mode_settings("NAI")
# save/generation_params_NAI.json 읽기
```

**로드 순서**:
1. 파일 존재 확인
2. 모드별 UI 업데이트 (동적 옵션 로드 포함)
3. 설정 적용
4. 실패 시 기본값 적용

#### on_mode_changed(old_mode: str, new_mode: str)

**파일**: `load_generation_params.py:543-565`

**목적**: API 모드 변경 시 호출되는 콜백

```python
# AppContext 이벤트에 연결
app_context.subscribe("api_mode_changed", manager.on_mode_changed)
```

**동작**:
1. 이전 모드 설정 저장 (호환되는 경우)
2. 새 모드 설정 로드
3. UI 전환

### 동적 옵션 로드

#### load_webui_dynamic_options()

**파일**: `load_generation_params.py:567-679`

**목적**: WEBUI API에서 동적 옵션 로드

```python
manager.load_webui_dynamic_options()
```

**로드 항목**:
1. 모델 목록 (`/sdapi/v1/sd-models`)
2. 현재 모델 (`/sdapi/v1/options`)
3. 샘플러 목록 (`/sdapi/v1/samplers`)
4. 스케줄러 목록 (`/sdapi/v1/schedulers`)
5. 업스케일러 목록 (`/sdapi/v1/upscalers`)

**복원 전략**:
- API 현재 모델 우선
- 이전 선택값 복원 시도
- 기본값 폴백

#### load_comfyui_dynamic_options()

**파일**: `load_generation_params.py:681-782`

**목적**: ComfyUI API에서 동적 옵션 로드

**로드 항목**:
1. 모델 목록 (`/object_info`)
2. 샘플러 목록
3. 스케줄러 목록
4. 시스템 정보 (`/system_stats`)

### UI 모드 전환

#### update_ui_for_nai_mode()

**파일**: `load_generation_params.py:814-857, 885-962`

**동작**:
- Hires Option 영역 숨기기
- NAID Option 영역 표시
- NAI 고정 옵션 복원 (모델, 샘플러, 스케줄러)

#### update_ui_for_webui_mode()

**파일**: `load_generation_params.py:858-883`

**동작**:
- NAID Option 영역 숨기기
- Hires Option 영역 표시

#### update_ui_for_comfyui_mode()

**파일**: `load_generation_params.py:784-812`

**동작**:
- NAI/WEBUI Option 영역 숨기기
- ComfyUI Option 영역 표시

---

## 실전 예제

### 예제 1: 이미지 메타데이터 추출 (5분)

**목표**: 이미지에서 프롬프트 추출

```python
from utils.image_info import ImageMetadataExtractor
from pathlib import Path

def extract_prompt_from_image(image_path: Path):
    """이미지에서 프롬프트 추출"""

    # 메타데이터 존재 확인
    if not ImageMetadataExtractor.has_metadata(image_path):
        print(f"❌ {image_path.name}: 메타데이터 없음")
        return None

    # 메타데이터 추출
    metadata = ImageMetadataExtractor.extract_metadata(image_path)
    if not metadata:
        print(f"❌ {image_path.name}: 추출 실패")
        return None

    # 소프트웨어 감지
    software = ImageMetadataExtractor.detect_software(metadata)
    print(f"✅ {image_path.name}: {software} 이미지")

    # 프롬프트 추출
    prompt = metadata.get('prompt', '')
    negative = metadata.get('negative') or metadata.get('uc', '')

    return {
        'software': software,
        'prompt': prompt,
        'negative': negative,
        'parameters': metadata.get('parameters', {})
    }

# 사용
image_path = Path("output/generated_image.png")
result = extract_prompt_from_image(image_path)

if result:
    print(f"프롬프트: {result['prompt']}")
    print(f"Negative: {result['negative']}")
```

### 예제 2: 토큰 계산 및 표시 (10분)

**목표**: 프롬프트 입력 시 실시간 토큰 카운트

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QLabel
from PyQt6.QtCore import pyqtSignal
from utils.token_calculator import count_prompt_tokens, format_token_label

class TokenCounterWidget(QWidget):
    """토큰 카운터 위젯"""

    def __init__(self, current_mode="NAI"):
        super().__init__()
        self.current_mode = current_mode
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 메인 프롬프트
        self.main_prompt = QTextEdit()
        self.main_prompt.setPlaceholderText("메인 프롬프트")
        self.main_prompt.textChanged.connect(self.update_token_count)

        # 캐릭터 프롬프트 (NAI 전용)
        self.char_prompt = QTextEdit()
        self.char_prompt.setPlaceholderText("캐릭터 프롬프트 (NAI 전용)")
        self.char_prompt.textChanged.connect(self.update_token_count)

        # 토큰 카운트 레이블
        self.token_label = QLabel("Estimated Tokens : 0")

        layout.addWidget(self.main_prompt)
        layout.addWidget(self.char_prompt)
        layout.addWidget(self.token_label)

    def update_token_count(self):
        """토큰 카운트 업데이트"""
        main_text = self.main_prompt.toPlainText()
        char_text = self.char_prompt.toPlainText()

        # 토큰 계산
        token_counts = count_prompt_tokens(
            main_prompt=main_text,
            character_prompt=char_text if char_text else None,
            current_mode=self.current_mode
        )

        # 레이블 포맷
        label_text = format_token_label(token_counts, mode=self.current_mode)
        self.token_label.setText(label_text)

    def set_mode(self, mode: str):
        """모드 변경 시 호출"""
        self.current_mode = mode

        # 캐릭터 프롬프트 가시성 (NAI 전용)
        self.char_prompt.setVisible(mode == "NAI")

        # 토큰 재계산
        self.update_token_count()
```

### 예제 3: 한글 프롬프트 자동 번역 (15분)

**목표**: 한글 입력 시 자동으로 영어로 번역

```python
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton
from PyQt6.QtCore import QThread, pyqtSignal
from utils.translator import korean_to_english

class TranslationWorker(QThread):
    """번역 워커 스레드"""
    translation_finished = pyqtSignal(str)

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        """스레드 실행"""
        result = korean_to_english(self.text)
        if result:
            self.translation_finished.emit(result)

class KoreanPromptWidget(QWidget):
    """한글 프롬프트 번역 위젯"""

    def __init__(self):
        super().__init__()
        self.worker = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 한글 입력
        self.korean_input = QTextEdit()
        self.korean_input.setPlaceholderText("한글 입력 (예: 웃는 소녀)")

        # 번역 버튼
        self.translate_btn = QPushButton("번역")
        self.translate_btn.clicked.connect(self.translate)

        # 영어 결과
        self.english_output = QTextEdit()
        self.english_output.setPlaceholderText("번역 결과")
        self.english_output.setReadOnly(True)

        layout.addWidget(self.korean_input)
        layout.addWidget(self.translate_btn)
        layout.addWidget(self.english_output)

    def translate(self):
        """번역 시작"""
        korean_text = self.korean_input.toPlainText()
        if not korean_text.strip():
            return

        # 워커 스레드 생성
        self.worker = TranslationWorker(korean_text)
        self.worker.translation_finished.connect(self._on_translation_finished)

        # UI 업데이트
        self.translate_btn.setEnabled(False)
        self.english_output.setPlainText("번역 중...")

        # 워커 시작
        self.worker.start()

    def _on_translation_finished(self, result):
        """번역 완료"""
        self.english_output.setPlainText(result)
        self.translate_btn.setEnabled(True)
```

### 예제 4: 모드별 파라미터 저장/로드 통합 (30분)

**목표**: 메인 윈도우에 GenerationParamsManager 통합

```python
from PyQt6.QtWidgets import QMainWindow
from utils.load_generation_params import GenerationParamsManager
from core.context import AppContext

class MainWindow(QMainWindow):
    def __init__(self, app_context: AppContext):
        super().__init__()
        self.app_context = app_context

        # GenerationParamsManager 초기화
        self.params_manager = GenerationParamsManager(self)

        # 모드 변경 이벤트 구독
        self.app_context.subscribe("api_mode_changed", self._on_mode_changed)

        # UI 초기화
        self.init_ui()

        # 초기 모드 설정 로드
        current_mode = self.app_context.get_api_mode()
        self.params_manager.load_mode_settings(current_mode)

    def _on_mode_changed(self, data: dict):
        """모드 변경 시 호출"""
        old_mode = data['old_mode']
        new_mode = data['new_mode']

        # GenerationParamsManager에 위임
        self.params_manager.on_mode_changed(old_mode, new_mode)

    def closeEvent(self, event):
        """앱 종료 시 현재 모드 설정 저장"""
        current_mode = self.app_context.get_api_mode()
        self.params_manager.save_mode_settings(current_mode)

        event.accept()
```

---

## 문제 해결

### Q1: 이미지 메타데이터가 추출되지 않음

**증상**: `extract_metadata()`가 None 반환

**원인**:
1. 메타데이터가 실제로 없음
2. 손상된 메타데이터
3. 지원하지 않는 포맷

**해결**:

```python
# 1. has_metadata()로 먼저 확인
if not ImageMetadataExtractor.has_metadata(image_path):
    print("메타데이터 없음")

# 2. 디버깅 모드 활성화 (콘솔 출력 확인)
metadata = ImageMetadataExtractor.extract_metadata(image_path)
# 콘솔에 상세 로그 출력됨

# 3. PIL Image 객체로 직접 확인
from PIL import Image
img = Image.open(image_path)
print(f"Image info keys: {list(img.info.keys())}")
print(f"Image mode: {img.mode}")
```

### Q2: 토큰 카운트가 부정확함

**증상**: CLIP과 비교 시 토큰 수가 다름

**원인**:
1. CLIP은 버전별로 다름 (OpenCLIP, NovelAI CLIP 등)
2. 보정 계수가 특정 프롬프트에 맞지 않음

**해결**:

```python
# 1. 보정 없이 GPT-2 카운트만 확인
from utils.token_calculator import get_token_calculator

calculator = get_token_calculator()
raw_tokens = calculator.count_tokens(text, use_clip_approximation=False)
print(f"GPT-2 토큰: {raw_tokens}")

# 2. 보정 계수 조정 (필요 시)
# token_calculator.py의 CLIP_CORRECTION_FACTORS 수정

# 3. 모드 확인
tokens_nai = calculator.count_tokens(text, current_mode="NAI")
tokens_webui = calculator.count_tokens(text, current_mode="WEBUI")
print(f"NAI: {tokens_nai}, WEBUI: {tokens_webui}")
```

### Q3: 번역이 실패함

**증상**: `korean_to_english()`가 None 반환

**원인**:
1. 인터넷 연결 없음
2. Google Translate API 차단
3. 잘못된 입력 (영어만 있는 경우)

**해결**:

```python
# 1. 인터넷 확인
import requests
try:
    requests.get("https://www.google.com", timeout=5)
    print("✅ 인터넷 연결 정상")
except:
    print("❌ 인터넷 연결 없음")

# 2. googletrans 설치 확인
try:
    from googletrans import Translator
    print("✅ googletrans 사용 가능")
except ImportError:
    print("⚠️ googletrans 없음, requests fallback만 사용")

# 3. 한글 포함 여부 확인
def has_korean(text):
    return any('\uac00' <= char <= '\ud7a3' for char in text)

if has_korean(text):
    result = korean_to_english(text)
else:
    print("한글이 없음")
```

### Q4: GenerationParamsManager가 설정을 로드하지 않음

**증상**: 모드 전환 시 UI가 업데이트되지 않음

**원인**:
1. 설정 파일이 없음
2. 잘못된 모드 이름
3. 위젯 참조 오류 (hasattr 실패)

**해결**:

```python
# 1. 설정 파일 확인
import os
filename = manager.get_mode_aware_filename("NAI")
print(f"설정 파일: {filename}")
print(f"존재 여부: {os.path.exists(filename)}")

# 2. 기본값 적용 확인
settings = manager._get_default_settings()
print(f"기본 설정: {settings}")

# 3. 위젯 참조 디버깅
mw = manager.main_window
print(f"model_combo exists: {hasattr(mw, 'model_combo')}")
print(f"steps_spinbox exists: {hasattr(mw, 'steps_spinbox')}")
```

### Q5: Stealth PNG가 읽히지 않음

**증상**: Stealth PNG 이미지인데 메타데이터 없음

**원인**:
1. RGB 이미지 (RGBA 필요)
2. 시그니처 손상
3. gzip 압축 해제 실패

**해결**:

```python
from PIL import Image
from utils.image_info import ImageMetadataExtractor

img = Image.open("stealth.png")

# 1. 모드 확인
print(f"Image mode: {img.mode}")  # RGBA여야 함

# 2. 직접 stealth 읽기 시도
stealth_data = ImageMetadataExtractor._read_stealth_pnginfo(img)
if stealth_data:
    print(f"✅ Stealth 데이터 발견: {len(stealth_data)} 자")
else:
    print("❌ Stealth 데이터 없음")

# 3. RGB → RGBA 변환 시도
if img.mode == 'RGB':
    img = img.convert('RGBA')
    stealth_data = ImageMetadataExtractor._read_stealth_pnginfo(img)
```

---

## 체크리스트

### 새 유틸리티 추가 시

```
[ ] 순수 함수 또는 가벼운 클래스로 구현
[ ] UI/컨트롤러에 의존하지 않음
[ ] 전역 상태 최소화
[ ] 예외 안전 (None 또는 빈 값 반환)
[ ] 타입 힌트 추가
[ ] 문서화 (docstring)
[ ] 단위 테스트 작성 (선택)
[ ] utils/CLAUDE.md에 문서 추가
```

### image_info.py 수정 시

```
[ ] 새 메타데이터 소스 추가 시:
    [ ] has_metadata()에 확인 로직 추가
    [ ] extract_metadata()에 추출 로직 추가
    [ ] 파싱 메서드 작성 (_parse_XXX)
[ ] Unicode 안전성 유지 (errors='ignore')
[ ] 예외를 catch하고 None 반환
[ ] 디버그 로그 추가 (print)
```

### token_calculator.py 수정 시

```
[ ] 모드별 전처리 로직 분리
[ ] CLIP 보정 계수 검증
[ ] artist: 태그 처리 (2 토큰 추가)
[ ] escaped paren 처리 (각 쌍 = 1 토큰)
[ ] 패턴 보정 계산 정확성 확인
[ ] 편의 함수 업데이트
```

### translator.py 수정 시

```
[ ] googletrans fallback 유지
[ ] requests 타임아웃 설정
[ ] 경고 억제 (warnings.filterwarnings)
[ ] 소문자 변환 (.lower())
[ ] 예외 안전 (None 반환)
```

### load_generation_params.py 수정 시

```
[ ] 새 파라미터 추가 시:
    [ ] collect_current_settings()에 수집 로직 추가
    [ ] apply_settings()에 적용 로직 추가
    [ ] _get_default_settings()에 기본값 추가
[ ] 콤보박스 설정 시 findText() 사용
[ ] 슬라이더 값 변환 (0-100 → 0.0-1.0 등)
[ ] 모드별 가시성 제어 (widget.setVisible())
```

---

## 참고 자료

### 관련 문서

- **[최상위 CLAUDE.md](../CLAUDE.md)**: 전체 프로젝트 개요
- **[core/CLAUDE.md](../core/CLAUDE.md)**: API 서비스, 컨트롤러
- **[modules/CLAUDE.md](../modules/CLAUDE.md)**: 모듈 개발 가이드
- **[tabs/CLAUDE.md](../tabs/CLAUDE.md)**: 탭 개발 가이드

### 예제 코드 위치

| 예제 | 파일 | 라인 | 특징 |
|------|------|------|------|
| **메타데이터 추출** | `tabs/png_info_tab.py` | 200-300 | has_metadata, extract_metadata 사용 |
| **토큰 계산** | `NAIA_cold_v4.py` | 1500-1600 | count_prompt_tokens 실시간 계산 |
| **번역** | `modules/prompt_engineering_module.py` | 500-600 | korean_to_english 통합 (예상) |
| **파라미터 로드** | `NAIA_cold_v4.py` | 500-700 | GenerationParamsManager 초기화 |

### 외부 라이브러리 참고

**PIL (Pillow)**:
- [Pillow 공식 문서](https://pillow.readthedocs.io/)
- [이미지 메타데이터](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html)

**tiktoken**:
- [tiktoken GitHub](https://github.com/openai/tiktoken)
- [Tokenizer 이해하기](https://platform.openai.com/tokenizer)

**googletrans**:
- [googletrans PyPI](https://pypi.org/project/googletrans/)
- ⚠️ 비공식 라이브러리, 불안정할 수 있음

**piexif**:
- [piexif GitHub](https://github.com/hMatoba/Piexif)
- [EXIF 태그 목록](https://www.exiv2.org/tags.html)

### 디버깅 팁

**이미지 메타데이터**:
```python
# PIL로 직접 확인
from PIL import Image
img = Image.open("image.png")
print(f"info: {img.info}")
print(f"mode: {img.mode}")
print(f"format: {img.format}")

# EXIF 직접 확인
exif = img.getexif()
for tag_id, value in exif.items():
    print(f"Tag {tag_id}: {value}")
```

**토큰 계산**:
```python
# tiktoken 직접 사용
import tiktoken
enc = tiktoken.get_encoding("gpt2")
tokens = enc.encode("1girl, smile")
print(f"Tokens: {tokens}")
print(f"Count: {len(tokens)}")

# 디코딩
for token in tokens:
    print(f"{token}: {enc.decode([token])}")
```

---

## 요약

**utils/의 핵심**:
- ✅ **독립성**: UI/컨트롤러에 의존하지 않음
- ✅ **ImageMetadataExtractor**: NAI/WebUI/Stealth PNG 메타데이터 추출
- ✅ **TokenCalculator**: GPT-2 + CLIP 근사 토큰 계산
- ✅ **korean_to_english**: 한글 → 영어 번역 (googletrans + API fallback)
- ✅ **GenerationParamsManager**: 모드별 파라미터 저장/로드
- ✅ **예외 안전**: 모든 유틸리티가 안전하게 실패 (None 반환)

**사용 패턴**:
1. **메타데이터 추출**: `ImageMetadataExtractor.extract_metadata()`
2. **토큰 계산**: `count_tokens()` 또는 `count_prompt_tokens()`
3. **번역**: `korean_to_english()`
4. **파라미터 관리**: `GenerationParamsManager` 인스턴스 생성 후 이벤트 연결

**다음 단계**:
1. 각 유틸리티 함수 사용법 숙지
2. 실전 예제 코드 실행
3. 필요 시 새 유틸리티 추가 (체크리스트 참고)

---

*문서 버전: 1.0*
*작성일: 2025-01-08*
*담당 영역: utils/ 디렉터리*
