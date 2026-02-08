# Sketchbook 마스크 자동 적용 솔루션

## 문제점
- Sketchbook에서 전송된 마스크가 Main Window에 도달하지만 API로 전달되지 않음
- 빈 마스크가 API로 전송되어 인페인트가 작동하지 않음

## 해결 방법: InpaintWindow 자동 처리

### 핵심 아이디어
skip_window로 InpaintWindow를 건너뛰는 대신, InpaintWindow의 검증된 마스크 처리 로직을 활용하여 자동으로 "Save Image" 효과를 구현

### 구현 내용

#### 1. InpaintWindow에 auto_accept 파라미터 추가
```python
# ui/inpaint_window.py
@staticmethod
def get_inpaint_data(pil_image: Image.Image, initial_mask: Image.Image = None, 
                     parent=None, auto_accept: bool = False) -> dict | None:
    dialog = InpaintWindow(pil_image, initial_mask, parent)
    
    # auto_accept가 True이면 즉시 accept() 호출
    if auto_accept and initial_mask is not None:
        dialog.accept()  # 마스크 처리 로직 실행
        return dialog.result
    
    # 일반적인 경우 dialog 표시
    result_code = dialog.exec()
    if result_code == QDialog.DialogCode.Accepted:
        return dialog.result
    return None
```

#### 2. Img2ImgPanel에 전용 메서드 추가
```python
# ui/img2img_panel.py
def set_mask_from_sketchbook(self, mask_pil: Image.Image):
    """Sketchbook 마스크를 InpaintWindow를 통해 처리"""
    
    # InpaintWindow를 통해 마스크 자동 처리
    result = InpaintWindow.get_inpaint_data(
        self.original_pil_image, 
        mask_pil,           # Sketchbook 마스크
        self, 
        auto_accept=True    # 자동 처리
    )
    
    if result and "full_mask_image" in result:
        # InpaintWindow가 생성한 마스크 적용
        self.mode = 'inpaint'
        self.full_mask_pil = result["full_mask_image"]   # 전체 크기 마스크
        self.small_mask_pil = result["small_mask_image"] # 1/8 크기 마스크 (NAI용)
        
        # 미리보기 업데이트
        if "preview_image" in result:
            # ... preview 처리
        
        self._update_ui_for_mode()
        return True
```

#### 3. SketchbookWidget 수정
```python
# tabs/assets/sketchbook/sketchbook_widget.py
def _handle_send_to_main(self, canvas_pixmap: QPixmap, mask_pixmap: QPixmap):
    # ... 캔버스와 마스크 변환
    
    # Main Window 활성화
    main_window.activate_inpaint_mode(canvas_pil, skip_window=True)
    
    # 새로운 메서드로 마스크 처리
    if hasattr(main_window, 'img2img_panel'):
        panel = main_window.img2img_panel
        
        # InpaintWindow를 통한 자동 마스크 처리
        if panel.set_mask_from_sketchbook(mask_pil):
            panel.strength_slider.setValue(99)  # 0.99
            panel.noise_slider.setValue(5)      # 0.05
```

## 장점

### 1. 검증된 마스크 처리 로직 재사용
- InpaintWindow의 8x8 격자 시스템 활용
- full_mask와 small_mask 자동 생성
- 이진화 처리 보장

### 2. 일관성 있는 마스크 형식
- InpaintWindow를 통과한 마스크는 항상 올바른 형식
- API 호환성 보장

### 3. 사용자 경험 개선
- 마스크 편집 창이 나타나지 않음 (auto_accept)
- 마스크가 정확히 적용됨
- Edit Mask 버튼으로 추가 편집 가능

## 작동 흐름

```
1. Sketchbook에서 [Send to Main] 클릭
   ↓
2. 캔버스 이미지와 마스크 추출
   ↓
3. Main Window 활성화
   ↓
4. set_mask_from_sketchbook() 호출
   ↓
5. InpaintWindow(auto_accept=True)
   ↓
6. accept() 자동 실행
   - 8x8 격자로 마스크 처리
   - full_mask 생성 (원본 크기)
   - small_mask 생성 (1/8 크기)
   ↓
7. 마스크 적용 완료
   ↓
8. API로 정상 전달
```

## 테스트 결과
✅ 모든 기능 정상 작동
- 마스크가 InpaintWindow를 통해 올바르게 처리됨
- full_mask와 small_mask 모두 생성됨
- API로 마스크가 정상 전달됨
- 생성 시 인페인트가 올바르게 작동함

## 결론
InpaintWindow의 검증된 마스크 처리 로직을 재사용하여, 안정적이고 일관성 있는 마스크 전송을 구현했습니다. 사용자는 마스크 편집 창을 보지 않고도 Sketchbook에서 그린 마스크가 정확히 적용되는 것을 확인할 수 있습니다.