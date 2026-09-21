# -*- coding: utf-8 -*-
"""믹스 조합 <-> PE 프리셋 다리 (사용자 지정 2026-09-21).

두 방향이다.

- **내보내기**: 지금 띠를 프리셋 하나로 굽는다. 프리셋 글에는 표식을 **펼친 글자 그대로**
  쓴다 - `<anchor:3>` 을 남기면 띠 없이 그 프리셋을 쓸 때 짝 없는 표식이 조용히 지워져
  작가가 빠진 그림이 나온다(`core.artist_anchor.expand_tags`). 왕복용으로 띠 구조의
  **사본**(`artist_mix`)도 함께 싣되, 글의 **지문**이 맞을 때만 믿는다 - 내보낸 뒤
  손으로 고친 글에서 낡은 사본이 엉뚱한 작가를 되살리면 안 된다.
- **가져오기**: 프리셋 글에서 아티스트 토큰을 읽어 띠 모양(`blocks`)으로 돌려준다.
  글 속 **위치는 옮기지 않는다** - 다른 프리셋의 자리는 지금 글에서 뜻이 없다.
  복원은 기존 규칙대로 지금 글 맨 앞에 새 표식을 넣는다(프론트 `restoreMix`).

⚠️ 여기는 **순수 함수**만 둔다. 저장소·세션을 만지는 것은 라우트 쪽 한 곳이다.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Callable, Iterable

from core.artist_anchor import ANCHOR_PATTERN, expand_text, has_anchor, normalize_groups

COPY_SCHEMA = 1
COLLAB_NAME = "artist collaboration"
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_NAI_OPEN = re.compile(rf"^({_NUMBER})::\s*")
_SD_WEIGHTED = re.compile(rf"^\((.*):\s*({_NUMBER})\)$", re.S)


# ── 토큰 가르기 ─────────────────────────────────────────────────────────────

def split_top(text: str) -> list[str]:
    """쉼표로 가르되 **괄호 안의 쉼표는 가르지 않는다**(SD `(a, b:1.2)`).

    ⚠️ 이스케이프된 괄호(`\\(`)는 깊이를 안 바꾼다 - SD 는 작가 이름 속 괄호를
       `hammer \\(sunset beach\\)` 로 쓴다. 원문 조각을 **그대로** 돌려준다
       (앞뒤 공백까지) - 작가 빼기가 나머지 글의 모양을 지키려면 필요하다.
    """
    pieces: list[str] = []
    depth = 0
    start = 0
    i = 0
    s = str(text or "")
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")" and depth:
            depth -= 1
        elif ch == "," and depth == 0:
            pieces.append(s[start:i])
            start = i + 1
        i += 1
    pieces.append(s[start:])
    return pieces


def _unescape(name: str) -> str:
    return re.sub(r"\\([()\[\]{}])", r"\1", name)


def _dict_key(name: str) -> str:
    return " ".join(_unescape(name).replace("_", " ").split()).casefold()


def _unwrap_emphasis(token: str) -> tuple[str, float]:
    """NAI 옛 강조 `{x}` = ×1.05, `[x]` = ÷1.05. 통째로 감싼 것만 벗긴다."""
    factor = 1.0
    while len(token) >= 2 and token[0] + token[-1] in ("{}", "[]"):
        factor *= 1.05 if token[0] == "{" else 1 / 1.05
        token = token[1:-1].strip()
    return token, factor


def _classify(body: str, known: set[str], allow_bare: bool = False) -> dict:
    """몸통 하나 -> {kind, artist, with_prefix}. kind: artist | collab | anchor | other | empty."""
    token = " ".join(str(body or "").split())
    if not token:
        return {"kind": "empty"}
    if ANCHOR_PATTERN.fullmatch(token):
        return {"kind": "anchor"}
    if token.casefold() == COLLAB_NAME:
        return {"kind": "collab"}
    if token[:7].casefold() == "artist:":
        name = _unescape(token[7:]).strip()
        return {"kind": "artist", "artist": name, "with_prefix": True, "known": _dict_key(name) in known} \
            if name else {"kind": "other"}
    if token.startswith("@") and len(token) > 1:          # Anima
        name = _unescape(token[1:]).strip()
        return {"kind": "artist", "artist": name, "with_prefix": True, "known": _dict_key(name) in known}
    key = _dict_key(token)
    if allow_bare and key in known:
        # 접두 없는 SD 토큰은 **사전에 있을 때만** 작가다(1girl 을 작가로 올리지 않는다).
        return {"kind": "artist", "artist": " ".join(_unescape(token).replace("_", " ").split()),
                "with_prefix": True, "known": True}
    return {"kind": "other"}


def parse_pieces(text: str, *, known: Iterable[str] = (), allow_bare: bool = False) -> list[dict]:
    """글 -> 조각 목록(순서 그대로). 조각마다 원문(`raw`)과 분류, 가중치, 묶음 번호.

    묶음(`group`)은 NAI `w::a, b ::` 과 SD `(a, b:w)`. 묶음 안의 조각은 같은 번호를
    갖고, 중첩 깊이(`depth`)가 1 이 아니면 동기화 앵커로 되살리지 않는다.
    `allow_bare=False`(NAI)면 접두 없는 이름은 사전에 있어도 작가가 아니다 -
    NAI 글에서 작가는 늘 `artist:` 를 단다.
    """
    known_set = {str(k).casefold() for k in known}
    out: list[dict] = []
    stack: list[tuple[int, float]] = []   # (group id, weight)
    next_group = 0
    for raw in split_top(text):
        token = raw.strip()
        piece: dict[str, Any] = {"raw": raw}
        # SD 묶음/가중치 - 조각 하나가 괄호 한 덩이다.
        sd = _SD_WEIGHTED.match(token)
        if sd:
            inner = split_top(sd[1])
            weight = float(sd[2])
            members = [m for m in inner if m.strip()]
            if len(members) > 1:
                next_group += 1
                piece.update({"kind": "group", "group": next_group, "depth": 1, "weight": weight,
                              "members": [{**_classify(m, known_set, allow_bare), "raw": m} for m in members]})
            else:
                info = _classify(members[0] if members else "", known_set, allow_bare)
                piece.update(info, weight=weight, group=None, depth=0)
            out.append(piece)
            continue
        opened = 0
        while head := _NAI_OPEN.match(token):
            next_group += 1
            stack.append((next_group, float(head[1])))
            token = token[head.end():]
            opened += 1
        closes = 0
        while token.endswith("::"):
            token = token[:-2].rstrip()
            closes += 1
        token, emphasis = _unwrap_emphasis(token)
        weight = math.prod(w for _gid, w in stack) * emphasis
        info = _classify(token, known_set, allow_bare)
        # 여기서 열고 여기서 닫힌 묶음은 조각 하나짜리 가중치다(`1.2::artist:a ::`).
        single = bool(stack) and opened >= 1 and closes >= 1 and len(stack) == opened
        piece.update(info, weight=round(weight, 4),
                     group=None if not stack or single else stack[0][0],
                     depth=0 if single else len(stack))
        out.append(piece)
        for _ in range(min(closes, len(stack))):
            stack.pop()
    return out


def _is_artist(piece: dict) -> bool:
    return piece.get("kind") == "artist"


def _groups(pieces: list[dict]) -> dict[int, list[dict]]:
    groups: dict[int, list[dict]] = {}
    for piece in pieces:
        if piece.get("group") is not None and piece.get("kind") != "group":
            groups.setdefault(piece["group"], []).append(piece)
    return groups


def _group_members(piece_or_members: list[dict]) -> list[dict]:
    return [m for m in piece_or_members if m.get("kind") != "empty"]


def _eligible(members: list[dict]) -> bool:
    """동기화 앵커로 되살릴 묶음인가: **작가만** 둘 이상, 중첩 없음."""
    live = _group_members(members)
    return len(live) >= 2 and all(_is_artist(m) for m in live) and all(m.get("depth", 1) == 1 for m in live)


# ── 가져오기 ────────────────────────────────────────────────────────────────

def _artist_block(piece: dict, weight: float) -> dict:
    return {"kind": "artist", "artist": piece["artist"], "weight": round(float(weight), 2),
            "with_prefix": bool(piece.get("with_prefix", True)), "enabled": True}


def blocks_from_text(pre: str, post: str, *, known: Iterable[str] = (), allow_bare: bool = False) -> dict:
    """prefix/postfix -> 띠 모양. 위치는 옮기지 않는다(모듈 머리말).

    - prefix 의 낱 작가 -> 첫 앵커 **앞**(= Artist Prompt, prefix 앞에 붙는다)
    - 작가만 든 묶음    -> 동기화 앵커 하나 + 그 작가들(같은 껍데기를 다시 내는 유일한 길)
    - 작가 아닌 태그가 섞인 묶음 -> 작가만 **각자** 그 가중치로
    - postfix 쪽은 앵커(slot=post) 아래로 - postfix 에 있던 작가가 앞으로 튀지 않게
    """
    known_list = list(known)
    lead: list[dict] = []
    tail: list[dict] = []
    collab: dict | None = None
    unknown: list[str] = []
    for slot, text in (("pre", pre), ("post", post)):
        pieces = parse_pieces(text, known=known_list, allow_bare=allow_bare)
        plain: list[dict] = []
        grouped: list[list[dict]] = []
        seen_groups: set[int] = set()
        nai_groups = _groups(pieces)
        for piece in pieces:
            kind = piece.get("kind")
            if kind == "group":                              # SD 묶음
                members = [{**m, "depth": 1} for m in piece["members"]]
                if _eligible(members):
                    grouped.append([_artist_block(m, piece["weight"]) for m in _group_members(members)])
                else:
                    plain.extend(_artist_block(m, piece["weight"]) for m in members if _is_artist(m))
                continue
            gid = piece.get("group")
            if gid is not None and _eligible(nai_groups.get(gid, [])):
                if gid not in seen_groups:
                    seen_groups.add(gid)
                    members = _group_members(nai_groups[gid])
                    grouped.append([_artist_block(m, m["weight"]) for m in members])
                continue
            if kind == "collab":
                collab = {"kind": "collab", "weight": round(float(piece.get("weight", -1)), 2), "enabled": True}
            elif kind == "artist":
                plain.append(_artist_block(piece, piece.get("weight", 1)))
        if slot == "pre":
            lead.extend(plain)
            for members in grouped:
                tail.append({"kind": "anchor", "slot": "pre", "sync": True})
                tail.extend(members)
        else:
            if plain:
                tail.append({"kind": "anchor", "slot": "post", "sync": False})
                tail.extend(plain)
            for members in grouped:
                tail.append({"kind": "anchor", "slot": "post", "sync": True})
                tail.extend(members)
        for piece in pieces if known_list else ():
            for m in (piece.get("members") or [piece]):
                if _is_artist(m) and not m.get("known") and m["artist"] not in unknown:
                    unknown.append(m["artist"])
    blocks = [*lead, *tail]
    if collab:
        blocks.append(collab)
    return {"blocks": blocks, "unknown": unknown}


def strip_artists(text: str, *, known: Iterable[str] = (), allow_bare: bool = False,
                  drop_anchors: bool = False) -> dict:
    """글에서 작가 토큰을 뺀다(같은 프리셋에서 가져올 때 두 번 나가지 않게).

    ⚠️ **묶음은 통째로만** 뺀다. `1.2::artist:a, masterpiece ::` 에서 a 만 빼면
       `1.2::masterpiece ::` 가 남아 가중치가 다른 태그에 붙는다 - 그런 묶음은 손대지
       않고 `kept` 로 알린다. 원문 조각을 그대로 이어 붙여 나머지 글의 모양을 지킨다.
    `drop_anchors`: 표식 조각(`<anchor:N>`)도 뺀다. 가져오기는 표식을 **새로** 넣는데,
    옛 표식이 남아 있으면 새 번호와 겹쳐 옛 자리에 눌러앉는다.
    """
    pieces = parse_pieces(text, known=list(known), allow_bare=allow_bare)
    groups = _groups(pieces)
    kept_raw: list[str] = []
    removed: list[str] = []
    kept_groups: list[str] = []
    removed_gid = None
    for piece in pieces:
        kind = piece.get("kind")
        gid = piece.get("group")
        if gid is None or kind == "group":
            removed_gid = None
        if kind == "group":
            members = piece["members"]
            if all(_is_artist(m) or m.get("kind") in {"collab", "empty"} for m in members):
                removed.append(piece["raw"].strip())
                continue
            if any(_is_artist(m) for m in members):
                kept_groups.append(piece["raw"].strip())
            kept_raw.append(piece["raw"])
            continue
        if gid is not None:
            members = groups.get(gid, [])
            if all(_is_artist(m) or m.get("kind") in {"collab", "empty"} for m in members):
                # 한 묶음은 **한 줄**로 알린다 - 조각마다 적으면 `1.2::artist:a` 와
                # `artist:b ::` 가 따로 보여 무엇이 빠지는지 읽히지 않는다(실측 2026-09-21).
                if removed_gid == gid and removed:
                    removed[-1] = f"{removed[-1]}, {piece['raw'].strip()}"
                else:
                    removed.append(piece["raw"].strip())
                removed_gid = gid
                continue
            if _is_artist(piece):
                kept_groups.append(piece["raw"].strip())
            kept_raw.append(piece["raw"])
            continue
        if kind in {"artist", "collab"}:
            removed.append(piece["raw"].strip())
            continue
        if kind == "anchor" and drop_anchors:
            continue
        kept_raw.append(piece["raw"])
    stripped = ",".join(kept_raw).strip().strip(",").strip()
    return {"text": stripped, "removed": [r for r in removed if r], "kept": kept_groups}


# ── 지문 · 내보내기 ─────────────────────────────────────────────────────────

def fingerprint(pre: str, post: str) -> str:
    """글의 지문. 공백·빈 조각은 무시한다(다시 저장하며 모양만 바뀐 것은 같은 글이다)."""
    def norm(text: str) -> str:
        return ",".join(" ".join(p.split()) for p in str(text or "").split(",") if p.strip())
    return hashlib.sha1(f"{norm(pre)}\x1f{norm(post)}".encode("utf-8")).hexdigest()[:16]


def baked_texts(pre: str, post: str, artist_prompt: str, anchor_groups: Any) -> dict:
    """생성 때 나가는 것과 **같은** 글을 만든다: 선행부 + 표식을 펼친 prefix / postfix.

    ⚠️ 펼친 뒤에도 표식이 남으면 **실패**다 - 파일에 표식을 박는 길을 막는 목이다.
    """
    groups = normalize_groups(anchor_groups)
    lead = str(artist_prompt or "").strip().strip(",").strip()
    baked_pre = expand_text(pre, groups)
    baked_post = expand_text(post, groups)
    if lead:
        baked_pre = f"{lead}, {baked_pre}" if baked_pre else lead
    if has_anchor(baked_pre) or has_anchor(baked_post):
        raise ValueError("앵커 표식을 펼치지 못했습니다 - 내보내지 않았습니다.")
    return {"pre": baked_pre, "post": baked_post}


def copy_record(blocks: Any, pre: str, post: str) -> dict:
    """프리셋에 함께 싣는 띠 구조 사본. 임시 칸은 이미 저장 모양에서 빠져 있다."""
    rows = [dict(b) for b in (blocks if isinstance(blocks, list) else [])[:400] if isinstance(b, dict)]
    return {"schema": COPY_SCHEMA, "blocks": rows, "fingerprint": fingerprint(pre, post)}


def import_blocks(data: dict, pre: str, post: str, *, known_fn: Callable[[], Iterable[str]],
                  allow_bare: bool) -> dict:
    """프리셋 -> 띠. 사본이 있고 **지문이 맞으면** 사본(무손실), 아니면 글을 읽는다."""
    copy = data.get("artist_mix") if isinstance(data, dict) else None
    if isinstance(copy, dict) and copy.get("fingerprint") == fingerprint(pre, post) \
            and isinstance(copy.get("blocks"), list) and copy["blocks"]:
        return {"blocks": copy["blocks"], "unknown": [], "source": "copy"}
    parsed = blocks_from_text(pre, post, known=known_fn(), allow_bare=allow_bare)
    stale = isinstance(copy, dict) and bool(copy.get("blocks"))
    return {**parsed, "source": "parsed", "stale_copy": stale}
