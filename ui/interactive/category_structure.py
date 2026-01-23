# 태그 카테고리 구조 (On/Off 버튼용)
# 생성일: 2025-01-22

CATEGORY_STRUCTURE = {
    "Clothing_Wear": [
        "accessories",
        "armor",
        "attire",
        "bra",
        "covering",
        "dress_actions",
        "etc",
        "eyewear",
        "fashion_style",
        "footwear",
        "handwear",
        "headwear",
        "legwear",
        "mask",
        "neck_and_neckwear",
        "panties",
        "patterns",
        "piercings",
        "prints",
        "sexual_attire",
        "sleeves",
    ],
    "Composition_Meta": [
        "colors",
        "composition",
        "count",
        "effects",
        "etc",
        "focus",
        "focus_tags",
        "image_composition",
        "lighting",
        "meta",
        "metatags",
        "scan",
        "subjective",
        "symbols",
        "text",
        "year_tags",
    ],
    "Creatures": [
        "birds",
        "cats",
        "dogs",
        "etc",
        "fish",
        "insects",
        "kemonomimi",
        "legendary_creatures",
        "other_animals",
        "plants",
        "pokemon",
        "reptiles",
    ],
    "Culture_Misc": [
        "artistic_license",
        "culture",
        "etc",
        "family_relationships",
        "groups",
        "history",
        "holidays_and_celebrations",
        "jobs",
        "memes",
        "occupation",
        "phrases",
        "sports",
    ],
    "Expression_Action": [
        "activity",
        "combat_actions",
        "dances",
        "emotion",
        "gesture",
        "gestures",
        "interaction",
        "personality",
        "pose",
        "posture",
        "verbs_and_gerunds",
    ],
    "Food_Object": [
        "board_games",
        "cards",
        "containers",
        "etc",
        "food_tags",
        "furniture",
        "instruments",
        "technology",
        "tools",
        "vehicles",
        "weapons",
    ],
    "Location_Background": [
        "backgrounds",
        "etc",
        "fire",
        "landmark",
        "locations",
        "nature",
        "real_world_locations",
        "time",
        "water",
        "weather",
    ],
    "NSFW": [
        "censorship",
        "etc",
        "meme",
        "nudity",
        "sex_acts",
        "sex_objects",
        "sexual_activity",
        "sexual_positions",
        "sexual_situation",
        "simulated_sex_acts",
        "symbol",
        "taboo",
    ],
    "Person_Body": [
        "ass",
        "body_parts",
        "body_type",
        "breasts_tags",
        "ears_tags",
        "etc",
        "eyes",
        "eyes_tags",
        "face",
        "face_tags",
        "hair",
        "hair_color",
        "hair_styles",
        "hands",
        "pussy",
        "relationship",
        "shoulders",
        "skin_color",
        "tail",
        "wings",
    ],
}

# 한글 표시 이름 (옵션)
CATEGORY_NAMES_KR = {
    "Clothing_Wear": "의류/착용",
    "Composition_Meta": "구도/메타",
    "Creatures": "생물",
    "Culture_Misc": "문화/기타",
    "Expression_Action": "표정/행동",
    "Food_Object": "음식/물체",
    "Location_Background": "장소/배경",
    "NSFW": "성인",
    "Person_Body": "신체",
}

# 플랫한 리스트 생성 함수
def get_flat_category_list():
    """모든 '대분류: [소분류]' 조합을 리스트로 반환"""
    result = []
    for group in sorted(CATEGORY_STRUCTURE.keys()):
        for subgroup in sorted(CATEGORY_STRUCTURE[group]):
            result.append(f"{group}: [{subgroup}]")
    return result

# 사용 예시
if __name__ == "__main__":
    # 전체 목록 출력
    for item in get_flat_category_list():
        print(item)

    print(f"\n총 {len(CATEGORY_STRUCTURE)}개 대분류")
    total = sum(len(v) for v in CATEGORY_STRUCTURE.values())
    print(f"총 {total}개 소분류")
