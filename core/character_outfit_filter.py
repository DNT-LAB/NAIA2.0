"""캐릭터 프롬프트에서 **의상만 걷어내는** 필터.

Assets 의 [불러오기시 의상 제거] 가 쓴다(사용자 지정 2026-08-25). 같은 캐릭터를 다른
옷으로 입히고 싶을 때, 저장된 프롬프트에서 옷만 빼고 꺼내 오는 것이 목적이다.

⚠️ **모르는 태그는 남긴다**(사양 변경 - 사용자 지시 2026-10-11 "중요 정보가 소실되고 있었군요").
   처음에는 화이트리스트였다: 인물 태그 + 특징 사전 + 악세서리 낱말에 걸리는 것**만** 남겼다. 그러면 사전에
   없는 것이 전부 버려진다 - 실측으로 캐릭터 이름(`sayuri (blue archive)`) · 체형(`muscular` · `thick thighs`
   · `gigantic breasts`) · 종족(`dragon` · `mermaid`) · 머리 모양(`flower braid` · `low ponytail`) ·
   장신구(`jewelry` · `ear flower`)가 빠지고 있었다(부품 카탈로그의 신체 블록 455개 중 200개가 탈락).
   지금은 거꾸로다: **의상으로 확인된 것만 뺀다.** 옷 하나가 남는 것보다 캐릭터가 바뀌는 쪽이 훨씬 나쁘다.

판정 차례(`keep_tag`):
  1. 인물 태그(girl · boy ...)                                  → 남긴다
  2. 부품 카탈로그(`data/character_parts.json` - 태그마다 블록 · 부품이 붙어 있다)
       머리 · 눈·얼굴 · 신체 · 종족                             → 남긴다 (캐릭터 자신이다)
       의상 · 소지품                                            → 뺀다
       소품·장식: 모자 · 머리 장식 · 안경·마스크 · 장식 · 작은 장신구 → 남긴다
                  소매 · 다리 · 신발 · 허리 · 가방 · 갑옷        → 뺀다 (옷과 함께 갈아입는 것)
                  목 · 손                                       → 섞여 있다: 넥타이 · 칼라 · 장갑은 빼고
                                                                  초커 · 목걸이 · 팔찌는 남긴다
  3. 카탈로그에 없으면: 특징 사전 · 악세서리 낱말에 걸리면 남기고, 의상 사전(`clothes_list.txt`)에 있으면 뺀다
  4. 어디에도 없다                                              → **남긴다**

⚠️ 의상 사전만으로 빼면 안 된다 - 그 목록에 `hat` · `hairclip` · `hair ornament` · `ribbon` 이 들어 있어
   모자와 악세서리가 같이 날아간다(실측). 그래서 카탈로그와 악세서리 낱말을 **먼저** 본다.

⚠️ **목·상의 부속은 악세서리로 치지 않는다.** `necktie` · `bowtie` · `sailor collar` · `hood` · `scarf` 는
   교복 · 후드티의 일부다 - 옷을 갈아입히려고 쓰는 기능에서 그것만 남으면 어색하다.

⚠️ 가중치 묶음(`1.2::a, b ::`)은 묶음째로 다룬다. 쉼표로만 자르면 `1.2::a` 와 `b ::` 가 따로 놀아,
   하나만 빠질 때 여는 쪽이나 닫는 쪽이 사라져 뒤의 태그가 전부 가중치를 뒤집어쓴다.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Iterable

# 인물 수 태그. 캐릭터 블록은 보통 `girl` / `boy` 로 시작한다.
PERSON_TAGS = frozenset({
    "girl", "boy", "other", "female", "male", "woman", "man",
    "1girl", "1boy", "1other", "2girls", "2boys", "2others",
})

# 모자·머리 착용물
_HEADWEAR_WORDS = frozenset({
    "hat", "cap", "beret", "helmet", "hood", "crown", "tiara", "headband",
    "headdress", "headgear", "veil", "bonnet", "visor", "hairband", "kanzashi",
    "circlet", "diadem", "turban", "nightcap", "mortarboard",
})
# 장신구
_ACCESSORY_WORDS = frozenset({
    "earring", "earrings", "necklace", "pendant", "bracelet", "bangle", "anklet",
    "choker", "brooch", "badge", "charm", "ornament", "scrunchie",
    "ribbon", "bow", "glasses", "goggles", "monocle", "eyepatch", "mask",
    "piercing", "hairclip", "hairpin", "barrette", "armlet", "armband",
    "wristband", "amulet", "locket", "lanyard", "medal", "jewelry",
})
# 씨앗에서 **빼는** 것 - 옷의 일부다(위 주석 참조).
_GARMENT_NECKWEAR = frozenset({
    "necktie", "bowtie", "ascot", "cross tie", "neckerchief", "sailor collar",
    "hood", "scarf", "shawl", "feather boa", "neck ruff", "balaclava", "chin strap",
    "collar",
})

# ── 부품 카탈로그로 가르는 선 ──
_CATALOG_KEEP_BLOCKS = frozenset({"hair", "face", "body", "species"})
# '소품·장식' 블록 가운데 옷을 갈아입혀도 남는 것(사용자 지정: 악세서리 · 모자).
_CATALOG_KEEP_PARTS = frozenset({
    "cloth_headwear", "cloth_hairacc", "cloth_eyewear", "cloth_accessory", "cloth_small",
})
# 섞여 있는 부품: 이 낱말이 들어 있으면 옷이고(뺀다), 아니면 장신구다(남긴다).
_CATALOG_MIXED_PARTS = {
    "cloth_neck": frozenset({
        "necktie", "bowtie", "tie", "collar", "scarf", "ascot", "neckerchief", "boa", "ruff", "towel",
    }),
    "cloth_handwear": frozenset({
        "gloves", "glove", "mittens", "mitts", "gauntlets", "yugake", "sleeve", "cuffs", "cuff",
        "wraps", "wrap", "armwear", "cots", "handbag", "armbands",
    }),
}
# 색을 앞에 붙인 변형(`white panties` · `black dress`)은 카탈로그에 원형만 있다 - 색을 떼고 다시 찾는다.
_COLOR_WORDS = frozenset({
    "white", "black", "red", "blue", "green", "yellow", "pink", "purple", "orange", "brown", "grey", "gray",
    "aqua", "beige", "silver", "gold", "blonde", "dark", "light",
})

_WORD_RE = re.compile(r"[a-z0-9']+")
_HAIR_RE = re.compile(r"\bhair\b")
_WEIGHT_OPEN_RE = re.compile(r"^(-?\d+(?:\.\d+)?::)\s*(.*)$", re.S)

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {}


def _data_dir(repo_root: str | Path | None = None) -> Path:
    base = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    return base / "data"


def _lines(path: Path) -> set[str]:
    return {line.strip().lower() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def _vocabulary(repo_root: str | Path | None = None) -> dict[str, Any]:
    """사전 넷: 특징 · 악세서리 씨앗 · 의상 · 부품 카탈로그. 읽기 실패는 빈 것으로 삼킨다 -
    사전이 없으면 아무것도 '의상으로 확인' 되지 않아 그대로 남는다(잃는 것이 없는 쪽으로 무너진다)."""
    data = _data_dir(repo_root)
    key = str(data)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        traits: set[str] = set()
        seed: set[str] = set()
        clothes: set[str] = set()
        catalog: dict[str, tuple[str, str]] = {}
        try:
            traits = _lines(data / "characteristic_list.txt")
        except Exception as exc:  # noqa: BLE001 - 사전이 없어도 기능이 죽으면 안 된다
            print(f"[warn] outfit filter: characteristic list unavailable: {exc}", flush=True)
        try:
            regions = json.loads(
                (data / "taglist" / "clothing_regions.json").read_text(encoding="utf-8")
            )["regions"]
            seed = {tag.lower() for tag in regions.get("HEAD_NECK_FACE", [])}
            seed |= {
                tag.lower() for tag in regions.get("ARMS_HANDS", [])
                if any(word in tag.lower() for word in ("anklet", "armband", "armlet",
                                                        "bracelet", "bangle", "ring"))
            }
            seed -= _GARMENT_NECKWEAR
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] outfit filter: clothing regions unavailable: {exc}", flush=True)
        try:
            clothes = _lines(data / "clothes_list.txt")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] outfit filter: clothes list unavailable: {exc}", flush=True)
        try:
            index = json.loads((data / "character_parts.json").read_text(encoding="utf-8"))["index"]
            catalog = {str(tag).lower(): (str(entry[0]), str(entry[1])) for tag, entry in index.items()}
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] outfit filter: parts catalog unavailable: {exc}", flush=True)
        result = {"traits": frozenset(traits), "seed": frozenset(seed),
                  "clothes": frozenset(clothes), "catalog": catalog}
        _CACHE[key] = result
        return result


def _load(repo_root: str | Path | None = None) -> tuple[frozenset[str], frozenset[str]]:
    """(캐릭터 특징 집합, 악세서리 씨앗 집합)."""
    vocabulary = _vocabulary(repo_root)
    return vocabulary["traits"], vocabulary["seed"]


def is_accessory_or_headwear(tag: str, repo_root: str | Path | None = None) -> bool:
    """모자·머리 착용물·장신구인가 (낱말로 본다 - 카탈로그에 없는 태그의 잣대)."""
    text = str(tag or "").strip().lower()
    if not text or text in _GARMENT_NECKWEAR:
        return False
    traits, seed = _load(repo_root)
    if text in seed:
        return True
    words = set(_WORD_RE.findall(text))
    if words & _HEADWEAR_WORDS or words & _ACCESSORY_WORDS:
        return True
    # `hair ornament` / `hair bow` 처럼 머리에 다는 것. 특징 사전에 있는 `long hair`
    # 같은 것은 이미 위에서 남으므로 여기서 또 볼 필요가 없다.
    return bool(_HAIR_RE.search(text) and text not in traits)


def _catalog_entry(text: str, catalog: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    entry = catalog.get(text)
    if entry is not None:
        return entry
    words = text.split(" ")
    while len(words) > 1 and words[0] in _COLOR_WORDS:      # `light blue skirt` 처럼 둘이 붙기도 한다
        words = words[1:]
        entry = catalog.get(" ".join(words))
        if entry is not None:
            return entry
    return None


def _catalog_verdict(text: str, entry: tuple[str, str]) -> bool:
    block, part = entry
    if block in _CATALOG_KEEP_BLOCKS:
        return True
    if block != "accessory":
        return False                    # 의상 · 소지품
    if part in _CATALOG_KEEP_PARTS:
        return True
    garment_words = _CATALOG_MIXED_PARTS.get(part)
    if garment_words is None:
        return False                    # 소매 · 다리 · 신발 · 허리 · 가방 · 갑옷
    return not (set(_WORD_RE.findall(text)) & garment_words)


def keep_tag(tag: str, repo_root: str | Path | None = None) -> bool:
    """이 태그를 '의상 제거' 후에도 남길 것인가. **의상으로 확인된 것만** False 다."""
    text = str(tag or "").strip().lower()
    if not text:
        return False
    if text in PERSON_TAGS:
        return True
    if text in _GARMENT_NECKWEAR:
        return False
    vocabulary = _vocabulary(repo_root)
    entry = _catalog_entry(text, vocabulary["catalog"])
    if entry is not None:
        return _catalog_verdict(text, entry)
    if text in vocabulary["traits"]:
        return True
    if is_accessory_or_headwear(text, repo_root):
        return True
    if text in vocabulary["clothes"]:
        return False
    return True                         # 모르는 태그 - 캐릭터 이름 · 표정 · 자세 · 새 태그


def _bare(piece: str) -> str:
    """판정에 쓸 맨 태그. 강조 괄호(`{{tag}}` · `[tag]`)는 떼고 본다 - 둥근 괄호는 태그의 일부다."""
    return piece.strip().strip("{}[]").strip()


def strip_outfit_tags(prompt: str, repo_root: str | Path | None = None) -> str:
    """캐릭터 프롬프트에서 의상을 걷어낸다. 남는 것이 없으면 **원본을 돌려준다**.

    ⚠️ 빈 문자열을 돌려주면 캐릭터 칸이 통째로 비어 무엇이 잘못됐는지 알 수 없다 - 그럴 바에는
       안 거른 채로 두는 편이 낫다.
    """
    text = str(prompt or "")
    if not text.strip():
        return text
    out: list[str] = []
    group: dict[str, Any] | None = None            # 열려 있는 가중치 묶음 {prefix, kept}
    for raw in text.split(","):
        piece = raw.strip()
        if not piece:
            continue
        opened = _WEIGHT_OPEN_RE.match(piece) if group is None else None
        if opened:
            group = {"prefix": opened.group(1), "kept": []}
            piece = opened.group(2).strip()
        closes = piece.endswith("::")
        if closes:
            piece = piece[:-2].strip()
        keep = bool(piece) and keep_tag(_bare(piece), repo_root)
        if group is None:
            if keep:
                out.append(f"{piece} ::" if closes else piece)
            continue
        if keep:
            group["kept"].append(piece)
        if closes:
            if group["kept"]:
                out.append(f'{group["prefix"]}{", ".join(group["kept"])} ::')
            group = None
    if group is not None and group["kept"]:        # 닫히지 않은 묶음 - 쓴 대로 둔다
        out.append(group["prefix"] + ", ".join(group["kept"]))
    if not out:
        return text
    return ", ".join(out)


def preview(tags: Iterable[str], repo_root: str | Path | None = None) -> dict[str, list[str]]:
    """무엇이 남고 무엇이 빠지는지. 진단·시험용."""
    items = [str(tag).strip() for tag in tags if str(tag).strip()]
    return {
        "kept": [tag for tag in items if keep_tag(tag, repo_root)],
        "dropped": [tag for tag in items if not keep_tag(tag, repo_root)],
    }
