import pandas as pd

from core.search_result_model import SearchResultModel


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
