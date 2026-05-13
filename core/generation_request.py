# core/generation_request.py

"""
생성 요청 데이터 클래스

이미지 생성 큐에서 사용되는 요청 객체를 정의합니다.
각 요청은 고유 ID, 우선순위, 재시도 정책 등을 가집니다.

🆕 NAI 전용 데이터 클래스 추가 (2025-01-20):
- CharacterPosition: 캐릭터 위치 좌표
- NAICharacterData: Character Module 데이터
- NAIVibeTransferData: Vibe Transfer 데이터
- NAICharacterReferenceData: Character Reference 데이터
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
import uuid
import pandas as pd
from datetime import datetime

from core.nai_vibe_limits import MAX_NAI_VIBE_REFERENCES


# ============ NAI 데이터 클래스 ============

@dataclass(frozen=True)
class CharacterPosition:
    """
    캐릭터 위치 좌표 (NovelAI NAID4 centers 파라미터용)

    Attributes:
        x: X 좌표 (0.0 ~ 1.0, 왼쪽에서 오른쪽)
        y: Y 좌표 (0.0 ~ 1.0, 위에서 아래)

    Examples:
        >>> pos = CharacterPosition(x=0.1, y=0.1)  # A1 (좌상단)
        >>> pos = CharacterPosition(x=0.5, y=0.5)  # C3 (중앙)
        >>> pos = CharacterPosition(x=0.9, y=0.9)  # E5 (우하단)
    """
    x: float
    y: float

    def __post_init__(self):
        """유효성 검사"""
        if not (0.0 <= self.x <= 1.0):
            raise ValueError(f"x must be between 0.0 and 1.0, got {self.x}")
        if not (0.0 <= self.y <= 1.0):
            raise ValueError(f"y must be between 0.0 and 1.0, got {self.y}")

    def to_dict(self) -> Dict[str, float]:
        """API 형식으로 변환"""
        return {'x': self.x, 'y': self.y}

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> 'CharacterPosition':
        """딕셔너리에서 생성"""
        return cls(x=data['x'], y=data['y'])

    @classmethod
    def from_grid(cls, col: str, row: str) -> 'CharacterPosition':
        """그리드 위치에서 생성 (예: "A", "1" → CharacterPosition(0.1, 0.1))"""
        x_mapping = {'A': 0.1, 'B': 0.3, 'C': 0.5, 'D': 0.7, 'E': 0.9}
        y_mapping = {'1': 0.1, '2': 0.3, '3': 0.5, '4': 0.7, '5': 0.9}

        x = x_mapping.get(col.upper(), 0.5)
        y = y_mapping.get(row, 0.5)

        return cls(x=x, y=y)


@dataclass(frozen=True)
class NAICharacterData:
    """
    Character Module 데이터 (NAID4 캐릭터 프롬프트)

    Attributes:
        characters: 캐릭터별 프롬프트 리스트 (최대 5개)
        uc: 캐릭터별 Negative Prompt 리스트
        character_positions: 캐릭터별 위치 좌표 리스트

    Examples:
        >>> data = NAICharacterData(
        ...     characters=["1girl, blonde hair", "1boy, brown hair"],
        ...     uc=["bad hands", "bad anatomy"],
        ...     character_positions=[
        ...         CharacterPosition(x=0.1, y=0.1),
        ...         CharacterPosition(x=0.9, y=0.9)
        ...     ]
        ... )
    """
    characters: List[str]
    uc: List[str]
    character_positions: List[CharacterPosition] = field(default_factory=list)

    def __post_init__(self):
        """유효성 검사"""
        if not self.characters:
            raise ValueError("characters list cannot be empty")

        if len(self.characters) > 5:
            raise ValueError(f"Maximum 5 characters allowed, got {len(self.characters)}")

        if len(self.uc) != len(self.characters):
            raise ValueError(
                f"uc list length ({len(self.uc)}) must match characters list length ({len(self.characters)})"
            )

        if self.character_positions:
            if len(self.character_positions) != len(self.characters):
                raise ValueError(
                    f"character_positions length ({len(self.character_positions)}) "
                    f"must match characters length ({len(self.characters)})"
                )

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환 (직렬화용)"""
        return {
            'characters': self.characters,
            'uc': self.uc,
            'character_positions': [pos.to_dict() for pos in self.character_positions]
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NAICharacterData':
        """딕셔너리에서 생성 (역직렬화용)"""
        return cls(
            characters=data['characters'],
            uc=data['uc'],
            character_positions=[
                CharacterPosition.from_dict(pos)
                for pos in data.get('character_positions', [])
            ]
        )

    @classmethod
    def from_params(cls, params: Dict[str, Any]) -> Optional['NAICharacterData']:
        """
        params 딕셔너리에서 생성 (마이그레이션 헬퍼)

        Returns:
            NAICharacterData or None (데이터 없으면 None)
        """
        characters = params.get('characters')
        if not characters:
            return None

        uc = params.get('uc', [])

        # character_positions 변환
        positions = []
        raw_positions = params.get('character_positions', [])
        for pos in raw_positions:
            if isinstance(pos, dict):
                positions.append(CharacterPosition.from_dict(pos))
            elif isinstance(pos, CharacterPosition):
                positions.append(pos)

        return cls(
            characters=characters,
            uc=uc,
            character_positions=positions
        )


@dataclass(frozen=True)
class NAIVibeTransferData:
    """
    Vibe Transfer Module 데이터 (참조 이미지)

    Attributes:
        reference_image_multiple: 인코딩된 이미지 리스트 (base64)
        reference_strength_multiple: 이미지별 강도 리스트 (-1.0 ~ 1.0)
        normalize: NAI API에 전달할 강도 정규화 플래그
        reference_information_extracted_multiple: IE 값 리스트 (NAID3만)

    Examples:
        >>> data = NAIVibeTransferData(
        ...     reference_image_multiple=["base64_img1", "base64_img2"],
        ...     reference_strength_multiple=[0.6, 0.4],
        ...     normalize=True,
        ...     reference_information_extracted_multiple=[0, 1]
        ... )
    """
    reference_image_multiple: List[str]
    reference_strength_multiple: List[float]
    normalize: bool
    reference_information_extracted_multiple: List[float] = field(default_factory=list)

    def __post_init__(self):
        """유효성 검사"""
        if not self.reference_image_multiple:
            raise ValueError("reference_image_multiple cannot be empty")

        if len(self.reference_image_multiple) > MAX_NAI_VIBE_REFERENCES:
            raise ValueError(
                f"Maximum {MAX_NAI_VIBE_REFERENCES} reference images allowed, "
                f"got {len(self.reference_image_multiple)}"
            )

        if len(self.reference_strength_multiple) != len(self.reference_image_multiple):
            raise ValueError(
                f"reference_strength_multiple length ({len(self.reference_strength_multiple)}) "
                f"must match reference_image_multiple length ({len(self.reference_image_multiple)})"
            )

        for strength in self.reference_strength_multiple:
            if not (-1.0 <= strength <= 1.0):
                raise ValueError(f"Strength must be between -1.0 and 1.0, got {strength}")

        if self.reference_information_extracted_multiple:
            if len(self.reference_information_extracted_multiple) != len(self.reference_image_multiple):
                raise ValueError(
                    f"reference_information_extracted_multiple length "
                    f"must match reference_image_multiple length"
                )

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'reference_image_multiple': self.reference_image_multiple,
            'reference_strength_multiple': self.reference_strength_multiple,
            'normalize': self.normalize,
            'reference_information_extracted_multiple': self.reference_information_extracted_multiple
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NAIVibeTransferData':
        """딕셔너리에서 생성"""
        return cls(
            reference_image_multiple=data['reference_image_multiple'],
            reference_strength_multiple=data['reference_strength_multiple'],
            normalize=data['normalize'],
            reference_information_extracted_multiple=data.get('reference_information_extracted_multiple', [])
        )

    @classmethod
    def from_params(cls, params: Dict[str, Any]) -> Optional['NAIVibeTransferData']:
        """params 딕셔너리에서 생성 (마이그레이션 헬퍼)"""
        reference_image_multiple = params.get('reference_image_multiple')
        if not reference_image_multiple:
            return None

        return cls(
            reference_image_multiple=reference_image_multiple,
            reference_strength_multiple=params.get('reference_strength_multiple', []),
            normalize=params.get('normalize_reference_strength_multiple', False),
            reference_information_extracted_multiple=params.get('reference_information_extracted_multiple', [])
        )


@dataclass(frozen=True)
class NAICharacterReferenceData:
    """
    Character Reference Module 데이터 (Director Tool, NAID4.5)

    Attributes:
        director_reference_descriptions: Director 설명 리스트
        director_reference_images: 참조 이미지 리스트 (base64)
        director_reference_information_extracted: IE 값 리스트
        director_reference_secondary_strength_values: Fidelity 값 리스트
        director_reference_strength_values: 강도 값 리스트
        controlnet_strength: ControlNet 강도
        inpaint_img2img_strength: Inpaint Img2Img 강도
        normalize_reference_strength_multiple: 정규화 여부

    Examples:
        >>> data = NAICharacterReferenceData(
        ...     director_reference_descriptions=[{
        ...         "caption": {"base_caption": "character&style", "char_captions": []},
        ...         "legacy_uc": False
        ...     }],
        ...     director_reference_images=["base64_img"],
        ...     director_reference_information_extracted=[1],
        ...     director_reference_secondary_strength_values=[0.8],
        ...     director_reference_strength_values=[1],
        ...     controlnet_strength=1,
        ...     inpaint_img2img_strength=1,
        ...     normalize_reference_strength_multiple=True
        ... )
    """
    director_reference_descriptions: List[Dict[str, Any]]
    director_reference_images: List[str]
    director_reference_information_extracted: List[int]
    director_reference_secondary_strength_values: List[float]
    director_reference_strength_values: List[int]
    controlnet_strength: int
    inpaint_img2img_strength: int
    normalize_reference_strength_multiple: bool

    def __post_init__(self):
        """유효성 검사"""
        if not self.director_reference_images:
            raise ValueError("director_reference_images cannot be empty")

        # 모든 리스트 길이가 이미지 개수와 일치해야 함
        expected_length = len(self.director_reference_images)

        if len(self.director_reference_descriptions) != expected_length:
            raise ValueError(
                f"director_reference_descriptions length must match images length ({expected_length})"
            )

        if len(self.director_reference_information_extracted) != expected_length:
            raise ValueError(
                f"director_reference_information_extracted length must match images length ({expected_length})"
            )

        if len(self.director_reference_secondary_strength_values) != expected_length:
            raise ValueError(
                f"director_reference_secondary_strength_values length must match images length ({expected_length})"
            )

        if len(self.director_reference_strength_values) != expected_length:
            raise ValueError(
                f"director_reference_strength_values length must match images length ({expected_length})"
            )

        # Fidelity 값 유효성 검사 (0.0 ~ 1.0)
        for fidelity in self.director_reference_secondary_strength_values:
            if not (0.0 <= fidelity <= 1.0):
                raise ValueError(f"Fidelity must be between 0.0 and 1.0, got {fidelity}")

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'director_reference_descriptions': self.director_reference_descriptions,
            'director_reference_images': self.director_reference_images,
            'director_reference_information_extracted': self.director_reference_information_extracted,
            'director_reference_secondary_strength_values': self.director_reference_secondary_strength_values,
            'director_reference_strength_values': self.director_reference_strength_values,
            'controlnet_strength': self.controlnet_strength,
            'inpaint_img2img_strength': self.inpaint_img2img_strength,
            'normalize_reference_strength_multiple': self.normalize_reference_strength_multiple
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'NAICharacterReferenceData':
        """딕셔너리에서 생성"""
        return cls(
            director_reference_descriptions=data['director_reference_descriptions'],
            director_reference_images=data['director_reference_images'],
            director_reference_information_extracted=data['director_reference_information_extracted'],
            director_reference_secondary_strength_values=data['director_reference_secondary_strength_values'],
            director_reference_strength_values=data['director_reference_strength_values'],
            controlnet_strength=data['controlnet_strength'],
            inpaint_img2img_strength=data['inpaint_img2img_strength'],
            normalize_reference_strength_multiple=data['normalize_reference_strength_multiple']
        )

    @classmethod
    def from_params(cls, params: Dict[str, Any]) -> Optional['NAICharacterReferenceData']:
        """params 딕셔너리에서 생성 (마이그레이션 헬퍼)"""
        director_reference_descriptions = params.get('director_reference_descriptions')
        if not director_reference_descriptions:
            return None

        return cls(
            director_reference_descriptions=director_reference_descriptions,
            director_reference_images=params['director_reference_images'],
            director_reference_information_extracted=params['director_reference_information_extracted'],
            director_reference_secondary_strength_values=params['director_reference_secondary_strength_values'],
            director_reference_strength_values=params['director_reference_strength_values'],
            controlnet_strength=params.get('controlnet_strength', 1),
            inpaint_img2img_strength=params.get('inpaintImg2ImgStrength', 1),
            normalize_reference_strength_multiple=params.get('normalize_reference_strength_multiple', True)
        )


# ============ GenerationRequest ============

@dataclass
class GenerationRequest:
    """
    이미지 생성 요청 데이터 클래스

    Attributes:
        params: 생성 파라미터 딕셔너리 (일반 파라미터만)
        source_row: 원본 데이터 행 (pandas Series)

        # 🆕 NAI 전용 데이터 (선택적)
        nai_characters: Character Module 데이터
        nai_vibe_transfer: Vibe Transfer 데이터
        nai_character_reference: Character Reference 데이터

        request_id: 고유 요청 ID (자동 생성)
        priority: 우선순위 (높을수록 먼저 처리, 기본값: 0)
        status: 현재 상태 ("pending", "processing", "completed", "failed")
        max_retries: 최대 재시도 횟수 (기본값: 0)
        retry_count: 현재 재시도 횟수
        created_at: 요청 생성 시각
        started_at: 처리 시작 시각
        completed_at: 처리 완료 시각
        error_message: 실패 시 에러 메시지
    """

    # 필수 필드
    params: Dict[str, Any]
    source_row: pd.Series

    # 🆕 NAI 전용 데이터 (선택적)
    nai_characters: Optional[NAICharacterData] = None
    nai_vibe_transfer: Optional[NAIVibeTransferData] = None
    nai_character_reference: Optional[NAICharacterReferenceData] = None

    # 자동 생성 필드
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)

    # 우선순위 및 상태
    priority: int = 0  # 0 = 일반, 100 = 긴급
    status: str = "pending"  # pending, processing, completed, failed

    # 재시도 정책
    max_retries: int = 0
    retry_count: int = 0

    # 시간 추적
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # 에러 추적
    error_message: Optional[str] = None

    def mark_processing(self):
        """처리 시작 상태로 변경"""
        self.status = "processing"
        self.started_at = datetime.now()

    def mark_completed(self):
        """완료 상태로 변경"""
        self.status = "completed"
        self.completed_at = datetime.now()

    def mark_failed(self, error: str):
        """실패 상태로 변경"""
        self.status = "failed"
        self.error_message = error
        self.completed_at = datetime.now()

    def can_retry(self) -> bool:
        """재시도 가능 여부 확인"""
        return self.retry_count < self.max_retries

    def increment_retry(self):
        """재시도 카운트 증가"""
        self.retry_count += 1
        self.status = "pending"  # 다시 대기 상태로

    def get_elapsed_time(self) -> Optional[float]:
        """경과 시간 계산 (초 단위)"""
        if self.started_at:
            end_time = self.completed_at or datetime.now()
            return (end_time - self.started_at).total_seconds()
        return None

    def get_wait_time(self) -> float:
        """대기 시간 계산 (초 단위)"""
        if self.started_at:
            return (self.started_at - self.created_at).total_seconds()
        return (datetime.now() - self.created_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환 (로깅/디버깅용)"""
        result = {
            'request_id': self.request_id,
            'priority': self.priority,
            'status': self.status,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'error_message': self.error_message,
            'elapsed_time': self.get_elapsed_time(),
            'wait_time': self.get_wait_time()
        }

        # 🆕 NAI 데이터 포함
        if self.nai_characters:
            result['nai_characters'] = self.nai_characters.to_dict()
        if self.nai_vibe_transfer:
            result['nai_vibe_transfer'] = self.nai_vibe_transfer.to_dict()
        if self.nai_character_reference:
            result['nai_character_reference'] = self.nai_character_reference.to_dict()

        return result

    def __repr__(self):
        """문자열 표현"""
        nai_flags = []
        if self.nai_characters:
            nai_flags.append(f"chars={len(self.nai_characters.characters)}")
        if self.nai_vibe_transfer:
            nai_flags.append(f"vibes={len(self.nai_vibe_transfer.reference_image_multiple)}")
        if self.nai_character_reference:
            nai_flags.append("char_ref")

        nai_str = f", NAI: {', '.join(nai_flags)}" if nai_flags else ""

        return (f"GenerationRequest(id={self.request_id[:8]}..., "
                f"priority={self.priority}, status={self.status}, "
                f"retry={self.retry_count}/{self.max_retries}{nai_str})")
