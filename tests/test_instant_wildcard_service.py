from types import SimpleNamespace

from core.instant_wildcard_service import (
    apply_instant_wildcards_to_context,
    load_instant_wildcards,
    write_instant_wildcard_file,
)


class _WildcardManager:
    def __init__(self):
        self.instant_wildcard_dict = {}
        self.instant_wildcard_tree = {}

    def update_instant_wildcards(self, instant_dict, instant_tree=None):
        self.instant_wildcard_dict = dict(instant_dict)
        self.instant_wildcard_tree = dict(instant_tree or {})


def test_load_instant_wildcards_creates_defaults_and_keeps_default_first(tmp_path):
    store = load_instant_wildcards(tmp_path)

    assert "default.json" in store["json_data"]
    assert next(iter(store["json_data"].keys())) == "default.json"
    assert store["instant_wildcard_dict"]["quality"] == "masterpiece, best quality"
    assert store["instant_wildcard_tree"]["default"]["negative"] == "lowres, bad anatomy, bad hands"


def test_load_instant_wildcards_suffixes_duplicate_non_default_keys(tmp_path):
    (tmp_path / "default.json").write_text('{"pose": "standing"}', encoding="utf-8")
    (tmp_path / "group.json").write_text('{"pose": "sitting"}', encoding="utf-8")

    store = load_instant_wildcards(tmp_path)

    assert store["instant_wildcard_dict"]["pose"] == "standing"
    assert store["instant_wildcard_dict"]["pose (group)"] == "sitting"
    assert store["instant_wildcard_tree"]["group"] == {"pose": "sitting"}


def test_write_instant_wildcard_file_persists_json_data(tmp_path):
    json_data = {"custom.json": {"hero": "1girl, sword"}}

    assert write_instant_wildcard_file(json_data, "custom", tmp_path) is True

    store = load_instant_wildcards(tmp_path, create_defaults=False)
    assert store["json_data"]["custom.json"] == {"hero": "1girl, sword"}


def test_apply_instant_wildcards_to_context_updates_wildcard_manager(tmp_path):
    (tmp_path / "default.json").write_text('{"chunk": "tag"}', encoding="utf-8")
    manager = _WildcardManager()
    context = SimpleNamespace(wildcard_manager=manager)

    store = apply_instant_wildcards_to_context(context, tmp_path)

    assert context.instant_wildcard_store is store
    assert manager.instant_wildcard_dict == {"chunk": "tag"}
    assert manager.instant_wildcard_tree == {"default": {"chunk": "tag"}}
