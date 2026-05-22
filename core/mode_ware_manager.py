from interfaces.mode_aware_module import ModeAwareModule
from typing import Any

class ModeAwareModuleManager:
    """모드 대응 모듈들을 자동으로 관리하는 매니저"""
    
    def __init__(self, app_context: Any):
        self.app_context = app_context
        self.registered_modules = []
    
    def register_module(self, module: ModeAwareModule):
        """모드 대응 모듈 등록"""
        if module not in self.registered_modules:
            self.registered_modules.append(module)
            # AppContext 모드 변경 이벤트 구독
            self.app_context.subscribe_mode_swap(module.on_mode_changed)
            print(f"📝 모드 대응 모듈 등록: {module.get_module_name()}")
            print(f"   - 현재 등록된 모듈 수: {len(self.registered_modules)}")
        else:
            print(f"⚠️ 이미 등록된 모듈: {module.get_module_name()}")
    
    def unregister_module(self, module: ModeAwareModule):
        """모드 대응 모듈 등록 해제"""
        if module in self.registered_modules:
            self.registered_modules.remove(module)
            self.app_context.unsubscribe_mode_swap(module.on_mode_changed)
            print(f"📝 모드 대응 모듈 등록 해제: {module.get_module_name()}")
    
    def save_all_current_mode(self):
        """모든 등록된 모듈의 현재 모드 설정 저장"""
        print(f"💾 모드별 설정 저장 시작 (등록된 모듈: {len(self.registered_modules)}개)")
        current_mode = self.app_context.get_api_mode()
        
        if not self.registered_modules:
            print("⚠️ 등록된 ModeAware 모듈이 없습니다!")
            return
        
        for module in self.registered_modules:
            try:
                # ✅ Save 무시 플래그 확인
                if getattr(module, 'ignore_save_load', False):
                    print(f"  ⏭️ {module.get_module_name()} Save 무시 플래그로 인해 저장 건너뜀")
                    continue
                
                if module.is_compatible_with_mode(current_mode):
                    module.save_mode_settings(current_mode)
                    print(f"  ✅ {module.get_module_name()} 설정 저장 완료")
                else:
                    print(f"  ⏭️ {module.get_module_name()} 현재 모드({current_mode})와 호환되지 않음")
            except Exception as e:
                print(f"  ❌ {module.get_module_name()} 설정 저장 실패: {e}")
    
    def load_all_mode(self, mode: str):
        """모든 등록된 모듈의 지정 모드 설정 로드"""
        print(f"📂 모드별 설정 로드 시작: {mode} (등록된 모듈: {len(self.registered_modules)}개)")
        
        if not self.registered_modules:
            print("⚠️ 등록된 ModeAware 모듈이 없습니다!")
            return
        
        for module in self.registered_modules:
            try:
                # ✅ Save 무시 플래그 확인
                if getattr(module, 'ignore_save_load', False):
                    print(f"  ⏭️ {module.get_module_name()} Save 무시 플래그로 인해 로드 건너뜀")
                    # 가시성 업데이트는 여전히 수행
                    module.update_visibility_for_mode(mode)
                    continue
                
                if module.is_compatible_with_mode(mode):
                    module.load_mode_settings(mode)
                    print(f"  ✅ {module.get_module_name()} 설정 로드 완료")
                else:
                    print(f"  ⏭️ {module.get_module_name()} 대상 모드({mode})와 호환되지 않음")
                # 가시성 업데이트
                module.update_visibility_for_mode(mode)
            except Exception as e:
                print(f"  ❌ {module.get_module_name()} 설정 로드 실패: {e}")
