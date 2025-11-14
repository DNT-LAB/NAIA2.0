# core/generation_request.py

"""
생성 요청 데이터 클래스

이미지 생성 큐에서 사용되는 요청 객체를 정의합니다.
각 요청은 고유 ID, 우선순위, 재시도 정책 등을 가집니다.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import uuid
import pandas as pd
from datetime import datetime


@dataclass
class GenerationRequest:
    """
    이미지 생성 요청 데이터 클래스

    Attributes:
        params: 생성 파라미터 딕셔너리 (프롬프트, 설정 등)
        source_row: 원본 데이터 행 (pandas Series)
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
        return {
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

    def __repr__(self):
        """문자열 표현"""
        return (f"GenerationRequest(id={self.request_id[:8]}..., "
                f"priority={self.priority}, status={self.status}, "
                f"retry={self.retry_count}/{self.max_retries})")
