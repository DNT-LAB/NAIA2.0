# -*- coding: utf-8 -*-
"""동반 태그 사전을 **사람/에이전트가 검수할 수 있는 형태**로 내보낸다.

`data/tag_cooccurrence.json` 은 `{태그: [후보...]}` 뿐이라 그것만 보고는 오분류를
판정할 수 없다. `cat ears -> bell` 이 맞는지 알려면 두 태그가 무엇인지 알아야 한다.

## 구성 (사용자 지정)

    <태그>  <설명(Eng or KR)>  <만들어진 태그>

설명은 각 행에 붙이지 않고 `desc` 사전에 한 번만 담는다 — 행마다 후보 4개의 설명을
복사하면 파일이 4배가 되고, 같은 설명이 수천 번 반복된다.

## 검수용 분할

전체 9,900여 행을 한 번에 읽히면 뒤쪽이 흐려진다. `--chunk` 로 나누면 **빈도 내림차순**
으로 잘린다 — 많이 쓰이는 태그의 오분류가 먼저 걸려야 한다.

    python tools/export_companion_review.py
    python tools/export_companion_review.py --chunk 600
"""
import argparse
import json
from pathlib import Path

from core.kr_tag_loader import load_kr_tag_records

SRC = Path("data/tag_cooccurrence.json")
OUT = Path("data/tag_cooccurrence_review.json")
CHUNK_DIR = Path("data/_companion_review")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk", type=int, default=0,
                    help="N행씩 나눠 data/_companion_review/ 에 쓴다(빈도 내림차순)")
    args = ap.parse_args()

    if not SRC.exists():
        raise SystemExit(f"{SRC} 가 없다. tools/build_tag_cooccurrence.py 를 먼저 돌려라.")
    doc = json.loads(SRC.read_text(encoding="utf-8"))
    companions: dict[str, list[str]] = doc.get("companions") or {}

    raw = load_kr_tag_records().raw

    def rec(t: str) -> dict:
        return raw.get(str(t).strip().lower()) or {}

    def desc_of(t: str) -> str:
        m = rec(t)
        # 한글 설명이 있으면 그것, 없으면 영문 wiki 요약. 둘 다 없으면 빈 문자열.
        for k in ("description", "desc", "wiki", "summary"):
            v = str(m.get(k) or "").strip()
            if v:
                return v
        return ""

    def freq_of(t: str) -> int:
        return int(rec(t).get("freq", 0) or 0)

    rows = []
    for tag in sorted(companions, key=lambda t: (-freq_of(t), t)):
        cands = companions[tag]
        rows.append({
            "tag": tag,
            "freq": freq_of(tag),
            "group": str(rec(tag).get("group") or ""),
            "subgroup": str(rec(tag).get("subgroup") or ""),
            "companions": list(cands),
        })

    # 설명은 등장하는 모든 태그(대상 + 후보)에 대해 한 번씩만 담는다.
    need = {r["tag"] for r in rows} | {c for r in rows for c in r["companions"]}
    desc = {t: desc_of(t) for t in sorted(need)}
    empty = sum(1 for v in desc.values() if not v)

    note = [
        "동반 태그 사전의 검수용 내보내기. tools/export_companion_review.py 가 만든다.",
        "구성: rows[] = {tag, freq, group, subgroup, companions[]}, desc = {태그: 설명}.",
        "설명은 desc 사전에 한 번만 담는다(행마다 복사하면 파일이 4배가 된다).",
        "rows 는 대상 태그 빈도 내림차순 — 앞쪽이 사용자가 실제로 많이 보는 것이다.",
        "companions 는 이벤트 코퍼스 449만 건에서 뽑은 '함께 쓰이는 것' 상위 4개다.",
        "정책과 근거는 tools/build_tag_cooccurrence.py 독스트링에 있다.",
        f"설명이 비어 있는 태그 {empty}개 — 그건 태그 DB 에 설명이 없는 것이고 오분류가 아니다.",
    ]
    OUT.write_text(json.dumps({"note": note, "count": len(rows),
                               "rows": rows, "desc": desc},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    size = OUT.stat().st_size / (1024 * 1024)
    print(f"{OUT}  ({len(rows)}행 / 설명 {len(desc)}개 / {size:.1f} MB)")

    if args.chunk > 0:
        CHUNK_DIR.mkdir(parents=True, exist_ok=True)
        for old in CHUNK_DIR.glob("chunk_*.json"):
            old.unlink()
        n = 0
        for i in range(0, len(rows), args.chunk):
            part = rows[i:i + args.chunk]
            # 그 조각에 필요한 설명만 담는다 — 조각 하나가 자체적으로 완결돼야 한다.
            need_p = {r["tag"] for r in part} | {c for r in part for c in r["companions"]}
            p = CHUNK_DIR / f"chunk_{n:02d}.json"
            p.write_text(json.dumps(
                {"note": note + [f"조각 {n} — 전체 {len(rows)}행 중 {i + 1}~{i + len(part)}행"],
                 "chunk": n, "range": [i + 1, i + len(part)], "count": len(part),
                 "rows": part, "desc": {t: desc[t] for t in sorted(need_p)}},
                ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {p.name}  {len(part)}행  {p.stat().st_size / 1024:.0f} KB")
            n += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
