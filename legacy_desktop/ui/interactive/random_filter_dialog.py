import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QCheckBox, QPushButton,
    QScrollArea, QWidget, QLabel, QGroupBox, QMessageBox, QGridLayout,
    QListWidget, QListWidgetItem, QTextEdit, QTextBrowser, QLineEdit,
    QSplitter, QStyle, QStyledItemDelegate, QFrame
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from legacy_desktop.ui.interactive.category_structure import CATEGORY_STRUCTURE, CATEGORY_NAMES_KR
from legacy_desktop.ui.interactive.interactive_theme import COMMON_STYLES, FONT_FAMILY
from legacy_desktop.ui.scaling_manager import get_scaled_size, get_scaled_font_size
from legacy_desktop.ui.theme import DARK_COLORS

CONFIG_FILE = Path("save/random_filter_config.json")


# ===== AutoHideGuideDialog =====

class AutoHideGuideDialog(QDialog):
    """Auto-Hide 패턴 가이드 다이얼로그"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-Hide 패턴 가이드")
        self.resize(get_scaled_size(800), get_scaled_size(600))
        self._init_ui()

    def _init_ui(self):
        # 다크 테마 적용 (밝은 배경)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(get_scaled_size(15))

        # 제목
        title_label = QLabel("Auto-Hide 패턴 가이드")
        title_label.setStyleSheet(f"""
            color: {DARK_COLORS['accent_blue']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(24)}px;
            font-weight: bold;
        """)
        layout.addWidget(title_label)

        # 설명
        desc_label = QLabel("Auto-Hide는 이미지 생성 전 프롬프트에서 매칭되는 태그를 제거합니다.")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_secondary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(16)}px;
            margin-bottom: {get_scaled_size(10)}px;
        """)
        layout.addWidget(desc_label)

        # 패턴 문법 테이블 (HTML)
        pattern_html = f"""
        <html>
        <head>
            <style>
                body {{
                    font-family: {FONT_FAMILY};
                    font-size: {get_scaled_font_size(16)}px;
                    color: {COMMON_STYLES['text_primary']};
                    background-color: {DARK_COLORS['bg_hover']};
                    padding: 10px;
                }}
                h3 {{
                    color: {DARK_COLORS['accent_blue']};
                    margin-top: 15px;
                    margin-bottom: 10px;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 10px;
                    margin-bottom: 20px;
                }}
                th, td {{
                    text-align: left;
                    padding: 8px;
                    border: 1px solid {COMMON_STYLES['input_border']};
                }}
                th {{
                    background-color: {DARK_COLORS['bg_pressed']};
                    color: {DARK_COLORS['accent_blue']};
                    font-weight: bold;
                }}
                td {{
                    background-color: {DARK_COLORS['bg_hover']};
                }}
                code {{
                    background-color: {DARK_COLORS['bg_pressed']};
                    color: #90EE90;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-family: 'Consolas', 'Courier New', monospace;
                }}
                .example {{
                    background-color: {DARK_COLORS['bg_pressed']};
                    padding: 10px;
                    border-radius: 5px;
                    margin-top: 10px;
                    font-size: {get_scaled_font_size(14)}px;
                    overflow-wrap: break-word;
                }}
            </style>
        </head>
        <body>
            <h3>패턴 문법:</h3>
            <table>
                <tr>
                    <th>패턴</th>
                    <th>동작</th>
                </tr>
                <tr>
                    <td><code>tag</code></td>
                    <td>정확히 일치하는 태그 제거</td>
                </tr>
                <tr>
                    <td><code>__pattern__</code></td>
                    <td>공백 무시하고 'pattern'을 포함하는 태그 제거 (예: <code>__background__</code> → white background 제거)</td>
                </tr>
                <tr>
                    <td><code>_pattern_</code></td>
                    <td>'pattern'을 포함하는 태그 제거 (예: <code>_hair_</code> → blonde hair 제거)</td>
                </tr>
                <tr>
                    <td><code>_pattern</code></td>
                    <td>'pattern'으로 끝나는 태그 제거 (예: <code>_logo</code> → bad logo 제거)</td>
                </tr>
                <tr>
                    <td><code>pattern_</code></td>
                    <td>'pattern'으로 시작하는 태그 제거 (예: <code>poke_</code> → pokemon 제거)</td>
                </tr>
                <tr>
                    <td><code>~keyword</code></td>
                    <td>보호 키워드 (제거에서 제외, 예: <code>~blurry background</code> → __background__ 패턴으로부터 보호)</td>
                </tr>
            </table>

            <h3>예제:</h3>
            <div class="example">
                [loli, child, minigirl, chibi, chibi inset, toddlercon, monochrome, doujin cover, bad source, __censor__, uncensored, bad id, _logo, bad twitter id, __background__, ~blurry background, character doll, stuffed animal, stuffed toy, speech bubble, cyclops, pov, 3d, glasses, mole, text focus, thought bubble, watermark, web address, body writing, fake screenshot, facing away, |_|, __piercing__, tattoo, _tattoo, _text, sound effects, greyscale, multiple views, peeing, rabbit, __censor__, pregnant, __chess__, trading card, __(medium)__, __theme__, child on child, covered clitoris, _gag, sketch, poke_, __pokemon__, recording, viewfinder, multiple boys, __measuring__, multiple views, big belly, curvy, doll joints, dark-skinned male, timestamp, battery indicator, tan, fake phone screenshot, stomach bulge, __beach__, __shower__, on table, huge penis, __bug__, giant insect, belly, eye mask, circle cut, dark nipples, signature, alternate race, alternate species, dark nipples, livestream, slap mark, x-ray, armpit hair, health bar, snapchat, facial mark, emoji, command spell, dark areolae, __piercing__, __bed__, __pillow__, __sheet__, body markings, obese, __long tongue__, __name__, handprint, __pasties__, mini person, __butt plug__, __eyepatch__, makeup, mascara, gigantic breasts, runny makeup, third eye, anal hair, __halo__]
            </div>
        </body>
        </html>
        """

        # QTextBrowser로 표시 (HTML 렌더링 지원)
        text_browser = QTextBrowser()
        text_browser.setHtml(pattern_html)
        text_browser.setOpenExternalLinks(False)
        text_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {DARK_COLORS['bg_hover']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
            }}
        """)
        layout.addWidget(text_browser, 1)  # stretch

        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setFixedHeight(get_scaled_size(35))
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(4)}px;
                padding: 8px 16px;
                font-family: {FONT_FAMILY};
                font-weight: bold;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_pressed']};
            }}
        """)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)


# ===== SimplifiedTagViewer (버튼 없음, 포커스 이탈 방지 없음) =====

class TagListDelegate(QStyledItemDelegate):
    """태그 리스트 커스텀 델리게이트 (우측 정렬 숫자 표시)"""
    def paint(self, painter, option, index):
        painter.save()

        # 폰트 설정
        painter.setFont(option.font)

        # 1. 배경 그리기
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(COMMON_STYLES['input_focus']))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor("#3A3A3A"))

        rect = option.rect
        tag = index.data(Qt.ItemDataRole.UserRole)
        count_text = index.data(Qt.ItemDataRole.UserRole + 2)

        # 2. 텍스트 색상 설정
        if option.state & QStyle.StateFlag.State_Selected:
            text_color = QColor(Qt.GlobalColor.white)
            count_color = QColor(Qt.GlobalColor.white)
        else:
            text_color = QColor(COMMON_STYLES['text_primary'])
            count_color = QColor(COMMON_STYLES['text_secondary'])

        # 3. 태그 그리기 (좌측 정렬)
        painter.setPen(text_color)
        tag_rect = rect.adjusted(get_scaled_size(5), 0, -get_scaled_size(60), 0)
        text = painter.fontMetrics().elidedText(tag, Qt.TextElideMode.ElideRight, tag_rect.width())
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        # 4. 숫자 그리기 (우측 정렬)
        if count_text:
            painter.setPen(count_color)
            count_rect = rect.adjusted(0, 0, -get_scaled_size(5), 0)
            painter.drawText(count_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, count_text)

        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(get_scaled_size(24))
        return size


class SimplifiedTagViewer(QWidget):
    """
    간소화된 태그 뷰어 (RandomFilterDialog 오른쪽 패널용)

    - 버튼 제거 (프롬프트 삽입, 퀵 서치, 복사 버튼 없음)
    - 포커스 이탈 닫기 제거
    - 일반 QWidget으로 표시
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.all_tags_data = {}  # tag -> tag_data
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self._perform_search)

        self._init_ui()

    def _init_ui(self):
        """UI 초기화"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 3단 리스트 (대분류 | 소분류 | 태그) ===
        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(0)

        self.group_list = self._create_list_widget()
        lists_layout.addWidget(self.group_list, 2)

        self.subgroup_list = self._create_list_widget()
        lists_layout.addWidget(self.subgroup_list, 2)

        self.tag_list = self._create_list_widget()
        self.tag_list.setItemDelegate(TagListDelegate(self.tag_list))
        lists_layout.addWidget(self.tag_list, 3)

        main_layout.addLayout(lists_layout, 3)

        # === 검색 바 ===
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("검색...")
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(15)}px;
            }}
        """)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        main_layout.addWidget(self.search_input)

        # === 설명 영역 ===
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_hover']};
                color: #FFFFFF;
                border: 1px solid {COMMON_STYLES['input_border']};
                padding: {get_scaled_size(8)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(17)}px;
            }}
        """)
        main_layout.addWidget(self.info_text, 1)

        # 시그널 연결
        self.group_list.currentItemChanged.connect(self._on_group_changed)
        self.subgroup_list.currentItemChanged.connect(self._on_subgroup_changed)
        self.tag_list.itemClicked.connect(self._on_tag_clicked)

    def _create_list_widget(self) -> QListWidget:
        """리스트 위젯 생성"""
        list_widget = QListWidget()
        list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(18)}px;
                padding: {get_scaled_size(4)}px;
            }}
            QListWidget::item {{
                padding: {get_scaled_size(5)}px;
                border-radius: {get_scaled_size(4)}px;
            }}
            QListWidget::item:hover {{
                background-color: #3A3A3A;
            }}
            QListWidget::item:selected {{
                background-color: {COMMON_STYLES['input_focus']};
                color: white;
            }}
        """)
        return list_widget

    def set_tags_data(self, tags_data: dict):
        """태그 데이터 설정"""
        self.all_tags_data = tags_data
        self._populate_groups()

    def _populate_groups(self):
        """대분류 목록 채우기"""
        self.group_list.clear()

        groups = set()
        for tag_data in self.all_tags_data.values():
            group = tag_data.get("group", "")
            if group:
                groups.add(group)

        group_kr_map = {
            "Clothing_Wear": "의상/착용",
            "Person_Body": "인체/신체",
            "Food_Object": "음식/사물",
            "Composition_Meta": "구도/메타",
            "Expression_Action": "표정/행동",
            "Creatures": "생물/종족",
            "Location_Background": "장소/배경",
            "NSFW": "NSFW",
            "Culture_Misc": "문화/기타"
        }

        for group in sorted(groups):
            group_kr = group_kr_map.get(group, group)
            item = QListWidgetItem(group_kr)
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.group_list.addItem(item)

    def _on_group_changed(self, current, previous):
        """대분류 선택 변경"""
        if not current:
            return

        selected_group = current.data(Qt.ItemDataRole.UserRole)

        self.subgroup_list.clear()
        subgroups = set()

        for tag_data in self.all_tags_data.values():
            if tag_data.get("group") == selected_group:
                subgroup = tag_data.get("subgroup", "")
                if subgroup:
                    subgroups.add(subgroup)

        for subgroup in sorted(subgroups):
            item = QListWidgetItem(subgroup)
            self.subgroup_list.addItem(item)

    def _on_subgroup_changed(self, current, previous):
        """소분류 선택 변경"""
        if not current:
            return

        group_item = self.group_list.currentItem()
        if not group_item:
            return

        selected_group = group_item.data(Qt.ItemDataRole.UserRole)
        selected_subgroup = current.text()

        self.tag_list.clear()
        filtered_tags = []

        for tag, tag_data in self.all_tags_data.items():
            if (tag_data.get("group") == selected_group and
                tag_data.get("subgroup") == selected_subgroup):
                filtered_tags.append((tag, tag_data))

        filtered_tags.sort(key=lambda x: x[1].get("freq", 0), reverse=True)

        for tag, tag_data in filtered_tags:
            count = tag_data.get("freq", 0)

            if count >= 1000000:
                count_text = f"{count/1000000:.1f}M"
            elif count >= 1000:
                count_text = f"{count/1000:.0f}k"
            else:
                count_text = str(count)

            item = QListWidgetItem(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag_data)
            item.setData(Qt.ItemDataRole.UserRole + 2, count_text)

            self.tag_list.addItem(item)

    def _on_search_text_changed(self, text):
        """검색어 변경 시 타이머 재설정"""
        self.search_timer.start()

    def _perform_search(self):
        """실제 검색 수행"""
        text = self.search_input.text().strip().lower()

        if not text:
            current_sub_item = self.subgroup_list.currentItem()
            if current_sub_item:
                self._on_subgroup_changed(current_sub_item, None)
            else:
                self.tag_list.clear()
            return

        self.tag_list.clear()
        matched_tags = []

        for tag, tag_data in self.all_tags_data.items():
            if text in tag.lower():
                matched_tags.append((tag, tag_data))
                continue

            keywords_kr = tag_data.get("keywords_kr", "")
            if keywords_kr and text in keywords_kr:
                matched_tags.append((tag, tag_data))
                continue

        matched_tags.sort(key=lambda x: x[1].get("freq", 0), reverse=True)

        for tag, tag_data in matched_tags:
            count = tag_data.get("freq", 0)

            if count >= 1000000:
                count_text = f"{count/1000000:.1f}M"
            elif count >= 1000:
                count_text = f"{count/1000:.0f}k"
            else:
                count_text = str(count)

            item = QListWidgetItem(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag_data)
            item.setData(Qt.ItemDataRole.UserRole + 2, count_text)

            self.tag_list.addItem(item)

        self.group_list.clearSelection()
        self.subgroup_list.clearSelection()

    def _on_tag_clicked(self, item):
        """태그 클릭 시 미리보기 업데이트"""
        if not item:
            return

        tag_data = item.data(Qt.ItemDataRole.UserRole + 1)

        info_parts = []

        description = tag_data.get("description", "")
        if description:
            info_parts.append(f"\n📝 설명:\n{description}")

        keywords_kr = tag_data.get("keywords_kr", "")
        if keywords_kr:
            info_parts.append(f"\n🔍 키워드: {keywords_kr}")

        self.info_text.setPlainText("\n".join(info_parts))

class RandomFilterDialog(QDialog):
    def __init__(self, parent=None, tags_data=None):
        super().__init__(parent)
        self.setWindowTitle("랜덤 프롬프트 고급 필터링")
        self.resize(get_scaled_size(1200), get_scaled_size(700))  # 너비 증가
        self.config = self.load_config()
        self.tags_data = tags_data or {}  # 태그 데이터 (InteractiveAutocompleteManager에서 전달)
        self._init_ui()
        
    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Config load failed: {e}")
        return {} # 기본값은 모두 True (로드되지 않으면)

    def save_config(self):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 현재 UI 상태 읽기
        new_config = {}
        for key, checkbox in self.checkboxes.items():
            new_config[key] = checkbox.isChecked()

        # 🆕 Auto-Hide 패턴 저장 (QTextEdit)
        new_config["autohide_patterns"] = self.autohide_input.toPlainText().strip()

        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(new_config, f, indent=4)
        except Exception as e:
            QMessageBox.warning(self, "저장 실패", str(e))
            
    def _init_ui(self):
        # ID 설정 (스타일 우선순위 확보용)
        self.setObjectName("RandomFilterDialog")
        
        # 다크 테마 적용
        self.setStyleSheet(f"""
            #RandomFilterDialog {{
                background-color: #1C1C1C;
                color: {DARK_COLORS['text_primary']};
            }}
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QWidget {{
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: {DARK_COLORS['bg_secondary']};
                width: 12px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {DARK_COLORS['border']};
                min-height: 20px;
                border-radius: 6px;
            }}
        """)

        main_layout = QVBoxLayout(self)

        # 설명
        label = QLabel("체크 해제된 카테고리의 태그는 랜덤 프롬프트 생성 시 제외됩니다.")
        label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_secondary']};
            margin-bottom: 10px;
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(18)}px;
        """)
        label.setWordWrap(True)
        main_layout.addWidget(label)

        # === 좌우 분할 레이아웃 ===
        horizontal_layout = QHBoxLayout()

        # === 좌측: 필터 설정 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setSpacing(20)

        self.checkboxes = {} # "Group:Subgroup" -> QCheckBox
        self.group_checkboxes = {} # "Group" -> QCheckBox (전체선택용)

        for group, subgroups in CATEGORY_STRUCTURE.items():
            group_kr = CATEGORY_NAMES_KR.get(group, group)

            # === 테두리 없는 프레임 구성 ===
            group_frame = QWidget()
            group_frame.setStyleSheet("background-color: transparent;")
            frame_layout = QVBoxLayout(group_frame)
            frame_layout.setContentsMargins(0, 5, 0, 10)
            frame_layout.setSpacing(8)

            # 헤더 체크박스 (전체 ON/OFF)
            header_chk = QCheckBox(f"{group_kr} ({group})")
            # 초기 상태는 소분류 로드 후 결정됨 (아래에서 _update_header_state 호출)
            header_chk.setStyleSheet(f"""
                QCheckBox {{
                    color: {DARK_COLORS['accent_blue']};
                    font-weight: bold;
                    font-family: {FONT_FAMILY};
                    font-size: {get_scaled_font_size(20)}px;
                }}
            """)
            self.group_checkboxes[group] = header_chk
            frame_layout.addWidget(header_chk)

            # 소분류 컨테이너 (GridLayout)
            subgroup_widget = QWidget()
            gb_layout = QGridLayout(subgroup_widget)
            gb_layout.setContentsMargins(10, 0, 0, 0)  # 좌측 들여쓰기 (20 → 10)

            # 소분류 체크박스 생성
            subgroup_chks = []
            visible_idx = 0  # 실제 UI에 표시되는 인덱스
            for subgroup in sorted(subgroups):
                key = f"{group}:{subgroup}"

                # 🆕 Composition_Meta:count는 UI에 표시하지 않음 (항상 활성화 상태로 유지)
                if group == "Composition_Meta" and subgroup == "count":
                    continue

                chk = QCheckBox(subgroup)
                chk.setChecked(self.config.get(key, True)) # 기본 True
                chk.setStyleSheet(f"""
                    color: {COMMON_STYLES['text_primary']};
                    font-family: {FONT_FAMILY};
                    font-size: {get_scaled_font_size(18)}px;
                """)
                self.checkboxes[key] = chk
                subgroup_chks.append(chk)

                # 2열 배치
                row = visible_idx // 2
                col = visible_idx % 2
                gb_layout.addWidget(chk, row, col)
                visible_idx += 1

            frame_layout.addWidget(subgroup_widget)

            # 🆕 헤더 체크박스 초기 상태 설정 (소분류 상태 기반)
            self._update_header_state(header_chk, subgroup_chks)

            # 헤더 체크박스 시그널 연결 (전체 선택/해제)
            header_chk.toggled.connect(
                lambda checked, chks=subgroup_chks: self._toggle_all_subgroups(checked, chks)
            )

            # 소분류 체크박스 시그널 연결 (헤더 체크박스 상태 업데이트)
            for chk in subgroup_chks:
                chk.toggled.connect(
                    lambda _, header=header_chk, chks=subgroup_chks: self._update_header_state(header, chks)
                )

            self.content_layout.addWidget(group_frame)

            # 구분선 추가 (마지막 그룹 제외)
            if group != list(CATEGORY_STRUCTURE.keys())[-1]:
                separator = QFrame()
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFrameShadow(QFrame.Shadow.Sunken)
                separator.setStyleSheet(f"background-color: {COMMON_STYLES['input_border']};")
                separator.setFixedHeight(1)
                self.content_layout.addWidget(separator)

        self.content_layout.addStretch()
        scroll.setWidget(content_widget)
        left_layout.addWidget(scroll)

        horizontal_layout.addWidget(left_widget, 1)  # 좌측 (비율 1)

        # === 우측: SimplifiedTagViewer ===
        self.tag_viewer = SimplifiedTagViewer()
        if self.tags_data:
            self.tag_viewer.set_tags_data(self.tags_data)
        horizontal_layout.addWidget(self.tag_viewer, 1)  # 우측 (비율 1)

        main_layout.addLayout(horizontal_layout)

        # === 하단: Auto-Hide 입력 영역 ===
        autohide_section = QVBoxLayout()
        autohide_section.setSpacing(get_scaled_size(8))

        # 상단 라인 (라벨 + 가이드 버튼)
        autohide_header = QHBoxLayout()
        autohide_header.setSpacing(get_scaled_size(8))

        # Auto-Hide 라벨
        autohide_label = QLabel("Auto-Hide 패턴:")
        autohide_label.setStyleSheet(f"""
            color: {COMMON_STYLES['text_primary']};
            font-family: {FONT_FAMILY};
            font-size: {get_scaled_font_size(16)}px;
            font-weight: bold;
        """)
        autohide_header.addWidget(autohide_label)

        # 가이드 버튼
        btn_guide = QPushButton("📖 가이드")
        btn_guide.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_guide.setFixedHeight(get_scaled_size(28))
        btn_guide.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                padding: 4px 12px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(14)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_pressed']};
                border: 1px solid {COMMON_STYLES['input_focus']};
            }}
        """)
        btn_guide.clicked.connect(self._on_guide_clicked)
        autohide_header.addWidget(btn_guide)

        autohide_header.addStretch()
        autohide_section.addLayout(autohide_header)

        # Auto-Hide 입력 필드 (QTextEdit, 4배 높이)
        self.autohide_input = QTextEdit()
        self.autohide_input.setPlaceholderText("예: _hair_, blonde hair, ~silver hair (쉼표로 구분)")
        self.autohide_input.setPlainText(self.config.get("autohide_patterns", ""))  # 저장된 값 로드
        self.autohide_input.setFixedHeight(get_scaled_size(100))  # 4배 높이
        self.autohide_input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {DARK_COLORS['bg_hover']};
                color: {COMMON_STYLES['text_primary']};
                border: 1px solid {COMMON_STYLES['input_border']};
                border-radius: {get_scaled_size(4)}px;
                padding: {get_scaled_size(6)}px;
                font-family: {FONT_FAMILY};
                font-size: {get_scaled_font_size(15)}px;
            }}
            QTextEdit:focus {{
                border: 1px solid {COMMON_STYLES['input_focus']};
            }}
        """)
        autohide_section.addWidget(self.autohide_input)

        main_layout.addLayout(autohide_section)

        # === 하단 버튼 라인 ===
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(get_scaled_size(10))

        # Stretch (왼쪽 여백)
        bottom_layout.addStretch()

        # 저장 버튼
        btn_save = QPushButton("설정 저장")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_button(btn_save, is_primary=True)
        btn_save.clicked.connect(self.accept) # accept 시 save 호출
        bottom_layout.addWidget(btn_save)

        # 취소 버튼
        btn_close = QPushButton("취소")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_button(btn_close, is_primary=False)
        btn_close.clicked.connect(self.reject)
        bottom_layout.addWidget(btn_close)

        main_layout.addLayout(bottom_layout)

    def _style_button(self, btn, is_primary=False):
        bg_color = DARK_COLORS['accent_blue'] if is_primary else DARK_COLORS['bg_hover']
        text_color = "white" if is_primary else DARK_COLORS['text_primary']
        border = "none" if is_primary else f"1px solid {DARK_COLORS['border']}"

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: {text_color};
                border: {border};
                border-radius: {get_scaled_size(4)}px;
                padding: 8px 16px;
                font-family: {FONT_FAMILY};
                font-weight: bold;
                font-size: {get_scaled_font_size(16)}px;
            }}
            QPushButton:hover {{
                background-color: {DARK_COLORS['bg_pressed'] if not is_primary else DARK_COLORS['accent_blue_hover']};
            }}
        """)

    def _toggle_all_subgroups(self, checked, subgroup_chks):
        """
        헤더 체크박스 토글 시 모든 소분류 체크박스 일괄 변경

        Args:
            checked: 헤더 체크박스 상태
            subgroup_chks: 소분류 체크박스 리스트
        """
        for chk in subgroup_chks:
            chk.setChecked(checked)

    def _update_header_state(self, header_chk, subgroup_chks):
        """
        소분류 체크박스 상태 변경 시 헤더 체크박스 상태 업데이트

        Args:
            header_chk: 헤더 체크박스
            subgroup_chks: 소분류 체크박스 리스트
        """
        # 모든 소분류가 체크되어 있으면 헤더도 체크
        all_checked = all(chk.isChecked() for chk in subgroup_chks)
        any_checked = any(chk.isChecked() for chk in subgroup_chks)

        # 시그널 블로킹하여 무한 루프 방지
        header_chk.blockSignals(True)
        if all_checked:
            header_chk.setChecked(True)
            header_chk.setTristate(False)
        elif any_checked:
            # 일부만 체크된 경우 (partial state)
            header_chk.setTristate(True)
            header_chk.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            header_chk.setChecked(False)
            header_chk.setTristate(False)
        header_chk.blockSignals(False)

    def get_config(self):
        """현재 체크박스 상태를 딕셔너리로 반환"""
        config = {}
        for key, checkbox in self.checkboxes.items():
            config[key] = checkbox.isChecked()

        # 🆕 Composition_Meta:count는 항상 True로 저장 (호환성 유지)
        config["Composition_Meta:count"] = True

        # 🆕 Auto-Hide 패턴 추가 (QTextEdit)
        config["autohide_patterns"] = self.autohide_input.toPlainText().strip()

        return config

    def _on_guide_clicked(self):
        """가이드 버튼 클릭 핸들러.
        TODO(web-dialog): 원래 AutoHideGuideDialog.exec() — Web Shell 패널로 재구현 필요."""
        print("[Dialog/SKIPPED] AutoHideGuideDialog 차단 — Web Shell 재구현 예정")

    def accept(self):
        self.save_config()
        super().accept()
