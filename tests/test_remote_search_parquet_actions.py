import json
from datetime import datetime

import pandas as pd

from legacy_desktop.core import remote_api_server
from legacy_desktop.core.remote_api_server import RemoteBridge
from core.search_result_model import SearchResultModel


class _Label:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class _MainWindow:
    def __init__(self, df):
        self.search_results = SearchResultModel(df)
        self.result_label1 = _Label()
        self.result_label2 = _Label()
        self.snapshot_count = 0

    def _save_search_snapshot(self):
        self.snapshot_count += 1


class _AppContext:
    def __init__(self, main_window):
        self.main_window = main_window

    def get_api_mode(self):
        return "NAI"


def _bridge(df):
    return RemoteBridge(_AppContext(_MainWindow(df)))


def _df(*ids):
    return pd.DataFrame({
        "id": list(ids),
        "rating": ["s"] * len(ids),
        "general": [f"tag {idx}" for idx in ids],
    })


def test_remote_load_custom_parquet_replaces_results(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    custom_dir = tmp_path / "save" / "custom_tags"
    custom_dir.mkdir(parents=True)
    _df(2, 3).to_parquet(custom_dir / "loaded.parquet", index=False)
    bridge = _bridge(_df(1))

    bridge._do_load_parquet("loaded.parquet")

    result = bridge.app_context.main_window.search_results.get_dataframe()
    assert result["id"].tolist() == [2, 3]
    assert bridge.app_context.main_window.result_label2.text == "남음: 2"
    assert bridge.app_context.main_window.snapshot_count == 1


def test_remote_merge_custom_parquet_appends_results(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    custom_dir = tmp_path / "save" / "custom_tags"
    custom_dir.mkdir(parents=True)
    _df(2, 3).to_parquet(custom_dir / "merge.parquet", index=False)
    bridge = _bridge(_df(1))

    bridge._do_merge_parquet("merge.parquet")

    result = bridge.app_context.main_window.search_results.get_dataframe()
    assert result["id"].tolist() == [1, 2, 3]
    assert bridge.app_context.main_window.result_label2.text == "남음: 3"


def test_remote_uploaded_parquet_replaces_results_and_deletes_temp(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    uploaded_path = tmp_path / "uploaded.parquet"
    _df(5, 6).to_parquet(uploaded_path, index=False)
    bridge = _bridge(_df(1))

    bridge._do_uploaded_parquet(json.dumps({
        "action": "load",
        "filename": "picked.parquet",
        "temp_path": str(uploaded_path),
    }))

    result = bridge.app_context.main_window.search_results.get_dataframe()
    assert result["id"].tolist() == [5, 6]
    assert not uploaded_path.exists()


def test_remote_uploaded_parquet_merge_appends_results(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    uploaded_path = tmp_path / "uploaded.parquet"
    _df(5, 6).to_parquet(uploaded_path, index=False)
    bridge = _bridge(_df(1))

    bridge._do_uploaded_parquet(json.dumps({
        "action": "merge",
        "filename": "picked.parquet",
        "temp_path": str(uploaded_path),
    }))

    result = bridge.app_context.main_window.search_results.get_dataframe()
    assert result["id"].tolist() == [1, 5, 6]
    assert not uploaded_path.exists()


def test_remote_parquet_actions_export_and_save_runner(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    bridge = _bridge(_df(1, 2))

    bridge._do_search_parquet_action('{"action":"export_results","filename":"named_export"}')
    bridge._do_search_parquet_action('{"action":"save_runner"}')

    exported = pd.read_parquet(tmp_path / "save" / "custom_tags" / "named_export.parquet")
    runner = pd.read_parquet(tmp_path / "naia_temp_rows.parquet")
    assert exported["id"].tolist() == [1, 2]
    assert runner["id"].tolist() == [1, 2]


def test_remote_default_export_uses_unique_names_for_same_second(monkeypatch, tmp_path):
    class _FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 5, 5, 1, 2, 3)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(remote_api_server, "datetime", _FixedDateTime)
    bridge = _bridge(_df(1, 2))

    bridge._do_search_parquet_action('{"action":"export_results"}')
    bridge._do_search_parquet_action('{"action":"export_results"}')

    export_dir = tmp_path / "save" / "custom_tags"
    names = sorted(path.name for path in export_dir.glob("search_export_20260505_010203*.parquet"))
    assert names == [
        "search_export_20260505_010203.parquet",
        "search_export_20260505_010203_2.parquet",
    ]


def test_remote_custom_parquet_rejects_path_traversal(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    bridge = _bridge(_df(1))

    bridge._do_load_parquet("../outside.parquet")

    result = bridge.app_context.main_window.search_results.get_dataframe()
    assert result["id"].tolist() == [1]
    assert bridge.app_context.main_window.snapshot_count == 0
