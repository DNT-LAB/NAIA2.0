from core.tag_relation_ranker import TagRelationRanker


def test_relation_ranker_filters_word_match_noise():
    records = {
        "panties under pantyhose": {
            "_tag": "panties under pantyhose",
            "freq": 17066,
            "group": "Clothing_Wear",
            "subgroup": "panties",
            "relations": {
                "parent": "pantyhose",
                "word_match": [
                    "mole under eye",
                    "black panties",
                    "no panties",
                    "mole under mouth",
                    "bow panties",
                    "side-tie panties",
                    "thighband pantyhose",
                    "under-rim eyewear",
                    "fishnet pantyhose",
                    "bags under eyes",
                ],
            },
        },
        "black panties": {"_tag": "black panties", "freq": 89897, "group": "Clothing_Wear", "subgroup": "panties"},
        "no panties": {"_tag": "no panties", "freq": 200000, "group": "Clothing_Wear", "subgroup": "panties"},
        "bow panties": {"_tag": "bow panties", "freq": 12000, "group": "Clothing_Wear", "subgroup": "panties"},
        "side-tie panties": {"_tag": "side-tie panties", "freq": 9000, "group": "Clothing_Wear", "subgroup": "panties"},
        "thighband pantyhose": {"_tag": "thighband pantyhose", "freq": 20742, "group": "Clothing_Wear", "subgroup": "legwear"},
        "fishnet pantyhose": {"_tag": "fishnet pantyhose", "freq": 40000, "group": "Clothing_Wear", "subgroup": "legwear"},
        "mole under eye": {"_tag": "mole under eye", "freq": 95260, "group": "Person_Body", "subgroup": "face_tags"},
        "mole under mouth": {"_tag": "mole under mouth", "freq": 20000, "group": "Person_Body", "subgroup": "face_tags"},
        "under-rim eyewear": {"_tag": "under-rim eyewear", "freq": 18300, "group": "Clothing_Wear", "subgroup": "eyewear"},
        "bags under eyes": {"_tag": "bags under eyes", "freq": 13673, "group": "Person_Body", "subgroup": "eyes_tags"},
    }

    related = TagRelationRanker(records).rank_related(
        "panties under pantyhose",
        records["panties under pantyhose"],
        limit=8,
    )

    assert "black panties" in related
    assert "no panties" in related
    assert "fishnet pantyhose" in related
    assert "thighband pantyhose" in related
    assert "mole under eye" not in related
    assert "mole under mouth" not in related
    assert "under-rim eyewear" not in related
    assert "bags under eyes" not in related


def test_relation_ranker_prefers_children_before_broad_siblings():
    records = {
        "pantyhose": {
            "_tag": "pantyhose",
            "freq": 302440,
            "group": "Clothing_Wear",
            "subgroup": "legwear",
            "relations": {
                "children": ["panties under pantyhose", "fishnet pantyhose"],
                "siblings": ["socks", "thighhighs"],
            },
        },
        "panties under pantyhose": {"_tag": "panties under pantyhose", "freq": 17066, "group": "Clothing_Wear", "subgroup": "panties"},
        "fishnet pantyhose": {"_tag": "fishnet pantyhose", "freq": 40000, "group": "Clothing_Wear", "subgroup": "legwear"},
        "socks": {"_tag": "socks", "freq": 500000, "group": "Clothing_Wear", "subgroup": "legwear"},
        "thighhighs": {"_tag": "thighhighs", "freq": 450000, "group": "Clothing_Wear", "subgroup": "legwear"},
    }

    related = TagRelationRanker(records).rank_related("pantyhose", records["pantyhose"], limit=4)

    assert related[:2] == ["fishnet pantyhose", "panties under pantyhose"]
