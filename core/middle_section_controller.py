# core/middle_section_controller.py (수정된 버전)

import os
import importlib.util
import traceback
from typing import Optional
from PyQt6.QtWidgets import QVBoxLayout, QWidget
from ui.collapsible import EnhancedCollapsibleBox  # 수정된 import
from ui.detached_window import DetachedWindow  # 추가 import
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule
from core.context import AppContext 

MIDDLE_MODULE_SPECS = (
    {"file": "automation_module", "class": "AutomationModule", "web_session_lazy": True},
    {"file": "character_module", "class": "CharacterModule"},
    {"file": "character_reference_module", "class": "CharacterReferenceModule"},
    {"file": "conditional_prompt_module", "class": "PromptListModifierModule"},
    {"file": "e621_event_module", "class": "E621EventModuleV2", "web_session_lazy": True},
    {"file": "instant_wildcard_module", "class": "InstantWildcardModule", "web_session_lazy": True},
    {"file": "ollama_module", "class": "OllamaModule", "web_session_lazy": True},
    {"file": "prompt_engineering_module", "class": "PromptEngineeringModule"},
    {
        "file": "reference_inset_module",
        "class": "ReferenceInsetAutoInjectModule",
        "web_session_lazy": True,
        "web_session_headless_hook": "reference_inset",
    },
    {"file": "vibe_transfer_module", "class": "VibeTransferModule"},
    {"file": "wildcard_status_module", "class": "WildcardStatusModule", "web_session_lazy": True},
)


def is_hidden_web_session_runtime() -> bool:
    return os.environ.get("NAIA_CLI_WEB_SESSION_HIDE_MAIN_WINDOW") == "1"


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
        self._deferred_module_specs = {}
        self._deferred_headless_hook_classes = set()

        # 분리된 모듈들을 추적하기 위한 딕셔너리
        self.detached_modules = {}  # {module_title: DetachedWindow}
        self.module_boxes = {}      # {module_title: EnhancedCollapsibleBox}

        # 🆕 모듈 상태 추적
        self.module_states = {
            'expanded': set(),      # 현재 펼쳐진 모듈들 (title)
            'detached': set(),      # 현재 분리된 모듈들 (title)
            'scroll_positions': {}  # {title: scroll_position}
        }

        # 🆕 아코디언 모드 (하나만 펼치기)
        self.accordion_mode = True

        self.app_context.subscribe("api_mode_changed", self.on_api_mode_changed)
        
        if not os.path.exists(modules_dir):
            os.makedirs(modules_dir)
            print(f"📁 모듈 디렉토리 생성: {modules_dir}")

    def on_api_mode_changed(self, data: dict):
        """API 모드가 변경될 때 각 모듈의 가시성을 업데이트합니다."""
        new_mode = data.get("new_mode")
        if not new_mode:
            return

        print(f"🎨 MiddleSectionController: API 모드 변경 감지 -> {new_mode}")
        
        # self.module_instances 대신 self.module_boxes를 기준으로 순회
        for title, box in self.module_boxes.items():
            # module_instances 리스트에서 해당 모듈 인스턴스 찾기
            module_instance = next((inst for inst in self.module_instances if inst.get_title() == title), None)

            if module_instance:
                # is_compatible_with_mode 메서드는 BaseMiddleModule에 기본 구현이 있으므로 안전하게 호출 가능
                is_compatible = module_instance.is_compatible_with_mode(new_mode)
                box.setVisible(is_compatible)
                visibility_status = "표시" if is_compatible else "숨김"
                print(f"  - '{title}' 모듈 가시성 설정: {visibility_status}")

    def load_modules(self) -> None:
        """명시된 middle module registry에서 지원 모듈만 로드."""
        print(f"🔍 모듈 로드 시작: {self.modules_dir}")
        print(f"📋 지원 middle 모듈 registry: {[spec['file'] for spec in MIDDLE_MODULE_SPECS]}")

        for module_spec in MIDDLE_MODULE_SPECS:
            name = module_spec["file"]
            class_name = module_spec["class"]
            if self._should_defer_module_spec(module_spec):
                self._deferred_module_specs[class_name] = module_spec
                self._register_deferred_headless_support(module_spec)
                print(f"⏳ Web Session middle 모듈 지연 로드: {name} -> {class_name}")
                continue
            path = os.path.join(self.modules_dir, f"{name}.py")
            if not os.path.exists(path):
                print(f"⚠️ 등록된 middle 모듈 파일 없음: {name}.py")
                continue
            try:
                loaded = self._load_registered_module_class(name, path, class_name)
                if loaded:
                    print(f"✅ 모듈 로드 성공: {name} -> {loaded.__name__}")
                            
            except Exception as e:
                print(f"❌ 모듈 로드 실패 ({name}): {e}")
                traceback.print_exc()
                continue

    def _load_registered_module_class(self, name: str, path: str, class_name: str):
        spec = importlib.util.spec_from_file_location(name, path)
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        obj = getattr(module, class_name, None)
        if not (
            isinstance(obj, type)
            and issubclass(obj, BaseMiddleModule)
            and obj is not BaseMiddleModule
        ):
            print(f"❌ 등록된 middle 모듈 클래스 없음: {name}.py::{class_name}")
            return None

        self.module_classes.append(obj)
        return obj

    def _should_defer_module_spec(self, module_spec: dict) -> bool:
        return bool(module_spec.get("web_session_lazy")) and is_hidden_web_session_runtime()

    def _initialize_module_instance(self, module_instance):
        module_instance.initialize_with_context(self.app_context)

        if isinstance(module_instance, ModeAwareModule):
            self.app_context.mode_manager.register_module(module_instance)
            current_mode = self.app_context.get_api_mode()
            module_instance.current_mode = current_mode
            print(f"🔗 모드 대응 모듈 초기화: {module_instance.get_title()}")
            print(f"   - NAI 호환: {module_instance.NAI_compatibility}")
            print(f"   - WEBUI 호환: {module_instance.WEBUI_compatibility}")
        else:
            current_mode = self.app_context.get_api_mode()
            if hasattr(module_instance, 'widget') and hasattr(module_instance, 'NAI_compatibility'):
                should_be_visible = (
                    (current_mode == "NAI" and getattr(module_instance, 'NAI_compatibility', True)) or
                    (current_mode == "WEBUI" and getattr(module_instance, 'WEBUI_compatibility', True)) or
                    (current_mode == "COMFYUI" and getattr(module_instance, 'COMFYUI_compatibility', True))
                )
                if module_instance.widget and hasattr(module_instance.widget, 'setVisible'):
                    module_instance.widget.setVisible(should_be_visible)

        if hasattr(module_instance, 'on_initialize'):
            try:
                module_instance.on_initialize()
            except Exception as e:
                print(f"⚠️ 모듈 초기화 오류 ({module_instance.__class__.__name__}): {e}")

    def _register_module_pipeline_hook(self, module_instance):
        hook_info = module_instance.get_pipeline_hook_info()
        if hook_info:
            self.app_context.register_pipeline_hook(hook_info, module_instance)

    def _register_deferred_headless_support(self, module_spec: dict) -> None:
        hook_id = module_spec.get("web_session_headless_hook")
        if not hook_id:
            return

        if hook_id == "reference_inset":
            try:
                from core.reference_inset_service import ReferenceInsetAutoInjectHook

                hook = ReferenceInsetAutoInjectHook(self.app_context)
                self.app_context.register_pipeline_hook(hook.get_pipeline_hook_info(), hook)
                self._deferred_headless_hook_classes.add(module_spec["class"])
                print(f"✅ Web Session headless middle hook 등록: {module_spec['class']}")
            except Exception as e:
                print(f"⚠️ Web Session headless middle hook 등록 실패 ({module_spec['class']}): {e}")
            return

        print(f"⚠️ 알 수 없는 Web Session headless middle hook: {hook_id}")

    def _load_deferred_module_instance(self, module_class_name: str):
        module_spec = self._deferred_module_specs.get(module_class_name)
        if not module_spec:
            return None

        name = module_spec["file"]
        path = os.path.join(self.modules_dir, f"{name}.py")
        if not os.path.exists(path):
            print(f"⚠️ 지연 middle 모듈 파일 없음: {name}.py")
            return None

        try:
            TargetModuleClass = self._load_registered_module_class(name, path, module_class_name)
            if not TargetModuleClass:
                return None
            module_instance = TargetModuleClass()
            self.module_instances.append(module_instance)
            self._initialize_module_instance(module_instance)
            if module_class_name not in self._deferred_headless_hook_classes:
                self._register_module_pipeline_hook(module_instance)
            self._deferred_module_specs.pop(module_class_name, None)
            print(f"✅ 지연 middle 모듈 로드 완료: {module_class_name}")
            return module_instance
        except Exception as e:
            print(f"❌ 지연 middle 모듈 로드 실패 ({module_class_name}): {e}")
            traceback.print_exc()
            return None

    def initialize_modules_with_context(self, app_context):
        """모듈 인스턴스들에 컨텍스트를 주입하고 ModeAwareModule들을 등록합니다."""
        print(f"🔗 {len(self.module_instances)}개 모듈에 컨텍스트 주입 시작...")
        
        for module_instance in self.module_instances:  # ✅ .values() 제거 (리스트이므로)
            self._initialize_module_instance(module_instance)
        
        print(f"✅ 컨텍스트 주입 완료. 등록된 ModeAware 모듈: {len(app_context.mode_manager.registered_modules)}개")

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
        
        # 모듈들을 order 순서대로 정렬 (인스턴스 1회만 생성하여 재사용 — 정렬용 임시 인스턴스 금지)
        instances = [cls() for cls in self.module_classes]
        instances.sort(key=lambda inst: inst.get_order())

        for module_instance in instances:
            module_name = module_instance.__class__.__name__
            try:
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
                    detachable=True,  # 모든 모듈을 분리 가능하게 설정
                    start_expanded=getattr(module_instance, 'start_expanded', False)
                )
                
                # 5. 모듈 분리 요청 시그널 연결
                box.module_detach_requested.connect(self.detach_module)

                # 🆕 5.5. 모듈 토글 시그널 연결 (아코디언 동작)
                box.toggled.connect(self.on_module_toggled)

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
                print(f"모듈 '{module_name}' UI 생성 또는 훅 등록 중 오류: {e}")
                import traceback
                traceback.print_exc()
        
        # 모든 모듈 생성 완료 후 추가 초기화는 제거 (이미 위에서 처리함)

        # 🆕 저장된 상태 로드
        # self.load_module_states()

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
            
            # content_area는 순수 QWidget이므로 레이아웃에서 위젯을 분리
            box._content_layout.removeWidget(content_widget)
            content_widget.setParent(None)
            
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

            # 🆕 E621 모듈인 경우 최소 너비 설정
            if "E621" in module_title or "e621" in module_title.lower():
                from ui.scaling_manager import get_scaled_size
                min_width = get_scaled_size(1160)
                detached_window.setMinimumWidth(min_width)
                # 초기 크기도 설정
                detached_window.resize(min_width, get_scaled_size(800))
                print(f"   - E621 모듈 최소 너비 설정: {min_width}px")

            # 창 추적 딕셔너리에 추가
            self.detached_modules[module_title] = detached_window

            # 🆕 분리 상태 추적
            self.module_states['detached'].add(module_title)
            self.module_states['expanded'].discard(module_title)  # 분리된 모듈은 펼침 목록에서 제거
            self.save_module_states()

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
                    box._content_layout.addWidget(content_widget)
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
            
            # 기존 플레이스홀더 제거 (content_layout의 모든 위젯 정리)
            while box._content_layout.count():
                item = box._content_layout.takeAt(0)
                widget = item.widget()
                if widget:
                    print(f"   - 플레이스홀더 제거: {widget}")
                    widget.deleteLater()

            # 위젯을 박스로 복귀
            print(f"   - 위젯을 CollapsibleBox로 복귀: {content_widget}")
            box._content_layout.addWidget(content_widget)
            
            # 위젯 강제 표시
            content_widget.show()
            content_widget.setVisible(True)
            
            # 박스 상태를 정상으로 복원
            box.set_detached_state(False)
            
            # 추적 딕셔너리에서 제거
            del self.detached_modules[module_title]

            # 🆕 복귀 상태 추적
            self.module_states['detached'].discard(module_title)
            # 복귀 시 펼쳐진 상태로 설정 (옵션: 원하면 접힌 상태로 가능)
            # self.module_states['expanded'].add(module_title)
            self.save_module_states()

            # 🆕 auto_detach 모듈의 경우 is_first_toggle 리셋
            # 창을 닫으면 다음에 열 때 자동으로 외부창이 열리도록 설정
            module_instance = next((inst for inst in self.module_instances if inst.get_title() == module_title), None)
            if module_instance and hasattr(module_instance, 'auto_detach') and module_instance.auto_detach:
                module_instance.is_first_toggle = True
                print(f"🔄 [AUTO-DETACH] '{module_title}' is_first_toggle 리셋 완료 (다음 토글 시 자동 분리됨)")

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

        deferred = self._load_deferred_module_instance(module_class_name)
        if deferred is not None:
            return deferred
        
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

    # 🆕 ============================================================
    # 🆕 모듈 상태 추적 및 아코디언 동작
    # 🆕 ============================================================

    def on_module_toggled(self, module_title: str, is_expanded: bool):
        """모듈 펼침/접힘 상태 변경 이벤트"""
        print(f"📊 [STATE] 모듈 토글: '{module_title}' → {'펼침' if is_expanded else '접음'}")

        if is_expanded:
            # 펼쳐진 모듈로 등록
            self.module_states['expanded'].add(module_title)

            # 🆕 auto_detach 체크: 자동 분리 모드 확인
            module_instance = next((inst for inst in self.module_instances if inst.get_title() == module_title), None)
            if module_instance and hasattr(module_instance, 'auto_detach') and module_instance.auto_detach:
                # 첫 토글인지 확인
                if hasattr(module_instance, 'is_first_toggle') and module_instance.is_first_toggle:
                    print(f"🚀 [AUTO-DETACH] '{module_title}' 자동 분리 모드 활성화")
                    module_instance.is_first_toggle = False

                    # content_widget 가져오기
                    box = self.module_boxes.get(module_title)
                    if box and hasattr(box, 'content_widget'):
                        content_widget = box.content_widget
                        # 분리 실행
                        self.detach_module(module_title, content_widget)
                        return  # 분리 후에는 아래 로직 실행 안 함
                    else:
                        print(f"⚠️ [AUTO-DETACH] '{module_title}' content_widget을 찾을 수 없습니다")

            # 🎯 아코디언 모드: 다른 모듈들 접기
            if self.accordion_mode:
                self._collapse_other_modules(module_title)

        else:
            # 접힌 모듈로 등록
            self.module_states['expanded'].discard(module_title)

        # 상태 저장
        self.save_module_states()

    def _collapse_other_modules(self, expanded_module_title: str):
        """아코디언 동작: 다른 모듈들을 접기 (분리된 모듈 제외)"""
        print(f"🎯 [ACCORDION] 다른 모듈들 접기 ('{expanded_module_title}' 제외)")

        for title, box in self.module_boxes.items():
            # 현재 펼친 모듈과 분리된 모듈은 건드리지 않음
            if title == expanded_module_title or title in self.module_states['detached']:
                continue

            # 펼쳐져 있으면 접기 (시그널 발행 안 함 - 재귀 방지)
            if box.is_expanded():
                print(f"  - '{title}' 접기")
                box.collapse(emit_signal=False)
                self.module_states['expanded'].discard(title)

    def _scroll_to_module(self, module_title: str):
        """모듈로 자동 스크롤"""
        if module_title not in self.module_boxes:
            return

        box = self.module_boxes[module_title]

        # 부모 스크롤 영역 찾기
        scroll_area = self._find_parent_scroll_area(box)
        if not scroll_area:
            print(f"⚠️ [SCROLL] '{module_title}': 부모 스크롤 영역을 찾을 수 없습니다.")
            return

        # 박스의 Y 위치 계산 (스크롤 영역의 content widget 기준으로 매핑)
        from PyQt6.QtCore import QPoint
        scroll_content = scroll_area.widget()
        if scroll_content:
            box_y = box.mapTo(scroll_content, QPoint(0, 0)).y()
        else:
            box_y = box.y()
        print(f"📜 [SCROLL] '{module_title}'로 스크롤 이동: Y={box_y}")

        # 스크롤 이동 (QTimer로 지연 - UI 업데이트 대기)
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, lambda: scroll_area.verticalScrollBar().setValue(box_y))

    def _find_parent_scroll_area(self, widget: QWidget):
        """위젯의 부모 QScrollArea 찾기"""
        from PyQt6.QtWidgets import QScrollArea

        parent = widget.parent()
        while parent:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parent()
        return None

    def set_accordion_mode(self, enabled: bool):
        """아코디언 모드 설정"""
        self.accordion_mode = enabled
        print(f"🎯 [ACCORDION] 아코디언 모드: {'활성화' if enabled else '비활성화'}")

    def get_module_states(self) -> dict:
        """현재 모듈 상태 반환"""
        return {
            'expanded': list(self.module_states['expanded']),
            'detached': list(self.module_states['detached']),
            'scroll_positions': self.module_states['scroll_positions'].copy(),
            'accordion_mode': self.accordion_mode
        }

    def save_module_states(self):
        """모듈 상태를 파일에 저장"""
        import json
        from pathlib import Path

        # 스크롤 위치 업데이트
        for title, box in self.module_boxes.items():
            if box.is_expanded():
                self.module_states['scroll_positions'][title] = box.get_scroll_position()

        state_file = Path("save/module_states.json")
        state_file.parent.mkdir(parents=True, exist_ok=True)

        state_data = self.get_module_states()

        try:
            with open(state_file, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, indent=2, ensure_ascii=False)
            print(f"💾 [STATE] 모듈 상태 저장 완료: {state_file}")
        except Exception as e:
            print(f"❌ [STATE] 모듈 상태 저장 실패: {e}")

    def load_module_states(self):
        """파일에서 모듈 상태 로드"""
        import json
        from pathlib import Path

        state_file = Path("save/module_states.json")
        if not state_file.exists():
            print(f"ℹ️ [STATE] 저장된 모듈 상태 파일 없음: {state_file}")
            return

        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state_data = json.load(f)

            # 상태 복원
            self.module_states['expanded'] = set(state_data.get('expanded', []))
            self.module_states['detached'] = set(state_data.get('detached', []))
            self.module_states['scroll_positions'] = state_data.get('scroll_positions', {})
            self.accordion_mode = state_data.get('accordion_mode', True)

            # UI에 상태 적용
            for title, box in self.module_boxes.items():
                # 펼침/접힘 상태 복원
                if title in self.module_states['expanded']:
                    box.expand(emit_signal=False)
                else:
                    box.collapse(emit_signal=False)

                # 스크롤 위치 복원
                if title in self.module_states['scroll_positions']:
                    scroll_pos = self.module_states['scroll_positions'][title]
                    box.set_scroll_position(scroll_pos)

            print(f"✅ [STATE] 모듈 상태 로드 완료: {len(self.module_states['expanded'])}개 펼침")

        except Exception as e:
            print(f"❌ [STATE] 모듈 상태 로드 실패: {e}")
            import traceback
            traceback.print_exc()
