# CLAUDE.md — tabs/artist_thumb/

> Artist Gallery Window: 4x2 그리드 갤러리 윈도우, 아티스트 썸네일, 관심 작가 토글, 커스텀 태그 생성.

---

## 아키텍처

```
artist_thumb_tab.py → opens → ArtistGalleryWindow (gallery_window.py)
                                    → contains 8x ArtistThumbnailFrame (artist_frame.py)
```

```
tabs/artist_thumb/
├── __init__.py
├── gallery_window.py     # ArtistGalleryWindow (QDialog)
├── artist_frame.py       # ArtistThumbnailFrame (QFrame)
└── CLAUDE.md
```

---

## ArtistGalleryWindow (`gallery_window.py`)

4x2 그리드 갤러리, 페이지네이션, 커스텀 태그 조합 생성.

**생성자**: `artist_data` (dict), `artist_list` (list), `favorite_artists` (list), `current_mode` (str), `parent`, `title_suffix` (str, 기본 "")

**시그널**:
- `favorite_toggled(str, bool)` -- 관심 작가 토글
- `artist_clicked(str)` -- 아티스트 선택
- `generate_requested(str)` -- 해당 작가로 생성
- `custom_generate_requested(str)` -- 커스텀 태그로 생성

**레이아웃**:
```
┌──────────────────────────────────────────────────────────────┐
│  [artist]★  [artist]   [artist]★  [artist]   │ 4x2 그리드  │
│  [artist]   [artist]★  [artist]   [artist]★  │             │
├──────────────────────────────────────────────────────────────┤
│ [<] 1/245 [>] │ 태그 조합: [________] [생성] │ 이동: [__][Go] │
└──────────────────────────────────────────────────────────────┘
```

---

## ArtistThumbnailFrame (`artist_frame.py`)

개별 아티스트 썸네일 프레임. Base64 썸네일 로드, 관심 작가 스타일링.

**시그널**: `favorite_toggled(str, bool)`, `artist_clicked(str)`, `generate_requested(str)`

**헤더 (5:1:1 비율)**: `[작가명 버튼 (클릭→관심 토글)] ★ │ 📋 복사 │ 🎨 생성`

**관심 작가 스타일**: 배경 `#2d5a2d` (녹색), 별표 `#ffd700` (금색) ★ / 비관심: 기본 배경, 회색 ☆

---

## 시그널 흐름

```
ArtistThumbnailFrame
    ├─ favorite_toggled → ArtistGalleryWindow → artist_thumb_tab._on_gallery_favorite_toggled
    ├─ artist_clicked   → ArtistGalleryWindow → artist_thumb_tab._on_gallery_artist_clicked
    └─ generate_requested → ArtistGalleryWindow → artist_thumb_tab._on_gallery_generate_requested

ArtistGalleryWindow (하단바)
    └─ custom_generate_requested → artist_thumb_tab._on_gallery_custom_generate_requested
         → positive_prompt 덮어쓰기 → QTimer.singleShot(100, _on_generate_clicked)
```

---

## 키보드/마우스 바인딩

| 입력 | 동작 |
|------|------|
| `←` / `A` | 이전 페이지 |
| `→` / `D` | 다음 페이지 |
| `Home` / `End` | 첫/마지막 페이지 |
| `Escape` | **블록** (창 닫지 않음) |
| 휠 위/아래 | 이전/다음 페이지 |
| 썸네일 클릭 | 아티스트 선택 |
| 헤더 클릭 | 관심 작가 토글 |

ESC 블록: `keyPressEvent`에서 `event.ignore()` 처리.

---

## 갤러리 열기 (필터 옵션)

`_open_gallery_window()`에서 `filter_combo` 값에 따라 다른 아티스트 리스트 생성:
- "관심 작가 보기" → favorite_artists 필터
- "제외 작가 보기" → banned_artists 필터
- 커스텀 필터 → `artist_thumb/{filter_name}.txt` 로드
- "전체 목록 보기" → 전체

가중치 기준 내림차순 정렬 후 `ArtistGalleryWindow` 생성.

---

## 스타일링

`DARK_COLORS` + `get_scaled_font_size()` / `get_scaled_size()` 사용.

주요 색상: `bg_primary`, `bg_secondary`, `bg_tertiary`, `accent_blue`, 관심 작가 `#2d5a2d`, 별표 `#ffd700`.
