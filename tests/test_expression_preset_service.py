import json
from pathlib import Path

import pytest

from core.expression_preset_service import CATALOG_RELATIVE_PATH, ExpressionPresetService
from tools.export_expression_preset_catalog import export_catalog, load_static_taxonomy


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_expression_service_reads_json_catalog(tmp_path):
    catalog_path = tmp_path / CATALOG_RELATIVE_PATH
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(
        json.dumps({
            "version": 1,
            "counts": {
                "sourceRows": 3,
                "rowsWithTaxonomyTags": 3,
                "rowsWithExpressionTags": 2,
                "expressionCombos": 2,
                "expressionTags": 3,
                "staticTags": 4,
                "noiseTagsRemoved": 1,
                "flattenedRows": 1,
            },
            "coverage": {
                "taxonomyTags": 4,
                "catalogTags": 3,
                "coveredTags": 2,
                "missingTags": 2,
                "noiseTags": 1,
                "extraTags": 1,
                "coverageRatio": 0.5,
                "missingTagList": ["closed mouth", "open mouth"],
                "extraTagList": ["sparkle eyes"],
                "byGroup": [
                    {
                        "id": "smile",
                        "label": "smile",
                        "total": 2,
                        "covered": 1,
                        "missing": 1,
                        "coverageRatio": 0.5,
                        "missingTags": ["closed mouth"],
                    },
                ],
            },
            "categories": [
                {
                    "id": "smile",
                    "label": "smile",
                    "count": 2,
                    "subcategories": [
                        {
                            "id": "smile-combo",
                            "label": "Expression Combos",
                            "count": 2,
                            "items": [
                                {"id": "expr-1", "label": "smile", "tags": ["smile"]},
                                {"id": "expr-2", "label": "blush, smile", "tags": ["blush", "smile"]},
                            ],
                        },
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )

    service = ExpressionPresetService(tmp_path)

    assert service.status()["dataAvailability"]["main"] == "ready"
    payload = service.bootstrap({"limit": 1})
    assert payload["counts"]["expressionCombos"] == 2
    assert payload["counts"]["flattenedRows"] == 1
    assert payload["coverage"]["coverageRatio"] == 0.5
    assert payload["coverage"]["noiseTags"] == 1
    assert payload["coverage"]["byGroup"][0]["covered"] == 1
    assert "missingTagList" not in payload["coverage"]
    assert payload["categories"][0]["count"] == 1
    assert payload["categories"][0]["subcategories"][0]["items"][0]["tags"] == ["smile"]


def test_expression_service_default_limit_keeps_later_categories(tmp_path):
    catalog_path = tmp_path / CATALOG_RELATIVE_PATH
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(
        json.dumps({
            "version": 1,
            "counts": {"expressionCombos": 4},
            "categories": [
                {
                    "id": "cheerful",
                    "label": "Cheerful",
                    "count": 3,
                    "subcategories": [
                        {
                            "id": "cheerful-face",
                            "label": "Face / Blush",
                            "count": 3,
                            "items": [
                                {"id": "expr-1", "label": "blush, smile", "tags": ["blush", "smile"]},
                                {"id": "expr-2", "label": "smile", "tags": ["smile"]},
                                {"id": "expr-3", "label": ":d, smile", "tags": [":d", "smile"]},
                            ],
                        },
                    ],
                },
                {
                    "id": "sad",
                    "label": "Sad / Tearful",
                    "count": 1,
                    "subcategories": [
                        {
                            "id": "sad-tears",
                            "label": "Tears",
                            "count": 1,
                            "items": [
                                {"id": "expr-4", "label": "tears", "tags": ["tears"]},
                            ],
                        },
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )

    payload = ExpressionPresetService(tmp_path).bootstrap()

    assert [category["id"] for category in payload["categories"]] == ["cheerful", "sad"]
    assert sum(category["count"] for category in payload["categories"]) == 4


def test_expression_service_preserves_overflow_items_and_total_counts(tmp_path):
    catalog_path = tmp_path / CATALOG_RELATIVE_PATH
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(
        json.dumps({
            "version": 2,
            "counts": {"expressionCombos": 3},
            "categories": [
                {
                    "id": "cheerful",
                    "label": "Cheerful",
                    "count": 3,
                    "subcategories": [
                        {
                            "id": "cheerful-expression",
                            "label": "Expression",
                            "count": 3,
                            "items": [
                                {"id": "expr-1", "label": "smile", "tags": ["smile"]},
                            ],
                            "moreItems": [
                                {"id": "expr-2", "label": "grin", "tags": ["grin"]},
                                {"id": "expr-3", "label": "happy", "tags": ["happy"]},
                            ],
                            "moreCount": 2,
                        },
                    ],
                },
            ],
        }),
        encoding="utf-8",
    )

    payload = ExpressionPresetService(tmp_path).bootstrap()
    subcategory = payload["categories"][0]["subcategories"][0]

    assert payload["categories"][0]["count"] == 3
    assert subcategory["count"] == 3
    assert [item["id"] for item in subcategory["items"]] == ["expr-1"]
    assert [item["id"] for item in subcategory["moreItems"]] == ["expr-2", "expr-3"]
    assert subcategory["moreCount"] == 2

    limited = ExpressionPresetService(tmp_path).bootstrap({"limit": 2})
    limited_subcategory = limited["categories"][0]["subcategories"][0]

    assert limited["categories"][0]["count"] == 2
    assert limited_subcategory["count"] == 2
    assert [item["id"] for item in limited_subcategory["items"]] == ["expr-1"]
    assert [item["id"] for item in limited_subcategory["moreItems"]] == ["expr-2"]
    assert limited_subcategory["moreCount"] == 1


def test_expression_exporter_filters_general_tags_and_flattens_noise(tmp_path):
    pytest.importorskip("pyarrow")

    write_taxonomy(tmp_path)
    write_source_parquet(tmp_path)

    catalog = export_catalog(tmp_path, min_tag_count=1, min_combo_count=1)

    assert catalog["source"] == "custom-general-expression-json-export"
    assert catalog["dataset"] == "custom_1girl_solo_general_expression"
    assert catalog["scope"]["person"] == "1girl_solo"
    assert catalog["scope"]["sourceColumn"] == "general"
    assert catalog["counts"]["sourceRows"] == 3
    assert catalog["counts"]["rowsWithTaxonomyTags"] == 3
    assert catalog["counts"]["rowsWithExpressionTags"] == 3
    assert catalog["counts"]["expressionCombos"] == 2
    assert catalog["counts"]["expressionTags"] == 2
    assert catalog["counts"]["noiseTagsRemoved"] == 3
    assert catalog["counts"]["flattenedRows"] == 3
    assert catalog["counts"]["deduplicatedRows"] == 0
    assert catalog["counts"]["decoratedRows"] == 3
    assert catalog["coverage"]["taxonomyTags"] == 5
    assert catalog["coverage"]["coveredTags"] == 2
    assert catalog["coverage"]["noiseTags"] == 3
    assert catalog["coverage"]["missingTagList"] == []

    cheerful_items = items_for_category(catalog, "cheerful")
    assert [item["label"] for item in cheerful_items] == ["smile, blush"]
    assert cheerful_items[0]["count"] == 2
    assert cheerful_items[0]["tags"] == ["smile", "blush"]
    assert cheerful_items[0]["coreTags"] == ["smile"]
    assert cheerful_items[0]["decoratorTags"] == ["blush"]
    assert cheerful_items[0]["subcategoryId"] == "expression"

    surprised_items = items_for_category(catalog, "surprised")
    assert [item["label"] for item in surprised_items] == ["?, open mouth"]
    assert surprised_items[0]["coreTags"] == ["?"]
    assert surprised_items[0]["decoratorTags"] == ["open mouth"]
    assert surprised_items[0]["subcategoryId"] == "emoticon"

    noise_tags = {row["tag"]: row["reason"] for row in catalog["quality"]["noiseTags"]}
    assert noise_tags == {
        "blush": "non-expression-modifier",
        "open mouth": "low-signal-modifier",
        "speech bubble": "non-expression",
    }
    assert catalog["semanticCoverage"]["totalTags"] == 2
    assert catalog["semanticCoverage"]["totalComboItems"] == 2


def test_expression_exporter_filters_singleton_combos(tmp_path):
    pytest.importorskip("pyarrow")

    write_taxonomy(tmp_path)
    write_source_parquet(tmp_path)

    catalog = export_catalog(tmp_path, min_tag_count=1, min_combo_count=2)

    assert catalog["counts"]["minComboCount"] == 2
    assert catalog["quality"]["minComboCount"] == 2
    assert catalog["counts"]["expressionCombos"] == 1
    assert catalog["counts"]["expressionTags"] == 1
    assert catalog["counts"]["lowCountCombosRemoved"] == 1
    assert catalog["counts"]["lowCountComboRowsRemoved"] == 1
    assert [item["label"] for item in items_for_category(catalog, "cheerful")] == ["smile, blush"]

    noise_tags = {row["tag"]: row["reason"] for row in catalog["quality"]["noiseTags"]}
    assert noise_tags["?"] == "singleton-only-combo"
    assert catalog["coverage"]["coveredTags"] == 1
    assert catalog["coverage"]["noiseTags"] == 4


def test_generated_expression_catalog_matches_expression_tags_coverage():
    catalog_path = REPO_ROOT / CATALOG_RELATIVE_PATH
    taxonomy_path = REPO_ROOT / "data" / "taglist" / "expression_tags.json"
    if not catalog_path.exists():
        pytest.skip(f"generated expression catalog is missing: {catalog_path}")

    taxonomy = load_static_taxonomy(REPO_ROOT)
    taxonomy_tags = taxonomy["all_tags"]
    taxonomy_groups = taxonomy["groups"]
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    tag_counts = {row["tag"]: int(row["count"]) for row in catalog.get("tagCounts") or []}
    noise_tags = {row["tag"]: row for row in catalog.get("quality", {}).get("noiseTags") or []}
    coverage = catalog.get("coverage") or {}
    counts = catalog.get("counts") or {}
    source_seen_tags = set(tag_counts) | set(noise_tags)
    min_combo_count = int(catalog.get("quality", {}).get("minComboCount") or 1)

    assert counts["staticTags"] == len(taxonomy_tags)
    assert counts["expressionTags"] == len(tag_counts)
    assert counts["noiseTagsRemoved"] == len(noise_tags)
    assert counts["minComboCount"] == min_combo_count
    assert coverage["taxonomyTags"] == len(taxonomy_tags)
    assert coverage["sourceSeenTags"] == len(source_seen_tags)
    assert coverage["catalogTags"] == len(tag_counts)
    assert coverage["coveredTags"] == len(tag_counts)
    assert coverage["noiseTags"] == len(noise_tags)
    assert coverage["missingTags"] == len(taxonomy_tags - source_seen_tags)
    assert coverage["missingTagList"] == sorted(taxonomy_tags - source_seen_tags)
    assert coverage["coverageRatio"] == pytest.approx(len(tag_counts) / len(taxonomy_tags))
    assert set(tag_counts).issubset(taxonomy_tags)
    assert set(noise_tags).issubset(taxonomy_tags)
    assert not (set(tag_counts) & set(noise_tags))
    assert "?" in tag_counts
    assert "?" not in noise_tags

    category_tags = set()
    for category in catalog.get("categories") or []:
        for subcategory in category.get("subcategories") or []:
            for item in subcategory.get("items") or []:
                assert int(item.get("count") or 0) >= min_combo_count
                category_tags.update(item.get("coreTags") or [])
            for item in subcategory.get("moreItems") or []:
                assert int(item.get("count") or 0) >= min_combo_count
                category_tags.update(item.get("coreTags") or [])
    assert category_tags == set(tag_counts)

    semantic_coverage = catalog.get("semanticCoverage") or {}
    assert semantic_coverage["totalTags"] == len(tag_counts)
    assert semantic_coverage["totalComboItems"] == sum(category["count"] for category in catalog.get("categories") or [])
    semantic_categories = {row["id"]: row for row in semantic_coverage.get("byCategory") or []}
    assert semantic_categories
    assert set(semantic_categories) == {category["id"] for category in catalog.get("categories") or []}
    for category in catalog.get("categories") or []:
        semantic_row = semantic_categories[category["id"]]
        assert semantic_row["comboItems"] == category["count"]
        focus_combo_counts = {
            str(subcategory["id"]).removeprefix(f"{category['id']}-"): subcategory["count"]
            for subcategory in category.get("subcategories") or []
        }
        semantic_focus = {row["id"]: row for row in semantic_row.get("byFocus") or []}
        assert semantic_focus
        for focus_id, count in focus_combo_counts.items():
            assert semantic_focus[focus_id]["comboItems"] == count

    by_group = {row["id"]: row for row in coverage.get("byGroup") or []}
    assert set(by_group) == {group["id"] for group in taxonomy_groups}
    for group in taxonomy_groups:
        row = by_group[group["id"]]
        group_tags = set(group["tags"])
        covered = group_tags & set(tag_counts)
        noise = group_tags & set(noise_tags)
        missing = group_tags - source_seen_tags
        assert row["total"] == len(group_tags)
        assert row["covered"] == len(covered)
        assert row["noise"] == len(noise)
        assert row["missing"] == len(missing)
        assert row["coverageRatio"] == pytest.approx(len(covered) / len(group_tags))


def write_taxonomy(root: Path) -> None:
    taxonomy_dir = root / "data" / "taglist"
    taxonomy_dir.mkdir(parents=True)
    (taxonomy_dir / "expression_tags.json").write_text(
        json.dumps({
            "version": 1,
            "modifiers": ["blush"],
            "groups": {
                "smile": ["smile"],
                "physical": ["open mouth", "speech bubble"],
            },
            "tags": ["?"],
        }),
        encoding="utf-8",
    )


def write_source_parquet(root: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.table({
        "general": [
            "1girl, blush, smile, speech bubble",
            "1girl, blush, smile",
            "1girl, open mouth, ?",
        ],
    })
    source_dir = root / "save" / "custom_tags"
    source_dir.mkdir(parents=True)
    pq.write_table(table, source_dir / "1girl_solo_only.parquet")


def items_for_category(catalog: dict, category_id: str) -> list[dict]:
    for category in catalog["categories"]:
        if category["id"] == category_id:
            return category["subcategories"][0]["items"]
    raise AssertionError(f"missing category: {category_id}")
