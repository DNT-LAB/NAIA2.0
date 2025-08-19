"""
인스턴트 와일드카드 모듈 테스트
"""

import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

# 프로젝트 루트 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.instant_wildcard_module import InstantWildcardModule


class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("인스턴트 와일드카드 테스트")
        self.setGeometry(100, 100, 800, 600)
        
        # 중앙 위젯 설정
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 인스턴트 와일드카드 모듈 생성
        self.instant_wildcard_module = InstantWildcardModule()
        
        # 위젯 생성 및 추가
        widget = self.instant_wildcard_module.create_widget(self)
        layout.addWidget(widget)
        
        # 와일드카드 업데이트 시그널 연결
        self.instant_wildcard_module.wildcards_updated.connect(self.on_wildcards_updated)
        
        print("[OK] Test window initialized")
        
    def on_wildcards_updated(self, wildcards_dict):
        """와일드카드 업데이트 시 호출"""
        print(f"[UPDATE] Wildcards updated: {len(wildcards_dict)} items")
        for key, value in list(wildcards_dict.items())[:5]:  # 처음 5개만 표시
            preview = value[:50] + "..." if len(value) > 50 else value
            print(f"  - {key}: {preview}")


def main():
    # 테스트용 폴더 및 파일 생성
    save_path = Path("save/instant_wildcard")
    if not save_path.exists():
        print("[INFO] Creating test folder...")
        save_path.mkdir(parents=True, exist_ok=True)
    
    # Qt 애플리케이션 생성
    app = QApplication(sys.argv)
    
    # 다크 테마 적용
    app.setStyleSheet("""
        QMainWindow {
            background-color: #1e1e1e;
        }
        QWidget {
            background-color: #2b2b2b;
            color: #e0e0e0;
        }
    """)
    
    # 테스트 윈도우 생성
    window = TestWindow()
    window.show()
    
    # 이벤트 루프 실행
    sys.exit(app.exec())


if __name__ == "__main__":
    main()