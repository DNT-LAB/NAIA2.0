"""Server-owned Remote Web mode, options, and parameter state."""

from __future__ import annotations

from typing import Any

from core.nai_model_contract import resolve_nai_model_for_context


SUPPORTED_API_MODES = ("NAI", "WEBUI", "COMFYUI")
# Mode-agnostic params that must survive a per-mode plane swap (e.g. the web
# session port is a process-level value, not a per-mode generation parameter).
RUNTIME_REMOTE_PARAM_KEYS = frozenset({"web_session_port"})
REMOTE_OPTION_DEFAULTS = {
    "prompt_fixed": False,
    "auto_generate": False,
    "wildcard_standalone": False,
    "auto_save": True,
    "nai_streaming_preview": False,
}
REMOTE_BOOLEAN_PARAMS = {
    "seed_fixed",
    "random_resolution",
    "auto_fit_resolution",
    "enable_hr",
    "resolution_preset_enabled",
    "webui_hiresfix_assist",
    "webui_hiresfix_assist_enabled",
    "webui_custom_payload_enabled",
    "SMEA",
    "DYN",
    "VAR+",
    "DECRISP",
}
REMOTE_INT_PARAMS = {
    "steps",
    "hires_steps",
    "width",
    "height",
    "webui_hiresfix_assist_target",
}
REMOTE_FLOAT_PARAMS = {
    "cfg_scale",
    "cfg_rescale",
    "hr_scale",
    "denoising_strength",
    "hr_cfg",
    "rescale_cfg",
}


class HeadlessRemoteStateService:
    def __init__(self, context: Any):
        self.context = context

    def get_api_mode(self) -> str:
        return self.context.current_api_mode

    def set_api_mode(self, mode: str) -> None:
        normalized = str(mode or "").strip().upper()
        if normalized not in SUPPORTED_API_MODES:
            return
        if normalized == self.context.current_api_mode:
            return
        old_mode = self.context.current_api_mode
        # Per-mode parameter planes: stash the outgoing mode's params and swap in
        # the target mode's plane so mode-specific values (sampler/scheduler/steps/
        # sampling_mode/comfyui_* …) never leak across modes. Leaking COMFYUI's
        # sampler/scheduler into a NAI generation produced a NAI 500.
        self._stash_active_param_plane(old_mode)
        # Same per-mode treatment for the main/negative prompt so each mode keeps
        # its own prompt (a NAI random prompt must not appear while in COMFYUI).
        self._stash_active_prompt_plane(old_mode)
        self.context.current_api_mode = normalized
        self._activate_param_plane(normalized)
        self._activate_prompt_plane(normalized)
        self.context.save_remote_ui_state()
        self.context.publish("api_mode_changed", {"old_mode": old_mode, "new_mode": normalized})

    def _param_planes(self) -> dict[str, dict[str, Any]]:
        planes = getattr(self.context, "remote_param_planes", None)
        if not isinstance(planes, dict):
            planes = {}
            self.context.remote_param_planes = planes
        return planes

    def _stash_active_param_plane(self, mode: str) -> None:
        if mode in SUPPORTED_API_MODES:
            self._param_planes()[mode] = self.context.remote_params

    def _activate_param_plane(self, mode: str) -> None:
        planes = self._param_planes()
        target = planes.get(mode)
        if not isinstance(target, dict):
            target = {}
            planes[mode] = target
        for key in RUNTIME_REMOTE_PARAM_KEYS:
            if key in self.context.remote_params and key not in target:
                target[key] = self.context.remote_params[key]
        self.context.remote_params = target

    def _prompt_planes(self) -> dict[str, dict[str, str]]:
        planes = getattr(self.context, "prompt_planes", None)
        if not isinstance(planes, dict):
            planes = {}
            self.context.prompt_planes = planes
        return planes

    def _stash_active_prompt_plane(self, mode: str) -> None:
        if mode in SUPPORTED_API_MODES:
            self._prompt_planes()[mode] = {
                "prompt": str(self.context.prompt_text or ""),
                "negative_prompt": str(self.context.negative_prompt_text or ""),
            }

    def _activate_prompt_plane(self, mode: str) -> None:
        plane = self._prompt_planes().get(mode)
        if not isinstance(plane, dict):
            # No remembered prompt for this mode yet — start it blank rather than
            # carrying the outgoing mode's prompt across (the leak this fixes).
            plane = {"prompt": "", "negative_prompt": ""}
            self._prompt_planes()[mode] = plane
        self.context.prompt_text = str(plane.get("prompt") or "")
        self.context.negative_prompt_text = str(plane.get("negative_prompt") or "")

    def set_option(self, key: str, value: Any) -> None:
        if key not in REMOTE_OPTION_DEFAULTS:
            return
        self.context.remote_options[key] = self.coerce_bool(value)
        if key == "auto_save":
            self.context.auto_save_state["auto_save"] = self.context.remote_options[key]
        self.context.save_remote_ui_state()
        self.context.publish("remote_options_changed", self.get_options())

    def get_options(self) -> dict[str, bool]:
        options = dict(REMOTE_OPTION_DEFAULTS)
        options.update({
            key: bool(value)
            for key, value in self.context.remote_options.items()
            if key in options
        })
        return options

    def set_param(self, key: str, value: Any) -> None:
        clean_key = str(key or "").strip()
        if not clean_key:
            return
        coerced = self.coerce_remote_param(clean_key, value)
        if clean_key == "model" and self.get_api_mode() == "NAI":
            coerced = self.guarded_nai_model_key(coerced)
        self.context.remote_params[clean_key] = coerced
        self._sync_cached_selection(clean_key, self.context.remote_params[clean_key])
        self.context.save_remote_ui_state()
        self.context.publish("remote_params_changed", self.context.generation_param_schema_payload())

    def _sync_cached_selection(self, key: str, value: Any) -> None:
        if key not in {"model", "sampler", "scheduler", "hr_upscaler"}:
            return
        mode = self.get_api_mode()
        option_cache = getattr(self.context, "remote_option_cache", None)
        if not isinstance(option_cache, dict):
            return
        cached_options = option_cache.get(mode)
        if not isinstance(cached_options, dict):
            return
        cached_options[key] = [value]

    def guarded_nai_model_key(self, value: Any) -> str:
        """레지스트리가 아는 키만 통과시킨다. 모르는 것이면 쓰던 것(없으면 기본)으로.

        ⚠️ 이 자리는 **모든 파라미터 설정이 지나는 목**이다 - UI 드롭다운뿐 아니라
           프리셋 적용·메타데이터 불러오기가 전부 여기로 온다. NAI 는 PNG 에 표시
           라벨을 남기므로(`NovelAI Diffusion V5`) 그 문자열이 한 번 흘러들면
           `remote_params["model"]` 에 앉아 **디스크에 저장되고**, 그 뒤로는 껐다
           켜도 `등록되지 않은 NAI 모델 키입니다` 로 생성이 영영 막힌다
           (사용자 제보 2026-08-25: 재시작·API 키 재발급으로도 안 풀렸다).

        생성 시점의 엄격한 판정(`resolve_nai_model_for_context`)은 그대로 둔다 -
        지우거나 오타 난 사용자 모델이 **말없이 4.5 Full 로** 돈에 태워지면 안 된다.
        여기서 막는 것은 애초에 모델 키가 아닌 것이 **들어와 눌러앉는 것**이다.
        """
        from core.nai_model_contract import DEFAULT_NAI_MODEL_KEY, normalize_nai_model_key

        key = normalize_nai_model_key(value)
        if not key:
            return key
        try:
            registry = self.context._nai_model_registry()
            if registry.has_key(key):
                return key
            fallback = normalize_nai_model_key(self.context.remote_params.get("model"))
            if not fallback or not registry.has_key(fallback):
                fallback = DEFAULT_NAI_MODEL_KEY
        except Exception as exc:  # noqa: BLE001 - 조회 실패가 파라미터 설정을 막으면 안 된다
            print(f"[warn] NAI model key check failed: {exc}", flush=True)
            return key
        print(f"[warn] unknown NAI model key rejected: {key} -> {fallback}", flush=True)
        return fallback

    def current_model_key(self) -> str:
        model = str(self.context.remote_params.get("model") or "NAID4.5F").strip()
        return model or "NAID4.5F"

    def _current_nai_model_spec(self):
        try:
            return resolve_nai_model_for_context(
                self.context,
                self.current_model_key(),
            )
        except (KeyError, RuntimeError, ValueError):
            return None

    def is_naid45_model(self) -> bool:
        spec = self._current_nai_model_spec()
        return bool(spec and spec.supports_character_reference)

    def is_naid3_model(self) -> bool:
        spec = self._current_nai_model_spec()
        return bool(spec and spec.payload_profile == "v3")

    def nai_model_supports_vibe(self) -> bool:
        spec = self._current_nai_model_spec()
        return bool(spec and spec.supports_vibe)

    @staticmethod
    def coerce_remote_param(key: str, value: Any) -> Any:
        if key in REMOTE_BOOLEAN_PARAMS:
            return HeadlessRemoteStateService.coerce_bool(value)
        if key in REMOTE_INT_PARAMS:
            try:
                if value is None or value == "":
                    return ""
                return int(float(value))
            except (TypeError, ValueError):
                return value
        if key in REMOTE_FLOAT_PARAMS:
            try:
                if value is None or value == "":
                    return ""
                return float(value)
            except (TypeError, ValueError):
                return value
        return value

    @staticmethod
    def coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
