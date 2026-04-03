# CLAUDE.md — Interactive Mode

> **목적**: Interactive Mode는 ComfyUI 스타일의 블록 기반 UI로 구성된 초보자 친화적 이미지 생성 인터페이스입니다.

---

## 아키텍처

### 파일 구조

```
ui/
├── interactive_window.py          # 메인 윈도우 (좌우 레이아웃)
└── interactive/
    ├── block_widget.py            # 블록 베이스 클래스
    ├── interactive_theme.py       # ComfyUI 스타일 테마
    ├── draggable_panel.py         # 플로팅 패널 시스템
    ├── interactive_autocomplete.py # 자동완성 시스템 (tags_unified 기반)
    ├── tag_viewer_widget.py       # 3단 구조 태그 뷰어 (MainPrompt용)
    ├── interactive                # 태그 통합 데이터셋 (25MB, 확장자 없음)
    ├── image_plane.py             # 이미지 표시 위젯 (중앙 배치)
    ├── floating_control_bar.py    # 하단 컨트롤 바 (생성/랜덤/설정)
    ├── parameter_panel.py         # 생성 파라미터 패널
    ├── person_settings_block.py   # 인원 수 / Rating 설정 (좌측)
    ├── quick_search_block.py      # 퀵 서치 (태그 추천, 좌측)
    ├── artist_tag_block.py        # 아티스트 태그 선택 (좌측)
    ├── quality_tag_block.py       # 품질 태그 설정 (좌측)
    ├── negative_prompt_block.py   # 네거티브 프롬프트 (좌측)
    ├── main_prompt_block.py       # 메인 프롬프트 (플로팅)
    ├── character_prompt_block.py  # 캐릭터 프롬프트 x6 (플로팅)
    ├── additional_negative_prompt_block.py  # 추가 네거티브 (플로팅)
    ├── composition_block.py       # X/Y/Z 축 구도 설정 (플로팅)
    ├── character_reference_block.py # NAI Character Reference (플로팅)
    ├── image_tagger_block.py      # WD14 이미지 태거 (플로팅)
    ├── tag_viewer_block.py        # 태그 뷰어 블록 (보조)
    ├── batch_image_processing_window.py # 배치 이미지 처리 윈도우
    ├── random_filter_dialog.py    # 랜덤 필터 다이얼로그
    ├── category_structure.py      # 카테고리 구조 정의
    └── quick_search_data.py       # Quick Search 데이터 로더
```

### 레이아웃

```
┌──────────────┬──────────────────────────────────────────────┐
│  좌측 패널    │  우측 패널 (이미지 뷰어 + 플로팅 패널 9개)     │
│  (460px)     │                                              │
│ PersonSettings│  [MainPrompt][C1~C6][AddNeg][Comp][Ref]     │
│ QuickSearch  │  [TagTgr][TagView]                           │
│ ArtistTag    │          [ImagePlane (중앙)]                  │
│ QualityTag   │                                              │
│ NegativePrompt│ [FloatingControlBar (하단 고정)]              │
└──────────────┴──────────────────────────────────────────────┘
```

### 데이터 흐름

```
PersonSettingsBlock → [settingsChanged] → QuickSearchBlock.load_partition()
MainPromptBlock → [generate_requested] → InteractiveWindow → GenerationController
CharacterPromptBlock → [random_field_requested] → QuickSearch 연동 (성별 기반 필터링)
ImageTaggerBlock → [tags_extracted] → MainPromptBlock.set_prompt_html()
FloatingControlBar → 랜덤/생성/사이드바 토글/핀/태그
InteractiveAutocompleteManager → [data_loaded] → TagViewer, MainPrompt 초기화
```

---

## 핵심 컴포넌트

### InteractiveWindow (`ui/interactive_window.py`)

전체 레이아웃 관리. 좌측 5개 블록 + 우측 9개 플로팅 요소.

**주요 메서드**: `collect_generation_params()`, `save_interactive_data()`, `load_interactive_data()`, `_reposition_floating_panels()`, `_handle_char_random_request()`

**저장 경로**: `save/interactive_data.json`

### BlockWidget (`block_widget.py`)

ComfyUI 스타일 블록의 기반 클래스.

**블록 타입별 색상**:

| 타입 | 색상 | 용도 |
|------|------|------|
| `latent` | 보라색 | 잠재 공간 |
| `conditioning` | 빨간색/핑크 | 프롬프트 |
| `model` | 파란색 | 모델 설정 |
| `image` | 초록색 | 이미지 생성 |
| `sampler` | 주황색 | 샘플러 |
| `utility` | 청록색 | 유틸리티 |
| `control` | 황금색 | 제어/설정 |
| `default` | 회색 | 기본 |

**필수 규칙**:
1. Vertical Policy: `QSizePolicy.Policy.Maximum`
2. 레이아웃 끝에 `layout.addStretch()` 필수
3. 스타일 격리: ID 선택자 사용 (`QPushButton#my_button { ... }`)

### DraggablePanel (`draggable_panel.py`)

자유 이동 가능한 플로팅 패널. Safe Move (최소 30px 보임), Z-Order 관리, 자동 크기 조절.

`FloatingPanelManager` (싱글톤): 패널 등록, 클릭/드래그/포커스 시 자동 최상단.

### InteractiveAutocompleteManager (`interactive_autocomplete.py`)

위젯별 데이터셋 지정 가능한 자동완성. `tags_unified.json` 기반 (16,698 태그).

**9개 데이터셋**: `general`, `clothing`, `body`, `food_object`, `composition`, `expression`, `creatures`, `location`, `nsfw`

**5단계 검색**: exact → starts_with → keyword(한글) → contains → description

**NAI 구문 지원**: `::` 가중치 편집 시 자동완성 무시, 괄호 매칭, prefix 처리.

```python
autocomplete_manager.register_widget(self.prompt_edit, dataset_id="general")
```

### TagViewer (`tag_viewer_widget.py`)

MainPromptBlock 전용 3단 구조 태그 브라우저 (대분류/소분류/태그). `use_tag_viewer` 속성으로 활성화.

- 3단 비율 (1:2:4), 800x600, 85% 불투명도
- 위젯 위치에 따라 좌/우 배치, 윈도우 경계 클램핑
- 2분할 미리보기: 기본 정보 + 연관 태그 (하이퍼링크 네비게이션)
- 더블클릭으로 프롬프트 삽입

### 테마 시스템 (`interactive_theme.py`)

```python
from ui.interactive.interactive_theme import COMMON_STYLES, INTERACTIVE_FONTS, FONT_FAMILY
```

스타일 함수: `get_header_style()`, `get_content_style()`, `get_button_style()`, `get_input_field_style()`, `get_combobox_style()`, `get_checkbox_style()`

### ImagePlane (`image_plane.py`)

PIL Image를 중앙에 비율 유지 표시. `clicked` 시그널 (TagViewer 접기 트리거). Z-Order 최하단.

### FloatingControlBar (`floating_control_bar.py`)

하단 고정 컨트롤 바.

**시그널**: `random_clicked`, `generate_clicked`, `random_generate_clicked`, `sidebar_toggled(bool)`, `float_pin_toggled(bool)`, `tags_clicked`

ParameterPanel 통합 (모델, steps, cfg_scale, sampler, scheduler, cfg_rescale, VAR+).

### CharacterPromptBlock (`character_prompt_block.py`)

6-슬롯 캐릭터 프롬프트 (C1~C6). 성별 선택, 이름/생김새/의상/표정/좌표/UC 필드. QuickSearch 연동 랜덤 생성.

### CharacterReferenceBlock (`character_reference_block.py`)

NAI Director Tool (NAID4.5). 이미지 업로드 + Style Aware + Fidelity 슬라이더 → `NAICharacterReferenceData` 변환.

### ImageTaggerBlock (`image_tagger_block.py`)

WD14 모델로 태그 자동 추출. `tags_extracted` 시그널로 MainPromptBlock에 덮어쓰기. 배치 처리 지원.

---

## 이미지 생성 플로우

`collect_generation_params()`에서 NAI 프롬프트 조합 순서:
1. 인원수 태그 (Main > Person, solo 제외)
2. Artist Tags
3. Composition Tags
4. Main Prompt (중복 제거)
5. Rating (없으면 추가)
6. Quality Tags (마지막)

`GenerationRequest` 생성 시 `nai_characters` (CharacterPromptBlock) + `nai_character_reference` (CharacterReferenceBlock) 포함.

---

## 플로팅 패널 자동 정렬

`_reposition_floating_panels()`: 최초 1회 + `is_floating_pinned=True` 상태에서 자동 정렬. 상단 수평 배치 (5px 간격): Main → Characters → AddNeg → Comp → Ref → Tagger.

핀 버튼 토글로 `is_floating_pinned` 제어.

---

## 주요 함정/주의사항

- **블록이 상하로 늘어남**: `addStretch()` 누락 또는 `SizePolicy.Maximum` 미설정
- **스타일 상속 깨짐**: ID 선택자(`#my_btn`)로 격리
- **콤보박스 스크롤**: `widget.wheelEvent = lambda e: e.ignore()` 로 방지
- **Quick Search 데이터**: 태그 수 13,053개 이하면 구버전 → 자동 다운로드 안내
- **자동완성 미동작**: `register_widget()` 호출 확인, `ui/interactive/interactive` 데이터 파일 존재 확인

---

## 관련 문서

- **[ui/CLAUDE.md](../CLAUDE.md)**: UI 시스템 가이드
- **[tabs/studio/CLAUDE.md](../../tabs/studio/CLAUDE.md)**: Studio Tab
