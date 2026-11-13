"""Pure prompt surgery that preserves the shells of surviving tags."""
from __future__ import annotations

from dataclasses import dataclass
import re

from core.artist_mix_preset import _dict_key, _unescape, split_top


AMBIGUOUS_BARE_ARTISTS: frozenset[str] = frozenset({
    "pink crown", "jinbei", "koichi makoto", "wakame", "the hermit",
    "qingxin gua yu", "kuzumochi", "nekomaru", "ruto (petatann)", "xinjinjumin",
    "uehara", "nuri", "a1", "nighthawk", "steamed egg", "jas", "nelt", "asha",
    "prime", "copper", "kanade", "softshikioni", "suihei",
})
_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_WEIGHT = re.compile(rf"{_NUMBER}::\s*")
_SD = re.compile(rf"^\((.*):\s*{_NUMBER}\)$", re.S)
_ANCHOR = re.compile(r"<anchor:\d+>", re.I)
_WILDCARD = re.compile(r"__.*?__|<[^<>]+>|\$[\w.-]+")


@dataclass
class _Event:
    kind: str
    text: str
    group: int = -1
    groups: tuple[int, ...] = ()
    body: str = ""
    raw: str = ""


def _wildcard(body):
    return bool(_WILDCARD.search(_ANCHOR.sub("", body)))


def _events(text):
    """Flat OPEN/CLOSE/TAG/SEP events, with matched group identities.

    Parentheses are opaque units; escaped punctuation is always literal.
    An unclosed group has no CLOSE event, including legal open NAI weights.
    """
    events = []
    stacks = {"brace": [], "bracket": [], "weight": []}
    active = []
    serial = 0
    for field_index, raw in enumerate(split_top(text)):
        leading = raw[:len(raw) - len(raw.lstrip())]
        sep = "," + leading if field_index else ""
        if field_index:
            events.append(_Event("SEP", sep))
        field_start = len(events)
        field = raw.strip()
        start = i = 0

        def tag(end):
            chunk = field[start:end].strip()
            if chunk:
                sd = _SD.fullmatch(chunk)
                body = sd[1].strip() if sd and len(split_top(sd[1])) == 1 else chunk
                events.append(_Event("TAG", chunk, groups=tuple(active),
                                     body=body, raw=raw.strip()))

        while i < len(field):
            ch = field[i]
            if ch == "\\":
                i += 2
                continue
            if field.startswith("__", i):
                # 와일드카드 이름(`__artists/[kantoku]__`)은 한 덩어리다. 안의 괄호를 껍질로 읽으면 이름이 잘린다.
                close = field.find("__", i + 2)
                if close > i + 2:
                    i = close + 2
                    continue
            if ch in "(<":
                # Parenthesized comma groups and angle markers are atomic.
                close = ")" if ch == "(" else ">"
                depth, j = 1, i + 1
                while j < len(field) and depth:
                    if field[j] == "\\":
                        j += 2
                        continue
                    if ch == "(" and field[j] == ch:
                        depth += 1
                    elif field[j] == close:
                        depth -= 1
                    j += 1
                i = j
                continue
            weight = _WEIGHT.match(field, i) if not field[start:i].strip() else None
            kind = {"{": "brace", "[": "bracket"}.get(ch)
            if weight or kind:
                tag(i)
                kind = "weight" if weight else kind
                end = weight.end() if weight else i + 1
                while end < len(field) and field[end].isspace():
                    end += 1
                serial += 1
                stacks[kind].append(serial)
                active.append(serial)
                events.append(_Event("OPEN", field[i:end], serial))
                start = i = end
                continue
            kind = {"}": "brace", "]": "bracket"}.get(ch)
            if field.startswith("::", i):
                kind = "weight"
                if not stacks[kind]:
                    # A postfix can close a weight opened in another field.
                    # Preserve that closer on surviving preceding tags without
                    # inventing an opener in this text fragment.
                    serial += 1
                    stacks[kind].append(serial)
                    active.append(serial)
                    for event in events:
                        if event.kind == "TAG":
                            event.groups += (serial,)
            if kind and stacks[kind]:
                tail = field[start:i]
                whitespace = tail[len(tail.rstrip()):]
                tag(i)
                gid = stacks[kind].pop()
                active.remove(gid)
                end = i + (2 if kind == "weight" else 1)
                events.append(_Event("CLOSE", whitespace + field[i:end], gid))
                start = i = end
                continue
            i += 1
        tag(len(field))
        # Spaces immediately before a comma belong to the preceding fragment.
        # Keep them when that fragment survives, including a moved closer.
        trailing = raw[len(raw.rstrip()):]
        if len(events) > field_start and events[-1].kind in {"TAG", "CLOSE"}:
            events[-1].text += trailing
    return events


def _classify(event, known):
    body = " ".join(event.body.split())
    if not body or _wildcard(body):
        return None
    if _ANCHOR.fullmatch(body):
        name, reason = body, "anchor"
    elif body.casefold().startswith("artist:") and body[7:].strip():
        name, reason = _unescape(body[7:]).strip(), "prefix"
    elif body.startswith("@") and body[1:].strip():
        name, reason = _unescape(body[1:]).strip(), "prefix"
    elif (_dict_key(body) in known and _dict_key(body) not in AMBIGUOUS_BARE_ARTISTS
          and _dict_key(body) != "artist collaboration" and not re.fullmatch(_NUMBER, body)):
        name, reason = " ".join(_unescape(body).replace("_", " ").split()), "dictionary"
    else:
        return None
    return {"raw": event.raw, "name": name, "reason": reason}


class _KnownKeys(frozenset):
    """Request-local normalized dictionary, reusable across a preset scan."""


# 마지막으로 정규화한 사전 한 벌. 라우트가 넘기는 사전은 세션에 한 번 담긴 같은 객체라(`_mix_known_artists`)
# 같은 객체면 다시 만들지 않는다 - 8만 4천 개를 매번 정규화하면 미리보기마다 50ms 가 든다(실측 2026-11-03).
_KNOWN_MEMO: tuple = (None, None)


def _known_keys(known):
    global _KNOWN_MEMO
    if isinstance(known, _KnownKeys):
        return known
    source, keys = _KNOWN_MEMO
    if source is known:
        return keys
    keys = _KnownKeys(_dict_key(name) for name in known)
    if isinstance(known, frozenset):
        _KNOWN_MEMO = (known, keys)
    return keys


def find_artists(text, *, known=frozenset()) -> list[dict]:
    keys = _known_keys(known)
    return [row for event in _events(text) if event.kind == "TAG"
            if (row := _classify(event, keys))]


_LAST_NUMBER = re.compile(rf"^(.*\S)\s*:\s*({_NUMBER})\s*$", re.S)


# 묶음 속 묶음을 따라 들어가는 한도. 넘으면 그 안은 한 덩어리로 둔다 - 괄호 3만 겹짜리 글이 겹마다 다시 훑여 20초 뒤
# RecursionError 로 끝났다(Codex 리뷰 2026-11-12 3차 #3). 사람이 쓰는 묶음은 두세 겹이다.
_MAX_GROUP_DEPTH = 8


def _split_group(chunk, depth=0):
    """SD 묶음 `(a, b:1.2)` · `(a, b)` -> (구성원들, 숫자 글 | None). 묶음이 아니면 None.

    `_events` 는 괄호를 한 덩어리로 둔다 - 묶음 안의 작가는 `_classify` 에 안 걸려 [이 아티스트로만 생성] 에 남았다
    (Codex 리뷰 2026-11-12 #6: `(artist:a, smile:1.2)`). 통째로 한 쌍의 괄호이고 구성원이 둘 이상이거나, 하나뿐인 구성원이
    다시 묶음일 때(`((a, b):1.2)`)만 묶음이다. 구성원이 하나인 `(name:1.2)` 는 `_events` 가 이미 벗긴다.
    """
    chunk = chunk.strip()
    if depth > _MAX_GROUP_DEPTH or len(chunk) < 2 or chunk[0] != "(" or chunk[-1] != ")":
        return None
    level = i = 0
    while i < len(chunk):                              # 통째로 한 쌍이어야 한다 - `(a) b (c)` 는 묶음이 아니다
        if chunk[i] == "\\":
            i += 2
            continue
        if chunk[i] == "(":
            level += 1
        elif chunk[i] == ")":
            level -= 1
            if level == 0 and i != len(chunk) - 1:
                return None
        i += 1
    if level:
        return None
    members = split_top(chunk[1:-1])
    number = None
    last = _LAST_NUMBER.match(members[-1])
    if last:
        members[-1], number = last[1], last[2]
    if len(members) < 2 and _split_group(members[0], depth + 1) is None:
        return None
    return members, number


def _member_artist(member, keys):
    """묶음 구성원 하나가 작가면 그 줄(+ `sd_weight`: `(name:1.2)` 꼴이면 그 숫자, 아니면 None).

    맨 위 태그와 같은 식으로 SD 한 개짜리 껍질을 벗긴다 - 안 벗기면 `(artist:a, (artist:b:1.2), smile)` 의 b 가 남는다(3차 #1).
    """
    chunk = member.strip()
    if not chunk:
        return None
    sd = _SD.fullmatch(chunk)
    single = bool(sd) and len(split_top(sd[1])) == 1
    body = sd[1].strip() if single else chunk
    row = _classify(_Event("TAG", chunk, body=body, raw=chunk), keys)
    if row:
        number = re.search(rf":\s*({_NUMBER})\)$", chunk) if single else None
        row["sd_weight"] = float(number[1]) if number else None
    return row


def _group_artists(chunk, keys, fixed, inherited, depth=0):
    """묶음 안의 작가들(가중치 포함) - 묶음 속 묶음까지. 묶음이 아니면 빈 목록.

    `fixed` = 바깥 NAI 숫자 가중치(`-0.5::( ... ) ::`) - 있으면 그것이 이긴다(부호까지). 없으면 묶음의 숫자, 그것도 없으면
    바깥에서 내려온 값의 1.1 배(SD 의 숫자 없는 괄호).
    """
    group = _split_group(chunk, depth)
    if not group:
        return []
    members, number = group
    own = float(number) if number else inherited * 1.1
    rows = []
    for member in members:
        row = _member_artist(member, keys)
        if row:
            inner = row.pop("sd_weight")
            row["weight"] = round(fixed if fixed is not None else (inner if inner is not None else own), 2)
            rows.append(row)
        else:
            rows.extend(_group_artists(member, keys, fixed, own, depth + 1))
    return rows


def _strip_group(chunk, keys, removed, depth=0):
    """묶음에서 작가만 걷은 글 - 묶음 속 묶음까지. 바뀐 것이 없으면 None, 남는 것이 없으면 빈 글.

    남는 태그의 가중치는 그대로다(`(artist:a, smile:1.2)` -> `(smile:1.2)`).
    """
    group = _split_group(chunk, depth)
    if not group:
        return None
    members, number = group
    kept, changed = [], False
    for member in members:
        row = _member_artist(member, keys)
        if row:
            row.pop("sd_weight", None)
            removed.append(row)
            changed = True
            continue
        inner = _strip_group(member, keys, removed, depth + 1)
        if inner is None:
            if member.strip():
                kept.append(member.strip())
        else:
            changed = True
            if inner:
                kept.append(inner)
    if not changed:
        return None
    return "(" + ", ".join(kept) + (f":{number}" if number else "") + ")" if kept else ""


def find_artists_weighted(text, *, known=frozenset()) -> list[dict]:
    """`find_artists` + 그 작가에 걸린 가중치(`weight`). 아티스트 태그 관리 창이 쓴다(2026-11-11).

    `0.6::artist:a, b ::` 는 둘 다 0.6 · 겹쳤으면 가장 안쪽 숫자 · SD 꼴 `(name:1.2)` 는 그 숫자.
    숫자가 없으면 중괄호 · 대괄호 겹수(1.05 배씩)이고, 아무것도 없으면 1. SD 묶음 안의 작가는 `_group_artists`.
    """
    keys, events = _known_keys(known), _events(text)
    opens = {event.group: event.text.strip() for event in events if event.kind == "OPEN"}
    rows = []
    for event in events:
        if event.kind != "TAG":
            continue
        number, factor = None, 1.0
        for gid in event.groups:                      # 바깥 -> 안쪽 차례
            opener = opens.get(gid, "")
            if opener.startswith("{"):
                factor *= 1.05
            elif opener.startswith("["):
                factor /= 1.05
            elif (match := re.match(_NUMBER, opener)):
                number = float(match[0])
        row = _classify(event, keys)
        if not row:
            # 묶음 구성원도 바깥 가중치를 같은 식으로 받는다 - 따로 세면 `-0.5::(artist:a, smile) ::` 가 1.1 이 됐다(리뷰 2차 #7).
            rows.extend(_group_artists(event.text, keys, number, factor))
            continue
        sd = re.search(rf":\s*({_NUMBER})\)$", event.text.strip()) if _SD.fullmatch(event.text.strip()) else None
        if sd:
            number = float(sd[1])
        row["weight"] = round(number if number is not None else factor, 2)
        rows.append(row)
    return rows


def solo_artist(text, token, *, known=frozenset()) -> dict:
    """작가를 전부 걷고 `token`(서식이 끝난 작가 태그) 하나만 넣은 글. 아티스트 태그 관리 창의 [이 아티스트로만 생성].

    자리는 맨 앞 인원 수 태그(1girl · 1boy ...) 바로 뒤다(사용자 확인 2026-11-11) - 메인 생성의 최종 포맷과 같은 차례.
    음수 가중치로 넣은 작가도 걷는다. 작가가 아닌 것(`artist collaboration` 등)은 그대로 둔다.
    """
    # 주석 칸은 가린 글로 읽는다 - 주석 속 `}` 가 묶음을 닫았다고 읽어 묶음 안의 태그를 밖으로 꺼냈다(Codex 리뷰 11차 #1).
    # 주석 조각은 아래에서 통째로 걷으니 가린 글이 결과로 나가지 않는다.
    text = _mask_comments(str(text or ""))
    events, keys = _events(text), _known_keys(known)
    remove, removed, rewritten = set(), [], {}
    for i, event in enumerate(events):
        if event.kind != "TAG":
            continue
        row = _classify(event, keys)
        if row:
            remove.add(i)
            removed.append(row)
            continue
        chunk = event.text.rstrip()
        inside = _strip_group(chunk, keys, removed)
        if inside is not None:
            # SD 묶음 안의 작가만 걷는다. 남는 것이 없으면 묶음째로.
            if inside:
                rewritten[i] = (chunk, inside)
                event.text = inside + event.text[len(chunk):]
            else:
                remove.add(i)
        elif event.body.lstrip().startswith("#"):
            # 주석 조각(`#랜덤프롬프트`)도 걷는다 - 생성이 어차피 버리는 글이다. 남겨 두면 작가가 빠진 가중치 묶음의
            # 여는 표식이 그 앞에 붙어(`0.75::#랜덤프롬프트`) 주석이 아니게 되고, 그 글이 프롬프트로 나간다(실측).
            remove.add(i)
    # ⚠️ 묶음 안만 고쳤으면 걷을 조각이 없다 - 그래도 고친 글이 나가야 한다(리뷰 2차 #1: 원문이 그대로 나갔다).
    #    그때는 **그 묶음만 제자리에서 갈아 끼운다** - 통째로 다시 조립하면 손대지 않은 글의 모양까지 바뀐다
    #    (3차 #2: `a {red} dress` -> `a{red}dress`). 걷을 조각이 있으면 예전처럼 조립한다(고친 묶음은 조각의 글로 간다).
    if remove:
        stripped = _remove(text, events, remove)
    else:
        stripped = _replace_in_place(text, events, rewritten)
        if stripped is None:
            stripped = _remove(text, events, remove, force=True)
    people, body = _hoist_people(stripped)
    return {"prompt": _join(", ".join(people), token, body), "removed": removed}


# [가중치를 업데이트하여 생성] 이 주는 껍질의 자리 표시 - 화면이 모드에 맞는 껍질(`0.5::\ue000 ::` · `(\ue000:0.5)`)을 만들어
# 주고, 여기서 원래 몸통(`hassai` · `artist:omone` · `@name`)을 그 자리에 넣는다. 몸통을 화면이 다시 지으면 `artist:` 를 뗀
# prefix 칸에 `artist:` 가 붙는다.
REWEIGHT_SLOT = "\ue000"


class ReweightError(ValueError):
    """가중치를 바꿀 자리를 못 짚었다. `code` = in_group(SD 묶음 안) · unparsed(글을 다시 짚지 못함)."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _event_spans(text, events):
    """조각마다 원문의 (시작, 끝). 조각은 원문에 차례대로 놓여 있다(`_replace_in_place` 와 같은 짚기). 못 짚으면 None."""
    spans, cursor = [], 0
    for event in events:
        piece = event.text.strip()
        if not piece:
            spans.append((cursor, cursor))
            continue
        found = text.find(piece, cursor)
        if found < 0:
            return None
        spans.append((found, found + len(piece)))
        cursor = found + len(piece)
    return spans


# 고친 자리의 몸통을 잠시 맡아 두는 표 - 다시 짚을 때 이미 고친 태그를 또 집지 않게(사전에 없는 글이라 작가로 안 읽힌다).
_HELD = "\ue001{}\ue002"


def _reweight_one(text, events, spans, i, wrap, one, body, members, opens, closes):
    """조각 i(작가 태그) 하나의 가중치를 고친 글. 자리를 못 고치면 None. `one` = 가중치 1 을 드러내 적는 껍질."""
    groups = events[i].groups
    mine = [g for g in groups if members.get(g) == [i] and g in opens and g in closes]
    shared = [g for g in groups if g not in mine and g in opens and g in closes]
    first = min([opens[g] for g in mine] + [i])
    last = max([closes[g] for g in mine] + [i])
    start, end = spans[first][0], spans[last][1]
    before = events[first - 1] if first > 0 else None
    after = events[last + 1] if last + 1 < len(events) else None
    # 나눠 쓰는 껍질에서 빼어 옮기는 것은 쉼표로 떼어 낼 수 있을 때만이다 - 못 떼면 제자리에서 고치고, 그러면 그 껍질도
    # 바깥으로 남는다(옮길 것으로 셈해 놓고 제자리에 두면 가중치 1 이 맨몸으로 남아 바깥 숫자를 물려받았다 · Codex 리뷰 3차 #2).
    # 쉼표를 지우면 이웃 칸과 이어 붙는다 - 그 칸이 주석이면 주석의 머리가 바뀌거나(`0.7::# ...` 로 살아난다) 닫는 `::` 를
    # 주석이 삼킨다(Codex 리뷰 5차 #1 #2). 그쪽 쉼표는 쓰지 않는다.
    side = ("before" if getattr(before, "kind", "") == "SEP" and not _comment_field(events, first - 2, -1)
            else "after" if getattr(after, "kind", "") == "SEP" and not _comment_field(events, last + 2, 1)
            else "")
    movable = shared and not mine and side
    moved = min(shared, key=lambda g: len(members[g])) if movable else None
    # 제 껍질을 걷어 낸 뒤에도 남는 바깥 껍질(나눠 쓰는 것 · 다른 칸에서 열린 것) - 그 안에서 가중치 1 을 맨몸으로 두면
    # 바깥 숫자를 물려받는다(`0.7::b, a ::` 의 a 는 0.7). 그때는 모드의 문법으로 드러내 적는다(1차 #4 · 2차 #1).
    outer = [g for g in groups if g not in mine and g != moved]
    shell = wrap if wrap != REWEIGHT_SLOT or not outer else one
    token = shell.replace(REWEIGHT_SLOT, body)
    if moved is None:
        # 쉼표 없이 붙은 이웃이 있으면 쉼표로 가른다 - 숫자 껍질은 태그 머리에서만 열리고, 맨몸은 이웃과 한 태그가 된다
        # (`artist:bar {artist:foo}` -> `artist:bar 0.5::artist:foo ::` 가 `bar 0.5` 라는 작가로 읽혔다 · 2차 #2 · 3차 #1).
        if getattr(before, "kind", "") == "TAG":
            while start > 0 and text[start - 1] in " \t":
                start -= 1
            token = ", " + token
        if getattr(after, "kind", "") in ("TAG", "OPEN"):
            while end < len(text) and text[end] in " \t":
                end += 1
            token = token + ", "
        return text[:start] + token + text[end:]
    # 나눠 쓰는 껍질 - 가장 안쪽 것(구성원이 가장 적다)에서 빼어 그 바로 뒤에 둔다.
    if side == "before":
        cut_start, cut_end = spans[first - 1][0], end
    else:
        cut_start, cut_end = start, spans[last + 1][1]
        while cut_end < len(text) and text[cut_end] in " \t":
            cut_end += 1
    tail = spans[closes[moved]][1]
    if tail < cut_end:
        return None
    # 옮겨 둔 자리 뒤에도 쉼표 없이 이어지는 것이 있으면 가른다(`{a, smile} blue eyes` · 줄바꿈 뒤 `0.75::` - Codex 리뷰 4차 #2).
    follow = events[closes[moved] + 1] if closes[moved] + 1 < len(events) else None
    if getattr(follow, "kind", "") in ("TAG", "OPEN"):
        return text[:cut_start] + text[cut_end:tail] + ", " + token + ", " + text[tail:].lstrip(" \t")
    return text[:cut_start] + text[cut_end:tail] + ", " + token + text[tail:]


def _is_comment(event):
    """주석 조각(`# ...` 로 시작하는 쉼표 칸)의 것 - 생성이 통째로 버린다. 그 안의 작가는 고치지 않는다(Codex 리뷰 4차 #1)."""
    return event.raw.lstrip().startswith("#")


def _without_comments(text):
    return ", ".join(field for field in split_top(text) if not field.strip().startswith("#"))


def _comment_field(events, index, step):
    """`index` 에서 `step` 쪽으로 쉼표를 만날 때까지 - 그 칸이 주석 칸인가."""
    while 0 <= index < len(events) and events[index].kind != "SEP":
        if events[index].kind == "TAG" and _is_comment(events[index]):
            return True
        index += step
    return False


def _other_tags(text, targets_of):
    """맞춰 볼 것 - (그 작가가 아닌 태그와 그 실제 가중치들, 주석 칸 원문들). 차례 무관. 가중치를 고치기 전과 뒤가 같아야 한다.

    가중치는 `find_artists_weighted` 와 같은 읽기(가장 안쪽 숫자 · 중괄호 겹수). 껍질이 주석에 먹혀 바깥 숫자가 안 닫히면
    다른 태그의 가중치가 바뀐다 - 그것을 잡는다(Codex 리뷰 5차 #2).
    """
    events = _events(_without_comments(text))
    skip = set(targets_of(events))
    opens = {event.group: event.text.strip() for event in events if event.kind == "OPEN"}
    tags = []
    for i, event in enumerate(events):
        if event.kind != "TAG" or i in skip:
            continue
        number, factor = None, 1.0
        for gid in event.groups:
            opener = opens.get(gid, "")
            if opener.startswith("{"):
                factor *= 1.05
            elif opener.startswith("["):
                factor /= 1.05
            elif (match := re.match(_NUMBER, opener)):
                number = float(match[0])
        tags.append((" ".join(event.body.split()), round(number if number is not None else factor, 2)))
    comments = [field.strip() for field in split_top(text) if field.strip().startswith("#")]
    return sorted(tags), sorted(comments)


def _people_folded(other):
    """`_other_tags` 의 결과에서 인원 수 태그를 (소문자 이름, 가중치) 모음으로 접는다 - 넣기 갈래는 인원 수 태그를 앞으로 꺼내며
    중복을 지우고 소문자로 적는다(`1girl, 1girl` · `1Girl` 을 거절했다 - Codex 리뷰 11차 #2). 가중치가 바뀌면 여전히 잡힌다."""
    from core.prompt_processor import ALL_PERSON_TAGS

    tags, comments = other
    rest, people = [], set()
    for body, weight in tags:
        name = body.lower()
        if name in ALL_PERSON_TAGS:
            people.add((name, weight))
        else:
            rest.append((body, weight))
    return rest, people, comments


# 같은 작가를 이보다 많이 쓴 글은 거절한다 - 한 자리마다 글 전체를 다시 짚어 1,000 번이면 12초가 들었다(Codex 리뷰 2차 #4).
REWEIGHT_MAX_OCCURRENCES = 64


def reweight_artist(text, artist, wrap, *, fresh="", one="", known=frozenset()) -> dict:
    """`artist` 의 가중치만 바꾼 글 - 다른 작가 · 태그 · 자리는 그대로다(아티스트 태그 관리 창 2026-11-13).

    - 그 작가만 감싼 껍질(`0.72::hassai ::` · `{artist:a}` · `(a:1.2)`)은 껍질째 새 껍질로 갈아 끼운다.
    - 다른 태그와 나눠 쓰는 껍질 안(`0.26::epi zero, e-note ::`)이면 거기서 빼어 그 껍질 바로 뒤에 둔다
      (`0.26::epi zero ::, 0.4::e-note ::`) - 다른 태그의 가중치는 안 바뀐다.
    - 같은 작가가 여러 번이면 모두 바꾼다 - 한 자리씩 고치고 다시 짚는다(한 번에 고치면 이웃한 둘의 쉼표가 겹친다 · 1차 #5).
      글에 없으면 `fresh`(서식이 끝난 새 태그)를 인원 수 태그 뒤에 넣는다(`fresh` 가 빈 글이면 그대로 둔다).
    - SD 묶음 `(a, b:1.2)` 안에 하나라도 있으면 `ReweightError("in_group")` - 바깥 것만 바꾸면 반만 바뀐다(1차 #6).
    """
    text = str(text or "")
    wrap = str(wrap or "")
    one = str(one or "") or "1::" + REWEIGHT_SLOT + " ::"
    for shell in (wrap, one):
        if shell.count(REWEIGHT_SLOT) != 1 or "\ue001" in shell or "\ue002" in shell:
            raise ValueError("wrap must hold exactly one slot")
    if any(mark in text for mark in "\ue001\ue002\ue004\ue005"):
        raise ReweightError("unparsed")
    keys, key = _known_keys(known), _dict_key(artist)

    def targets_of(events):
        return [i for i, event in enumerate(events) if event.kind == "TAG" and not _is_comment(event)
                and (row := _classify(event, keys)) and _dict_key(row["name"]) == key]

    original = text
    others = _other_tags(text, targets_of)
    # 주석 칸은 생성이 통째로 버린다 - 그 안의 `::` · 괄호를 껍질로 읽으면 바깥 껍질의 짝이 주석 속으로 들어가, 작가를 주석
    # 한가운데로 옮겼다(Codex 리뷰 6차 · 7차는 대상 찾기도: `0.7::a, smile, # 0.6::b ::, blue eyes ::`). 고치는 동안은 자리 표시로 가려 두고 끝에 되돌린다.
    fields, hidden = split_top(text), []
    for n, field in enumerate(fields):
        if field.strip().startswith("#"):
            lead, trail = field[:len(field) - len(field.lstrip())], field[len(field.rstrip()):]
            fields[n] = f"{lead}#\ue004{len(hidden)}\ue005{trail}"
            hidden.append(field.strip())
    text = ",".join(fields)
    events = _events(text)
    targets = targets_of(events)
    found = sum(1 for row in find_artists_weighted(_without_comments(original), known=known) if _dict_key(row["name"]) == key)
    if found > len(targets):
        raise ReweightError("in_group")
    if not targets:
        if not str(fresh or "").strip():
            return {"prompt": original, "changed": 0, "inserted": False}
        people, body = _hoist_people(original)
        inserted = _join(", ".join(people), fresh, body)
        if _people_folded(_other_tags(inserted, targets_of)) != _people_folded(others):
            raise ReweightError("unparsed")
        return {"prompt": inserted, "changed": 0, "inserted": True}
    if len(targets) > REWEIGHT_MAX_OCCURRENCES:
        raise ReweightError("too_many")
    bodies = []
    for _ in range(len(targets)):
        events = _events(text)
        todo = targets_of(events)
        spans = _event_spans(text, events)
        if not todo or spans is None:
            raise ReweightError("unparsed")
        members, opens, closes = {}, {}, {}
        for j, event in enumerate(events):
            if event.kind == "TAG":
                for gid in event.groups:
                    members.setdefault(gid, []).append(j)
            elif event.kind == "OPEN":
                opens[event.group] = j
            elif event.kind == "CLOSE":
                closes[event.group] = j
        i = todo[0]
        held = _HELD.format(len(bodies))
        bodies.append(" ".join(events[i].body.split()))
        text = _reweight_one(text, events, spans, i, wrap, one, held, members, opens, closes)
        if text is None:
            raise ReweightError("unparsed")
    if targets_of(_events(text)):
        raise ReweightError("unparsed")
    for n, body in enumerate(bodies):
        text = text.replace(_HELD.format(n), body)
    for n, comment in enumerate(hidden):
        mark = f"#\ue004{n}\ue005"
        if text.count(mark) != 1:
            raise ReweightError("unparsed")
        text = text.replace(mark, comment)
    # 결과를 다시 읽어 맞춰 본다(2차 #2 · 3차 #1) - 어긋나면 글을 돌려주지 않는다:
    #   그 작가가 바꾼 수만큼 · 모두 요청한 가중치로 읽히고, 다른 태그는 하나도 빠지거나 바뀌지 않았다.
    want = find_artists_weighted(wrap.replace(REWEIGHT_SLOT, "artist:\ue003"))
    rows = [row for row in find_artists_weighted(_without_comments(text), known=known) if _dict_key(row["name"]) == key]
    if (len(want) != 1 or len(rows) != len(bodies)
            or any(abs(row["weight"] - want[0]["weight"]) > 0.005 for row in rows)
            or _other_tags(text, targets_of) != others):
        raise ReweightError("unparsed")
    return {"prompt": text, "changed": len(bodies), "inserted": False}


def _replace_in_place(text, events, rewritten):
    """고친 묶음만 원문의 **제자리에서** 갈아 끼운 글. 자리를 못 짚으면 None.

    조각은 원문에 차례대로 놓여 있다 - 앞에서부터 **모든 조각을** 하나씩 짚어 가며 제 조각의 자리만 바꾼다.
    고친 묶음의 글만 찾으면 앞선 다른 조각 속의 같은 글을 집는다(Codex 리뷰 2026-11-12 4차:
    `<lora:style (dairi, smile):1>, (dairi, smile)` 에서 LoRA 이름이 바뀌고 정작 묶음의 작가는 남았다).
    """
    out, cursor, last = [], 0, 0
    for i, event in enumerate(events):
        piece = (rewritten[i][0] if i in rewritten else event.text).strip()
        if not piece:
            continue
        found = text.find(piece, cursor)
        if found < 0:
            return None
        if i in rewritten:
            out.append(text[last:found])
            out.append(rewritten[i][1])
            last = found + len(piece)
        cursor = found + len(piece)
    out.append(text[last:])
    return "".join(out)


def _remove(text, events, remove, force=False):
    if not remove and not force:
        return text
    kept = [i for i, event in enumerate(events) if event.kind == "TAG" and i not in remove]
    prefixes = {i: [] for i in kept}
    suffixes = {i: [] for i in kept}
    members = {}
    for i in kept:
        for gid in events[i].groups:
            members.setdefault(gid, []).append(i)
    for event in events:
        inside = members.get(event.group)
        if inside and event.kind == "OPEN":
            prefixes[inside[0]].append(event.text)
        elif inside and event.kind == "CLOSE":
            suffixes[inside[-1]].append(event.text)
    parts = []
    previous = -1
    for i in kept:
        if parts:
            separators = [event.text for event in events[previous + 1:i] if event.kind == "SEP"]
            parts.append(separators[-1] if separators else "")
        parts.extend([*prefixes[i], events[i].text, *suffixes[i]])
        previous = i
    return "".join(parts)


def strip_artists(text, *, known=frozenset(), keep=()) -> dict:
    events, keys = _events(text), _known_keys(known)
    raw_keep = {str(value).strip() for value in keep}
    name_keep = {_dict_key(value) for value in keep}
    remove, removed = set(), []
    for i, event in enumerate(events):
        if event.kind != "TAG":
            continue
        row = _classify(event, keys)
        if row and row["raw"].strip() not in raw_keep and _dict_key(row["name"]) not in name_keep:
            remove.add(i)
            removed.append(row)
    return {"text": _remove(text, events, remove), "removed": removed}


def strip_tags(text, tags) -> str:
    keys, events = {_dict_key(tag) for tag in tags}, _events(text)
    remove = {i for i, event in enumerate(events) if event.kind == "TAG"
              and not _wildcard(event.body) and _dict_key(event.body) in keys}
    return _remove(text, events, remove)


def _join(*parts):
    return ", ".join(clean for part in parts if (clean := str(part or "").strip(" ,\t\r\n")))


def _hoist_people(text):
    """그림 본문의 인원 수 태그(1girl · 2boys …)를 꺼낸다 - 스왑 결과의 **맨 앞**에 다시 세운다.

    메인 생성은 최종 포맷에서 인원 수 태그를 프리셋 앞머리(pre_prompt)보다 앞으로 옮긴다(`prompt_processor`
    의 `_step_final_format`). 스왑은 그 결과에 새 프리셋 앞머리를 다시 붙이므로, 그대로 두면 `1girl` 이 작가
    줄 뒤 · 본문 한가운데로 밀린다(사용자 제보 2026-11-06). 순서도 같은 규칙(boys -> girls -> others).
    가중치 · 괄호 안에 든 것은 사용자가 일부러 감싼 것이라 건드리지 않는다.
    """
    from core.prompt_processor import ALL_PERSON_TAGS, PERSON_TAG_SETS

    # 묶음은 주석을 가린 글로 읽는다 - 주석 속 `}` 가 묶음을 닫았다고 읽어 묶음 안의 1girl 을 밖으로 꺼냈다(Codex 리뷰 10차
    # #2: `{smile, # artist:wlop}, 1girl, blue eyes}`). 같은 길이로 가려 조각 자리가 원문 자리와 그대로 맞는다.
    masked = _mask_comments(text)
    events = _events(masked)
    found = []
    for i, event in enumerate(events):
        if event.kind != "TAG" or event.groups:
            continue
        name = " ".join(event.text.split()).lower()
        if name in ALL_PERSON_TAGS and name == " ".join(event.body.split()).lower():
            found.append((i, name))
    if not found:
        return [], text
    rank = {**{t: 0 for t in PERSON_TAG_SETS["boys"]}, **{t: 1 for t in PERSON_TAG_SETS["girls"]}}
    people = []
    for _, name in sorted(found, key=lambda row: rank.get(row[1], 2)):
        if name not in people:
            people.append(name)
    # 꺼낸 태그의 자리만 원문에서 뺀다 - `_remove` 로 다시 조립하면 손대지 않은 글의 모양이 바뀐다(Codex 리뷰 8차:
    # `a {red} dress` -> `a{red}dress`). 이름으로 고르면 묶음 안의 같은 태그까지 잡힌다(9차) - 짚은 조각의 자리로 뺀다.
    spans = _event_spans(masked, events)
    if spans is None:
        return people, _remove_unmasked(text, people)
    cuts = []
    for i, _ in found:
        start, end = spans[i]
        before = i > 0 and events[i - 1].kind == "SEP"
        after = i + 1 < len(events) and events[i + 1].kind == "SEP"
        if (i > 0 and not before) or (i + 1 < len(events) and not after):
            # 같은 쉼표 칸에 다른 글이 남는다(`1girl {blue eyes}`) - 태그와 그 옆 빈칸만 빼고 쉼표는 둔다(Codex 리뷰 10차 #1).
            if i + 1 < len(events) and not after:
                while end < len(text) and text[end] in " \t":
                    end += 1
            else:
                while start > 0 and text[start - 1] in " \t":
                    start -= 1
            cuts.append((start, end))
        elif after:
            # 앞 쉼표 뒤부터 뒤 쉼표까지 - `a, 1girl, b` -> `a, b`
            cuts.append((spans[i - 1][1] if before else start, spans[i + 1][1]))
        else:
            # 마지막 칸이면 앞 쉼표부터 - `a, 1girl` -> `a`
            cuts.append((spans[i - 1][0] if before else start, end))
    merged = []
    for start, end in sorted(cuts):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    out, cursor = [], 0
    for start, end in merged:
        out.append(text[cursor:start])
        cursor = end
    out.append(text[cursor:])
    return people, "".join(out)


def _mask_comments(text):
    """주석 칸(`#` 로 시작하는 맨 위 쉼표 칸) 의 `#` 뒤를 같은 길이의 U+E004 로 가린 글 - 생성이 버리는 글 속 괄호 · `::` 가
    묶음을 닫거나 열지 않게. 길이가 같아 조각 자리가 원문 자리와 그대로 맞는다. 칸을 다시 이어 원문이 안 되면 그대로 둔다."""
    fields = split_top(text)
    if ",".join(fields) != text:
        return text
    for n, field in enumerate(fields):
        body = field.strip()
        if body.startswith("#"):
            lead = len(field) - len(field.lstrip())
            fields[n] = field[:lead] + "#" + "\ue004" * (len(body) - 1) + field[lead + len(body):]
    return ",".join(fields)


def _remove_unmasked(text, people):
    events = _events(text)
    return _remove(text, events, {i for i, event in enumerate(events) if event.kind == "TAG" and not event.groups
                                  and " ".join(event.text.split()).lower() in people})


def preset_tags(pre, post, *, known=frozenset()) -> list[str]:
    keys = _known_keys(known)
    return [event.body for event in _events(_join(pre, post)) if event.kind == "TAG"
            and event.body and not _wildcard(event.body) and not _classify(event, keys)]


def compose_swap(image_prompt, *, source_pre, source_post, target_pre, target_post,
                 artist_mode, known=frozenset(), keep=()) -> dict:
    if artist_mode not in {"preset", "keep"}:
        raise ValueError("Invalid artist_mode")
    known = _known_keys(known)
    removed, target_removed = [], []
    body = image_prompt
    if artist_mode == "preset":
        result = strip_artists(body, known=known, keep=keep)
        body, removed = result["text"], result["removed"]
    else:
        # Parse both preset fields together so a weight spanning them is retained.
        # The unique marker stands for the image body without classifying its artists.
        marker = "$__inpaint_swap_body__"
        while marker in _join(target_pre, target_post, image_prompt):
            marker += "_"
        result = strip_artists(_join(target_pre, marker, target_post), known=known)
        target_removed = result["removed"]
    body = strip_tags(body, preset_tags(source_pre, source_post, known=known))
    people, body = _hoist_people(body)
    if artist_mode == "keep":
        if body.strip():
            main_prompt = result["text"].replace(marker, body.strip())
        else:
            events = _events(result["text"])
            main_prompt = _remove(result["text"], events,
                                  {i for i, event in enumerate(events) if event.body == marker})
    else:
        main_prompt = _join(target_pre, body, target_post)
    if people:
        main_prompt = _join(", ".join(people), main_prompt)
    # 창은 이것을 보여 준다 - 작가 · 원본 프리셋 앞뒤를 걷고 **남는 그림 태그**(사용자 지정 2026-11-06).
    # 새 프리셋의 앞뒤는 몇 개 붙는지만 센다(원본 유지면 그 앞뒤에서도 작가는 빠진 뒤의 수).
    if artist_mode == "keep":
        pre_left = strip_artists(target_pre, known=known)["text"]
        post_left = strip_artists(target_post, known=known)["text"]
    else:
        pre_left, post_left = target_pre, target_post
    return {"main_prompt": main_prompt,
            "removed": removed, "target_removed": target_removed,
            "people": people, "body": body.strip(" ,\t\r\n"),
            "body_tags": len(people) + _count_tags(body),
            "target_pre_tags": _count_tags(pre_left), "target_post_tags": _count_tags(post_left)}


def _count_tags(text):
    # 다른 칸에서 연 가중치를 닫는 `}` · `]` · `::` 만 남은 칸은 붙는 태그가 아니다(Codex 4차: 뒤 태그 1개 오안내).
    return sum(1 for event in _events(str(text or ""))
               if event.kind == "TAG" and event.body.strip(" {}[]():"))


def guess_source_preset(image_prompt, presets, *, known=frozenset()) -> dict | None:
    known = _known_keys(known)
    image_tags = {_dict_key(event.body) for event in _events(image_prompt) if event.kind == "TAG"}
    scored = []
    for preset in presets:
        tags = {_dict_key(tag) for tag in preset_tags(preset.get("pre"), preset.get("post"), known=known)}
        matched, total = len(tags & image_tags), len(tags)
        if matched:
            scored.append({"name": preset["name"], "matched": matched, "total": total})
    return min(scored, key=lambda row: (-row["matched"], -row["matched"] / row["total"], row["name"])) if scored else None
