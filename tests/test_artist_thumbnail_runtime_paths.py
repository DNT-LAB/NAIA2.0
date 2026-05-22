import json

from core.artist_thumbnail_service import ArtistThumbnailService


def test_artist_thumbnail_service_prefers_runtime_mode_data_root(tmp_path):
    runtime_root = tmp_path / "user-data" / "ui_assets" / "artist_thumb"
    runtime_root.mkdir(parents=True)
    (runtime_root / "artist_thumbnail_nai.json").write_text(
        json.dumps({"runtime_artist": ["thumb"]}),
        encoding="utf-8",
    )
    legacy_path = tmp_path / "data" / "artist_thumbnail_nai.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps({"legacy_artist": ["thumb"]}), encoding="utf-8")

    service = ArtistThumbnailService(tmp_path, mode_data_root=runtime_root)

    assert service._mode_path("NAID4.5F-31000") == runtime_root / "artist_thumbnail_nai.json"
    assert service.load_data("NAID4.5F-31000") == {"runtime_artist": ["thumb"]}


def test_artist_thumbnail_service_reads_legacy_mode_data_until_downloaded_runtime_copy_exists(tmp_path):
    runtime_root = tmp_path / "user-data" / "ui_assets" / "artist_thumb"
    legacy_path = tmp_path / "data" / "artist_thumbnail_nai.json"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps({"legacy_artist": ["thumb"]}), encoding="utf-8")

    service = ArtistThumbnailService(tmp_path, mode_data_root=runtime_root)

    assert service._mode_path("NAID4.5F-31000") == legacy_path
    assert service.load_data("NAID4.5F-31000") == {"legacy_artist": ["thumb"]}
    assert service._mode_download_path(service._mode_info("NAID4.5F-31000")) == (
        runtime_root / "artist_thumbnail_nai.json"
    )


def test_artist_thumbnail_service_writes_state_to_runtime_roots_with_legacy_fallback(tmp_path):
    runtime_state_root = tmp_path / "user-data" / "ui_assets" / "artist_thumb"
    runtime_wildcards_root = tmp_path / "user-data" / "wildcards"
    legacy_favorite = tmp_path / "wildcards" / "favorite_artist.txt"
    legacy_favorite.parent.mkdir(parents=True)
    legacy_favorite.write_text("legacy_favorite\n", encoding="utf-8")
    legacy_banned = tmp_path / "artist_thumb" / "banned_artist.txt"
    legacy_banned.parent.mkdir(parents=True)
    legacy_banned.write_text("legacy_banned\n", encoding="utf-8")

    service = ArtistThumbnailService(
        tmp_path,
        mode_data_root=runtime_state_root,
        state_root=runtime_state_root,
        wildcards_root=runtime_wildcards_root,
    )

    state_path = runtime_state_root / "artist_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["favorites"] == ["legacy_favorite"]
    assert state["banned"] == ["legacy_banned"]
    assert (runtime_wildcards_root / "favorite_artist.txt").read_text(encoding="utf-8") == "legacy_favorite\n"
    assert (runtime_state_root / "banned_artist.txt").read_text(encoding="utf-8") == "legacy_banned\n"


def test_artist_thumbnail_service_uses_mode_data_when_artist_dictionary_is_not_shipped(tmp_path, capsys):
    data_path = tmp_path / "data" / "artist_thumbnail_nai.json"
    data_path.parent.mkdir(parents=True)
    data_path.write_text(
        json.dumps({"artist_alpha": ["thumb-a"], "artist_beta": ["thumb-b"]}),
        encoding="utf-8",
    )

    service = ArtistThumbnailService(tmp_path)
    payload = service.build_list("NAID4.5F-31000", per_page=12)

    assert payload["total"] == 2
    assert [item["artist"] for item in payload["items"]] == ["artist_alpha", "artist_beta"]
    assert "artist dictionary load failed" not in capsys.readouterr().out


def test_artist_thumbnail_service_loads_optional_artist_dictionary_from_repo_root(tmp_path):
    (tmp_path / "artist_dictionary.py").write_text(
        "artist_dict = {'artist_zeta': 42}\n",
        encoding="utf-8",
    )

    service = ArtistThumbnailService(tmp_path)
    state = service.state()

    assert state["artist_count"] == 1
    assert state["filters"][0]["count"] == 1
