"""신규 캐릭터 프로필을 배포 자산 두 곳에 **병합**한다.

    data/character_analysis.json        구성요소(툴팁 칩) - 없는 캐릭터만 추가
    danbooru_character.py               character_dict_count - 없는 태그만 추가

배포 친화적으로 설계했다:
  · 새 파일을 만들지 않는다 → 릴리즈 매니페스트/계약을 건드릴 필요가 없다
    (두 파일 모두 `release_include_exclude_draft.json` 에 이미 있다).
  · 기존 엔트리는 한 글자도 바꾸지 않는다. 추가만 한다(멱등).
  · `key_clothes` 를 버린다 - 배포본 스키마에 그 필드가 **없고**(9,738종 전수 확인)
    툴팁도 안 쓴다. 넣으면 파일만 3배로 불어난다.

⚠️ gender 는 코퍼스에서 **실측**한다. 프로필은 `1girl solo` 행에서 나오므로 그냥
   "girl" 을 박으면 남성 캐릭터가 젠더벤드 그림으로 프로필을 갖게 된다 - 배포본이
   `zhongli` 에 `large breasts 31.4%` 를 붙인 그 경로다.

   ⚠️⚠️ 판정 잣대가 중요하다. 코퍼스 **전체**에서 `1girl` vs `1boy` 를 세면 안 된다 -
   남성 캐릭터도 여성과 함께 있는 그림이면 그 행이 `1girl` 로 세어져 통과한다
   (실측: hinata hajime 은 girl 2,185 / boy 1,880 으로 통과했지만, 프로필과 같은
   `solo` 필터에서는 83 / 613 으로 명백히 남성이다).
   그래서 **프로필과 같은 필터**(`solo ∧ ~alternate ∧ ~cosplay`) 아래에서
   `1girl` vs `1boy` 를 센다.

   비율이 애매한 구간에는 남성 캐릭터뿐 아니라 **사람이 아닌 것**도 섞인다
   (pac-man · gengar · chocobo · crystalfly (genshin impact) …). 이들은 `1girl solo`
   그림에 배경 요소로 태그돼 있어, 프로필이 그 개체가 아니라 **같이 그려진 여자**를
   묘사하게 된다. 임계값 10 은 감이 아니라 추가분 2,632종 전수 분포에서 골랐다
   (10배 미만 = 72종 = 2.7%; 81.1% 는 boy_solo 가 아예 0이다).

   제외는 analysis 에만 적용한다. 사전에는 넣는다 - 이름과 빈도는 성별과 무관한
   사실이고, 자동완성에서 이름이 안 뜨는 것이 더 나쁘다.

   ⚠️ 남는 한계(고치지 못했다): 이 비율은 **성별**을 겨냥한 잣대라 비인간 개체는
   부분적으로만 걸린다. 같이 그려진 여자만 있는 마스코트는 boy_solo 가 0이라 어떤
   임계값으로도 통과한다(예: rx-78-2 는 58/5 = 11.6 로 남는다). 임계값을 20으로
   올리면 그 구간이 moogle·bulbasaur·chain chomp 같은 개체로 차 있어 잡히는 듯
   보이지만, 같은 구간에 inkling(2,307행)·mari (faraway)·sajou ayaka 같은 실제 여성
   캐릭터가 함께 있어 그쪽을 잃는다. 비인간 판별은 별도 신호가 필요하다.

⚠️ `character_dict_count` 에 넣은 빈도가 자동완성 랭킹 값이 아닐 수 있다.
   `kr_tag_loader` 는 태그가 이미 `raw` 에 있으면(주로 `data/KR_tags.parquet` 출신)
   `_cat` 만 setdefault 하고 빈도는 **기존 값을 유지**한다. 실측으로 신규 캐릭터
   80종·아티스트 16종이 여기 해당한다(예: ju fufu 사전 2,602 vs 실효 436).
   카테고리는 정상적으로 채워지므로 칩은 뜬다 - 랭킹 값만 parquet 쪽이 우선이다.

    python tools/merge_character_profile_increment.py --profile <increment json> \\
        --counts <counts csv> --corpus <buckets dir> [--apply]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"
DICT_PATH = REPO_ROOT / "danbooru_character.py"

DROP_FIELDS = ("key_clothes",)
MARKER = "# --- increment"

# 비인간 개체(girl/boy 어느 쪽도 아닌 것)를 가려내는 문턱.
#
# 색 칩이 '고유색' 이 아니라 '그림 속 아무 여자의 색' 일 때를 잡는다.
#
# 진짜 캐릭터는 고유색이 있어 personal_color 가 **몇 개 안 된다**(ganyu 2 · miku 2 ·
# ju fufu 5 · ellen joe 6). 반대로 비인간 개체는 그 태그가 붙은 `1girl solo` 그림
# 속 아무 여자의 색이 쌓여 모집단 색 분포에 수렴하고, 가짓수가 20~30 으로 부푼다
# (rx-78-2 28 · moogle 29 · haro 30 · crewmate 30).
#
# 퍼센트 1위로 가르면 안 된다 - hatsune miku 는 aqua/blue 로 갈려 1위가 51.6% 라
# 같이 걸린다. **가짓수**가 맞는 잣대다.
#
# 20 은 전수 분포에서 골랐다(12,204종): 비인간 표본 10/10 을 잡고 진짜 캐릭터
# 12종 오탐 0, 대상 411종(3.4%). 18 로 낮추면 mari (faraway) 가 오탐된다.
MAX_COLOR_KINDS = 20

# ⚠️ 두 자산 모두 **CRLF** 다(실측: character_analysis.json / danbooru_character.py).
# `write_text` 는 `\n` 으로 써서 28MB·6.4MB 파일이 통째로 diff 에 잡힌다.
# 무변경 왕복이 바이트 일치하는지 확인하고 쓴다.
NEWLINE = "\r\n"


def write_preserving_crlf(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))


def flatten_names(analysis: dict) -> set[str]:
    names: set[str] = set()
    for members in analysis.values():
        if isinstance(members, dict):
            names.update(str(n).strip().lower() for n in members)
    return names


def scan_corpus(targets: set[str], dirs: list[Path]) -> tuple[Counter, Counter, Counter]:
    """대상 캐릭터의 (전체 출현, 1girl+solo 행, 1boy+solo 행).

    `total` 은 **필터 없이** 센다 - `character_dict_count` 의 빈도는 걸러지지 않은
    출현이다(예: ouro kronii 7,253 vs 1girl solo 3,620).

    성별 신호는 **프로필과 같은 필터**로 센다(`solo ∧ ~alternate ∧ ~cosplay`).
    잣대가 다르면 판정이 무의미해진다 - 모듈 서두 참조.
    """
    files = sorted((DATA_DIR / "tags").glob("tags_*.parquet"))
    for d in dirs:
        files += sorted(d.glob("tags_*.parquet"))
    total: Counter = Counter()
    girl: Counter = Counter()
    boy: Counter = Counter()
    for i, path in enumerate(files, 1):
        df = pd.read_parquet(path, columns=["character", "general"])
        general = df["general"].fillna("").astype(str)
        padded = ", " + general + ", "
        profile_ok = (padded.str.contains(", solo, ", regex=False)
                      & ~general.str.contains("alternate", regex=False)
                      & ~general.str.contains("cosplay", regex=False)).tolist()
        is_girl = padded.str.contains(", 1girl, ", regex=False).tolist()
        is_boy = padded.str.contains(", 1boy, ", regex=False).tolist()
        for value, ok, g, b in zip(df["character"], profile_ok, is_girl, is_boy):
            if not value:
                continue
            for name in str(value).split(", "):
                name = name.strip()
                if name and name in targets:
                    total[name] += 1
                    if ok and g:
                        girl[name] += 1
                    if ok and b:
                        boy[name] += 1
        if i % 25 == 0 or i == len(files):
            print(f"  [스캔] {i}/{len(files)}", flush=True)
    return total, girl, boy


def build_dict_text(entries: list[tuple[str, int]]) -> str | None:
    """`character_dict_count` 의 닫는 중괄호 직전에 추가한 **전체 텍스트**를 만든다.

    쓰지 않고 돌려주기만 한다 - 두 자산을 다 만든 뒤 함께 써야 반쪽 상태가 안 생긴다.
    같은 블록이 여러 번 생겨도 무해하다: 중복은 호출부가 임포트한 모듈 기준으로
    이미 걸러냈다(마커는 사람이 읽기 위한 표시일 뿐 중복 방지 수단이 아니다).

    파일 구조(실측): `character_dict = {` ... `character_dict_count = {` ... `}`(파일 끝).
    그래서 **마지막** `}` 앞이 삽입 지점이다. 통째로 다시 쓰지 않는 이유는
    `character_dict` 28,836줄을 건드릴 이유가 없기 때문이다.
    """
    # 바이트로 읽어야 CRLF 가 보존된다. (`read_text(newline=...)` 은 3.13+ 전용이고,
    # 기본 텍스트 읽기는 CRLF 를 `\n` 으로 바꿔 6.4MB 파일을 통째로 다시 쓰게 만든다.)
    text = DICT_PATH.read_bytes().decode("utf-8")
    idx = text.rfind("}")
    if idx == -1:
        raise SystemExit("danbooru_character.py 에서 닫는 중괄호를 못 찾았다")
    if not entries:
        return None
    # ⚠️ 사전 파일에 따라 마지막 항목의 후행 쉼표가 없을 수 있다
    #    (artist_dictionary.py 가 그랬다). 그대로 이어 붙이면 SyntaxError 가 난다.
    prefix = text[:idx].rstrip()
    if prefix and not prefix.endswith(("{", ",")):
        prefix += ","
    lines = [f"    {MARKER} (신규 캐릭터) ---{NEWLINE}"]
    for tag, count in entries:
        lines.append(f"    {json.dumps(tag, ensure_ascii=False)}: {count},{NEWLINE}")
    return prefix + NEWLINE + "".join(lines) + text[idx:]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--counts", required=True)
    ap.add_argument("--corpus", action="append", default=[])
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 쓴다")
    ap.add_argument("--min-girl-ratio", type=float, default=10.0,
                    help="`solo` 기준 1girl/1boy 비율이 이 값 미만이면 analysis 제외 "
                         "(기본 10 - 추가분 전수 분포에서 고름)")
    ap.add_argument("--max-color-kinds", type=int, default=MAX_COLOR_KINDS,
                    help=f"personal_color 가짓수가 이 값 이상이면 비인간으로 보아 "
                         f"analysis 에서 제외 (기본 {MAX_COLOR_KINDS} - 전수 분포에서 고름)")
    args = ap.parse_args()

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import danbooru_character


    known_tags = {str(k).strip().lower() for k in danbooru_character.character_dict_count}
    analysis = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    have = flatten_names(analysis)
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    rows = list(csv.DictReader(Path(args.counts).open(encoding="utf-8-sig")))

    print(f"배포본 analysis {len(have):,}종 / dict {len(known_tags):,}종")
    print(f"증분 프로필 {sum(len(v) for v in profile.values()):,}종\n")

    # 대상: analysis 에 없는 것(추가) ∪ dict 에 없는 것(추가)
    need_analysis = {n for n in (r["character"].strip() for r in rows)
                     if n.lower() not in have}
    need_dict = {n for n in (r["character"].strip() for r in rows)
                 if n.lower() not in known_tags}
    targets = need_analysis | need_dict
    print(f"analysis 추가 후보 {len(need_analysis):,}종 / dict 추가 후보 {len(need_dict):,}종"
          f"  (합집합 {len(targets):,})\n")

    total, girl, boy = scan_corpus(targets, [Path(c) for c in args.corpus])

    def ratio(name: str) -> float:
        b = boy.get(name, 0)
        return float("inf") if b == 0 else girl.get(name, 0) / b

    rejected = {n for n in targets if ratio(n) < args.min_girl_ratio}
    print(f"\n[성별 실측] `solo` 기준 1girl/1boy 비율 < {args.min_girl_ratio}"
          f" 인 것 {len(rejected):,}종 - analysis 에서 제외(사전에는 넣는다)")
    for n in sorted(rejected, key=ratio)[:10]:
        print(f"    girl {girl.get(n,0):>5,} / boy {boy.get(n,0):>5,}"
              f"  = {ratio(n):>5.2f}  {n}")

    # ── analysis 병합 ────────────────────────────────────────────────────
    added = suppressed = 0
    for group, members in profile.items():
        if not isinstance(members, dict):
            continue
        for name, data in members.items():
            key = name.strip().lower()
            if key in have or name.strip() in rejected:
                continue
            # 색이 '아무 여자의 평균' 이면 이 엔트리는 개체가 아니라 같이 그려진
            # 사람을 묘사한다. 부분 억제(색·가슴만 끄기)도 해봤지만 characteristics
            # 에 머리 모양이 그대로 남아(long hair 41% · twintails 14%) 어차피
            # 반쪽이었다. 통째로 뺀다 - 사전에는 남으니 이름은 여전히 자동완성된다.
            if len(data.get("personal_color") or []) >= args.max_color_kinds:
                suppressed += 1
                continue
            entry = {k: v for k, v in data.items() if k not in DROP_FIELDS}
            entry["gender"] = "girl"
            entry.setdefault("aliases", [name])
            analysis.setdefault(group, {})[name] = entry
            have.add(key)
            added += 1
    print(f"\n[analysis] 추가 {added:,}종 -> 총 {len(have):,}종")
    print(f"  비인간으로 보아 제외 {suppressed:,}종"
          f"  (personal_color 가짓수 >= {args.max_color_kinds})")

    # ── dict 병합 (아직 쓰지 않는다) ─────────────────────────────────────
    new_entries = sorted(((n, total.get(n, 0)) for n in need_dict if total.get(n, 0) > 0),
                         key=lambda kv: -kv[1])
    print(f"\n[dict] 추가 {len(new_entries):,}종  (빈도는 필터 없는 전수 출현)")
    for tag, cnt in new_entries[:8]:
        print(f"    {cnt:>7,}  {tag}")
    dict_text = build_dict_text(new_entries)

    analysis_text = json.dumps(analysis, ensure_ascii=False, indent=2)
    if not args.apply:
        print(f"\n  [dry-run] analysis 예상 {len(analysis_text.encode('utf-8'))/1024/1024:.1f} MB"
              f" (현재 {ANALYSIS_PATH.stat().st_size/1024/1024:.1f} MB)"
              f" · dict {'갱신 예정' if dict_text else '변경 없음'}")
        return 0

    # ⚠️ 두 자산을 **여기서 함께** 쓴다. 예전에는 analysis 를 먼저 쓰고 사전 단계에서
    #    조용히 빠져나가 exit 0 이 되면서, 프로필만 있고 사전 태그가 없는 반쪽 상태가
    #    만들어질 수 있었다. 그런 프로필은 `cat == 'character'` 게이트를 통과하지
    #    못해 영영 안 보인다. 앞 단계에서 예외가 나면 아무것도 안 쓴 상태로 끝난다.
    shutil.copy2(ANALYSIS_PATH, ANALYSIS_PATH.with_suffix(".json.bak"))
    write_preserving_crlf(ANALYSIS_PATH, analysis_text)
    print(f"\n  {ANALYSIS_PATH}  {ANALYSIS_PATH.stat().st_size/1024/1024:.1f} MB (.bak 보관)")
    if dict_text:
        shutil.copy2(DICT_PATH, DICT_PATH.with_suffix(".py.bak"))
        DICT_PATH.write_bytes(dict_text.encode("utf-8"))
        print(f"  {DICT_PATH.name} 갱신 (.bak 보관)")
    else:
        print(f"  {DICT_PATH.name} 변경 없음 (추가할 태그 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
