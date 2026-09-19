"""Process-local reference mode. Never persist this policy or substitute credentials."""
from contextlib import contextmanager
from functools import wraps
import threading


class GenerationBlocked(RuntimeError):
    """A local policy refusal, never a retryable provider error."""


class GenerationAccessPolicy:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = "normal"
        self.revision = 0
        self.active_operations = 0
        self.saved_mode = None

    @property
    def blocked(self):
        return self.state != "normal"

    def reason(self):
        if self.state == "reference":
            return "NO API 모드에서는 이미지를 생성할 수 없습니다. API 설정에서 연결해 주세요."
        if self.state == "setup":
            return "API 설정 중입니다. NO API 모드를 선택하거나 API 연결을 확인해 주세요."
        return ""

    @contextmanager
    def operation(self, revision=None):
        with self.lock:
            if self.blocked:
                raise GenerationBlocked(self.reason())
            if revision is not None and revision != self.revision:
                raise GenerationBlocked("API 사용 상태가 변경되어 이전 생성 요청을 취소했습니다.")
            self.active_operations += 1
        try:
            yield
        finally:
            with self.lock:
                self.active_operations -= 1

    def enter_reference(self, context):
        with self.lock:
            queue = getattr(context, "generation_queue_manager", None)
            if (self.active_operations or getattr(context, "is_generating", False)
                    or (queue is not None and queue.get_queue_size())):
                raise GenerationBlocked("진행 중이거나 대기 중인 생성 작업을 중단한 뒤 NO API 모드를 선택해 주세요.")
            # Avoid taking a reference-mode snapshot in the middle of a continuous run.
            for accessor in ("_automation_service", "_storyteller_service",
                             "_sequence_run_service", "_inpaint_sequence_run_service"):
                getter = getattr(context, accessor, None)
                if callable(getter) and getter().is_running():
                    raise GenerationBlocked("연속 생성 작업을 중단한 뒤 NO API 모드를 선택해 주세요.")
            if self.saved_mode is None:
                self.saved_mode = context.get_api_mode()
            self.state = "reference"
            self.revision += 1
            context.set_api_mode("NAI")

    def open_setup(self):
        with self.lock:
            if self.state == "reference":
                self.state = "setup"
                self.revision += 1

    def connected(self, context, mode, revision):
        with self.lock:
            if revision != self.revision:
                return False
            self.state = "normal"
            self.saved_mode = None
            self.revision += 1
            context.set_api_mode(mode)
            context.save_remote_ui_state()
            return True

    def payload(self):
        with self.lock:
            return {"no_api_mode": self.state == "reference",
                    "api_setup_pending": self.state == "setup",
                    "api_access_revision": self.revision}


_creation_lock = threading.Lock()


def access_policy(context):
    # Lazy creation also supports the small service contexts used by plugins/tests.
    with _creation_lock:
        policy = getattr(context, "generation_access_policy", None)
        if policy is None:
            policy = GenerationAccessPolicy()
            context.generation_access_policy = policy
        return policy


def generation_operation(function):
    """Protect the entire synchronous operation, including provider retry loops."""
    @wraps(function)
    def guarded(owner, *args, **kwargs):
        context = getattr(owner, "app_context", None) or getattr(owner, "context", None) or owner
        with access_policy(context).operation():
            return function(owner, *args, **kwargs)
    return guarded


def generation_dispatch(function):
    @wraps(function)
    def guarded(service, command=None, **kwargs):
        try:
            with access_policy(service.context).operation():
                return function(service, command, **kwargs)
        except GenerationBlocked as exc:
            from core.headless_generation_service import HeadlessGenerationDispatch
            normalized_command = command if isinstance(command, dict) else {}
            return HeadlessGenerationDispatch(None, service._normalize_mode(normalized_command), str(exc))
    return guarded
