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


def _paren_group(event):
    """SD 묶음 `(a, b:1.2)` · `(a, b)` -> (구성원들, 숫자 글 | None, 뒤 공백). 묶음이 아니거나 구성원이 하나면 None.

    `_events` 는 괄호를 한 덩어리로 둔다 - 묶음 안의 작가는 `_classify` 에 안 걸려 [이 아티스트로만 생성] 에 남았다
    (Codex 리뷰 2026-11-12 #6: `(artist:a, smile:1.2)`). 구성원이 하나인 `(name:1.2)` 는 `_events` 가 이미 벗긴다.
    """
    chunk = event.text.rstrip()
    if len(chunk) < 2 or chunk[0] != "(" or chunk[-1] != ")":
        return None
    depth = i = 0
    while i < len(chunk):                              # 통째로 한 쌍이어야 한다 - `(a) b (c)` 는 묶음이 아니다
        if chunk[i] == "\\":
            i += 2
            continue
        if chunk[i] == "(":
            depth += 1
        elif chunk[i] == ")":
            depth -= 1
            if depth == 0 and i != len(chunk) - 1:
                return None
        i += 1
    if depth:
        return None
    members = split_top(chunk[1:-1])
    number = None
    last = _LAST_NUMBER.match(members[-1])
    if last:
        members[-1], number = last[1], last[2]
    if len(members) < 2:
        return None
    return members, number, event.text[len(chunk):]


def _member_artist(member, keys):
    body = member.strip()
    return _classify(_Event("TAG", body, body=body, raw=body), keys) if body else None


def find_artists_weighted(text, *, known=frozenset()) -> list[dict]:
    """`find_artists` + 그 작가에 걸린 가중치(`weight`). 아티스트 태그 관리 창이 쓴다(2026-11-11).

    `0.6::artist:a, b ::` 는 둘 다 0.6 · 겹쳤으면 가장 안쪽 숫자 · SD 꼴 `(name:1.2)` 는 그 숫자.
    숫자가 없으면 중괄호 · 대괄호 겹수(1.05 배씩)이고, 아무것도 없으면 1.
    """
    keys, events = _known_keys(known), _events(text)
    opens = {event.group: event.text.strip() for event in events if event.kind == "OPEN"}
    rows = []
    for event in events:
        row = _classify(event, keys) if event.kind == "TAG" else None
        if not row:
            group = _paren_group(event) if event.kind == "TAG" else None
            for member in (group[0] if group else ()):
                inner = _member_artist(member, keys)
                if inner:
                    # 묶음의 숫자가 곧 그 작가의 가중치. 숫자 없는 `(a, b)` 는 SD 의 1.1 배.
                    inner["weight"] = round(float(group[1]) if group[1] else 1.1, 2)
                    rows.append(inner)
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
    text = str(text or "")
    events, keys = _events(text), _known_keys(known)
    remove, removed = set(), []
    for i, event in enumerate(events):
        if event.kind != "TAG":
            continue
        row = _classify(event, keys)
        if row:
            remove.add(i)
            removed.append(row)
        elif (group := _paren_group(event)):
            # SD 묶음 안의 작가만 걷는다 - 남는 태그의 가중치는 그대로(`(artist:a, smile:1.2)` -> `(smile:1.2)`).
            members, number, trailing = group
            inside = [_member_artist(member, keys) for member in members]
            if any(inside):
                removed.extend(found for found in inside if found)
                kept = [member.strip() for member, found in zip(members, inside) if not found and member.strip()]
                if kept:
                    event.text = "(" + ", ".join(kept) + (f":{number}" if number else "") + ")" + trailing
                else:
                    remove.add(i)
        elif event.body.lstrip().startswith("#"):
            # 주석 조각(`#랜덤프롬프트`)도 걷는다 - 생성이 어차피 버리는 글이다. 남겨 두면 작가가 빠진 가중치 묶음의
            # 여는 표식이 그 앞에 붙어(`0.75::#랜덤프롬프트`) 주석이 아니게 되고, 그 글이 프롬프트로 나간다(실측).
            remove.add(i)
    people, body = _hoist_people(_remove(text, events, remove))
    return {"prompt": _join(", ".join(people), token, body), "removed": removed}


def _remove(text, events, remove):
    if not remove:
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

    events = _events(text)
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
    return people, _remove(text, events, {i for i, _ in found})


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
