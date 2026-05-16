import sys
from types import ModuleType, SimpleNamespace

import pandas as pd

_piexif = ModuleType("piexif")
_piexif_helper = ModuleType("piexif.helper")
_piexif.helper = _piexif_helper
sys.modules.setdefault("piexif", _piexif)
sys.modules.setdefault("piexif.helper", _piexif_helper)

import core.generation_controller as generation_controller_module
from core.generation_controller import GenerationController


class _Thread:
    def __init__(self, running=False):
        self.running = running
        self.wait_called = False
        self.terminate_called = False
        self.deleted = False

    def isRunning(self):
        return self.running

    def wait(self, *_args):
        self.wait_called = True
        raise AssertionError("normal generation start must not block on stale thread wait")

    def terminate(self):
        self.terminate_called = True
        raise AssertionError("normal generation start must not terminate stale thread")

    def deleteLater(self):
        self.deleted = True


class _Worker:
    _is_running = False

    def __init__(self):
        self.deleted = False

    def deleteLater(self):
        self.deleted = True


class _QueueManager:
    def __init__(self):
        self.requests = []

    def enqueue_request(self, request):
        self.requests.append(request)
        return "queued-request"

    def enqueue_with_priority(self, request):
        self.requests.append(request)
        return "priority-request"

    def get_queue_size(self):
        return len(self.requests)

    def is_empty(self):
        return not self.requests

    def is_paused(self):
        return False

    def peek_next_request(self):
        return self.requests[0] if self.requests else None


class _CheckBox:
    def __init__(self, checked):
        self.checked = checked

    def isChecked(self):
        return self.checked


def test_start_threaded_generation_queues_when_previous_thread_is_still_running():
    queue = _QueueManager()
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(generation_queue_manager=queue)
    controller.generation_thread = _Thread(running=True)
    controller.generation_worker = _Worker()
    controller.is_generating = False
    controller._thread_cleanup_in_progress = False
    controller._pending_thread_refs = []
    controller._update_button_with_queue_size = lambda: None

    params = {"api_mode": "WEBUI", "input": "1girl"}
    source_row = pd.Series({"general": "1girl"})

    controller._start_threaded_generation(params, source_row)

    assert controller.is_generating is True
    assert len(queue.requests) == 1
    assert queue.requests[0].params is params
    assert queue.requests[0].source_row is source_row
    assert controller.generation_thread.wait_called is False
    assert controller.generation_thread.terminate_called is False


def test_prepared_queue_request_keeps_nai_early_binding():
    queue = _QueueManager()
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(generation_queue_manager=queue)
    controller._update_button_with_queue_size = lambda: None

    sentinels = (object(), object(), object())
    controller._extract_nai_data = lambda params: sentinels

    params = {"api_mode": "NAI", "input": "1girl", "characters": ["alice"]}
    source_row = pd.Series({"general": "1girl"})

    controller._enqueue_prepared_request(params, source_row)

    assert len(queue.requests) == 1
    request = queue.requests[0]
    assert request.nai_characters is sentinels[0]
    assert request.nai_vibe_transfer is sentinels[1]
    assert request.nai_character_reference is sentinels[2]


def test_fast_webui_enqueue_is_cancelled_if_current_mode_is_nai():
    queue = _QueueManager()
    messages = []
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        generation_queue_manager=queue,
        main_window=SimpleNamespace(
            status_bar=SimpleNamespace(showMessage=lambda message: messages.append(message)),
        ),
    )
    controller._collect_generation_params = lambda: {"api_mode": "NAI", "credential": "nai-token"}

    controller._enqueue_current_request({"_webui_fast_auto_gen": True}, priority=0)

    assert queue.requests == []
    assert messages == [
        "⚡ WEBUI Fast Auto Gen: 현재 모드가 WEBUI가 아니어서 큐 요청을 취소했습니다."
    ]


def test_thread_finished_resumes_pending_auto_generation(monkeypatch):
    auto_calls = []
    timer_calls = []
    monkeypatch.setattr(
        generation_controller_module.QTimer,
        "singleShot",
        lambda ms, fn: (timer_calls.append(ms), fn())[1],
    )
    monkeypatch.setattr(
        generation_controller_module,
        "_force_cleanup_all_threads",
        lambda **_kwargs: None,
    )

    thread = _Thread(running=False)
    worker = _Worker()
    main_window = SimpleNamespace(
        _auto_generation_waiting_for_thread=True,
        generation_checkboxes={"자동 생성": _CheckBox(True)},
        _check_and_trigger_auto_generation=lambda: auto_calls.append("auto"),
    )
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        main_window=main_window,
        generation_queue_manager=_QueueManager(),
        publish=lambda *_args: None,
        session_p_eng_override=None,
        session_cond_override=None,
        temp_window_mode=False,
    )
    controller.generation_thread = thread
    controller.generation_worker = worker
    controller.is_generating = True
    controller.queue_hold_auto_gen = False
    controller.auto_retry_pending = False
    controller._pending_thread_refs = []
    controller._update_button_with_queue_size = lambda: None

    controller._on_thread_finished(thread, worker)

    assert controller.is_generating is False
    assert main_window._auto_generation_waiting_for_thread is False
    assert auto_calls == ["auto"]
    assert 0 in timer_calls


def test_generation_finished_prearms_normal_autogen_before_ui_when_fast_mode_enabled(monkeypatch):
    scheduled = []
    events = []

    monkeypatch.setattr(
        generation_controller_module.QTimer,
        "singleShot",
        lambda ms, fn: scheduled.append((ms, fn)),
    )

    queue = _QueueManager()
    main_window = SimpleNamespace(
        _auto_generation_waiting_for_thread=False,
        generation_checkboxes={"자동 생성": _CheckBox(True)},
        is_webui_fast_auto_gen_enabled=lambda *_args: True,
        automation_module=SimpleNamespace(
            automation_controller=SimpleNamespace(is_running=False)
        ),
        update_ui_with_result=lambda result: events.append(("ui", result)),
    )

    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        main_window=main_window,
        generation_queue_manager=queue,
        publish=lambda name, payload: events.append((name, payload)),
        session_p_eng_override=None,
        session_cond_override=None,
    )
    controller.current_generation_params = None
    controller.auto_retry_count = 1
    controller._update_button_with_queue_size = lambda: None

    result = {"image": object(), "generation_params": {"api_mode": "WEBUI"}}

    controller._on_generation_finished(result)

    assert main_window._auto_generation_waiting_for_thread is True
    assert result["_skip_update_ui_auto_generate_check"] is True
    assert ("generation_finished", result) in events
    assert not [event for event in events if event[0] == "ui"]
    assert scheduled and scheduled[0][0] == 50

    scheduled[0][1]()

    assert ("ui", result) in events


def test_generation_finished_does_not_prearm_normal_autogen_when_fast_mode_disabled(monkeypatch):
    scheduled = []
    events = []

    monkeypatch.setattr(
        generation_controller_module.QTimer,
        "singleShot",
        lambda ms, fn: scheduled.append((ms, fn)),
    )

    queue = _QueueManager()
    main_window = SimpleNamespace(
        _auto_generation_waiting_for_thread=False,
        generation_checkboxes={"자동 생성": _CheckBox(True)},
        is_webui_fast_auto_gen_enabled=lambda *_args: False,
        automation_module=SimpleNamespace(
            automation_controller=SimpleNamespace(is_running=False)
        ),
        update_ui_with_result=lambda result: events.append(("ui", result)),
    )

    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        main_window=main_window,
        generation_queue_manager=queue,
        publish=lambda name, payload: events.append((name, payload)),
        session_p_eng_override=None,
        session_cond_override=None,
    )
    controller.current_generation_params = None
    controller.auto_retry_count = 1
    controller._update_button_with_queue_size = lambda: None

    result = {"image": object(), "generation_params": {"api_mode": "WEBUI"}}

    controller._on_generation_finished(result)

    assert main_window._auto_generation_waiting_for_thread is False
    assert "_skip_update_ui_auto_generate_check" not in result
    assert ("ui", result) in events
    assert not scheduled


def test_generation_finished_defers_ui_for_webui_fast_auto_gen_queue(monkeypatch):
    scheduled = []
    events = []

    monkeypatch.setattr(
        generation_controller_module.QTimer,
        "singleShot",
        lambda ms, fn: scheduled.append((ms, fn)),
    )

    queue = _QueueManager()
    queue.requests.append(SimpleNamespace(params={"api_mode": "WEBUI", "_webui_fast_auto_gen": True}))
    main_window = SimpleNamespace(
        _auto_generation_waiting_for_thread=False,
        generation_checkboxes={"자동 생성": _CheckBox(True)},
        is_webui_fast_auto_gen_enabled=lambda *_args: True,
        automation_module=SimpleNamespace(
            automation_controller=SimpleNamespace(is_running=False)
        ),
        update_ui_with_result=lambda result: events.append(("ui", result)),
    )

    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        main_window=main_window,
        generation_queue_manager=queue,
        publish=lambda name, payload: events.append((name, payload)),
        session_p_eng_override=None,
        session_cond_override=None,
    )
    controller.current_generation_params = None
    controller.auto_retry_count = 1
    controller._update_button_with_queue_size = lambda: None

    result = {"image": object(), "generation_params": {"api_mode": "WEBUI"}}

    controller._on_generation_finished(result)

    assert result["_skip_update_ui_auto_generate_check"] is True
    assert ("generation_finished", result) in events
    assert not [event for event in events if event[0] == "ui"]
    assert scheduled and scheduled[0][0] == 50

    scheduled[0][1]()

    assert ("ui", result) in events


def test_generation_finished_keeps_nai_on_legacy_auto_gen_path(monkeypatch):
    scheduled = []
    events = []

    monkeypatch.setattr(
        generation_controller_module.QTimer,
        "singleShot",
        lambda ms, fn: scheduled.append((ms, fn)),
    )

    queue = _QueueManager()
    queue.requests.append(SimpleNamespace(params={"api_mode": "WEBUI", "_webui_fast_auto_gen": True}))
    main_window = SimpleNamespace(
        _auto_generation_waiting_for_thread=False,
        generation_checkboxes={"자동 생성": _CheckBox(True)},
        is_webui_fast_auto_gen_enabled=lambda *_args: True,
        automation_module=SimpleNamespace(
            automation_controller=SimpleNamespace(is_running=False)
        ),
        update_ui_with_result=lambda result: events.append(("ui", result)),
    )

    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        main_window=main_window,
        generation_queue_manager=queue,
        publish=lambda name, payload: events.append((name, payload)),
        session_p_eng_override=None,
        session_cond_override=None,
    )
    controller.current_generation_params = {"api_mode": "NAI"}
    controller.auto_retry_count = 1
    controller._update_button_with_queue_size = lambda: None

    result = {"image": object(), "generation_params": {"api_mode": "NAI"}}

    controller._on_generation_finished(result)

    assert "_skip_update_ui_auto_generate_check" not in result
    assert main_window._auto_generation_waiting_for_thread is False
    assert ("ui", result) in events
    assert not scheduled


def test_generation_started_prepares_fast_mode_only_for_webui_request():
    calls = []
    events = []

    main_window = SimpleNamespace(
        status_bar=SimpleNamespace(showMessage=lambda *_args: None),
        prepare_fast_webui_auto_generation=lambda api_mode=None: calls.append(api_mode),
    )
    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        main_window=main_window,
        publish=lambda name, payload: events.append((name, payload)),
        generation_queue_manager=_QueueManager(),
    )
    controller.current_generation_params = {"api_mode": "NAI"}
    controller._update_button_with_queue_size = lambda: None

    controller._on_generation_started()

    assert calls == []

    controller.current_generation_params = {"api_mode": "WEBUI"}
    controller._on_generation_started()

    assert calls == ["WEBUI"]


def test_stale_thread_finished_signal_does_not_clear_current_generation(monkeypatch):
    calls = []
    monkeypatch.setattr(generation_controller_module.QTimer, "singleShot", lambda _ms, fn: fn())
    monkeypatch.setattr(
        generation_controller_module,
        "_force_cleanup_all_threads",
        lambda **kwargs: calls.append(kwargs),
    )

    current_thread = _Thread(running=True)
    current_worker = _Worker()
    stale_thread = _Thread(running=False)
    stale_worker = _Worker()

    controller = GenerationController.__new__(GenerationController)
    controller.context = SimpleNamespace(
        publish=lambda *_args: (_ for _ in ()).throw(AssertionError("stale finish must not publish")),
        generation_queue_manager=SimpleNamespace(),
    )
    controller.generation_thread = current_thread
    controller.generation_worker = current_worker
    controller.is_generating = True
    controller._pending_thread_refs = []

    controller._on_thread_finished(stale_thread, stale_worker)

    assert controller.generation_thread is current_thread
    assert controller.generation_worker is current_worker
    assert controller.is_generating is True
    assert stale_thread.deleted is True
    assert stale_worker.deleted is True
    assert calls == [{"wait_ms": 0, "process_events_passes": 0}]
