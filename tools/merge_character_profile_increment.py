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

# `color_kinds_raw` 는 폐기된 신호다(가짓수 게이트를 쓰던 시절). 옛 증분 파일에 남아
# 있을 수 있으니 계속 걷어낸다 — 28MB 배포본에 쓸모없는 필드가 실리면 안 된다.
DROP_FIELDS = ("key_clothes", "color_kinds_raw", "built_from")
MARKER = "# --- increment"

# 비인간·아바타(개체가 아닌 것)를 가려내는 문턱 — **최고 색 비율**이다.
#
# 색 칩이 '고유색' 이 아니라 '그림 속 아무 여자의 색' 일 때를 잡는다. 진짜 캐릭터는
# 고유색이 높게 뜨고, 아바타·비인간은 모집단 분포로 흩어져 어느 하나도 이 값을
# 못 넘는다. `build_character_profile_increment.py --min-pct-color` 와 같은 값이다.
#
# ⚠️ 예전에는 **가짓수**(`>= 20`)로 갈랐는데 그것은 잣대가 아니라 코퍼스 크기의
#    대리값이었다(실측: 행 200 미만 평균 11.3종 -> 행 5,000 이상 평균 40.2종).
#    그대로 두면 hatsune miku(59종) · hakurei reimu(44) · artoria pendragon(46) ·
#    ganyu(40) 가 비인간으로 걸린다. 근거로 삼았던 `miku 2 · ganyu 2` 는
#    **가지치기된 배포본**, `rx-78-2 28 · moogle 29` 는 **가지치기 안 된 증분**에서
#    온 값이라 처음부터 서로 다른 자를 비교한 것이었다.
MIN_PCT_COLOR = 30.0

# ⚠️ 두 자산 모두 **CRLF** 다(실측: character_analysis.json / danbooru_character.py).
# `write_text` 는 `\n` 으로 써서 28MB·6.4MB 파일이 통째로 diff 에 잡힌다.
# 무변경 왕복이 바이트 일치하는지 확인하고 쓴다.
NEWLINE = "\r\n"


def write_preserving_crlf(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))


def looks_nonhuman(data: dict, min_pct_color: float = MIN_PCT_COLOR) -> bool:
    """**문턱을 넘는 색이 하나도 없으면** 개체가 아니다 — 제외한다.

    색 칩이 '고유색' 이 아니라 '그림 속 아무 여자의 색' 일 때를 잡는 것이 목적이다.
    진짜 캐릭터는 고유색이 높은 비율로 뜨고(miku `blue hair` 90.5% · reimu 2개 ·
    `2b` 76.5%), 아바타·비인간은 색이 모집단 분포로 흩어져 **어느 하나도 30% 를
    못 넘는다.**

    ⚠️ **가짓수로 세면 안 된다.** 예전 규칙은 `len(personal_color) >= 20` 이었는데,
    가짓수는 잣대가 아니라 **코퍼스 크기의 대리값**이다(실측 9,327종: 행 200 미만
    평균 11.3종 -> 행 5,000 이상 평균 40.2종 -> miku 59종). 그 값으로 재면
    hatsune miku · hakurei reimu · artoria pendragon · ganyu 가 통째로 비인간으로
    걸린다. 원래 근거였던 `miku 2 · ganyu 2` 는 **가지치기된 배포본**에서, `rx-78-2 28
    · moogle 29` 는 **가지치기 안 된 증분**에서 온 값이라 처음부터 서로 다른 자였다.

    이 판정은 문턱을 **여기서 직접** 걸기 때문에 빌더가 가지치기를 했든 안 했든
    같은 답을 준다(가지치기 안 된 비인간도 최고 pct 가 문턱 미만이다).

    실측(9,327종): 걸리는 것 121종(1.3%) — warrior of light (ff14) · inkling player
    character · sensei (blue archive) · doctor (arknights) · avatar (wow) ·
    ragnarok online 직업군 · manjuu · slime · poring · pikachu · hello kitty ·
    enemy naval mine. 상위 25 오탐 0.
    경계를 1 로 올리면 2b (nier:automata) 76.5% · mystia lorelei 87.9% ·
    texas (arknights) 83.5% 가 걸린다 — **0 이 경계다.**
    """
    pcts = [e.get("pct", 0) for e in (data.get("personal_color") or [])
            if isinstance(e, dict)]
    values = []
    for p in pcts:
        try:
            values.append(float(p))
        except (TypeError, ValueError):
            continue
    return not values or max(values) < float(min_pct_color)


def flatten_names(analysis: dict) -> set[str]:
    names: set[str] = set()
    for members in analysis.values():
        if isinstance(members, dict):
            names.update(str(n).strip().lower() for n in members)
    return names


def scan_corpus(targets: set[str],
                dirs: list[Path]) -> tuple[Counter, Counter, Counter, Counter]:
    """대상 캐릭터의 (전체 출현, 1girl+solo 행, 1boy+solo 행, **최신 버킷 출현**).

    `total` 은 **필터 없이** 센다 - `character_dict_count` 의 빈도는 걸러지지 않은
    출현이다(예: ouro kronii 7,253 vs 1girl solo 3,620).

    성별 신호는 **프로필과 같은 필터**로 센다(`solo ∧ ~alternate ∧ ~cosplay`).
    잣대가 다르면 판정이 무의미해진다 - 모듈 서두 참조.
    """
    files = sorted((DATA_DIR / "tags").glob("tags_*.parquet"))
    base_count = len(files)
    for d in dirs:
        files += sorted(d.glob("tags_*.parquet"))
    total: Counter = Counter()
    girl: Counter = Counter()
    boy: Counter = Counter()
    recent: Counter = Counter()
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
                    if i > base_count:
                        recent[name] += 1
                    if ok and g:
                        girl[name] += 1
                    if ok and b:
                        boy[name] += 1
        if i % 25 == 0 or i == len(files):
            print(f"  [스캔] {i}/{len(files)}", flush=True)
    return total, girl, boy, recent


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
    ap.add_argument("--min-boy-ratio", type=float, default=1.0,
                    help="`1boy` 로 만든 엔트리의 boy/girl 비율 문턱 (기본 1.0). "
                         "여성 쪽(10)과 다른 이유는 코퍼스가 여성으로 기울어 있어서다 "
                         "- floor_for() 주석 참조")
    ap.add_argument("--fix-misgendered", action="store_true",
                    help="이미 있는 엔트리라도 **성별이 틀렸으면** 이번 프로필로 "
                         "교체한다. 기본은 끔 - 추가만 하는 것이 이 도구의 안전 규약이다")
    ap.add_argument("--keep-stale-tags", action="store_true",
                    help="최신 버킷에 0행인 태그도 사전에 넣는다(옛 동작). "
                         "기본은 제외 - 개명된 옛 표기가 자동완성에 들어가면 "
                         "같은 인물이 둘로 보이고 죽은 태그로 생성하게 된다")
    ap.add_argument("--min-pct-color", type=float, default=MIN_PCT_COLOR,
                    help=f"이 비율을 넘는 색이 하나도 없으면 개체가 아니라고 보아 "
                         f"analysis 에서 제외 (기본 {MIN_PCT_COLOR} - 빌더의 "
                         f"--min-pct-color 와 같은 값이어야 한다)")
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

    total, girl, boy, recent = scan_corpus(targets, [Path(c) for c in args.corpus])

    # ⚠️ 판정의 **방향**은 프로필이 어느 필터에서 나왔는지에 달렸다.
    #    `1girl` 로 만든 엔트리는 girl/boy 비를, `1boy` 로 만든 것은 boy/girl 비를 본다.
    #    방향을 고정하면 남성 프로필이 전부 "여성이 아니다" 로 걸려 통째로 사라진다.
    built = {}
    for members in profile.values():
        if isinstance(members, dict):
            for name, data in members.items():
                if isinstance(data, dict):
                    built[name.strip()] = str(data.get("built_from") or "1girl")

    def ratio(name: str) -> float:
        """이 엔트리가 주장하는 성별 쪽 / 반대쪽. 클수록 그 성별이 확실하다."""
        want_girl = built.get(name, "1girl") == "1girl"
        mine = girl.get(name, 0) if want_girl else boy.get(name, 0)
        other = boy.get(name, 0) if want_girl else girl.get(name, 0)
        return float("inf") if other == 0 else mine / other

    def floor_for(name: str) -> float:
        """방향마다 임계가 다르다 - **코퍼스가 여성으로 크게 기울어 있기 때문**이다.

        실측:
            남성 엔트리 1,339종 중 `1girl solo` 가 0인 것  29.9%
            여성 엔트리 2,632종 중 `1boy solo` 가 0인 것    81.1%

        남성 캐릭터는 젠더벤드 그림이 흔해 `1girl solo` 행이 꽤 쌓인다. 여성 쪽
        임계(10)를 그대로 쓰면 **진짜 남성이 6.5% 나 걸린다**(fujimaru ritsuka
        (male) 은 boy 263 / girl 158 인데도 탈락했다).

        남성 방향 분포에서 다시 골랐다(1,339종): 비율 1.0 미만 28종(2.1%)은 전부
        **양성 아바타·직업군**이다 - byleth/corrin/alear/robin (fire emblem 성별
        선택), ragnarok online 직업군 전체, warrior of light (ff14),
        employee (project moon). 1.0 위부터는 terry bogard(1.66) ·
        hanzo (overwatch)(2.73) · genji(3.23) 같은 진짜 남성이다.
        """
        return (args.min_girl_ratio if built.get(name, "1girl") == "1girl"
                else args.min_boy_ratio)

    rejected = {n for n in targets if ratio(n) < floor_for(n)}
    n_boy = sum(1 for n in targets if built.get(n, "1girl") == "1boy")
    print(f"\n[성별 실측] `solo` 기준 자기 성별/반대 성별 비율이 임계 미만인 것"
          f" {len(rejected):,}종 - analysis 에서 제외(사전에는 넣는다)"
          f"   [임계 girl {args.min_girl_ratio} / boy {args.min_boy_ratio}"
          f" · 1boy 로 만든 엔트리 {n_boy:,}종]")
    for n in sorted(rejected, key=ratio)[:10]:
        print(f"    girl {girl.get(n,0):>5,} / boy {boy.get(n,0):>5,}"
              f"  = {ratio(n):>5.2f}  ({built.get(n,'1girl')})  {n}")

    # ── analysis 병합 ────────────────────────────────────────────────────
    def entry_gender(name: str) -> str:
        return "boy" if built.get(name.strip()) == "1boy" else "girl"

    def target_of(group: str, name: str, tree: dict) -> tuple[str, str, dict] | None:
        """배포본에서 같은 이름을 찾아 `(그룹, 이름, 엔트리)` 를 준다.

        ⚠️ **그룹이 다를 수 있다.** 배포본은 `employee (project moon)` 을
        `lobotomy corporation` 아래 두는데 이번 빌드는 `project moon` 으로 잡았다.
        새 그룹에 쓰면 같은 캐릭터가 두 작품에 **중복**된다 - 반드시 원래 자리에 쓴다.
        """
        hit = (tree.get(group) or {}).get(name)
        if isinstance(hit, dict):
            return group, name, hit
        low = name.strip().lower()
        for g, members2 in tree.items():
            if not isinstance(members2, dict):
                continue
            for n2, d2 in members2.items():
                if str(n2).strip().lower() == low and isinstance(d2, dict):
                    return g, n2, d2
        return None

    added = suppressed = 0
    fixed: list[tuple[str, str, str, str]] = []
    for group, members in profile.items():
        if not isinstance(members, dict):
            continue
        for name, data in members.items():
            key = name.strip().lower()
            if key in have:
                # ⚠️ **이미 있는 엔트리는 손대지 않는 것이 원칙**이다(멱등·안전).
                #    딱 한 가지 예외: 성별이 틀린 채로 배포돼 있고, 이번 실행이
                #    **반대 성별로 다시 만든** 프로필을 손에 들고 있는 경우다.
                #    실측: `1boy` 로 만들 수 있는 1,290종 중 76종이 배포본에서
                #    girl 이고, 그중 69종에 가슴 데이터가 붙어 있다
                #    (zhongli `large breasts 31.4%` · link · kirby · kuzuha).
                #    `1girl` 필터가 젠더벤드 그림을 물어 온 흔적이다.
                #
                #    양성 아바타(ragnarok 직업군 · warrior of light)는 성별 게이트를
                #    통과하지 못하므로 여기 오지 않는다 - 그쪽은 여성 프로필이
                #    틀린 것이 아니라 여성 판을 묘사한 것이다.
                if not (args.fix_misgendered and name.strip() not in rejected):
                    continue
                found = target_of(group, name, analysis)
                if found is None:
                    continue
                tgt_group, tgt_name, target = found
                if target.get("gender") == entry_gender(name):
                    continue
                if looks_nonhuman(data, args.min_pct_color):
                    continue
                fixed.append((tgt_group, tgt_name, target.get("gender"), entry_gender(name)))
                new_entry = {k: v for k, v in data.items() if k not in DROP_FIELDS}
                new_entry["gender"] = entry_gender(name)
                new_entry.setdefault("aliases", target.get("aliases") or [tgt_name])
                analysis[tgt_group][tgt_name] = new_entry
                continue
            if name.strip() in rejected:
                continue
            # 색이 '아무 여자의 평균' 이면 이 엔트리는 개체가 아니라 같이 그려진
            # 사람을 묘사한다. 부분 억제(색·가슴만 끄기)도 해봤지만 characteristics
            # 에 머리 모양이 그대로 남아(long hair 41% · twintails 14%) 어차피
            # 반쪽이었다. 통째로 뺀다 - 사전에는 남으니 이름은 여전히 자동완성된다.
            if looks_nonhuman(data, args.min_pct_color):
                suppressed += 1
                continue
            entry = {k: v for k, v in data.items() if k not in DROP_FIELDS}
            # ⚠️ 예전에는 "girl" 을 박았다 - 필터가 `1girl` 뿐이었기 때문이다.
            #    이제 `1boy` 로 만든 엔트리가 있으므로 만들어진 출처를 따른다.
            entry["gender"] = "boy" if built.get(name.strip()) == "1boy" else "girl"
            entry.setdefault("aliases", [name])
            analysis.setdefault(group, {})[name] = entry
            have.add(key)
            added += 1
    print(f"\n[analysis] 추가 {added:,}종 -> 총 {len(have):,}종")
    if fixed:
        print(f"  ★ 성별이 틀려 교체한 기존 엔트리 {len(fixed):,}종 "
              f"(--fix-misgendered)")
        for group, name, was, now in fixed[:10]:
            print(f"      {name[:38]:<38} [{group[:18]}]  {was} -> {now}")
    print(f"  개체가 아니라고 보아 제외 {suppressed:,}종"
          f"  ({args.min_pct_color}% 를 넘는 색이 하나도 없음)")

    # ── dict 병합 (아직 쓰지 않는다) ─────────────────────────────────────
    # ⚠️ **'사전에 없다' 가 곧 '추가해야 한다' 가 아니다.** Danbooru 가 태그를 개명하면
    #    옛 표기가 코퍼스에 잔뜩 남지만 신규 그림에는 안 붙는다. 그것을 자동완성에
    #    넣으면 같은 인물이 둘로 보이고, 사용자가 **죽은 태그로 생성**하게 된다.
    #
    #    실측(전수조사 800종): 신 버킷(2025/09~2026/06) 0행인 것이 131종.
    #      todoroki shouto  구1,576 / 신0     <- 죽은 표기
    #      todoroki shoto   구701  / 신353    <- 현행(이미 사전에 있다)
    #    상위 15 중 13개가 hololive 번호식 의상 태그였다(3rd/2nd/5th costume).
    #    `costume` 태그 자체는 살아 있고(신 27,147회) **서술식으로 개명**됐다 -
    #    `nekomata okayu (gyaru)` 가 구0/신161 로 새로 등장한 것이 증거다.
    #
    #    판정은 **문자열 유사도가 아니라 시기 분포**로 한다. difflib 0.86 으로는
    #    lohen<-xilonen · flins<-lisa 같은 무관한 신규 캐릭터가 쏟아진다.
    stale: list[tuple[str, int]] = []
    if args.corpus and not args.keep_stale_tags:
        fresh = []
        for n in need_dict:
            if total.get(n, 0) <= 0:
                continue
            if recent.get(n, 0) == 0:
                stale.append((n, total.get(n, 0)))
            else:
                fresh.append((n, total.get(n, 0)))
        new_entries = sorted(fresh, key=lambda kv: -kv[1])
    else:
        new_entries = sorted(((n, total.get(n, 0)) for n in need_dict if total.get(n, 0) > 0),
                             key=lambda kv: -kv[1])
    if stale:
        print(f"\n[dict] 폐기 태그로 보아 제외 {len(stale):,}종  "
              f"(최신 버킷 0행 - 개명됐거나 더 이상 쓰이지 않는다)")
        for tag, cnt in sorted(stale, key=lambda kv: -kv[1])[:8]:
            print(f"    구 {cnt:>7,} / 신 0   {tag}")
    print(f"\n[dict] 추가 {len(new_entries):,}종  (빈도는 필터 없는 전수 출현)")
    for tag, cnt in new_entries[:8]:
        print(f"    {cnt:>7,}  {tag}")
    dict_text = build_dict_text(new_entries)

    analysis_text = json.dumps(analysis, ensure_ascii=False, indent=2)
    if not args.apply:
        # ⚠️ 둘 다 **CRLF 기준**으로 재야 한다. `json.dumps` 는 LF 라 그대로 비교하면
        #    줄 수(약 170만)만큼 작아 보여 **추가를 했는데 파일이 줄어드는 것처럼** 나온다.
        predicted = len(analysis_text.encode("utf-8")) + analysis_text.count("\n")
        print(f"\n  [dry-run] analysis 예상 {predicted/1024/1024:.1f} MB"
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
