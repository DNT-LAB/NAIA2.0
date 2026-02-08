# ui/wildcard_simulator_dialog.py

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QGroupBox, QWidget, QHeaderView,
    QApplication, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QColor
from ui.theme import DARK_COLORS, get_dynamic_styles
from ui.scaling_manager import get_scaled_font_size, get_scaled_size
from ui.modern_menu import setModernStyle
from core.wildcard_analyzer import WildcardAnalyzer, WildcardInfo
from core.wildcard_processor import WildcardProcessor
from core.prompt_context import PromptContext
import pandas as pd
from typing import List, Dict


class WildcardSimulatorDialog(QDialog):
    """
    순차/종속 와일드카드 시뮬레이터 다이얼로그
    프롬프트를 입력받아 N번 시뮬레이션하고 결과를 표시합니다.
    """

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app_context = app_context
        self.wildcard_manager = app_context.wildcard_manager
        self.analyzer = WildcardAnalyzer(self.wildcard_manager)
        self.processor = WildcardProcessor(self.wildcard_manager)

        # 시뮬레이션 결과 저장
        self.simulation_results: List[Dict] = []
        self.current_wildcards: List[WildcardInfo] = []
        self.current_context: PromptContext = None

        self.init_ui()

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle("🎲 순차/종속 와일드카드 시뮬레이터")
        self.setGeometry(100, 100, get_scaled_size(1400), get_scaled_size(900))

        # 다크 테마 적용
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_COLORS['bg_primary']};
                color: {DARK_COLORS['text_primary']};
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(get_scaled_size(10))
        main_layout.setContentsMargins(
            get_scaled_size(15), get_scaled_size(15),
            get_scaled_size(15), get_scaled_size(15)
        )

        dynamic_styles = get_dynamic_styles()

        # === 1. 프롬프트 입력 섹션 ===
        prompt_group = QGroupBox("📝 프롬프트")
        prompt_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(25)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)
        prompt_layout = QVBoxLayout(prompt_group)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setStyleSheet(dynamic_styles['compact_textedit'])
        self.prompt_edit.setFixedHeight(get_scaled_size(80))
        self.prompt_edit.setPlaceholderText("예: 1girl, __*pose__, __$pose:expression__, __$expression:detail__")
        self.prompt_edit.setProperty("autocomplete_ignore", True)
        setModernStyle(self.prompt_edit)
        prompt_layout.addWidget(self.prompt_edit)

        # 분석 버튼
        analyze_btn = QPushButton("🔍 분석하기")
        analyze_btn.setStyleSheet(dynamic_styles['primary_button'])
        analyze_btn.setFixedHeight(get_scaled_font_size(32))
        analyze_btn.clicked.connect(self.analyze_prompt)
        prompt_layout.addWidget(analyze_btn)

        main_layout.addWidget(prompt_group)

        # === 2. 분석 결과 섹션 ===
        analysis_group = QGroupBox("⚙️ 순차/종속 와일드카드 분석")
        analysis_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(25)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)
        analysis_layout = QVBoxLayout(analysis_group)

        self.analysis_text = QTextEdit()
        self.analysis_text.setStyleSheet(dynamic_styles['compact_textedit'])
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setFixedHeight(get_scaled_size(180))
        self.analysis_text.setPlaceholderText("프롬프트를 입력하고 '분석하기'를 클릭하세요")
        setModernStyle(self.analysis_text)
        analysis_layout.addWidget(self.analysis_text)

        main_layout.addWidget(analysis_group)

        # === 3. 시뮬레이션 버튼 섹션 ===
        sim_btn_layout = QHBoxLayout()
        sim_btn_layout.setSpacing(get_scaled_size(10))

        self.sim_10_btn = QPushButton("10번 시뮬레이션")
        self.sim_10_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.sim_10_btn.setFixedHeight(get_scaled_font_size(32))
        self.sim_10_btn.setEnabled(False)
        self.sim_10_btn.clicked.connect(lambda: self.run_simulation(10))
        sim_btn_layout.addWidget(self.sim_10_btn)

        self.sim_100_btn = QPushButton("100번 시뮬레이션")
        self.sim_100_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.sim_100_btn.setFixedHeight(get_scaled_font_size(32))
        self.sim_100_btn.setEnabled(False)
        self.sim_100_btn.clicked.connect(lambda: self.run_simulation(100))
        sim_btn_layout.addWidget(self.sim_100_btn)

        self.sim_1000_btn = QPushButton("1000번 시뮬레이션")
        self.sim_1000_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.sim_1000_btn.setFixedHeight(get_scaled_font_size(32))
        self.sim_1000_btn.setEnabled(False)
        self.sim_1000_btn.clicked.connect(lambda: self.run_simulation(1000))
        sim_btn_layout.addWidget(self.sim_1000_btn)

        self.reset_sim_btn = QPushButton("🔄 리셋 후 시뮬레이션")
        self.reset_sim_btn.setStyleSheet(dynamic_styles['secondary_button'])
        self.reset_sim_btn.setFixedHeight(get_scaled_font_size(32))
        self.reset_sim_btn.setEnabled(False)
        self.reset_sim_btn.clicked.connect(self.reset_and_simulate)
        sim_btn_layout.addWidget(self.reset_sim_btn)

        sim_btn_layout.addStretch()

        main_layout.addLayout(sim_btn_layout)

        # === 4. 시뮬레이션 결과 테이블 ===
        result_group = QGroupBox("📊 시뮬레이션 결과")
        result_group.setStyleSheet(f"""
            QGroupBox {{
                font-size: {get_scaled_font_size(18)}px;
                font-weight: bold;
                color: {DARK_COLORS['text_primary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                padding-top: {get_scaled_size(25)}px;
                margin-top: {get_scaled_size(10)}px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {get_scaled_size(10)}px;
                padding: 0 {get_scaled_size(5)}px;
            }}
        """)
        result_layout = QVBoxLayout(result_group)

        self.result_table = QTableWidget()
        self.result_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {DARK_COLORS['bg_tertiary']};
                border: 1px solid {DARK_COLORS['border']};
                border-radius: {get_scaled_size(5)}px;
                font-size: {get_scaled_font_size(16)}px;
                color: {DARK_COLORS['text_primary']};
                gridline-color: {DARK_COLORS['border']};
            }}
            QTableWidget::item {{
                padding: {get_scaled_size(4)}px;
            }}
            QTableWidget::item:selected {{
                background-color: {DARK_COLORS['accent_blue']};
            }}
            QHeaderView::section {{
                background-color: {DARK_COLORS['bg_secondary']};
                color: {DARK_COLORS['text_primary']};
                padding: {get_scaled_size(6)}px;
                border: 1px solid {DARK_COLORS['border']};
                font-weight: bold;
                font-size: {get_scaled_font_size(16)}px;
            }}
        """)
        result_layout.addWidget(self.result_table)

        main_layout.addWidget(result_group)

        # === 5. 하단 버튼 섹션 ===
        bottom_btn_layout = QHBoxLayout()
        bottom_btn_layout.setSpacing(get_scaled_size(10))

        self.copy_btn = QPushButton("📋 결과 복사")
        self.copy_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.copy_btn.setFixedHeight(get_scaled_font_size(32))
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self.copy_results)
        bottom_btn_layout.addWidget(self.copy_btn)

        self.save_csv_btn = QPushButton("💾 CSV 저장")
        self.save_csv_btn.setStyleSheet(dynamic_styles['compact_button'])
        self.save_csv_btn.setFixedHeight(get_scaled_font_size(32))
        self.save_csv_btn.setEnabled(False)
        self.save_csv_btn.clicked.connect(self.save_csv)
        bottom_btn_layout.addWidget(self.save_csv_btn)

        bottom_btn_layout.addStretch()

        close_btn = QPushButton("❌ 닫기")
        close_btn.setStyleSheet(dynamic_styles['secondary_button'])
        close_btn.setFixedHeight(get_scaled_font_size(32))
        close_btn.clicked.connect(self.close)
        bottom_btn_layout.addWidget(close_btn)

        main_layout.addLayout(bottom_btn_layout)

    def analyze_prompt(self):
        """프롬프트 분석"""
        prompt = self.prompt_edit.toPlainText().strip()

        if not prompt:
            QMessageBox.warning(self, "경고", "프롬프트를 입력하세요.")
            return

        # 분석 실행
        wildcards, total_combinations, advance_rates = self.analyzer.analyze(prompt)

        if not wildcards:
            self.analysis_text.setText("⚠️ 순차 또는 종속 와일드카드가 없습니다.\n\n사용법:\n- 순차: __*wildcard__\n- 종속: __$master:slave__")
            self.disable_simulation_buttons()
            return

        # 결과 저장
        self.current_wildcards = wildcards

        # 분석 결과 텍스트 생성
        result_text = ""

        for wc in wildcards:
            if wc.master_name:
                # 종속 와일드카드
                master_count = self.analyzer._get_wildcard_count(wc.master_name)
                result_text += f"✓ {wc.name} ({wc.item_count}개 항목) [{wc.master_name}에 종속]\n"
                result_text += f"   → {wc.master_name} {master_count}번 완료 시 1번 전진\n"
                result_text += f"   → 매 {self.analyzer.format_number(wc.advance_rate)}번 생성마다 1번 전진\n\n"
            else:
                # 독립 순차 와일드카드
                result_text += f"✓ {wc.name} ({wc.item_count}개 항목)\n"
                result_text += f"   → 매 {wc.advance_rate}번 생성마다 1번 전진\n\n"

        # 전체 조합 수 및 경고
        result_text += f"📊 전체 조합 경우의 수: {self.analyzer.format_number(total_combinations)}가지\n"
        result_text += f"⏱️ 마지막 항목을 보려면: {self.analyzer.format_number(total_combinations)}번 생성\n\n"

        # 경고 메시지
        color, warning = self.analyzer.get_warning_level(total_combinations)
        result_text += f"{warning}"

        self.analysis_text.setText(result_text)

        # 시뮬레이션 버튼 활성화
        self.enable_simulation_buttons()

    def enable_simulation_buttons(self):
        """시뮬레이션 버튼 활성화"""
        self.sim_10_btn.setEnabled(True)
        self.sim_100_btn.setEnabled(True)
        self.sim_1000_btn.setEnabled(True)
        self.reset_sim_btn.setEnabled(True)

    def disable_simulation_buttons(self):
        """시뮬레이션 버튼 비활성화"""
        self.sim_10_btn.setEnabled(False)
        self.sim_100_btn.setEnabled(False)
        self.sim_1000_btn.setEnabled(False)
        self.reset_sim_btn.setEnabled(False)

    def reset_and_simulate(self):
        """리셋 후 10번 시뮬레이션"""
        # 컨텍스트 초기화
        self.current_context = None
        self.simulation_results.clear()

        # 10번 시뮬레이션
        self.run_simulation(10)

    def run_simulation(self, iterations: int):
        """
        N번 시뮬레이션 실행

        Args:
            iterations: 실행 횟수
        """
        if not self.current_wildcards:
            QMessageBox.warning(self, "경고", "먼저 프롬프트를 분석하세요.")
            return

        prompt = self.prompt_edit.toPlainText().strip()

        # 컨텍스트 생성 (첫 실행 시)
        if self.current_context is None:
            self.current_context = PromptContext(
                source_row=pd.Series(),
                settings={}
            )

        # 시뮬레이션 실행
        for i in range(iterations):
            # 프롬프트를 태그 리스트로 변환
            tags = [tag.strip() for tag in prompt.split(',') if tag.strip()]

            # 와일드카드 확장
            expanded_tags = self.processor.expand_tags(tags, self.current_context)

            # 최종 프롬프트 생성
            final_prompt = ', '.join(expanded_tags)

            # 각 와일드카드의 현재 상태 기록
            wildcard_states = {}
            for wc in self.current_wildcards:
                state = self.current_context.wildcard_state.get(wc.name)
                if state:
                    wildcard_states[wc.name] = f"{state['current']}/{state['total']}"
                else:
                    wildcard_states[wc.name] = "N/A"

            # 결과 저장
            self.simulation_results.append({
                'num': len(self.simulation_results) + 1,
                'states': wildcard_states.copy(),
                'prompt': final_prompt
            })

        # 결과 표시
        self.display_results()

    def display_results(self):
        """결과 테이블 표시"""
        if not self.simulation_results:
            return

        # 테이블 설정
        self.result_table.clear()
        self.result_table.setRowCount(len(self.simulation_results))

        # 컬럼 설정: # + 각 와일드카드 + 최종 프롬프트
        columns = ['#'] + [wc.name for wc in self.current_wildcards] + ['최종 프롬프트']
        self.result_table.setColumnCount(len(columns))
        self.result_table.setHorizontalHeaderLabels(columns)

        # 데이터 채우기
        for row_idx, result in enumerate(self.simulation_results):
            # 번호
            self.result_table.setItem(row_idx, 0, QTableWidgetItem(str(result['num'])))

            # 각 와일드카드 상태
            for col_idx, wc in enumerate(self.current_wildcards, start=1):
                state = result['states'].get(wc.name, 'N/A')
                self.result_table.setItem(row_idx, col_idx, QTableWidgetItem(state))

            # 최종 프롬프트
            self.result_table.setItem(row_idx, len(columns) - 1, QTableWidgetItem(result['prompt']))

        # 컬럼 너비 조정
        self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col_idx in range(1, len(columns) - 1):
            self.result_table.horizontalHeader().setSectionResizeMode(col_idx, QHeaderView.ResizeMode.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Stretch)

        # 복사/저장 버튼 활성화
        self.copy_btn.setEnabled(True)
        self.save_csv_btn.setEnabled(True)

    def copy_results(self):
        """결과를 클립보드에 복사"""
        if not self.simulation_results:
            return

        # TSV 형식으로 변환
        columns = ['#'] + [wc.name for wc in self.current_wildcards] + ['최종 프롬프트']
        text = '\t'.join(columns) + '\n'

        for result in self.simulation_results:
            row = [str(result['num'])]
            for wc in self.current_wildcards:
                row.append(result['states'].get(wc.name, 'N/A'))
            row.append(result['prompt'])
            text += '\t'.join(row) + '\n'

        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        QMessageBox.information(self, "완료", "결과가 클립보드에 복사되었습니다.")

    def save_csv(self):
        """결과를 CSV 파일로 저장"""
        if not self.simulation_results:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "CSV 저장",
            "wildcard_simulation.csv",
            "CSV Files (*.csv)"
        )

        if not file_path:
            return

        try:
            # DataFrame 생성
            data = []
            for result in self.simulation_results:
                row = {'#': result['num']}
                for wc in self.current_wildcards:
                    row[wc.name] = result['states'].get(wc.name, 'N/A')
                row['최종 프롬프트'] = result['prompt']
                data.append(row)

            df = pd.DataFrame(data)
            df.to_csv(file_path, index=False, encoding='utf-8-sig')

            QMessageBox.information(self, "완료", f"CSV 파일이 저장되었습니다:\n{file_path}")

        except Exception as e:
            QMessageBox.critical(self, "오류", f"CSV 저장 실패: {e}")
