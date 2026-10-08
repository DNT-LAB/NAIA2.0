#!/usr/bin/env python3
"""전원이 끊겨 설정 파일이 깨져도 설정 · 퀵 프리셋이 초기화되지 않는지 확인한다.

사용자 제보(2026-10-08): PC 가 멈춰 콘센트를 뽑았더니 퀵 프리셋과 설정이 전부 초기화됐다.
자주 다시 쓰이는 세 파일(app_settings.json · presets/last_used_preset.json · 지금 프리셋 본문)을
전원이 끊긴 모양(0 바이트 · NUL 로 참 · 반쯤 잘림)으로 깨뜨리고 재시작해, .bak 에서 되살아나는지 본다.

`python tools/test_settings_power_loss_recovery.py`
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class _NullTokenStore:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def _break(path: Path, how: str) -> None:
    original = path.read_bytes()
    if how == "empty":
        path.write_bytes(b"")
    elif how == "nul":
        path.write_bytes(b"\x00" * len(original))
    elif how == "truncated":
        path.write_bytes(original[: len(original) // 2])
    else:
        raise ValueError(how)


def main() -> int:
    evidence: dict = {}
    from core.safe_json_file import backup_path

    for how in ("empty", "nul", "truncated"):
        with tempfile.TemporaryDirectory(prefix="naia-power-loss-") as user_data:
            os.environ["NAIA_USER_DATA_DIR"] = user_data
            from core.web_session_context import WebSessionContext

            def boot():
                return WebSessionContext(token_manager=_NullTokenStore())

            context = boot()
            context.set_api_mode("WEBUI")
            context._prompt_engineering_service().ensure_first_run_recommended_preset()
            context.set_module_param("prompt_engineering", "preset_create", "mine")
            context.set_module_param("prompt_engineering", "pre_prompt", "MY_PREFIX")
            context.set_param("steps", "37")
            context.set_param("cfg_scale", "7.7")
            context.prompt_text = "my prompt"
            context.save_remote_ui_state()
            context._prompt_engineering_service().persist_active_settings()

            save_dir = Path(context.runtime_paths.save_dir)
            files = [
                save_dir / "app_settings.json",
                save_dir / "presets" / "last_used_preset.json",
                save_dir / "presets" / "WEBUI" / "mine.json",
            ]
            for path in files:
                assert path.exists() and backup_path(path).exists(), (how, path)
                _break(path, how)

            restarted = boot()
            pe_state = restarted._prompt_engineering_service().state()
            assert restarted.current_api_mode == "WEBUI", (how, restarted.current_api_mode)
            assert str(restarted.remote_params.get("steps")) == "37", (how, restarted.remote_params.get("steps"))
            assert float(restarted.remote_params.get("cfg_scale")) == 7.7, (how, restarted.remote_params.get("cfg_scale"))
            assert restarted.prompt_text == "my prompt", (how, restarted.prompt_text)
            assert pe_state.get("preset") == "mine", (how, pe_state.get("preset"))
            assert pe_state.get("pre_prompt") == "MY_PREFIX", (how, pe_state.get("pre_prompt"))
            for path in files:
                # 되살린 본 파일은 다시 읽히고, 깨진 파일은 지우지 않고 따로 남는다
                json.loads(path.read_text(encoding="utf-8"))
                assert list(path.parent.glob(path.name + ".corrupt-*")), (how, "corrupt copy kept", path)
            evidence[how] = "settings, quick preset and prefix restored"

    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
