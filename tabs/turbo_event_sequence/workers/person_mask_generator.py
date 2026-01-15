"""
Person Mask Generator for Turbo Event Sequence

YOLO 기반 인물 분할을 사용하여 배경 보존 마스크를 생성합니다.
- 배경 정보 유지 옵션 활성화 시 사용
- 인물 영역만 Inpaint 대상으로 설정하여 배경 유지

Model: person_yolov8n-seg.pt (data/ 폴더)
"""

import os
from pathlib import Path
from typing import Optional, Tuple, List
from PIL import Image
import numpy as np


class PersonMaskGenerator:
    """
    YOLO 기반 인물 마스크 생성기.

    인물 영역을 감지하고 확장된 마스크를 생성합니다.
    배경 보존 Inpainting에 사용됩니다.
    """

    # 마스크 확장 비율 (인물 영역 주변 여유 공간)
    # 1.0 = 확장 없음, 1.1 = 10% 확장, 1.3 = 30% 확장
    # 고립된 배경 영역(손/옷 밖 등)을 포함시키기 위해 1.25 사용
    EXPANSION_RATIO = 1.07

    # YOLO 신뢰도 임계값
    CONFIDENCE_THRESHOLD = 0.25

    def __init__(self, model_path: Optional[str] = None):
        """
        PersonMaskGenerator 초기화.

        Args:
            model_path: YOLO 모델 경로. None이면 기본 경로 사용.
        """
        self._model = None
        self._model_loaded = False

        # 기본 모델 경로 설정
        if model_path is None:
            # NAIA2.0/data/person_yolov8n-seg.pt
            base_dir = Path(__file__).parent.parent.parent.parent
            model_path = str(base_dir / 'data' / 'person_yolov8n-seg.pt')

        self.model_path = model_path

    @property
    def model(self):
        """YOLO 모델 (Lazy load)"""
        if not self._model_loaded:
            self._load_model()
        return self._model

    def _load_model(self):
        """YOLO 모델 로드"""
        try:
            if not os.path.exists(self.model_path):
                print(f"[PersonMaskGenerator] Model not found: {self.model_path}")
                self._model = None
            else:
                from ultralytics import YOLO
                self._model = YOLO(self.model_path)
                print(f"[PersonMaskGenerator] Model loaded: {self.model_path}")
        except ImportError as e:
            print(f"[PersonMaskGenerator] ultralytics import failed: {e}")
            print("[PersonMaskGenerator] ultralytics not installed or broken. Run: pip install ultralytics")
            self._model = None
        except Exception as e:
            print(f"[PersonMaskGenerator] Failed to load model: {e}")
            self._model = None

        self._model_loaded = True

    def generate_person_mask(
        self,
        image: Image.Image,
        expansion_ratio: float = None
    ) -> Optional[Image.Image]:
        """
        이미지에서 인물 마스크 생성.

        Args:
            image: 입력 이미지 (PIL Image)
            expansion_ratio: 마스크 확장 비율 (기본값: EXPANSION_RATIO)

        Returns:
            인물 마스크 (흰색=인물 영역, 검정=배경) 또는 None
        """
        if self.model is None:
            print("[PersonMaskGenerator] Model not available")
            return None

        if expansion_ratio is None:
            expansion_ratio = self.EXPANSION_RATIO

        try:
            # PIL Image → numpy array
            image_np = np.array(image.convert('RGB'))

            # YOLO 추론 (CPU 사용)
            results = self.model(
                image_np,
                conf=self.CONFIDENCE_THRESHOLD,
                device="cpu",
                verbose=False
            )

            if not results or len(results) == 0:
                print("[PersonMaskGenerator] No detection results")
                return None

            result = results[0]

            # 마스크가 없는 경우
            if result.masks is None or len(result.masks) == 0:
                print("[PersonMaskGenerator] No masks detected")
                return None

            # 모든 인물 마스크 합치기
            combined_mask = self._combine_masks(result.masks, image_np.shape[:2])

            if combined_mask is None:
                return None

            # 마스크 확장
            expanded_mask = self._expand_mask(combined_mask, expansion_ratio)

            # 🔧 디버그: 마스크 값 확인
            print(f"[PersonMaskGenerator] Mask stats - min: {expanded_mask.min()}, max: {expanded_mask.max()}, mean: {expanded_mask.mean():.1f}")
            print(f"[PersonMaskGenerator] Non-zero pixels: {np.count_nonzero(expanded_mask)} / {expanded_mask.size}")

            # numpy → PIL Image (명시적으로 'L' 모드 지정)
            mask_image = Image.fromarray(expanded_mask.astype(np.uint8), mode='L')

            print(f"[PersonMaskGenerator] Mask generated: {mask_image.size}, mode: {mask_image.mode}")
            return mask_image

        except Exception as e:
            print(f"[PersonMaskGenerator] Error generating mask: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _combine_masks(
        self,
        masks,
        image_shape: Tuple[int, int]
    ) -> Optional[np.ndarray]:
        """
        여러 마스크를 하나로 합침.

        Args:
            masks: YOLO 마스크 결과
            image_shape: (height, width)

        Returns:
            합쳐진 마스크 (0-255)
        """
        height, width = image_shape
        combined = np.zeros((height, width), dtype=np.uint8)

        try:
            print(f"[PersonMaskGenerator] _combine_masks: {len(masks.data)} masks, target shape: ({height}, {width})")

            for i, mask in enumerate(masks.data):
                # 텐서 → numpy
                mask_np = mask.cpu().numpy()
                print(f"[PersonMaskGenerator] Mask {i}: shape={mask_np.shape}, dtype={mask_np.dtype}, min={mask_np.min():.3f}, max={mask_np.max():.3f}")

                # 마스크 크기가 다르면 리사이즈
                if mask_np.shape != (height, width):
                    from PIL import Image as PILImage
                    mask_pil = PILImage.fromarray((mask_np * 255).astype(np.uint8))
                    mask_pil = mask_pil.resize((width, height), PILImage.Resampling.NEAREST)
                    mask_np = np.array(mask_pil) / 255.0
                    print(f"[PersonMaskGenerator] Mask {i} resized: shape={mask_np.shape}, min={mask_np.min():.3f}, max={mask_np.max():.3f}")

                # 합치기 (OR 연산)
                mask_255 = (mask_np * 255).astype(np.uint8)
                print(f"[PersonMaskGenerator] Mask {i} * 255: min={mask_255.min()}, max={mask_255.max()}, non-zero={np.count_nonzero(mask_255)}")
                combined = np.maximum(combined, mask_255)

            print(f"[PersonMaskGenerator] Combined mask: min={combined.min()}, max={combined.max()}, non-zero={np.count_nonzero(combined)}")
            return combined

        except Exception as e:
            print(f"[PersonMaskGenerator] Error combining masks: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _expand_mask(
        self,
        mask: np.ndarray,
        expansion_ratio: float
    ) -> np.ndarray:
        """
        마스크를 Morphological Dilation으로 확장.

        세그멘트의 형태를 유지하면서 가장자리를 확장합니다.
        고립된 배경 영역(손/옷 바깥 등)을 포함시키기 위함.

        Args:
            mask: 원본 마스크 (0-255)
            expansion_ratio: 확장 비율 (1.05 = 5% 확장 → ~15px padding)

        Returns:
            확장된 마스크
        """
        if expansion_ratio <= 1.0:
            return mask

        try:
            from scipy import ndimage

            height, width = mask.shape

            # expansion_ratio를 픽셀 패딩으로 변환
            # 이미지 크기의 비율로 계산 (예: 1.05 = 5% → 약 30px for 600px image)
            avg_dim = (height + width) / 2
            padding_pixels = int(avg_dim * (expansion_ratio - 1.0))
            padding_pixels = max(5, padding_pixels)  # 최소 5px

            print(f"[PersonMaskGenerator] Dilation padding: {padding_pixels}px (ratio={expansion_ratio})")

            # 바이너리 마스크로 변환
            binary_mask = mask > 127

            # Morphological Dilation (4-connected 구조 요소 사용)
            struct = ndimage.generate_binary_structure(2, 1)
            iterations = padding_pixels

            dilated = ndimage.binary_dilation(
                binary_mask,
                structure=struct,
                iterations=iterations
            )

            # 다시 0-255 범위로 변환
            expanded = (dilated.astype(np.uint8)) * 255

            print(f"[PersonMaskGenerator] Mask expanded: {np.count_nonzero(mask > 127)} → {np.count_nonzero(expanded > 127)} pixels")

            return expanded

        except ImportError:
            print("[PersonMaskGenerator] scipy not available, skipping dilation")
            return mask
        except Exception as e:
            print(f"[PersonMaskGenerator] Error expanding mask: {e}")
            return mask

    def create_inpaint_mask_with_person(
        self,
        prev_image: Image.Image,
        canvas_size: Tuple[int, int],
        paste_size: Tuple[int, int],
        direction: str,
        mask_scale: int = 8,
        debug: bool = False
    ) -> Optional[Image.Image]:
        """
        인물 감지 기반 Inpaint 마스크 생성.

        기본 Inpaint 마스크(하단/우측 절반 = 흰색)에서
        배경 영역을 제거하여 인물 영역만 Inpaint 대상으로 남깁니다.

        **핵심 로직**:
        1. prev_image를 paste 영역 크기로 리사이즈
        2. 리사이즈된 이미지에서 YOLO로 인물 감지 → 인물 마스크 생성
        3. 기본 Inpaint 마스크(하단/우측 = 흰색)와 인물 마스크를 AND 연산
        4. 결과: 인물 영역만 Inpaint, 배경은 보존

        Args:
            prev_image: 이전 이미지 (참조 이미지)
            canvas_size: 캔버스 크기 (width, height) - 예: (832, 1216)
            paste_size: 이전 이미지를 붙일 영역 크기 (width, height) - 예: (832, 608)
            direction: 'horizontal' 또는 'vertical'
            mask_scale: 마스크 축소 비율 (NAI API는 1/8 사용)
            debug: 디버그 시각화 표시 여부

        Returns:
            NAI API용 마스크 (1/8 크기) 또는 None (실패 시)
        """
        canvas_width, canvas_height = canvas_size
        paste_width, paste_height = paste_size

        # 1. prev_image를 paste 영역 크기로 리사이즈 (YOLO 입력용)
        prev_resized = self._resize_and_crop(prev_image, paste_width, paste_height)

        # 2. 리사이즈된 이미지에서 인물 마스크 생성
        person_mask = self.generate_person_mask(prev_resized)

        if person_mask is None:
            print("[PersonMaskGenerator] YOLO detection failed")
            return None

        # person_mask는 이미 paste 영역 크기와 동일함
        person_mask_np = np.array(person_mask)

        # 🔧 디버그: person_mask_np 값 확인
        print(f"[PersonMaskGenerator] person_mask_np - shape: {person_mask_np.shape}, dtype: {person_mask_np.dtype}")
        print(f"[PersonMaskGenerator] person_mask_np - min: {person_mask_np.min()}, max: {person_mask_np.max()}, non-zero: {np.count_nonzero(person_mask_np)}")

        # 3. 전체 캔버스 크기의 기본 Inpaint 마스크 생성
        # 기본값: 상단/좌측 = 검정(보존), 하단/우측 = 흰색(Inpaint)
        full_mask = np.zeros((canvas_height, canvas_width), dtype=np.uint8)

        if direction == 'horizontal':
            # 가로 방향: 하단 절반이 Inpaint 영역
            half_height = canvas_height // 2  # 608
            inpaint_height = canvas_height - half_height  # 608
            inpaint_width = canvas_width  # 832

            # 인물 마스크를 Inpaint 영역 크기로 리사이즈
            person_mask_for_inpaint = Image.fromarray(person_mask_np).resize(
                (inpaint_width, inpaint_height),
                Image.Resampling.NEAREST
            )

            # 하단 Inpaint 영역에 인물 마스크 적용
            # (인물 = 흰색 = Inpaint, 배경 = 검정 = 보존)
            full_mask[half_height:canvas_height, 0:canvas_width] = np.array(person_mask_for_inpaint)

        else:  # vertical
            # 세로 방향: 우측 절반이 Inpaint 영역
            half_width = canvas_width // 2  # 608
            inpaint_width = canvas_width - half_width  # 608
            inpaint_height = canvas_height  # 832

            # 인물 마스크를 Inpaint 영역 크기로 리사이즈
            person_mask_for_inpaint = Image.fromarray(person_mask_np).resize(
                (inpaint_width, inpaint_height),
                Image.Resampling.NEAREST
            )

            # 우측 Inpaint 영역에 인물 마스크 적용
            full_mask[0:canvas_height, half_width:canvas_width] = np.array(person_mask_for_inpaint)

        # 🔧 디버그: full_mask 값 확인
        print(f"[PersonMaskGenerator] full_mask - shape: {full_mask.shape}, min: {full_mask.min()}, max: {full_mask.max()}, non-zero: {np.count_nonzero(full_mask)}")

        # 4. 1/8 크기로 축소
        full_mask_pil = Image.fromarray(full_mask, mode='L')
        print(f"[PersonMaskGenerator] full_mask_pil - size: {full_mask_pil.size}, mode: {full_mask_pil.mode}")

        final_mask = full_mask_pil.resize(
            (canvas_width // mask_scale, canvas_height // mask_scale),
            Image.Resampling.NEAREST
        )

        # 🔧 디버그: final_mask 값 확인
        final_mask_np = np.array(final_mask)
        print(f"[PersonMaskGenerator] final_mask - size: {final_mask.size}, min: {final_mask_np.min()}, max: {final_mask_np.max()}, non-zero: {np.count_nonzero(final_mask_np)}")

        # 🔧 디버그: 마스크 생성 과정 시각화
        if debug:
            self._show_debug_visualization(
                prev_image, prev_resized, person_mask,
                full_mask_pil, final_mask, direction
            )

        print(f"[PersonMaskGenerator] Inpaint mask created: {final_mask.size} (from {canvas_size})")
        return final_mask

    def _resize_and_crop(self, image: Image.Image, target_w: int, target_h: int) -> Image.Image:
        """이미지를 목표 크기에 맞게 리사이즈하고 중앙 크롭"""
        orig_w, orig_h = image.size

        # 비율 계산: 목표 영역을 완전히 채우도록 스케일
        scale_w = target_w / orig_w
        scale_h = target_h / orig_h
        scale = max(scale_w, scale_h)

        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)

        resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 중앙 크롭
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        cropped = resized.crop((left, top, left + target_w, top + target_h))

        return cropped

    def _show_debug_visualization(
        self,
        original: Image.Image,
        prev_resized: Image.Image,
        person_mask: Image.Image,
        full_mask: Image.Image,
        final_mask: Image.Image,
        direction: str
    ):
        """
        디버그용 시각화: YOLO 감지 결과 및 마스크 변환 과정 표시.

        표시 순서 (좌→우):
        1. 원본 이미지
        2. 리사이즈된 이미지 (paste 영역 크기, YOLO 입력)
        3. YOLO 인물 마스크 (paste 영역 크기)
        4. Full 캔버스 마스크 (1:1)
        5. 최종 마스크 (1/8, 확대 표시)
        """
        try:
            # 공통 높이로 정규화 (400px)
            target_height = 400

            def resize_for_display(img: Image.Image) -> Image.Image:
                """표시용 리사이즈"""
                if img.mode == 'L':
                    img = img.convert('RGB')
                ratio = target_height / img.height
                new_width = int(img.width * ratio)
                return img.resize((new_width, target_height), Image.Resampling.NEAREST)

            # 이미지들 준비
            img1 = resize_for_display(original.convert('RGB'))
            img2 = resize_for_display(prev_resized.convert('RGB'))
            img3 = resize_for_display(person_mask)
            img4 = resize_for_display(full_mask)
            # 최종 마스크는 8배 확대
            final_enlarged = final_mask.resize(
                (final_mask.width * 8, final_mask.height * 8),
                Image.Resampling.NEAREST
            )
            img5 = resize_for_display(final_enlarged)

            # 전체 디버그 이미지 생성
            gap = 10
            total_width = img1.width + img2.width + img3.width + img4.width + img5.width + gap * 4
            debug_img = Image.new('RGB', (total_width, target_height + 30), (40, 40, 40))

            # 이미지 배치
            x = 0
            from PIL import ImageDraw

            draw = ImageDraw.Draw(debug_img)

            labels = [
                f"1.Original ({original.size[0]}x{original.size[1]})",
                f"2.Resized ({prev_resized.size[0]}x{prev_resized.size[1]})",
                f"3.YOLO Mask ({person_mask.size[0]}x{person_mask.size[1]})",
                f"4.Full Canvas ({full_mask.size[0]}x{full_mask.size[1]})",
                f"5.Final [{direction}]"
            ]
            images = [img1, img2, img3, img4, img5]

            for img, label in zip(images, labels):
                debug_img.paste(img, (x, 25))
                draw.text((x + 5, 5), label, fill=(255, 255, 255))
                x += img.width + gap

            print(f"[PersonMaskGenerator] 🔧 Debug: Showing mask generation process")
            debug_img.show()

        except Exception as e:
            print(f"[PersonMaskGenerator] Debug visualization error: {e}")
            import traceback
            traceback.print_exc()

    def is_available(self) -> bool:
        """모델 사용 가능 여부 확인"""
        return self.model is not None
