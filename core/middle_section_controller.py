# core/middle_section_controller.py (수정된 버전)

import os
import glob
import importlib.util
import traceback
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from ui.collapsible import EnhancedCollapsibleBox  # 수정된 import
from ui.detached_window import DetachedWindow  # 추가 import
from interfaces.base_module import BaseMiddleModule
from core.context import AppContext 

class MiddleSectionController:
    """
    Middle Section의 모듈을 동적으로 로드하고, CollapsibleBox 하위로 배치하는 컨트롤러
    모듈 분리/복귀 기능 추가
    """

    def __init__(self, modules_dir: str, app_context: AppContext, parent: QWidget = None):
        self.modules_dir = modules_dir
        self.app_context = app_context
        self.parent_widget = parent
        self.module_classes = []
        self.module_instances = []
        
        # 분리된 모듈들을 추적하기 위한 딕셔너리
        self.detached_modules = {}  # {module_title: DetachedWindow}
        self.module_boxes = {}      # {module_title: EnhancedCollapsibleBox}
        
        if not os.path.exists(modules_dir):
            os.makedirs(modules_dir)
            print(f"📁 모듈 디렉토리 생성: {modules_dir}")

    def load_modules(self) -> None:
        """모듈 디렉토리에서 *_module.py 파일들을 로드"""
        print(f"🔍 모듈 로드 시작: {self.modules_dir}")
        
        pattern = os.path.join(self.modules_dir, "*_module.py")
        module_files = glob.glob(pattern)
        
        if not module_files:
            print("❌ 모듈 파일이 없습니다.")
            print("💡 다음 파일들을 modules/ 디렉토리에 복사하세요:")
            expected_modules = [
                'automation_module.py',
                'turbo_module.py', 
                'character_module.py',
                'prompt_engineering_module.py'
            ]
            for module in expected_modules:
                print(f"  - {module}")
            return
        
        print(f"📋 발견된 모듈 파일: {[os.path.basename(f) for f in module_files]}")
        
        for path in module_files:
            name = Path(path).stem
            try:
                spec = importlib.util.spec_from_file_location(name, path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # 모듈에서 BaseMiddleModule을 상속한 클래스 찾기
                    for attr in dir(module):
                        obj = getattr(module, attr)
                        if (isinstance(obj, type) and 
                            issubclass(obj, BaseMiddleModule) and 
                            obj is not BaseMiddleModule):
                            self.module_classes.append(obj)
                            print(f"✅ 모듈 로드 성공: {name} -> {obj.__name__}")
                            
            except Exception as e:
                print(f"❌ 모듈 로드 실패 ({name}): {e}")
                traceback.print_exc()
                continue

    def initialize_modules_with_context(self, context: 'AppContext'):
        """로드된 모든 모듈 인스턴스에 AppContext를 주입합니다."""
        for inst in self.module_instances:
            inst.initialize_with_context(context)

    def build_ui(self, layout: QVBoxLayout) -> None:
        """모듈들을 EnhancedCollapsibleBox로 감싸서 UI 구성"""
        if not self.module_classes:
            self.load_modules()
        
        # 모듈이 없으면 경고 메시지 표시
        if not self.module_classes:
            print("⚠️ 로드된 모듈이 없습니다.")
            
            # 폴백 위젯 생성
            from PyQt6.QtWidgets import QLabel
            fallback_widget = QLabel("모듈 파일이 없습니다.\nmodules/ 디렉토리를 확인하세요.")
            fallback_widget.setStyleSheet("""
                QLabel {
                    color: #FF9800;
                    font-family: 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
                    font-size: 16px;
                    padding: 20px;
                    text-align: center;
                }
            """)
            layout.addWidget(fallback_widget)
            return
        
        # 모듈들을 order 순서대로 정렬
        sorted_classes = sorted(self.module_classes, key=lambda c: c().get_order())
        
        for cls in sorted_classes:
            try:
                # 1. 모듈 인스턴스 생성
                module_instance = cls()
                self.module_instances.append(module_instance)
                
                # 2. 컨텍스트 주입
                module_instance.initialize_with_context(self.app_context)
                
                # 3. 모듈 초기화 (위젯 생성 전에 필요)
                try:
                    module_instance.on_initialize()
                except Exception as e:
                    print(f"⚠️ 모듈 초기화 오류 ({module_instance.__class__.__name__}): {e}")
                
                # 4. EnhancedCollapsibleBox 생성 (분리 가능)
                module_title = module_instance.get_title()
                box = EnhancedCollapsibleBox(
                    title=module_title, 
                    parent=self.parent_widget, 
                    detachable=True  # 모든 모듈을 분리 가능하게 설정
                )
                
                # 5. 모듈 분리 요청 시그널 연결
                box.module_detach_requested.connect(self.detach_module)
                
                # 6. 위젯 생성 및 박스에 추가
                widget = module_instance.create_widget(parent=self.parent_widget)
                
                # 위젯과 레이아웃이 유효한지 확인
                if widget and widget.layout():
                    box.setContentLayout(widget.layout())
                    
                    # 7. 레이아웃에 추가
                    layout.addWidget(box)
                    
                    # 8. 추적을 위해 딕셔너리에 저장
                    self.module_boxes[module_title] = box
                    
                    print(f"✅ 모듈 '{module_title}' UI 생성 완료")
                else:
                    print(f"❌ 모듈 '{module_title}': 위젯 또는 레이아웃이 None입니다.")
                    continue

                # 9. 파이프라인 훅 등록
                hook_info = module_instance.get_pipeline_hook_info()
                if hook_info:
                    self.app_context.register_pipeline_hook(hook_info, module_instance)
                    
            except Exception as e:
                print(f"모듈 '{cls.__name__}' UI 생성 또는 훅 등록 중 오류: {e}")
                import traceback
                traceback.print_exc()
        
        # 모든 모듈 생성 완료 후 추가 초기화는 제거 (이미 위에서 처리함)

    def detach_module(self, module_title: str, content_widget: QWidget):
        """모듈을 외부 창으로 분리 (완전 독립 창)"""
        if module_title in self.detached_modules:
            # 이미 분리된 모듈인 경우 기존 창을 활성화
            self.detached_modules[module_title].raise_()
            self.detached_modules[module_title].activateWindow()
            print(f"⚠️ 모듈 '{module_title}'은 이미 분리되어 있습니다.")
            return
            
        # content_widget 유효성 검사
        if not content_widget:
            print(f"❌ 모듈 '{module_title}': content_widget이 None입니다.")
            return
            
        try:
            print(f"🔧 독립 모듈 분리 시작: {module_title}")
            
            # 위젯이 여전히 유효한지 테스트
            _ = content_widget.isVisible()
            print(f"   - content_widget 타입: {type(content_widget).__name__}")
            print(f"   - content_widget 부모: {content_widget.parent()}")
            
        except RuntimeError:
            print(f"❌ 모듈 '{module_title}': 위젯이 이미 삭제되었습니다.")
            return
            
        # 해당 모듈의 CollapsibleBox 찾기
        if module_title not in self.module_boxes:
            print(f"❌ 모듈 '{module_title}'의 박스를 찾을 수 없습니다.")
            return
            
        box = self.module_boxes[module_title]
        
        try:
            # 1. CollapsibleBox에서 위젯을 안전하게 분리
            print(f"   - CollapsibleBox에서 위젯 분리 중...")
            
            # takeWidget()을 사용하여 위젯을 안전하게 제거
            actual_widget = box.content_area.takeWidget()
            
            if actual_widget != content_widget:
                print(f"⚠️ 예상과 다른 위젯: expected={content_widget}, actual={actual_widget}")
                # 실제 위젯이 다르면 실제 위젯을 사용
                content_widget = actual_widget
            
            if not content_widget:
                print(f"❌ 모듈 '{module_title}': 추출된 위젯이 None입니다.")
                return
            
            print(f"   - 추출된 위젯: {content_widget}")
            print(f"   - 추출된 위젯 크기: {content_widget.size()}")
            print(f"   - 추출된 위젯 레이아웃: {content_widget.layout()}")
            
            # 2. 박스를 분리 상태로 설정 (플레이스홀더 표시)
            box.set_detached_state(True)
            
            # 3. ✅ 완전히 독립적인 창 생성 (parent 관계 제거)
            print(f"   - 독립 DetachedWindow 생성 중...")
            detached_window = DetachedWindow(
                content_widget, 
                module_title, 
                -1, 
                parent_container=self.parent_widget  # 부모가 아닌 참조만 전달
            )
            detached_window.window_closed.connect(self.reattach_module)
            
            # 창 추적 딕셔너리에 추가
            self.detached_modules[module_title] = detached_window
            
            # 4. 독립 창 표시
            detached_window.show()
            detached_window.raise_()
            detached_window.activateWindow()
            
            print(f"✅ 독립 모듈 '{module_title}' 분리 완료 (메인 UI와 완전 분리)")
            
        except Exception as e:
            print(f"❌ 모듈 '{module_title}' 분리 실패: {e}")
            import traceback
            traceback.print_exc()
            
            # 실패 시 박스 상태 복원
            try:
                if content_widget:
                    print(f"   - 복원 시도: 위젯을 CollapsibleBox로 되돌림")
                    box.content_area.setWidget(content_widget)
                box.set_detached_state(False)
            except Exception as restore_error:
                print(f"   - 복원 실패: {restore_error}")

    def reattach_module(self, tab_index: int, content_widget: QWidget):
        """외부 창에서 모듈로 복귀 (수정된 버전)"""
        module_title = None
        
        print(f"🔄 모듈 복귀 요청: tab_index={tab_index}, widget={content_widget}")
        
        # 분리된 모듈들 중에서 해당 위젯을 가진 것을 찾기
        for title, window in self.detached_modules.items():
            if window.get_original_widget() == content_widget:
                module_title = title
                break
                
        if not module_title or module_title not in self.module_boxes:
            print("❌ 복귀할 모듈을 찾을 수 없습니다.")
            return
            
        try:
            print(f"   - 복귀할 모듈: {module_title}")
            
            # CollapsibleBox 가져오기
            box = self.module_boxes[module_title]
            
            # 기존 플레이스홀더 제거
            old_placeholder = box.content_area.takeWidget()
            if old_placeholder:
                print(f"   - 플레이스홀더 제거: {old_placeholder}")
                old_placeholder.deleteLater()
            
            # 위젯을 박스로 복귀
            print(f"   - 위젯을 CollapsibleBox로 복귀: {content_widget}")
            content_widget.setParent(box.content_area)
            box.content_area.setWidget(content_widget)
            
            # 위젯 강제 표시
            content_widget.show()
            content_widget.setVisible(True)
            
            # 박스 상태를 정상으로 복원
            box.set_detached_state(False)
            
            # 추적 딕셔너리에서 제거
            del self.detached_modules[module_title]
            
            print(f"✅ 모듈 '{module_title}' 복귀 완료")
            
        except Exception as e:
            print(f"❌ 모듈 '{module_title}' 복귀 실패: {e}")
            import traceback
            traceback.print_exc()

    def get_module_instance(self, module_class_name: str) -> Optional[BaseMiddleModule]:
        """
        클래스 이름(문자열)으로 관리 중인 모듈 인스턴스를 찾아 반환합니다.
        """
        for instance in self.module_instances:
            if instance.__class__.__name__ == module_class_name:
                return instance
        
        print(f"⚠️ 모듈 인스턴스를 찾을 수 없습니다: {module_class_name}")
        return None

    def save_all_module_settings(self):
        """모든 모듈의 설정을 저장합니다."""
        print("🔧 모든 모듈의 설정 저장을 시도합니다...")
        for inst in self.module_instances:
            if hasattr(inst, 'save_settings') and callable(getattr(inst, 'save_settings')):
                try:
                    inst.save_settings()
                    print(f"  - {inst.get_title()} 설정 저장 완료.")
                except Exception as e:
                    print(f"  - ❌ {inst.get_title()} 설정 저장 실패: {e}")

    def close_all_detached_modules(self):
        """모든 분리된 모듈 창을 닫습니다 (앱 종료 시 호출)"""
        print("🔗 분리된 모듈 창들을 정리합니다...")
        for title, window in list(self.detached_modules.items()):
            try:
                window.close()
                print(f"  - {title} 창 닫기 완료")
            except Exception as e:
                print(f"  - ❌ {title} 창 닫기 실패: {e}")
        self.detached_modules.clear()