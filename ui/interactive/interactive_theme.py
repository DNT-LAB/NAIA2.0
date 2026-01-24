# ui/interactive/interactive_theme.py
"""
Interactive Mode Theme - ComfyUI 스타일의 블록 테마
"""

from ui.scaling_manager import get_scaled_size, get_scaled_font_size
from ui.theme import DARK_COLORS

# 폰트 패밀리 정의
FONT_FAMILY = "'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif"

# 공통 스타일 (ui/theme.py의 DARK_COLORS 참조)
COMMON_STYLES = {
    'text_primary': DARK_COLORS['text_primary'],      # #FFFFFF
    'text_secondary': DARK_COLORS['text_secondary'],  # #B0B0B0
    'text_disabled': DARK_COLORS['text_disabled'],    # #666666
    'input_bg': DARK_COLORS['bg_secondary'],          # #2B2B2B
    'input_border': DARK_COLORS['border'],            # #333333
    'input_focus': DARK_COLORS['accent_blue'],        # #1976D2
    'error': DARK_COLORS['error'],                    # #F44336
}

# 인터랙티브 모드 전용 폰트 사이즈 (ui/theme.py와 비율 맞춤)
# 인터랙티브 모드 전용 폰트 사이즈 (ui/theme.py와 비율 맞춤)
INTERACTIVE_FONTS = {
    'header': 20,    # 헤더 타이틀 (가독성 위해 +2)
    'content': 18,   # 일반 내용 (+2)
    'label': 18,     # 라벨 (+2)
    'input': 20,     # 입력 필드 (+2)
    'tiny': 16       # 작은 텍스트 (+2)
}


# ComfyUI 스타일 블록 색상 팔레트 (복원 및 최적화)
BLOCK_COLORS = {
    # Latent 계열 (보라색)
    'latent': {
        'header': '#5e4fa2',
        'content': '#2a2438',
    },
    # Conditioning 계열 (빨간색/핑크)
    'conditioning': {
        'header': '#8b4a6f',
        'content': '#3d2533',
    },
    # Model 계열 (파란색)
    'model': {
        'header': '#4a708b',
        'content': '#25333d',
    },
    # Image 계열 (초록색)
    'image': {
        'header': '#4a8b6f',
        'content': '#253d33',
    },
    # Sampler 계열 (주황색)
    'sampler': {
        'header': '#8b6f4a',
        'content': '#3d3325',
    },
    # Utility 계열 (회색/청록)
    'utility': {
        'header': '#4a7a8b',
        'content': '#25353d',
    },
    # Control 계열 (노란색/황금)
    'control': {
        'header': '#8b7a4a',
        'content': '#3d3525',
    },
    # Default (어두운 회색)
    'default': {
        'header': '#4a4a4a',
        'content': '#252525',
    },
}


def get_block_style(block_type: str = 'default') -> dict:
    """
    블록 타입에 따른 스타일 딕셔너리 반환
    """
    return BLOCK_COLORS.get(block_type, BLOCK_COLORS['default'])


def get_header_style(block_type: str = 'default', collapsed: bool = False) -> str:
    """
    ComfyUI 스타일의 헤더 스타일 생성 (Flat Design)
    """
    colors = get_block_style(block_type)
    radius = get_scaled_size(8)
    
    if collapsed:
        border_radius = f"{radius}px"
    else:
        border_radius = f"{radius}px {radius}px 0px 0px"

    return f"""
        QFrame {{
            background-color: {colors['header']};
            border: none;
            border-radius: {border_radius};
            padding: {get_scaled_size(8)}px {get_scaled_size(12)}px;
        }}
        QFrame:hover {{
            background-color: {_lighten_color(colors['header'], 0.1)};
        }}
        QLabel {{
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['header'])}px;
            font-weight: bold;
            background: transparent;
            border: none;
        }}
    """


def get_content_style(block_type: str = 'default') -> str:
    """
    블록 내용 영역 스타일 생성 (내부 위젯 스타일 포함)

    Args:
        block_type: 블록 타입

    Returns:
        QSS 스타일 문자열
    """
    colors = get_block_style(block_type)
    radius = get_scaled_size(8)
    
    # 내부 텍스트 색상 (약간 덜 밝은 흰색)
    text_color = "#E0E0E0"

    # 기본 프레임 스타일
    base_style = f"""
        QFrame {{
            background-color: {colors['content']};
            border: none;
            border-bottom-left-radius: {radius}px;
            border-bottom-right-radius: {radius}px;
            border-top-left-radius: 0px;
            border-top-right-radius: 0px;
            margin-top: 0px;
        }}
    """
    
    # 내부 요소 스타일 (상속을 위해 여기에 포함)
    children_style = f"""
        QLabel {{
            color: {text_color};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            background: transparent;
            border: none;
            padding: 0;
        }}
        
        QCheckBox {{
            color: {text_color};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            spacing: {get_scaled_size(8)}px;
            background: transparent; 
        }}
        QCheckBox::indicator {{
            width: {get_scaled_size(18)}px;
            height: {get_scaled_size(18)}px;
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            background-color: {COMMON_STYLES['input_bg']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {COMMON_STYLES['input_focus']};
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
        QCheckBox::indicator:hover {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
        
        QLineEdit, QSpinBox, QDoubleSpinBox {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {text_color};
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(8)}px {get_scaled_size(10)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['input'])}px;
        }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
        
        QComboBox {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {text_color};
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(8)}px {get_scaled_size(10)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['input'])}px;
        }}
        QComboBox:focus {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
        QComboBox::drop-down {{
            border: none;
            width: {get_scaled_size(24)}px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {COMMON_STYLES['text_secondary']};
            margin-right: {get_scaled_size(5)}px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {text_color};
            border: 1px solid {COMMON_STYLES['input_border']};
            selection-background-color: {COMMON_STYLES['input_focus']};
            font-family: {FONT_FAMILY};
            outline: none;
        }}
        
        QPushButton {{
            background-color: {colors['header']};
            color: {text_color};
            border: none;
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['content'])}px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {_lighten_color(colors['header'], 0.15)};
        }}
        QPushButton:pressed {{
            background-color: {_lighten_color(colors['header'], -0.1)};
        }}
    """
    
    return base_style + children_style


def get_input_field_style() -> str:
    """
    ComfyUI 스타일의 입력 필드 스타일
    """
    return f"""
        QLineEdit, QSpinBox, QDoubleSpinBox {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {COMMON_STYLES['text_primary']};
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(8)}px {get_scaled_size(10)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['input'])}px;
        }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
        QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
            background-color: {get_block_style('default')['content']};
            color: {COMMON_STYLES['text_disabled']};
        }}
    """


def get_label_style() -> str:
    """
    레이블 스타일
    """
    return f"""
        QLabel {{
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            background: transparent;
        }}
    """


def get_combobox_style() -> str:
    """
    ComfyUI 스타일의 콤보박스
    """
    return f"""
        QComboBox {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {COMMON_STYLES['text_primary']};
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(8)}px {get_scaled_size(10)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['input'])}px;
        }}
        QComboBox:focus {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
        QComboBox::drop-down {{
            border: none;
            width: {get_scaled_size(24)}px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 6px solid {COMMON_STYLES['text_secondary']};
            margin-right: {get_scaled_size(5)}px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {COMMON_STYLES['text_primary']};
            border: 1px solid {COMMON_STYLES['input_border']};
            selection-background-color: {COMMON_STYLES['input_focus']};
            font-family: {FONT_FAMILY};
        }}
    """


def get_checkbox_style() -> str:
    """
    체크박스 스타일
    """
    return f"""
        QCheckBox {{
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['label'])}px;
            spacing: {get_scaled_size(8)}px;
        }}
        QCheckBox::indicator {{
            width: {get_scaled_size(18)}px;
            height: {get_scaled_size(18)}px;
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            background-color: {COMMON_STYLES['input_bg']};
        }}
        QCheckBox::indicator:checked {{
            background-color: {COMMON_STYLES['input_focus']};
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
        QCheckBox::indicator:hover {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
    """


def get_button_style(block_type: str = 'default', bg_color: str = None, text_color: str = None) -> str:
    """
    버튼 스타일
    """
    colors = get_block_style(block_type)
    
    background = bg_color if bg_color else colors['header']
    text = text_color if text_color else COMMON_STYLES['text_primary']

    return f"""
        QPushButton {{
            background-color: {background};
            color: {text};
            border: none;
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(8)}px {get_scaled_size(16)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['content'])}px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {_lighten_color(background, 0.15)};
        }}
        QPushButton:pressed {{
            background-color: {_lighten_color(background, -0.1)};
        }}
        QPushButton:disabled {{
            background-color: {get_block_style('default')['content']};
            color: {COMMON_STYLES['text_disabled']};
        }}
    """


def get_readonly_text_style() -> str:
    """
    수정 불가능한 텍스트 에디터 스타일 (미리보기용)

    Returns:
        QSS 스타일 문자열
    """
    return f"""
        QTextEdit {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {COMMON_STYLES['text_secondary']};
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            padding: {get_scaled_size(8)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['content'])}px;
        }}
        QTextEdit:focus {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
    """


def _lighten_color(hex_color: str, factor: float) -> str:
    """
    색상을 밝게 만드는 헬퍼 함수

    Args:
        hex_color: #RRGGBB 형식의 색상
        factor: 밝기 증가 계수 (0.0 ~ 1.0)

    Returns:
        밝아진 색상 문자열
    """
    # # 제거
    hex_color = hex_color.lstrip('#')

    # RGB 추출
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # 밝기 증가
    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))

    return f'#{r:02x}{g:02x}{b:02x}'


def get_slider_style() -> str:
    """
    슬라이더 스타일

    Returns:
        QSS 스타일 문자열
    """
    return f"""
        QSlider::groove:horizontal {{
            background: {COMMON_STYLES['input_bg']};
            height: {get_scaled_size(6)}px;
            border-radius: {get_scaled_size(3)}px;
        }}
        QSlider::handle:horizontal {{
            background: {COMMON_STYLES['input_focus']};
            width: {get_scaled_size(14)}px;
            height: {get_scaled_size(14)}px;
            margin: -{get_scaled_size(4)}px 0;
            border-radius: {get_scaled_size(7)}px;
        }}
        QSlider::handle:horizontal:hover {{
            background: {_lighten_color(COMMON_STYLES['input_focus'], 0.2)};
        }}
    """


def get_readonly_text_style() -> str:
    """읽기 전용 텍스트 에디트 스타일"""
    return f"""
        QTextEdit {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {COMMON_STYLES['text_secondary']};
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['content'])}px;
            padding: 8px;
        }}
    """


def get_input_text_style() -> str:
    """입력 가능한 텍스트 에디트 스타일"""
    return f"""
        QTextEdit {{
            background-color: {COMMON_STYLES['input_bg']};
            color: {COMMON_STYLES['text_primary']};
            border: 1px solid {COMMON_STYLES['input_border']};
            border-radius: {get_scaled_size(4)}px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(INTERACTIVE_FONTS['input'])}px;
            padding: 8px;
        }}
        QTextEdit:focus {{
            border: 1px solid {COMMON_STYLES['input_focus']};
        }}
    """
