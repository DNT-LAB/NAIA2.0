import os
import glob
import importlib.util
import traceback
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from ui.collapsible import CollapsibleBox
from interfaces.base_module import BaseMiddleModule
from core.context import AppContext 

class MiddleSectionController:
    """
    Middle Section의 모듈을 동적으로 로드하고, CollapsibleBox 하위로 배치하는 컨트롤러
    """

    def __init__(self, modules_dir: str, app_context: AppContext, parent: QWidget = None):
        self.modules_dir = modules_dir
        self.app_context = app_context # AppContext 참조
        self.parent_widget = parent
        self.module_classes = []
        self.module_instances = []
        
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
        """모듈들을 CollapsibleBox로 감싸서 UI 구성"""
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
        
        # CollapsibleBox 임포트 (메인 파일에서)
        from ui.collapsible import CollapsibleBox
        
        # 모듈들을 order 순서대로 정렬
        sorted_classes = sorted(self.module_classes, key=lambda c: c().get_order())
        
        from ui.collapsible import CollapsibleBox
        
        sorted_classes = sorted(self.module_classes, key=lambda c: c().get_order())
        
        for cls in sorted_classes:
            try:
                # 1. 모듈 인스턴스 생성
                module_instance = cls()
                self.module_instances.append(module_instance)
                
                # ✅ [핵심 수정] 위젯을 생성하기 전에 컨텍스트를 먼저 주입합니다.
                # initialize_with_context를 build_ui 밖이 아닌, 여기서 바로 호출합니다.
                module_instance.initialize_with_context(self.app_context)
                
                # 2. 컨텍스트가 주입된 후에 위젯을 생성합니다.
                box = CollapsibleBox(title=module_instance.get_title(), parent=self.parent_widget)
                widget = module_instance.create_widget(parent=self.parent_widget)
                box.setContentLayout(widget.layout())
                layout.addWidget(box)

                # 3. 파이프라인 훅을 등록합니다.
                hook_info = module_instance.get_pipeline_hook_info()
                if hook_info:
                    self.app_context.register_pipeline_hook(hook_info, module_instance)
                    
            except Exception as e:
                print(f"모듈 '{cls.__name__}' UI 생성 또는 훅 등록 중 오류: {e}")
        
        
        # 모든 모듈 초기화
        for inst in self.module_instances:
            try:
                inst.on_initialize()
            except Exception as e:
                print(f"⚠️ 모듈 초기화 오류 ({inst.__class__.__name__}): {e}")

    def get_module_instance(self, module_class_name: str) -> Optional[BaseMiddleModule]:
        """
        클래스 이름(문자열)으로 관리 중인 모듈 인스턴스를 찾아 반환합니다.
        
        Args:
            module_class_name (str): 찾고자 하는 모듈의 클래스 이름 (예: "CharacterModule")

        Returns:
            Optional[BaseMiddleModule]: 찾은 모듈의 인스턴스. 없으면 None을 반환합니다.
        """
        for instance in self.module_instances:
            if instance.__class__.__name__ == module_class_name:
                return instance
        
        print(f"⚠️ 모듈 인스턴스를 찾을 수 없습니다: {module_class_name}")
        return None

    # [신규] 관리하는 모든 모듈의 설정을 저장하는 메서드
    def save_all_module_settings(self):
        """
        모든 모듈 인스턴스를 순회하며, save_settings 메서드가 있는 경우 호출합니다.
        """
        print("🔧 모든 모듈의 설정 저장을 시도합니다...")
        for inst in self.module_instances:
            # 모듈이 save_settings 메서드를 가지고 있는지 확인
            if hasattr(inst, 'save_settings') and callable(getattr(inst, 'save_settings')):
                try:
                    inst.save_settings()
                    print(f"  - {inst.get_title()} 설정 저장 완료.")
                except Exception as e:
                    print(f"  - ❌ {inst.get_title()} 설정 저장 실패: {e}")