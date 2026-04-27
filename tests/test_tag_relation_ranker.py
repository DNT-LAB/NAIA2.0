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


def test_relation_ranker_validates_parent_implications():
    records = {
        "panties under pantyhose": {
            "_tag": "panties under pantyhose",
            "relations": {"parent": "pantyhose"},
        },
        "pantyhose": {"_tag": "pantyhose"},
        "open arms": {"_tag": "open arms", "relations": {"parent": "pen"}},
        "pen": {"_tag": "pen"},
        "brazil": {"_tag": "brazil", "relations": {"parent": "bra"}},
        "no bra": {"_tag": "no bra", "relations": {"parent": "bra"}},
        "bra": {"_tag": "bra"},
        "lungmen dollar": {"_tag": "lungmen dollar", "relations": {"parent": "doll"}},
        "doll": {"_tag": "doll"},
    }
    ranker = TagRelationRanker(records)

    assert ranker.valid_implications("panties under pantyhose", records["panties under pantyhose"]) == ["pantyhose"]
    assert ranker.valid_implications("no bra", records["no bra"]) == ["bra"]
    assert ranker.valid_implications("open arms", records["open arms"]) == []
    assert ranker.valid_implications("brazil", records["brazil"]) == []
    assert ranker.valid_implications("lungmen dollar", records["lungmen dollar"]) == []


def test_relation_ranker_suppresses_broad_siblings_for_wide_subgroups():
    records = {
        "torn swimsuit": {
            "_tag": "torn swimsuit",
            "freq": 701,
            "group": "Clothing_Wear",
            "subgroup": "attire",
            "relations": {
                "parent": "swimsuit",
                "siblings": ["one-piece swimsuit", "shirt", "skirt", "dress"],
            },
        },
        "swimsuit": {"_tag": "swimsuit", "group": "Clothing_Wear", "subgroup": "attire"},
        "one-piece swimsuit": {"_tag": "one-piece swimsuit", "freq": 10000, "group": "Clothing_Wear", "subgroup": "attire"},
        "shirt": {"_tag": "shirt", "freq": 100000, "group": "Clothing_Wear", "subgroup": "attire"},
        "skirt": {"_tag": "skirt", "freq": 90000, "group": "Clothing_Wear", "subgroup": "attire"},
        "dress": {"_tag": "dress", "freq": 80000, "group": "Clothing_Wear", "subgroup": "attire"},
        "confused": {
            "_tag": "confused",
            "freq": 1845,
            "group": "Expression_Action",
            "subgroup": "expression",
            "relations": {"siblings": ["blush", "smile"]},
        },
        "blush": {"_tag": "blush", "freq": 300000, "group": "Expression_Action", "subgroup": "expression"},
        "smile": {"_tag": "smile", "freq": 200000, "group": "Expression_Action", "subgroup": "expression"},
    }
    ranker = TagRelationRanker(records)

    clothing_related = ranker.rank_related("torn swimsuit", records["torn swimsuit"], limit=8)
    assert clothing_related == ["one-piece swimsuit"]

    expression_related = ranker.rank_related("confused", records["confused"], limit=8)
    assert expression_related == ["blush", "smile"]
