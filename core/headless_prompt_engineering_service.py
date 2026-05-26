"""Headless Prompt Engineering module state service."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

HIRES_OVERLAY_DISALLOWED_NAMES = {"", "*randomized", "(프리셋 없음)"}


class HeadlessPromptEngineeringService:
    def __init__(self, context: Any):
        self.context = context

    @staticmethod
    def _empty_debug_snapshot() -> dict[str, Any]:
        return {
            "source_info": {},
            "filter_log": [],
            "original_count": 0,
            "remaining_count": 0,
            "e621_info": None,
            "implication_info": [],
        }

    @staticmethod
    def _debug_snapshot_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return HeadlessPromptEngineeringService._empty_debug_snapshot()

        def int_value(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return {
            "source_info": copy.deepcopy(metadata.get("debug_source_info") or {}),
            "filter_log": copy.deepcopy(metadata.get("filter_log") or []),
            "original_count": int_value(metadata.get("original_tag_count")),
            "remaining_count": int_value(metadata.get("remaining_tag_count")),
            "e621_info": copy.deepcopy(metadata.get("e621_debug_info")),
            "implication_info": copy.deepcopy(metadata.get("implication_compressed_tags") or []),
        }

    def debug_snapshot(self) -> dict[str, Any]:
        current_context = getattr(self.context, "current_prompt_context", None)
        current_metadata = getattr(current_context, "metadata", None)
        snapshot = self._debug_snapshot_from_metadata(current_metadata)
        if snapshot != self._empty_debug_snapshot():
            return snapshot

        latest_run = getattr(getattr(self.context, "pipeline_run_registry", None), "latest_prompt_run", None)
        if not callable(latest_run):
            return snapshot
        run = latest_run()
        return self._debug_snapshot_from_metadata(getattr(run, "metadata", None))

    def state(self) -> dict[str, Any]:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        self.ensure_first_run_recommended_preset()
        settings = store.collect_settings()
        state = store.state()
        preset_options = store.preset_options()

        def preset_summary(name: str, mode: str | None = None) -> dict[str, Any]:
            if name == "*randomized":
                return {
                    "name": name,
                    "api_mode": context.get_api_mode(),
                    "description": "Randomized preset pool",
                    "pre_prompt_preview": "",
                    "thumbnail_url": "",
                }
            data = store.read_preset_data(name, mode or context.get_api_mode())
            module_settings = data.get("module_settings") if isinstance(data, dict) else {}
            module_settings = module_settings if isinstance(module_settings, dict) else {}
            return {
                "name": name,
                "api_mode": str(data.get("api_mode") or mode or context.get_api_mode()),
                "description": str(data.get("description") or ""),
                "pre_prompt_preview": str(module_settings.get("pre_prompt") or ""),
                "thumbnail_url": str(data.get("thumbnail_url") or ""),
            }

        webui_presets = store.list_preset_names("WEBUI")
        payload = {
            "preset": state["current_preset"],
            "preset_options": preset_options,
            "preset_summaries": [preset_summary(name) for name in preset_options],
            "webui_preset_options": webui_presets,
            "webui_preset_summaries": [preset_summary(name, "WEBUI") for name in webui_presets],
            "randomized_active": state["current_preset"] == "*randomized",
            "randomized_preset_list": list(state["randomized_preset_list"]),
            "randomized_available_presets": store.randomized_available_presets(),
            "pre_prompt": settings.get("pre_prompt", ""),
            "post_prompt": settings.get("post_prompt", ""),
            "auto_hide": settings.get("auto_hide_prompt", ""),
            "preprocessing": dict(settings.get("preprocessing_options") or {}),
            "e621_settings": dict(settings.get("e621_settings") or {}),
            "danbooru_settings": dict(settings.get("danbooru_weight_settings") or {}),
            "debug_snapshot": self.debug_snapshot(),
            "preset_can_save_current": state["current_preset"] not in ("", "(프리셋 없음)", "*randomized"),
            "preset_can_delete": state["current_preset"] not in ("", "(프리셋 없음)", "*randomized", "default"),
        }
        return context._module_state_payload("prompt_engineering", payload)

    def ensure_first_run_recommended_preset(self) -> tuple[bool, str]:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        mode = context.get_api_mode()
        if mode == "COMFYUI" and not self._is_comfyui_anima_mode():
            return False, ""
        if mode not in {"NAI", "WEBUI", "COMFYUI"}:
            return False, ""
        if store.load_last_used_preset(mode):
            return False, ""
        user_presets = [
            name
            for name in store.list_preset_names(mode)
            if name not in {"", "default", "*randomized"}
        ]
        if user_presets:
            return False, ""
        ok, message = self.create_and_apply_recommended_preset(save_current=False)
        if ok:
            print(f"Remote Web: first-run recommended preset applied: {message}", flush=True)
        return ok, message

    def ensure_first_run_recommended_preset_payloads(self) -> list[dict[str, Any]]:
        ok, _message = self.ensure_first_run_recommended_preset()
        if not ok:
            return []
        context = self.context
        return [
            self.state(),
            context.generation_param_schema_payload(),
            {
                "type": "prompt_sync",
                "prompt": context.prompt_text,
                "negative": context.negative_prompt_text,
                "negative_prompt": context.negative_prompt_text,
            },
        ]

    def set_param(self, key: str, value: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        text_value = str(value or "")
        if key == "pre_prompt":
            store.apply_settings({"pre_prompt": text_value})
        elif key == "post_prompt":
            store.apply_settings({"post_prompt": text_value})
        elif key == "auto_hide":
            store.apply_settings({"auto_hide_prompt": text_value})
        elif key == "preset":
            if not store.set_preset(text_value):
                return context._toast(f"프리셋을 찾을 수 없습니다: {text_value}", level="error")
        elif key == "preset_save_current":
            ok, message = store.save_current_preset()
            if not ok:
                return context._toast(message, level="error")
        elif key == "preset_create":
            ok, message = store.create_preset(text_value)
            if not ok:
                return context._toast(message, level="error")
        elif key == "preset_apply_recommended":
            ok, message = self.create_and_apply_recommended_preset()
            if not ok:
                return context._toast(message, level="error")
            return [
                context._toast(f"추천 프리셋 적용: {message}", level="success"),
                self.state(),
                context.generation_param_schema_payload(),
                {
                    "type": "prompt_sync",
                    "prompt": context.prompt_text,
                    "negative": context.negative_prompt_text,
                    "negative_prompt": context.negative_prompt_text,
                },
            ]
        elif key == "preset_delete":
            ok, message = store.delete_preset(text_value or store.state()["current_preset"])
            if not ok:
                return context._toast(message, level="error")
        elif key == "randomized_add":
            ok, message = store.add_randomized_preset(text_value)
            if not ok:
                return context._toast(message, level="error")
        elif key == "randomized_remove":
            ok, message = store.remove_randomized_preset(text_value)
            if not ok:
                return context._toast(message, level="error")
        elif key == "randomized_clear":
            store.clear_randomized_presets()
        elif key == "e621_settings":
            settings = json.loads(text_value or "{}")
            if not isinstance(settings, dict):
                return context._toast("Invalid e621 settings", level="error")
            store.save_e621_settings(settings)
            store.apply_settings({"e621_settings": settings})
        elif key == "danbooru_settings":
            settings = json.loads(text_value or "{}")
            if not isinstance(settings, dict):
                return context._toast("Invalid Danbooru settings", level="error")
            store.save_danbooru_weight_settings(settings)
            store.apply_settings({"danbooru_weight_settings": settings})
        elif key == "debug_refresh":
            pass
        elif key.startswith("pp_"):
            option_key = key[3:]
            settings = store.collect_settings()
            preprocessing = dict(settings.get("preprocessing_options") or {})
            preprocessing[option_key] = context._coerce_bool(value)
            store.apply_settings({"preprocessing_options": preprocessing})
        else:
            return None
        return self.state()

    def create_and_apply_recommended_preset(self, *, save_current: bool = True) -> tuple[bool, str]:
        from core.prompt_engineering_settings import get_prompt_engineering_store

        context = self.context
        store = get_prompt_engineering_store(context)
        mode = context.get_api_mode()
        if mode == "COMFYUI":
            if not self._is_comfyui_anima_mode():
                return False, "추천 설정 적용은 COMFYUI ANIMA 모드에서만 지원됩니다."
            preset_name = self._unique_preset_name(store, "recommend_anima", mode)
            module_settings = self._comfyui_anima_recommended_module_settings()
            main_settings = self._comfyui_anima_recommended_main_settings()
        elif mode == "WEBUI":
            preset_name = self._unique_preset_name(store, "recommend", mode)
            module_settings = self._webui_recommended_module_settings()
            main_settings = self._webui_recommended_main_settings()
        elif mode == "NAI":
            preset_name = self._unique_preset_name(store, "recommend", mode)
            module_settings = store.collect_settings(mode)
            module_settings.update(self._nai_recommended_module_settings())
            main_settings = self._nai_recommended_main_settings()
        else:
            return False, "추천 설정 적용은 현재 NAI, WEBUI 또는 COMFYUI ANIMA 모드에서만 지원됩니다."

        if save_current:
            current = store.state(mode).get("current_preset")
            if current and current not in {"", "(프리셋 없음)", "*randomized"}:
                store.save_current_preset(mode)

        preset_data = {
            "api_mode": mode,
            "module_settings": module_settings,
            "main_settings": main_settings,
        }
        store.write_preset_data(preset_name, mode, preset_data)
        store.refresh(mode)
        if not store.set_preset(preset_name, mode):
            return False, f"프리셋을 적용할 수 없습니다: {preset_name}"
        self._apply_main_settings(main_settings)
        return True, preset_name

    def _is_comfyui_anima_mode(self) -> bool:
        context = self.context
        if context.get_api_mode() != "COMFYUI":
            return False
        sampling_mode = str(context.remote_params.get("sampling_mode") or "").strip().lower()
        comfyui_sampling_mode = str(context.remote_params.get("comfyui_sampling_mode") or "").strip().lower()
        workflow_type = str(
            context.remote_params.get("workflow_type")
            or context.remote_params.get("comfyui_workflow_type")
            or ""
        ).strip().lower()
        if sampling_mode:
            return sampling_mode == "anima"
        if comfyui_sampling_mode:
            return comfyui_sampling_mode == "anima"
        return workflow_type == "unet"

    @staticmethod
    def _unique_preset_name(store: Any, base_name: str, mode: str) -> str:
        from core.prompt_engineering_settings import sanitize_preset_name

        base = sanitize_preset_name(base_name) or "preset"
        existing = set(store.list_preset_names(mode))
        candidate = base
        suffix = 1
        while candidate in existing:
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def _apply_main_settings(self, main_settings: dict[str, Any]) -> None:
        context = self.context
        prompt_dirty = False
        for key, value in dict(main_settings or {}).items():
            if key == "prompt":
                context.prompt_text = str(value or "")
                prompt_dirty = True
            elif key in {"negative", "negative_prompt"}:
                context.negative_prompt_text = str(value or "")
                prompt_dirty = True
            elif key == "webui_hiresfix_assist":
                enabled = context._coerce_bool(value)
                state = context._normalized_webui_hiresfix_assist_state(
                    context.webui_hiresfix_assist_state
                )
                state["enabled"] = enabled
                state["webui_hiresfix_assist"] = enabled
                context.webui_hiresfix_assist_state = state
                context.set_param(str(key), enabled)
            elif key == "webui_hiresfix_assist_target":
                target = 768 if str(value).strip() == "768" else 512
                state = context._normalized_webui_hiresfix_assist_state(
                    context.webui_hiresfix_assist_state
                )
                state["target"] = target
                state["webui_hiresfix_assist_target"] = target
                context.webui_hiresfix_assist_state = state
                context.set_param(str(key), target)
            else:
                context.set_param(str(key), value)
        if main_settings or prompt_dirty:
            context.save_remote_ui_state()
            context.publish("remote_params_changed", context.generation_param_schema_payload())

    def _webui_remote_options(self, option_key: str) -> list[str]:
        context = self.context
        option_cache = getattr(context, "remote_option_cache", {}) or {}
        cached_options = option_cache.get("WEBUI", {}) if isinstance(option_cache, dict) else {}
        values = cached_options.get(option_key) if isinstance(cached_options, dict) else None
        if isinstance(values, list):
            return [str(value) for value in values if str(value or "").strip()]
        return []

    @staticmethod
    def _option_key(value: str) -> str:
        return "".join(ch for ch in str(value or "").lower() if ch.isalnum())

    def _preferred_webui_option(self, option_key: str, preferred: list[str], fallback: str) -> str:
        options = self._webui_remote_options(option_key)
        if not options:
            return fallback
        option_by_key = {self._option_key(option): option for option in options}
        for candidate in preferred:
            matched = option_by_key.get(self._option_key(candidate))
            if matched:
                return matched
        return options[0]

    @staticmethod
    def _comfyui_anima_recommended_module_settings() -> dict[str, Any]:
        return {
            "pre_prompt": "(@myowa), newest, year2024, (best quality), highres, absurdres",
            "post_prompt": (
                "(3d background, blurry background:1.5), (musk, oekaki, crosshatching, sketch, "
                "watercolor \\(medium\\), airbrush \\(medium\\), cel rendering:0.4), "
                "(delicate colored lineart, highly aesthetic Pixiv style illustration, clean composition, "
                "high-quality digital art, very thin lineart, low contrast shading, cinematic lighting, "
                "very beautiful and detailed scene:0.8)"
            ),
            "auto_hide_prompt": "",
        }

    @staticmethod
    def _comfyui_anima_recommended_main_settings() -> dict[str, Any]:
        return {
            "negative": (
                "ai-generated, face in shadow, (worst quality), low quality, cropped, (score_1), "
                "score_2, score_3, artist logo, unfinished, work-in-progress, blank, letterboxed, "
                "blurry, jpeg artifacts, sepia, mutated, mutated digits, missing fingers, extra digit, "
                "fewer digits, artistic error, bad anatomy, watermark, patreon username, web address, "
                "patreon logo, weibo username, watermark, mature female, adult female, adolescent, "
                "wide hips, narrow waist, long body, (multiple views:1.3), monochrome, greyscale, "
                "retro artstyle, (outline, thick outlines:1.15), bold lines, thick borders, messy shading, "
                "(western comics \\(style\\):1.5), furry, english text, spot color, doodle on background, "
                "gif artifacts, muted color, high contrast, oversaturated colors, glossy highlights"
            ),
            "sampling_mode": "anima",
            "comfyui_sampling_mode": "anima",
            "workflow_type": "unet",
            "sampler": "er_sde",
            "scheduler": "simple",
            "steps": 30,
            "cfg_scale": 5.1,
            "rescale_cfg": 0.5,
            "anima_weight": "1",
        }

    @staticmethod
    def _webui_recommended_module_settings() -> dict[str, Any]:
        return {
            "pre_prompt": "newest, year 2024, (best quality), score_8, highres, absurdres",
            "post_prompt": (
                "(perspective, foreshortening, dutch angle:0.75), "
                "(dynamic facial expressions), exaggerated and dark environment, "
                "violent composition, (low-contrast, muted color, watercolor \\(medium\\), "
                "highly aesthetic Pixiv style illustration, clean composition, view focus "
                "concentrated on the character with blurry background, high-quality digital art.:0.75)"
            ),
            "auto_hide_prompt": (
                "monochrome, doujin cover, bad source, __censor__, uncensored, female pubic hair, "
                "bad id, _logo, bad twitter id, comic, __background__, ~blurry background, "
                "~sky background, character doll, stuffed animal, stuffed toy, speech bubble, cyclops, "
                "pov, 3d, glasses, mole, text focus, thought bubble, watermark, web address, "
                "body writing, fake screenshot, facing away, |_|, __piercing__, tattoo, _tattoo, "
                "_text, sound effects, greyscale, multiple views, __pubic hair__, peeing, rabbit, "
                "__censor__, pregnant, __chess__, trading card, __(medium)__, __theme__, child on child, "
                "covered clitoris, _gag, sketch, poke_, __pokemon__, recording, viewfinder, multiple boys, "
                "__measuring__, multiple views, big belly, curvy, doll joints, looking at viewer, timestamp, "
                "battery indicator, tan, fake phone screenshot, stomach bulge, __beach__, __shower__, "
                "on table, huge penis, __bug__, giant insect, belly, eye mask, circle cut, dark nipples, "
                "signature, alternate race, alternate species, dark nipples, livestream, slap mark, x-ray, "
                "armpit hair, health bar, snapchat, facial mark, emoji, command spell, dark areolae, "
                "__piercing__, __bed__, __pillow__, __sheet__, body markings, obese, __long tongue__, "
                "toddlercon, __name__, handprint, __pasties__, mini person, __butt plug__, __eyepatch__, "
                "oppai loli, sex toy, loli, chibi, chibi inset, makeup, mascara, large breasts, "
                "runny makeup, third eye, anal hair, __halo__, __(style)__, __(cosplay)__, __freckles__, "
                "braces, gag, __joint__"
            ),
            "preprocessing_options": {
                "remove_author": True,
                "remove_work_title": True,
                "remove_character_name": True,
                "remove_character_features": False,
                "remove_clothes": False,
                "remove_clothing_event": False,
                "remove_color": False,
                "remove_location_and_background_color": False,
                "remove_expression": False,
                "remove_pose_action": False,
                "remove_meta_tags": True,
                "remove_object_tags": True,
                "remove_noise_tags": True,
                "closed_eyes_sync": True,
                "e621_auto_boost": False,
                "danbooru_auto_weight": False,
                "tag_implication_compression": True,
            },
        }

    def _webui_recommended_main_settings(self) -> dict[str, Any]:
        return {
            "sampler": self._preferred_webui_option(
                "options_sampler",
                ["ER SDE", "Euler a", "Euler A", "Euler Ancestral"],
                "Euler a",
            ),
            "scheduler": self._preferred_webui_option(
                "options_scheduler",
                ["Simple", "SGM Uniform"],
                "SGM Uniform",
            ),
            "resolution": "1024 x 1024",
            "steps": 32,
            "cfg_scale": 5.0,
            "negative": (
                "ai-generated, 3d, (worst quality), low quality, (score_1), score_2, score_3, "
                "realistic, furry, furry female, anthro, unfinished, work-in-progress, "
                "absurdly detailed composition, blank, blank background, letterboxed, blurry, "
                "jpeg artifacts, mutated, mutated digits, missing fingers, extra digit, fewer digits, "
                "artistic error, unusual anatomy, watermark, patreon username, web address, patreon logo, "
                "weibo username, (artist logo, twitter username, signature), watermark, (multiple views), "
                "distorted anatomy, english text, anatomically incorrect, doodle on background, "
                "bad perspective, high contrast, cool colored, glitch, distortion, colorful, neon palette, "
                "detailed background, (vignetting, shiny skin, shaded face, face in shadow, underexposed face, "
                "underexposed body, dark body, body in shadow, low-key lighting, cast shadow, diagonal shadow, "
                "shadow across face, shadow across torso, harsh shadow, dramatic lighting, spotlight, rim light, "
                "split lighting, chiaroscuro:0.85)"
            ),
            "seed": "-1",
            "seed_fixed": False,
            "enable_hr": False,
            "hr_scale": 2.0,
            "hr_upscaler": "Latent (nearest-exact)",
            "denoising_strength": 0.5,
            "hires_steps": 0,
            "hr_cfg": 7.0,
            "webui_hiresfix_assist": False,
            "webui_hiresfix_assist_target": 512,
            "anima_weight": "1",
            "random_prompt_weight": "1",
            "resolution_preset_enabled": False,
            "resolution_preset": "standard",
        }

    @staticmethod
    def _nai_recommended_module_settings() -> dict[str, Any]:
        return {
            "pre_prompt": (
                "1.2::artist:kim eb ::, 0.7::artist:torino aqua ::, 0.6::artist:mikozin ::, "
                "0.4::tianliang duohe fangdongye, ixy ::, 0.5::kedama milk ::, "
                "0.7::artist:quasarcake ::, 0.7::artist:channel (caststation) ::, "
                "0.6::artist:tab head ::, 0.5::artist:qiandaiyiyu ::, "
                "0.5::artist:mika pikazo ::, 0.3::artist:wanke ::, 0.4::artist:freng ::, "
                "0.25::artist:cutesexyrobutts ::"
            ),
            "post_prompt": (
                "year 2025, year 2024, 1.2::3d ::, 1.2::blender (medium) ::, detailed eyes, "
                "silky skin, detailed skin texture, masterpiece, best quality, very aesthetic, highres, "
                "best illustration, novel illustration, -1.2::simple illustration ::, "
                "-1::artist collaboration ::, -1::multiple views ::, -1::duplicate ::, -0.8::censored ::"
            ),
            "auto_hide_prompt": (
                "monochrome, doujin cover, bad source, __censor__, uncensored, female pubic hair, "
                "bad id, _logo, bad twitter id, comic, __background__, ~blurry background, "
                "~sky background, character doll, stuffed animal, stuffed toy, speech bubble, cyclops, "
                "pov, 3d, glasses, mole, text focus, thought bubble, watermark, web address, "
                "body writing, fake screenshot, facing away, |_|, __piercing__, tattoo, _tattoo, "
                "_text, sound effects, greyscale, multiple views, __pubic hair__, peeing, rabbit, "
                "__censor__, pregnant, __chess__, trading card, __(medium)__, __theme__, child on child, "
                "covered clitoris, _gag, sketch, poke_, __pokemon__, recording, viewfinder, multiple boys, "
                "__measuring__, multiple views, big belly, curvy, doll joints, looking at viewer, timestamp, "
                "battery indicator, tan, fake phone screenshot, stomach bulge, __beach__, __shower__, "
                "on table, huge penis, __bug__, giant insect, belly, eye mask, circle cut, dark nipples, "
                "signature, alternate race, alternate species, dark nipples, livestream, slap mark, x-ray, "
                "armpit hair, health bar, snapchat, facial mark, emoji, command spell, dark areolae, "
                "__piercing__, __bed__, __pillow__, __sheet__, body markings, obese, __long tongue__, "
                "toddlercon, __name__, handprint, __pasties__, mini person, __butt plug__, __eyepatch__, "
                "oppai loli, sex toy, loli, chibi, chibi inset, makeup, mascara, large breasts, "
                "runny makeup, third eye, anal hair, __halo__, __(style)__, __(cosplay)__, __freckles__, "
                "braces, gag, __joint__"
            ),
            "preprocessing_options": {
                "remove_author": True,
                "remove_work_title": True,
                "remove_character_name": True,
                "remove_character_features": False,
                "remove_clothes": False,
                "remove_clothing_event": False,
                "remove_color": False,
                "remove_location_and_background_color": False,
                "remove_expression": False,
                "remove_pose_action": False,
                "remove_meta_tags": True,
                "remove_object_tags": True,
                "remove_noise_tags": True,
                "e621_auto_boost": False,
                "danbooru_auto_weight": False,
                "tag_implication_compression": True,
            },
        }

    @staticmethod
    def _nai_recommended_main_settings() -> dict[str, Any]:
        return {
            "model": "NAID4.5F",
            "sampler": "k_euler_ancestral",
            "scheduler": "karras",
            "resolution": "1024 x 1024",
            "steps": 28,
            "cfg_scale": 5.8,
            "cfg_rescale": 0.28,
            "negative": (
                "text, logo, signature, watermark, too many watermarks, chili inset, "
                "0.4::artist:nameo (judgemasterkou), artist:matsunaga kouyou::, artist collaboration, "
                "chibi, 1990s (style), bad anatomy, distorted anatomy, disfigured, bad hands, "
                "missing finger, extra digits, mutation, extra arms, extra legs, long neck, bad feet, "
                "very displeasing, undetailed eyes, multiple views, negative space, blank page, variant set, "
                "large variant set, 4koma, 2koma, oekaki, halftone, screentone, artistic error, "
                "film grain, scan artifacts, jpeg artifacts, chromatic aberration, dithering, "
                "disorganized colors, lowres, worst quality, bad quality, cheesy, sloppiness, "
                "unfinished, Incomplete, ai-generated"
            ),
            "seed": "8097879955",
            "seed_fixed": False,
            "random_resolution": True,
            "auto_fit_resolution": True,
            "SMEA": False,
            "DYN": False,
            "VAR+": True,
            "DECRISP": False,
        }

    def hires_overlay_response(self, preset_name: str) -> dict[str, Any]:
        name = str(preset_name or "").strip()
        response = {
            "type": "hires_preset_overlay",
            "preset_name": name,
            "original": {"prefix_prompt": "", "postfix_prompt": "", "negative_prompt": ""},
            "overlay": None,
            "editable": False,
            "available": False,
            "runtime": "web",
        }
        path = self.hires_overlay_path(name)
        if path is None:
            return response
        response["editable"] = True
        response["available"] = True
        preset_path = self.context._existing_save_path("presets", "WEBUI", f"{name}.json")
        if preset_path.exists():
            try:
                preset_data = json.loads(preset_path.read_text(encoding="utf-8"))
                module_settings = preset_data.get("module_settings", {}) if isinstance(preset_data, dict) else {}
                main_settings = preset_data.get("main_settings", {}) if isinstance(preset_data, dict) else {}
                module_settings = module_settings if isinstance(module_settings, dict) else {}
                main_settings = main_settings if isinstance(main_settings, dict) else {}
                response["original"] = {
                    "prefix_prompt": str(module_settings.get("pre_prompt", "") or ""),
                    "postfix_prompt": str(module_settings.get("post_prompt", "") or ""),
                    "negative_prompt": str(
                        main_settings.get("negative") or main_settings.get("negative_prompt") or ""
                    ),
                }
            except Exception:
                pass
        overlay_path = self.context._existing_save_path("presets", "WEBUI", f"{name}.hires.json")
        if overlay_path.exists():
            try:
                overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
                if isinstance(overlay, dict):
                    response["overlay"] = {
                        "prefix_prompt": str(overlay.get("prefix_prompt", "") or ""),
                        "postfix_prompt": str(overlay.get("postfix_prompt", "") or ""),
                        "negative_prompt": str(overlay.get("negative_prompt", "") or ""),
                    }
            except Exception:
                pass
        return response

    def write_hires_overlay(self, preset_name: str, body: dict[str, Any] | None) -> tuple[bool, str]:
        path = self.hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        source = body if isinstance(body, dict) else {}
        payload = {
            "schema_version": 1,
            "prefix_prompt": str(source.get("prefix_prompt", "") or ""),
            "postfix_prompt": str(source.get("postfix_prompt", "") or ""),
            "negative_prompt": str(source.get("negative_prompt", "") or ""),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, f"Overlay saved: {path.name}"
        except Exception as exc:
            return False, f"저장 실패: {exc}"

    def reset_hires_overlay(self, preset_name: str) -> tuple[bool, str]:
        path = self.hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        try:
            if path.exists():
                path.unlink()
                return True, f"Overlay removed: {path.name}"
            return True, "Overlay already absent."
        except Exception as exc:
            return False, f"삭제 실패: {exc}"

    def hires_overlay_path(self, preset_name: str) -> Path | None:
        name = str(preset_name or "").strip()
        if name in HIRES_OVERLAY_DISALLOWED_NAMES:
            return None
        safe_name = Path(name).name
        if safe_name != name:
            return None
        if self.context.get_api_mode() != "WEBUI":
            return None
        return self.context._save_path("presets", "WEBUI", f"{safe_name}.hires.json")
