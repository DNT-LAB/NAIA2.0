# ui/remote/ — RemoteWindow 서브모듈

> **목적**: RemoteWindow의 탭별 코드를 Mixin 패턴으로 분리하여 유지보수성 향상

---

## 디렉터리 구조

```
ui/remote/
├── __init__.py           # 모듈 export 정의
├── quick_search_tab.py   # 퀵 서치 탭 Mixin
├── event_tab.py          # 이벤트 탭 Mixin
├── instant_wc_tab.py     # 인스턴트 와일드카드 탭 Mixin
├── char_prompt_tab.py    # 캐릭터 프롬프트 탭 Mixin
├── char_ref_tab.py       # 캐릭터 레퍼런스 탭 Mixin
└── preset_tab.py         # 프리셋 탭 Mixin
```

**상속 순서**:
```python
class RemoteWindow(QMainWindow, QuickSearchTabMixin, EventTabMixin, InstantWcTabMixin, CharPromptTabMixin, CharRefTabMixin, PresetTabMixin):
```

---

## Mixin 패턴

Mixin은 다중 상속으로 기능을 추가하는 패턴. `self`는 호스트 클래스(RemoteWindow) 인스턴스를 가리킴.

**데이터 초기화**: RemoteWindow `__init__`에서 각 Mixin 초기화 호출 필수:
```python
self._init_quick_search_data()
self._init_char_ref_data()
self._init_char_prompt_data()
self._init_preset_data()
```

---

## 파일별 상세

### quick_search_tab.py

**클래스**: `QuickSearchTabMixin`, `QsPreviewPopup`, `SinglePartitionStore`, `FlowLayout`, `PartitionDataDownloadWorker`

**UI**: Filter (Rating/Person 체크박스) → Include/Exclude 태그 → 추천 태그 (3열 그리드, 페이지네이션) → 미리보기/생성 버튼

**특징**: EZMode STEP4 스타일 태그 버튼, 동적 필터링, 파티션 기반 데이터, 미리보기 팝업 (`QsPreviewPopup` - 외부 클릭으로 자동 닫힘).

### event_tab.py

**클래스**: `EventTabMixin`, `EventItemWidget`

**EventItemWidget 시그널**: `instant_generate_requested(str)`, `add_to_queue_requested(str)`, `delete_requested(str)`, `edit_requested(str, str)`, `heart_changed(str, int)`, `rating_changed(str, str)`

**썸네일**: `KeepAspectRatioByExpanding`으로 확대 후 중앙 크롭.

### instant_wc_tab.py

**클래스**: `InstantWcTabMixin`, `WildcardItemWidget`

**WildcardItemWidget 시그널**: `instant_generate_requested(str, str)`, `add_to_queue_requested(str, str)`, `delete_requested(str, str)`, `edit_requested(str, str, str)`, `heart_changed(str, str, int)`, `clip_requested(str, str)`

### char_prompt_tab.py

**클래스**: `CharPromptTabMixin`, `CharacterPromptFavoriteItemWidget`

**상수**: `CHAR_PROMPT_FAVORITES_DIR = Path("save/character_prompt_favorites")`, 썸네일 144x200

### char_ref_tab.py

**클래스**: `CharRefTabMixin`, `CharRefFavoriteItemWidget`

**상수**: `CHAR_REF_FAVORITES_DIR = Path("save/character_reference")`, 썸네일 120x167

**JSON 포맷 호환성 (중요)**: 기존 포맷 (직접 리스트) + 새 포맷 (`{"favorites": [...]}`) 모두 지원.

### preset_tab.py

**클래스**: `PresetTabMixin`, `PresetFavoriteItemWidget`

**상수**: `PRESET_FAVORITES_DIR = Path("save/presets/favorites")`, 썸네일 120x167

**양방향 동기화 (중요)**: 원본 PresetModule과 `_preset_sync_in_progress` 플래그로 무한 루프 방지. 전처리 체크박스도 양방향 연결.

---

## 주요 함정/주의사항

1. **self 참조**: Mixin 메서드에서 `self`는 RemoteWindow. `hasattr(self, 'xxx')`로 확인 권장
2. **순환 import 금지**: Mixin에서 `from ui.remote_window import RemoteWindow` 사용 금지
3. **메서드 이름 충돌 방지**: 탭별 고유 접두사 사용 (`_on_event_*`, `_on_wc_*`, `_on_qs_*`)
4. **시그널 타입**: item_data에서 가져온 값의 타입 확인 (dict/str 혼동 주의)

---

## 관련 문서

- **[ui/CLAUDE.md](../CLAUDE.md)**: UI 전체 가이드
