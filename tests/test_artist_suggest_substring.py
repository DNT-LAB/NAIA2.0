"""Regression for substring suggestions beyond the old candidate cap."""
from core.artist_affinity import ArtistAffinityPack


def test_suggest_substring_keeps_late_word_matches_and_punctuation(monkeypatch):
    from types import SimpleNamespace
    names = [f"interior ntefragment{i}" for i in range(650)] + [
        "lacrimosa (nte)", "mint (nte)"]
    pack = ArtistAffinityPack()
    monkeypatch.setattr(pack, "_load", lambda: True)
    pack._names = {"character": names}
    pack._lookup = {"character": {name: i for i, name in enumerate(names)}}
    counts = [1000] * 650 + [240, 275]
    monkeypatch.setattr(pack, "_span_of", lambda axis, tid: counts[tid])
    monkeypatch.setattr(pack, "_posting", lambda axis, tid: SimpleNamespace(size=counts[tid]))
    for query in ["nte", "(nte", "nte)"]:
        rows = pack.suggest(query, axis="character", limit=2)
        assert [r["tag"] for r in rows] == ["mint (nte)", "lacrimosa (nte)"]
        assert [r["posts"] for r in rows] == [275, 240]
    assert pack.suggest("nte", axis="copyright") == []
    assert pack.suggest("", axis="character") == []
