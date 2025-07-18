# 개선된 어두운 테마 색상 팔레트
DARK_COLORS = {
    'bg_primary': '#212121',      # 메인 배경 (매우 어두운 회색)
    'bg_secondary': '#2B2B2B',    # 서브 배경
    'bg_tertiary': '#2B2B2B',     # 카드/위젯 배경
    'bg_hover': '#404040',        # 호버 상태
    'bg_pressed': '#4A4A4A',      # 눌린 상태
    'text_primary': '#FFFFFF',    # 주요 텍스트 (흰색)
    'text_secondary': '#B0B0B0',  # 보조 텍스트 (회색)
    'text_disabled': '#666666',   # 비활성 텍스트
    'accent_blue': '#1976D2',     # 강조 파란색
    'accent_blue_hover': '#1565C0',
    'accent_blue_light': '#42A5F5',
    'border': '#333333',          # 경계선
    'border_light': '#666666',    # 밝은 경계선
    'success': '#4CAF50',         # 성공 색상
    'warning': '#FF9800',         # 경고 색상
    'error': '#F44336',           # 오류 색상
}

# 어두운 테마 스타일시트
DARK_STYLES = {
    'main_container': f"""
        QWidget {{
            background-color: {DARK_COLORS['bg_primary']};
            color: {DARK_COLORS['text_primary']};
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-size: 21px;
            font-weight: 400;
        }}
    """,
    
    'collapsible_box': f"""
        QWidget {{
            background-color: {DARK_COLORS['bg_tertiary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 6px;
            margin: 2px 4px;
        }}
        QToolButton {{
            background-color: transparent;
            border: none;
            border-radius: 4px;
            padding: 8px 12px;
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-weight: 600;
            font-size: 21px;
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
            border-radius: 4px;
            padding: 8px;
            margin: 2px 4px;
        }}
    """,
    
    'primary_button': f"""
        QPushButton {{
            background-color: {DARK_COLORS['accent_blue']};
            border: none;
            border-radius: 4px;
            padding: 10px 20px;
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-weight: 600;
            color: {DARK_COLORS['text_primary']};
            font-size: 21px;
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
            border-radius: 4px;
            padding: 8px 16px;
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-weight: 500;
            color: {DARK_COLORS['text_primary']};
            font-size: 20px;
        }}
        QPushButton:hover {{
            background-color: {DARK_COLORS['bg_hover']};
            border: 1px solid {DARK_COLORS['border_light']};
        }}
        QPushButton:pressed {{
            background-color: {DARK_COLORS['bg_pressed']};
        }}
    """,
    
    'compact_textedit': f"""
        QTextEdit {{
            background-color: {DARK_COLORS['bg_secondary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px;
            padding: 8px;
            color: {DARK_COLORS['text_primary']};
            selection-background-color: {DARK_COLORS['accent_blue']};
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-size: 22px;
        }}
        QTextEdit:focus {{
            border: 2px solid {DARK_COLORS['accent_blue']};
        }}
    """,
    
    'compact_lineedit': f"""
        QLineEdit {{
            background-color: {DARK_COLORS['bg_secondary']};
            border: 1px solid {DARK_COLORS['border']};
            border-radius: 4px;
            padding: 8px 12px;
            color: {DARK_COLORS['text_primary']};
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-size: 19px;
        }}
        QLineEdit:focus {{
            border: 2px solid {DARK_COLORS['accent_blue']};
        }}
    """,
    
    'dark_checkbox': f"""
        QCheckBox {{
            background-color: transparent;
            spacing: 8px;
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-size: 19px;
            color: {DARK_COLORS['text_primary']};
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
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
            border-radius: 4px;
            background-color: {DARK_COLORS['bg_tertiary']};
            margin-top: 2px;
        }}
        QTabBar::tab {{
            background-color: {DARK_COLORS['bg_secondary']};
            border: 1px solid {DARK_COLORS['border']};
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            padding: 8px 16px;
            margin-right: 1px;
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-weight: 500;
            color: {DARK_COLORS['text_secondary']};
            font-size: 19px;
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
            border-radius: 4px;
            padding: 6px 12px;
            color: {DARK_COLORS['text_primary']};
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-size: 19px;
        }}
        QComboBox:hover {{
            border: 1px solid {DARK_COLORS['border_light']};
        }}
        QComboBox::drop-down {{
            border: none;
        }}
        QComboBox::down-arrow {{
            width: 10px;
            height: 10px;
        }}
    """,
    
    'label_style': f"""
        QLabel {{
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            color: {DARK_COLORS['text_primary']};
            font-size: 19px;
        }}
    """,
    
    # 새로 추가: 투명 배경 스타일
    'transparent_frame': f"""
        QFrame {{
            background-color: transparent;
            border: none;
        }}
    """,
    
    # 새로 추가: 확장 토글 버튼 스타일
    'expand_toggle_button': f"""
        QPushButton {{
            background-color: {DARK_COLORS['accent_blue']};
            border: none;
            border-radius: 4px;
            padding: 8px 16px;
            font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-weight: 600;
            color: {DARK_COLORS['text_primary']};
            font-size: 16px;
        }}
        QPushButton:hover {{
            background-color: {DARK_COLORS['accent_blue_hover']};
        }}
        QPushButton:pressed {{
            background-color: #0D47A1;
        }}
    """,
}

CUSTOM = {
    "middle_scroll_area" : f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_secondary']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['border_light']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['accent_blue_light']};
            }}
        """,
    "main" : f"""
            QMainWindow {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard';
            }}
        """,
    "top_scroll_area" : f"""
            QScrollArea {{
                background-color: {DARK_COLORS['bg_primary']};
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {DARK_COLORS['bg_secondary']};
                width: 8px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {DARK_COLORS['border_light']};
                border-radius: 4px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {DARK_COLORS['accent_blue_light']};
            }}
        """,
    "toggle_active_style" : f"""
            QPushButton {{
                background-color: {DARK_COLORS['accent_blue']};
                border: none;
                border-radius: 4px;
                color: {DARK_COLORS['text_primary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 600;
                font-size: 18px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['accent_blue_hover']};
            }}
        """,
    "toggle_inactive_style" : f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: 4px;
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-weight: 500;
                font-size: 18px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """,
    "status_bar" : f"""
            QStatusBar {{
                background-color: {DARK_COLORS['bg_secondary']};
                border-top: 1px solid {DARK_COLORS['border']};
                color: {DARK_COLORS['text_secondary']};
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: 18px;
            }}
        """,
    "main_splitter" : f"""
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
    "params_title" : f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                color: {DARK_COLORS['text_primary']};
                font-size: 21px;
                font-weight: 600;
                margin-bottom: 8px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """,
    "param_label_style" : f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                color: {DARK_COLORS['text_primary']};
                font-size: 19px;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """,
    "naid_options_label" : f"""
            QLabel {{
                font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                color: {DARK_COLORS['text_primary']};
                font-size: 19px;
                font-weight: 500;
                background-color: {DARK_COLORS['bg_primary']};
            }}
        """
}