import pandas as pd

from core.search_result_model import SearchResultModel


def test_pop_random_row_uses_cached_candidates_and_updates_rating_counts():
    model = SearchResultModel(pd.DataFrame([
        {"general": "alpha", "rating": "s"},
        {"general": "", "rating": "s"},
        {"general": "beta", "rating": "g"},
        {"general": "gamma", "rating": "s"},
    ]))

    model.prime_random_cache([{"s"}])
    first = model.pop_random_row({"s"})
    second = model.pop_random_row({"s"})

    assert {first["general"], second["general"]} == {"alpha", "gamma"}
    assert model.pop_random_row({"s"}) is None
    assert model.get_count_by_rating()["s"] == 1


def test_dataframe_access_invalidates_random_caches_after_external_mutation():
    model = SearchResultModel(pd.DataFrame([
        {"general": "alpha", "rating": "s"},
        {"general": "beta", "rating": "s"},
    ]))
    model.prime_random_cache([{"s"}])

    frame = model.get_dataframe()
    frame.drop(frame.index[0], inplace=True)

    row = model.pop_random_row({"s"})
    assert row["general"] == "beta"
    assert model.is_empty()
