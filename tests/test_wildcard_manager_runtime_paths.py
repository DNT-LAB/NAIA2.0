from pathlib import Path

from core.wildcard_manager import WildcardManager


def test_wildcard_manager_uses_user_data_dir_when_available(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    user_data = tmp_path / "user-data"
    (repo / "wildcards").mkdir(parents=True)
    (repo / "wildcards" / "source_only.txt").write_text("source\n", encoding="utf-8")
    (user_data / "wildcards").mkdir(parents=True)
    (user_data / "wildcards" / "runtime_only.txt").write_text("runtime\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("NAIA_USER_DATA_DIR", str(user_data))
    monkeypatch.delenv("NAIA_PORTABLE", raising=False)

    manager = WildcardManager()

    assert Path(manager.wildcards_dir) == (user_data / "wildcards").resolve()
    assert "runtime_only" in manager.wildcard_dict_tree
    assert "source_only" not in manager.wildcard_dict_tree


def test_wildcard_manager_keeps_cwd_default_without_runtime_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "wildcards").mkdir(parents=True)
    (repo / "wildcards" / "source_only.txt").write_text("source\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    monkeypatch.delenv("NAIA_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("NAIA_PORTABLE", raising=False)

    manager = WildcardManager()

    assert Path(manager.wildcards_dir) == (repo / "wildcards").resolve()
    assert "source_only" in manager.wildcard_dict_tree


def test_wildcard_manager_explicit_dir_overrides_runtime_env(tmp_path, monkeypatch):
    user_data = tmp_path / "user-data"
    explicit = tmp_path / "explicit-wildcards"
    (user_data / "wildcards").mkdir(parents=True)
    (user_data / "wildcards" / "runtime_only.txt").write_text("runtime\n", encoding="utf-8")
    explicit.mkdir()
    (explicit / "explicit_only.txt").write_text("explicit\n", encoding="utf-8")
    monkeypatch.setenv("NAIA_USER_DATA_DIR", str(user_data))

    manager = WildcardManager(wildcards_dir=explicit)

    assert Path(manager.wildcards_dir) == explicit.resolve()
    assert "explicit_only" in manager.wildcard_dict_tree
    assert "runtime_only" not in manager.wildcard_dict_tree
