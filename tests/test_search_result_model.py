import pandas as pd
import numpy as np

from core.search_result_model import SearchResultModel


def _set_bucket_starts(monkeypatch, starts):
    monkeypatch.setattr(SearchResultModel, "_bucket_starts_cache", starts)
    monkeypatch.setattr(SearchResultModel, "_bucket_starts_array_cache", np.asarray(starts, dtype=np.int64))


def test_id_bucket_assignment_uses_9000000_as_bucket_135_start(monkeypatch):
    starts = list(range(134))
    starts.append(8932586)
    starts.append(9000000)
    starts.append(9066571)
    starts.append(9132369)
    starts.append(9203411)
    starts.extend(9203411 + (index - 138) * 100000 for index in range(139, 150))
    _set_bucket_starts(monkeypatch, starts)

    model = SearchResultModel(pd.DataFrame([
        {"id": 8999999, "rating": "s", "general": "last bucket 134"},
        {"id": 9000000, "rating": "s", "general": "first bucket 135"},
        {"id": 9199999, "rating": "s", "general": "bucket 137 by id range"},
    ]))

    assert set(model._buckets) == {134, 135, 137}
    assert set(model._buckets[134].df["id"]) == {8999999}
    assert set(model._buckets[135].df["id"]) == {9000000}
    assert set(model._buckets[137].df["id"]) == {9199999}


def test_append_dataframe_keeps_results_in_buckets_without_global_concat(monkeypatch):
    _set_bucket_starts(monkeypatch, [0, 10, 20])
    model = SearchResultModel()

    model.append_dataframe(pd.DataFrame([
        {"id": 1, "rating": "s", "general": "bucket zero"},
        {"id": 10, "rating": "e", "general": "bucket one"},
    ]))
    model.append_dataframe(pd.DataFrame([
        {"id": 20, "rating": "g", "general": "bucket two"},
    ]))

    assert set(model._buckets) == {0, 1, 2}
    assert model.get_count() == 3
    assert model.df.empty
    assert model.get_count_by_rating() == {"g": 1, "s": 1, "q": 0, "e": 1}


def test_pop_random_row_excludes_blank_prompts_without_dropping_them():
    model = SearchResultModel(pd.DataFrame([
        {"id": 1, "rating": "s", "general": "1girl, smile"},
        {"id": 2, "rating": "s", "general": ""},
        {"id": 3, "rating": "q", "general": "nan"},
        {"id": 4, "rating": "e", "general": "solo"},
    ]))

    model.prime_random_cache()

    popped = {model.pop_random_row()["id"] for _ in range(2)}

    assert popped == {1, 4}
    assert model.pop_random_row() is None
    assert model.get_count() == 2


def test_pop_random_row_respects_active_ratings_and_preserves_inactive_rows():
    model = SearchResultModel(pd.DataFrame([
        {"id": 1, "rating": "s", "general": "safe one"},
        {"id": 2, "rating": "q", "general": "questionable one"},
        {"id": 3, "rating": "s", "general": "safe two"},
    ]))

    model.prime_random_cache()

    row = model.pop_random_row({"q"})

    assert row["id"] == 2
    assert model.pop_random_row({"q"}) is None
    assert model.get_count() == 2
    assert set(model.get_dataframe()["id"]) == {1, 3}


def test_pop_random_row_without_rating_column_uses_all_valid_prompts():
    model = SearchResultModel(pd.DataFrame([
        {"id": 1, "general": "first prompt"},
        {"id": 2, "general": "second prompt"},
    ]))

    model.prime_random_cache()

    popped = {model.pop_random_row({"s"})["id"] for _ in range(2)}

    assert popped == {1, 2}
    assert model.get_count() == 0


def test_rating_counts_cache_updates_after_random_pop():
    model = SearchResultModel(pd.DataFrame([
        {"id": 1, "rating": "s", "general": "safe one"},
        {"id": 2, "rating": "s", "general": "safe two"},
        {"id": 3, "rating": "e", "general": "explicit one"},
    ]))

    assert model.get_count_by_rating()["s"] == 2

    model.pop_random_row({"s"})

    assert model.get_count_by_rating()["s"] == 1
    assert model.get_filtered_count({"s", "e"}) == 2
    assert model.get_filtered_count(set()) == 0


def test_pop_random_row_marks_row_consumed_without_rebuilding_dataframe():
    model = SearchResultModel(pd.DataFrame([
        {"id": 1, "rating": "s", "general": "safe one"},
        {"id": 2, "rating": "s", "general": "safe two"},
    ]))
    original_df = model.df

    popped = model.pop_random_row({"s"})

    assert popped is not None
    assert model.df is original_df
    assert len(model.df) == 2
    assert model.get_count() == 1
    assert popped["id"] not in set(model.get_dataframe()["id"])


def test_get_dataframe_invalidates_random_cache_for_direct_mutation():
    model = SearchResultModel(pd.DataFrame([
        {"id": 1, "rating": "s", "general": "safe one"},
        {"id": 2, "rating": "s", "general": "safe two"},
    ]))
    model.prime_random_cache()

    exposed = model.get_dataframe()
    exposed.drop(exposed.index[0], inplace=True)

    row = model.pop_random_row({"s"})

    assert row is not None
    assert row["id"] == 2
    assert model.get_count() == 0
