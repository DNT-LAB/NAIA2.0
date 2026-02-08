from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QFrame, QApplication, QGraphicsDropShadowEffect,
    QSizePolicy, QRubberBand
)
from PyQt6.QtCore import Qt, QPoint, QRect, QSize, QEvent, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor, QColor, QPainter, QPen

from ui.theme import DARK_COLORS
from ui.interactive.interactive_theme import COMMON_STYLES
from ui.scaling_manager import get_scaled_size
from ui.interactive.draggable_panel import FloatingPanelManager

class SmoothImageLabel(QLabel):
    """
    setScaledContents(True)의 성능 문제(깜빡임)를 해결하기 위해
    paintEvent에서 직접 이미지를 그리는 커스텀 라벨.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setScaledContents(False)

    def paintEvent(self, event):
        if self.pixmap() and not self.pixmap().isNull():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # KeepAspectRatio로 스케일링
            target_rect = self.rect()
            scaled_pixmap = self.pixmap().scaled(target_rect.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            
            # 중앙 정렬 좌표 계산
            x = (target_rect.width() - scaled_pixmap.width()) // 2
            y = (target_rect.height() - scaled_pixmap.height()) // 2
            
            painter.drawPixmap(x, y, scaled_pixmap)
        else:
            super().paintEvent(event)

class ImagePlane(QWidget):
    """
    원본 비율을 유지하며 크기 조절 및 이동이 가능한 이미지 패널
    """
    clicked = pyqtSignal()  # 클릭 시그널 (드래그/리사이즈 아닌 단순 클릭)

    def __init__(self, parent=None, image_path=None):
        super().__init__(parent)



        self.setWindowFlags(Qt.WindowType.SubWindow)
        # Mouse tracking 필수 (리사이즈 커서 변경을 위해)
        self.setMouseTracking(True)

        self.min_size = get_scaled_size(100)
        self.resize_margin = get_scaled_size(8) # 마진

        # 이미지 비율 (width / height)
        self.aspect_ratio = 1.0  # 기본값: 정사각형

        # 원본 Pixmap 저장 (리사이즈 시 재사용)
        self._original_pixmap = None

        # 상태 변수
        self._dragging = False
        self._resizing = False
        self._resize_drag_pos = None
        self._drag_start_pos = None
        self._resize_edge = None
        self._pending_geometry = None  # 리사이즈 완료 시 적용할 최종 위치/크기
        self.rubber_band = None # 리사이즈 힌트용 러버밴드

        # 클릭 판정용 변수
        self._click_start_pos = None


        self._init_ui(image_path)

        # 초기 크기는 이미지 로드 후 설정됨 (aspect_ratio 기반)



    def _init_ui(self, image_path):
        # 레이아웃 제거 (성능 최적화: 레이아웃 매니저 오버헤드로 인한 깜빡임 방지)
        # 직접 resizeEvent에서 위치/크기 제어
        m = self.resize_margin
        
        # 1. 이미지 컨테이너
        self.content_frame = QFrame(self)
        self.content_frame.setStyleSheet(f"""
            background-color: transparent;
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: 8px;
        """)

        # 이미지 라벨
        self.image_label = SmoothImageLabel(self.content_frame)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("background-color: transparent;")

        # self.image_label.setScaledContents(True)  <-- SmoothImageLabel이 paintEvent에서 처리함


        if image_path:
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # 원본 pixmap 저장
                self._original_pixmap = pixmap

                # 비율 계산 및 저장
                self.aspect_ratio = pixmap.width() / pixmap.height()

                # 이미지 설정
                self.image_label.setPixmap(pixmap)

                # 초기 크기를 이미지 비율에 맞춰 설정 (기본 300px로 축소)
                initial_width = get_scaled_size(300)
                initial_height = initial_width / self.aspect_ratio
                # 마진 포함
                self.resize(int(initial_width + m * 2), int(initial_height + m * 2))
            else:
                self.image_label.setText("Image Load Failed")
                self.resize(get_scaled_size(300), get_scaled_size(300))
        else:
            self.image_label.setText("No Image")
            self.resize(get_scaled_size(300), get_scaled_size(300))

        # layout.addWidget(self.content_frame) <--- 제거


        # 그림자 초기화
        self._toggle_shadow(True)

    def _toggle_shadow(self, enable: bool):
        """성능 최적화를 위해 드래그 중에만 그림자 비활성화"""
        if enable:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(20)
            shadow.setXOffset(0)
            shadow.setYOffset(4)
            shadow.setColor(QColor(0, 0, 0, 100))
            self.setGraphicsEffect(shadow)
        else:
            self.setGraphicsEffect(None)

    def resizeEvent(self, event):
        """수동 레이아웃 업데이트 (깜빡임 방지)"""
        m = self.resize_margin
        
        # content_frame을 resize_margin을 뺀 중앙 영역에 배치
        cf_rect = QRect(m, m, self.width() - m * 2, self.height() - m * 2)
        self.content_frame.setGeometry(cf_rect)
        
        # image_label을 content_frame 내부에 꽉 채움 (border 1px 고려하여 살짝 안쪽으로)
        self.image_label.setGeometry(self.content_frame.rect().adjusted(1, 1, -1, -1))
        
        super().resizeEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        
        # 리사이즈 핸들 아이콘/선 그리기 - 마진 영역에
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 흰색 얇은 선
        pen = QPen(QColor(255, 255, 255, 100))
        pen.setWidth(1)
        painter.setPen(pen)
        
        # 마진의 중앙선에 그림
        rect = self.rect()
        # 1px 안쪽으로 보정
        l, t, r, b = rect.left() + 1, rect.top() + 1, rect.right() - 1, rect.bottom() - 1
        cl = 15 # Corner Length
        
        # Draw Corners (┌ ┐ ┘ └)
        lines = []
        
        # Top-Left ┌
        lines.append(QPoint(l, t + cl))
        lines.append(QPoint(l, t))
        lines.append(QPoint(l + cl, t))
        painter.drawPolyline(lines)
        
        # Top-Right ┐
        lines = []
        lines.append(QPoint(r - cl, t))
        lines.append(QPoint(r, t))
        lines.append(QPoint(r, t + cl))
        painter.drawPolyline(lines)
        
        # Bottom-Right ┘
        lines = []
        lines.append(QPoint(r, b - cl))
        lines.append(QPoint(r, b))
        lines.append(QPoint(r - cl, b))
        painter.drawPolyline(lines)
        
        # Bottom-Left └
        lines = []
        lines.append(QPoint(l + cl, b))
        lines.append(QPoint(l, b))
        lines.append(QPoint(l, b - cl))
        painter.drawPolyline(lines)



    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # 클릭 판정을 위해 시작 위치 저장
            self._click_start_pos = event.globalPosition().toPoint()

            # 성능 최적화: 조작 시작 시 그림자 제거
            self._toggle_shadow(False)

            # 리사이즈 영역 클릭 확인
            edge = self._check_resize_area(event.pos())
            if edge:
                self._resizing = True
                self._resize_edge = edge
                self._resize_drag_pos = event.globalPosition().toPoint()

                # 러버밴드 초기화 (전역 좌표계 사용)
                if not self.rubber_band:
                    self.rubber_band = QRubberBand(QRubberBand.Shape.Rectangle)

                # 현재 위치를 Global로 변환하여 러버밴드 표시
                global_pos = self.mapToGlobal(self.rect().topLeft())
                self.rubber_band.setGeometry(QRect(global_pos, self.size()))
                self.rubber_band.show()

                event.accept()
                return

            # 드래그 처리: 이미지 영역 등 클릭 시
            # 리사이즈 영역이 아니면 무조건 드래그로 간주
            self._dragging = True
            self._drag_start_pos = event.globalPosition().toPoint() - self.pos()
            event.accept()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 1. 리사이즈 중
        if self._resizing:
            if self._resize_edge:
                self._handle_resize(event.globalPosition().toPoint())
            event.accept()
            return
            
        # 2. 이동 중
        if self._dragging:
            if self._drag_start_pos:
                new_pos = event.globalPosition().toPoint() - self._drag_start_pos
                self.move_to_safe_position(new_pos)
            event.accept()
            return
            
        # 3. 마우스 커서 업데이트 (Hover)
        edge = self._check_resize_area(event.pos())
        if edge:
            self._update_cursor(edge)
        else:
            # 리사이즈 영역 아니면 기본적으로 SizeAll (이미지 드래그 가능하므로)
            self.setCursor(Qt.CursorShape.SizeAllCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # 클릭 판정: 이동 거리가 5px 미만이면 클릭으로 간주
        if self._click_start_pos is not None:
            release_pos = event.globalPosition().toPoint()
            move_distance = (release_pos - self._click_start_pos).manhattanLength()

            # 드래그/리사이즈가 아니고 이동 거리가 짧으면 클릭 시그널 발행
            if move_distance < 5 and not self._resizing:
                self.clicked.emit()
                print("[ImagePlane] 클릭 감지 - 좌측 패널 토글 시그널 발행")

        if self._resizing:
            # 리사이즈 종료: 러버밴드 숨기고 최종 크기 적용
            if self.rubber_band:
                self.rubber_band.hide()

            if self._pending_geometry:
                self.setGeometry(self._pending_geometry)
                self._pending_geometry = None

        self._dragging = False
        self._resizing = False
        self._resize_edge = None
        self._click_start_pos = None

        # 조작 종료 시 그림자 복구
        self._toggle_shadow(True)
        super().mouseReleaseEvent(event)

    # === 헬퍼 메서드 ===

    def _check_resize_area(self, pos):
        """마우스 위치가 리사이즈 영역(코너)인지 확인"""
        rect = self.rect()
        w, h = rect.width(), rect.height()
        x, y = pos.x(), pos.y()
        
        # 코너 감지 범위 (마진보다 넓게 잡아서 조작 용이성 확보)
        cz = 24 # Corner Size
        
        on_left = x < cz
        on_right = x > w - cz
        on_top = y < cz
        on_bottom = y > h - cz
        
        # 코너만 체크
        if on_top and on_left: return 'top-left'
        if on_top and on_right: return 'top-right'
        if on_bottom and on_left: return 'bottom-left'
        if on_bottom and on_right: return 'bottom-right'
        
        return None

    def _update_cursor(self, edge):
        # 요청사항: 커서를 + (Cross) 형태로 변경
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _handle_resize(self, global_mouse_pos):
        """리사이즈 로직 (원본 비율 유지)"""
        if not self._resize_edge: return

        prev_geo = self.geometry()

        # 부모 기준 마우스 위치
        parent_pos = self.parent().mapFromGlobal(global_mouse_pos)
        mx, my = parent_pos.x(), parent_pos.y()

        l, t, r, b = prev_geo.left(), prev_geo.top(), prev_geo.right(), prev_geo.bottom()

        # 1. Edge에 따라 잠정적 l, t, r, b 업데이트
        if 'left' in self._resize_edge: l = mx
        if 'right' in self._resize_edge: r = mx
        if 'top' in self._resize_edge: t = my
        if 'bottom' in self._resize_edge: b = my

        # 2. 너비/높이 계산
        raw_w = prev_geo.right() - l + 1 if 'left' in self._resize_edge else (r - prev_geo.left() + 1 if 'right' in self._resize_edge else prev_geo.width())
        raw_h = prev_geo.bottom() - t + 1 if 'top' in self._resize_edge else (b - prev_geo.top() + 1 if 'bottom' in self._resize_edge else prev_geo.height())

        if 'left' not in self._resize_edge and 'right' not in self._resize_edge: raw_w = prev_geo.width()
        if 'top' not in self._resize_edge and 'bottom' not in self._resize_edge: raw_h = prev_geo.height()

        # 3. 비율 유지 로직 제거 (자유 변형)
        target_w = max(raw_w, self.min_size)
        target_h = max(raw_h, self.min_size)

        # 좌표 재조정
        final_l, final_t = prev_geo.left(), prev_geo.top()

        if 'left' in self._resize_edge: final_l = prev_geo.right() - target_w + 1
        if 'top' in self._resize_edge: final_t = prev_geo.bottom() - target_h + 1

        new_geo = QRect(final_l, final_t, target_w, target_h)
        
        # [변경] 실시간 setGeometry 대신 러버밴드 업데이트만 수행
        self._pending_geometry = new_geo
        
        # Parent Local 좌표인 new_geo를 Global 좌표로 변환하여 러버밴드에 적용
        if self.parent():
            global_top_left = self.parent().mapToGlobal(new_geo.topLeft())
            self.rubber_band.setGeometry(QRect(global_top_left, new_geo.size()))
        else:
            # 부모가 없는 경우 (거의 없음)
            self.rubber_band.setGeometry(new_geo)


    def move_to_safe_position(self, pos: QPoint):
        """화면 이탈 방지 (ImagePlane은 상단 제한 없음)"""
        parent = self.parent()
        if not parent:
            self.move(pos)
            return

        parent_rect = parent.rect()
        panel_rect = self.rect()
        margin = 30

        x = max(-panel_rect.width() + margin, min(pos.x(), parent_rect.width() - margin))
        # ImagePlane은 상단을 넘어갈 수 있음 (y=0 제한 제거)
        y = min(pos.y(), parent_rect.height() - margin)

        self.move(x, y)

    def set_image(self, pil_image):
        """
        PIL Image를 받아 QPixmap으로 변환하여 표시

        Args:
            pil_image: PIL.Image 객체
        """
        try:
            # PIL Image를 QPixmap으로 변환
            from PIL.ImageQt import ImageQt

            # RGBA 모드로 변환 (Qt 호환성)
            if pil_image.mode != 'RGBA':
                pil_image = pil_image.convert('RGBA')

            # QImage로 변환
            qimage = ImageQt(pil_image)

            # QPixmap으로 변환
            pixmap = QPixmap.fromImage(qimage)

            if not pixmap.isNull():
                # 원본 pixmap 저장
                self._original_pixmap = pixmap

                # 비율 계산 및 저장
                self.aspect_ratio = pixmap.width() / pixmap.height()

                # 이미지 설정 (SmoothImageLabel이 알아서 비율 유지하며 그림)
                self.image_label.setPixmap(pixmap)
                
                # 리사이징 로직 제거: 위젯 크기는 유지하고 이미지만 그 안에서 출력됨
                # 단, 초기 로드 시 너무 작으면 기본 크기 설정? (선택사항)
                # 여기서는 사용자 요청대로 "사용자가 배치한 박스 안에서만" 처리하므로 크기 변경 없음.

                print(f"✅ ImagePlane: 이미지 설정 완료 (크기: {pil_image.size}, 비율: {self.aspect_ratio:.2f})")
            else:
                self.image_label.setText("Image Conversion Failed")
                print("❌ ImagePlane: QPixmap 변환 실패")

        except Exception as e:
            self.image_label.setText(f"Image Load Error: {e}")
            print(f"❌ ImagePlane: 이미지 설정 중 오류: {e}")
            import traceback
            traceback.print_exc()
