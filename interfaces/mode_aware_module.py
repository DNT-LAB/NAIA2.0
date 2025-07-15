from abc import ABC, abstractmethod
import json
import os
from typing import Dict, Any

class ModeAwareModule(ABC):
    """모드별 설정 저장/로드 및 가시성 제어를 지원하는 모듈의 기본 인터페이스"""
    
    def __init__(self):
        # 🆕 필수 속성들을 기본값으로 초기화
        self.settings_base_filename = None  # 서브클래스에서 설정 필요
        self.current_mode = "NAI"  # 기본값
        
        # 🆕 필수: 각 모드 호환성 플래그
        if not hasattr(self, 'NAI_compatibility'):
            self.NAI_compatibility = True   # 기본값: NAI 호환
        if not hasattr(self, 'WEBUI_compatibility'):
            self.WEBUI_compatibility = True # 기본값: WEBUI 호환
        
        # UI 가시성 관련
        self.widget = None
        self.is_visible = True
        
    def get_mode_aware_filename(self, mode: str = None) -> str:
        """모드별 설정 파일명 생성"""
        if not self.settings_base_filename:
            raise ValueError(f"{self.__class__.__name__}: settings_base_filename이 설정되지 않았습니다.")
        
        target_mode = mode or self.current_mode
        return os.path.join('save', f'{self.settings_base_filename}_{target_mode}.json')
    
    def save_mode_settings(self, mode: str = None):
        """현재 모드의 설정을 저장"""
        target_mode = mode or self.current_mode
        filename = self.get_mode_aware_filename(target_mode)
        
        try:
            # 현재 설정 수집
            current_settings = self.collect_current_settings()
            
            # 모드별 단일 파일 구조로 저장
            mode_data = {target_mode: current_settings}
            
            # 파일 저장
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(mode_data, f, indent=4, ensure_ascii=False)
                
            print(f"✅ '{self.get_module_name()}' {target_mode} 모드 설정 저장 완료")
            
        except Exception as e:
            print(f"❌ '{self.get_module_name()}' {target_mode} 모드 설정 저장 실패: {e}")
    
    def load_mode_settings(self, mode: str = None):
        """지정된 모드의 설정을 로드"""
        target_mode = mode or self.current_mode
        filename = self.get_mode_aware_filename(target_mode)
        
        try:
            if not os.path.exists(filename):
                print(f"⚠️ '{self.get_module_name()}' {target_mode} 모드 설정 파일이 없습니다.")
                return
            
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 해당 모드의 설정 가져오기
            mode_settings = data.get(target_mode, {})
            if mode_settings:
                self.apply_settings(mode_settings)
                print(f"✅ '{self.get_module_name()}' {target_mode} 모드 설정 로드 완료")
            else:
                print(f"⚠️ '{self.get_module_name()}' {target_mode} 모드 설정이 파일에 없습니다.")
                
        except Exception as e:
            print(f"❌ '{self.get_module_name()}' {target_mode} 모드 설정 로드 실패: {e}")
    
    def is_compatible_with_mode(self, mode: str) -> bool:
        """해당 모드와 호환되는지 확인"""
        if mode == "NAI":
            return getattr(self, 'NAI_compatibility', True)
        elif mode == "WEBUI":
            return getattr(self, 'WEBUI_compatibility', True)
        return False
    
    def update_visibility_for_mode(self, mode: str):
        """🔧 강화된 가시성 업데이트"""
        should_be_visible = self.is_compatible_with_mode(mode)
        
        if self.widget and hasattr(self.widget, 'setVisible'):
            self.widget.setVisible(should_be_visible)
            self.is_visible = should_be_visible
            
            visibility_status = "표시" if should_be_visible else "숨김"
            print(f"🔍 '{self.get_module_name()}' {mode} 모드에서 {visibility_status}")
            
            # 🆕 부모 위젯도 업데이트 (레이아웃 새로고침)
            if self.widget.parent():
                self.widget.parent().update()
        else:
            print(f"⚠️ '{self.get_module_name()}' 위젯이 없어 가시성 제어 불가")
    
    def on_mode_changed(self, old_mode: str, new_mode: str):
        """🔧 강화된 모드 변경 처리"""
        print(f"🔄 '{self.get_module_name()}' 모드 변경: {old_mode} → {new_mode}")
        
        # 1. 이전 모드 설정 저장
        if self.is_compatible_with_mode(old_mode):
            self.save_mode_settings(old_mode)
        
        # 2. 새 모드로 전환
        self.current_mode = new_mode
        
        # 3. 새 모드 설정 로드
        if self.is_compatible_with_mode(new_mode):
            self.load_mode_settings(new_mode)
        
        # 4. 🆕 강화된 가시성 업데이트
        self.update_visibility_for_mode(new_mode)
    
    @abstractmethod
    def collect_current_settings(self) -> Dict[str, Any]:
        """현재 UI 상태에서 설정을 수집하여 반환"""
        pass
    
    @abstractmethod
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 UI에 적용"""
        pass
    
    @abstractmethod
    def get_module_name(self) -> str:
        """모듈 이름 반환 (로깅용)"""
        pass