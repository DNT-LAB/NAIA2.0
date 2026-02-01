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
        self.COMFYUI_compatibility = True
        
    def get_mode_aware_filename(self, mode: str) -> str:
        """모드별 설정 파일명 생성"""
        return os.path.join('save', f'{self.settings_base_filename}_{mode}.json')
    
    def collect_current_settings(self) -> Dict[str, Any]:
        """메인 윈도우에서 현재 생성 파라미터 수집"""
        try:
            mw = self.main_window

            # 기본 파라미터들로 시작
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
            
            # Input (main_prompt_textedit) 수집
            if hasattr(mw, 'main_prompt_textedit') and mw.main_prompt_textedit:
                settings["input"] = mw.main_prompt_textedit.toPlainText()
            
            # Negative Prompt 수집
            if hasattr(mw, 'negative_prompt_textedit') and mw.negative_prompt_textedit:
                settings["negative_prompt"] = mw.negative_prompt_textedit.toPlainText()
            
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
            
            # 🔧 수정: Steps 설정 - 실제 위젯명(steps_spinbox) 사용
            if hasattr(mw, 'steps_spinbox') and mw.steps_spinbox:
                try:
                    settings["steps"] = mw.steps_spinbox.value()
                except AttributeError:
                    settings["steps"] = 28
            else:
                settings["steps"] = 28
            
            # 🔧 수정: CFG Scale 설정 - 슬라이더 값을 적절히 변환
            if hasattr(mw, 'cfg_scale_slider') and mw.cfg_scale_slider:
                try:
                    # 슬라이더 값(10~300)을 실제 CFG 값(1.0~30.0)으로 변환
                    settings["cfg_scale"] = mw.cfg_scale_slider.value() / 10.0
                except AttributeError:
                    settings["cfg_scale"] = 5.0
            else:
                settings["cfg_scale"] = 5.0
            
            # 🔧 수정: CFG Rescale 설정 - 슬라이더 값을 적절히 변환
            if hasattr(mw, 'cfg_rescale_slider') and mw.cfg_rescale_slider:
                try:
                    # 슬라이더 값(0~100)을 실제 rescale 값(0.0~1.0)으로 변환
                    settings["cfg_rescale"] = mw.cfg_rescale_slider.value() / 100.0
                except AttributeError:
                    settings["cfg_rescale"] = 0.4
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

            # Seed 관련 설정
            if hasattr(mw, 'seed_input') and mw.seed_input:
                try:
                    settings["seed"] = int(mw.seed_input.text())
                except (ValueError, AttributeError):
                    settings["seed"] = -1
            else:
                settings["seed"] = -1

            if hasattr(mw, 'seed_fix_checkbox') and mw.seed_fix_checkbox:
                settings["seed_fixed"] = mw.seed_fix_checkbox.isChecked()
            else:
                settings["seed_fixed"] = False
            
            # 🔧 수정: 고급 옵션들 - 딕셔너리에서 직접 접근
            if hasattr(mw, 'advanced_checkboxes') and mw.advanced_checkboxes:
                advanced_options = ["SMEA", "DYN", "VAR+", "DECRISP"]
                for option in advanced_options:
                    checkbox = mw.advanced_checkboxes.get(option)
                    if checkbox and hasattr(checkbox, 'isChecked'):
                        settings[option] = checkbox.isChecked()
                    else:
                        settings[option] = False
            else:
                # 기본값 설정
                for option in ["SMEA", "DYN", "VAR+", "DECRISP"]:
                    settings[option] = False
            
            # Random Resolution 체크박스
            if hasattr(mw, 'random_resolution_checkbox') and mw.random_resolution_checkbox:
                settings["random_resolution"] = mw.random_resolution_checkbox.isChecked()
            else:
                settings["random_resolution"] = False

            # Auto Fit Resolution 체크박스
            if hasattr(mw, 'auto_fit_resolution_checkbox') and mw.auto_fit_resolution_checkbox:
                settings["auto_fit_resolution_checked"] = mw.auto_fit_resolution_checkbox.isChecked()
            else:
                settings["auto_fit_resolution_checked"] = False
            
            # 커스텀 API 파라미터
            if hasattr(mw, 'custom_api_checkbox') and mw.custom_api_checkbox:
                settings["use_custom_api_params"] = mw.custom_api_checkbox.isChecked()
            else:
                settings["use_custom_api_params"] = False

            if hasattr(mw, 'custom_script_textbox') and mw.custom_script_textbox:
                settings["custom_api_params"] = mw.custom_script_textbox.toPlainText()
            else:
                settings["custom_api_params"] = ""
            
            # 생성 제어 체크박스들
            if hasattr(mw, 'generation_checkboxes') and mw.generation_checkboxes:
                gen_checkboxes = mw.generation_checkboxes
                
                checkbox_keys = ["프롬프트 고정", "자동 생성", "터보 옵션", "와일드카드 단독 모드"]
                for key in checkbox_keys:
                    checkbox = gen_checkboxes.get(key)
                    if checkbox and hasattr(checkbox, 'isChecked'):
                        settings[f"gen_cb_{key}"] = checkbox.isChecked()
                    else:
                        settings[f"gen_cb_{key}"] = False
            else:
                settings["gen_cb_프롬프트 고정"] = False
                settings["gen_cb_자동 생성"] = False
                settings["gen_cb_터보 옵션"] = False
                settings["gen_cb_와일드카드 단독 모드"] = False

            # 🆕 ComfyUI 모드일 때 ComfyUI 전용 파라미터 수집 (라디오 버튼 기반)
            if hasattr(mw, 'eps_radio') and hasattr(mw, 'v_pred_radio') and hasattr(mw, 'anima_radio'):
                # 선택된 라디오 버튼 확인
                if mw.eps_radio.isChecked():
                    settings["sampling_mode"] = "eps"
                elif mw.v_pred_radio.isChecked():
                    settings["sampling_mode"] = "v_prediction"
                elif mw.anima_radio.isChecked():
                    settings["sampling_mode"] = "anima"
                else:
                    settings["sampling_mode"] = "eps"  # 기본값
            else:
                settings["sampling_mode"] = "eps"  # 기본값

            # WEBUI 전용 파라미터 수집
            if hasattr(mw, 'enable_hr_checkbox'):
                settings["enable_hr"] = mw.enable_hr_checkbox.isChecked()
            else:
                settings["enable_hr"] = False
            
            if hasattr(mw, 'hr_scale_spinbox'):
                settings["hr_scale"] = mw.hr_scale_spinbox.value()
            else:
                settings["hr_scale"] = 1.5
            
            if hasattr(mw, 'hr_upscaler_combo'):
                settings["hr_upscaler"] = mw.hr_upscaler_combo.currentText()
            else:
                settings["hr_upscaler"] = "Lanczos"
            
            if hasattr(mw, 'denoising_strength_slider'):
                settings["denoising_strength"] = mw.denoising_strength_slider.value() / 100.0
            else:
                settings["denoising_strength"] = 0.5
            
            # 🔥 추가: hires_steps 파라미터 수집
            if hasattr(mw, 'hires_steps_spinbox'):
                settings["hires_steps"] = mw.hires_steps_spinbox.value()
            else:
                settings["hires_steps"] = 0
            
            return settings
            
        except Exception as e:
            print(f"❌ 생성 파라미터 수집 중 오류: {e}")
            return self._get_default_settings()

    def _get_default_settings(self) -> Dict[str, Any]:
        """기본 설정값 반환 (모든 파라미터 포함)"""
        return {
            # 기본 액션 정보
            "action": "generate",
            "access_token": "",
            
            # 프롬프트 관련
            "input": "",
            "negative_prompt": "",
            
            # 모델 및 샘플링 설정
            "model": "NAID4.5F",
            "scheduler": "karras",
            "sampler": "k_euler_ancestral",
            
            # 해상도 관련
            "resolution": "1024 x 1024",
            "width": 1024,
            "height": 1024,
            "random_resolution": False,
            "auto_fit_resolution_checked": False,
            "resolutions": [
                "1024 x 1024", "960 x 1088", "896 x 1152", "832 x 1216",
                "1088 x 960", "1152 x 896", "1216 x 832"
            ],
            
            # 생성 파라미터
            "steps": 28,
            "cfg_scale": 5.0,
            "cfg_rescale": 0.4,
            
            # 시드 관련
            "seed": -1,
            "seed_fixed": False,
            
            # NAI 고급 옵션들
            "SMEA": False,
            "DYN": False,
            "VAR+": False,
            "DECRISP": False,
            
            # 커스텀 API 파라미터
            "use_custom_api_params": False,
            "custom_api_params": "",
            
            # 생성 제어 체크박스들
            "gen_cb_프롬프트 고정": False,
            "gen_cb_자동 생성": False,
            "gen_cb_터보 옵션": False,
            "gen_cb_와일드카드 단독 모드": False,

            # ComfyUI 샘플링 모드 (eps, v_prediction, anima)
            "sampling_mode": "eps",
            
            # 기타 체크박스들
            "random_resolution_checked": False,
            
            # WEBUI 전용 파라미터들
            "enable_hr": False,
            "hr_scale": 1.5,
            "hr_upscaler": "Lanczos",
            "denoising_strength": 0.5,
            "hires_steps": 14,  # 🔥 추가
        }

    
    def apply_settings(self, settings: Dict[str, Any]):
        """설정을 메인 윈도우 UI에 적용"""
        try:
            mw = self.main_window
            
            # Input (main_prompt_textedit) 로드 
            if hasattr(mw, 'main_prompt_textedit') and mw.main_prompt_textedit:
                mw.main_prompt_textedit.setPlainText(settings.get("input", ""))
            
            # Negative Prompt 설정
            if hasattr(mw, 'negative_prompt_textedit') and mw.negative_prompt_textedit:
                mw.negative_prompt_textedit.setPlainText(settings.get("negative_prompt", ""))
            
            # 🔧 수정: 모델 설정 - 현재 목록에 있는 항목만 선택
            if hasattr(mw, 'model_combo') and mw.model_combo:
                model = settings.get("model", "NAID4.5F")
                index = mw.model_combo.findText(model)
                if index >= 0:
                    mw.model_combo.setCurrentIndex(index)
                    print(f"✅ 모델 설정 적용: {model}")
            
            # 해상도 설정
            if hasattr(mw, 'resolution_combo') and mw.resolution_combo:
                resolution = settings.get("resolution", "1024 x 1024")
                index = mw.resolution_combo.findText(resolution)
                if index >= 0:
                    mw.resolution_combo.setCurrentIndex(index)
            
            # 🔧 수정: Steps 설정 - 실제 위젯명(steps_spinbox) 사용
            if hasattr(mw, 'steps_spinbox') and mw.steps_spinbox:
                mw.steps_spinbox.setValue(int(settings.get("steps", 28)))
            
            # 🔧 수정: CFG Scale 설정 - 슬라이더 값으로 변환하여 설정
            if hasattr(mw, 'cfg_scale_slider') and mw.cfg_scale_slider:
                cfg_value = float(settings.get("cfg_scale", 5.0))
                # 실제 CFG 값(1.0~30.0)을 슬라이더 값(10~300)으로 변환
                slider_value = int(cfg_value * 10)
                mw.cfg_scale_slider.setValue(slider_value)
            
            # 🔧 수정: CFG Rescale 설정 - 슬라이더 값으로 변환하여 설정
            if hasattr(mw, 'cfg_rescale_slider') and mw.cfg_rescale_slider:
                rescale_value = float(settings.get("cfg_rescale", 0.4))
                # 실제 rescale 값(0.0~1.0)을 슬라이더 값(0~100)으로 변환
                slider_value = int(rescale_value * 100)
                mw.cfg_rescale_slider.setValue(slider_value)
            
            # 🔧 수정: Sampler 설정 - 현재 목록에 있는 항목만 선택
            if hasattr(mw, 'sampler_combo') and mw.sampler_combo:
                sampler = settings.get("sampler", "k_euler_ancestral")
                index = mw.sampler_combo.findText(sampler)
                if index >= 0:
                    mw.sampler_combo.setCurrentIndex(index)
                    print(f"✅ 샘플러 설정 적용: {sampler}")
            
            # 🔧 수정: Scheduler 설정 - 현재 목록에 있는 항목만 선택
            if hasattr(mw, 'scheduler_combo') and mw.scheduler_combo:
                scheduler = settings.get("scheduler", "karras")
                index = mw.scheduler_combo.findText(scheduler)
                if index >= 0:
                    mw.scheduler_combo.setCurrentIndex(index)
                    print(f"✅ 스케줄러 설정 적용: {scheduler}")
            
            # Seed 관련 설정 적용
            if hasattr(mw, 'seed_input') and mw.seed_input:
                seed_value = settings.get("seed", -1)
                mw.seed_input.setText(str(seed_value))

            if hasattr(mw, 'seed_fix_checkbox') and mw.seed_fix_checkbox:
                mw.seed_fix_checkbox.setChecked(settings.get("seed_fixed", False))
            
            # 🔧 수정: 고급 옵션들 - 딕셔너리에서 직접 접근
            if hasattr(mw, 'advanced_checkboxes') and mw.advanced_checkboxes:
                advanced_options = ["SMEA", "DYN", "VAR+", "DECRISP"]
                for option in advanced_options:
                    checkbox = mw.advanced_checkboxes.get(option)
                    if checkbox and hasattr(checkbox, 'setChecked'):
                        checkbox.setChecked(settings.get(option, False))
            
            # Random Resolution 체크박스 적용
            if hasattr(mw, 'random_resolution_checkbox') and mw.random_resolution_checkbox:
                mw.random_resolution_checkbox.setChecked(settings.get("random_resolution", False))

            # Auto Fit Resolution 체크박스 적용
            if hasattr(mw, 'auto_fit_resolution_checkbox') and mw.auto_fit_resolution_checkbox:
                mw.auto_fit_resolution_checkbox.setChecked(settings.get("auto_fit_resolution_checked", False))
            
            # 커스텀 API 파라미터 적용
            if hasattr(mw, 'custom_api_checkbox') and mw.custom_api_checkbox:
                mw.custom_api_checkbox.setChecked(settings.get("use_custom_api_params", False))

            if hasattr(mw, 'custom_script_textbox') and mw.custom_script_textbox:
                mw.custom_script_textbox.setPlainText(settings.get("custom_api_params", ""))
            
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

            # WEBUI 전용 파라미터 적용
            if hasattr(mw, 'enable_hr_checkbox'):
                mw.enable_hr_checkbox.setChecked(settings.get("enable_hr", False))
            
            if hasattr(mw, 'hr_scale_spinbox'):
                mw.hr_scale_spinbox.setValue(settings.get("hr_scale", 1.5))
            
            # 🔧 수정: 업스케일러 설정 - 현재 목록에 있는 항목만 선택
            if hasattr(mw, 'hr_upscaler_combo'):
                hr_upscaler = settings.get("hr_upscaler", "Lanczos")
                index = mw.hr_upscaler_combo.findText(hr_upscaler)
                if index >= 0:
                    mw.hr_upscaler_combo.setCurrentIndex(index)
                    print(f"✅ 업스케일러 설정 적용: {hr_upscaler}")
            
            if hasattr(mw, 'denoising_strength_slider'):
                denoising_value = int(settings.get("denoising_strength", 0.5) * 100)
                mw.denoising_strength_slider.setValue(denoising_value)
            
            # 🔥 추가: hires_steps 파라미터 적용
            if hasattr(mw, 'hires_steps_spinbox'):
                mw.hires_steps_spinbox.setValue(settings.get("hires_steps", 0))

            # ComfyUI 샘플링 모드 라디오 버튼 설정
            if hasattr(mw, 'eps_radio') and hasattr(mw, 'v_pred_radio') and hasattr(mw, 'anima_radio'):
                sampling_mode = settings.get("sampling_mode", "eps")

                # 적절한 라디오 버튼 선택
                if sampling_mode == "eps":
                    mw.eps_radio.setChecked(True)
                elif sampling_mode == "v_prediction":
                    mw.v_pred_radio.setChecked(True)
                elif sampling_mode == "anima":
                    mw.anima_radio.setChecked(True)
                else:
                    mw.eps_radio.setChecked(True)  # 기본값

                print(f"✅ ComfyUI 샘플링 모드 설정: {sampling_mode}")
            
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
                # 🔧 수정: 모드 전환 로직을 먼저 실행
                if mode == "WEBUI":
                    self.load_webui_dynamic_options()
                    self.update_ui_for_webui_mode()
                elif mode == "NAI":
                    self.update_ui_for_nai_mode()
                elif mode == "COMFYUI":  # 🆕 ComfyUI 모드 추가
                    self.load_comfyui_dynamic_options()
                    self.update_ui_for_comfyui_mode()
                self.apply_settings(default_settings)
                return
            
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 해당 모드의 설정 가져오기
            mode_settings = data.get(mode, {})
            if mode_settings:
                # 🔧 수정: 모드 전환 로직을 먼저 실행 후 설정 적용
                if mode == "WEBUI":
                    self.load_webui_dynamic_options()
                    self.update_ui_for_webui_mode()
                elif mode == "NAI":
                    self.update_ui_for_nai_mode()
                elif mode == "COMFYUI":  # 🆕 ComfyUI 모드 추가
                    self.load_comfyui_dynamic_options()
                    self.update_ui_for_comfyui_mode()
                
                # 모드 전환 완료 후 설정 적용
                self.apply_settings(mode_settings)
                print(f"✅ 메인 생성 파라미터 {mode} 모드 설정 로드 완료")
            else:
                print(f"⚠️ 메인 생성 파라미터 {mode} 모드 설정이 파일에 없습니다. 기본값 사용.")
                # 🔧 수정: 기본값 적용 시에도 모드 전환 로직 실행
                if mode == "WEBUI":
                    self.load_webui_dynamic_options()
                    self.update_ui_for_webui_mode()
                elif mode == "NAI":
                    self.update_ui_for_nai_mode()
                elif mode == "COMFYUI":  # 🆕 ComfyUI 모드 추가
                    self.load_comfyui_dynamic_options()
                    self.update_ui_for_comfyui_mode()
                default_settings = self._get_default_settings()
                self.apply_settings(default_settings)
                
        except Exception as e:
            print(f"❌ 메인 생성 파라미터 {mode} 모드 설정 로드 실패: {e}")
            # 오류 시 기본값 적용
            if mode == "WEBUI":
                self.load_webui_dynamic_options()
                self.update_ui_for_webui_mode()
            elif mode == "NAI":
                self.update_ui_for_nai_mode()
            elif mode == "COMFYUI":  # 🆕 ComfyUI 모드 추가
                self.load_comfyui_dynamic_options()
                self.update_ui_for_comfyui_mode()
            default_settings = self._get_default_settings()
            self.apply_settings(default_settings)
    
    def is_compatible_with_mode(self, mode: str) -> bool:
        """주어진 모드와 현재 설정이 호환되는지 확인 (ComfyUI 지원 추가)"""
        if mode == "NAI":
            return self.NAI_compatibility
        elif mode == "WEBUI":
            return self.WEBUI_compatibility
        elif mode == "COMFYUI":  # 🆕 ComfyUI 호환성 확인
            return self.COMFYUI_compatibility
        return False
    
    def on_mode_changed(self, old_mode: str, new_mode: str):
        """API 모드 변경 시 호출되는 콜백 (ComfyUI 지원 추가)"""
        print(f"🔄 메인 생성 파라미터 모드 변경: {old_mode} → {new_mode}")
        
        # 1. 이전 모드와 호환되었던 경우에만 설정 저장
        if self.is_compatible_with_mode(old_mode):
            self.save_mode_settings(old_mode)
        
        # 2. 새 모드와 호환되는 경우에만 설정 로드
        # load_mode_settings 내부에서 이미 load_webui_dynamic_options를 호출하므로
        # 여기서는 추가로 호출하지 않음
        if self.is_compatible_with_mode(new_mode):
            self.load_mode_settings(new_mode)
        else:
            # 호환되지 않는 경우에만 UI 업데이트
            if new_mode == "NAI":
                self.update_ui_for_nai_mode()
            elif new_mode == "WEBUI":
                self.load_webui_dynamic_options()
                self.update_ui_for_webui_mode()
            elif new_mode == "COMFYUI":
                self.load_comfyui_dynamic_options()
                self.update_ui_for_comfyui_mode()

    def load_webui_dynamic_options(self):
        """WEBUI API에서 동적 옵션들을 로드하여 UI에 적용"""
        try:
            from core.webui_utils import WebuiAPIUtils
            
            # 키링에서 WEBUI URL 가져오기
            webui_url = self.main_window.app_context.secure_token_manager.get_token('webui_url')
            if not webui_url:
                print("⚠️ WEBUI URL이 설정되지 않았습니다.")
                return
            if not webui_url.startswith("http"):
                webui_url = "https://" + webui_url if "127.0" not in webui_url else "http://" + webui_url
            
            mw = self.main_window
            
            # 1. 모델 리스트 및 현재 모델 업데이트
            model_list = WebuiAPIUtils.get_model_list(webui_url)
            current_model = WebuiAPIUtils.get_current_model(webui_url)
            
            if model_list and hasattr(mw, 'model_combo'):
                # 🔧 수정: 현재 선택값 보존
                current_model_text = mw.model_combo.currentText()
                mw.model_combo.clear()
                mw.model_combo.addItems(model_list)
                
                # 복원 우선순위: 1) API 현재 모델, 2) 이전 선택값, 3) 첫 번째 항목
                if current_model:
                    index = mw.model_combo.findText(current_model)
                    if index >= 0:
                        mw.model_combo.setCurrentIndex(index)
                        print(f"✅ 모델을 API 현재 모델로 설정: {current_model}")
                    else:
                        # API 현재 모델이 리스트에 없을 때 이전 선택값 시도
                        index = mw.model_combo.findText(current_model_text)
                        if index >= 0:
                            mw.model_combo.setCurrentIndex(index)
                            print(f"✅ 모델을 이전 선택값으로 복원: {current_model_text}")
                else:
                    # API 현재 모델이 없을 때 이전 선택값 시도
                    index = mw.model_combo.findText(current_model_text)
                    if index >= 0:
                        mw.model_combo.setCurrentIndex(index)
                        print(f"✅ 모델을 이전 선택값으로 복원: {current_model_text}")
                
                print(f"✅ WEBUI 모델 목록 업데이트: {len(model_list)}개")
            
            # 2. 샘플러 리스트 업데이트
            sampler_list = WebuiAPIUtils.get_sampler_list(webui_url)
            if sampler_list and hasattr(mw, 'sampler_combo'):
                # 🔧 수정: 현재 선택값 보존 후 콤보박스 업데이트
                current_sampler = mw.sampler_combo.currentText()
                mw.sampler_combo.clear()
                mw.sampler_combo.addItems(sampler_list)
                
                # 이전 선택값 복원 시도
                index = mw.sampler_combo.findText(current_sampler)
                if index >= 0:
                    mw.sampler_combo.setCurrentIndex(index)
                    print(f"✅ 샘플러 복원: {current_sampler}")
                else:
                    # 기본값 설정 (Euler a)
                    euler_index = mw.sampler_combo.findText("Euler a")
                    if euler_index >= 0:
                        mw.sampler_combo.setCurrentIndex(euler_index)
                        print(f"✅ 샘플러를 기본값으로 설정: Euler a")
                
                print(f"✅ WEBUI 샘플러 목록 업데이트: {len(sampler_list)}개")
            
            # 3. 스케줄러 리스트 업데이트
            scheduler_list = WebuiAPIUtils.get_schedulers_list(webui_url)
            if scheduler_list and hasattr(mw, 'scheduler_combo'):
                # 🔧 수정: 현재 선택값 보존 후 콤보박스 업데이트
                current_scheduler = mw.scheduler_combo.currentText()
                mw.scheduler_combo.clear()
                mw.scheduler_combo.addItems(scheduler_list)
                
                # 이전 선택값 복원 시도
                index = mw.scheduler_combo.findText(current_scheduler)
                if index >= 0:
                    mw.scheduler_combo.setCurrentIndex(index)
                    print(f"✅ 스케줄러 복원: {current_scheduler}")
                else:
                    # 기본값 설정 (SGM Uniform)
                    sgm_index = mw.scheduler_combo.findText("SGM Uniform")
                    if sgm_index >= 0:
                        mw.scheduler_combo.setCurrentIndex(sgm_index)
                        print(f"✅ 스케줄러를 기본값으로 설정: SGM Uniform")
                
                print(f"✅ WEBUI 스케줄러 목록 업데이트: {len(scheduler_list)}개")
            
            # 4. 업스케일러 리스트 업데이트 (Hires-fix용)
            upscaler_list = WebuiAPIUtils.get_upscaler_list(webui_url)
            if upscaler_list and hasattr(mw, 'hr_upscaler_combo'):
                # 🔧 수정: 현재 선택값 보존 후 콤보박스 업데이트
                current_upscaler = mw.hr_upscaler_combo.currentText()
                mw.hr_upscaler_combo.clear()
                mw.hr_upscaler_combo.addItems(upscaler_list)
                
                # 이전 선택값 복원 시도
                index = mw.hr_upscaler_combo.findText(current_upscaler)
                if index >= 0:
                    mw.hr_upscaler_combo.setCurrentIndex(index)
                    print(f"✅ 업스케일러 복원: {current_upscaler}")
                else:
                    # 기본값 설정 (첫 번째 항목)
                    if mw.hr_upscaler_combo.count() > 0:
                        mw.hr_upscaler_combo.setCurrentIndex(0)
                        print(f"✅ 업스케일러를 기본값으로 설정: {mw.hr_upscaler_combo.currentText()}")
                
                print(f"✅ WEBUI 업스케일러 목록 업데이트: {len(upscaler_list)}개")
            
        except Exception as e:
            print(f"❌ WEBUI 동적 옵션 로드 실패: {e}")

    def load_comfyui_dynamic_options(self):
        """🆕 ComfyUI API에서 동적 옵션들을 로드하여 UI에 적용"""
        try:
            from core.comfyui_utils import ComfyUIAPIUtils
            
            # 키링에서 ComfyUI URL 가져오기
            comfyui_url = self.main_window.app_context.secure_token_manager.get_token('comfyui_url')
            if not comfyui_url:
                print("⚠️ ComfyUI URL이 설정되지 않았습니다.")
                return
            
            # URL 정규화
            if not comfyui_url.startswith("http"):
                comfyui_url = f"http://{comfyui_url}"
            
            mw = self.main_window
            
            # 1. 모델 리스트 업데이트
            model_list = ComfyUIAPIUtils.get_model_list(comfyui_url)
            if model_list and hasattr(mw, 'model_combo'):
                # 현재 선택값 보존
                current_model = mw.model_combo.currentText()
                mw.model_combo.clear()
                mw.model_combo.addItems(model_list)
                
                # 이전 선택값 복원 시도
                index = mw.model_combo.findText(current_model)
                if index >= 0:
                    mw.model_combo.setCurrentIndex(index)
                    print(f"✅ ComfyUI 모델 복원: {current_model}")
                else:
                    # 기본값 설정 (첫 번째 모델)
                    if mw.model_combo.count() > 0:
                        mw.model_combo.setCurrentIndex(0)
                        print(f"✅ ComfyUI 모델을 기본값으로 설정: {mw.model_combo.currentText()}")
                
                print(f"✅ ComfyUI 모델 목록 업데이트: {len(model_list)}개")
            else:
                print("⚠️ ComfyUI 모델 목록을 가져올 수 없습니다.")
            
            # 2. 샘플러 리스트 업데이트
            sampler_list = ComfyUIAPIUtils.get_sampler_list(comfyui_url)
            if sampler_list and hasattr(mw, 'sampler_combo'):
                # 현재 선택값 보존
                current_sampler = mw.sampler_combo.currentText()
                mw.sampler_combo.clear()
                mw.sampler_combo.addItems(sampler_list)
                
                # 이전 선택값 복원 시도
                index = mw.sampler_combo.findText(current_sampler)
                if index >= 0:
                    mw.sampler_combo.setCurrentIndex(index)
                    print(f"✅ ComfyUI 샘플러 복원: {current_sampler}")
                else:
                    # euler을 기본값으로 설정
                    euler_index = mw.sampler_combo.findText("euler")
                    if euler_index >= 0:
                        mw.sampler_combo.setCurrentIndex(euler_index)
                        print(f"✅ ComfyUI 샘플러를 기본값으로 설정: euler")
                    elif mw.sampler_combo.count() > 0:
                        mw.sampler_combo.setCurrentIndex(0)
                        print(f"✅ ComfyUI 샘플러를 첫 번째 항목으로 설정: {mw.sampler_combo.currentText()}")
                
                print(f"✅ ComfyUI 샘플러 목록 업데이트: {len(sampler_list)}개")
            else:
                print("⚠️ ComfyUI 샘플러 목록을 가져올 수 없습니다.")
            
            # 3. 스케줄러 리스트 업데이트
            scheduler_list = ComfyUIAPIUtils.get_scheduler_list(comfyui_url)
            if scheduler_list and hasattr(mw, 'scheduler_combo'):
                # 현재 선택값 보존
                current_scheduler = mw.scheduler_combo.currentText()
                mw.scheduler_combo.clear()
                mw.scheduler_combo.addItems(scheduler_list)
                
                # 이전 선택값 복원 시도
                index = mw.scheduler_combo.findText(current_scheduler)
                if index >= 0:
                    mw.scheduler_combo.setCurrentIndex(index)
                    print(f"✅ ComfyUI 스케줄러 복원: {current_scheduler}")
                else:
                    # normal을 기본값으로 설정
                    normal_index = mw.scheduler_combo.findText("normal")
                    if normal_index >= 0:
                        mw.scheduler_combo.setCurrentIndex(normal_index)
                        print(f"✅ ComfyUI 스케줄러를 기본값으로 설정: normal")
                    elif mw.scheduler_combo.count() > 0:
                        mw.scheduler_combo.setCurrentIndex(0)
                        print(f"✅ ComfyUI 스케줄러를 첫 번째 항목으로 설정: {mw.scheduler_combo.currentText()}")
                
                print(f"✅ ComfyUI 스케줄러 목록 업데이트: {len(scheduler_list)}개")
            else:
                print("⚠️ ComfyUI 스케줄러 목록을 가져올 수 없습니다.")
            
            # 4. 시스템 정보 로그 (선택사항)
            system_info = ComfyUIAPIUtils.get_system_info(comfyui_url)
            if system_info:
                print(f"🎨 ComfyUI 시스템 정보 확인됨")
                # GPU, 메모리 정보 등을 로그에 출력 (필요시)
            
        except Exception as e:
            print(f"❌ ComfyUI 동적 옵션 로드 실패: {e}")

    def update_ui_for_comfyui_mode(self):
        """🆕 UI를 ComfyUI 모드로 전환"""
        try:
            mw = self.main_window
            
            # 1. NAI/WEBUI Option 영역 숨기기
            if hasattr(mw, 'naid_option_widgets'):
                for widget in mw.naid_option_widgets:
                    widget.setVisible(False)
            if hasattr(mw, 'hires_option_widgets'):
                for widget in mw.hires_option_widgets:
                    widget.setVisible(False)
            if hasattr(mw, 'nai_rescale_ui'):
                for widget in mw.nai_rescale_ui:
                    widget.setVisible(False)
            
            # 2. ComfyUI Option 영역 표시
            if hasattr(mw, 'comfyui_option_widgets'):
                for widget in mw.comfyui_option_widgets:
                    widget.setVisible(True)

            # 4. 라벨 텍스트 변경
            if hasattr(mw, 'option_section_label'):
                mw.option_section_label.setText("🎨 ComfyUI 옵션:")
            
            print("✅ UI가 ComfyUI 모드로 전환되었습니다.")
            
        except Exception as e:
            print(f"❌ ComfyUI 모드 UI 전환 실패: {e}")

    def update_ui_for_nai_mode(self):
        """UI를 NAI 모드로 전환"""
        try:
            mw = self.main_window
            
            # 1. Hires Option 영역 숨기기
            if hasattr(mw, 'hires_option_widgets'):
                for widget in mw.hires_option_widgets:
                    widget.setVisible(False)
            
            # 2. NAID Option 영역 표시
            if hasattr(mw, 'naid_option_widgets'):
                for widget in mw.naid_option_widgets:
                    widget.setVisible(True)
            if hasattr(mw, 'nai_rescale_ui'):
                for widget in mw.nai_rescale_ui:
                    widget.setVisible(True)
            
            # 3. 라벨 텍스트 변경
            if hasattr(mw, 'option_section_label'):
                mw.option_section_label.setText("NAID Option:")
            
            # 4. NAI 고정 옵션들 복원
            if hasattr(mw, 'model_combo'):
                nai_models = ["NAID4.5F", "NAID4.5C", "NAID4.0F", "NAID4.0C", "NAID3"]
                mw.model_combo.clear()
                mw.model_combo.addItems(nai_models)
            
            if hasattr(mw, 'sampler_combo'):
                nai_samplers = ["k_euler_ancestral", "k_euler", "k_dpmpp_2m", "k_dpmpp_2s_ancestral", 
                            "k_dpmpp_sde", "k_dpmpp_2m_sde", "ddim_v3"]
                mw.sampler_combo.clear()
                mw.sampler_combo.addItems(nai_samplers)
            
            if hasattr(mw, 'scheduler_combo'):
                nai_schedulers = ["native", "karras", "exponential", "polyexponential"]
                mw.scheduler_combo.clear()
                mw.scheduler_combo.addItems(nai_schedulers)
            
            print("✅ UI가 NAI 모드로 전환되었습니다.")
            
        except Exception as e:
            print(f"❌ NAI 모드 UI 전환 실패: {e}")

    def update_ui_for_webui_mode(self):
        """UI를 WEBUI 모드로 전환"""
        try:
            mw = self.main_window
            
            # 1. NAID Option 영역 숨기기
            if hasattr(mw, 'naid_option_widgets'):
                for widget in mw.naid_option_widgets:
                    widget.setVisible(False)
            if hasattr(mw, 'nai_rescale_ui'):
                for widget in mw.nai_rescale_ui:
                    widget.setVisible(False)
            
            # 2. Hires Option 영역 표시
            if hasattr(mw, 'hires_option_widgets'):
                for widget in mw.hires_option_widgets:
                    widget.setVisible(True)
            
            # 3. 라벨 텍스트 변경
            if hasattr(mw, 'option_section_label'):
                mw.option_section_label.setText("Hires Option:")
            
            print("✅ UI가 WEBUI 모드로 전환되었습니다.")
            
        except Exception as e:
            print(f"❌ WEBUI 모드 UI 전환 실패: {e}")

    def update_ui_for_nai_mode(self):
        """UI를 NAI 모드로 전환"""
        try:
            mw = self.main_window
            
            # 1. Hires Option 영역 숨기기
            if hasattr(mw, 'hires_option_widgets'):
                for widget in mw.hires_option_widgets:
                    widget.setVisible(False)
            
            # 2. NAID Option 영역 표시
            if hasattr(mw, 'naid_option_widgets'):
                for widget in mw.naid_option_widgets:
                    widget.setVisible(True)
            if hasattr(mw, 'nai_rescale_ui'):
                for widget in mw.nai_rescale_ui:
                    widget.setVisible(True)
            
            # 3. 라벨 텍스트 변경
            if hasattr(mw, 'option_section_label'):
                mw.option_section_label.setText("NAID Option:")
            
            # 🔧 수정: NAI 고정 옵션들 복원 시 현재 선택값 보존
            if hasattr(mw, 'model_combo'):
                current_model = mw.model_combo.currentText()
                nai_models = ["NAID4.5F", "NAID4.5C", "NAID4.0F", "NAID4.0C", "NAID3"]
                mw.model_combo.clear()
                mw.model_combo.addItems(nai_models)
                
                # 이전 선택값 복원
                index = mw.model_combo.findText(current_model)
                if index >= 0:
                    mw.model_combo.setCurrentIndex(index)
                    print(f"✅ NAI 모델 복원: {current_model}")
                else:
                    # 기본값 설정
                    mw.model_combo.setCurrentIndex(0)
                    print(f"✅ NAI 모델을 기본값으로 설정: {mw.model_combo.currentText()}")
            
            if hasattr(mw, 'sampler_combo'):
                current_sampler = mw.sampler_combo.currentText()
                nai_samplers = ["k_euler_ancestral", "k_euler", "k_dpmpp_2m", "k_dpmpp_2s_ancestral", 
                            "k_dpmpp_sde", "k_dpmpp_2m_sde", "ddim_v3"]
                mw.sampler_combo.clear()
                mw.sampler_combo.addItems(nai_samplers)
                
                # 이전 선택값 복원
                index = mw.sampler_combo.findText(current_sampler)
                if index >= 0:
                    mw.sampler_combo.setCurrentIndex(index)
                    print(f"✅ NAI 샘플러 복원: {current_sampler}")
                else:
                    # 기본값 설정
                    mw.sampler_combo.setCurrentIndex(0)
                    print(f"✅ NAI 샘플러를 기본값으로 설정: {mw.sampler_combo.currentText()}")
            
            if hasattr(mw, 'scheduler_combo'):
                current_scheduler = mw.scheduler_combo.currentText()
                nai_schedulers = ["native", "karras", "exponential", "polyexponential"]
                mw.scheduler_combo.clear()
                mw.scheduler_combo.addItems(nai_schedulers)
                
                # 이전 선택값 복원
                index = mw.scheduler_combo.findText(current_scheduler)
                if index >= 0:
                    mw.scheduler_combo.setCurrentIndex(index)
                    print(f"✅ NAI 스케줄러 복원: {current_scheduler}")
                else:
                    # 기본값 설정 (karras)
                    karras_index = mw.scheduler_combo.findText("karras")
                    if karras_index >= 0:
                        mw.scheduler_combo.setCurrentIndex(karras_index)
                        print(f"✅ NAI 스케줄러를 기본값으로 설정: karras")
            
            print("✅ UI가 NAI 모드로 전환되었습니다.")
            
        except Exception as e:
            print(f"❌ NAI 모드 UI 전환 실패: {e}")