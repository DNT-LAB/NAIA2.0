# core/generation_queue_manager.py

"""
생성 큐 관리자

이미지 생성 요청들을 큐로 관리하고, 우선순위에 따라 처리 순서를 결정합니다.
스레드 안전성을 보장하며, 일시정지/재개/비우기 기능을 제공합니다.
"""

from collections import deque
from threading import Lock
from typing import Optional, List, Deque
from core.generation_request import GenerationRequest


class GenerationQueueManager:
    """
    생성 큐 관리자

    특징:
    - 스레드 안전: Lock을 사용한 동기화
    - 우선순위 지원: 긴급 요청은 큐 앞쪽에 삽입
    - 일시정지/재개: 큐 처리를 일시적으로 중단 가능
    - 이벤트 발행: AppContext를 통해 큐 상태 변경 알림
    """

    def __init__(self, app_context):
        """
        Args:
            app_context: AppContext 인스턴스 (이벤트 발행용)
        """
        self.app_context = app_context
        self._queue: Deque[GenerationRequest] = deque()
        self._queue_lock = Lock()
        self._is_paused = False

    def enqueue_request(self, request: GenerationRequest) -> str:
        """
        일반 요청을 큐 끝에 추가

        Args:
            request: GenerationRequest 객체

        Returns:
            request_id: 추가된 요청의 고유 ID
        """
        with self._queue_lock:
            self._queue.append(request)
            request_id = request.request_id

            # 큐 크기 계산
            queue_size = len(self._queue)

        # 이벤트 발행 (Lock 외부에서)
        self._publish_queue_event("request_enqueued", {
            "request_id": request_id,
            "priority": request.priority,
            "queue_size": queue_size,
            "position": "back"
        })

        print(f"[QUEUE] 요청 추가: {request_id[:8]}... (큐 크기: {queue_size})")
        return request_id

    def enqueue_with_priority(self, request: GenerationRequest) -> str:
        """
        우선순위 요청을 큐에 추가 (우선순위에 따라 위치 결정)

        높은 우선순위 요청은 큐 앞쪽에, 같은 우선순위는 순서대로 삽입됩니다.

        Args:
            request: GenerationRequest 객체

        Returns:
            request_id: 추가된 요청의 고유 ID
        """
        with self._queue_lock:
            if request.priority > 0:
                # 우선순위가 높은 요청: 큐 앞쪽에서 적절한 위치 찾기
                inserted = False
                for i, queued_request in enumerate(self._queue):
                    if request.priority > queued_request.priority:
                        self._queue.insert(i, request)
                        inserted = True
                        position = i
                        break

                if not inserted:
                    # 모든 요청보다 우선순위가 낮거나 같음 → 끝에 추가
                    self._queue.append(request)
                    position = len(self._queue) - 1
            else:
                # 일반 요청 (priority == 0): 끝에 추가
                self._queue.append(request)
                position = len(self._queue) - 1

            request_id = request.request_id
            queue_size = len(self._queue)

        # 이벤트 발행
        self._publish_queue_event("request_enqueued", {
            "request_id": request_id,
            "priority": request.priority,
            "queue_size": queue_size,
            "position": position
        })

        priority_text = "긴급" if request.priority > 0 else "일반"
        print(f"[QUEUE] {priority_text} 요청 추가: {request_id[:8]}... "
              f"(위치: {position}, 큐 크기: {queue_size})")
        return request_id

    def dequeue_request(self) -> Optional[GenerationRequest]:
        """
        큐에서 다음 요청을 가져옴

        일시정지 상태이거나 큐가 비어있으면 None 반환

        Returns:
            GenerationRequest 또는 None
        """
        with self._queue_lock:
            if self._is_paused:
                print("[QUEUE] 일시정지 상태: 요청을 가져올 수 없습니다")
                return None

            if not self._queue:
                return None

            request = self._queue.popleft()
            queue_size = len(self._queue)

        # 이벤트 발행
        self._publish_queue_event("request_dequeued", {
            "request_id": request.request_id,
            "priority": request.priority,
            "queue_size": queue_size
        })

        print(f"[QUEUE] 요청 가져옴: {request.request_id[:8]}... (남은 큐: {queue_size})")
        return request

    def pause_queue(self):
        """큐 일시정지"""
        with self._queue_lock:
            queue_size = len(self._queue)
            if not self._is_paused:
                self._is_paused = True
                should_publish = True
            else:
                should_publish = False

        if should_publish:
            self._publish_queue_event("queue_paused", {
                "queue_size": queue_size
            })

        print(f"[QUEUE] ⏸️ 큐 일시정지 (대기 중: {queue_size})")

    def resume_queue(self):
        """큐 재개"""
        with self._queue_lock:
            queue_size = len(self._queue)
            if self._is_paused:
                self._is_paused = False
                should_publish = True
            else:
                should_publish = False

        if should_publish:
            self._publish_queue_event("queue_resumed", {
                "queue_size": queue_size
            })

        print(f"[QUEUE] ▶️ 큐 재개 (대기 중: {queue_size})")

    def clear_queue(self):
        """큐 비우기 (모든 대기 중인 요청 제거)"""
        with self._queue_lock:
            cleared_count = len(self._queue)
            self._queue.clear()

        self._publish_queue_event("queue_cleared", {
            "cleared_count": cleared_count
        })

        print(f"[QUEUE] 🗑️ 큐 비우기 완료: {cleared_count}개 요청 제거됨")

    def get_queue_size(self) -> int:
        """현재 큐 크기 반환"""
        with self._queue_lock:
            return len(self._queue)

    def is_paused(self) -> bool:
        """일시정지 상태 확인"""
        with self._queue_lock:
            return self._is_paused

    def is_empty(self) -> bool:
        """큐가 비어있는지 확인"""
        with self._queue_lock:
            return len(self._queue) == 0

    def peek_next_request(self) -> Optional[GenerationRequest]:
        """
        다음 요청을 미리 확인 (큐에서 제거하지 않음)

        Returns:
            GenerationRequest 또는 None
        """
        with self._queue_lock:
            if self._queue:
                return self._queue[0]
            return None

    def get_all_requests(self) -> List[GenerationRequest]:
        """
        모든 대기 중인 요청 목록 반환 (복사본)

        Returns:
            List[GenerationRequest]
        """
        with self._queue_lock:
            return list(self._queue)

    def remove_request(self, request_id: str) -> bool:
        """
        특정 요청을 큐에서 제거

        Args:
            request_id: 제거할 요청의 ID

        Returns:
            성공 여부 (True/False)
        """
        removed = False
        queue_size = 0

        with self._queue_lock:
            for i, request in enumerate(self._queue):
                if request.request_id == request_id:
                    del self._queue[i]
                    queue_size = len(self._queue)
                    removed = True
                    break

        if not removed:
            return False

        self._publish_queue_event("request_removed", {
            "request_id": request_id,
            "queue_size": queue_size
        })

        print(f"[QUEUE] 요청 제거: {request_id[:8]}... (남은 큐: {queue_size})")
        return True

    def get_queue_stats(self) -> dict:
        """
        큐 통계 정보 반환

        Returns:
            dict: 큐 크기, 일시정지 상태, 우선순위별 개수 등
        """
        with self._queue_lock:
            total = len(self._queue)
            priority_counts = {}

            for request in self._queue:
                priority = request.priority
                priority_counts[priority] = priority_counts.get(priority, 0) + 1

            return {
                "total": total,
                "is_paused": self._is_paused,
                "priority_counts": priority_counts,
                "has_urgent": any(r.priority > 0 for r in self._queue)
            }

    def _publish_queue_event(self, event_name: str, data: dict):
        """
        큐 이벤트 발행 (AppContext를 통해)

        Args:
            event_name: 이벤트 이름
            data: 이벤트 데이터
        """
        if self.app_context:
            try:
                self.app_context.publish(f"queue_{event_name}", data)
            except Exception as e:
                print(f"[QUEUE] 이벤트 발행 실패: {e}")

    def __repr__(self):
        """문자열 표현"""
        stats = self.get_queue_stats()
        return (f"GenerationQueueManager(size={stats['total']}, "
                f"paused={stats['is_paused']}, "
                f"urgent={stats['has_urgent']})")
