"""
동적 UI 테마 시스템
스케일링 매니저를 활용한 반응형 UI 지원
"""

from ui.scaling_manager import get_scaled_font_size, get_scaled_size

# 개선된 어두운 테마 색상 팔레트
DARK_COLORS = {
    'bg_primary': '#212121',      # 메인 배경 (매우 어두운 회색)
    'bg_secondary': '#2B2B2B',    # 서브 배경
    'bg_tertiary': '#2B2B2B',     # 카드/위젯 배경
    'bg_hover': '#404040',        # 호버 상태
    'bg_pressed': '#4A4A4A',      # 눌린 상태
    'text_primary': '#FFFFFF',    # 주요 텍스트 (흰색)
    'text_secondary': "#B0B0B0",  # 보조 텍스트 (회색)
    'text_disabled': '#666666',   # 비활성 텍스트
    'accent_blue': '#1976D2',     # 강조 파란색
    'accent_blue_hover': '#1565C0',
    'accent_blue_light': '#42A5F5',
    'accent_purple': '#7B1FA2',          # Material Purple 700
    'accent_purple_hover': '#6A1B9A',    # Material Purple 800
    'accent_purple_light': '#AB47BC',    # Material Purple 300
    'border': '#333333',          # 경계선
    'border_light': '#666666',    # 밝은 경계선
    'success': '#4CAF50',         # 성공 색상
    'warning': '#FF9800',         # 경고 색상
    'error': '#F44336',           # 오류 색상
    # 호환성을 위한 추가 키
    'background': '#212121',      # 메인 배경 (bg_primary와 동일)
    'panel': '#2B2B2B',          # 패널 배경 (bg_secondary와 동일)
    'input': '#2B2B2B',          # 입력 필드 배경 (bg_tertiary와 동일)
    'highlight': '#1976D2',       # 하이라이트 (accent_blue와 동일)
    'text': '#FFFFFF',            # 텍스트 (text_primary와 동일)
}


def generate_dark_styles():
    """현재 스케일링 팩터에 맞는 동적 스타일시트 생성"""
    
    # 기본 폰트 크기 정의 (QHD 기준)
    BASE_FONT_SIZES = {
        'main': 21,
        'title': 21, 
        'button': 18,
        'input': 22,
        'input_small': 19,
        'label': 19,
        'label_small': 16,
        'tab': 19,
        'combobox': 19,
        'status': 18,
        'compact': 16,
        'tiny': 14,
        'large': 24
    }
    
    # 기본 크기 정의 (QHD 기준)
    BASE_SIZES = {
        'padding_small': 4,
        'padding_medium': 8,
        'padding_large': 12,
        'margin_small': 2,
        'margin_medium': 4,
        'border_radius': 4,
        'border_radius_large': 6,
        'button_height': 16,
        'input_height': 20,
        'checkbox_size': 18,
        'icon_small': 16,
        'icon_medium': 20,
        'icon_large': 24,
        'scrollbar_width': 8,
        'slider_handle': 18
    }
    
    # 스케일 적용된 값들 계산
    fonts = {key: get_scaled_font_size(size) for key, size in BASE_FONT_SIZES.items()}
    sizes = {key: get_scaled_size(size) for key, size in BASE_SIZES.items()}
    
    return {
        'main_container': f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['main']}px;
                font-weight: 400;
            }}
            QToolTip {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_small']}px {sizes['padding_medium']}px;
                font-size: {fonts['compact']}px;
            }}
        """,
        
        'collapsible_box': f"""
            QWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius_large']}px;
                margin: {sizes['margin_small']}px {sizes['margin_medium']}px;
            }}
            QToolButton {{
                background-color: transparent;
                border: none;
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px {sizes['padding_large']}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 600;
                font-size: {fonts['title']}px;
                color: {DARK_COLORS['text_primary']};
                text-align: left;
            }}
            QToolButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """,
        
        'compact_card': f"""
            QFrame {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px;
                margin: {sizes['margin_small']}px {sizes['margin_medium']}px;
            }}
        """,
        
        'primary_button': f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                border: none;
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px {sizes['padding_large'] * 2}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['button']}px;
                min-height: {sizes['button_height']}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: #0D47A1;
            }}
        """,
        
        'secondary_button': f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px {sizes['padding_large'] + 4}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['button']}px;
                min-height: {sizes['button_height']}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 1px solid {DARK_COLORS['border_light']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """,
        
        'compact_button': f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_small']}px {sizes['padding_large']}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['compact']}px;
                min-height: {sizes['button_height']}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 1px solid {DARK_COLORS['border_light']};
            }}
            QPushButton:pressed {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
            QPushButton:disabled {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_disabled']};
                border: 1px solid {DARK_COLORS['border']};
            }}
        """,
        
        'toggle_button': f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px {sizes['padding_large'] + 4}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['status']}px;
            }}
            QPushButton:hover:!checked {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 1px solid {DARK_COLORS['border_light']};
            }}
            QPushButton:checked {{
                background-color: {DARK_COLORS['accent_blue_hover']};
                border: 1px solid {DARK_COLORS['accent_blue']};
                color: {DARK_COLORS['text_primary']};
                font-weight: 600;
            }}
            QPushButton:disabled {{
                background-color: #404040;
                color: #888888;
            }}
        """,
        
        'expand_toggle_button': f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                border: none;
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px {sizes['padding_large'] + 4}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 600;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['compact']}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
            QPushButton:pressed {{
                background-color: #0D47A1;
            }}
        """,
        
        'compact_textedit': f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px;
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['input']}px;
            }}
            QTextEdit:focus {{
                border: 2px solid {DARK_COLORS['accent_blue']};
            }}
        """,
        
        'dark_text_edit': f"""
            QTextEdit {{
                background-color: transparent;
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px;
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['input']}px;
            }}
            QTextEdit QAbstractScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
        """,
        
        'compact_lineedit': f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px {sizes['padding_large']}px;
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['input_small']}px;
                min-height: {sizes['input_height']}px;
            }}
            QLineEdit:focus {{
                border: 2px solid {DARK_COLORS['accent_blue']};
            }}
        """,
        
        'dark_checkbox': f"""
            QCheckBox {{
                background-color: transparent;
                spacing: {sizes['padding_medium']}px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['label']}px;
                color: {DARK_COLORS['text_primary']};
            }}
            QCheckBox::indicator {{
                width: {sizes['checkbox_size']}px;
                height: {sizes['checkbox_size']}px;
                border: 1px solid {DARK_COLORS['border_light']};
                border-radius: 3px;
                background-color: {DARK_COLORS['bg_secondary']};
            }}
            QCheckBox::indicator:checked {{
                background-color: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['accent_blue']};
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {DARK_COLORS['accent_blue_light']};
            }}
        """,
        
        'dark_tabs': f"""
            QTabWidget::pane {{
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                background-color: {DARK_COLORS['bg_tertiary']};
                margin-top: 2px;
            }}
            QTabBar::tab {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-bottom: none;
                border-top-left-radius: {sizes['border_radius']}px;
                border-top-right-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_medium']}px {sizes['padding_large']}px;
                margin-right: 1px;
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                color: {DARK_COLORS['text_secondary']};
                font-size: {fonts['tab']}px;
            }}
            QTabBar::tab:selected {{
                background-color: {DARK_COLORS['bg_tertiary']};
                color: {DARK_COLORS['text_primary']};
                border-bottom: 2px solid {DARK_COLORS['accent_blue']};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """,
        
        'compact_combobox': f"""
            QComboBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_small']}px {sizes['padding_large']}px;
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['combobox']}px;
                min-height: {sizes['input_height']}px;
            }}
            QComboBox:hover {{
                border: 1px solid {DARK_COLORS['border_light']};
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QComboBox:focus {{
                border: 2px solid {DARK_COLORS['accent_blue']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: {sizes['icon_medium']}px;
                padding-right: 5px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {DARK_COLORS['text_secondary']};
                width: 0px;
                height: 0px;
            }}
            QComboBox::down-arrow:hover {{
                border-top: 5px solid {DARK_COLORS['text_primary']};
            }}
            QComboBox QAbstractItemView {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                color: {DARK_COLORS['text_primary']};
                selection-background-color: {DARK_COLORS['accent_blue']};
                selection-color: {DARK_COLORS['text_primary']};
                font-size: {fonts['combobox']}px;
                padding: {sizes['padding_small']}px;
            }}
            QComboBox QAbstractItemView::item {{
                padding: {sizes['padding_small']}px {sizes['padding_large']}px;
                border: none;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
        """,
        
        'compact_spinbox': f"""
            QSpinBox, QDoubleSpinBox {{
                background-color: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                padding: {sizes['padding_small']}px {sizes['padding_medium']}px;
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['compact']}px;
                min-height: {sizes['icon_medium']}px;
            }}
            QSpinBox:hover, QDoubleSpinBox:hover {{
                border: 1px solid {DARK_COLORS['border_light']};
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 2px solid {DARK_COLORS['accent_blue']};
            }}
            QSpinBox::up-button, QDoubleSpinBox::up-button {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: none;
                border-left: 1px solid {DARK_COLORS['border']};
                border-top-right-radius: 3px;
                width: {sizes['icon_small']}px;
                padding: 2px;
            }}
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 4px solid {DARK_COLORS['text_secondary']};
                width: 0px;
                height: 0px;
            }}
            QSpinBox::up-arrow:hover, QDoubleSpinBox::up-arrow:hover {{
                border-bottom: 4px solid {DARK_COLORS['text_primary']};
            }}
            QSpinBox::down-button, QDoubleSpinBox::down-button {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: none;
                border-left: 1px solid {DARK_COLORS['border']};
                border-bottom-right-radius: 3px;
                width: {sizes['icon_small']}px;
                padding: 2px;
            }}
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
                background-color: {DARK_COLORS['bg_hover']};
            }}
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid {DARK_COLORS['text_secondary']};
                width: 0px;
                height: 0px;
            }}
            QSpinBox::down-arrow:hover, QDoubleSpinBox::down-arrow:hover {{
                border-top: 4px solid {DARK_COLORS['text_primary']};
            }}
        """,
        
        'compact_slider': f"""
            QSlider {{
                background: transparent;
                outline: none;
            }}
            QSlider::groove:horizontal {{
                background: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                height: {sizes['padding_medium']}px;
                border-radius: {sizes['border_radius']}px;
            }}
            QSlider::handle:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border_light']};
                width: {sizes['slider_handle']}px;
                height: {sizes['slider_handle']}px;
                margin: -{sizes['padding_small'] + 2}px 0;
                border-radius: 9px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {DARK_COLORS['accent_blue_hover']};
                border: 2px solid {DARK_COLORS['accent_blue_light']};
            }}
            QSlider::handle:horizontal:pressed {{
                background: {DARK_COLORS['accent_blue_hover']};
            }}
            QSlider::sub-page:horizontal {{
                background: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border']};
                height: {sizes['padding_medium']}px;
                border-radius: {sizes['border_radius']}px;
            }}
            QSlider::add-page:horizontal {{
                background: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                height: {sizes['padding_medium']}px;
                border-radius: {sizes['border_radius']}px;
            }}
            QSlider::groove:vertical {{
                background: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                width: {sizes['padding_medium']}px;
                border-radius: {sizes['border_radius']}px;
            }}
            QSlider::handle:vertical {{
                background: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border_light']};
                width: {sizes['slider_handle']}px;
                height: {sizes['slider_handle']}px;
                margin: 0 -{sizes['padding_small'] + 2}px;
                border-radius: 9px;
            }}
            QSlider::handle:vertical:hover {{
                background: {DARK_COLORS['accent_blue_hover']};
                border: 2px solid {DARK_COLORS['accent_blue_light']};
            }}
            QSlider::sub-page:vertical {{
                background: {DARK_COLORS['bg_secondary']};
                border: 1px solid {DARK_COLORS['border']};
                width: {sizes['padding_medium']}px;
                border-radius: {sizes['border_radius']}px;
            }}
            QSlider::add-page:vertical {{
                background: {DARK_COLORS['accent_blue']};
                border: 1px solid {DARK_COLORS['border']};
                width: {sizes['padding_medium']}px;
                border-radius: {sizes['border_radius']}px;
            }}
        """,
        
        'transparent_frame': f"""
            QFrame {{
                background-color: transparent;
                border: none;
            }}
        """,
        
        'label_style': f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['label']}px;
            }}
        """,
    }


def get_dynamic_styles():
    """현재 스케일링에 맞는 동적 스타일 생성"""
    return generate_dark_styles()


def get_legacy_dark_styles():
    """하위 호환성을 위한 동적 DARK_STYLES 생성"""
    return generate_dark_styles()


# 하위 호환성을 위한 동적 DARK_STYLES
# 스케일링 매니저는 항상 사용 가능하므로 간단히 호출
DARK_STYLES = get_legacy_dark_styles()


# 커스텀 스타일 딕셔너리 (동적 스케일링 적용)
def get_custom_styles():
    """커스텀 스타일 딕셔너리 생성 (동적 스케일링 적용)"""
    fonts = {
        'main': get_scaled_font_size(21),
        'status': get_scaled_font_size(18),
        'title': get_scaled_font_size(21),
        'label': get_scaled_font_size(19),
        'compact': get_scaled_font_size(16),
        'tiny': get_scaled_font_size(14),
    }
    
    sizes = {
        'padding_medium': get_scaled_size(8),
        'border_radius': get_scaled_size(4),
        'scrollbar_width': get_scaled_size(8),
    }
    
    return {
        "middle_scroll_area": f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_secondary']};
                width: {sizes['scrollbar_width']}px;
                border-radius: {sizes['border_radius']}px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['border_light']};
                border-radius: {sizes['border_radius']}px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['accent_blue_light']};
            }}
        """,
        
        "main": f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard';
            }}
        """,
        
        "top_scroll_area": f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_secondary']};
                width: {sizes['scrollbar_width']}px;
                border-radius: {sizes['border_radius']}px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['border_light']};
                border-radius: {sizes['border_radius']}px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['accent_blue_light']};
            }}
        """,
        
        "toggle_active_style": f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                border: none;
                border-radius: {sizes['border_radius']}px;
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 600;
                font-size: {fonts['status']}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """,
        
        "toggle_inactive_style": f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {sizes['border_radius']}px;
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                font-size: {fonts['status']}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """,
        
        "status_bar": f"""
            QStatusBar {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-top: 1px solid {DARK_COLORS['border']};
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: {fonts['status']}px;
            }}
        """,
        
        "main_splitter": f"""
            QSplitter::handle {{
                background-color: {DARK_COLORS['border']};
                height: 3px;
                margin: 0px 4px;
                border-radius: 1px;
            }}
            QSplitter::handle:hover {{
                background-color: {DARK_COLORS['accent_blue_light']};
            }}
        """,
        
        "params_title": f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['title']}px;
                font-weight: 600;
                margin-bottom: {sizes['padding_medium']}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """,
        
        "param_label_style": f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['label']}px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """,
        
        "naid_options_label": f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                color: {DARK_COLORS['text_primary']};
                font-size: {fonts['label']}px;
                font-weight: 500;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """,
    }


# 하위 호환성을 위한 CUSTOM 딕셔너리
# 스케일링 매니저는 항상 사용 가능하므로 간단히 호출
CUSTOM = get_custom_styles()


# === Dark Theme MessageBox Helpers ===

def get_message_box_stylesheet() -> str:
    """Get dark theme stylesheet for QMessageBox"""
    return f"""
        QMessageBox {{
            background-color: {DARK_COLORS['bg_primary']};
        }}
        QMessageBox QLabel {{
            color: {DARK_COLORS['text_primary']};
            font-size: {get_scaled_font_size(15)}px;
        }}
        QMessageBox QPushButton {{
            background-color: {DARK_COLORS['bg_tertiary']};
            color: {DARK_COLORS['text_primary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px;
            padding: 6px 16px;
            min-width: 80px;
            font-size: {get_scaled_font_size(14)}px;
        }}
        QMessageBox QPushButton:hover {{
            background-color: {DARK_COLORS['bg_hover']};
        }}
        QMessageBox QPushButton:pressed {{
            background-color: {DARK_COLORS['bg_pressed']};
        }}
    """


def show_info(parent, title: str, message: str):
    """Show dark-themed information message box"""
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setStyleSheet(get_message_box_stylesheet())
    msg.exec()


def show_warning(parent, title: str, message: str):
    """Show dark-themed warning message box"""
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setStyleSheet(get_message_box_stylesheet())
    msg.exec()


def show_error(parent, title: str, message: str):
    """Show dark-themed error message box"""
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setStyleSheet(get_message_box_stylesheet())
    msg.exec()


def show_question(parent, title: str, message: str) -> bool:
    """Show dark-themed question message box, returns True if Yes clicked"""
    from PyQt6.QtWidgets import QMessageBox
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle(title)
    msg.setText(message)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    msg.setStyleSheet(get_message_box_stylesheet())
    return msg.exec() == QMessageBox.StandardButton.Yes