from core.context import AppContext
from PIL import Image
import piexif
import piexif.helper
import json
import re
from PyQt6.QtCore import QThread, QObject, pyqtSignal

class GenerationWorker(QObject):
    """API 호출을 담당하는 워커 클래스"""
    generation_started = pyqtSignal()
    generation_progress = pyqtSignal(str)  # 진행 상황 메시지
    generation_finished = pyqtSignal(dict)  # 최종 결과
    generation_error = pyqtSignal(str)  # 오류 메시지
    
    def __init__(self, context: 'AppContext'):
        super().__init__()
        self.context = context
        self.params = None
        self.source_row = None
        
    def set_generation_params(self, params: dict, source_row):
        """생성 파라미터와 소스 행을 설정합니다."""
        self.params = params
        self.source_row = source_row
        
    def run_generation(self):
        """별도 스레드에서 실행될 생성 작업"""
        try:
            self.generation_started.emit()
            self.generation_progress.emit("API 호출 중...")
            
            # API 호출 (이 부분이 시간이 오래 걸림)
            api_result = self.context.api_service.call_generation_api(self.params)
            
            self.generation_progress.emit("결과 처리 중...")
            
            # 후처리
            processed_result = self._post_process(api_result)
            
            if processed_result.get('status') == 'success':
                processed_result['source_row'] = self.source_row.copy()
                
                # 생성된 이미지에서 직접 생성 정보(info) 추출
                generated_image = processed_result.get('image')
                if generated_image:
                    info_text = self._extract_info_from_image(generated_image)
                    processed_result['info'] = info_text
                else:
                    processed_result['info'] = "이미지 객체를 찾을 수 없습니다."
            
            self.generation_finished.emit(processed_result)
            
        except Exception as e:
            self.generation_error.emit(str(e))
    
    def _post_process(self, result: dict) -> dict:
        """결과 후처리 로직"""
        return result
    
    def _extract_info_from_image(self, image: Image.Image) -> str:
        """
        PIL Image 객체에서 생성 정보를 추출합니다.
        png_info_tab.py의 로직과 제공된 코드를 결합하여 NAI, A1111 등 다양한 포맷을 처리합니다.
        """
        if not image or not hasattr(image, 'info'):
            return "메타데이터를 포함하지 않는 이미지입니다."

        # 1. NovelAI 이미지 메타데이터 처리 (가장 먼저 확인)
        if image.info.get("Software", "") == "NovelAI":
            try:
                comment_data = json.loads(image.info.get("Comment", "{}"))
                # NAI 형식에 맞춰 문자열 재구성
                info_string = (
                    f"{image.info.get('Description', '')}\n"
                    f"Negative prompt: {comment_data.get('uc', '')}\n"
                    f"Steps: {comment_data.get('steps', 'N/A')}, Sampler: {comment_data.get('sampler', 'N/A')}, "
                    f"CFG scale: {comment_data.get('scale', 'N/A')}, Seed: {comment_data.get('seed', 'N/A')}"
                )
                return info_string
            except (json.JSONDecodeError, KeyError) as e:
                print(f"NovelAI 메타데이터 파싱 오류: {e}")
                # 실패 시 다른 방법으로 계속 진행

        # 2. A1111/ComfyUI 등 표준 'parameters' 메타데이터 처리
        if 'parameters' in image.info and isinstance(image.info['parameters'], str):
            return image.info['parameters']
            
        # 3. EXIF 데이터에서 UserComment 추출 시도
        if 'exif' in image.info:
            try:
                exif_data = image.info['exif']
                exif_dict = piexif.load(exif_data)
                user_comment_bytes = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')
                
                if user_comment_bytes:
                    return piexif.helper.UserComment.load(user_comment_bytes)
            except Exception as e:
                print(f"EXIF UserComment 추출 오류: {e}")

        # 4. 기타 'Comment' 또는 'comment' 필드 확인
        comment = image.info.get("Comment", image.info.get("comment"))
        if comment and isinstance(comment, str):
            return comment
        elif comment and isinstance(comment, bytes):
            return comment.decode('utf-8', errors='ignore')

        return "AI 생성 이미지가 아니거나, 인식할 수 있는 메타데이터가 없습니다."


class GenerationController:
    def __init__(self, context: 'AppContext', module_instances: list):
        self.context = context
        self.module_instances = module_instances
        
        # 스레드 관련 초기화
        self.generation_thread = None
        self.generation_worker = None
        self.is_generating = False
        
    def execute_generation_pipeline(self):
        """7단계 생성 파이프라인을 실행합니다."""
        # 이미 생성 중인 경우 중복 실행 방지
        if self.is_generating:
            self.context.main_window.status_bar.showMessage("⚠️ 이미 생성 중입니다...")
            return
            
        try:
            # --- 1 ~ 4 단계: 파라미터 수집 및 유효성 검사 ---
            api_mode = self.context.main_window.get_current_api_mode()
            credential = self.context.secure_token_manager.get_token('nai_token' if api_mode == "NAI" else 'webui_url')
            if not credential:
                self.context.main_window.status_bar.showMessage(f"❌ {api_mode} 인증 정보가 없습니다.")
                return

            params = self.context.main_window.get_main_parameters()
            params['api_mode'] = api_mode
            params['credential'] = credential

            source_row = self.context.current_source_row
            if source_row is None:
                self.context.main_window.status_bar.showMessage("❌ 먼저 [랜덤/다음 프롬프트] 버튼을 눌러주세요.")
                return

            for module in self.module_instances:
                module_params = module.get_parameters()
                if module_params: params.update(module_params)

            is_valid, error_msg = self.validate_parameters(params)
            if not is_valid:
                self.context.main_window.status_bar.showMessage(f"⚠️ 유효성 검사 실패: {error_msg}")
                return

            # --- 5. 스레드에서 API 호출 시작 ---
            self._start_threaded_generation(params, source_row)

        except Exception as e:
            self.context.main_window.status_bar.showMessage(f"❌ 생성 준비 오류: {e}")
            print(f"오류 발생: {e}")
    
    def _start_threaded_generation(self, params: dict, source_row):
        """별도 스레드에서 생성 작업을 시작합니다."""
        # 새 스레드와 워커 생성
        self.generation_thread = QThread()
        self.generation_worker = GenerationWorker(self.context)
        
        # 워커를 스레드로 이동
        self.generation_worker.moveToThread(self.generation_thread)
        
        # 시그널 연결
        self.generation_worker.generation_started.connect(self._on_generation_started)
        self.generation_worker.generation_progress.connect(self._on_generation_progress)
        self.generation_worker.generation_finished.connect(self._on_generation_finished)
        self.generation_worker.generation_error.connect(self._on_generation_error)
        
        # 스레드 시작/종료 연결
        self.generation_thread.started.connect(self.generation_worker.run_generation)
        self.generation_worker.generation_finished.connect(self.generation_thread.quit)
        self.generation_worker.generation_error.connect(self.generation_thread.quit)
        self.generation_thread.finished.connect(self._on_thread_finished)
        
        # 파라미터 설정 및 스레드 시작
        self.generation_worker.set_generation_params(params, source_row)
        self.generation_thread.start()
    
    def _on_generation_started(self):
        """생성 시작 시 호출되는 슬롯"""
        self.is_generating = True
        self.context.main_window.generate_button_main.setEnabled(False)
        self.context.main_window.generate_button_main.setText("🔄 생성 중...")
        self.context.main_window.status_bar.showMessage("🚀 생성 시작...")
    
    def _on_generation_progress(self, message: str):
        """생성 진행 상황 업데이트 슬롯"""
        self.context.main_window.status_bar.showMessage(message)
    
    def _on_generation_finished(self, result: dict):
        """생성 완료 시 호출되는 슬롯"""
        # [수정] 생성 완료 시 즉시 is_generating을 False로 설정
        self.is_generating = False
        self.context.main_window.generate_button_main.setEnabled(True)
        self.context.main_window.generate_button_main.setText("🎨 이미지 생성 요청")
        
        # UI 업데이트 (이제 is_generating이 False이므로 자동 생성이 가능)
        self.context.main_window.update_ui_with_result(result)

    def _on_generation_error(self, error_message: str):
        """생성 오류 시 호출되는 슬롯"""
        # [수정] 오류 발생 시에도 is_generating을 False로 설정
        self.is_generating = False
        self.context.main_window.generate_button_main.setEnabled(True)
        self.context.main_window.generate_button_main.setText("🎨 이미지 생성 요청")
        
        self.context.main_window.status_bar.showMessage(f"❌ 생성 오류: {error_message}")
        print(f"생성 오류: {error_message}")

    def _on_thread_finished(self):
        """스레드 완료 시 정리 작업"""
        # [수정] is_generating 설정은 이미 위에서 처리됨
        # self.is_generating = False  # 제거
        # self.context.main_window.generate_button_main.setEnabled(True)  # 제거
        # self.context.main_window.generate_button_main.setText("🎨 이미지 생성 요청")  # 제거
        
        # 스레드와 워커 정리만 수행
        if self.generation_thread:
            self.generation_thread.deleteLater()
            self.generation_thread = None
        if self.generation_worker:
            self.generation_worker.deleteLater()
            self.generation_worker = None

    def validate_parameters(self, params: dict) -> tuple[bool, str]:
        """파라미터 유효성 검사 로직"""
        return True, ""