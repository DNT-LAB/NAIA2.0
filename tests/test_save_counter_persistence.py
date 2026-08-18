# -*- coding: utf-8 -*-
"""저장 카운터는 **세션 값**이다 - 설정 파일에 눌러앉으면 안 된다.

`5cfe3b68` 이 고친 결함의 회귀망. 그 커밋의 리포트는 이 이름의 테스트가 워킹
트리에 있다고 적었지만 **실제로는 어디에도 없었다**(2026-08-18 확인). 고친
사람이 사라지면 다음 사람이 되돌릴 수 있는 상태라 여기 다시 세운다.

계약: 데스크톱 `ImageCrudController._load_counter_from_settings` 가 못 박은
"앱을 다시 켜면 1부터". 헤드리스는 카운터를 `save_directory_state` 에 두는데,
그 dict 를 `remote_web` 상태로 통째로 저장/복원하면서 카운터까지 딸려갔다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import headless_remote_ui_state_service as svc   # noqa: E402


class _Ctx:
    """`save_remote_ui_state` / `apply_remote_ui_state` 가 만지는 것만 흉내낸다."""

    def __init__(self, root: Path, *, counter: int = 1):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self.save_directory_state = {
            "base_path": str(root / "out"),
            "classification_method": "prompt_recognition",
            "save_counter": counter,
        }
        self.auto_save_state = {"auto_save": True}
        self.remote_options = {"auto_save": True}
        self.remote_params = {}
        self.remote_param_planes = {}
        self.prompt_planes = {}
        self.api_mode = "NAI"
        self.prompt_text = ""
        self.negative_prompt_text = ""

    def get_api_mode(self) -> str:
        return self.api_mode

    def get_options(self) -> dict:
        return dict(self.remote_options)

    def _save_path(self, name: str) -> Path:
        return self._root / name

    # 읽기는 `_existing_save_path` 를 쓴다(포터블은 user-data 쪽을 먼저 본다).
    def _existing_save_path(self, name: str) -> Path:
        return self._root / name

    repo_root = str(ROOT)

    def save_remote_ui_state(self):
        return svc.save_remote_ui_state(self)

    @staticmethod
    def _coerce_bool(value) -> bool:
        return bool(value)


def _settings(ctx: _Ctx) -> dict:
    p = ctx._save_path("app_settings.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _stored_sd(ctx: _Ctx) -> dict:
    return ((_settings(ctx).get("remote_web") or {}).get("save_directory_state") or {})


def test_counter_never_reaches_the_settings_file(tmp_path):
    """이미지 한 장마다 저장되는 경로다 - 여기서 새면 매번 새 번호가 박힌다."""
    ctx = _Ctx(tmp_path, counter=1)
    for n in (1, 2, 3, 10675):
        ctx.save_directory_state["save_counter"] = n
        ctx.save_remote_ui_state()
        assert "save_counter" not in _stored_sd(ctx), f"{n} 이 파일에 새어 나갔다"
    # 나머지 저장 설정은 보존된다(카운터만 빼는 것이지 통째로 버리는 게 아니다).
    assert _stored_sd(ctx).get("classification_method") == "prompt_recognition"


def test_restart_starts_from_one(tmp_path):
    """**계약 그 자체.** 다시 켜면 1 이다."""
    ctx = _Ctx(tmp_path, counter=10675)
    ctx.save_remote_ui_state()
    fresh = _Ctx(tmp_path, counter=1)          # 재시작 = 런타임 기본값으로 시작
    svc.apply_remote_ui_state(fresh)
    assert fresh.save_directory_state["save_counter"] == 1
    assert fresh.save_directory_state["classification_method"] == "prompt_recognition"


def test_old_builds_leftover_is_cleaned_once(tmp_path):
    """옛 빌드가 박아 둔 값은 **정규화 비교에서 지워져 영영 남는다.**

    저장 쪽이 `previous == normalized` 로 중복 쓰기를 막는데, 정규화가 카운터를
    빼고 비교하므로 파일에 남은 10675 는 영원히 같다고 판정된다. 그래서 옛 키가
    있는 경우만 한 번 더 쓴다 - 그 예외가 살아 있는지 본다.
    """
    ctx = _Ctx(tmp_path, counter=1)
    ctx.save_remote_ui_state()
    # 옛 빌드 흉내: 파일에 직접 카운터를 박는다
    data = _settings(ctx)
    data["remote_web"]["save_directory_state"]["save_counter"] = 10675
    ctx._save_path("app_settings.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert _stored_sd(ctx).get("save_counter") == 10675
    ctx.save_remote_ui_state()
    assert "save_counter" not in _stored_sd(ctx), "옛 값이 청소되지 않았다"


def test_clean_saves_do_not_rewrite_the_file(tmp_path):
    """청소 예외가 **매번 쓰기**로 번지지 않는지. 장당 파일 쓰기가 부활하면 안 된다."""
    ctx = _Ctx(tmp_path, counter=1)
    ctx.save_remote_ui_state()
    p = ctx._save_path("app_settings.json")
    before = p.stat().st_mtime_ns
    for n in range(2, 12):                      # 이미지 10장
        ctx.save_directory_state["save_counter"] = n
        ctx.save_remote_ui_state()
    assert p.stat().st_mtime_ns == before, "카운터만 바뀌었는데 파일을 다시 썼다"


def test_real_user_settings_file_recovers(tmp_path):
    """사용자 실제 파일로 재현한다. 없으면 건너뛴다(개발 머신 전용 경로)."""
    real = ROOT / "NAIA-Portable" / "user-data" / "save" / "app_settings.json"
    if not real.exists():
        pytest.skip("포터블 설정 파일이 없다")
    raw = json.loads(real.read_text(encoding="utf-8"))
    stored = ((raw.get("remote_web") or {}).get("save_directory_state") or {})
    if "save_counter" not in stored:
        pytest.skip("이미 청소된 파일이다")
    (tmp_path / "app_settings.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    ctx = _Ctx(tmp_path, counter=1)
    svc.apply_remote_ui_state(ctx)
    assert ctx.save_directory_state["save_counter"] == 1, "복원이 옛 번호를 물고 왔다"
    ctx.save_remote_ui_state()
    assert "save_counter" not in _stored_sd(ctx)
