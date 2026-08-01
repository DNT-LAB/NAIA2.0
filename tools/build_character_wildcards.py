# -*- coding: utf-8 -*-
"""캐릭터 대표값 와일드카드 — 캐릭터 썸네일 생성 벤치용.

## 왜 필요한가

캐릭터 뷰어는 9,738명인데 썸네일이 40장(0.4%)뿐이다. 벤치로 한 번에 돌리려면
`__wildcard__` 한 줄에 캐릭터 하나가 들어가야 한다.

## 한 줄에 무엇을 넣는가

    <캐릭터 태그>, <작품 태그>, <대표 색>, <대표 특징>

**캐릭터 태그만으로는 꼬리에서 무너진다.** 근거 행수 중위값이 84라 절반 이상이 얕은
표본이고, 그런 캐릭터는 NAI 가 모른다. 대표 태그를 같이 넣으면 모르는 캐릭터도
색·머리 형태는 맞는 그림이 나온다. 아는 캐릭터에게는 어차피 맞는 값이라 해가 없다.

작품 태그를 넣는 이유: Danbooru 캐릭터 태그가 `ganyu (genshin impact)` 처럼 작품을
괄호로 달고 있는 경우와 `hatsune miku` 처럼 안 단 경우가 섞여 있다. 후자는 작품을
따로 줘야 식별된다.

## 문턱

    personal_color  pct >= 40
    characteristics pct >= 50
    합쳐서 최대 6개

실측 예(`--sample` 로 확인 가능):
    hatsune miku    aqua hair 51.6 / long hair 93.9 · twintails 89.1 · very long hair 63.2
    hakurei reimu   brown hair 61.4 / long hair 50.4
    ganyu           blue hair 95.6 · purple eyes 75.7 / horns 96.6 · long hair 91.9 ...

낮은 pct 까지 넣으면 그 캐릭터의 소수 변형이 섞여 노이즈가 된다. 문턱을 바꾸면
이 주석의 숫자도 같이 고쳐라.

## 파일 단위

**1,000줄씩** 나눈다(사용자 지정). 빈도(`total_rows`) 내림차순이라 `char_00` 이 가장
많이 쓰이는 캐릭터다 — 예산이 모자라면 앞 파일부터 돌리면 된다.

## 벤치 프롬프트 (사용자 확정)

    1girl, 0.38::kanzarin, nns (sobchan), torino aqua, ixy, epi zero ::,
    solo, upper body, rating:general, front view, bust shot,
    0.5::close-up, extreme close-up, top of head at edge of frame ::,
    __wildcard__,
    0.4:: watercolor (medium), no lineart ::, -1:: thick outlines, ai-generated ::,
    best quality, masterpiece, very absurdres, year 2024, year 2025,
    -1::widescreen, blurry ::
"""
import argparse
import json
from pathlib import Path

ANALYSIS = Path("data/character_analysis.json")
OUT_DIR = Path("wildcards/character")


def main() -> int:
    ap = argparse.ArgumentParser(description="캐릭터 대표값 와일드카드 생성")
    ap.add_argument("--chunk", type=int, default=1000, help="파일당 줄 수")
    ap.add_argument("--color-pct", type=float, default=40.0)
    ap.add_argument("--feature-pct", type=float, default=50.0)
    ap.add_argument("--max-tags", type=int, default=6, help="대표 태그 상한(색+특징 합계)")
    ap.add_argument("--sample", type=int, default=0, help="쓰지 않고 N줄만 보여준다")
    args = ap.parse_args()

    data = json.loads(ANALYSIS.read_text(encoding="utf-8"))
    rows = []
    for work, chars in data.items():
        if str(work).startswith("_"):
            continue
        for name, rec in chars.items():
            rows.append((int(rec.get("total_rows", 0) or 0), work, name, rec))
    rows.sort(key=lambda r: (-r[0], r[1], r[2]))

    lines = []
    for _n, work, name, rec in rows:
        tags = []
        for x in (rec.get("personal_color") or []):
            if float(x.get("pct", 0) or 0) >= args.color_pct:
                tags.append(str(x["tag"]))
        for x in (rec.get("characteristics") or []):
            if float(x.get("pct", 0) or 0) >= args.feature_pct:
                tags.append(str(x["tag"]))
        # 캐릭터 태그가 이미 작품을 괄호로 달고 있으면 작품을 또 붙이지 않는다.
        head = [name] if f"({work})" in name else [name, work]
        # 중복 제거하되 순서는 유지한다(앞쪽이 pct 가 높다).
        seen, out = set(), []
        for t in head + tags[: args.max_tags]:
            k = t.strip().lower()
            if k and k not in seen:
                seen.add(k)
                out.append(t.strip())
        lines.append(", ".join(out))

    if args.sample:
        for l in lines[: args.sample]:
            print("  " + l)
        print(f"\n총 {len(lines):,}줄 (쓰지 않음)")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("char_*.txt"):
        old.unlink()
    n = 0
    for i in range(0, len(lines), args.chunk):
        part = lines[i:i + args.chunk]
        p = OUT_DIR / f"char_{n:02d}.txt"
        p.write_text("\n".join(part) + "\n", encoding="utf-8")
        print(f"  {p}  {len(part):,}줄")
        n += 1
    # **줄 -> 캐릭터 키 대응표를 같이 낸다.** 생성된 PNG 의 프롬프트에는 이 줄이 그대로
    # 들어가므로, 그림이 어느 캐릭터의 것인지 역추적할 때 이 표가 필요하다.
    # 팩 빌더가 같은 규칙을 다시 구현하면 두 곳이 갈라진다(이 리포의 상습 결함).
    key_of = {line: f"{work}::{name}"
              for line, (_n, work, name, _rec) in zip(lines, rows)}
    idx = OUT_DIR / "_lines.json"
    idx.write_text(json.dumps({
        "note": ["와일드카드 한 줄 -> '<작품>::<캐릭터>' 대응표.",
                 "생성된 PNG 의 프롬프트에 이 줄이 그대로 들어간다.",
                 "tools/build_character_preview_pack.py 가 이것으로 역추적한다."],
        "count": len(key_of), "lines": key_of,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"  {idx}  ({len(key_of):,}줄 대응표)")
    print(f"\n총 {len(lines):,}줄 / 파일 {n}개 (빈도 내림차순 — char_00 이 최상위)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
