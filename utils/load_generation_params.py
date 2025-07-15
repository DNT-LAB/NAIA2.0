import json
import os
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from NAIA_cold_v4 import NAIAColdV4  # 순환 import 방지

class GenerationParamsManager:
    """메인 생성 파라미터를 모드별로 저장/로드하는 유틸리티 클래스"""
    
    def __init__(self, main_window: 'NAIAColdV4'):
        self.main_window = main_window
        self.settings_base_filename = "generation_params"
        
        # 호환성 설정 (둘 다 호환)
        self.NAI_compatibility = True
        self.WEBUI_compatibility = True
        
    def get_mode_aware_filename(self, mode: str) -> str:
        """모드별 설정 파일명 생성"""
        return os.path.join('save', f'{self.settings_base_filename}_{mode}.json')
    
    def collect_current_settings(self) -> Dict[str, Any]:
        """메인 윈도우에서 현재 생성 파라미터 수집"""
        try:
            # 기본 파라미터들
            settings = {
                "action": "generate",
                "access_token": "",
                "input": "",
                "negative_prompt": "",
                "random_resolution": False,
                "use_custom_api_params": False,
                "custom_api_params": "",
                "random_resolution_checked": False,
                "auto_fit_resolution_checked": False,
                "resolutions": [
                    "1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216",
                    "1088 x 960", "1152 x 896", "1216 x 832"
                ]
            }
            
            # 메인 윈도우에서 현재 설정된 값들 수집
            mw = self.main_window
            
            # 모델 설정
            if hasattr(mw, 'model_combo') and mw.model_combo:
                settings["model"] = mw.model_combo.currentText()
            else:
                settings["model"] = "NAID4.5F"
            
            # 해상도 설정
            if hasattr(mw, 'resolution_combo') and mw.resolution_combo:
                resolution_text = mw.resolution_combo.currentText()
                settings["resolution"] = resolution_text
                
                # width, height 파싱
                if " x " in resolution_text:
                    try:
                        width_str, height_str = resolution_text.split(" x ")
                        settings["width"] = int(width_str.strip())
                        settings["height"] = int(height_str.strip())
                    except (ValueError, IndexError):
                        settings["width"] = 1024
                        settings["height"] = 1024
                else:
                    settings["width"] = 1024
                    settings["height"] = 1024
            else:
                settings["resolution"] = "1024 x 1024"
                settings["width"] = 1024
                settings["height"] = 1024
            
            # Steps 설정
            if hasattr(mw, 'steps_spinbox') and mw.steps_spinbox:
                settings["steps"] = mw.steps_spinbox.value()
            else:
                settings["steps"] = 28
            
            # CFG Scale 설정
            if hasattr(mw, 'cfg_scale_spinbox') and mw.cfg_scale_spinbox:
                settings["cfg_scale"] = mw.cfg_scale_spinbox.value()
            else:
                settings["cfg_scale"] = 5.0
            
            # CFG Rescale 설정
            if hasattr(mw, 'cfg_rescale_spinbox') and mw.cfg_rescale_spinbox:
                settings["cfg_rescale"] = mw.cfg_rescale_spinbox.value()
            else:
                settings["cfg_rescale"] = 0.4
            
            # Sampler 설정
            if hasattr(mw, 'sampler_combo') and mw.sampler_combo:
                settings["sampler"] = mw.sampler_combo.currentText()
            else:
                settings["sampler"] = "k_euler_ancestral"
            
            # Scheduler 설정
            if hasattr(mw, 'scheduler_combo') and mw.scheduler_combo:
                settings["scheduler"] = mw.scheduler_combo.currentText()
            else:
                settings["scheduler"] = "karras"
            
            # Negative Prompt 설정
            if hasattr(mw, 'main_negative_textedit') and mw.main_negative_textedit:
                settings["negative_prompt"] = mw.main_negative_textedit.toPlainText()
            
            # 고급 옵션들 (체크박스)
            advanced_options = ["SMEA", "DYN", "VAR+", "DECRISP"]
            for option in advanced_options:
                checkbox_attr = f'{option.lower().replace("+", "_plus")}_checkbox'
                if hasattr(mw, checkbox_attr):
                    checkbox = getattr(mw, checkbox_attr)
                    settings[option] = checkbox.isChecked() if checkbox else False
                else:
                    settings[option] = False
            
            # 생성 제어 체크박스들
            if hasattr(mw, 'generation_checkboxes') and mw.generation_checkboxes:
                gen_checkboxes = mw.generation_checkboxes
                settings["gen_cb_프롬프트 고정"] = gen_checkboxes.get("프롬프트 고정", {}).get('checked', False) if isinstance(gen_checkboxes.get("프롬프트 고정"), dict) else gen_checkboxes.get("프롬프트 고정", False) if hasattr(gen_checkboxes.get("프롬프트 고정"), 'isChecked') else False
                settings["gen_cb_자동 생성"] = gen_checkboxes.get("자동 생성", {}).get('checked', False) if isinstance(gen_checkboxes.get("자동 생성"), dict) else gen_checkboxes.get("자동 생성", False) if hasattr(gen_checkboxes.get("자동 생성"), 'isChecked') else False
                settings["gen_cb_터보 옵션"] = gen_checkboxes.get("터보 옵션", {}).get('checked', False) if isinstance(gen_checkboxes.get("터보 옵션"), dict) else gen_checkboxes.get("터보 옵션", False) if hasattr(gen_checkboxes.get("터보 옵션"), 'isChecked') else False
                settings["gen_cb_와일드카드 단독 모드"] = gen_checkboxes.get("와일드카드 단독 모드", {}).get('checked', False) if isinstance(gen_checkboxes.get("와일드카드 단독 모드"), dict) else gen_checkboxes.get("와일드카드 단독 모드", False) if hasattr(gen_checkboxes.get("와일드카드 단독 모드"), 'isChecked') else False
                
                # 실제 QCheckBox 객체인 경우 처리
                for key in ["프롬프트 고정", "자동 생성", "터보 옵션", "와일드카드 단독 모드"]:
                    checkbox = gen_checkboxes.get(key)
                    if hasattr(checkbox, 'isChecked'):
                        settings[f"gen_cb_{key}"] = checkbox.isChecked()
            else:
                settings["gen_cb_프롬프트 고정"] = False
                settings["gen_cb_자동 생성"] = False
                settings["gen_cb_터보 옵션"] = False
                settings["gen_cb_와일드카드 단독 모드"] = False
            
            return settings
            
        except Exception as e:
            print(f"❌ 생성 파라미터 수집 중 오류: {e}")
            return self._get_default_settings()
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """기본 설정값 반환"""
        return {
            "action": "generate",
            "access_token": "",
            "input": "",
            "negative_prompt": "",
            "model": "NAID4.5F",
            "scheduler": "karras",
            "sampler": "k_euler_ancestral",
            "resolution": "1024 x 1024",
            "width": 1024,
            "height": 1024,
            "random_resolution": False,
            "steps": 28,
            "cfg_scale": 5.0,
            "cfg_rescale": 0.4,
            "SMEA": False,
            "DYN": False,
            "VAR+": False,
            "DECRISP": False,
            "use_custom_api_params": False,
            "custom_api_params": "",
            "gen_cb_프롬프트 고정": False,
            "gen_cb_자동 생성": False,
            "gen_cb_터보 옵션": False,
            "gen_cb_와일드카드 단독 모드": False,
            "random_resolution_checked": False,
            "auto_fit_resolution_checked": False,
            "resolutions": [
                "1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216",
                "1088 x 960", "1152 x 896", "1216 x 832"
            ]
        }
    
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 메인 윈도우 UI에 적용"""
        try:
            mw = self.main_window
            
            # 모델 설정
            if hasattr(mw, 'model_combo') and mw.model_combo:
                model = settings.get("model", "NAID4.5F")
                index = mw.model_combo.findText(model)
                if index >= 0:
                    mw.model_combo.setCurrentIndex(index)
            
            # 해상도 설정
            if hasattr(mw, 'resolution_combo') and mw.resolution_combo:
                resolution = settings.get("resolution", "1024 x 1024")
                index = mw.resolution_combo.findText(resolution)
                if index >= 0:
                    mw.resolution_combo.setCurrentIndex(index)
            
            # Steps 설정
            if hasattr(mw, 'steps_spinbox') and mw.steps_spinbox:
                mw.steps_spinbox.setValue(settings.get("steps", 28))
            
            # CFG Scale 설정
            if hasattr(mw, 'cfg_scale_spinbox') and mw.cfg_scale_spinbox:
                mw.cfg_scale_spinbox.setValue(settings.get("cfg_scale", 5.0))
            
            # CFG Rescale 설정
            if hasattr(mw, 'cfg_rescale_spinbox') and mw.cfg_rescale_spinbox:
                mw.cfg_rescale_spinbox.setValue(settings.get("cfg_rescale", 0.4))
            
            # Sampler 설정
            if hasattr(mw, 'sampler_combo') and mw.sampler_combo:
                sampler = settings.get("sampler", "k_euler_ancestral")
                index = mw.sampler_combo.findText(sampler)
                if index >= 0:
                    mw.sampler_combo.setCurrentIndex(index)
            
            # Scheduler 설정
            if hasattr(mw, 'scheduler_combo') and mw.scheduler_combo:
                scheduler = settings.get("scheduler", "karras")
                index = mw.scheduler_combo.findText(scheduler)
                if index >= 0:
                    mw.scheduler_combo.setCurrentIndex(index)
            
            # Negative Prompt 설정
            if hasattr(mw, 'main_negative_textedit') and mw.main_negative_textedit:
                mw.main_negative_textedit.setPlainText(settings.get("negative_prompt", ""))
            
            # 고급 옵션들 (체크박스)
            advanced_options = ["SMEA", "DYN", "VAR+", "DECRISP"]
            for option in advanced_options:
                checkbox_attr = f'{option.lower().replace("+", "_plus")}_checkbox'
                if hasattr(mw, checkbox_attr):
                    checkbox = getattr(mw, checkbox_attr)
                    if checkbox and hasattr(checkbox, 'setChecked'):
                        checkbox.setChecked(settings.get(option, False))
            
            # 생성 제어 체크박스들
            if hasattr(mw, 'generation_checkboxes') and mw.generation_checkboxes:
                checkbox_settings = {
                    "프롬프트 고정": settings.get("gen_cb_프롬프트 고정", False),
                    "자동 생성": settings.get("gen_cb_자동 생성", False),
                    "터보 옵션": settings.get("gen_cb_터보 옵션", False),
                    "와일드카드 단독 모드": settings.get("gen_cb_와일드카드 단독 모드", False),
                }
                
                for checkbox_name, should_check in checkbox_settings.items():
                    checkbox = mw.generation_checkboxes.get(checkbox_name)
                    if checkbox and hasattr(checkbox, 'setChecked'):
                        checkbox.setChecked(should_check)
            
            print(f"✅ 생성 파라미터 UI 적용 완료")
            
        except Exception as e:
            print(f"❌ 생성 파라미터 UI 적용 중 오류: {e}")
    
    def save_mode_settings(self, mode: str):
        """현재 모드의 설정을 저장"""
        filename = self.get_mode_aware_filename(mode)
        
        try:
            # 현재 설정 수집
            current_settings = self.collect_current_settings()
            
            # 모드별 단일 파일 구조로 저장
            mode_data = {mode: current_settings}
            
            # 파일 저장
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(mode_data, f, indent=4, ensure_ascii=False)
                
            print(f"✅ 메인 생성 파라미터 {mode} 모드 설정 저장 완료")
            
        except Exception as e:
            print(f"❌ 메인 생성 파라미터 {mode} 모드 설정 저장 실패: {e}")
    
    def load_mode_settings(self, mode: str):
        """지정된 모드의 설정을 로드"""
        filename = self.get_mode_aware_filename(mode)
        
        try:
            if not os.path.exists(filename):
                print(f"⚠️ 메인 생성 파라미터 {mode} 모드 설정 파일이 없습니다. 기본값 사용.")
                # 기본값 적용
                default_settings = self._get_default_settings()
                self.apply_settings(default_settings)
                return
            
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 해당 모드의 설정 가져오기
            mode_settings = data.get(mode, {})
            if mode_settings:
                self.apply_settings(mode_settings)
                print(f"✅ 메인 생성 파라미터 {mode} 모드 설정 로드 완료")
            else:
                print(f"⚠️ 메인 생성 파라미터 {mode} 모드 설정이 파일에 없습니다. 기본값 사용.")
                default_settings = self._get_default_settings()
                self.apply_settings(default_settings)
                
        except Exception as e:
            print(f"❌ 메인 생성 파라미터 {mode} 모드 설정 로드 실패: {e}")
            # 오류 시 기본값 적용
            default_settings = self._get_default_settings()
            self.apply_settings(default_settings)
    
    def is_compatible_with_mode(self, mode: str) -> bool:
        """해당 모드와 호환되는지 확인"""
        if mode == "NAI":
            return self.NAI_compatibility
        elif mode == "WEBUI":
            return self.WEBUI_compatibility
        return False
    
    def on_mode_changed(self, old_mode: str, new_mode: str):
        """모드 변경 시 호출되는 콜백"""
        print(f"🔄 메인 생성 파라미터 모드 변경: {old_mode} → {new_mode}")
        
        # 1. 이전 모드와 호환되었던 경우에만 설정 저장
        if self.is_compatible_with_mode(old_mode):
            self.save_mode_settings(old_mode)
        
        # 2. 새 모드와 호환되는 경우에만 설정 로드
        if self.is_compatible_with_mode(new_mode):
            self.load_mode_settings(new_mode)
