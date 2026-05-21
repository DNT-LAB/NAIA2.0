import json
from types import SimpleNamespace

from core.api_service import APIService
from core.runtime_paths import resolve_runtime_paths


class _TokenManager:
    def __init__(self, values):
        self.values = dict(values)

    def get_token(self, key):
        return self.values.get(key, "")


def test_nai_multi_account_file_uses_runtime_save_dir(tmp_path):
    runtime_paths = resolve_runtime_paths(tmp_path / "repo", env={}, portable=True)
    runtime_paths.save_dir.mkdir(parents=True)
    (runtime_paths.save_dir / "nai_accounts.json").write_text(
        json.dumps({
            "round_robin_enabled": False,
            "main_account_enabled": False,
            "accounts": [{"id": "alt_token", "enabled": True}],
        }),
        encoding="utf-8",
    )
    context = SimpleNamespace(
        runtime_paths=runtime_paths,
        secure_token_manager=_TokenManager({
            "nai_token": "pst-main",
            "alt_token": "pst-alt",
        }),
    )
    service = APIService(context)

    assert service._get_active_nai_token() == "pst-alt"
    assert not (tmp_path / "repo" / "save" / "nai_accounts.json").exists()
