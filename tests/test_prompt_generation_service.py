import inspect
from types import SimpleNamespace

import core.prompt_generation_service as prompt_generation_service
from core.prompt_generation_service import PromptGenerationService


def test_prompt_generation_service_has_no_pyqt_dependency():
    assert "PyQt6" not in inspect.getsource(prompt_generation_service)


def test_silent_generation_restores_app_context():
    saved_source = object()
    saved_context = SimpleNamespace(
        sequential_counters={"pose": 2},
        wildcard_state={"pose": {"index": 1}},
    )
    app_context = SimpleNamespace(
        current_source_row=saved_source,
        current_prompt_context=saved_context,
        event_stream_runtime=None,
    )
    service = PromptGenerationService(app_context)

    def process():
        app_context.current_prompt_context.final_prompt = "tag prompt"
        return app_context.current_prompt_context

    service.processor = SimpleNamespace(process=process)

    prompt = service.generate_instant_source_silent({"general": ["tag", "prompt"]}, {})

    assert prompt == "tag prompt"
    assert app_context.current_source_row is saved_source
    assert app_context.current_prompt_context is saved_context


def test_build_result_reports_auto_fit_reset_without_qt():
    app_context = SimpleNamespace(current_source_row=None, current_prompt_context=None, event_stream_runtime=None)
    service = PromptGenerationService(app_context)
    context = SimpleNamespace(
        final_prompt="tag prompt",
        settings={"auto_fit_resolution": True},
        metadata={},
    )

    result = service.build_result(context)

    assert result.final_prompt == "tag prompt"
    assert result.detected_resolution is None
    assert result.reset_resolution_detected is True
