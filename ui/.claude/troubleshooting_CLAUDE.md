# UI 문제 해결 가이드 레퍼런스

> **레퍼런스 문서**: 자주 발생하는 문제와 해결 방법 모음입니다. 메인 문서에서 링크로 참조됩니다.

---

## Q1: 스타일이 적용되지 않아요

**증상**:
```python
button.setStyleSheet(DARK_STYLES['primary_button'])
# 버튼이 여전히 기본 스타일로 표시됨
```

**원인**:
1. 부모 위젯의 스타일시트가 우선순위 높음
2. Qt 스타일시트 특수성 규칙
3. DARK_STYLES가 최신 스케일 반영 안 됨

**해결**:

### 1. 스타일 직접 확인
```python
from ui.theme import DARK_STYLES

# 스타일 출력
print(DARK_STYLES['primary_button'])

# 정상 출력되는지 확인
```

### 2. 부모 스타일 확인
```python
# 부모 위젯에 너무 구체적인 스타일시트가 있는지 확인
print(parent_widget.styleSheet())

# 해결: 더 구체적인 선택자 사용
button.setStyleSheet(f"""
    QPushButton#myButton {{
        /* ... */
    }}
""")
button.setObjectName("myButton")
```

### 3. 동적 스타일 강제 갱신
```python
from ui.theme import get_dynamic_styles

# 최신 스케일 반영된 스타일 가져오기
latest_styles = get_dynamic_styles()
button.setStyleSheet(latest_styles['primary_button'])
```

---

## Q2: 스케일링이 작동하지 않아요

**증상**:
```python
font_size = get_scaled_font_size(21)
print(font_size)  # 항상 21 (스케일 안 됨)
```

**원인**:
1. ScalingManager 초기화 안 됨
2. 사용자가 자동 스케일링 비활성화
3. 스케일 팩터 범위 제한 (0.5~2.0)

**해결**:

### 1. ScalingManager 상태 확인
```python
from ui.scaling_manager import get_scaling_manager

manager = get_scaling_manager()
print(f"현재 스케일: {manager.get_scale_factor()}")
print(f"자동 스케일링: {manager.is_auto_scaling_enabled()}")
print(f"사용자 스케일: {manager.get_user_scale_factor()}")
```

### 2. 강제 재계산
```python
manager.refresh_scaling()
```

### 3. 수동 스케일 설정
```python
# 1.5배로 강제
manager.set_auto_scaling_enabled(False)
manager.set_user_scale_factor(1.5)
```

---

## Q3: CollapsibleBox가 비어 보여요

**증상**:
```python
box = EnhancedCollapsibleBox(title="모듈")
box.setContentLayout(my_layout)
# 펼쳐도 내용이 안 보임
```

**원인**:
1. 레이아웃에 위젯이 없음
2. 위젯의 크기 정책 문제
3. 레이아웃이 None

**해결**:

### 1. 레이아웃 확인
```python
# 레이아웃에 위젯이 있는지 확인
print(f"레이아웃 항목 수: {my_layout.count()}")

# 위젯들이 표시되는지 확인
for i in range(my_layout.count()):
    widget = my_layout.itemAt(i).widget()
    if widget:
        print(f"위젯 {i}: {widget}, visible={widget.isVisible()}")
```

### 2. 크기 정책 확인
```python
from PyQt6.QtWidgets import QSizePolicy

# 콘텐츠 위젯 크기 정책 설정
content_widget = QWidget()
content_widget.setSizePolicy(
    QSizePolicy.Policy.Expanding,
    QSizePolicy.Policy.Preferred
)
content_widget.setLayout(my_layout)
```

### 3. 최소 크기 설정
```python
# 콘텐츠에 최소 높이 지정
content_widget.setMinimumHeight(100)
```

---

## Q4: DetachedWindow가 메인 창 뒤에 숨어요

**증상**:
- 분리 창을 열었는데 메인 창 뒤에 숨음
- 활성화가 안 됨

**원인**:
1. `raise_()`, `activateWindow()` 호출 안 함
2. 윈도우 플래그 문제
3. OS 창 관리자 제한

**해결**:

### 1. 명시적 활성화
```python
detached_window.show()
detached_window.raise_()
detached_window.activateWindow()

# 추가: 포커스 설정
from PyQt6.QtCore import Qt
detached_window.setFocus(Qt.FocusReason.OtherFocusReason)
```

### 2. 윈도우 플래그 확인
```python
# 항상 위에 표시 (임시)
detached_window.setWindowFlags(
    detached_window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint
)
detached_window.show()
```

### 3. 지연 활성화
```python
from PyQt6.QtCore import QTimer

# 약간 지연 후 활성화
QTimer.singleShot(100, lambda: detached_window.raise_())
QTimer.singleShot(150, lambda: detached_window.activateWindow())
```

---

## Q5: ModernMenu 태그 정보가 안 나와요

**증상**:
```python
setModernStyle(text_edit)
# 우클릭해도 태그 정보 없음
```

**원인**:
1. `data/KR_tags.parquet` 파일 없음
2. 커서 위치에 태그 없음
3. DataFrame 로드 실패

**해결**:

### 1. 파일 확인
```python
import os

filepath = 'data/KR_tags.parquet'
if os.path.exists(filepath):
    print(f"✅ {filepath} 존재")

    import pandas as pd
    df = pd.read_parquet(filepath)
    print(f"태그 수: {len(df)}")
else:
    print(f"❌ {filepath} 없음")
```

### 2. 태그 형식 확인
```python
# 콤마로 구분된 태그여야 함
text_edit.setPlainText("1girl, smile, blue_eyes")

# 우클릭 시 각 태그 위치에서 정보 표시
```

### 3. 수동 로드 확인
```python
from ui.modern_menu import _load_kr_tags

kr_tags_df = _load_kr_tags()
print(f"로드된 태그: {len(kr_tags_df)}")

# 특정 태그 검색
result = kr_tags_df[kr_tags_df['tag'] == '1girl']
print(result)
```

---

## 추가 디버깅 팁

### 스타일시트 디버깅

```python
# 현재 적용된 스타일시트 확인
print(widget.styleSheet())

# 부모 스타일시트 확인
print(widget.parent().styleSheet())

# 계산된 스타일 확인 (Qt Designer 없이는 어려움)
```

### 스케일링 디버깅

```python
from ui.scaling_manager import get_scaling_manager

manager = get_scaling_manager()
print(f"현재 스케일: {manager.get_scale_factor()}")
print(f"자동 스케일링: {manager.is_auto_scaling_enabled()}")
print(f"사용자 스케일: {manager.get_user_scale_factor()}")

# 스케일 변경 감지
manager.scaling_changed.connect(lambda scale: print(f"스케일 변경: {scale}"))
```

### 레이아웃 디버깅

```python
def debug_layout(layout, indent=0):
    """레이아웃 구조 출력"""
    prefix = "  " * indent
    print(f"{prefix}Layout: {layout.__class__.__name__}, count={layout.count()}")
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget():
            w = item.widget()
            print(f"{prefix}  Widget: {w.__class__.__name__}, size={w.size()}, visible={w.isVisible()}")
        elif item.layout():
            debug_layout(item.layout(), indent + 1)

debug_layout(my_layout)
```

---

*레퍼런스 문서 버전: 1.0*
*최종 업데이트: 2025-01-17*
