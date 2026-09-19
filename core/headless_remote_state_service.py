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
    # Auto Gen 중 태그 필터 풀이 소진됐을 때 **되살리지 않고 멈춘다**(사용자 지정
    # 2026-08-31). 기본 꺼짐 = 검색 시점 스냅샷으로 되살려 계속 돈다.
    "stop_autogen_on_tag_exhaust": False,
    # 이벤트 맵 진입 반구 단추(E)를 숨긴다. 숨겨도 **Ctrl+E 는 그대로 열린다**
    # (사용자 지시 2026-09-13 - 화면에서 치우고 싶을 뿐, 기능을 끄는 것이 아니다).
    "hide_event_map_button": False,
}
REMOTE_BOOLEAN_PARAMS = {
    "seed_fixed",
    "random_resolution",
    "auto_fit_resolution",
    "enable_hr",
    "resolution_preset_enabled",
    "nai_resolution_preset_enabled",
    "webui_hiresfix_assist",
    "webui_hiresfix_assist_enabled",
    "webui_custom_payload_enabled",
    # 투명 배경(V5 t2i 전용). 문자열 `"true"` 로 오는 경로가 있어 여기서 불리언으로 굳힌다 -
    # 그래야 저장본과 화면이 같은 모양을 본다.
    "transparent_background",
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
        from core.generation_access_policy import access_policy, GenerationBlocked
        policy = access_policy(self.context)
        if policy.blocked and normalized != "NAI":
            raise GenerationBlocked(policy.reason())
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
        self._sync_resolution_dimensions(clean_key, self.context.remote_params[clean_key])
        self._disable_unsupported_reference_frames(clean_key)
        self.context.save_remote_ui_state()
        self.context.publish("remote_params_changed", self.context.generation_param_schema_payload())

    def _disable_unsupported_reference_frames(self, key: str) -> list[str]:
        """새 모델이 못 쓰는 Character Reference / Vibe Transfer 를 꺼 둔다.

        ⚠️ **여기가 목이다.** 모델을 바꾸는 길은 하나가 아니다 - UI 드롭다운뿐
           아니라 프리셋 적용·메타데이터 불러오기가 전부 이 set_param 으로 온다
           (`guarded_nai_model_key` 주석 참조). 프론트의 모델 변경 분기에 걸면
           프리셋으로 V5 가 된 사람은 그대로 지나간다.

        V4.5 에서 CR/VT 를 켜고 V5 로 넘어가면 켜진 채로 남아 있었다(사용자 제보
        2026-09-19). 생성 자체는 이미 안전하다 - CR 은 `active_params()` 가
        V4.5 가 아니면 `{}` 를 주고, VT 도 같은 가드를 갖는다. 그래서 그림이
        틀리게 나오진 않았지만, **화면은 켜졌다고 말하고 있었다**.

        끄는 것은 `disable_all_frames()` 로 한다 - CR↔VT 상호배타가 쓰는 것과
        같은 영속 진입점이다. 그 함수는 `_ensure_loaded()` 로 시작해 **미로드
        상대까지 깨워** 디스크의 enabled 를 끄고 저장한다. 모듈을 한 번도 연 적
        없는 세션에서 목록이 비어 보인다고 건너뛰면, 나중에 모듈을 열 때 디스크의
        켜진 프레임이 그대로 되살아난다.

        그래서 '켜진 게 있나' 를 미리 보고 거르지 **않는다**. 로드는 모드당 1회
        캐시(`_character_reference_frames_loaded_mode`)라 반복 비용도 없고,
        끌 것이 없으면 `disable_all_frames()` 는 저장도 하지 않는다.

        ⚠️ 되돌려 주지 않는다. V4.5 로 되돌아가도 사용자가 다시 켜야 한다 -
           기존 cross-disable 과 같은 성질이다.

        반환: 꺼 달라고 청한 도구 id 목록. 모델 키가 아니거나 NAI 모드가 아니면
        빈 목록.
        """
        if key != "model" or self.get_api_mode() != "NAI":
            return []
        disabled: list[str] = []
        if not self.is_naid45_model():
            self._call_context("_disable_all_character_reference_frames")
            disabled.append("character_reference")
        if not self.nai_model_supports_vibe():
            self._call_context("_disable_all_vibe_frames")
            disabled.append("vibe_transfer")
        return disabled

    def _call_context(self, method_name: str) -> None:
        method = getattr(self.context, method_name, None)
        if not callable(method):
            return
        try:
            method()
        except Exception as exc:  # noqa: BLE001 - 끄기 실패가 모델 변경을 막으면 안 된다
            print(f"[warn] {method_name} failed: {exc}", flush=True)

    def _sync_resolution_dimensions(self, key: str, value: Any) -> None:
        """`resolution` 라벨을 바꾸면 `width`/`height` 도 **함께** 옮긴다.

        ⚠️ 안 맞추면 라벨과 치수가 갈린다. 생성 직전 정규화
           (`headless_generation_service._normalize_resolution`)는 **치수를 먼저**
           보므로, 갈리면 사용자가 고른 해상도가 조용히 무시되고 옛 치수로 나간다.
           실측 2026-08-29: 저장 파일이 `resolution '1408 x 960'` 인데
           `width 1280 / height 1024` 로 이미 갈려 있었다(Codex 리뷰 HIGH).
           set_param 이 이 키 하나만 쓰고 있었던 탓이다.
        ⚠️ 파싱이 안 되면 **아무것도 안 한다** - 모르는 형식에 치수를 지어내면
           안 된다.
        """
        if key != "resolution":
            return
        from core.resolution_utils import parse_resolution_pair

        pair = parse_resolution_pair(value)
        if not pair:
            return
        self.context.remote_params["width"] = int(pair[0])
        self.context.remote_params["height"] = int(pair[1])

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
        """모델 **이름**이 키 자리로 들어오면 키로 되돌린다. 그 외에는 **손대지 않는다**.

        ⚠️ 이 자리는 **모든 파라미터 설정이 지나는 목**이다 - UI 드롭다운뿐 아니라
           프리셋 적용·메타데이터 불러오기가 전부 여기로 온다. NAI 는 PNG 에 표시
           라벨을 남기므로(`NovelAI Diffusion V5`) 그 문자열이 한 번 흘러들면
           `remote_params["model"]` 에 앉아 **디스크에 저장되고**, 그 뒤로는 껐다
           켜도 생성이 영영 막힌다(사용자 제보 2026-08-25).

        ⚠️⚠️ **모르는 값을 다른 모델로 갈아 끼우지 않는다.** 한때 "쓰던 것(없으면
           기본)" 으로 되돌렸는데, 그러면 사용자가 등록했다가 지운 커스텀 모델을
           고른 프리셋이 **말없이 4.5 Full 로 돈을 태운다**(Codex 리뷰 BLOCK, 재현됨).
           돈이 나가는 판단은 화면이 아니라 사람이 해야 한다.

           그래서 여기서 하는 일은 **번역 하나뿐**이다: 그 값이 우리가 아는 모델의
           표시 라벨이나 wire 이름과 **정확히 같으면** canonical 키로 되돌린다
           (`NOVELAI DIFFUSION V5` -> `NAID5F` — 원래 고르려던 그 모델이다).
           무엇인지 모르겠으면 **그대로 둔다.** 그러면 생성 직전에 막히고, 화면이
           PARAMS 를 열어 다시 고르게 안내한다.

        ⚠️ **표시 이름만** 번역한다(`nai_key_from_display_name`). 라벨·계열 이름은
           공백이 있어 커스텀 키가 될 수 없으니 남의 키를 삼킬 수가 없다. wire 이름
           (`nai-diffusion-5-full`)은 공백이 없어 **그대로 커스텀 키가 되므로** 여기서
           번역하면 사용자가 고른 자기 모델이 빌트인으로 둔갑한다(Codex 리뷰 BLOCK).
        """
        from core.nai_model_contract import nai_key_from_display_name, normalize_nai_model_key

        key = normalize_nai_model_key(value)
        if not key:
            return key
        try:
            if self.context._nai_model_registry().has_key(key):
                return key
            translated = nai_key_from_display_name(key)
        except Exception as exc:  # noqa: BLE001 - 조회 실패가 파라미터 설정을 막으면 안 된다
            print(f"[warn] NAI model key check failed: {exc}", flush=True)
            return key
        if translated and translated != key:
            print(f"[warn] NAI model name mapped to key: {key} -> {translated}", flush=True)
            return translated
        # 모르는 값이다. 그대로 두고 생성 직전의 엄격한 판정에 맡긴다.
        print(f"[warn] unknown NAI model key kept for reselect: {key}", flush=True)
        return key

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

    def is_naid5_model(self) -> bool:
        """V5 계열인가.

        ⚠️ 계열 판정은 `payload_profile` 로 한다. `family` 는 표시용(색·묶음)이라
           커스텀 모델에서 비어 있을 수 있다 - 그러면 사용자가 등록한 V5 모델이
           조용히 V4 취급을 받는다.
        """
        spec = self._current_nai_model_spec()
        return bool(spec and spec.payload_profile == "v5")

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
