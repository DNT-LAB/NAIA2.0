# -*- coding: utf-8 -*-
"""Assist 속어 · 비속어 풀이 빌더 — English Wiktionary(kaikki.org wiktextract 원본)에서 한국어 표제어 중 속된 뜻이 있는
것만 골라 ``data/assist/slang_glossary_wiktionary.json`` 을 만든다(사용자 지정 2026-09-28 — 통째로가 아니라 골라서).

    python tools/build_slang_glossary.py --input C:/VNR/DEV/wiktionary/raw-wiktextract-data.jsonl.gz

- 입력: https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz (약 2.8GB · 풀면 24GB). **풀지 않고** 흘려 읽는다.
- 고르는 것: ``lang_code == "ko"`` · 한글 표제어 · 속된 뜻(태그 vulgar · slang · derogatory · offensive · Internet, 또는
  성(性) 주제 — topics · 분류 ko:Sex · 풀이 낱말)이 있는 것 중 **첫 뜻이 속된 것**, 또는 세 음절 이상이면 어느 뜻이든.
  진짜 원본 앞 10% 시도: 뒤쪽 뜻 하나로 개 · 돼지 · 벌레 · 친구 · 일 · 하다 · 성 · 색 이 골렸다(흔한 말 — 요청마다 풀이가
  붙는다). 세 음절 이상(따먹다 — 첫 뜻 '따서 먹다')은 흔한 말과 겹칠 일이 적어 받는다. euphemistic(완곡)은 보지 않는다
  (없다 = 죽다 · 일 = 볼일). 그 낱말의 뜻은 **차례대로** 넷까지, '… 의 다른 꼴 · 줄임말' 풀이는 싣지 않는다.
- 뜻마다 ``sexual`` — 쓰는 쪽(core/assist_slang)은 Q · E 에서만 그 뜻을 보인다.
- 라이선스: Wiktionary = CC BY-SA 4.0. 결과 파일에 출처 · 라이선스를 적고, 옆의 ``.LICENSE.txt`` 와 함께 배포한다.
  손으로 쓴 풀이(korean_rules.json slang_glossary)와 한 파일로 합치지 않는다.
- 덮어쓰기는 ``--force`` 로만. ``*.part`` 에 쓰고 끝에 이름을 바꾼다(끊기면 다음 실행이 치우고 다시 돈다).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "assist" / "slang_glossary_wiktionary.json"
SELECT_TAGS = ("vulgar", "slang", "derogatory", "offensive", "Internet")
SEX_TOPICS = {"sex", "sexuality", "BDSM", "prostitution", "pornography", "genitalia"}
SEX_CATEGORIES = {"ko:Sex", "ko:Sexuality", "ko:Genitalia", "ko:Prostitution", "ko:BDSM"}
# 낱말 경계 양쪽 — 'cock' 이 cockroach(바퀴벌레)에 걸렸다(진짜 원본 시도)
_SEXUAL_WORDS = re.compile(
    r"\b(?:fuck\w*|intercourse|coitus|copulat\w*|sexual\w*|sex|penis\w*|penes|vagina\w*|vulva\w*|cunts?|cocks?|dicks?|"
    r"puss(?:y|ies)|semen|sperm|cum|cumming|ejaculat\w*|masturbat\w*|orgasm\w*|rape[sd]?|raping|rapist|gangbang\w*|"
    r"breasts?|tits|titties|nipples?|anal|anus|prostitut\w*|whores?|sluts?|slutty|erection|porn\w*|blowjobs?|fellat\w*|"
    r"cunnilingus|clitor\w*|testic\w*|scrotum|horny|arous\w*|creampie\w*|genital\w*)\b", re.IGNORECASE)
_FORM_OF = re.compile(r"^(alternative (form|spelling)|abbreviation|short(ened)? (form )?(of|for)|clipping of|"
                      r"romanization of|synonym of|eye dialect|misspelling of|initialism of|contraction of)", re.IGNORECASE)
_HANGUL = re.compile(r"[가-힣]")
_NOT_KOREAN = re.compile(r"[A-Za-z\u4e00-\u9fff\u3400-\u4dbf]")
MAX_SENSES = 4
MAX_GLOSS = 90
EXPECT = {"모가지": "neck", "씹": "coitus", "따먹다": "intercourse"}     # 진짜 원본이면 있어야 할 것(끝의 자기 검증)


def _names(values) -> set[str]:
    out = set()
    for v in values or ():
        if isinstance(v, dict):
            v = v.get("name")
        if v:
            out.add(str(v))
    return out


def _short(gloss: str) -> str:
    text = " ".join(str(gloss or "").split()).rstrip(" .;")
    if len(text) <= MAX_GLOSS:
        return text
    cut = text[:MAX_GLOSS].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;") + "…"


def sense_row(sense: dict) -> dict | None:
    """wiktextract 뜻 -> {en, tags, sexual} · 싣지 않을 뜻(풀이 없음 · 다른 꼴)은 None."""
    glosses = [g for g in sense.get("glosses") or [] if isinstance(g, str) and g.strip()]
    if not glosses or _FORM_OF.match(glosses[-1].strip()):
        return None
    en = _short(glosses[-1])                       # 여러 단계 풀이는 마지막이 가장 구체적이다
    tags = [t for t in SELECT_TAGS if t in set(sense.get("tags") or ())]
    topics = set(sense.get("topics") or ())
    sexual = bool(topics & SEX_TOPICS) or bool(_names(sense.get("categories")) & SEX_CATEGORIES) \
        or bool(_SEXUAL_WORDS.search(en))
    return {"en": en, "tags": tags, "sexual": sexual}


def pick(entry: dict) -> tuple[str, dict] | None:
    """한국어 표제어 하나 -> (낱말, {key, kind, pos, senses, _all, _any}) · 실을 뜻이 없으면 None. 속된 뜻이 없는 항목도
    돌려준다 — 같은 낱말의 평범한 항목(년 = year)을 한 음절 규칙이 봐야 한다(keep 은 항목을 다 이은 뒤에)."""
    if entry.get("lang_code") != "ko":
        return None
    word = " ".join(str(entry.get("word") or "").split())
    if not word or not _HANGUL.search(word) or _NOT_KOREAN.search(word):
        return None
    rows = [r for r in (sense_row(s) for s in entry.get("senses") or []) if r]
    if not rows:
        return None
    pos = str(entry.get("pos") or "")
    verbish = word.endswith("다") and len(word) >= 2 and (
        pos in ("verb", "adj") or any(r["en"].lower().startswith("to ") for r in rows))
    kind = "phrase" if " " in word else "verb" if verbish else "noun"
    key = word[:-1] if kind == "verb" else word
    # _all · _any = 이 항목의 뜻이 모두 · 하나라도 속되다(자르기 전) — keep 이 항목을 다 이은 뒤에 본다
    return word, {"key": key, "kind": kind, "pos": pos, "senses": rows[:MAX_SENSES],
                  "_all": all(coarse(r) for r in rows), "_any": any(coarse(r) for r in rows)}


def coarse(row: dict) -> bool:
    return bool(row["tags"]) or bool(row["sexual"])


def keep(word: str, item: dict) -> bool:
    """고른 낱말을 싣나(항목을 다 이은 뒤에 본다):
    - 한 음절: 모든 항목의 모든 뜻이 속될 때만(좆 · 씹) — 공(seme/ball) · 년(bitch/year) · 빵(zero/bread) · 성(sex/castle)은
      어원별 항목의 차례로 '첫 뜻' 이 정해져 믿을 수 없다(진짜 원본 시도).
    - 두 음절: 첫 뜻이 속될 때(보지 · 좆물). 걸레(첫 뜻 rag) 같은 것은 손으로 쓴 풀이가 맡는다.
    - 세 음절 이상: 어느 뜻이든(따먹다 — 흔한 말과 겹칠 일이 적다)."""
    senses = item["senses"]
    n = len(word.replace(" ", ""))
    if not senses or not item.get("_any"):
        return False
    if n == 1:
        return bool(item.get("_all"))
    return coarse(senses[0]) if n == 2 else True


def merge(into: dict, word: str, item: dict) -> None:
    """같은 낱말의 다른 품사 항목 — 뜻을 이어 붙인다(겹치는 풀이는 한 번)."""
    old = into.get(word)
    if old is None:
        into[word] = item
        return
    old["_all"] = bool(old.get("_all")) and bool(item.get("_all"))
    old["_any"] = bool(old.get("_any")) or bool(item.get("_any"))
    seen = {r["en"] for r in old["senses"]}
    old["senses"] = (old["senses"] + [r for r in item["senses"] if r["en"] not in seen])[:MAX_SENSES]


def build(src: Path, out: Path, *, dump_date: str, limit_bytes: int = 0) -> dict:
    total = src.stat().st_size
    entries: dict[str, dict] = {}
    started = time.time()
    last = 0.0
    lines = ko = 0
    with open(src, "rb") as raw, gzip.GzipFile(fileobj=raw) as gz:
        for line in gz:
            lines += 1
            # 거르기는 바이트로 먼저 — 24GB 를 전부 JSON 으로 풀면 느리다. 영어 표제어의 한국어 번역 칸도 걸리니 다시 본다
            if b'"lang_code": "ko"' in line:
                try:
                    entry = json.loads(line)
                except ValueError:
                    entry = None
                if entry and entry.get("lang_code") == "ko":
                    ko += 1
                    got = pick(entry)
                    if got:
                        merge(entries, *got)
            if lines % 20000 == 0:
                done = raw.tell()
                now = time.time()
                if now - last >= 5 or done >= total:
                    last = now
                    frac = done / total if total else 0
                    eta = (now - started) / frac - (now - started) if frac > 0 else 0
                    print(f"  {frac * 100:5.1f}%  {done / 1e9:.2f}/{total / 1e9:.2f}GB  한국어 항목 {ko:,} · 낱말 {len(entries):,}"
                          f"  남은 시간 약 {eta / 60:.0f}분", flush=True)
                if limit_bytes and done >= limit_bytes:
                    break
    picked = {w: {k: v for k, v in e.items() if not k.startswith("_")} for w, e in entries.items() if keep(w, e)}
    dropped = sum(1 for e in entries.values() if e.get("_any")) - len(picked)      # 속된 뜻은 있었지만 흔한 말이라 뺀 것
    entries = picked
    data = {
        "schema_version": 1, "kind": "assist_slang_glossary",
        "source": f"English Wiktionary via kaikki.org wiktextract raw dump ({dump_date})",
        "license": "CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)",
        "attribution": ("Glosses from Wiktionary contributors (https://en.wiktionary.org), extracted by wiktextract "
                        "(Tatu Ylonen, kaikki.org). Changes by NAIA: only Korean words whose first sense (or, for words of "
                        "three or more syllables, any sense) is tagged vulgar/slang/derogatory/offensive/Internet or is on a "
                        "sexual topic were selected; glosses were shortened."),
        "built": dt.date.today().isoformat(),
        "counts": {"korean_entries": ko, "words": len(entries), "common_words_dropped": dropped,
                   "sexual_words": sum(1 for e in entries.values() if any(r["sexual"] for r in e["senses"]))},
        "entries": dict(sorted(entries.items())),
    }
    part = out.with_name(out.name + ".part")
    part.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    os.replace(part, out)
    return data


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")              # cp949 콘솔에서 못 쓰는 글자로 죽지 않게
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Assist 속어 풀이(Wiktionary) 빌더")
    ap.add_argument("--input", required=True, type=Path, help="raw-wiktextract-data.jsonl.gz")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dump-date", default="", help="원본 날짜(기본: 입력 파일의 수정 시각)")
    ap.add_argument("--force", action="store_true", help="결과 파일이 있으면 덮어쓴다")
    ap.add_argument("--limit-bytes", type=int, default=0, help="시험용: 압축 바이트 이만큼만 읽는다")
    ap.add_argument("--min-words", type=int, default=200, help="자기 검증: 고른 낱말이 이보다 적으면 실패")
    args = ap.parse_args(argv)
    if not args.input.is_file():
        print(f"입력이 없습니다: {args.input}")
        return 2
    stale = args.out.with_name(args.out.name + ".part")
    if stale.exists():
        stale.unlink()                                       # 지난 실행이 끊긴 반쪽
        print(f"지난 반쪽을 치웠습니다: {stale.name}")
    if args.out.exists() and not args.force:
        print(f"이미 있습니다: {args.out} — 덮어쓰려면 --force")
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dump_date = args.dump_date or dt.datetime.fromtimestamp(args.input.stat().st_mtime).date().isoformat()
    print(f"읽는 중: {args.input} ({args.input.stat().st_size / 1e9:.2f}GB) — 풀지 않고 흘려 읽습니다")
    t = time.time()
    data = build(args.input, args.out, dump_date=dump_date, limit_bytes=args.limit_bytes)
    c = data["counts"]
    print(f"끝: {time.time() - t:.0f}초 · 한국어 표제어 {c['korean_entries']:,} · 고른 낱말 {c['words']:,}"
          f"(성적 뜻 있는 것 {c['sexual_words']:,}) -> {args.out}")
    # 자기 검증 — 진짜 원본(전체)이면 있어야 할 낱말
    miss = [w for w, needle in EXPECT.items()
            if not any(needle in r["en"] for r in (data["entries"].get(w) or {}).get("senses", []))]
    if args.limit_bytes:
        print("시험 실행(--limit-bytes) — 자기 검증은 건너뜁니다")
    elif miss or c["words"] < args.min_words:
        print(f"⚠ 검증 실패: 빠진 낱말 {miss} · 고른 낱말 {c['words']} — 입력이 맞는지 보십시오")
        return 4
    else:
        print("검증 통과: 모가지 · 씹 · 따먹다 있음")
    print("다음: 결과를 Claude 에게 알려 주세요(파일 크기 · 고른 낱말 수) — 검토 후 커밋합니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
