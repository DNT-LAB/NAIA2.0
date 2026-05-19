"""
Cached UI theme definitions.

future01 removed user-configurable scaling, so the old dynamic theme API now
returns fixed, cached QSS dictionaries for compatibility.
"""

from functools import lru_cache

from legacy_desktop.ui.scaling_manager import get_scaled_font_size, get_scaled_size

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


@lru_cache(maxsize=1)
def generate_dark_styles():
    """Return cached dark styles."""
    
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
    """Return cached dark styles for legacy callers."""
    return generate_dark_styles()


def get_legacy_dark_styles():
    """Return cached dark styles for legacy callers."""
    return generate_dark_styles()


# 하위 호환성을 위한 DARK_STYLES
DARK_STYLES = get_legacy_dark_styles()


@lru_cache(maxsize=1)
def get_custom_styles():
    """Return cached custom styles."""
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
CUSTOM = get_custom_styles()


# === Dark Theme MessageBox Helpers ===

@lru_cache(maxsize=1)
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


# ============================================================================
# TODO(web-dialog): future01 Web Shell 마이그레이션
# ----------------------------------------------------------------------------
# 데스크톱 GUI 가 hidden 모드로 동작하고 모든 사용자 상호작용은 QWebEngineView
# (Web Shell) 를 통해 이뤄지도록 마이그레이션 진행 중. QMessageBox.exec() 는
# 메인 스레드를 blocking 하여 같은 프로세스의 QWebEngineView 페인트도 정지시키
# 므로, 이 헬퍼들은 더 이상 dialog 를 띄우지 않고 콘솔에만 출력한다.
#
# 재구현 시 옵션:
#   1) Web Shell 토스트(`showToast(...)` JS) — info/warn/error 알림용
#   2) Web Shell 모달 dialog — confirm 류 (yes/no 응답 필요)
#   3) 그대로 데스크톱 popup 유지가 필요하면 `QMessageBox(...).show()` 비-modal
#      + `buttonClicked` 시그널 + 콜백 패턴
#
# 원본 동작 보존:
#   - show_info: QMessageBox.Information.exec()
#   - show_warning: QMessageBox.Warning.exec()
#   - show_error: QMessageBox.Critical.exec()
#   - show_question: QMessageBox.Question (Yes/No) — 사용자가 Yes 클릭하면 True
#
# show_question 은 안전한 기본값으로 항상 False 를 반환한다. 이 동작이 의미가
# 있는 호출처(예: "삭제하시겠습니까?")는 의도치 않은 진행을 방지하지만, 정상
# 흐름이 막힐 수 있으므로 호출처를 web shell confirm 으로 재설계해야 한다.
# ============================================================================

def _print_dialog(level: str, title: str, message: str):
    """blocking dialog 대체 — stdout 로그만 (web shell 토스트로 교체할 자리)."""
    print(f"[Dialog/{level}] {title}: {message}")


def show_info(parent, title: str, message: str):
    """TODO(web-dialog): 원래 QMessageBox(Information) — Web Shell 토스트로 재구현."""
    _print_dialog("INFO", title, message)


def show_warning(parent, title: str, message: str):
    """TODO(web-dialog): 원래 QMessageBox(Warning) — Web Shell 토스트(warn 톤)로 재구현."""
    _print_dialog("WARN", title, message)


def show_error(parent, title: str, message: str):
    """TODO(web-dialog): 원래 QMessageBox(Critical) — Web Shell 토스트(error 톤)로 재구현."""
    _print_dialog("ERROR", title, message)


def show_question(parent, title: str, message: str) -> bool:
    """TODO(web-dialog): 원래 QMessageBox(Question, Yes/No).exec() — 안전 기본값 False 반환.
    재구현 시 Web Shell 모달 confirm + 콜백 패턴으로 비동기화 필요.
    현재 호출처는 False 반환에 의해 진행 차단되므로 가능한 빨리 재설계 권장."""
    _print_dialog("CONFIRM(skipped→False)", title, message)
    return False
