import copy
import json
import os
from pathlib import Path
from typing import Any, Callable


DEFAULT_CONDITIONAL_ENGINE_OPTIONS = {
    "max_passes": 1,
    "stop_on_match": False,
}

# 조건식 연산자 우선순위 스키마. 0 = 우선순위 수정 이전(구 런타임이 `&` 를 먼저 분할하던 시절)
# 저장분. 1 = 표준 우선순위 기준으로 해석해도 되는 텍스트. **로드 시점에 0 인 파일에만** 괄호
# 마이그레이션을 태운다 — 저장 때마다 태우면 사용자가 새로 입력한 `a|b&c`(표준 의미)까지
# 옛 의미로 되돌려버린다.
PRECEDENCE_SCHEMA = 1

DEFAULT_CONDITIONAL_SETTINGS = {
    "enabled": False,
    "rules": "",
    "rules_v2": "",
    "editor_mode": "legacy",
    # ⚠️ 엔진 옵션도 **모드별로** 기억한다. RuleBook JSON 에는 옵션이 규칙과 함께
    # 들어 있어 프리셋의 일부다 - 칸이 하나면 프리셋을 부를 때마다 반대편 모드의
    # 옵션까지 덮어써서, Legacy 로 돌아왔을 때 이름·규칙은 L 인데 max_passes 는
    # V 것이 된다(Codex 지적, 코드로 확인).
    "engine_options_legacy": dict(DEFAULT_CONDITIONAL_ENGINE_OPTIONS),
    "engine_options_v2": dict(DEFAULT_CONDITIONAL_ENGINE_OPTIONS),
    # 지금 모드의 옵션을 비추는 파생값. 엔진이 읽는 이름이라 유지한다.
    "engine_options": dict(DEFAULT_CONDITIONAL_ENGINE_OPTIONS),
    # ⚠️ 프리셋 이름은 **모드별로** 기억한다. 규칙 칸이 `rules`(Legacy) / `rules_v2`
    # (블록 편집기)로 나뉘어 있는데 이름표만 하나면, 모드를 바꿨을 때 규칙은 이쪽
    # 것인데 이름은 저쪽 것이 뜬다 - "프리셋을 바꿨는데 내용이 안 바뀐다" 로 보인다
    # (실측 2026-08-23: legacy 복귀 후 규칙은 legacy 인데 이름표는 v2 프리셋).
    # 모드별로 다른 프리셋을 쓰려는 것이 이 기능의 목적이다(사용자).
    "active_preset_legacy": None,
    "active_preset_v2": None,
    # 옛 단일 키. 읽기 전용 하위호환 - 마이그레이션이 위 둘로 옮긴다.
    "active_preset": None,
    "precedence_schema": PRECEDENCE_SCHEMA,
}


def normalize_conditional_mode(mode: Any = None) -> str:
    text = str(mode or "NAI").strip().upper()
    return text if text in {"NAI", "WEBUI", "COMFYUI"} else "NAI"


def _default_save_root() -> Path:
    user_data_dir = os.environ.get("NAIA_USER_DATA_DIR")
    if user_data_dir:
        return Path(user_data_dir).expanduser().resolve() / "save"
    return Path("save")


def _coerce_save_root(save_root: Path | str | None = None) -> Path:
    return Path(save_root).expanduser().resolve() if save_root is not None else _default_save_root()


def _legacy_save_fallback_enabled() -> bool:
    if os.environ.get("NAIA_DISABLE_LEGACY_SAVE_FALLBACK") == "1":
        return False
    if os.environ.get("NAIA_ELECTRON") == "1":
        return False
    return True


def conditional_settings_path(mode: Any = None, *, save_root: Path | str | None = None) -> Path:
    return _coerce_save_root(save_root) / f"PromptListModifierModule_{normalize_conditional_mode(mode)}.json"


def _existing_conditional_settings_path(mode: Any = None, *, save_root: Path | str | None = None) -> Path:
    primary = conditional_settings_path(mode, save_root=save_root)
    if primary.exists():
        return primary
    legacy = Path("save").resolve() / primary.name
    if _legacy_save_fallback_enabled() and legacy != primary.resolve() and legacy.exists():
        return legacy
    return primary


def normalize_conditional_engine_options(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    try:
        max_passes = int(source.get("max_passes", 1))
    except Exception:
        max_passes = 1
    return {
        "max_passes": min(20, max(1, max_passes)),
        "stop_on_match": bool(source.get("stop_on_match", False)),
    }


def migrate_precedence_payload(payload: Any) -> Any:
    """저장 파일이 우선순위 수정 **이전** 스키마일 때만 1회 괄호 마이그레이션.

    구 런타임은 최상위 `&` 를 먼저 분할해 `a|b&c` 를 `(a|b)&c` 로 계산했다. 표준 우선순위로
    고친 뒤에도 기존 규칙의 결과가 바뀌지 않도록 명시적 괄호를 넣는다.

    **로드 경로에서만** 호출해야 한다. 저장 경로에서도 돌리면 사용자가 새 규칙으로 입력한
    `a|b&c`(안내대로라면 `a|(b&c)`)까지 구 의미로 되돌아간다.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        schema = int(payload.get("precedence_schema", 0))
    except Exception:
        schema = 0
    if schema >= PRECEDENCE_SCHEMA:
        return payload
    try:
        from core.conditional.lint import migrate_rules_text

        migrated = dict(payload)
        rewritten = False
        for key in ("rules", "rules_v2"):
            text = str(migrated.get(key, "") or "")
            if not text:
                continue
            updated = migrate_rules_text(text)
            if updated != text:
                rewritten = True
            migrated[key] = updated
        migrated["precedence_schema"] = PRECEDENCE_SCHEMA
    except Exception as exc:  # 마이그레이션 실패가 설정 로드를 막으면 안 된다
        print(f"Conditional Prompt precedence migration skipped: {exc}")
        return payload
    if rewritten:
        print("Conditional Prompt: mixed &/| rules rewritten with explicit parentheses (behavior preserved)")
    return migrated


def normalize_conditional_settings(raw: Any = None) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    settings = copy.deepcopy(DEFAULT_CONDITIONAL_SETTINGS)
    settings["enabled"] = bool(source.get("enabled", settings["enabled"]))
    settings["rules"] = str(source.get("rules", "") or "")
    settings["rules_v2"] = str(source.get("rules_v2", "") or "")
    try:
        schema = int(source.get("precedence_schema", PRECEDENCE_SCHEMA))
    except Exception:
        schema = PRECEDENCE_SCHEMA
    settings["precedence_schema"] = max(0, min(PRECEDENCE_SCHEMA, schema))
    editor_mode = str(source.get("editor_mode", settings["editor_mode"]) or "legacy")
    settings["editor_mode"] = editor_mode if editor_mode in {"legacy", "v2"} else "legacy"
    # 엔진 옵션: 모드별 두 칸 + 지금 모드를 비추는 파생 `engine_options`.
    #
    # ⚠️ 마이그레이션 규칙이 `active_preset` 과 **다르다.** 옛 저장본의 단일 값은
    # **양쪽에 다 넣는다.** 이름표는 "사용자가 그 편집기에서 고른 프리셋" 이라
    # 한쪽에만 넣는 것이 맞지만, 엔진 옵션은 기본값이 있는 설정이라 한쪽에만
    # 넣으면 반대편이 업그레이드하는 순간 조용히 기본값(max_passes=1)으로
    # 떨어진다 - 사용자가 아무것도 안 했는데 동작이 바뀐다.
    has_split = "engine_options_legacy" in source or "engine_options_v2" in source
    fallback = source.get("engine_options")
    settings["engine_options_legacy"] = normalize_conditional_engine_options(
        source.get("engine_options_legacy") if has_split else fallback
    )
    settings["engine_options_v2"] = normalize_conditional_engine_options(
        source.get("engine_options_v2") if has_split else fallback
    )
    settings["engine_options"] = dict(
        settings["engine_options_v2"] if settings["editor_mode"] == "v2"
        else settings["engine_options_legacy"]
    )

    def _name(value):
        return str(value) if value else None

    legacy_name = _name(source.get("active_preset_legacy"))
    v2_name = _name(source.get("active_preset_v2"))
    old_name = _name(source.get("active_preset"))
    # 하위호환: 옛 저장본은 단일 `active_preset` 뿐이다. **지금 모드 쪽으로만**
    # 옮긴다 - 양쪽에 같은 이름을 넣으면 쓰지도 않은 편집기에 프리셋이 걸린 것처럼
    # 보인다. 모드별로 다른 프리셋을 쓰려는 것이 이 기능의 목적이므로 더 그렇다.
    if old_name and not legacy_name and not v2_name:
        if settings["editor_mode"] == "v2":
            v2_name = old_name
        else:
            legacy_name = old_name
    settings["active_preset_legacy"] = legacy_name
    settings["active_preset_v2"] = v2_name
    # 지금 모드의 이름을 옛 키에도 비춰 둔다 - 이 키를 읽는 곳이 아직 남아 있고,
    # 저장본을 되돌려 열어도 뜻이 통해야 한다.
    settings["active_preset"] = v2_name if settings["editor_mode"] == "v2" else legacy_name
    return settings


def load_conditional_settings(mode: Any = None, *, save_root: Path | str | None = None) -> dict[str, Any]:
    mode_key = normalize_conditional_mode(mode)
    path = _existing_conditional_settings_path(mode_key, save_root=save_root)
    if not path.exists():
        return normalize_conditional_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Conditional Prompt settings load failed: {exc}")
        return normalize_conditional_settings()
    payload = data.get(mode_key, {}) if isinstance(data, dict) else {}
    # 구 스키마 파일에만 1회 적용 — 저장 경로(normalize/save)에서는 절대 돌리지 않는다.
    return normalize_conditional_settings(migrate_precedence_payload(payload))


def save_conditional_settings(
    settings: dict[str, Any],
    mode: Any = None,
    *,
    save_root: Path | str | None = None,
) -> None:
    mode_key = normalize_conditional_mode(mode)
    path = conditional_settings_path(mode_key, save_root=save_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {mode_key: normalize_conditional_settings(settings)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")


class ConditionalPromptHeadlessStore:
    def __init__(
        self,
        mode_getter: Callable[[], str] | None = None,
        *,
        save_root: Path | str | None = None,
    ):
        self._mode_getter = mode_getter
        self._save_root = _coerce_save_root(save_root)
        self._state_by_mode: dict[str, dict[str, Any]] = {}

    def mode(self) -> str:
        if callable(self._mode_getter):
            try:
                return normalize_conditional_mode(self._mode_getter())
            except Exception:
                pass
        return "NAI"

    def state(self, mode: Any = None) -> dict[str, Any]:
        mode_key = normalize_conditional_mode(mode or self.mode())
        if mode_key not in self._state_by_mode:
            self._state_by_mode[mode_key] = load_conditional_settings(mode_key, save_root=self._save_root)
        return self._state_by_mode[mode_key]

    def collect_settings(self, mode: Any = None) -> dict[str, Any]:
        return copy.deepcopy(self.state(mode))

    def apply_settings(self, updates: dict[str, Any], mode: Any = None, *, persist: bool = True) -> dict[str, Any]:
        mode_key = normalize_conditional_mode(mode or self.mode())
        current = self.state(mode_key)
        merged = {**current, **(updates or {})}
        normalized = normalize_conditional_settings(merged)
        self._state_by_mode[mode_key] = normalized
        if persist:
            save_conditional_settings(normalized, mode_key, save_root=self._save_root)
        return copy.deepcopy(normalized)


def get_conditional_prompt_store(app_context) -> ConditionalPromptHeadlessStore:
    store = getattr(app_context, "conditional_prompt_headless_store", None)
    if isinstance(store, ConditionalPromptHeadlessStore):
        return store
    mode_getter = getattr(app_context, "get_api_mode", None)
    runtime_paths = getattr(app_context, "runtime_paths", None)
    save_root = getattr(runtime_paths, "save_dir", None)
    store = ConditionalPromptHeadlessStore(
        mode_getter if callable(mode_getter) else None,
        save_root=save_root,
    )
    setattr(app_context, "conditional_prompt_headless_store", store)
    return store
