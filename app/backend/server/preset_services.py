from __future__ import annotations

from typing import Any

from core.clothes_preset_service import ClothesPresetService
from core.event_preset_download_service import EventPresetDownloadService
from core.event_preset_service import EventPresetService
from core.expression_preset_service import ExpressionPresetService
from core.preset_composer_service import PresetComposerService
from core.web_session_context import WebSessionContext


def event_preset_service(context: WebSessionContext) -> EventPresetService:
    service = getattr(context, "event_preset_service", None)
    if service is None:
        data_root = None
        thumbnail_root = None
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is not None:
            data_root = runtime_paths.data_dir
            thumbnail_root = runtime_paths.ui_assets_dir
        service = EventPresetService(
            context.repo_root,
            data_root=data_root,
            thumbnail_root=thumbnail_root,
        )
        context.event_preset_service = service
    return service


def clothes_preset_service(context: WebSessionContext) -> ClothesPresetService:
    service = getattr(context, "clothes_preset_service", None)
    if service is None:
        service = ClothesPresetService(context.repo_root)
        context.clothes_preset_service = service
    return service


def expression_preset_service(context: WebSessionContext) -> ExpressionPresetService:
    service = getattr(context, "expression_preset_service", None)
    if service is None:
        service = ExpressionPresetService(context.repo_root)
        context.expression_preset_service = service
    return service


def preset_composer_service(context: WebSessionContext) -> PresetComposerService:
    service = getattr(context, "preset_composer_service", None)
    if service is None:
        service = PresetComposerService(
            event_preset_service(context),
            axis_providers={"clothes": clothes_preset_service(context)},
        )
        context.preset_composer_service = service
    return service


def event_preset_download_service(context: WebSessionContext) -> EventPresetDownloadService:
    service = getattr(context, "event_preset_download_service", None)
    if service is None:
        def refresh_services() -> None:
            data_root = None
            thumbnail_root = None
            runtime_paths = getattr(context, "runtime_paths", None)
            if runtime_paths is not None:
                data_root = runtime_paths.data_dir
                thumbnail_root = runtime_paths.ui_assets_dir
            context.event_preset_service = EventPresetService(
                context.repo_root,
                data_root=data_root,
                thumbnail_root=thumbnail_root,
            )
            context.preset_composer_service = PresetComposerService(
                context.event_preset_service,
                axis_providers={"clothes": clothes_preset_service(context)},
            )

        data_root = None
        thumbnail_root = None
        runtime_paths = getattr(context, "runtime_paths", None)
        if runtime_paths is not None:
            data_root = runtime_paths.data_dir
            thumbnail_root = runtime_paths.ui_assets_dir
        service = EventPresetDownloadService(
            context.repo_root,
            status_provider=lambda: event_preset_service(context).status(),
            on_complete=refresh_services,
            data_root=data_root,
            thumbnail_root=thumbnail_root,
        )
        context.event_preset_download_service = service
    return service


def event_preset_status(context: WebSessionContext) -> dict[str, Any]:
    status = event_preset_service(context).status()
    status["download"] = event_preset_download_service(context).snapshot()
    return status
