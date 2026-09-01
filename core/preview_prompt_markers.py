# -*- coding: utf-8 -*-
"""프리뷰 프롬프트 구간 표식 — 메인 프롬프트에서 **general 태그만** 골라낸다.

사용자 지정 2026-09-01:
  "사용자의 메인 프롬프트에서 general prompts만 회수해야 합니다. 메인 프롬프트 영역에
   `#프리뷰 프롬프트 시작:` `:#프리뷰 프롬프트 종료` 를 넣어서 이해하기 쉽도록 만들어야
   합니다. 삽입 위치는 사용자의 Prefix Prompt의 가장 마지막 문자열부터 메인 프롬프트에서
   Search 하여 그 뒤에 삽입하면 됩니다. (Post는 반대)
   -> 못찾으면 순서대로 앞으로 전진, 계속 못찾으면 1girl, 1boy 바로 뒤에 넣게 됩니다.
      그 마저도 없으면 맨 앞에."

⚠️ **종료 표식은 `#` 로 시작해야 한다.** 사양의 `:#프리뷰 프롬프트 종료` 를 그대로 쓰면
   API 로 새어 나간다 - 주석 제거가 `startswith('#')` 이기 때문이다(실측):

       입력   1girl, #프리뷰 프롬프트 시작:, solo, :#프리뷰 프롬프트 종료, masterpiece
       남는 것 ['1girl', 'solo', ':#프리뷰 프롬프트 종료', 'masterpiece']

   프리뷰를 안 쓰는 **일반 생성에서도** 그 글자가 NAI 로 나간다. 그래서 콜론을 안쪽으로
   옮겨 `#:프리뷰 프롬프트 종료` 로 쓴다 - 대칭은 지키면서 지워진다.

⚠️ **사용자의 서식을 건드리지 않는다**(사용자 지정 2026-09-01: "기존 
, 

 등을
   소거해서는 안됩니다"). 처음엔 쉼표로 끊어 `', '` 로 다시 붙였는데, 그러면 줄바꿈과
   들여쓰기가 통째로 사라졌다(실측: 줄바꿈 5 -> 0). 그래서 표식은 **원문 좌표에 끼워
   넣고**, 걷을 때도 표식과 붙은 쉼표 하나만 도려낸다. 넣었다 걷으면 원문 그대로다.
"""

from __future__ import annotations

import re

START_MARKER = "#프리뷰 프롬프트 시작:"
END_MARKER = "#:프리뷰 프롬프트 종료"

# 표식을 걸 데가 하나도 없을 때의 최후 기준점(사용자 지정).
PERSON_ANCHORS = ("1girl", "1boy")


def split_spans(text: str) -> list[tuple[int, int, str]]:
    """쉼표로 끊되 **원문 좌표를 들고 있는다** - 줄바꿈·들여쓰기를 지키기 위해.

    각 조각은 (앞뒤 공백을 뺀 시작, 끝, 그 사이 글자). 빈 칸은 버린다.
    """
    raw = str(text or "")
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for part in raw.split(","):
        end = pos + len(part)
        head = pos + (len(part) - len(part.lstrip()))
        tail = end - (len(part) - len(part.rstrip()))
        if tail > head:
            spans.append((head, tail, raw[head:tail]))
        pos = end + 1
    return spans


def split_tags(text: str) -> list[str]:
    """쉼표로 끊고 공백을 정리한다. 빈 칸은 버린다."""
    return [content for _, _, content in split_spans(text)]


def join_tags(tags: list[str]) -> str:
    return ", ".join(tags)


def strip_markers(text: str) -> str:
    """이미 박혀 있는 표식을 걷어낸다(두 번 넣지 않기 위해).

    ⚠️ 표식과 **붙은 쉼표 하나**만 도려낸다 - 다시 짜 맞추면 줄바꿈이 사라진다.
    """
    raw = str(text or "")
    hits = [(head, tail) for head, tail, content in split_spans(raw) if _is_marker(content)]
    for head, tail in reversed(hits):
        cut_head, cut_tail = head, tail
        # 뒤따르는 쉼표(+공백)를 함께 지운다. 없으면 앞의 쉼표를 지운다.
        probe = tail
        while probe < len(raw) and raw[probe] in " 	":
            probe += 1
        if probe < len(raw) and raw[probe] == ",":
            cut_tail = probe + 1
            while cut_tail < len(raw) and raw[cut_tail] == " ":
                cut_tail += 1
        else:
            probe = head - 1
            while probe >= 0 and raw[probe] in " 	":
                probe -= 1
            if probe >= 0 and raw[probe] == ",":
                cut_head = probe
        raw = raw[:cut_head] + raw[cut_tail:]
    return raw


def _is_marker(tag: str) -> bool:
    clean = str(tag or "").strip()
    return clean == START_MARKER or clean == END_MARKER


def _norm(tag: str) -> str:
    """비교용 정규화 - 밑줄을 공백으로 보고 가중치 껍데기를 벗긴다.

    ⚠️ Prefix 는 보통 `1.2::artist:kim eb ::` 처럼 가중치가 붙은 채로 온다.
       날것끼리 비교하면 메인 프롬프트의 `artist:kim eb` 와 안 맞아 **늘 실패**하고,
       그러면 표식이 매번 맨 앞으로 떨어진다.
    """
    text = str(tag or "").strip().lower().replace("_", " ")
    text = re.sub(r"^-?\d+(?:\.\d+)?::", "", text)          # 여는 NAI 가중치
    text = re.sub(r"::$", "", text).strip()                  # 닫는 NAI 가중치
    text = re.sub(r"^\((.*):\s*-?\d+(?:\.\d+)?\)$", r"\1", text)   # WEBUI 가중치
    return " ".join(text.split())


def _find(tags: list[str], needle: str) -> int:
    """정규화 기준 정확일치 위치. 없으면 -1."""
    target = _norm(needle)
    if not target:
        return -1
    for index, tag in enumerate(tags):
        if _norm(tag) == target:
            return index
    return -1


def start_index(main_tags: list[str], prefix_tags: list[str]) -> int:
    """시작 표식이 들어갈 자리(그 인덱스 **앞**에 삽입).

    ① Prefix 의 **마지막**부터 앞으로 전진하며 메인에서 찾는다 → 찾으면 그 **뒤**.
    ② 없으면 `1girl`/`1boy` **뒤**.
    ③ 그마저 없으면 맨 앞.
    """
    for tag in reversed(prefix_tags):
        at = _find(main_tags, tag)
        if at >= 0:
            return at + 1
    for anchor in PERSON_ANCHORS:
        at = _find(main_tags, anchor)
        if at >= 0:
            return at + 1
    return 0


def end_index(main_tags: list[str], postfix_tags: list[str]) -> int:
    """종료 표식이 들어갈 자리(그 인덱스 **앞**에 삽입). 시작의 거울이다.

    ① Postfix 의 **처음**부터 뒤로 전진하며 찾는다 → 찾으면 그 **앞**.
    ② 없으면 맨 뒤.

    ⚠️ 사람 태그 폴백은 여기 없다 - `1girl` 뒤에 종료를 걸면 구간이 비어 버린다.
       시작의 폴백이 '맨 앞' 이므로 거울은 '맨 뒤' 다.
    """
    for tag in postfix_tags:
        at = _find(main_tags, tag)
        if at >= 0:
            return at
    return len(main_tags)


def insert_markers(main_prompt: str, prefix_prompt: str, postfix_prompt: str) -> str:
    """메인 프롬프트에 시작/종료 표식을 꽂아 돌려준다.

    이미 표식이 있으면 걷어내고 다시 계산한다 - Prefix/Postfix 가 바뀌면 자리도 바뀐다.
    """
    base = strip_markers(main_prompt)
    spans = split_spans(base)
    main_tags = [content for _, _, content in spans]
    prefix_tags = split_tags(prefix_prompt)
    postfix_tags = split_tags(postfix_prompt)

    start = start_index(main_tags, prefix_tags)
    end = end_index(main_tags, postfix_tags)
    # ⚠️ 종료가 시작보다 앞이면 구간이 뒤집힌다. 그럴 땐 종료를 맨 뒤로 민다 -
    #    빈(또는 음수) 구간을 만들어 프리뷰가 아무것도 못 뽑는 것보다 낫다.
    if end < start:
        end = len(main_tags)

    # ⚠️ 조각을 다시 짜 맞추지 않는다 - 원문 좌표에 표식만 끼워 넣는다.
    #    (짜 맞추면 사용자의 줄바꿈·들여쓰기가 사라진다: 실측 5 -> 0)
    edits: list[tuple[int, str]] = []
    if end >= len(spans):
        edits.append((spans[-1][1] if spans else len(base), ", " + END_MARKER))
    else:
        edits.append((spans[end][0], END_MARKER + ", "))
    if start >= len(spans):
        edits.append((spans[-1][1] if spans else len(base), ", " + START_MARKER))
    else:
        edits.append((spans[start][0], START_MARKER + ", "))
    out = base
    for at, text in sorted(edits, key=lambda item: -item[0]):
        out = out[:at] + text + out[at:]
    return out


def extract_between(main_prompt: str) -> str:
    """표식 사이의 프롬프트. 표식이 없으면 빈 문자열.

    ⚠️ 빈 문자열을 "메인 프롬프트 전체" 로 대신하지 않는다. 표식이 없다는 것은
       사용자가 아직 구간을 정하지 않았다는 뜻이고, 그때 전체를 보내면 Prefix 의
       아티스트·품질 태그까지 프리뷰에 실려 **구도를 보려던 목적이 흐려진다**.
       화면이 "구간을 먼저 만드세요" 라고 말할 수 있어야 한다.
    """
    tags = split_tags(main_prompt)
    try:
        start = tags.index(START_MARKER)
    except ValueError:
        return ""
    try:
        end = tags.index(END_MARKER, start + 1)
    except ValueError:
        return ""
    # ⚠️ 주석 태그(`#랜덤프롬프트` · Category Annotation 의 `#의상:` 등)는 내용이 아니다.
    #    구간 안에 섞여 들어오므로 여기서 뺀다 - 어차피 API 직전에 지워지지만,
    #    프리뷰 프롬프트에 남으면 사용자가 무엇이 나갔는지 읽기 어렵다.
    return join_tags([t for t in tags[start + 1:end] if not t.startswith(chr(35))])


def has_markers(main_prompt: str) -> bool:
    tags = split_tags(main_prompt)
    return START_MARKER in tags and END_MARKER in tags
