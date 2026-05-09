"""Export the Remote Web Expression Preset JSON catalog from a general-tag parquet."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.expression_preset_service import (  # noqa: E402
    CATALOG_RELATIVE_PATH,
    format_count,
    unique_preserve,
)


SOURCE_RELATIVE_PATH = Path("save") / "custom_tags" / "1girl_solo_only.parquet"
MIN_TAG_COUNT = 5
MIN_COMBO_COUNT = 2
MAX_ITEMS_PER_SUBCATEGORY = 40
EMOTICON_RE = re.compile(r"^[0-9a-z:;=@!?._+\\/\-^><|() ]{1,10}$")
SYMBOL_UNDERSCORE_RE = re.compile(r"^[0-9a-z:;=@!?._+\\/\-^><|()]{1,12}$")

CATEGORY_ORDER: list[tuple[str, str]] = [
    ("cheerful", "Cheerful"),
    ("playful", "Playful / Teasing"),
    ("shy", "Shy / Embarrassed"),
    ("sad", "Sad / Tearful"),
    ("tense", "Tense / Nervous"),
    ("surprised", "Surprised / Questioning"),
    ("angry", "Angry / Frustrated"),
    ("displeased", "Displeased"),
    ("neutral", "Neutral / Stoic"),
    ("sleepy", "Sleepy / Tired"),
    ("intense", "Intense / Altered"),
    ("physical", "Physical Condition"),
    ("other", "Other"),
]
CATEGORY_INDEX = {group_id: index for index, (group_id, _label) in enumerate(CATEGORY_ORDER)}
CATEGORY_LABELS_KO: dict[str, str] = {
    "cheerful":   "밝은 표정",
    "playful":    "장난스러운 표정",
    "shy":        "부끄러운 표정",
    "sad":        "슬픈/눈물 표정",
    "tense":      "긴장된 표정",
    "surprised":  "놀란 표정",
    "angry":      "화난 표정",
    "displeased": "시큰둥한 표정",
    "neutral":    "무표정/담담한 표정",
    "sleepy":     "졸린/지친 표정",
    "intense":    "격앙된 표정",
    "physical":   "신체 반응",
    "other":      "기타",
}

# Consolidated focus axes (12 → 6). Legacy IDs map onto these for both
# semantic_for_tag returns and CATEGORY_FOCUS_ORDER lookups.
FOCUS_ORDER: list[tuple[str, str]] = [
    ("expression", "Expression"),
    ("eyes", "Eyes / Gaze"),
    ("emoticon", "Emoticon"),
    ("tears_sweat", "Tears / Sweat"),
    ("mood_state", "Mood State"),
    ("physical", "Physical"),
]
FOCUS_LABELS = dict(FOCUS_ORDER)
FOCUS_LABELS_KO: dict[str, str] = {
    "expression":  "표정",
    "eyes":        "눈/시선",
    "emoticon":    "이모티콘",
    "tears_sweat": "눈물·땀",
    "mood_state":  "분위기",
    "physical":    "신체",
}
FOCUS_INDEX = {focus_id: index for index, (focus_id, _label) in enumerate(FOCUS_ORDER)}
SUBCATEGORY_INDEX = {
    category_id: FOCUS_INDEX.copy()
    for category_id, _label in CATEGORY_ORDER
}
MOOD_PRIORITY = {category_id: index for index, (category_id, _label) in enumerate(CATEGORY_ORDER)}
DEFAULT_FOCUS_ORDER = ("expression", "eyes", "emoticon", "tears_sweat", "mood_state", "physical")
CATEGORY_FOCUS_ORDER: dict[str, tuple[str, ...]] = {
    "cheerful":   ("expression", "emoticon", "eyes", "tears_sweat", "mood_state", "physical"),
    "playful":    ("expression", "eyes", "emoticon", "tears_sweat", "mood_state", "physical"),
    "shy":        ("expression", "tears_sweat", "eyes", "emoticon", "mood_state", "physical"),
    "sad":        ("tears_sweat", "expression", "eyes", "mood_state", "emoticon", "physical"),
    "tense":      ("expression", "tears_sweat", "eyes", "emoticon", "mood_state", "physical"),
    "surprised":  ("emoticon", "eyes", "expression", "mood_state", "tears_sweat", "physical"),
    "angry":      ("expression", "eyes", "emoticon", "mood_state", "tears_sweat", "physical"),
    "displeased": ("emoticon", "expression", "eyes", "mood_state", "tears_sweat", "physical"),
    "neutral":    ("expression", "eyes", "mood_state", "emoticon", "tears_sweat", "physical"),
    "sleepy":     ("eyes", "expression", "mood_state", "physical", "emoticon", "tears_sweat"),
    "intense":    ("mood_state", "expression", "eyes", "physical", "emoticon", "tears_sweat"),
    "physical":   ("physical", "expression", "eyes", "mood_state", "emoticon", "tears_sweat"),
    "other":      DEFAULT_FOCUS_ORDER,
}


def normalize_tag(value: Any) -> str:
    if value is None:
        return ""
    tag = " ".join(str(value).strip().lower().split())
    if "_" in tag and not SYMBOL_UNDERSCORE_RE.fullmatch(tag):
        tag = tag.replace("_", " ")
    return " ".join(tag.split())


def normalize_group_id(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def parse_general_tags(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [tag for tag in (normalize_tag(part) for part in value.split(",")) if tag]

NOISE_TAGS: set[str] = {
    "!",
    "!!",
    "??",
    "+++",
    "| |",
    "|_|",
    "x",
    "yes",
    "speech bubble",
    "thought bubble",
    "motion lines",
    "notice lines",
    "sound effects",
    "spoken ellipsis",
    "spoken blush",
    "spoken heart",
    "spoken flower",
    "facial mark",
    "dot nose",
    "no nose",
    "facepaint",
    "food on face",
    "chocolate on face",
    "rice on face",
    "paint splatter on face",
    "dirty face",
    "wet face",
    "bruise on face",
    "bruised eye",
    "body blush",
    "full-body blush",
    "knee blush",
    "breast conscious",
    "crossdressing",
    "reverse trap",
    "incoming hug",
    "wiping face",
    "fanning face",
    "face in hands",
    "cheek on glass",
    "cheek poking",
    "cheek press",
    "cheek pull",
    "cheek squash",
    "clutching head",
    "fingers to cheek",
    "fingers to cheeks",
    "looking through fingers",
    "peeking through fingers",
    "cheek pinching",
    "stop (gesture)",
    "shouting with hands",
    "we can do it!",
    "snap my choker (phrase)",
    "double entendre",
    "multiple expressions",
    "expressions",
}
NOISE_PREFIXES: tuple[str, ...] = ("spoken ",)
SYMBOL_EXPRESSION_TAGS: set[str] = {"?"}
NON_EXPRESSION_MODIFIER_TAGS: set[str] = {
    "blush",
    "light blush",
    "blush stickers",
    "nose blush",
    "forehead blush",
    "full-face blush",
    "ear blush",
    "blush visible through clothes",
    "blush visible through hands",
    "eyes over blush",
    "heart-shaped blush stickers",
}
LOW_SIGNAL_COMBO_TAGS: set[str] = {
    "open mouth",
    "closed mouth",
    "parted lips",
    "teeth",
    "upper teeth only",
    "lower teeth only",
    "round teeth",
    "clenched teeth",
    "visible teeth",
    "raised eyebrows",
    "raised eyebrow",
    "short eyebrows",
    "closed eyes",
    "half-closed eyes",
    "half-closed eye",
}

# Eye-shape anatomy (character traits, not expressions). User confirmed
# tareme/tsurime/sanpaku/hikimayu are noise; jitome stays as a real expression.
EYE_SHAPE_NOISE: set[str] = {"tareme", "tsurime", "sanpaku", "hikimayu"}

# Stylized rendering shapes. Stripped from combos when a real expression
# tag is also present; preserved as standalone neutral rows otherwise.
STYLIZED_MOUTH_NOISE: set[str] = {
    "wavy mouth",
    "dot mouth",
    "chestnut mouth",
    "triangle mouth",
    "square mouth",
    "peanut mouth",
    "chest mouth",
    "black mouth",
    "flower over mouth",
    "split mouth",
    "sideways mouth",
}

# Blush positional/style variants. They duplicate `blush` for the AI and
# clutter labels. Treated as tag-level noise (drop, do not surface as decorator).
BLUSH_FAMILY_DROP: set[str] = {
    "nose blush",
    "forehead blush",
    "ear blush",
    "full-face blush",
    "shoulder blush",
    "knee blush",
    "blush visible through clothes",
    "blush visible through hands",
    "eyes over blush",
    "heart-shaped blush stickers",
}

# Light/strong & parent/child collapse pairs (parent kept, children dropped).
LIGHT_STRONG_PAIRS: list[tuple[str, str]] = [
    ("smile", "light smile"),
    ("frown", "light frown"),
]
PARENT_CHILD_COLLAPSE: list[tuple[str, set[str]]] = [
    ("drooling", {"saliva", "saliva trail", "saliva drip", "mouth drool"}),
    ("tears", {"tearing up"}),
    ("heavy breathing", {"breath"}),
]

# Emoticon mouth-state implications. Used to drop redundant mouth-state
# decorators when the emoticon already encodes the state.
EMOTICON_MOUTH_OPEN: set[str] = {
    ":d", ":o", ";d", ";o", ":p", ":q", ";p", ";q",
    "^^^", "d:", "dx", ">:p", "x3", "gao", "o3o",
    "!?", ">:)", ">:(", "@_@", "@ @",
}
EMOTICON_MOUTH_CLOSED: set[str] = {
    ":3", ":t", "3:", ":<", ":/", ":>", "c:", ";)",
    "^_^", ";(", ";<", ";|", ":|", "...", ". .", "= =",
    "+_+", "+ +", "+ -",
}
EMOTICON_IMPLIES_TONGUE: set[str] = {":p", ":q", ";p", ";q", ":t", ";t"}
EMOTICON_IMPLIES_GRIN: set[str] = {":d", ";d"}

# Auxiliary modifiers stripped when an emoticon dominates the combo.
# Keep fangs/sharp teeth distinct (visually meaningful).
EMOTICON_AUX_STRIP: set[str] = {
    "tongue", "tongue out",
    "drooling", "saliva", "saliva trail", "saliva drip", "mouth drool",
    "sweatdrop", "flying sweatdrops",
    "breath", "heavy breathing", "huffing",
    "happy",  # :d already implies happy grin
    "tareme", "tsurime", "sanpaku", "hikimayu",  # belt-and-braces
    "^^^", "^_^", "^ ^", "^3^", "^v^",  # nested emoticons
}

PROMPT_DECORATOR_TAGS = NON_EXPRESSION_MODIFIER_TAGS | LOW_SIGNAL_COMBO_TAGS
MAX_PROMPT_DECORATORS = 3

# Decorator slot families: at most one decorator per family survives.
DECORATOR_BLUSH_FAMILY: set[str] = {"blush", "light blush", "blush stickers"}
DECORATOR_MOUTH_FAMILY: set[str] = {"open mouth", "closed mouth", "parted lips"}
DECORATOR_EYE_FAMILY: set[str] = {"closed eyes", "half-closed eyes", "half-closed eye"}
DECORATOR_DROP: set[str] = {  # never surface as decorators
    "teeth", "upper teeth only", "lower teeth only", "round teeth",
    "clenched teeth", "visible teeth",
    "raised eyebrows", "raised eyebrow", "short eyebrows",
}
PROMPT_DECORATOR_PRIORITY: dict[str, int] = {
    "blush": 0,
    "light blush": 1,
    "blush stickers": 2,
    "open mouth": 10,
    "closed mouth": 11,
    "parted lips": 12,
    "closed eyes": 20,
    "half-closed eyes": 21,
    "half-closed eye": 22,
}
REDUNDANT_TAGS_IF_PRESENT: dict[str, set[str]] = {
    "tongue": {"tongue out", "pulling tongue", "tongue up", "yellow tongue", "biting tongue"},
    "teeth": {
        "upper teeth only",
        "lower teeth only",
        "clenched teeth",
        "sharp teeth",
        "round teeth",
        "buck teeth",
        "visible teeth",
        "orange teeth",
        "red teeth",
        "rainbow teeth",
    },
    "fangs": {"skin fang", "fang out", "fangs out"},
    "saliva": {"drooling", "saliva trail", "saliva drip", "mouth drool", "excessive saliva"},
    "open mouth": {"wide mouth", "jaw drop", "gasp", "shouting", "roaring", "moaning", "yawning", "hollow mouth"},
}

TEARS_TAGS = {"tears", "crying", "crying with eyes open", "tearing up", "fake tears", "floating tears", "happy tears", "single tear", "teardrop", "watery eyes"}
ANGRY_TAGS = {
    "angry",
    "frown",
    "light frown",
    "annoyed",
    "defeat",
    "anger vein",
    "furrowed brow",
    "furious",
    "grumpy",
    "scowl",
}
SHY_TAGS = {"embarrassed", "shy", "nervous", "sweatdrop", "flying sweatdrops"}
SURPRISE_TAGS = {":o", ";o", "surprised"}
DISPLEASED_TAGS = {":<", ":/"}
GRIN_TAGS = {"grin", "smirk", "smug", "evil smile", "evil grin", "seductive smile", "crazy grin"}
SMILE_TAGS = {"smile", "light smile", "happy"}
STOIC_TAGS = {"expressionless", "serious", "sleepy", "wavy mouth", "dot mouth", "sideways mouth"}
BLUSH_TAGS = {
    "blush",
    "light blush",
    "blush stickers",
    "nose blush",
    "forehead blush",
    "full-face blush",
    "ear blush",
    "blush visible through clothes",
    "blush visible through hands",
    "eyes over blush",
    "heart-shaped blush stickers",
}
EYE_EXACT = {
    "closed eyes",
    "one eye closed",
    "half-closed eyes",
    "half-closed eye",
    "wide-eyed",
    "empty eyes",
    "blank eyes",
    "rolling eyes",
    "heart in eye",
    "shiny eyes",
    "opening eyes",
    "blurry eyes",
    "twinkle eye",
    "one eye narrowed",
    "wall-eyed",
    "liquid from eyes",
    "melting eyes",
    "staring",
    "sideways glance",
    "averting eyes",
    "tareme",
    "tsurime",
    "jitome",
    "sanpaku",
    "glaring",
    "blinking",
    "squeans",
    "squinting",
    "eyelid pull",
    "blank stare",
    "eyes in shadow",
    "shaft look",
    "dot pupils",
}
EYEBROW_TAGS = {
    "raised eyebrows",
    "raised eyebrow",
    "raised inner eyebrows",
    "cocked eyebrow",
    "short eyebrows",
    "furrowed brow",
    "hikimayu",
}
MOUTH_EXACT = {
    "open mouth",
    "closed mouth",
    "parted lips",
    "biting own lip",
    "licking lips",
    "pout",
    "tongue",
    "tongue out",
    "pulling tongue",
    "teeth",
    "upper teeth only",
    "clenched teeth",
    "sharp teeth",
    "round teeth",
    "fangs",
    "skin fang",
    "fang out",
    "saliva",
    "saliva trail",
    "drooling",
    "breath",
    "heavy breathing",
    "moaning",
    "yawning",
    "split mouth",
    "chestnut mouth",
    "triangle mouth",
    "wide mouth",
    "square mouth",
    "diamond mouth",
    "smoke from mouth",
    "uwu",
    "underbite",
    "huffing",
    "sneer",
    "lower teeth only",
    "mouth drool",
    "skin fangs",
    "grimace",
    "shouting",
    "akanbe",
    "teeth hold",
    "saliva drip",
    "buck teeth",
    "cheek bulge",
    "puffy cheeks",
    "puff of air",
    "pill on tongue",
    "yellow tongue",
    "glasgow smile",
    "biting tongue",
    "breathing on hands",
    "humming",
}
PHYSICAL_TAGS = {
    "blood on face",
    "blood from mouth",
    "nosebleed",
    "snot",
    "drunk",
    "stoned",
    "tipsy",
    "headache",
    "paralysis",
    "red nose",
    "runny nose",
    "brain freeze",
}
EMOTICON_WORD_TAGS = {"u u", "x x", "o o", "0 0", "gao", "o3o", "xd"}
MOOD_TAGS = {
    "affectionate",
    "awake",
    "betrayal",
    "charisma break",
    "comfy",
    "confident",
    "corruption",
    "dark persona",
    "desperation",
    "distracted",
    "failure",
    "feral instincts",
    "flinch",
    "lonely",
    "lovestruck",
    "narcissism",
    "naughty face",
    "pain",
    "peaceful",
    "possessed",
    "skeptical",
    "sly",
    "stutter",
    "sulking",
    "waking up",
    "yandere",
    "shaded face",
    "wince",
    "nervous smile",
    "scared",
    "sad",
    "aroused",
    "disgust",
    "laughing",
    "pervert",
    "worried",
    "clueless",
    "flustered",
    "doyagao",
    "exhausted",
    "confused",
    "thinking",
    "fever",
    "dazed",
    "disdain",
    "distress",
    "excited",
    "false smile",
    "gloom (expression)",
    "hungry",
    "concentrating",
    "horrified",
    "pleading face emoji",
    "threat",
    "unhappy",
    "panicking",
    "begging",
    "sobbing",
    "partially shaded face",
    "turn pale",
    "mob face",
    "zzz",
    "gesugao",
    "bored",
    "unamused",
    "depressed",
    "face in shadow",
    "focused",
    "frustrated",
    "giggling",
    "pensive",
}


def export_catalog(
    repo_root: Path | str = REPO_ROOT,
    output_path: Path | str | None = None,
    source_path: Path | str | None = None,
    min_tag_count: int = MIN_TAG_COUNT,
    min_combo_count: int = MIN_COMBO_COUNT,
) -> dict[str, Any]:
    root = Path(repo_root)
    source = Path(source_path) if source_path is not None else root / SOURCE_RELATIVE_PATH
    if not source.is_absolute():
        source = root / source
    taxonomy = load_static_taxonomy(root)
    catalog = build_catalog(
        root,
        source,
        taxonomy,
        min_tag_count=max(1, int(min_tag_count or MIN_TAG_COUNT)),
        min_combo_count=max(1, int(min_combo_count or MIN_COMBO_COUNT)),
    )

    target = Path(output_path) if output_path is not None else root / CATALOG_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return catalog


def build_catalog(
    repo_root: Path,
    source_path: Path,
    taxonomy: dict[str, Any],
    min_tag_count: int,
    min_combo_count: int,
) -> dict[str, Any]:
    import pyarrow.parquet as pq

    if not source_path.exists():
        raise FileNotFoundError(f"missing source parquet: {source_path}")
    table = pq.read_table(source_path, columns=["general"])
    general_values = table.column("general").to_pylist()

    taxonomy_emoticons = collect_emoticon_tags(taxonomy)

    raw_tag_counts: Counter[str] = Counter()
    raw_combo_counts: Counter[tuple[str, ...]] = Counter()
    rows_with_taxonomy_tags = 0
    for general in general_values:
        hits = tuple(sorted(set(parse_general_tags(general)) & taxonomy["all_tags"]))
        if not hits:
            continue
        rows_with_taxonomy_tags += 1
        raw_tag_counts.update(hits)
        raw_combo_counts[hits] += 1

    semantics: dict[str, tuple[str, str]] = {}
    noise_reasons: dict[str, str] = {}
    for tag in sorted(raw_tag_counts):
        reason = noise_reason_for_tag(tag, taxonomy["tag_groups"].get(tag, []), raw_tag_counts[tag], min_tag_count)
        if reason:
            noise_reasons[tag] = reason
            continue
        semantic = semantic_for_tag(tag, taxonomy["tag_groups"].get(tag, []))
        if semantic is None:
            noise_reasons[tag] = "no-expression-semantic"
            continue
        semantics[tag] = semantic

    pre_canonical_combo_counts: Counter[tuple[str, ...]] = Counter()
    combo_counts: Counter[tuple[str, ...]] = Counter()
    variant_counts: dict[tuple[str, ...], Counter[tuple[str, ...]]] = defaultdict(Counter)
    flattened_rows = 0
    deduplicated_rows = 0
    decorated_rows = 0
    rows_with_kept_tags = 0
    for raw_combo, count in raw_combo_counts.items():
        kept = tuple(tag for tag in raw_combo if tag in semantics)
        if not kept:
            continue
        decorators = tuple(tag for tag in raw_combo if tag in PROMPT_DECORATOR_TAGS)
        rows_with_kept_tags += count
        if len(kept) != len(raw_combo):
            flattened_rows += count
        pre_canonical_combo_counts[kept] += count
        canonical = canonicalize_combo(kept, taxonomy_emoticons)
        if not canonical:
            continue
        if canonical != kept:
            deduplicated_rows += count
        combo_counts[canonical] += count
        prompt_variant = canonicalize_prompt_variant(canonical, decorators, taxonomy_emoticons)
        if set(prompt_variant) - set(canonical):
            decorated_rows += count
        variant_counts[canonical][prompt_variant] += count

    low_count_combo_counts = Counter({
        combo: count
        for combo, count in combo_counts.items()
        if count < min_combo_count
    })
    low_count_combo_rows = sum(low_count_combo_counts.values())
    low_count_combo_tags = {
        tag
        for combo in low_count_combo_counts
        for tag in combo
    }
    for combo in low_count_combo_counts:
        combo_counts.pop(combo, None)
        variant_counts.pop(combo, None)

    kept_tag_counts: Counter[str] = Counter()
    for combo, count in combo_counts.items():
        for tag in combo:
            kept_tag_counts[tag] += count

    # Tags that survived semantic classification but had every combo
    # collapse to empty under canonicalization need to be reclassified as
    # noise so the coverage bookkeeping stays internally consistent.
    for tag in list(semantics):
        if tag not in kept_tag_counts:
            noise_reasons[tag] = "singleton-only-combo" if tag in low_count_combo_tags else "no-surviving-combo"
            semantics.pop(tag, None)

    categories = build_categories(combo_counts, kept_tag_counts, semantics, variant_counts, taxonomy_emoticons)
    coverage = build_coverage(taxonomy, raw_tag_counts, kept_tag_counts, noise_reasons, min_tag_count)
    semantic_coverage = build_semantic_coverage(categories, kept_tag_counts, semantics)
    source_relative = str(source_path.relative_to(repo_root)) if source_path.is_relative_to(repo_root) else str(source_path)

    return {
        "version": 2,
        "dataset": "custom_1girl_solo_general_expression",
        "scope": {
            "person": "1girl_solo",
            "sourceColumn": "general",
        },
        "source": "custom-general-expression-json-export",
        "sourceFile": source_relative,
        "counts": {
            "sourceRows": len(general_values),
            "rowsWithTaxonomyTags": rows_with_taxonomy_tags,
            "rowsWithExpressionTags": rows_with_kept_tags,
            "rawExpressionTags": len(raw_tag_counts),
            "rawExpressionCombos": len(raw_combo_counts),
            "expressionTags": len(kept_tag_counts),
            "expressionCombos": len(combo_counts),
            "minComboCount": min_combo_count,
            "staticTags": len(taxonomy["all_tags"]),
            "noiseTagsRemoved": len(noise_reasons),
            "noiseTagOccurrences": sum(raw_tag_counts[tag] for tag in noise_reasons),
            "flattenedRows": flattened_rows,
            "deduplicatedRows": deduplicated_rows,
            "decoratedRows": decorated_rows,
            "lowCountCombosRemoved": len(low_count_combo_counts),
            "lowCountComboRowsRemoved": low_count_combo_rows,
            "semanticDuplicateCombos": len(pre_canonical_combo_counts) - len(combo_counts),
            "lowSignalComboTags": len(LOW_SIGNAL_COMBO_TAGS),
        },
        "quality": {
            "minTagCount": min_tag_count,
            "minComboCount": min_combo_count,
            "maxItemsPerSubcategory": MAX_ITEMS_PER_SUBCATEGORY,
            "sortPolicy": "category mood order, focus order, fewer core tags first, count descending, concise combo first",
            "representativeVariantPolicy": (
                "dedupe by core expression tags, then display/apply the highest-scoring prompt variant "
                "after pruning blush/mouth-state/eye-state to one decorator each (max 3 total)"
            ),
            "canonicalizationPolicy": {
                parent: sorted(children)
                for parent, children in REDUNDANT_TAGS_IF_PRESENT.items()
            },
            "lowSignalComboTags": sorted(LOW_SIGNAL_COMBO_TAGS),
            "eyeShapeNoise": sorted(EYE_SHAPE_NOISE),
            "stylizedMouthNoise": sorted(STYLIZED_MOUTH_NOISE),
            "blushFamilyDrop": sorted(BLUSH_FAMILY_DROP),
            "lightStrongPairs": [list(pair) for pair in LIGHT_STRONG_PAIRS],
            "parentChildCollapse": {parent: sorted(children) for parent, children in PARENT_CHILD_COLLAPSE},
            "moodReroute": [
                {"forced": forced, "mustContain": sorted(must), "mustNotContain": sorted(must_not)}
                for forced, must, must_not in MOOD_REROUTE_PRIORITY
            ],
            "noisePolicy": [
                "drop taxonomy tags below minTagCount",
                "drop canonical expression combos below minComboCount",
                "drop misc symbol tags from expression_tags.json tags[]",
                "drop non-expression modifiers such as blush",
                "drop blush positional variants (nose/forehead/ear/full-face/...)",
                "drop eye-shape anatomy (tareme/tsurime/sanpaku/hikimayu) — jitome kept as expression",
                "drop non-facial visual effects and annotation-like tags",
                "drop tags that cannot be assigned to an expression semantic bucket",
                "strip stylized mouth shapes when a real expression tag co-occurs",
                "collapse parent tags when a more specific child tag is present",
                "collapse light/strong duplicates (smile+light smile → smile)",
                "collapse parent/child fluid families (drooling absorbs saliva variants; tears absorbs tearing up; heavy breathing absorbs breath)",
                "drop redundant `angry` when `frown` is present, `nervous` when `embarrassed` is present",
                "demote `expressionless` to implicit when another expression-bearing tag exists",
                "strip auxiliary modifiers (tongue/saliva/sweatdrop/breath) when an emoticon is present",
                "drop low-signal combo tags when stronger expression tags remain",
                "reroute embarrassed → shy, nervous-smile-only → tense, false/forced smile → displeased, sad smile → sad",
            ],
            "noiseTags": [
                {
                    "tag": tag,
                    "count": int(raw_tag_counts[tag]),
                    "reason": noise_reasons[tag],
                    "groups": taxonomy["tag_groups"].get(tag, []),
                }
                for tag in sorted(noise_reasons, key=lambda item: (-raw_tag_counts[item], item))
            ],
        },
        "tagCounts": [
            {
                "tag": tag,
                "count": int(count),
                "displayCount": format_count(int(count)),
                "categoryId": semantics[tag][0],
                "subcategoryId": semantics[tag][1],
                "groups": taxonomy["tag_groups"].get(tag, []),
            }
            for tag, count in sorted(kept_tag_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "coverage": coverage,
        "semanticCoverage": semantic_coverage,
        "categories": categories,
    }


def noise_reason_for_tag(tag: str, groups: list[str], count: int, min_tag_count: int) -> str:
    if count < min_tag_count:
        return "low-support"
    if tag in EYE_SHAPE_NOISE:
        return "anatomy-not-expression"
    if tag in BLUSH_FAMILY_DROP:
        return "blush-variant"
    if tag in NON_EXPRESSION_MODIFIER_TAGS:
        return "non-expression-modifier"
    if tag in LOW_SIGNAL_COMBO_TAGS:
        return "low-signal-modifier"
    if "tags" in groups and tag not in SYMBOL_EXPRESSION_TAGS:
        return "misc-symbol"
    if tag in NOISE_TAGS:
        return "non-expression"
    if any(tag.startswith(prefix) for prefix in NOISE_PREFIXES):
        return "annotation"
    if " bubble" in tag or tag.endswith(" bubble"):
        return "annotation"
    return ""


def semantic_for_tag(tag: str, groups: list[str]) -> tuple[str, str] | None:
    if tag in TEARS_TAGS or "tear" in tag or "crying" in tag:
        return ("sad", "tears_sweat")
    if tag in ANGRY_TAGS or "frown" in tag or "angry" in tag:
        return ("angry", "expression")
    if tag in SHY_TAGS or "sweat" in tag:
        if "sweat" in tag:
            return ("tense", "tears_sweat")
        return ("tense", "mood_state") if tag == "nervous" else ("shy", "expression")
    if tag in SURPRISE_TAGS:
        return ("surprised", "emoticon" if tag in {":o", ";o"} else "mood_state")
    if tag in DISPLEASED_TAGS:
        return ("displeased", "emoticon")
    if tag in GRIN_TAGS or "grin" in tag:
        if "evil" in tag or "crazy" in tag:
            return ("intense", "expression")
        return ("playful", "expression")
    if tag in SMILE_TAGS:
        return ("cheerful", "expression")
    if "smile" in tag:
        if tag == "nervous smile":
            return ("tense", "expression")
        if tag == "sad smile":
            return ("sad", "expression")
        if tag in {"false smile", "forced smile"}:
            return ("displeased", "expression")
        return ("cheerful", "expression")
    if tag in STOIC_TAGS:
        if tag == "sleepy":
            return ("sleepy", "mood_state")
        if tag in {"wavy mouth", "dot mouth", "sideways mouth"}:
            return ("neutral", "expression")
        return ("neutral", "mood_state")
    if tag in BLUSH_TAGS or ("blush" in tag and tag not in NOISE_TAGS):
        return ("shy", "expression")
    if tag in EYEBROW_TAGS:
        if "furrow" in tag:
            return ("angry", "expression")
        if "raised" in tag or "cocked" in tag:
            return ("surprised", "expression")
        return ("neutral", "expression")
    if tag in EYE_EXACT or " eyes" in tag or tag.endswith(" eye") or "eyed" in tag:
        if tag in {"closed eyes", "half-closed eyes", "half-closed eye"}:
            return ("neutral", "eyes")
        if tag in {"one eye closed", "one eye narrowed"}:
            return ("playful", "eyes")
        if tag == "averting eyes":
            return ("shy", "eyes")
        if tag == "rolling eyes":
            return ("displeased", "eyes")
        if tag in {"sideways glance", "staring"}:
            return ("neutral", "eyes")
        if tag == "glaring":
            return ("angry", "eyes")
        if tag in {"wide-eyed", "shiny eyes", "twinkle eye", "sparkling eyes"}:
            return ("surprised", "eyes")
        if tag == "jitome":
            return ("displeased", "eyes")
        return ("neutral", "eyes")
    if any(token in tag for token in ("eye", "eyebrow", "stare", "squint", "blink", "glare", "squeans", "pupil")):
        return ("neutral", "eyes")
    if tag in MOUTH_EXACT or " mouth" in tag or " lips" in tag:
        return mouth_semantic(tag)
    if any(token in tag for token in ("teeth", "fang", "drool", "saliva", "tongue", "mouth", "cheek", "shout", "grimace")):
        return mouth_semantic(tag)
    if tag in PHYSICAL_TAGS:
        if "blood" in tag or "nosebleed" in tag:
            return ("physical", "physical")
        if tag in {"snot", "runny nose"}:
            return ("physical", "physical")
        return ("intense", "physical") if tag in {"drunk", "stoned", "tipsy"} else ("physical", "physical")
    if tag in MOOD_TAGS or "emotion" in groups or "emotional_state" in groups:
        return mood_semantic(tag)
    if tag in SYMBOL_EXPRESSION_TAGS:
        return ("surprised", "emoticon")
    if tag in EMOTICON_WORD_TAGS:
        if tag in {"xd", "gao", "o3o"}:
            return ("cheerful", "emoticon")
        if tag == "0 0":
            return ("surprised", "emoticon")
        if tag == "u u":
            return ("sleepy", "emoticon")
        return ("neutral", "emoticon")
    if looks_like_emoticon(tag, groups):
        if tag in {":d", ";d", ":>", "^^^", "^ ^", "^3^", "^v^", "c:"}:
            return ("cheerful", "emoticon")
        if tag in {":3", ";3"}:
            return ("playful", "emoticon")
        if tag in {":p", ":q", ";p", ";q", ":t", ";t", "3:", "3;"}:
            return ("playful", "emoticon")
        if tag in {":o", ";o", "!?"}:
            return ("surprised", "emoticon")
        if tag in {":<", ">:(", ";(", "dx"}:
            return ("displeased", "emoticon")
        if tag in {":|", ";|", "...", ". ."}:
            return ("neutral", "emoticon")
        return ("playful", "emoticon")
    return None


def looks_like_emoticon(tag: str, groups: list[str]) -> bool:
    if "emoticon" not in groups and "physical" not in groups:
        return False
    return bool(EMOTICON_RE.match(tag)) and any(char in tag for char in ":;=@!?._+\\/-^><|()")


def mouth_semantic(tag: str) -> tuple[str, str]:
    if tag in {"tongue", "tongue out", "pulling tongue", "tongue up", "biting tongue"}:
        return ("playful", "expression")
    if tag in {"fangs", "skin fang", "fang out", "fangs out", "sharp teeth", "skin fangs"}:
        return ("playful", "expression")
    if tag in {"grimace", "wince", "shouting", "huffing"}:
        return ("tense", "expression")
    if tag in {"drooling", "saliva", "saliva trail", "saliva drip", "mouth drool", "heavy breathing", "breath", "moaning"}:
        return ("physical", "physical")
    if tag == "yawning":
        return ("sleepy", "expression")
    return ("neutral", "expression")


def mood_semantic(tag: str) -> tuple[str, str]:
    if tag in {"yandere", "corruption", "dark persona", "possessed", "feral instincts", "aroused", "pervert", "threat"}:
        return ("intense", "mood_state")
    if tag in {"sad", "lonely", "unhappy", "depressed", "sobbing", "gloom (expression)", "pleading face emoji"}:
        return ("sad", "mood_state")
    if tag in {"scared", "horrified", "panicking", "distress", "desperation", "flinch", "wince", "worried", "clueless", "confused", "uncomfortable", "unsure", "stutter"}:
        return ("tense", "mood_state")
    if tag in {"bored", "exhausted", "zzz", "lazy"}:
        return ("sleepy", "mood_state")
    if tag in {"disgust", "disdain", "unamused", "skeptical", "sly", "failure", "bitter", "reluctant"}:
        return ("displeased", "mood_state")
    if tag in {"laughing", "giggling", "excited", "peaceful", "confident", "amused", "proud", "satisfied"}:
        return ("cheerful", "mood_state")
    if tag in {"naughty face", "doyagao", "gesugao"}:
        return ("playful", "mood_state")
    if tag in {"shaded face", "face in shadow", "turn pale", "partially shaded face"}:
        return ("intense", "expression")
    return ("neutral", "mood_state")


def is_emoticon_tag(tag: str, taxonomy_emoticons: set[str] | None = None) -> bool:
    if taxonomy_emoticons and tag in taxonomy_emoticons:
        return True
    if tag in SYMBOL_EXPRESSION_TAGS:
        return True
    if tag in EMOTICON_WORD_TAGS:
        return True
    return False


def canonicalize_combo(tags: tuple[str, ...], taxonomy_emoticons: set[str] | None = None) -> tuple[str, ...]:
    tag_set = set(tags)

    # Stylized mouth strip — keep only when no other expression tag co-exists.
    other_expression_present = bool(
        (tag_set - STYLIZED_MOUTH_NOISE - LOW_SIGNAL_COMBO_TAGS - NON_EXPRESSION_MODIFIER_TAGS)
    )
    if other_expression_present:
        tag_set -= STYLIZED_MOUTH_NOISE

    # Light/strong & parent/child collapse.
    for parent, child in LIGHT_STRONG_PAIRS:
        if parent in tag_set and child in tag_set:
            tag_set.discard(child)
    for parent, children in PARENT_CHILD_COLLAPSE:
        if parent in tag_set:
            tag_set -= children

    # wince absorbs one eye closed (the wince IS a one-eye-closed gesture).
    if "wince" in tag_set:
        tag_set.discard("one eye closed")

    # Avoid double-encoding: angry+frown → frown; nervous+embarrassed → embarrassed.
    if "frown" in tag_set:
        tag_set.discard("angry")
    if "embarrassed" in tag_set:
        tag_set.discard("nervous")

    # expressionless demotion: when another expression-bearing tag exists,
    # expressionless becomes implicit. Drop it from the dedupe key.
    if "expressionless" in tag_set:
        rest = (tag_set - {"expressionless"}) - LOW_SIGNAL_COMBO_TAGS - STYLIZED_MOUTH_NOISE - NON_EXPRESSION_MODIFIER_TAGS
        if rest:
            tag_set.discard("expressionless")

    # Emoticon dominance: when an emoticon is present, strip auxiliary
    # modifiers that the emoticon already implies or that explode variants.
    has_emoticon = any(is_emoticon_tag(t, taxonomy_emoticons) for t in tag_set)
    if has_emoticon:
        tag_set -= EMOTICON_AUX_STRIP
        if tag_set & EMOTICON_IMPLIES_TONGUE:
            tag_set.discard("tongue")
            tag_set.discard("tongue out")
        if tag_set & EMOTICON_IMPLIES_GRIN:
            tag_set.discard("grin")

    # Existing parent-with-specific-child rule.
    for parent, children in REDUNDANT_TAGS_IF_PRESENT.items():
        if parent in tag_set and tag_set.intersection(children):
            tag_set.remove(parent)

    reduced = tag_set - LOW_SIGNAL_COMBO_TAGS
    if reduced:
        tag_set = reduced
    return tuple(sorted(tag_set))


def build_categories(
    combo_counts: Counter[tuple[str, ...]],
    tag_counts: Counter[str],
    semantics: dict[str, tuple[str, str]],
    variant_counts: dict[tuple[str, ...], Counter[tuple[str, ...]]],
    taxonomy_emoticons: set[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for combo, count in combo_counts.items():
        category_id, subcategory_id, primary_tag = classify_combo(combo, semantics, tag_counts, taxonomy_emoticons)
        grouped[(category_id, subcategory_id)].append(
            combo_item(
                combo,
                count,
                category_id,
                subcategory_id,
                primary_tag,
                variant_counts.get(combo, Counter({combo: count})),
                taxonomy_emoticons,
            )
        )

    categories: list[dict[str, Any]] = []
    for category_id, category_label in CATEGORY_ORDER:
        subcategory_rows = [
            (subcategory_id, items)
            for (group_id, subcategory_id), items in grouped.items()
            if group_id == category_id
        ]
        if not subcategory_rows:
            continue
        subcategory_rows.sort(key=lambda row: (
            focus_sort_index(category_id, row[0]),
            row[0],
        ))
        subcategories: list[dict[str, Any]] = []
        category_count = 0
        for subcategory_id, items in subcategory_rows:
            items.sort(key=lambda item: (
                len(item.get("coreTags") or []),
                -int(item.get("count") or 0),
                len(item.get("decoratorTags") or []),
                item.get("label") or "",
            ))
            primary_items = items[:MAX_ITEMS_PER_SUBCATEGORY]
            more_items = items[MAX_ITEMS_PER_SUBCATEGORY:]
            category_count += len(items)
            subcategory_payload: dict[str, Any] = {
                "id": f"{category_id}-{subcategory_id}",
                "label": FOCUS_LABELS.get(subcategory_id, title_label(subcategory_id)),
                "labelKo": FOCUS_LABELS_KO.get(subcategory_id, ""),
                "count": len(items),
                "items": primary_items,
            }
            if more_items:
                subcategory_payload["moreItems"] = more_items
                subcategory_payload["moreCount"] = len(more_items)
            subcategories.append(subcategory_payload)
        categories.append({
            "id": category_id,
            "label": category_label,
            "labelKo": CATEGORY_LABELS_KO.get(category_id, ""),
            "count": category_count,
            "subcategories": subcategories,
        })
    return categories


# Mood reroute rules. When the combo carries any of these "anchor" tags,
# the listed category wins regardless of generic smile/grin scoring.
# Tuned so the user's intuition (embarrassed = shy, not cheerful) matches
# the picker's mood column.
MOOD_REROUTE_PRIORITY: list[tuple[str, frozenset[str], frozenset[str]]] = [
    # (forced_category, must_contain, must_not_contain)
    ("intense", frozenset({"yandere", "corruption", "dark persona", "possessed", "feral instincts", "aroused", "pervert"}), frozenset()),
    ("shy", frozenset({"embarrassed"}), frozenset()),
    ("tense", frozenset({"nervous smile"}), frozenset({"embarrassed"})),
    ("displeased", frozenset({"false smile", "forced smile"}), frozenset()),
    ("sad", frozenset({"sad smile"}), frozenset()),
]


def apply_mood_reroute(combo_set: set[str]) -> str | None:
    for forced, must_contain, must_not in MOOD_REROUTE_PRIORITY:
        if combo_set & must_contain and not (combo_set & must_not):
            return forced
    return None


def classify_combo(
    combo: tuple[str, ...],
    semantics: dict[str, tuple[str, str]],
    tag_counts: Counter[str],
    taxonomy_emoticons: set[str],
) -> tuple[str, str, str]:
    semantic_rows = [(tag, *semantics[tag]) for tag in combo if tag in semantics]
    ranked_moods = sorted(
        semantic_rows,
        key=lambda row: (
            -tag_mood_strength(row[0], row[1]),
            MOOD_PRIORITY.get(row[1], 999),
            -tag_counts[row[0]],
            row[0],
        ),
    )
    if not ranked_moods:
        return ("other", "mood_state", combo[0] if combo else "")

    forced_category = apply_mood_reroute(set(combo))
    if forced_category is not None:
        forced_rows = [r for r in ranked_moods if r[1] == forced_category]
        if forced_rows:
            ranked_moods = forced_rows + [r for r in ranked_moods if r[1] != forced_category]
        else:
            primary_tag = ranked_moods[0][0]
            focus_id = combo_focus(semantic_rows, taxonomy_emoticons, combo)
            return forced_category, focus_id, primary_tag

    primary_tag, category_id, _primary_focus = ranked_moods[0]
    focus_id = combo_focus(semantic_rows, taxonomy_emoticons, combo)
    return category_id, focus_id, primary_tag


def tag_mood_strength(tag: str, mood_id: str) -> int:
    """Higher = stronger mood signal. Generic mouth/eye states score low."""
    if tag in BLUSH_TAGS:
        return 35
    if tag in {"open mouth", "closed mouth", "parted lips", "teeth", "upper teeth only", "closed eyes", "half-closed eyes"}:
        return 25
    if mood_id == "neutral":
        return 40
    if mood_id == "physical":
        return 65
    # Specific mood-bearing tags get the strongest score.
    if tag in {"embarrassed", "shy", "scared", "nervous smile", "yandere", "aroused", "corruption", "dark persona"}:
        return 110
    if tag in {"one eye closed", "tongue", "tongue out", ":p", ":q", ";p", ";q", ":3", ";3"}:
        return 90
    return 100


def combo_focus(rows: list[tuple[str, str, str]], taxonomy_emoticons: set[str], combo: tuple[str, ...]) -> str:
    """Pick the dominant focus axis for a combo.

    Emoticons win when present (otherwise smile/frown core would steal the
    focus from a `:d, smile`-style combo). Falls back to the per-tag focus
    ranked by FOCUS_INDEX and mood strength.
    """
    if any(is_emoticon_tag(t, taxonomy_emoticons) for t in combo):
        return "emoticon"
    ranked = sorted(
        rows,
        key=lambda row: (
            FOCUS_INDEX.get(row[2], 999),
            -tag_mood_strength(row[0], row[1]),
            row[0],
        ),
    )
    return ranked[0][2] if ranked else "mood_state"


def focus_sort_index(category_id: str, focus_id: str) -> int:
    order = CATEGORY_FOCUS_ORDER.get(category_id, DEFAULT_FOCUS_ORDER)
    try:
        return order.index(focus_id)
    except ValueError:
        return len(order) + FOCUS_INDEX.get(focus_id, 999)


def canonicalize_prompt_variant(
    core_tags: tuple[str, ...],
    decorator_tags: tuple[str, ...],
    taxonomy_emoticons: set[str] | None = None,
) -> tuple[str, ...]:
    core = tuple(sorted(set(core_tags)))
    core_set = set(core)
    decorators = set(decorator_tags) - core_set

    # Drop blacklisted decorator families (teeth, eyebrows).
    decorators -= DECORATOR_DROP

    # Drop blush-variant family entirely (already noise at tag level, but
    # belt-and-braces in case raw combo carried them).
    decorators -= BLUSH_FAMILY_DROP

    # Reconcile mouth state with emoticons / tongue-out core.
    has_open_emoticon = bool(core_set & EMOTICON_MOUTH_OPEN)
    has_closed_emoticon = bool(core_set & EMOTICON_MOUTH_CLOSED)
    if has_open_emoticon:
        decorators -= {"closed mouth"}
    if has_closed_emoticon:
        decorators -= {"open mouth", "parted lips"}
    if has_open_emoticon and has_closed_emoticon:
        decorators -= DECORATOR_MOUTH_FAMILY
    if core_set & {"tongue out"} or core_set & {"tongue"}:
        decorators -= {"closed mouth", "parted lips"}
    if core_set & {"open mouth"} or core_set & {"wide mouth"} or core_set & {"yawning"}:
        decorators -= {"closed mouth", "parted lips"}

    for parent, children in REDUNDANT_TAGS_IF_PRESENT.items():
        if parent in decorators and decorators.intersection(children):
            decorators.remove(parent)

    # One-per-family caps, in priority order.
    selected: list[str] = []
    blush_decos = sorted(decorators & DECORATOR_BLUSH_FAMILY, key=decorator_sort_key)
    if blush_decos:
        selected.append(blush_decos[0])
    mouth_decos = sorted(decorators & DECORATOR_MOUTH_FAMILY, key=decorator_sort_key)
    if mouth_decos:
        selected.append(mouth_decos[0])
    eye_decos = sorted(decorators & DECORATOR_EYE_FAMILY, key=decorator_sort_key)
    if eye_decos:
        selected.append(eye_decos[0])

    selected = selected[:MAX_PROMPT_DECORATORS]
    return tuple(list(core) + selected)


def decorator_sort_key(tag: str) -> tuple[int, str]:
    return (PROMPT_DECORATOR_PRIORITY.get(tag, 999), tag)


def collect_emoticon_tags(taxonomy: dict[str, Any]) -> set[str]:
    """All taxonomy tags that should be treated as emoticons.

    Underscore-style emoticons (`+_+`, `^_^`, `@_@`, `>_<`) live in the
    `physical` group rather than `emoticon`, so we sweep all groups and
    accept anything that matches the emoticon regex.
    """
    out: set[str] = set()
    for group_obj in taxonomy.get("groups") or []:
        group_id = normalize_group_id(group_obj.get("id") or "")
        tags = group_obj.get("tags") or []
        if group_id == "emoticon":
            out.update(tags)
            continue
        for tag in tags:
            if EMOTICON_RE.match(tag) and any(char in tag for char in ":;=@!?._+\\/-^><|()"):
                out.add(tag)
    out.update(SYMBOL_EXPRESSION_TAGS)
    out.update(EMOTICON_WORD_TAGS)
    return out


def select_representative_variant(
    core_tags: tuple[str, ...],
    variants: Counter[tuple[str, ...]],
) -> tuple[tuple[str, ...], int]:
    if not variants:
        return core_tags, 0
    max_count = max(variants.values())
    threshold = max_count * 0.75
    candidates = [
        (variant, count)
        for variant, count in variants.items()
        if count >= threshold
    ]
    core_set = set(core_tags)
    return max(
        candidates,
        key=lambda row: (
            len(set(row[0]) - core_set),
            row[1],
            -len(row[0]),
            row[0],
        ),
    )


def combo_item(
    combo: tuple[str, ...],
    count: int,
    category_id: str,
    subcategory_id: str,
    primary_tag: str,
    variants: Counter[tuple[str, ...]],
    taxonomy_emoticons: set[str],
) -> dict[str, Any]:
    core_tags = list(combo)
    representative_tags, representative_count = select_representative_variant(combo, variants)
    # Re-run decorator pruning on the representative variant so the label
    # respects the new one-per-family caps even when the source variant
    # carried multiple blush/mouth-state decorators.
    pruned_variant = canonicalize_prompt_variant(
        tuple(core_tags),
        tuple(tag for tag in representative_tags if tag not in set(core_tags)),
        taxonomy_emoticons,
    )
    tags = list(pruned_variant)
    label = ", ".join(tags)
    canonical_label = ", ".join(core_tags)
    digest = hashlib.sha1(canonical_label.encode("utf-8")).hexdigest()[:12]
    decorator_tags = [tag for tag in tags if tag not in set(core_tags)]
    return {
        "id": f"expr-{digest}",
        "label": label,
        "canonicalLabel": canonical_label,
        "tag": primary_tag or (core_tags[0] if core_tags else label),
        "tags": tags,
        "coreTags": core_tags,
        "decoratorTags": decorator_tags,
        "count": int(count),
        "displayCount": format_count(int(count)),
        "variantCount": len(variants),
        "representativeCount": int(representative_count),
        "representativeShare": round(float(representative_count) / float(count), 6) if count else 0.0,
        "source": "custom-general-expression",
        "categoryId": category_id,
        "subcategoryId": subcategory_id,
    }


def build_coverage(
    taxonomy: dict[str, Any],
    raw_tag_counts: Counter[str],
    kept_tag_counts: Counter[str],
    noise_reasons: dict[str, str],
    min_tag_count: int,
) -> dict[str, Any]:
    raw_tags = set(raw_tag_counts)
    kept_tags = set(kept_tag_counts)
    noise_tags = set(noise_reasons)
    static_tags = taxonomy["all_tags"]
    missing = sorted(static_tags - raw_tags)
    by_group: list[dict[str, Any]] = []
    for group in taxonomy["groups"]:
        group_tags = set(group.get("tags") or [])
        group_seen = group_tags & raw_tags
        group_kept = group_tags & kept_tags
        group_noise = group_tags & noise_tags
        by_group.append({
            "id": group["id"],
            "label": group["label"],
            "total": len(group_tags),
            "seen": len(group_seen),
            "covered": len(group_kept),
            "noise": len(group_noise),
            "missing": len(group_tags - raw_tags),
            "coverageRatio": len(group_kept) / len(group_tags) if group_tags else 0.0,
        })

    return {
        "taxonomyTags": len(static_tags),
        "sourceSeenTags": len(raw_tags),
        "catalogTags": len(kept_tags),
        "coveredTags": len(kept_tags),
        "missingTags": len(missing),
        "noiseTags": len(noise_tags),
        "extraTags": 0,
        "coverageRatio": len(kept_tags) / len(static_tags) if static_tags else 0.0,
        "minTagCount": min_tag_count,
        "missingTagList": missing,
        "noiseTagList": sorted(noise_tags),
        "byGroup": by_group,
    }


def build_semantic_coverage(
    categories: list[dict[str, Any]],
    kept_tag_counts: Counter[str],
    semantics: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    category_combo_counts = {category["id"]: int(category.get("count") or 0) for category in categories}
    focus_combo_counts: dict[tuple[str, str], int] = {}
    for category in categories:
        category_id = category["id"]
        for subcategory in category.get("subcategories") or []:
            focus_id = str(subcategory.get("id") or "").removeprefix(f"{category_id}-")
            focus_combo_counts[(category_id, focus_id)] = int(subcategory.get("count") or 0)

    rows: list[dict[str, Any]] = []
    for category_id, category_label in CATEGORY_ORDER:
        category_tags = [
            tag
            for tag, (tag_category, _focus_id) in semantics.items()
            if tag_category == category_id and tag in kept_tag_counts
        ]
        if not category_tags and not category_combo_counts.get(category_id):
            continue
        by_focus: list[dict[str, Any]] = []
        for focus_id, focus_label in FOCUS_ORDER:
            focus_tags = [
                tag
                for tag in category_tags
                if semantics[tag][1] == focus_id
            ]
            combo_items = focus_combo_counts.get((category_id, focus_id), 0)
            if not focus_tags and not combo_items:
                continue
            by_focus.append({
                "id": focus_id,
                "label": focus_label,
                "tags": len(focus_tags),
                "occurrences": sum(int(kept_tag_counts[tag]) for tag in focus_tags),
                "comboItems": combo_items,
            })
        rows.append({
            "id": category_id,
            "label": category_label,
            "tags": len(category_tags),
            "occurrences": sum(int(kept_tag_counts[tag]) for tag in category_tags),
            "comboItems": category_combo_counts.get(category_id, 0),
            "byFocus": by_focus,
        })

    return {
        "totalTags": len(kept_tag_counts),
        "totalComboItems": sum(category_combo_counts.values()),
        "byCategory": rows,
    }


def load_static_taxonomy(repo_root: Path) -> dict[str, Any]:
    taxonomy_path = repo_root / "data" / "taglist" / "expression_tags.json"
    payload = json.loads(taxonomy_path.read_text(encoding="utf-8"))
    all_tags: set[str] = set()
    groups: list[dict[str, Any]] = []
    tag_groups: dict[str, list[str]] = defaultdict(list)

    modifiers = normalize_tag_list(payload.get("modifiers") or [])
    if modifiers:
        all_tags.update(modifiers)
        groups.append({"id": "modifiers", "label": "modifiers", "tags": modifiers})
        for tag in modifiers:
            tag_groups[tag].append("modifiers")

    for group_id, values in (payload.get("groups") or {}).items():
        tags = normalize_tag_list(values or [])
        if not tags:
            continue
        normalized_group_id = normalize_group_id(group_id)
        all_tags.update(tags)
        groups.append({"id": normalized_group_id, "label": str(group_id), "tags": tags})
        for tag in tags:
            tag_groups[tag].append(normalized_group_id)

    free_tags = normalize_tag_list(payload.get("tags") or [])
    if free_tags:
        all_tags.update(free_tags)
        groups.append({"id": "tags", "label": "tags", "tags": free_tags})
        for tag in free_tags:
            tag_groups[tag].append("tags")

    return {
        "all_tags": all_tags,
        "groups": groups,
        "tag_groups": {tag: groups for tag, groups in tag_groups.items()},
    }


def normalize_tag_list(values: list[Any]) -> list[str]:
    return unique_preserve([tag for tag in (normalize_tag(value) for value in values) if tag])


def title_label(value: str) -> str:
    return str(value or "general").replace("_", " ").title()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--min-tag-count", type=int, default=MIN_TAG_COUNT)
    parser.add_argument("--min-combo-count", type=int, default=MIN_COMBO_COUNT)
    args = parser.parse_args(argv)

    catalog = export_catalog(args.repo_root, args.output, args.source, args.min_tag_count, args.min_combo_count)
    target = args.output or args.repo_root / CATALOG_RELATIVE_PATH
    counts = catalog["counts"]
    print(
        f"Wrote {target} with {counts['expressionCombos']} combos, "
        f"{counts['expressionTags']} tags, and {counts['noiseTagsRemoved']} removed noise tags."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
