"""캐릭터 프롬프트에서 **의상만 걷어내는** 필터.

Assets 의 [불러오기시 의상 제거] 가 쓴다(사용자 지정 2026-08-25). 같은 캐릭터를 다른
옷으로 입히고 싶을 때, 저장된 프롬프트에서 정체성만 꺼내 오는 것이 목적이다.

⚠️ **화이트리스트다.** 사용자 지정은 "girl/boy + 캐릭터 특징 + 악세서리, 모자**만**
   검출" 이었다. 의상 목록(`data/clothes_list.txt`, 11,091개)을 빼는 블랙리스트로 짜면
   그 목록에 `hat`·`hairclip`·`hair ornament`·`ribbon` 이 들어 있어 **모자와 악세서리가
   같이 날아간다**(실측). 남길 것을 세는 쪽이 맞다.

⚠️ 계열 낱말을 함께 본다. 씨앗(`clothing_regions.json` 의 HEAD_NECK_FACE, 70개)만으로는
   `beret`·`witch hat`·`baseball cap` 같은 변형이 안 잡힌다 - 의상 사전이 11,091개라
   변형이 훨씬 많다.

⚠️ **목·상의 부속은 악세서리로 치지 않는다.** `necktie`·`bowtie`·`sailor collar`·
   `hood`·`scarf` 는 씨앗에 들어 있지만(그 파일은 '의류 Region 추적용'이라 그렇다)
   교복·후드티의 일부다 - 옷을 갈아입히려고 쓰는 기능에서 그것만 남으면 어색하다.
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
    "wristband", "amulet", "locket", "lanyard", "medal",
})
# 씨앗에서 **빼는** 것 - 옷의 일부다(위 주석 참조).
_GARMENT_NECKWEAR = frozenset({
    "necktie", "bowtie", "ascot", "cross tie", "neckerchief", "sailor collar",
    "hood", "scarf", "shawl", "feather boa", "neck ruff", "balaclava", "chin strap",
    "collar",
})
_WORD_RE = re.compile(r"[a-z0-9']+")
_HAIR_RE = re.compile(r"\bhair\b")

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {}


def _data_dir(repo_root: str | Path | None = None) -> Path:
    base = Path(repo_root) if repo_root else Path(__file__).resolve().parents[1]
    return base / "data"


def _load(repo_root: str | Path | None = None) -> tuple[frozenset[str], frozenset[str]]:
    """(캐릭터 특징 집합, 악세서리 씨앗 집합). 읽기 실패는 빈 집합으로 삼킨다."""
    with _LOCK:
        cached = _CACHE.get("sets")
        if cached is not None:
            return cached
        data = _data_dir(repo_root)
        traits: set[str] = set()
        seed: set[str] = set()
        try:
            raw = (data / "characteristic_list.txt").read_text(encoding="utf-8")
            traits = {line.strip().lower() for line in raw.splitlines() if line.strip()}
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
        result = (frozenset(traits), frozenset(seed))
        _CACHE["sets"] = result
        return result


def is_accessory_or_headwear(tag: str, repo_root: str | Path | None = None) -> bool:
    """모자·머리 착용물·장신구인가."""
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


def keep_tag(tag: str, repo_root: str | Path | None = None) -> bool:
    """이 태그를 '의상 제거' 후에도 남길 것인가."""
    text = str(tag or "").strip().lower()
    if not text:
        return False
    if text in PERSON_TAGS:
        return True
    traits, _seed = _load(repo_root)
    if text in traits:
        return True
    return is_accessory_or_headwear(text, repo_root)


def strip_outfit_tags(prompt: str, repo_root: str | Path | None = None) -> str:
    """캐릭터 프롬프트에서 의상을 걷어낸다. 남는 것이 없으면 **원본을 돌려준다**.

    ⚠️ 빈 문자열을 돌려주면 캐릭터 칸이 통째로 비어 무엇이 잘못됐는지 알 수 없다 -
       사전을 못 읽었을 때(위 `_load` 의 방어)가 정확히 그 경우다. 그럴 바에는
       안 거른 채로 두는 편이 낫다.
    """
    text = str(prompt or "")
    if not text.strip():
        return text
    tags = [part.strip() for part in text.split(",")]
    kept = [tag for tag in tags if tag and keep_tag(tag, repo_root)]
    if not kept:
        return text
    return ", ".join(kept)


def preview(tags: Iterable[str], repo_root: str | Path | None = None) -> dict[str, list[str]]:
    """무엇이 남고 무엇이 빠지는지. 진단·시험용."""
    items = [str(tag).strip() for tag in tags if str(tag).strip()]
    return {
        "kept": [tag for tag in items if keep_tag(tag, repo_root)],
        "dropped": [tag for tag in items if not keep_tag(tag, repo_root)],
    }
