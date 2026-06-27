# core/image_crud_controller.py
"""
ImageCrudController - 이미지 파일 저장/관리 컨트롤러

이미지 파일의 생성(Create), 읽기(Read), 삭제(Delete) 작업을 관리하는 컨트롤러.
UI 로직과 파일 시스템 관리를 분리하여 재사용성과 유지보수성을 향상.

주요 기능:
- 파일명 자동 생성 (카운터 기반)
- 저장 경로 관리
- 멀티스레드 안전성 (threading.Lock)
- 카운터 영속화 (app_settings.json)
- 파일명 중복 방지
- 상세한 에러 처리 및 이벤트 발행
"""

from pathlib import Path
from typing import Optional, Tuple, Callable, List
from PIL import Image
from threading import Lock
from datetime import datetime
import io
import json

from core import image_classification


class ImageCrudController:
    """이미지 파일의 생성(Create), 읽기(Read), 삭제(Delete) 작업을 관리하는 컨트롤러"""

    def __init__(self, app_context):
        """
        ImageCrudController 초기화

        Parameters:
            app_context: AppContext 인스턴스
        """
        self.app_context = app_context
        self._save_counter: int = 1  # 파일명 자동 증가 카운터
        self._base_save_path: Path = Path("output")  # 기본 저장 경로

        # ✅ 멀티스레드 안전성: 카운터 접근 보호
        self._counter_lock = Lock()

        # Phase 2에서 활성화될 속성들
        self._auto_classification_enabled: bool = False
        self._subfolder_format: Optional[str] = None

        # 🆕 파일명 형식: "number_only", "time_number", "datetime"
        self._filename_format: str = "number_only"

        # 🆕 분류 방법: "none", "prompt_recognition"
        self._classification_method: str = "none"

        # 🆕 분류 규칙: 쉼표로 구분된 조건 문자열
        self._classification_rules: str = ""

        # 🆕 타임스탬프 폴더 사용 여부
        self._use_timestamp_folder: bool = True

        # 🆕 2차 분류 설정
        self._secondary_classification_enabled: bool = False
        self._secondary_classification_method: str = "none"  # "none", "prompt_recognition"
        self._secondary_classification_rules: dict = {}  # {primary_folder: secondary_rules_text}

        # ✅ 카운터 영속화: 저장된 값 불러오기
        self._load_counter_from_settings()

        print(f"✅ ImageCrudController 초기화 완료 (카운터: {self._save_counter})")

    # ========================================================================
    # A. 저장 경로 관리
    # ========================================================================

    def get_save_directory(self, classification_subfolder: Optional[str] = None) -> Path:
        """
        현재 저장에 사용될 최종 디렉토리 경로를 반환합니다.

        Phase 1: base_path / session_timestamp / [classification_subfolder]
        Phase 2: base_path / {자동분류경로} / session_timestamp (optional)

        Parameters:
            classification_subfolder (str, optional): 분류 하위 폴더명 (예: "character", "landscape")

        Returns:
            Path: 저장할 디렉토리 경로 (예: output/20250109_143520/ 또는 output/20250109_143520/character/)
        """
        # 타임스탬프 폴더 사용 여부에 따라 경로 결정
        if self._use_timestamp_folder:
            # Phase 1: session_timestamp 사용
            session_timestamp = self.app_context.session_timestamp
            save_dir = self._base_save_path / session_timestamp

            # 🆕 분류 하위 폴더 추가
            if classification_subfolder:
                save_dir = save_dir / classification_subfolder
        else:
            # 타임스탬프 폴더 미사용: 기본 경로에 바로 저장
            save_dir = self._base_save_path

            # 🆕 분류 하위 폴더 추가
            if classification_subfolder:
                save_dir = save_dir / classification_subfolder

        # TODO Phase 2: 자동 분류 활성화 시
        # if self._auto_classification_enabled and self._subfolder_format:
        #     classified_path = self._apply_subfolder_format()
        #     save_dir = self._base_save_path / classified_path / session_timestamp

        return save_dir

    def set_base_save_directory(self, base_path: str):
        """
        기본 저장 경로를 변경합니다.

        Parameters:
            base_path (str): 새로운 기본 저장 경로

        Example:
            controller.set_base_save_directory("D:/AIArt/outputs")
        """
        self._base_save_path = Path(base_path)
        print(f"📁 기본 저장 경로 변경: {self._base_save_path}")

        # 이벤트 발행 (다른 컴포넌트가 경로 변경 감지 가능)
        self.app_context.publish("save_directory_changed", {
            "new_base_path": str(self._base_save_path)
        })

    def ensure_directory_exists(self, directory: Path) -> bool:
        """
        디렉토리가 존재하지 않으면 생성합니다.

        Parameters:
            directory (Path): 생성할 디렉토리 경로

        Returns:
            bool: 생성 성공 여부
        """
        try:
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                print(f"✅ 디렉토리 생성: {directory}")
            return True
        except PermissionError as e:
            print(f"❌ 디렉토리 생성 권한 없음: {e}")
            return False
        except Exception as e:
            print(f"❌ 디렉토리 생성 실패: {e}")
            return False

    # ========================================================================
    # B. 파일명 생성
    # ========================================================================

    def generate_filename(self, extension: str = "png", use_counter: bool = True, classification_subfolder: Optional[str] = None, prompt: Optional[str] = None) -> str:
        """
        저장할 파일명을 생성합니다 (파일명 형식 및 중복 방지 포함).

        파일명 형식:
        - "number_only": 00001.png (기본)
        - "time_number": 143052_00001.png (HHMMSS_카운터)
        - "datetime": 20250108_143052.png (YYYYMMDD_HHMMSS)
        - "prompt": prompt.png (프롬프트 기반, 최대 250자)
        - "wildcard": wildcard.png (와일드카드 결과 기반, '__' 구분자)

        중복 방지:
        - number_only/time_number: 카운터 자동 증가
        - datetime/prompt: (1), (2) 등 추가 번호 부여

        Parameters:
            extension (str): 파일 확장자 ("png" 또는 "webp")
            use_counter (bool): 카운터 사용 여부
            classification_subfolder (str, optional): 분류 하위 폴더명
            prompt (str, optional): 프롬프트 텍스트 (prompt 형식 시 필요)

        Returns:
            str: 생성된 파일명 (예: "00001.png", "143052_00001.png", "20250108_143052.png", "1girl_standing.png")
        """
        save_dir = self.get_save_directory(classification_subfolder=classification_subfolder)

        if not use_counter:
            # 타임스탬프 기반 (마이크로초 포함, 중복 가능성 극히 낮음)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:21]
            return f"{timestamp}.{extension}"

        # 파일명 형식에 따라 생성
        filename_format = self._filename_format

        if filename_format == "number_only":
            # 00001.png
            with self._counter_lock:
                while True:
                    filename = f"{self._save_counter:05d}.{extension}"
                    if not (save_dir / filename).exists():
                        break
                    print(f"⚠️ 파일 중복 방지: {filename} 건너뜀 (카운터 증가)")
                    self._save_counter += 1
            return filename

        elif filename_format == "time_number":
            # 143052_00001.png (HHMMSS_카운터)
            current_time = datetime.now().strftime("%H%M%S")
            with self._counter_lock:
                while True:
                    filename = f"{current_time}_{self._save_counter:05d}.{extension}"
                    if not (save_dir / filename).exists():
                        break
                    print(f"⚠️ 파일 중복 방지: {filename} 건너뜀 (카운터 증가)")
                    self._save_counter += 1
            return filename

        elif filename_format == "datetime":
            # 20250108_143052.png (YYYYMMDD_HHMMSS)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"{timestamp}.{extension}"

            # 중복 체크 및 (1), (2) 추가
            final_filename = self._resolve_duplicate_filename(save_dir, base_filename, extension)
            return final_filename

        elif filename_format == "prompt":
            # prompt.png (프롬프트 기반, 최대 230자)
            if not prompt:
                # 프롬프트가 없으면 타임스탬프로 대체
                print("⚠️ 프롬프트가 없습니다. 타임스탬프로 대체합니다.")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_filename = f"{timestamp}.{extension}"
            else:
                # 프롬프트를 안전한 파일명으로 변환
                # Windows MAX_PATH 고려: 230자 (전체 경로 260자 제한 회피)
                safe_prompt = self._sanitize_filename(prompt, max_length=200)
                base_filename = f"{safe_prompt}.{extension}"

            # 중복 체크 및 (1), (2) 추가
            final_filename = self._resolve_duplicate_filename(save_dir, base_filename, extension)
            return final_filename

        elif filename_format == "wildcard":
            # 와일드카드 히스토리에서 파일명 조합
            wildcard_name = self._build_wildcard_filename()
            if not wildcard_name:
                # fallback: timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_filename = f"{timestamp}.{extension}"
            else:
                base_filename = f"{wildcard_name}.{extension}"
            final_filename = self._resolve_duplicate_filename(save_dir, base_filename, extension)
            return final_filename

        else:
            # 기본값: number_only
            with self._counter_lock:
                while True:
                    filename = f"{self._save_counter:05d}.{extension}"
                    if not (save_dir / filename).exists():
                        break
                    print(f"⚠️ 파일 중복 방지: {filename} 건너뜀 (카운터 증가)")
                    self._save_counter += 1
            return filename

    def _build_wildcard_filename(self) -> str:
        """현재 PromptContext의 wildcard_history에서 파일명용 문자열 생성.

        각 와일드카드의 마지막 선택값을 개별 sanitize 후 '__'로 결합.
        와일드카드 값은 깨끗한 태그명이므로 최소한의 정제만 수행.
        """
        ctx = getattr(self.app_context, 'current_prompt_context', None)
        if not ctx or not ctx.wildcard_history:
            return ""
        parts = []
        for key, values in ctx.wildcard_history.items():
            if values:
                sanitized = self._sanitize_wildcard_value(values[-1])
                if sanitized:
                    parts.append(sanitized)
        return "__".join(parts) if parts else ""

    def _sanitize_wildcard_value(self, text: str, max_length: int = 100) -> str:
        """와일드카드 값을 파일명에 안전한 문자열로 변환 (최소한의 정제)."""
        import re
        # Windows 금지 문자 → 언더스코어
        text = re.sub(r'[<>:"/\\|?*]', '_', text)
        # 공백 → 언더스코어
        text = text.replace(' ', '_')
        # 연속 언더스코어 정리, 앞뒤 제거
        text = re.sub(r'_+', '_', text).strip('_')
        if len(text) > max_length:
            text = text[:max_length].rstrip('_')
        return text

    def _sanitize_filename(self, text: str, max_length: int = 230) -> str:
        """
        텍스트를 안전한 파일명으로 변환합니다.

        처리 규칙:
        - Windows 금지 문자 제거: < > : " / \\ | ? *
        - 쉘 특수문자 제거: [ ] { } ( )
        - 쉼표, 세미콜론, 점 → 언더스코어
        - 공백 → 언더스코어
        - "artist" 단어 제거
        - 불필요한 프리픽스 제거 (Novel_AI_prompt_, WEBUI_prompt_ 등)
        - 연속된 언더스코어 정리
        - 최대 길이 제한 (기본 230자, Windows MAX_PATH 260자 제한 고려)
        - 앞뒤 공백/언더스코어 제거

        Parameters:
            text (str): 원본 텍스트 (프롬프트)
            max_length (int): 최대 길이 (기본 230자)

        Returns:
            str: 안전한 파일명 (확장자 제외)

        Example:
            >>> _sanitize_filename("1girl, long hair, standing:1.2, masterpiece")
            "1girl_long_hair_standing_1_2_masterpiece"
            >>> _sanitize_filename("[Novel_AI]_{prompt_(test)}")
            "Novel_AI_prompt_test"
        """
        import re

        # 1. Windows 금지 문자 제거
        forbidden_chars = '<>:"/\\|?*'
        for char in forbidden_chars:
            text = text.replace(char, '')

        # 2. 쉘 특수문자 제거 (파일 탐색기 호환성)
        shell_special_chars = '[]{}()'
        for char in shell_special_chars:
            text = text.replace(char, '_')

        # 3. 쉼표, 세미콜론 → 언더스코어
        text = text.replace(',', '_')
        text = text.replace(';', '_')

        # 4. 공백 → 언더스코어
        text = text.replace(' ', '_')

        # 5. 점(.) → 언더스코어 (파일 탐색기 호환성, Explorer 명령 오류 방지)
        text = text.replace('.', '_')

        # 6. "artist" 단어 제거 (대소문자 구분 없이)
        text = re.sub(r'artist', '', text, flags=re.IGNORECASE)

        # 7. 불필요한 프리픽스 제거
        # "Novel_AI_prompt_", "WEBUI_prompt_", "ComfyUI_prompt_" 등 제거
        text = re.sub(r'^(Novel_AI|WEBUI|ComfyUI)_prompt_', '', text, flags=re.IGNORECASE)

        # 8. 연속된 언더스코어 정리 (___  → _)
        text = re.sub(r'_+', '_', text)

        # 9. 앞뒤 언더스코어 제거
        text = text.strip('_')

        # 10. 최대 길이 제한
        if len(text) > max_length:
            text = text[:max_length].rstrip('_')

        # 11. 빈 문자열 방지
        if not text:
            text = "untitled"

        if text:
            text = text.replace("Novel_AI_prompt_", "").replace("WEBUI_prompt_", "").replace("ComfyUI_prompt_", "")

        return text

    def _resolve_duplicate_filename(self, save_dir: Path, base_filename: str, extension: str) -> str:
        """
        파일명 중복 시 (1), (2) 등을 추가하여 고유한 파일명을 반환합니다.

        Parameters:
            save_dir (Path): 저장 디렉토리
            base_filename (str): 기본 파일명 (예: "20250108_143052.png")
            extension (str): 파일 확장자

        Returns:
            str: 고유한 파일명 (예: "20250108_143052.png" 또는 "20250108_143052 (1).png")
        """
        # 기본 파일명이 중복되지 않으면 그대로 반환
        if not (save_dir / base_filename).exists():
            return base_filename

        # 확장자를 제외한 파일명
        name_without_ext = base_filename.rsplit('.', 1)[0]

        # (1), (2) 형식으로 추가
        counter = 1
        while True:
            new_filename = f"{name_without_ext} ({counter}).{extension}"
            if not (save_dir / new_filename).exists():
                print(f"⚠️ 파일 중복 방지: {base_filename} → {new_filename}")
                return new_filename
            counter += 1

            # 무한 루프 방지 (1000개 이상은 비정상)
            if counter > 1000:
                # 마이크로초 추가하여 강제 고유화
                timestamp_unique = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:21]
                return f"{timestamp_unique}.{extension}"

    # ========================================================================
    # C. 카운터 관리
    # ========================================================================

    def increment_counter(self):
        """저장 카운터를 1 증가시키고 영속화합니다 (스레드 안전)."""
        with self._counter_lock:
            self._save_counter += 1
            self._persist_counter()

            # ✅ 이벤트 발행 (UI 업데이트용)
            self.app_context.publish("image_counter_changed", {
                "new_counter": self._save_counter
            })

    def reset_counter(self):
        """저장 카운터를 1로 초기화합니다."""
        with self._counter_lock:
            self._save_counter = 1
            self._persist_counter()

        print("🔄 저장 카운터 초기화: 1")

        # ✅ 이벤트 발행
        self.app_context.publish("image_counter_changed", {
            "new_counter": 1
        })

    def get_counter(self) -> int:
        """현재 카운터 값을 반환합니다 (스레드 안전)."""
        with self._counter_lock:
            return self._save_counter

    def set_filename_format(self, format: str):
        """
        파일명 형식을 설정합니다.

        Parameters:
            format (str): "number_only", "time_number", "datetime", "prompt", "wildcard" 중 하나

        Raises:
            ValueError: 유효하지 않은 형식인 경우
        """
        valid_formats = ["number_only", "time_number", "datetime", "prompt", "wildcard"]
        if format not in valid_formats:
            raise ValueError(f"유효하지 않은 파일명 형식: {format}. 사용 가능: {valid_formats}")

        self._filename_format = format
        self._persist_counter()  # 즉시 저장
        print(f"✅ 파일명 형식 변경: {format}")

    def get_filename_format(self) -> str:
        """현재 파일명 형식을 반환합니다."""
        return self._filename_format

    def set_classification_method(self, method: str):
        """
        분류 방법을 설정합니다.

        Parameters:
            method (str): "none", "prompt_recognition" 중 하나

        Raises:
            ValueError: 유효하지 않은 분류 방법인 경우
        """
        valid_methods = ["none", "prompt_recognition"]
        if method not in valid_methods:
            raise ValueError(f"유효하지 않은 분류 방법: {method}. 사용 가능: {valid_methods}")

        self._classification_method = method
        self._persist_counter()  # 즉시 저장
        print(f"✅ 분류 방법 변경: {method}")

    def get_classification_method(self) -> str:
        """현재 분류 방법을 반환합니다."""
        return self._classification_method

    def set_classification_rules(self, rules: str):
        """
        분류 규칙을 설정합니다.

        Parameters:
            rules (str): 쉼표로 구분된 조건 문자열
                        예: "*1girl, (*solo&*1girl), (landscape|scenery)"
        """
        self._classification_rules = rules
        self._persist_counter()  # 즉시 저장
        print(f"✅ 분류 규칙 저장: {len(rules)} 문자")

    def get_classification_rules(self) -> str:
        """현재 분류 규칙을 반환합니다."""
        return self._classification_rules

    def set_use_timestamp_folder(self, use_timestamp: bool):
        """타임스탬프 폴더 사용 여부를 설정합니다."""
        self._use_timestamp_folder = use_timestamp
        self._persist_counter()  # 즉시 저장
        print(f"✅ 타임스탬프 폴더 사용: {use_timestamp}")

    def get_use_timestamp_folder(self) -> bool:
        """타임스탬프 폴더 사용 여부를 반환합니다."""
        return self._use_timestamp_folder

    def set_secondary_classification_enabled(self, enabled: bool):
        """2차 분류 활성화 여부를 설정합니다."""
        self._secondary_classification_enabled = enabled
        self._persist_counter()
        print(f"✅ 2차 분류 활성화: {enabled}")

    def get_secondary_classification_enabled(self) -> bool:
        """2차 분류 활성화 여부를 반환합니다."""
        return self._secondary_classification_enabled

    def set_secondary_classification_method(self, method: str):
        """2차 분류 방법을 설정합니다."""
        self._secondary_classification_method = method
        self._persist_counter()
        print(f"✅ 2차 분류 방법: {method}")

    def get_secondary_classification_method(self) -> str:
        """2차 분류 방법을 반환합니다."""
        return self._secondary_classification_method

    def set_secondary_classification_rules(self, rules: dict):
        """2차 분류 규칙을 설정합니다.

        Parameters:
            rules (dict): {primary_folder_name: secondary_rules_text}
        """
        self._secondary_classification_rules = rules
        self._persist_counter()
        print(f"✅ 2차 분류 규칙 설정: {len(rules)}개 규칙")

    def get_secondary_classification_rules(self) -> dict:
        """2차 분류 규칙을 반환합니다."""
        return self._secondary_classification_rules

    def _load_counter_from_settings(self):
        """저장된 파일명 형식, 분류 방법, 분류 규칙을 app_settings.json에서 불러옵니다.

        ⚠️ 카운터는 항상 1로 초기화됩니다 (프로그램 재시작 시).
        """
        try:
            settings_path = Path("save/app_settings.json")
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # 카운터는 항상 1로 시작 (재시작 시 초기화)
                    self._save_counter = 1
                    self._filename_format = settings.get('image_crud.filename_format', 'number_only')
                    self._classification_method = settings.get('image_crud.classification_method', 'none')
                    self._classification_rules = settings.get('image_crud.classification_rules', '')
                    self._use_timestamp_folder = settings.get('image_crud.use_timestamp_folder', True)

                    # 🆕 2차 분류 설정 로드
                    self._secondary_classification_enabled = settings.get('image_crud.secondary_classification_enabled', False)
                    self._secondary_classification_method = settings.get('image_crud.secondary_classification_method', 'none')
                    self._secondary_classification_rules = settings.get('image_crud.secondary_classification_rules', {})

                    print(f"📊 설정 복원: 카운터=1 (초기화), 파일명={self._filename_format}, 분류={self._classification_method}, 규칙={len(self._classification_rules)}자, 타임스탬프={self._use_timestamp_folder}, 2차분류={self._secondary_classification_enabled}")
        except Exception as e:
            print(f"⚠️ 설정 복원 실패 (기본값 사용): {e}")
            self._save_counter = 1
            self._filename_format = "number_only"
            self._classification_method = "none"
            self._classification_rules = ""
            self._use_timestamp_folder = True
            self._secondary_classification_enabled = False
            self._secondary_classification_method = "none"
            self._secondary_classification_rules = {}

    def _persist_counter(self):
        """현재 카운터 값, 파일명 형식, 분류 방법을 app_settings.json에 저장합니다."""
        try:
            settings_path = Path("save/app_settings.json")
            settings_path.parent.mkdir(parents=True, exist_ok=True)

            settings = {}
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

            settings['image_crud.last_counter'] = self._save_counter
            settings['image_crud.filename_format'] = self._filename_format
            settings['image_crud.classification_method'] = self._classification_method
            settings['image_crud.classification_rules'] = self._classification_rules
            settings['image_crud.use_timestamp_folder'] = self._use_timestamp_folder

            # 🆕 2차 분류 설정 저장
            settings['image_crud.secondary_classification_enabled'] = self._secondary_classification_enabled
            settings['image_crud.secondary_classification_method'] = self._secondary_classification_method
            settings['image_crud.secondary_classification_rules'] = self._secondary_classification_rules

            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 설정 영속화 실패: {e}")

    def _get_classified_directory(self, classification_info: Optional[dict]) -> Optional[str]:
        """
        분류 정보를 바탕으로 하위 폴더명을 결정합니다.

        Parameters:
            classification_info (dict, optional): 분류 정보
                - method: "none" | "prompt_recognition"
                - prompt: 프롬프트 텍스트
                - image_size: (width, height)
                - tags: 태그 리스트
                - backend_type: NAI/WEBUI/COMFYUI

        Returns:
            str or None: 분류 하위 폴더명 (없으면 None)
        """
        if not classification_info:
            return None

        method = classification_info.get("method", "none")

        if method == "none":
            return None

        elif method == "prompt_recognition":
            # TODO: 프롬프트 인식 분류 로직 구현
            return self._classify_by_prompt(classification_info)

        else:
            return None

    # ========================================================================
    # 🆕 Phase 2: 분류 규칙 파싱 유틸리티
    # ========================================================================

    # NOTE: 분류 DSL 엔진(규칙 분리/평가/폴더명 변환/괄호 매칭)은 core/image_classification.py로
    # 추출되어 헤드리스 저장 경로와 공유된다. 이 데스크톱 컨트롤러의 아래 메서드들은 동일 동작을
    # 유지하기 위한 얇은 위임 래퍼다(로깅이 있는 _classify_by_prompt/_apply_secondary_classification은
    # 기존 print를 그대로 보존). 의미는 변경되지 않았다.

    def _split_classification_rules(self, rules_text: str) -> List[str]:
        """쉼표로 구분된 분류 규칙을 리스트로 분리합니다(공유 엔진 위임)."""
        return image_classification.split_rules(rules_text)

    def _condition_to_folder_name(self, condition_text: str) -> str:
        """조건 텍스트를 폴더명으로 변환합니다(공유 엔진 위임)."""
        return image_classification.condition_to_folder_name(condition_text)

    def _evaluate_classification_condition(self, condition: str, tags: List[str]) -> bool:
        """분류 조건을 평가합니다(단일/논리 표현식, 공유 엔진 위임)."""
        return image_classification.evaluate_condition(condition, tags)

    def _classify_by_prompt(self, classification_info: dict) -> str:
        """
        [Phase 2 구현] 프롬프트 규칙에 따라 분류 폴더명을 반환합니다.

        작동 방식:
        1. classification_rules를 쉼표로 분리
        2. 각 규칙을 순서대로 평가
        3. 첫 번째 만족하는 규칙의 폴더명 반환
        4. 모두 만족하지 않으면 "misc" 반환

        Parameters:
            classification_info (dict): {
                "method": "prompt_recognition",
                "prompt": str,
                "tags": List[str],
                "image_size": tuple,
                "backend_type": str
            }

        Returns:
            str: 분류 폴더명
        """
        # 규칙이 없으면 misc
        if not self._classification_rules:
            print("⚠️ 분류 규칙이 비어있습니다. 'misc'로 분류합니다.")
            return "misc"

        # tags 추출
        tags = classification_info.get("tags", [])
        if not tags:
            print("⚠️ tags가 비어있습니다. 'misc'로 분류합니다.")
            return "misc"

        # 규칙 파싱
        rules = self._split_classification_rules(self._classification_rules)

        print(f"🔍 분류 시작: {len(rules)}개 규칙, {len(tags)}개 태그")
        print(f"   tags: {tags[:10]}{'...' if len(tags) > 10 else ''}")

        # 순차적으로 조건 평가
        for idx, rule in enumerate(rules, 1):
            try:
                is_match = self._evaluate_classification_condition(rule, tags)

                if is_match:
                    primary_folder_name = self._condition_to_folder_name(rule)
                    print(f"✅ 규칙 #{idx} 만족: '{rule}' → 폴더: '{primary_folder_name}'")

                    # 🆕 2차 분류 적용
                    if (self._secondary_classification_enabled and
                        self._secondary_classification_method == "prompt_recognition" and
                        primary_folder_name in self._secondary_classification_rules):

                        secondary_rules_text = self._secondary_classification_rules[primary_folder_name]
                        if secondary_rules_text.strip():
                            secondary_folder = self._apply_secondary_classification(secondary_rules_text, tags)
                            if secondary_folder and secondary_folder != "misc":
                                combined_path = f"{primary_folder_name}/{secondary_folder}"
                                print(f"   🔹 2차 분류 적용: '{secondary_folder}' → 최종: '{combined_path}'")
                                return combined_path

                    return primary_folder_name
                else:
                    print(f"   규칙 #{idx} 불만족: '{rule}'")

            except Exception as e:
                print(f"⚠️ 규칙 #{idx} 평가 오류: '{rule}' - {e}")
                continue

        # 모든 규칙 불만족 시 misc
        print("   모든 규칙 불만족 → 'misc'로 분류")
        return "misc"

    def _apply_secondary_classification(self, secondary_rules_text: str, tags: List[str]) -> Optional[str]:
        """
        2차 분류 규칙을 적용하여 서브폴더명을 반환합니다.

        Parameters:
            secondary_rules_text (str): 2차 분류 규칙 문자열 (쉼표 구분)
            tags (List[str]): 태그 리스트

        Returns:
            str or None: 2차 분류 서브폴더명, 또는 None (분류 실패 시)
        """
        if not secondary_rules_text or not tags:
            return None

        # 규칙 파싱
        secondary_rules = self._split_classification_rules(secondary_rules_text)

        print(f"   🔸 2차 분류 시작: {len(secondary_rules)}개 규칙")

        # 순차적으로 조건 평가
        for idx, rule in enumerate(secondary_rules, 1):
            try:
                is_match = self._evaluate_classification_condition(rule, tags)

                if is_match:
                    secondary_folder_name = self._condition_to_folder_name(rule)
                    print(f"   ✅ 2차 규칙 #{idx} 만족: '{rule}' → '{secondary_folder_name}'")
                    return secondary_folder_name
                else:
                    print(f"      2차 규칙 #{idx} 불만족: '{rule}'")

            except Exception as e:
                print(f"   ⚠️ 2차 규칙 #{idx} 평가 오류: '{rule}' - {e}")
                continue

        # 2차 규칙 모두 불만족 시 None 반환 (1차 폴더만 사용)
        print("      2차 규칙 모두 불만족 → 1차 폴더만 사용")
        return None

    # ========================================================================
    # D. 이미지 저장 (핵심)
    # ========================================================================

    def save_image(
        self,
        image_bytes: bytes,
        as_webp: bool = False,
        metadata: Optional[dict] = None,
        classification_info: Optional[dict] = None
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        이미지를 파일로 저장합니다.

        기존 save_image_with_metadata() 메서드의 기능을 계승하되,
        경로 및 파일명 생성 로직을 통합 관리합니다.

        Parameters:
            image_bytes (bytes): 저장할 이미지 원본 바이트 데이터
            as_webp (bool): WEBP 형식으로 저장할지 여부 (기본: PNG)
            metadata (dict, optional): 추가 메타데이터 (향후 확장용)
            classification_info (dict, optional): 분류 정보
                - method: "none" | "prompt_recognition"
                - prompt: 프롬프트 텍스트
                - image_size: (width, height)
                - tags: 태그 리스트
                - backend_type: NAI/WEBUI/COMFYUI

        Returns:
            Tuple[bool, Optional[str], Optional[str]]: (성공 여부, 파일 경로, 에러 메시지)

        Example:
            success, filepath, error = controller.save_image(
                image_bytes=raw_bytes,
                as_webp=True,
                classification_info={
                    "method": "prompt_recognition",
                    "prompt": "1girl, landscape",
                    "tags": ["1girl", "landscape"]
                }
            )
            if success:
                print(f"저장 완료: {filepath}")
            else:
                print(f"저장 실패: {error}")
        """
        try:
            # 🆕 1. 분류 하위 폴더 결정
            classification_subfolder = self._get_classified_directory(classification_info)

            # 2. 저장 디렉토리 결정 및 생성
            save_dir = self.get_save_directory(classification_subfolder=classification_subfolder)
            if not self.ensure_directory_exists(save_dir):
                # 폴백: output 폴더 사용
                save_dir = Path("output")
                self.ensure_directory_exists(save_dir)
                print(f"⚠️ 대체 경로 사용: {save_dir}")

            # 3. 파일명 생성 (중복 방지 포함)
            extension = "webp" if as_webp else "png"

            # 프롬프트 추출 (prompt 형식 사용 시)
            prompt_text = None
            if classification_info:
                prompt_text = classification_info.get("prompt")

            filename = self.generate_filename(extension, classification_subfolder=classification_subfolder, prompt=prompt_text)
            file_path = save_dir / filename

            # 3. 실제 파일 저장
            if as_webp:
                # WEBP로 저장 (EXIF 보존)
                img = Image.open(io.BytesIO(image_bytes))
                exif = img.info.get('exif', b'')

                # ⚠️ PNG 메타데이터 손실 경고
                png_metadata = {}
                for key in ['parameters', 'prompt', 'Comment', 'Source', 'Software']:
                    if key in img.info:
                        png_metadata[key] = img.info[key]

                if png_metadata:
                    print(f"⚠️ WEBP 변환 시 PNG 메타데이터 일부 손실 가능: {list(png_metadata.keys())}")

                img.save(str(file_path), format='WEBP', quality=95, method=6, exif=exif)
                print(f"✅ WEBP 저장 완료: {filename}")
            else:
                # PNG로 저장 (원본 바이트 그대로 - 메타데이터 완전 보존)
                with open(str(file_path), 'wb') as f:
                    f.write(image_bytes)
                print(f"✅ PNG 저장 완료: {filename}")

            # 4. 카운터 증가 (스레드 안전, 영속화, 이벤트 발행 자동 처리)
            self.increment_counter()

            # 5. 저장 완료 이벤트 (Remote Viewer 등에서 활용)
            self.app_context.publish("image_saved", {
                "filepath": str(file_path),
                "filename": filename,
                "save_dir": str(save_dir),
            })

            return True, str(file_path), None

        except PermissionError as e:
            error_msg = f"저장 권한이 없습니다: {save_dir}"
            print(f"❌ {error_msg}")

            # ✅ 이벤트 발행 (UI에서 에러 다이얼로그 표시 가능)
            self.app_context.publish("image_save_failed", {
                "error_type": "PermissionError",
                "message": error_msg,
                "path": str(save_dir)
            })

            return False, None, error_msg

        except OSError as e:
            # 디스크 용량 부족, 파일명 길이 초과 등
            error_msg = f"파일 시스템 오류: {str(e)}"
            print(f"❌ {error_msg}")

            self.app_context.publish("image_save_failed", {
                "error_type": "OSError",
                "message": error_msg
            })

            return False, None, error_msg

        except Exception as e:
            error_msg = f"이미지 저장 실패: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()

            self.app_context.publish("image_save_failed", {
                "error_type": "Exception",
                "message": error_msg
            })

            return False, None, error_msg

    # ========================================================================
    # E. 일괄 저장 지원
    # ========================================================================

    def save_images_bulk(
        self,
        image_items: list,  # List[Tuple[bytes, bool]]  (bytes, is_webp)
        progress_callback: Optional[Callable] = None
    ) -> Tuple[int, int]:
        """
        여러 이미지를 일괄 저장합니다 (스레드 안전).

        Parameters:
            image_items: (image_bytes, as_webp) 튜플의 리스트
            progress_callback: 진행 상황 콜백 (index, total, message)

        Returns:
            Tuple[int, int]: (성공한 개수, 전체 개수)

        Example:
            items = [(bytes1, False), (bytes2, True), (bytes3, False)]
            saved, total = controller.save_images_bulk(items, progress_callback)
            print(f"저장 완료: {saved}/{total}")
        """
        saved_count = 0
        total_count = len(image_items)

        for i, (image_bytes, as_webp) in enumerate(image_items):
            success, filepath, error = self.save_image(image_bytes, as_webp)
            if success:
                saved_count += 1

            if progress_callback:
                message = f"[저장됨] {Path(filepath).name}" if success else f"[실패] {error}"
                progress_callback(i + 1, total_count, message)

        return saved_count, total_count

    # ========================================================================
    # F. Phase 2 확장 메서드 (현재는 NotImplemented)
    # ========================================================================

    def enable_auto_classification(self, enabled: bool):
        """
        자동 분류 활성화/비활성화

        Phase 2에서 구현 예정
        """
        raise NotImplementedError("Phase 2에서 구현 예정")

    def set_subfolder_format(self, format_string: str):
        """
        하위폴더 형식 설정

        지원 템플릿 변수 (Phase 2):
            {mode} - NAI/WEBUI/COMFYUI
            {date} - YYYYMMDD
            {timestamp} - YYYYMMDD_HHMMSS
            {year}, {month}, {day} - 개별 날짜 요소

        Example:
            controller.set_subfolder_format("{mode}/{date}")
            # 결과: output/NAI/20250109/20250109_143520/00001.png

        Phase 2에서 구현 예정
        """
        raise NotImplementedError("Phase 2에서 구현 예정")

    def set_filename_template(self, template: str):
        """
        파일명 템플릿 설정

        지원 템플릿 변수 (Phase 2):
            {counter} - 자동 증가 카운터
            {timestamp} - YYYYMMDD_HHMMSS
            {mode} - NAI/WEBUI/COMFYUI
            {seed} - 생성 시드 (메타데이터에서 추출)

        Example:
            controller.set_filename_template("{mode}_{counter:05d}_{seed}")
            # 결과: NAI_00001_123456.png

        Phase 2에서 구현 예정
        """
        raise NotImplementedError("Phase 2에서 구현 예정")
