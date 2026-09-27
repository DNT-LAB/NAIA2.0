"""메인 프롬프트 추천 카드의 태그 관계 팩(`data/tag_relation_pack.json`) 읽기.

팩은 `tools/build_tag_relation_pack.py` 가 Codex 의 관계 지도에서 미리 구운 것이다. 태그마다
유형별(siblings · variations · companions · attributes · state · action · parts · context) 추천 목록과
누르면 할 일(op: 바꾸기/더하기)이 순서대로 들어 있고, `ko` 에는 카드에 보일 한국어 설명의 검토판
(Codex 대표 문장 - 지금 사전 설명과 다른 것만)이 있다. 여기서는 **읽기만** 한다 - 판정과 순서는
빌더 한 곳이 정한다.

파일이 없거나 형식이 다르면 빈 팩으로 떨어진다. 추천 줄만 안 보이고 태그 카드는 산다.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Iterable

PACK_FILENAME = "tag_relation_pack.json"
SCHEMA = "naia.tag-relation-pack.v1"
OPS = {0: "add", 1: "replace"}

_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "pack": None}


def find_pack(data_roots: Iterable[Path | str]) -> Path | None:
    for root in data_roots:
        path = Path(root) / PACK_FILENAME
        if path.is_file():
            return path
    return None


def load_pack(data_roots: Iterable[Path | str]) -> dict[str, Any]:
    """팩을 한 번 읽어 둔다. 파일을 갈아 끼우면(크기·시각이 바뀌면) 다시 읽는다."""
    path = find_pack(data_roots)
    if path is None:
        return {}
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["pack"]
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pack = {}
        if not isinstance(pack, dict) or pack.get("schema") != SCHEMA or not isinstance(pack.get("seeds"), dict):
            print(f"Remote: tag relation pack ignored ({path.name}: unknown schema)")
            pack = {}
        _cache["key"] = key
        _cache["pack"] = pack
        return pack


def _key(tag: Any) -> str:
    return " ".join(str(tag or "").split()).lower()


def korean_description(pack: dict[str, Any], tag: Any) -> str | None:
    """카드에 보일 한국어 설명의 검토판. 없으면 None - 호출자는 사전 설명을 그대로 쓴다.

    **표시 전용**이다. 검색 색인은 원래 설명을 읽는다(새 문장의 '~는 제외한다' 가 검색에 걸리는
    부작용 - 2026-09-26 실측, 결정 전까지 바꾸지 않는다).
    """
    ko = pack.get("ko") if isinstance(pack, dict) else None
    if not isinstance(ko, dict) or not tag:
        return None
    key = _key(tag)
    text = ko.get(key) or ko.get(key.replace("_", " "))
    return text if isinstance(text, str) and text.strip() else None


# 추천 프롬프트(사용자 지정 2026-09-27): 고른 태그 하나에서 **함께 1 · 상태 1** 을 더하기만. 색·무늬·모양(스타일)은
# 취향이라 뺀다. 장면을 뒤집는 상태(벗음·부재·찢김·한쪽만)도 뺀다 - 시제품에서 hat + unworn hat 같은 모순이 나왔다.
# 프롬프트를 고치지 않는다(Codex 계약: 사용자가 고른다) - 칩으로 보여 줄 뿐이다.
FILL_KINDS = ("companions", "state")
FLIP_STATE_WORDS = ("unworn", "no ", "torn", "removed", "removing", "undressing", "detached", "single ")
PROMPT_TAG_LIMIT = 150
_PEOPLE = re.compile(r"^(\d+)\+?(girl|boy|other)s?$")
_CROWD_TAGS = {"multiple girls", "multiple boys", "multiple others"}


def people_count(tags: Iterable[str]) -> int:
    """프롬프트의 인원(1girl=1, 2boys=2, 6+girls=6, multiple girls=2 …). solo 를 권해도 되는지 가른다."""
    total = 0
    for tag in tags:
        hit = _PEOPLE.match(tag)
        if hit:
            total += int(hit.group(1))
        elif tag in _CROWD_TAGS:
            total += 2
    return total


def _rivals(rows: Any) -> set[str]:
    """배타 축의 대안(⇄ 형제) - 같이 있으면 모순이다(short hair · long hair)."""
    if not isinstance(rows, dict):
        return set()
    return {e[0] for e in rows.get("siblings", []) if isinstance(e, list) and len(e) >= 2 and e[1] == 1}


def fill_recommendation(pack: dict[str, Any], tag: str, prompt_tags: Iterable[str], *, keep=None) -> list[dict[str, Any]]:
    """고른 태그의 추천 프롬프트 [{"tag", "type"}] - 함께 1 · 상태 1, 관련도 앞에서부터 거르며 고른다.

    prompt_tags = 메인 칸의 **명확한 태그**(호출자가 사전에 있는 것만 넘긴다 - 자연어 문장은 이미 빠졌다).
    이미 있는 것 · 이미 있는 태그와 배타 축으로 부딪히는 것 · 인원이 둘 이상인데 solo · 인원 태그 자체는 뺀다.
    """
    seeds = pack.get("seeds") if isinstance(pack, dict) else None
    if not seeds:
        return []
    key = _key(tag)
    rows = seeds.get(key) or seeds.get(key.replace("_", " "))
    if not isinstance(rows, dict):
        return []
    present = {_key(t).replace("_", " ") for t in prompt_tags if isinstance(t, str) and t.strip()}
    present.add(key)
    blocked: set[str] = set()
    for name in present:
        blocked |= _rivals(seeds.get(name))
    crowd = people_count(present) >= 2
    out: list[dict[str, Any]] = []
    for kind in FILL_KINDS:
        for entry in rows.get(kind, []):
            if not (isinstance(entry, list) and len(entry) >= 2 and isinstance(entry[0], str)):
                continue
            name, op = entry[0], entry[1]
            if op != 0 or name in present or name in blocked:
                continue
            if kind == "state" and any(word in name + " " for word in FLIP_STATE_WORDS):
                continue
            if name == "solo" and crowd:
                continue
            if _PEOPLE.match(name) or name in _CROWD_TAGS:
                continue                    # 사람을 더하면 장면이 바뀐다(1girl 의 함께 = solo, 1boy)
            if keep is not None and not keep(name):
                continue
            if _rivals(seeds.get(name)) & present:
                continue
            out.append({"tag": name, "type": kind})
            present.add(name)
            blocked |= _rivals(seeds.get(name))
            break
    return out


def recommendations(pack: dict[str, Any], tag: str, *, keep=None, limit: int = 16) -> list[dict[str, Any]]:
    """태그의 유형별 추천. [{"type": "state", "items": [{"tag": "open shirt", "op": "add", "key": 3}, ...]}, ...]

    items 는 관련도 순이다(대표 칩은 앞에서 고른다). key = 카드에 **보이는** 자리(비슷한 것끼리 + ABC,
    2026-09-27) - 옛 팩(항목이 [태그, op] 두 칸)에는 없다.

    팩의 키는 소문자·공백 표기다. 사용자가 밑줄로 친 태그(`open_shirt`)도 찾는다.
    keep 은 호출자의 '권할 값이 있는가' 술어 - 팩을 구운 뒤 사전이 바뀌어도 같은 규칙으로 거른다.
    """
    seeds = pack.get("seeds") if isinstance(pack, dict) else None
    if not seeds:
        return []
    key = " ".join(str(tag or "").split()).lower()
    rows = seeds.get(key) or seeds.get(key.replace("_", " "))
    if not isinstance(rows, dict):
        return []
    order = pack.get("types") or list(rows)
    out: list[dict[str, Any]] = []
    for kind in order:
        items = rows.get(kind)
        if not isinstance(items, list):
            continue
        picked = []
        for entry in items:
            if not isinstance(entry, list) or len(entry) not in (2, 3):
                continue
            name, op = entry[0], entry[1]
            if not isinstance(name, str) or op not in OPS or name == key:
                continue
            if keep is not None and not keep(name):
                continue
            item = {"tag": name, "op": OPS[op]}
            if len(entry) == 3 and isinstance(entry[2], int) and not isinstance(entry[2], bool):
                item["key"] = entry[2]
            picked.append(item)
            if len(picked) >= limit:
                break
        if picked:
            out.append({"type": kind, "items": picked})
    return out
