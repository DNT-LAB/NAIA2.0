import numpy as np
import pandas as pd

from core.search_engine import SearchEngine
from core.search_result_model import SearchResultModel
from tabs.depth_search_window import DepthSearchWindow


def test_ensure_model_tags_string_persists_to_bucketed_model(monkeypatch):
    monkeypatch.setattr(SearchResultModel, "_bucket_starts_cache", [0, 10])
    monkeypatch.setattr(SearchResultModel, "_bucket_starts_array_cache", np.asarray([0, 10], dtype=np.int64))

    window = DepthSearchWindow.__new__(DepthSearchWindow)
    window.search_engine = SearchEngine()
    model = SearchResultModel(pd.DataFrame([
        {"id": 1, "rating": "s", "general": "1girl", "character": None, "copyright": None, "artist": None, "meta": None},
        {"id": 11, "rating": "g", "general": "solo", "character": None, "copyright": None, "artist": None, "meta": None},
    ]))

    DepthSearchWindow._ensure_model_tags_string(window, model)

    result = model.get_dataframe()
    assert set(model._buckets) == {0, 1}
    assert "tags_string" in result.columns
    assert result["tags_string"].tolist() == ["1girl", "solo"]
