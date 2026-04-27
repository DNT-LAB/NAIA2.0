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


def test_relation_ranker_suppresses_count_sibling_noise():
    records = {
        "solo": {
            "_tag": "solo",
            "freq": 2748259,
            "group": "Composition_Meta",
            "subgroup": "count",
            "relations": {
                "children": ["solo focus", "princess leia organa solo (cosplay)"],
                "siblings": ["1girl", "multiple girls", "1boy", "2girls", "multiple boys", "2boys"],
            },
        },
        "solo focus": {
            "_tag": "solo focus",
            "freq": 204833,
            "group": "Composition_Meta",
            "subgroup": "focus",
        },
        "princess leia organa solo (cosplay)": {
            "_tag": "princess leia organa solo (cosplay)",
            "freq": 87,
            "group": "Clothing_Wear",
            "subgroup": "attire",
        },
        "1girl": {"_tag": "1girl", "freq": 3302760, "group": "Composition_Meta", "subgroup": "count"},
        "multiple girls": {"_tag": "multiple girls", "freq": 712811, "group": "Composition_Meta", "subgroup": "count"},
        "1boy": {"_tag": "1boy", "freq": 704526, "group": "Composition_Meta", "subgroup": "count"},
        "2girls": {"_tag": "2girls", "freq": 480614, "group": "Composition_Meta", "subgroup": "count"},
        "multiple boys": {"_tag": "multiple boys", "freq": 202713, "group": "Composition_Meta", "subgroup": "count"},
        "2boys": {"_tag": "2boys", "freq": 131875, "group": "Composition_Meta", "subgroup": "count"},
    }

    related = TagRelationRanker(records).rank_related("solo", records["solo"], limit=8)

    assert related == ["solo focus"]
    assert "princess leia organa solo (cosplay)" not in related
    assert "2girls" not in related
    assert "1boy" not in related


def test_relation_ranker_filters_generic_word_match_tokens():
    records = {
        "multiple views": {
            "_tag": "multiple views",
            "freq": 96886,
            "group": "Composition_Meta",
            "subgroup": "image_composition",
            "relations": {
                "siblings": ["multiple others"],
                "word_match": ["multiple girls", "multiple boys", "multiple tails"],
            },
        },
        "multiple others": {"_tag": "multiple others", "freq": 20300, "group": "Composition_Meta", "subgroup": "image_composition"},
        "multiple girls": {"_tag": "multiple girls", "freq": 712811, "group": "Composition_Meta", "subgroup": "count"},
        "multiple boys": {"_tag": "multiple boys", "freq": 202713, "group": "Composition_Meta", "subgroup": "count"},
        "multiple tails": {"_tag": "multiple tails", "freq": 10131, "group": "Person_Body", "subgroup": "tails"},
        "w": {
            "_tag": "w",
            "freq": 21316,
            "group": "Expression_Action",
            "subgroup": "gesture",
            "relations": {"word_match": ["wet hair", "white capelet"]},
        },
        "wet hair": {"_tag": "wet hair", "freq": 10663, "group": "Person_Body", "subgroup": "hair"},
        "white capelet": {"_tag": "white capelet", "freq": 10524, "group": "Clothing_Wear", "subgroup": "attire"},
    }
    ranker = TagRelationRanker(records)

    multiple_related = ranker.rank_related("multiple views", records["multiple views"], limit=8)
    assert "multiple girls" not in multiple_related
    assert "multiple boys" not in multiple_related
    assert "multiple others" not in multiple_related
    assert "multiple tails" not in multiple_related

    assert ranker.rank_related("w", records["w"], limit=8) == []


def test_relation_ranker_filters_cross_axis_children_but_keeps_same_group_children():
    records = {
        "hetero": {
            "_tag": "hetero",
            "freq": 83229,
            "group": "NSFW",
            "subgroup": "sex_acts",
            "relations": {"children": ["heterochromia"]},
        },
        "heterochromia": {"_tag": "heterochromia", "freq": 63478, "group": "Person_Body", "subgroup": "eyes"},
        "scar": {
            "_tag": "scar",
            "freq": 148980,
            "group": "Person_Body",
            "subgroup": "body_parts",
            "relations": {"children": ["scar on face"]},
        },
        "scar on face": {"_tag": "scar on face", "freq": 34208, "group": "Person_Body", "subgroup": "face_tags"},
        "sweat": {
            "_tag": "sweat",
            "freq": 111111,
            "group": "Expression_Action",
            "subgroup": "pose",
            "relations": {"children": ["sweatdrop", "sweater lift"]},
        },
        "sweatdrop": {"_tag": "sweatdrop", "freq": 33411, "group": "Expression_Action", "subgroup": "expression"},
        "sweater lift": {
            "_tag": "sweater lift",
            "freq": 16751,
            "group": "Expression_Action",
            "subgroup": "clothing_action",
        },
    }
    ranker = TagRelationRanker(records)

    assert ranker.rank_related("hetero", records["hetero"], limit=8) == []
    assert ranker.rank_related("scar", records["scar"], limit=8) == ["scar on face"]
    assert ranker.rank_related("sweat", records["sweat"], limit=8) == ["sweatdrop"]


def test_relation_ranker_requires_meaningful_overlap_for_word_match():
    records = {
        "black skirt": {
            "_tag": "black skirt",
            "freq": 100000,
            "group": "Clothing_Wear",
            "subgroup": "attire",
            "relations": {
                "word_match": [
                    "pleated skirt",
                    "black dress",
                    "black jacket",
                    "black shirt",
                ],
            },
        },
        "pleated skirt": {
            "_tag": "pleated skirt",
            "freq": 90000,
            "group": "Clothing_Wear",
            "subgroup": "attire",
        },
        "black dress": {
            "_tag": "black dress",
            "freq": 80000,
            "group": "Clothing_Wear",
            "subgroup": "attire",
        },
        "black jacket": {
            "_tag": "black jacket",
            "freq": 70000,
            "group": "Clothing_Wear",
            "subgroup": "attire",
        },
        "black shirt": {
            "_tag": "black shirt",
            "freq": 60000,
            "group": "Clothing_Wear",
            "subgroup": "attire",
        },
    }

    related = TagRelationRanker(records).rank_related("black skirt", records["black skirt"], limit=8)

    assert related == ["pleated skirt"]


def test_relation_ranker_suppresses_single_token_word_match_from_broad_areas():
    records = {
        "plaid skirt": {
            "_tag": "plaid skirt",
            "freq": 52180,
            "group": "Clothing_Wear",
            "subgroup": "patterns",
            "relations": {
                "parent": "skirt",
                "word_match": [
                    "pleated skirt",
                    "black skirt",
                    "red skirt",
                    "skirt lift",
                ],
            },
        },
        "skirt": {"_tag": "skirt", "group": "Clothing_Wear", "subgroup": "attire"},
        "pleated skirt": {"_tag": "pleated skirt", "group": "Clothing_Wear", "subgroup": "attire"},
        "black skirt": {"_tag": "black skirt", "group": "Clothing_Wear", "subgroup": "attire"},
        "red skirt": {"_tag": "red skirt", "group": "Clothing_Wear", "subgroup": "attire"},
        "skirt lift": {
            "_tag": "skirt lift",
            "group": "Expression_Action",
            "subgroup": "clothing_action",
        },
    }

    related = TagRelationRanker(records).rank_related("plaid skirt", records["plaid skirt"], limit=8)

    assert related == []
