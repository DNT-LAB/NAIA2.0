# CLAUDE.md — ui/

> **목적**: NAIA 2.0의 UI 시스템 가이드. 테마, 스케일링, 공용 위젯, RightView 탭 컨테이너를 다룹니다.

**레퍼런스 문서**:
- [NovelAI 메타데이터 필드](.claude/metadata_fields_CLAUDE.md)
- [Virtual Module 패턴 가이드](.claude/virtual_module_CLAUDE.md)
- [실전 예제 모음](.claude/examples_CLAUDE.md)
- [문제 해결 가이드](.claude/troubleshooting_CLAUDE.md)

---

## 개요

ui/는 NAIA 2.0의 **시각적 표현 계층**을 담당합니다.

**아키텍처**:
```
NAIA_cold_v4.py (메인 윈도우)
    ↓
ui/theme.py (색상 + 스타일)
ui/scaling_manager.py (DPI 계산)
    ↓
ui/collapsible.py (좌측 모듈 컨테이너)
ui/right_view.py (우측 탭 컨테이너)
ui/modern_menu.py (컨텍스트 메뉴)
ui/detached_window.py (분리 창)
```

**핵심 원칙**:
1. 모든 위젯은 DARK_STYLES 사용 (색상 하드코딩 금지)
2. `get_scaled_font_size()` / `get_scaled_size()` 필수
3. UI 스레드에서 무거운 작업 금지 (QThread 사용)
4. `QTextEdit.setAcceptRichText(False)` 필수

### 주요 파일

| 파일 | 역할 | 주요 클래스/함수 |
|------|------|-----------------|
| **theme.py** | 테마 색상 및 스타일 | `DARK_COLORS`, `generate_dark_styles()`, `DARK_STYLES` |
| **scaling_manager.py** | DPI 기반 UI 스케일링 | `ScalingManager`, `get_scaled_font_size()`, `get_scaled_size()` |
| **collapsible.py** | 접을 수 있는 모듈 박스 | `EnhancedCollapsibleBox` |
| **right_view.py** | 탭 컨테이너 및 브리징 | `RightView`, `EnhancedTabWidget` |
| **detached_window.py** | 독립 분리 창 | `DetachedWindow` |
| **modern_menu.py** | 컨텍스트 메뉴 스타일 | `setModernStyle()`, `setDarkStyle()` |
| **metadata_viewer.py** | 이미지 메타데이터 뷰어 | `MetadataViewerWindow` |
| **resolution_manager_dialog.py** | 해상도 관리 | `ResolutionManagerDialog` |
| **img2img_popup.py** | 이미지 작업 선택 팝업 | `Img2ImgPopup` |
| **img2img_window.py** | 독립 Img2Img/Inpaint 윈도우 | `Img2ImgWindow` |
| **tag_result_window.py** | 태그 분석 결과 윈도우 | `TagResultWindow` |
| **outpaint_window.py** | 아웃페인팅 설정 | `OutpaintWindow` |
| **image_viewer_window.py** | Honeyview 스타일 이미지 뷰어 | `NAIAImageViewer`, `ViewerBindingsDialog` |
| **character_asset_generation_window.py** | 캐릭터 에셋 연속 생성/저장 | `CharacterAssetGenerationWindow`, `CharacterAssetResultCard` |
| **character_asset_storage_window.py** | 저장된 에셋 스토리지 (C1 + 레퍼런스 인셋 적용) | `CharacterAssetStorageWindow`, `CharacterAssetStorageItem` |

---

## 테마 시스템

### DARK_COLORS 팔레트 (`theme.py`)

```python
DARK_COLORS = {
    'bg_primary': '#212121',  'bg_secondary': '#2B2B2B',  'bg_tertiary': '#2B2B2B',
    'bg_hover': '#404040',    'bg_pressed': '#4A4A4A',
    'text_primary': '#FFFFFF', 'text_secondary': "#B0B0B0", 'text_disabled': '#666666',
    'accent_blue': '#1976D2', 'accent_blue_hover': '#1565C0', 'accent_blue_light': '#42A5F5',
    'border': '#333333',      'border_light': '#666666',
    'success': '#4CAF50',     'warning': '#FF9800',        'error': '#F44336',
}
```

**함정 -- 존재하지 않는 키 (KeyError)**:
- `'accent'` → `'accent_blue'` 사용
- `'accent_hover'` → `'accent_blue_hover'` 사용
- `'primary'` → `'bg_primary'` 사용
- `'text'` → `'text_primary'` 사용

### DARK_STYLES 주요 키

| 키 | 용도 |
|----|------|
| `primary_button` / `secondary_button` / `compact_button` | 버튼 |
| `toggle_button` | 토글 버튼 |
| `compact_textedit` / `compact_lineedit` | 텍스트 입력 |
| `dark_checkbox` | 체크박스 |
| `dark_tabs` | 탭 위젯 |
| `compact_combobox` / `compact_spinbox` / `compact_slider` | 입력 컨트롤 |
| `collapsible_box` | 모듈 컨테이너 |
| `label_style` | 레이블 |

**사용법**:
```python
from ui.theme import DARK_STYLES, DARK_COLORS
self.generate_btn.setStyleSheet(DARK_STYLES['primary_button'])
```

---

## 스케일링 시스템

QHD(2560x1440)를 기준 해상도로, DPI 기반 자동 스케일링 제공. 범위 0.5~2.0.

```python
from ui.scaling_manager import get_scaled_font_size, get_scaled_size

label.setStyleSheet(f"font-size: {get_scaled_font_size(21)}px;")
layout.setContentsMargins(get_scaled_size(12), get_scaled_size(12), get_scaled_size(12), get_scaled_size(12))
```

**설정 파일**: `save/ui_scaling_settings.json`

---

## 공용 위젯

### CollapsibleBox (`collapsible.py`)

접을 수 있는 모듈 컨테이너. 분리 창 지원.

**시그널**:
- `module_detach_requested(str, object)` -- 모듈 분리 요청
- `toggled(str, bool)` -- 펼침/접힘 상태 변경

**주요 메서드**: `setContentLayout()`, `is_expanded()`, `set_expanded()`, `expand()`, `collapse()`, `get_scroll_position()`, `set_scroll_position()`

**특징**: 접을 때 스크롤 위치 자동 저장, 펼칠 때 자동 복원. 프로그래밍 방식으로 `emit_signal=False`를 사용해 시그널 없이 제어 가능.

### ModernMenu (`modern_menu.py`)

```python
from ui.modern_menu import setModernStyle
self.prompt_edit = QTextEdit()
setModernStyle(self.prompt_edit)  # 컨텍스트 메뉴 + 태그 정보 + 와일드카드
```

기능: KR_tags.parquet 기반 태그 툴팁, 인스턴트 와일드카드 통합, 스케일링 적용.

### QTextEdit 필수 규칙

모든 QTextEdit에 `setAcceptRichText(False)` 적용 필수 (웹 복사 서식 차단). `PromptHighlighter`는 내부 포맷을 사용하므로 정상 동작.

```python
self.prompt_edit = QTextEdit()
self.prompt_edit.setAcceptRichText(False)  # 필수
self.prompt_edit.setStyleSheet(DARK_STYLES['compact_textedit'])
```

---

## 독립 Img2Img 윈도우 시스템

### Img2ImgWindow (`ui/img2img_window.py`)

3-column 레이아웃: `[이미지 + Strength/Noise] | [메인 프롬프트] | [캐릭터 탭 | UC 탭]`

- Strength/Noise 슬라이더 (세션 동안 마지막 값 기억)
- 캐릭터 프롬프트 관리, Edit Mask 버튼
- 시그널: `generate_requested(int, dict)`, `window_closing(int)`

### Img2ImgWindowManager (`NAIA_cold_v4.py`)

`history_item` 전달 시 `initialize_from_history_item()`, 없으면 `initialize_from_main_ui()`.

### Tag Interrogation

`Img2ImgPopup` → WD14 태그 분석 → `generate_instant_source_silent()` → `TagResultWindow` (5 액션 버튼: 메인 프롬프트 적용, 즉시 생성, img2img, Inpaint, 닫기).

---

## 아웃페인팅 시스템

두 가지 모드:
1. **Auto-Outpainting**: img2img 체크박스 → 기본 캔버스에 자동 배치
2. **Outpaint 버튼**: `OutpaintWindow.get_outpaint_data()` → 캔버스/배치/마스크 직접 설정

`OutpaintWindow` 주요 기능: 캔버스 크기 프리셋, 스케일/회전 슬라이더, 드래그 배치 (8px 그리드 스냅), 리사이즈 핸들, 마스크 자동 생성 (블렌딩 보더 8px), RGBA 회전.

API: `_single_pass_outpainting()` → OutpaintWindow 데이터 사용 또는 기본 캔버스 자동 생성 (가로→1:1, 세로→3:2).

---

## 캐릭터 에셋 시스템

### 생성 창 (`character_asset_generation_window.py`)

CharacterModule "캐릭터 에셋 생성" 버튼 → hidden TempGenerationWindow 위에 모달리스 다이얼로그. 체크된 C1 캐릭터를 로드해 연속 생성하고 원하는 결과만 저장.

**핵심 흐름**:
1. `temp_window.build_c1_asset_generation_params(request_id, prompt, uc)` — 레퍼런스 프롬프트 스캐폴드(`ReferenceGenerationSpec.build_prompt()`) + C1 캐릭터만 포함, `wildcard_standalone=True`로 source_row 오염 방지
2. `character_asset_request=True` + `character_asset_request_id=uuid` 플래그로 요청 식별
3. 완료: `generation_completed_for_character_asset` 이벤트 구독 (payload는 `result` dict 전체 — `image`, `raw_bytes`, `generation_params`)
4. 실패: `generation_error` 채널 + `character_asset_request` 플래그/id 매칭

**수명주기**: `WA_DeleteOnClose=True`. `closeEvent`에서 `app_context.unsubscribe()` 호출 필수. 다이얼로그가 닫히면 부모 hidden temp window도 `destroyed` 연결로 함께 정리.

### 스토리지 창 (`character_asset_storage_window.py`)

`save/character_asset/images/`에 PNG만 저장 (메타데이터는 NAI Comment에서 런타임 복원).

**저장**: `raw_bytes` 우선 사용 — NAI Comment 손실 방지. `image`만 있으면 PIL 재인코딩되어 메타데이터가 사라지므로 저장 경로에서는 raw_bytes가 내려오는지 확인.

**복원 적용** (더블클릭):
1. `ImageMetadataExtractor.extract_metadata()`로 캐릭터 프롬프트/UC 복구
2. `CharacterModule.assign_c1(prompt, uc)` — C1 슬롯에 주입
3. `MainWindow.apply_character_asset_reference_from_image_path()` — 저장 이미지를 레퍼런스 인셋 캔버스로 img2img 패널에 적용 (`utils/reference_inpaint_preprocess.prepare_reference_inpaint_canvas`)

### Img2ImgPanel Comic Panel / 레퍼런스 인셋 모드

`_comic_panel_mode` 플래그가 켜지면:
- `strength=1.0`, `noise=0.0` 강제 (NovelAI 레퍼런스 인페인트 가이드 준수)
- strength 슬라이더 비활성, noise 그룹 숨김
- `get_generation_parameters()`도 1.0/0.0으로 오버라이드

Comic Panel 버튼과 캐릭터 에셋 적용 모두 이 플래그를 공유합니다. 기본 인페인트 슬라이더 값을 바꾸려면 플래그 분기를 재검토해야 합니다.

---

## 이미지 뷰어 (`image_viewer_window.py`)

Honeyview 스타일 전체화면 이미지 뷰어. `tabs/image_window.py`의 `[뷰어]` 버튼에서 진입.

**핵심 기능**:
- 전체화면/윈도우 모드 전환 (F/F11, 윈도우 모드 시 OS 네이티브 프레임)
- 마우스 휠 = 페이지 탐색, 좌클릭+휠 = 줌, 좌클릭+드래그 = 패닝
- 상단/하단 플로팅 오버레이 (마우스 호버 100px 영역, Pin 고정 가능)
- 페이지 슬라이더 + 경계 경고/순환 (첫/마지막 이미지)
- 사용자 정의 키/마우스 바인딩 → 복사/이동/삭제 액션 (최대 3개, `save/app_settings.json` 영속화)
- 복사/이동 대상 경로 설정 가능 (기본: `~/Pictures/꿀뷰/NAIA/{세션명}`)
- 우클릭 컨텍스트 메뉴: 클립보드 복사, 복사/이동/삭제, 파일 위치 열기, 키 바인딩 설정
- LRU 캐시 (31장) + QThread 백그라운드 프리로드 (뒤 10장, 앞 20장)
- `image_counter_changed` 이벤트 구독 + 포커스 시 폴더 mtime 체크로 실시간 동기화

**주요 클래스**: `NAIAImageViewer` (메인), `ImageViewerGraphicsView` (커스텀 QGraphicsView), `ViewerBindingsDialog` (설정), `PixmapCache`, `_PixmapCacheWorker`

---

## 분리 창 시스템

`DetachedWindow`: 위젯을 메인 윈도우에서 독립된 창으로 분리. 항상 위에 표시 토글, 도킹 시스템 지원, 창 닫힘 시 자동 복귀.

**사용 패턴**: 상태 플래그 초기화 → 레이아웃에서 위젯 분리 → `DetachedWindow` 생성 → `window_closed` 시그널로 복귀 처리.

---

## 리모트 컨트롤 창

**파일**: `ui/remote_window.py`

`RemoteWindow`는 메인 윈도우의 핵심 기능을 분리한 컴팩트 제어 패널. Mixin 패턴으로 탭별 코드 분리 (상세: [ui/remote/CLAUDE.md](remote/CLAUDE.md)).

**탭 구조**: P.엔지니어링 (프리셋 + 캐릭터 레퍼런스), 캐릭터 (프롬프트 즐겨찾기 + 관리), 이벤트 (필터링 + 대기열)

**RemoteWindow 상속**:
```python
class RemoteWindow(QMainWindow, QuickSearchTabMixin, EventTabMixin, InstantWcTabMixin, CharPromptTabMixin, CharRefTabMixin, PresetTabMixin):
```

### 즐겨찾기 시스템

- **프리셋**: `save/remote_preset_favorites/` -- 프리셋명으로 관리
- **캐릭터 프롬프트**: `save/character_prompt_favorites/` -- 폴더별 관리, 썸네일 지원
- **캐릭터 레퍼런스**: `save/remote_char_ref_favorites/` -- SHA-256 해시 기반 파일 관리, Storage 검증

### 이벤트 탭

`save/remote_events/` -- source_row 저장, 재생성 지원. Rating 필터 + 태그 검색 + 심층 검색. 대기열 시스템 (추가/비우기/순차 생성). 하트 기반 우선순위 정렬. **Parquet 내보내기**: 대기열/필터 결과를 `save/custom_tags/`에 parquet로 내보내서 메인 자동 생성 파이프라인에서 재활용.

---

## 의존성

**ui/가 의존**: `data/KR_tags.parquet`, `save/ui_scaling_settings.json`

**ui/를 의존**: `modules/`, `tabs/`, `core/`, `NAIA_cold_v4.py`
