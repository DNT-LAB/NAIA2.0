"""
Sequence Generation Worker for Turbo Event Sequence Tab

NAIA의 표준 생성 파이프라인(GenerationController)을 사용하는 시퀀스 이미지 생성 워커.
QThread를 상속하여 백그라운드에서 순차적으로 이미지를 생성합니다.
"""

from PyQt6.QtCore import pyqtSignal, QTimer, QObject
from PIL import Image
import io
from typing import List, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.context import AppContext

# 인원 태그 키워드
PERSON_KEYWORDS = ["boy", "girl", "other"]

# Rating 태그 매핑
RATING_TAG_MAP = {
    'g': ['rating:general'],
    's': ['rating:sensitive'],
    'q': ['rating:questionable'],
    'e': ['nsfw', 'rating:questionable'],
}


class SequenceGenerationWorker(QObject):
    """
    NAIA 표준 파이프라인 기반의 시퀀스 이미지 생성 워커.

    GenerationController.execute_generation_pipeline()을 호출하여
    NAIA의 표준 생성 흐름을 따릅니다.
    """

    # ===================== Signals =====================

    # 개별 이미지 생성 완료: (index, PIL.Image)
    image_generated = pyqtSignal(int, object)

    # 진행률 업데이트: (current, total, status_message)
    progress_updated = pyqtSignal(int, int, str)

    # 전체 완료: [PIL.Image, ...]
    generation_finished = pyqtSignal(list)

    # 에러 발생: (failed_index, error_message)
    generation_error = pyqtSignal(int, str)

    # 취소됨
    generation_cancelled = pyqtSignal()

    # ===================== Constants =====================

    # 샘플 이미지 크기 (첫 번째 이미지 생성용)
    SAMPLE_SIZE_H = (1152, 832)   # 가로 방향 (width, height)
    SAMPLE_SIZE_V = (832, 1152)   # 세로 방향 (width, height)

    # Inpaint 캔버스 크기
    # 가로 방향: 세로로 확장 (832 x 1216) - 이미지를 위에 배치하고 아래로 생성
    # 세로 방향: 가로로 확장 (1216 x 832) - 이미지를 왼쪽에 배치하고 오른쪽으로 생성
    CANVAS_SIZE_H = (832, 1216)   # 가로 방향 (width, height)
    CANVAS_SIZE_V = (1216, 832)   # 세로 방향 (width, height)

    # 이전 이미지를 캔버스에 붙일 때의 크기 (정확히 절반)
    # 가로 방향: 832 x 608 영역에 이미지 배치 (캔버스 높이 1216의 절반)
    # 세로 방향: 608 x 832 영역에 이미지 배치 (캔버스 너비 1216의 절반)
    PASTE_SIZE_H = (832, 608)     # 가로 방향에서 붙여넣을 영역 (1216/2 = 608)
    PASTE_SIZE_V = (608, 832)     # 세로 방향에서 붙여넣을 영역 (1216/2 = 608)

    # ===================== Constructor =====================

    def __init__(
        self,
        app_context: 'AppContext',
        prompts: List[Dict],
        direction: str = 'horizontal',
        strength: float = 0.7,
        negative_prompt: str = '',
        prev_images: List[Image.Image] = None,
        start_index: int = 0
    ):
        """
        SequenceGenerationWorker 초기화.

        Args:
            app_context: NAIA AppContext
            prompts: 프롬프트 리스트
                [
                    {'index': 0, 'id': 12345, 'general': '1girl, smile...', 'is_parent': True},
                    {'index': 1, 'id': 12346, 'general': '1girl, blush...', 'is_parent': False},
                    ...
                ]
            direction: 'horizontal' 또는 'vertical'
            strength: Inpaint 강도 (0.0 ~ 1.0)
            negative_prompt: 공통 네거티브 프롬프트
            prev_images: 이전에 생성된 이미지 리스트 (중간부터 시작 시 사용)
            start_index: 시작 인덱스 (시그널에 전달할 실제 인덱스)
        """
        super().__init__()

        self.app_context = app_context
        self.prompts = prompts
        self.direction = direction
        self.strength = strength
        # 🆕 네거티브 프롬프트 앞에 split screen 방지 태그 추가
        self.negative_prompt = negative_prompt #self._prepare_negative_prompt(negative_prompt)
        self.prev_images = prev_images or []
        self.start_index = start_index
        # Base reference image (parent) when continuing a sequence.
        self.base_reference_image = self.prev_images[0] if self.prev_images else None

        # 취소 플래그
        self._cancelled = False

        # 생성된 이미지 리스트
        self._generated_images: List[Image.Image] = []

        # 현재 생성 중인 인덱스
        self._current_index = 0

        # 생성 완료 대기 플래그
        self._waiting_for_result = False
        self._last_result = None
        self._pending_request_is_inpaint = False

        # 방향에 따른 크기 설정
        if direction == 'horizontal':
            self.sample_width, self.sample_height = self.SAMPLE_SIZE_H
            self.canvas_width, self.canvas_height = self.CANVAS_SIZE_H
        else:  # vertical
            self.sample_width, self.sample_height = self.SAMPLE_SIZE_V
            self.canvas_width, self.canvas_height = self.CANVAS_SIZE_V

    # ===================== Main Methods =====================

    def start_generation(self):
        """시퀀스 생성 시작 - 메인 스레드에서 호출"""
        if len(self.prompts) == 0:
            self.generation_error.emit(-1, "프롬프트 리스트가 비어있습니다.")
            return

        self._generated_images = []
        self._pending_request_is_inpaint = False
        self._current_index = 0

        # 생성 완료 이벤트 구독
        self._subscribe_generation_events()

        # 첫 번째 생성 시작
        self._generate_next()

    def cancel(self):
        """생성 취소"""
        self._cancelled = True
        self._unsubscribe_generation_events()

    # ===================== Event Subscription =====================

    def _subscribe_generation_events(self):
        """생성 완료 이벤트 구독"""
        if hasattr(self.app_context, 'subscribe'):
            self.app_context.subscribe('generation_completed', self._on_generation_completed)
            self.app_context.subscribe('generation_error', self._on_generation_error_event)

    def _unsubscribe_generation_events(self):
        """이벤트 구독 해제"""
        if hasattr(self.app_context, 'unsubscribe'):
            try:
                self.app_context.unsubscribe('generation_completed', self._on_generation_completed)
                self.app_context.unsubscribe('generation_error', self._on_generation_error_event)
            except:
                pass

    # ===================== Generation Flow =====================

    def _generate_next(self):
        """다음 이미지 생성"""
        if self._cancelled:
            self._unsubscribe_generation_events()
            self.generation_cancelled.emit()
            return

        if self._current_index >= len(self.prompts):
            # 모든 생성 완료
            self._unsubscribe_generation_events()
            self.progress_updated.emit(len(self.prompts), len(self.prompts), "생성 완료!")
            self.generation_finished.emit(self._generated_images)
            return

        prompt_data = self.prompts[self._current_index]
        actual_index = self.start_index + self._current_index
        is_parent_prompt = bool(prompt_data.get('is_parent', False))

        # 🆕 프롬프트 처리 (고정 프롬프트 + rating 태그 적용)
        prompt = self._process_prompt(prompt_data)
        print(f"[SequenceWorker] 처리된 프롬프트 ({actual_index}): {prompt[:100]}...")

        # 진행률 업데이트
        page_type = "Parent" if is_parent_prompt else f"Child {actual_index}"
        status = f"{page_type} 생성 중..."
        self.progress_updated.emit(self._current_index, len(self.prompts), status)

        try:
            if is_parent_prompt:
                # 첫 번째 이미지: txt2img
                self._request_txt2img_generation(prompt)
            else:
                # 후속 이미지: 항상 첫 번째 이미지를 참조하여 Inpaint
                # (Sliding Window 대신 고정 참조 방식)
                if self.base_reference_image is not None:
                    # Always inpaint from the base(parent) image when available.
                    prev_image = self.base_reference_image
                elif len(self._generated_images) > 0:
                    # 현재 세션에서 생성된 첫 번째 이미지
                    prev_image = self._generated_images[0]
                else:
                    self.generation_error.emit(actual_index, "참조할 이미지가 없습니다")
                    return

                self._request_inpaint_generation(prev_image, prompt)

        except Exception as e:
            self.generation_error.emit(actual_index, str(e))
            self._unsubscribe_generation_events()

    def _request_txt2img_generation(self, prompt: str):
        """txt2img 생성 요청 - GenerationController 사용"""
        override_params = {
            'input': prompt,
            'negative_prompt': self.negative_prompt,
            'width': self.sample_width,
            'height': self.sample_height,
            'random_resolution': False,
            'turbo_sequence_request': True,  # 식별자
            'turbo_sequence_index': self.start_index + self._current_index,
        }

        self._waiting_for_result = True
        self._pending_request_is_inpaint = False
        self._execute_generation_pipeline(override_params)

    def _request_inpaint_generation(self, prev_image: Image.Image, prompt: str):
        """Inpaint 생성 요청 - GenerationController 사용"""
        # 이미지 데이터 완전 로드
        if hasattr(prev_image, 'load'):
            prev_image.load()

        # Inpaint 캔버스 및 마스크 생성
        canvas = self._create_inpaint_canvas(prev_image)
        mask = self._create_inpaint_mask()

        # 🔧 디버그: 요청 전 캔버스와 마스크 미리보기
        self._show_debug_preview(canvas, mask)

        # 이미지를 bytes로 변환
        canvas_bytes = io.BytesIO()
        canvas.save(canvas_bytes, format='PNG')
        canvas_bytes.seek(0)

        mask_bytes = io.BytesIO()
        mask.save(mask_bytes, format='PNG')
        mask_bytes.seek(0)

        override_params = {
            'type': 'inpaint',
            'input': prompt,
            'negative_prompt': self.negative_prompt,
            'image_bytes': canvas_bytes.getvalue(),
            'mask_bytes': mask_bytes.getvalue(),
            'width': self.canvas_width,
            'height': self.canvas_height,
            'strength': self.strength,
            'noise': 0.0,
            'random_resolution': False,
            'turbo_sequence_request': True,
            'turbo_sequence_index': self.start_index + self._current_index,
        }

        self._waiting_for_result = True
        self._pending_request_is_inpaint = True
        self._execute_generation_pipeline(override_params)

    def _show_debug_preview(self, canvas: Image.Image, mask: Image.Image):
        """디버그용 캔버스 및 마스크 미리보기 (배포 시 비활성화)"""
        # 🔧 디버그 모드 비활성화 (배포용)
        return

        # try:
        #     # 캔버스와 마스크를 나란히 표시할 디버그 이미지 생성
        #     # 마스크를 캔버스 크기로 확대
        #     mask_enlarged = mask.resize((self.canvas_width, self.canvas_height), Image.Resampling.NEAREST)
        #     mask_rgb = mask_enlarged.convert('RGB')

        #     # 캔버스와 마스크를 나란히 붙임
        #     debug_width = self.canvas_width * 2 + 20
        #     debug_height = self.canvas_height
        #     debug_image = Image.new('RGB', (debug_width, debug_height), (50, 50, 50))

        #     # 캔버스 붙이기
        #     debug_image.paste(canvas, (0, 0))

        #     # 마스크 붙이기
        #     debug_image.paste(mask_rgb, (self.canvas_width + 20, 0))

        #     # 디버그 이미지 표시
        #     actual_index = self.start_index + self._current_index
        #     print(f"🔧 [Debug] Index {actual_index}: Canvas ({self.canvas_width}x{self.canvas_height}) + Mask")
        #     debug_image.show()
        # except Exception as e:
        #     print(f"🔧 [Debug] Preview error: {e}")

    def _execute_generation_pipeline(self, override_params: dict):
        """GenerationController를 통해 생성 실행"""
        try:
            main_window = self.app_context.main_window
            if hasattr(main_window, 'generation_controller'):
                gen_controller = main_window.generation_controller
                gen_controller.execute_generation_pipeline(overrides=override_params)
            else:
                raise Exception("GenerationController를 찾을 수 없습니다.")
        except Exception as e:
            actual_index = self.start_index + self._current_index
            self.generation_error.emit(actual_index, str(e))
            self._unsubscribe_generation_events()

    # ===================== Event Handlers =====================

    def _on_generation_completed(self, result: dict):
        """생성 완료 이벤트 핸들러"""
        if not self._waiting_for_result:
            return

        # turbo_sequence_request가 아닌 경우 무시
        if not result.get('turbo_sequence_request'):
            return

        self._waiting_for_result = False

        try:
            image = result.get('image')
            if image is None:
                actual_index = self.start_index + self._current_index
                self.generation_error.emit(actual_index, "이미지 생성 실패")
                self._unsubscribe_generation_events()
                return

            # Inpaint 결과인 경우 크롭
            actual_index = self.start_index + self._current_index
            if self._pending_request_is_inpaint:
                # Inpaint 결과에서 새 영역 추출
                image = self._crop_result(image)

            # 이미지 저장
            self._generated_images.append(image)

            # 시그널 발생
            self.image_generated.emit(actual_index, image)

            # 다음 생성
            self._current_index += 1
            # 약간의 딜레이 후 다음 생성 (UI 업데이트 시간 확보)
            QTimer.singleShot(100, self._generate_next)

        except Exception as e:
            actual_index = self.start_index + self._current_index
            self.generation_error.emit(actual_index, str(e))
            self._unsubscribe_generation_events()

    def _on_generation_error_event(self, error_data: dict):
        """생성 에러 이벤트 핸들러"""
        if not self._waiting_for_result:
            return

        # turbo_sequence_request가 아닌 경우 무시
        if not error_data.get('turbo_sequence_request'):
            return

        self._waiting_for_result = False
        actual_index = self.start_index + self._current_index
        error_msg = error_data.get('message', 'Unknown error')
        self.generation_error.emit(actual_index, error_msg)
        self._unsubscribe_generation_events()

    # ===================== Canvas & Mask Creation =====================

    def _create_inpaint_canvas(self, prev_image: Image.Image) -> Image.Image:
        """
        Inpaint용 캔버스 생성 (정확히 절반 분할).

        가로 방향 (horizontal):
        - 캔버스: 832 x 1216
        - 이전 이미지를 상단 절반(832 x 608)에 리사이즈하여 배치
        - 하단 절반(832 x 608)은 Inpaint 영역

        세로 방향 (vertical):
        - 캔버스: 1216 x 832
        - 이전 이미지를 좌측 절반(608 x 832)에 리사이즈하여 배치
        - 우측 절반(608 x 832)은 Inpaint 영역
        """
        # 이미지 데이터 완전 로드
        if hasattr(prev_image, 'load'):
            prev_image.load()

        # 캔버스 생성 (RGB 모드, 검정 배경)
        canvas = Image.new('RGB', (self.canvas_width, self.canvas_height), (0, 0, 0))

        if self.direction == 'horizontal':
            # 가로 방향: 상단 절반에 배치
            paste_width, paste_height = self.PASTE_SIZE_H  # (832, 608)

            # 이미지를 붙여넣을 영역 크기에 맞게 리사이즈 (비율 유지, 크롭)
            resized = self._resize_and_crop(prev_image, paste_width, paste_height)

            # 캔버스 상단(0, 0)에 배치
            canvas.paste(resized, (0, 0))

            # 🆕 경계선 추가 (Split screen 유도): 601~608px 영역을 검은색으로 칠함
            # 상단 이미지의 하단 8px을 덮어씀
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            # (x0, y0, x1, y1) - y1은 포함되지 않음 (PIL 버전에 따라 다를 수 있으니 주의, rectangle은 x1,y1 포함)
            # 여기서는 확실하게 601부터 608까지 칠함
            draw.rectangle([(0, 600), (self.canvas_width, 608)], fill=(0, 0, 0))

        else:  # vertical
            # 세로 방향: 좌측 절반에 배치
            paste_width, paste_height = self.PASTE_SIZE_V  # (608, 832)

            # 이미지를 붙여넣을 영역 크기에 맞게 리사이즈 (비율 유지, 크롭)
            resized = self._resize_and_crop(prev_image, paste_width, paste_height)

            # 캔버스 좌측(0, 0)에 배치
            canvas.paste(resized, (0, 0))

            # 🆕 경계선 추가 (Split screen 유도): 601~608px 영역을 검은색으로 칠함
            # 좌측 이미지의 우측 7px을 덮어씀
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            draw.rectangle([(601, 0), (608, self.canvas_height)], fill=(0, 0, 0))

        return canvas

    def _resize_and_crop(self, image: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """이미지를 목표 크기에 맞게 리사이즈하고 중앙 크롭"""
        orig_w, orig_h = image.size

        # 비율 계산: 목표 영역을 완전히 채우도록 스케일
        scale_w = target_w / orig_w
        scale_h = target_h / orig_h
        scale = max(scale_w, scale_h)  # 더 큰 스케일 사용 (영역을 완전히 채움)

        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)

        resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 중앙 크롭
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        cropped = resized.crop((left, top, left + target_w, top + target_h))

        return cropped

    def _create_inpaint_mask(self) -> Image.Image:
        """
        1/8 크기 마스크 생성 (정확히 절반 분할).

        NAI API는 캔버스 크기의 1/8 크기 마스크를 요구합니다.
        - 검정 (0): 보존 영역
        - 흰색 (255): Inpaint 영역

        가로 방향:
        - 캔버스: 832 x 1216 -> 마스크: 104 x 152
        - 상단 절반(608px = 76px in mask): 보존
        - 하단 절반(608px = 76px in mask): Inpaint

        세로 방향:
        - 캔버스: 1216 x 832 -> 마스크: 152 x 104
        - 좌측 절반(608px = 76px in mask): 보존
        - 우측 절반(608px = 76px in mask): Inpaint
        """
        mask_width = self.canvas_width // 8
        mask_height = self.canvas_height // 8

        # 검정(보존) 마스크로 시작
        mask = Image.new('L', (mask_width, mask_height), 0)

        if self.direction == 'horizontal':
            # 가로 방향: 하단 절반이 Inpaint 영역
            # 캔버스 1216px -> 절반 608px -> 마스크에서 76px
            half_height = mask_height // 2  # 152 // 2 = 76
            mask.paste(255, (0, half_height, mask_width, mask_height))
        else:
            # 세로 방향: 우측 절반이 Inpaint 영역
            # 캔버스 1216px -> 절반 608px -> 마스크에서 76px
            half_width = mask_width // 2  # 152 // 2 = 76
            mask.paste(255, (half_width, 0, mask_width, mask_height))

        return mask

    def _crop_result(self, inpaint_result: Image.Image) -> Image.Image:
        """
        Inpaint 결과에서 새로 생성된 영역 추출 (정확히 절반).

        가로 방향: 하단 절반(608px) 추출
        세로 방향: 우측 절반(608px) 추출
        """
        if self.direction == 'horizontal':
            # 가로 방향: 하단 절반 추출
            half_height = self.canvas_height // 2  # 1216 // 2 = 608
            return inpaint_result.crop((0, half_height, self.canvas_width, self.canvas_height))
        else:
            # 세로 방향: 우측 절반 추출
            half_width = self.canvas_width // 2  # 1216 // 2 = 608
            return inpaint_result.crop((half_width, 0, self.canvas_width, self.canvas_height))

    # ===================== Prompt Processing =====================

    def _get_fixed_prompts(self) -> tuple:
        """
        PromptEngineeringModule에서 선행/후행 고정 프롬프트 가져오기.

        Returns:
            tuple: (leading_prompt_tags, trailing_prompt_tags) - 각각 태그 리스트
        """
        leading_tags = []
        trailing_tags = []

        try:
            main_window = self.app_context.main_window
            if hasattr(main_window, 'middle_section_controller'):
                pe_module = main_window.middle_section_controller.get_module_instance("PromptEngineeringModule")
                if pe_module:
                    # 선행 고정 프롬프트
                    if hasattr(pe_module, 'pre_textedit'):
                        pre_text = pe_module.pre_textedit.toPlainText().strip()
                        if pre_text:
                            leading_tags = [t.strip() for t in pre_text.split(',') if t.strip()]

                    # 후행 고정 프롬프트
                    if hasattr(pe_module, 'post_textedit'):
                        post_text = pe_module.post_textedit.toPlainText().strip()
                        if post_text:
                            trailing_tags = [t.strip() for t in post_text.split(',') if t.strip()]
        except Exception as e:
            print(f"[SequenceWorker] 고정 프롬프트 가져오기 오류: {e}")

        return leading_tags, trailing_tags

    def _find_last_person_index(self, tags: List[str]) -> int:
        """
        태그 리스트에서 boy/girl/other의 마지막 인덱스 찾기.

        Args:
            tags: 태그 리스트

        Returns:
            마지막 인원 태그 인덱스, 없으면 -1
        """
        last_idx = -1
        for idx, tag in enumerate(tags):
            tag_lower = tag.lower()
            for keyword in PERSON_KEYWORDS:
                if keyword in tag_lower:
                    last_idx = idx
                    break
        return last_idx

    def _process_prompt(self, prompt_data: Dict) -> str:
        """
        프롬프트에 고정 프롬프트 및 rating 태그 적용.

        프롬프트 엔지니어링 옵션과 관계없이 항상 적용됩니다.

        1. ','로 split 및 strip
        2. boy/girl/other의 마지막 인덱스 찾기
        3. 선행 고정 프롬프트를 인덱스 뒤에 삽입
        4. rating 태그 추가 (g→rating:general, s→rating:sensitive, q→rating:questionable, e→nsfw, rating:questionable)
        5. 후행 고정 프롬프트를 끝에 삽입

        Args:
            prompt_data: 프롬프트 데이터 딕셔너리 {'general': '...', 'rating': '...', ...}

        Returns:
            처리된 프롬프트 문자열
        """
        prompt = prompt_data.get('general', '')
        rating = str(prompt_data.get('rating', '')).lower()

        # 고정 프롬프트 가져오기
        leading_tags, trailing_tags = self._get_fixed_prompts()

        # 태그 분리
        tags = [t.strip() for t in prompt.split(',') if t.strip()]

        # 인원 태그 인덱스 찾기
        person_idx = self._find_last_person_index(tags)

        # 이미 존재하는 태그 세트 (중복 방지용)
        existing_tags_lower = set(t.lower() for t in tags)

        # 1. 선행 고정 프롬프트 삽입 (중복 제외)
        if leading_tags and person_idx >= 0:
            new_leading = [t for t in leading_tags if t.lower() not in existing_tags_lower]
            if new_leading:
                insert_pos = person_idx + 1
                tags = tags[:insert_pos] + new_leading + tags[insert_pos:]
                # 기존 태그 세트 업데이트
                existing_tags_lower.update(t.lower() for t in new_leading)

        # 2. Rating 태그 추가
        rating_tags = RATING_TAG_MAP.get(rating, [])
        if rating_tags:
            new_rating_tags = [t for t in rating_tags if t.lower() not in existing_tags_lower]
            if new_rating_tags:
                tags.extend(new_rating_tags)
                existing_tags_lower.update(t.lower() for t in new_rating_tags)

        # 3. 후행 고정 프롬프트 추가 (중복 제외)
        if trailing_tags:
            new_trailing = [t for t in trailing_tags if t.lower() not in existing_tags_lower]
            if new_trailing:
                tags.extend(new_trailing)

        return ', '.join(tags)

    # ===================== Utility Methods =====================

    def _prepare_negative_prompt(self, negative_prompt: str) -> str:
        """
        네거티브 프롬프트 앞에 split screen 방지 태그 추가.

        Turbo Event Sequence는 이미지를 이어붙여 생성하므로,
        split screen 현상을 방지하기 위해 네거티브에 관련 태그를 추가합니다.

        Args:
            negative_prompt: 원본 네거티브 프롬프트

        Returns:
            처리된 네거티브 프롬프트
        """
        # split screen 방지 태그 (NAI 가중치 형식)
        split_screen_tag = "1.5::split screen, black border ::"

        if not negative_prompt or not negative_prompt.strip():
            return split_screen_tag

        # 이미 split screen 태그가 있는지 확인
        if "split screen" in negative_prompt.lower():
            return negative_prompt

        # 앞에 추가
        return f"{split_screen_tag}, {negative_prompt}"

    def get_generated_images(self) -> List[Image.Image]:
        """생성된 이미지 리스트 반환"""
        return self._generated_images.copy()

    def get_progress(self) -> tuple:
        """현재 진행 상황 반환: (current, total)"""
        return len(self._generated_images), len(self.prompts)
