"""캐릭터 **기본(Default) 의상** 분포를 `data/character_analysis.json` 에 채운다(사용자 지시 2026-10-22).

왜 비어 있었나:
  · 원본 빌더(`tools/character_profile/analyze_characters.py`)와 증분 빌더(`tools/build_character_profile_increment.py`)는
    의상을 `key_clothes` 로 **계산했다.**
  · 그런데 병합(`tools/merge_character_profile_increment.py` `DROP_FIELDS`)과 원본 재빌드 파이프라인이 그 필드를
    버렸다 - "배포본 스키마에 없고 툴팁도 안 쓴다". 그래서 배포본 기본 엔트리에는 의상 필드가 아예 없고,
    `alternates[*].attire`(공식 의상 변형 · `add_alternate_costumes.py`)만 의상을 들고 있다.
  · 캐릭터 상세보기의 Attire 칸은 기본 보기에서 늘 빈 목록을 받았다(`character_viewer_service._variant_items`).

이 도구는 기본 엔트리에 `attire` 를 넣는다 - 변형과 **같은 모양**(`[{tag, count, pct}]` · pct 내림차순).

분류(무엇이 '입는 것' 인가) = **이벤트 맵 3단 지도**(`core/event_map/tree_3depth.json` · Danbooru 위키 tag_groups) -
`TreeAttireClassifier` 참조. 기본값이다(사용자 지시 2026-10-22: "더 성능이 좋은 분류 도구가 있다").
  · 옛 분류(`--classifier legacy` = `add_alternate_costumes.classify_tag` · `data/clothes_list.txt`)는 목록 자체가 거칠어
    `low ponytail` · `red nails` · `nail polish` · `bare shoulders` 를 의상으로 쳤다. 변형(`alternates[*].attire`)은 아직
    그 분류로 만든 값이다 - 변형 의상은 변형 프롬프트에 실리므로 이 도구는 건드리지 않는다.

원천 = 프로필과 같은 코퍼스 · 같은 필터:
    data/tags/tags_*.parquet (+ --corpus 증분 버킷)
    `<1girl|1boy>` ∧ `solo` ∧ 어떤 태그에도 "alternate" 없음 ∧ "cosplay" 없음 ∧ (변형을 접은 뒤) 인물 1명
    (`build_character_profile_increment.apply_filter` 와 같은 뜻)
  · 성별은 엔트리 `gender` 를 따른다(girl -> 1girl · boy -> 1boy). `other`(비인간 30)는 만들지 않는다.
  · pct 의 분모는 **이 필터를 통과한 행 수**다 - 엔트리 `total_rows` 는 옛 코퍼스(원본 9,738종)에서 온 값이라 다를 수 있다.
  · 이미 특징 · 색에 있는 태그(안경이 기본값인 324종의 `glasses` 등)는 의상에 다시 넣지 않는다.

규약(병합 · 안경 도구와 같다):
  · 기본은 `attire` 가 **없는** 엔트리만 채운다(멱등). `--refresh` 면 다시 계산해 덮는다.
  · 그 밖의 필드는 한 글자도 안 바꾼다. `attire` 는 `characteristics` 바로 뒤에 놓는다.
  · CRLF 를 보존한다(끝에 줄바꿈 없음). 쓰기 전 무변경 왕복이 바이트 일치하는지 확인한다.
  · 쓰기 전에 `.json.attire.bak` 을 남긴다.

    python tools/add_default_attire.py --corpus C:/VNR/DEV/tag_increment_full/buckets --cache <tally.json>          # dry-run
    python tools/add_default_attire.py --corpus C:/VNR/DEV/tag_increment_full/buckets --cache <tally.json> --apply

⚠️ 사전에 새 캐릭터를 병합하면(`merge_character_profile_increment.py`) 이 도구를 다시 돌려야 새 엔트리에 의상이 붙는다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"
NEWLINE = "\r\n"

sys.path.insert(0, str(Path(__file__).resolve().parent / "character_profile"))
sys.path.insert(0, str(REPO_ROOT))
from add_alternate_costumes import BREAST_TAGS, classify_tag  # noqa: E402  옛 분류(--classifier legacy)

TREE_PATH = REPO_ROOT / "core" / "event_map" / "tree_3depth.json"

# 저장 문턱 30% - 색(personal_color) 문턱과 같다. 화면 문턱은 소비자(`CharacterViewerService.DEFAULT_ATTIRE_MIN_PCT`
# = 40)가 따로 건다 - 저장을 화면보다 낮게 두어 화면 문턱을 다시 스캔 없이 30 까지 내릴 수 있게 했다.
# 실측(2026-10-22 · 16,670종 · 175 버킷): 15% 면 평균 17.3개 · 파일 41.5MB -> 70MB(변형 문턱 그대로는 너무 크다) ·
# 30% 면 평균 8.3개 · 55.9MB · 40% 면 5.5개 · 51.3MB.
MIN_STORE_PCT = 30.0
TOP_N = 30
# 캐시에 남기는 최저 비율 - 문턱을 바꿔 다시 볼 수 있게 저장 문턱보다 낮게 둔다.
CACHE_FLOOR_PCT = 5.0

_PAREN = re.compile(r"\s*\([^()]*\)")


def base_name(name: str) -> str:
    """`build_character_profile_increment.base_name` 과 같다 - 변형 태깅을 접는다."""
    prev = None
    out = str(name or "").strip().lower()
    while prev != out:
        prev = out
        out = _PAREN.sub("", out).strip()
    if ":" in out:
        out = out.split(":", 1)[0].strip()
    return out


def split_names(value) -> list[str]:
    if not value:
        return []
    return [t.strip() for t in str(value).split(", ") if t.strip()]


class TreeAttireClassifier:
    """태그가 **입는 것**(옷 · 장신구 · 머리 장식)인지 - 이벤트 맵 3단 지도(Danbooru 위키 tag_groups)로 가른다.

    지도의 자리(D1 > D2 > D3)로 본다. 한 태그가 여러 자리에 있을 수 있다(`hair bow` = 머리 > Objects · 장신구 · 의상).
      · 강한 자리 = D1 `Attire and body accessories` 에서 화장(`makeup`) · 노출(`nudity`) 쪽을 뺀 곳 -> 의상
      · 약한 자리 = 몸 갈래 안의 '입는 것' 절(`WEAK`) - 머리 장식 · 귀걸이 · 양말류 · 어깨 옷 · 가슴 옷.
        노출 자리에도 있으면 의상이 아니다(`bare shoulders` · `off shoulder` · `no bra`).
      · 지도에 있는데 위 어디에도 없으면 의상이 아니다(`low ponytail` = 머리 모양 · `halo` · `animal ears` = 몸 ·
        `nail polish` = 화장 · `bare shoulders` = 노출).
      · 단, 그 자리가 몸 · 노출 · 화장이 **아닌** 딴 갈래뿐이면(무늬 · 동물 · 사물 - `heart earrings` = symbols ·
        `cat hair ornament` = cats) 아래 '앞 낱말 떼기' 를 계속한다 -> earrings · hair ornament.
        몸 · 노출 자리는 계속하지 않는다 - `no shoes` -> shoes · `no bra` -> bra 로 뒤집히면 안 된다.
    지도에 없는 태그(지도는 **색 태그를 버렸다** - `white shirt` · `red bow`)는 앞 낱말을 하나씩 떼며 처음 걸리는
    자리로 본다: `white shirt` -> shirt · `plaid skirt` -> skirt · `black-framed eyewear` -> eyewear ·
    `red nails` -> nails(어디에도 없다 = 의상 아님) · `very long braid` -> long braid(머리 모양).
    지도에 없는 포괄 낱말(`UMBRELLA` - `black headwear` · `white footwear` · `gold trim`)만 손으로 둔다.
    끝까지 못 찾으면 의상이 아니다(`striped` · `animal print` - 무늬만으로는 옷이 아니다).
    """

    ATTIRE_D1 = "Attire and body accessories"
    NOT_WORN_D2 = frozenset({"tag_group:makeup", "tag_group:nudity"})
    NUDITY_D2 = "tag_group:nudity"
    WEAK = frozenset({
        ("tag_group:hair", "Objects"),
        ("tag_group:ears_tags", "Objects for the ears; or, objects with ears"),
        ("tag_group:feet", "Clothing & Accessories"),
        ("tag_group:shoulders", "Attire for shoulders"),
        ("tag_group:breasts_tags", "Clothes for breasts"),
    })
    # 지도에 없거나(포괄 태그) 엉뚱한 자리에만 있는(`jewelry` = 들고 있는 것) 포괄 낱말.
    UMBRELLA = frozenset({"headwear", "footwear", "eyewear", "legwear", "handwear", "neckwear", "sleeves", "trim",
                          "jewelry"})
    BODY_D1 = "Body"

    def __init__(self, tree_path: Path = TREE_PATH):
        tree = json.loads(Path(tree_path).read_text(encoding="utf-8"))
        self.place: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for d1 in tree.get("d1") or []:
            for d2 in d1.get("d2") or []:
                for d3 in d2.get("d3") or []:
                    for tag in d3.get("tags") or []:
                        self.place[str(tag)].append((str(d1.get("id")), str(d2.get("id")), str(d3.get("id"))))
        self._memo: dict[str, bool] = {}

    def _direct(self, tag: str) -> bool | None:
        """True = 의상 · False = 의상 아님(확정) · None = 모름(앞 낱말을 떼고 계속)."""
        if tag in self.UMBRELLA:
            return True
        hits = self.place.get(tag)
        if not hits:
            return None
        strong = any(d1 == self.ATTIRE_D1 and d2 not in self.NOT_WORN_D2 for d1, d2, _ in hits)
        weak = any((d2, d3) in self.WEAK for _, d2, d3 in hits)
        nude = any(d2 == self.NUDITY_D2 for _, d2, _ in hits)
        if strong or (weak and not nude):
            return True
        if any(d1 in (self.BODY_D1, self.ATTIRE_D1) for d1, _, _ in hits):
            return False                    # 몸 · 노출 · 화장 자리 = 확정
        return None                         # 딴 갈래(무늬 · 동물 · 사물)뿐 - 더 짧은 꼬리를 본다

    def is_attire(self, tag: str) -> bool:
        tag = " ".join(str(tag or "").replace("_", " ").lower().split())
        hit = self._memo.get(tag)
        if hit is None:
            words = tag.split(" ")
            hit = False
            for i in range(len(words)):
                found = self._direct(" ".join(words[i:]))
                if found is not None:
                    hit = found
                    break
            self._memo[tag] = hit
        return hit


def legacy_attire_classifier():
    """옛 분류(`add_alternate_costumes.classify_tag` · `clothes_list.txt`) - 변형 의상과 같은 잣대."""
    clothes_set, chars_set = load_tag_sets()
    memo: dict[str, bool] = {}

    def is_attire(tag: str) -> bool:
        hit = memo.get(tag)
        if hit is None:
            hit = memo[tag] = classify_tag(tag.replace(" ", "_"), clothes_set, chars_set) == "clothes"
        return hit
    return is_attire


def make_classifier(kind: str):
    return TreeAttireClassifier().is_attire if kind == "tree" else legacy_attire_classifier()


def load_tag_sets() -> tuple[set[str], set[str]]:
    """`add_alternate_costumes.load_tag_sets` 와 같은 규칙(밑줄 형식 · 특징에서 가슴 태그 제외). 경로만 리포 기준."""
    def read(name: str) -> set[str]:
        return {line.strip().replace(" ", "_")
                for line in (DATA_DIR / name).read_text(encoding="utf-8").splitlines() if line.strip()}
    clothes = read("clothes_list.txt")
    chars = read("characteristic_list.txt") - BREAST_TAGS
    return clothes, chars


def bucket_files(extra: list[Path]) -> list[Path]:
    files = sorted((DATA_DIR / "tags").glob("tags_*.parquet"))
    for d in extra:
        files += sorted(Path(d).glob("tags_*.parquet"))
    return files


def scan(analysis: dict, files: list[Path], attire_tag) -> dict:
    """(그룹, 이름) -> {"rows": n, "tags": {태그: 수}} - `attire_tag` 가 의상이라고 하는 태그만 센다.

    ⚠️ 캐시는 **만든 분류기의 후보만** 담는다. 다른 분류기로 읽으면 두 분류기가 다 의상이라고 한 태그만 남는다
       (2026-10-22 캐시는 옛 분류로 만들었다 - 지도로 다시 거르면 옛 목록에 없던 의상은 빠진다. 다 넣으려면 다시 스캔).
    """

    # 이름 · 별칭(소문자) -> [(그룹, 이름, 인물 태그)]
    lookup: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for group, members in analysis.items():
        if group.startswith("_") or not isinstance(members, dict):
            continue
        for name, data in members.items():
            if not isinstance(data, dict):
                continue
            gender = str(data.get("gender") or "girl").strip().lower()
            if gender not in ("girl", "boy"):
                continue
            person = "1girl" if gender == "girl" else "1boy"
            keys = {name.strip().lower()} | {str(a).strip().lower() for a in data.get("aliases") or []}
            for key in keys:
                if key:
                    lookup[key].append((group, name, person))

    rows: Counter = Counter()
    tally: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for i, path in enumerate(files, 1):
        df = pd.read_parquet(path, columns=["character", "general"])
        general = df["general"].fillna("").astype(str)
        padded = ", " + general + ", "
        keep = padded.str.contains(", solo, ", regex=False)
        keep &= ~general.str.contains("alternate", regex=False)
        keep &= ~general.str.contains("cosplay", regex=False)
        girl = padded.str.contains(", 1girl, ", regex=False)
        boy = padded.str.contains(", 1boy, ", regex=False)
        keep &= girl | boy
        sub = df[keep]
        for value, gen, g, b in zip(sub["character"], sub["general"], girl[keep], boy[keep]):
            names = split_names(value)
            if not names:
                continue
            if len({base_name(n) for n in names if base_name(n)}) > 1:
                continue                       # 진짜 두 명 - 누구의 옷인지 알 수 없다
            targets = set()
            for n in names:
                for group, name, person in lookup.get(n.lower(), ()):
                    if (person == "1girl" and g) or (person == "1boy" and b):
                        targets.add((group, name))
            if not targets:
                continue
            tags = {t.strip() for t in str(gen or "").split(",") if t.strip()}
            worn = [t for t in tags if attire_tag(t)]
            for key in targets:
                rows[key] += 1
                tally[key].update(worn)
        if i % 25 == 0 or i == len(files):
            print(f"  [스캔] {i}/{len(files)}  캐릭터 {len(rows):,}", flush=True)

    out = {}
    for key, n in rows.items():
        kept = {t: c for t, c in tally[key].items() if c / n * 100 >= CACHE_FLOOR_PCT}
        out[f"{key[0]}\t{key[1]}"] = {"rows": n, "tags": kept}
    return out


def build_attire(entry: dict, cached: dict, min_pct: float, top_n: int, attire_tag=None) -> list[dict]:
    n = int(cached.get("rows") or 0)
    if n <= 0:
        return []
    taken = {str(e.get("tag")) for key in ("personal_color", "characteristics")
             for e in entry.get(key) or [] if isinstance(e, dict)}
    items = []
    for tag, cnt in sorted(cached["tags"].items(), key=lambda kv: (-kv[1], kv[0])):
        pct = round(cnt / n * 100, 1)
        if pct < min_pct:
            break
        if tag in taken or (attire_tag is not None and not attire_tag(tag)):
            continue
        items.append({"tag": tag, "count": int(cnt), "pct": pct})
        if len(items) >= top_n:
            break
    return items


def with_attire(entry: dict, attire: list[dict]) -> dict:
    """`attire` 를 `characteristics` 바로 뒤에 둔다(다른 키 순서는 그대로)."""
    out = {}
    for k, v in entry.items():
        if k == "attire":
            continue
        out[k] = v
        if k == "characteristics":
            out["attire"] = attire
    if "attire" not in out:
        out["attire"] = attire
    return out


def dump(analysis: dict) -> bytes:
    return json.dumps(analysis, ensure_ascii=False, indent=2).replace("\n", NEWLINE).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", action="append", default=[], help="추가 버킷 디렉터리(증분)")
    ap.add_argument("--cache", type=Path, default=None, help="스캔 결과 캐시(JSON) - 있으면 읽고, 없으면 만들어 둔다")
    ap.add_argument("--min-rows", type=int, default=10, help="필터 통과 행이 이 값 미만이면 만들지 않는다")
    ap.add_argument("--min-pct", type=float, default=MIN_STORE_PCT, help=f"저장 문턱 (기본 {MIN_STORE_PCT})")
    ap.add_argument("--top-n", type=int, default=TOP_N)
    ap.add_argument("--classifier", choices=("tree", "legacy"), default="tree",
                    help="의상 분류 - tree = 이벤트 맵 3단 지도(기본) · legacy = clothes_list.txt(변형과 같은 옛 잣대)")
    ap.add_argument("--refresh", action="store_true",
                    help="이미 attire 가 있는 엔트리도 다시 계산해 덮는다(자격이 없어진 엔트리는 attire 를 뗀다)")
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 쓴다")
    args = ap.parse_args()

    raw = ANALYSIS_PATH.read_bytes()
    analysis = json.loads(raw.decode("utf-8"))
    if dump(analysis) != raw:
        raise SystemExit("무변경 왕복이 바이트 일치하지 않는다 - 형식(CRLF · indent · 끝 줄바꿈)이 바뀌었다. 쓰지 않는다")

    attire_tag = make_classifier(args.classifier)
    if args.cache and args.cache.exists():
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
        print(f"[캐시] {args.cache}  {len(cache):,}종")
    else:
        files = bucket_files([Path(c) for c in args.corpus])
        print(f"[원천] {len(files)}개 버킷")
        cache = scan(analysis, files, attire_tag)
        if args.cache:
            args.cache.parent.mkdir(parents=True, exist_ok=True)
            args.cache.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
            print(f"[캐시] 저장 {args.cache}")

    filled = skipped_have = no_rows = few_rows = empty = dropped = 0
    for group, members in analysis.items():
        if group.startswith("_") or not isinstance(members, dict):
            continue
        for name in list(members):
            entry = members[name]
            if not isinstance(entry, dict):
                continue
            if "attire" in entry and not args.refresh:
                skipped_have += 1
                continue
            cached = cache.get(f"{group}\t{name}")
            if not cached or int(cached.get("rows") or 0) < args.min_rows:
                if not cached:
                    no_rows += 1
                else:
                    few_rows += 1
                if "attire" in entry:      # --refresh: 자격이 없어졌으면 이 도구가 넣은 값을 뗀다
                    members[name] = {k: v for k, v in entry.items() if k != "attire"}
                    dropped += 1
                continue
            attire = build_attire(entry, cached, args.min_pct, args.top_n, attire_tag)
            if not attire:
                empty += 1
            members[name] = with_attire(entry, attire)
            filled += 1
    print(f"[attire] 채움 {filled:,}종 (그중 문턱 넘는 의상 없음 {empty:,}) · 이미 있음 {skipped_have:,}"
          f" · 코퍼스 행 없음(other 포함) {no_rows:,} · 행 {args.min_rows} 미만 {few_rows:,}"
          f" · 뗌 {dropped:,}  [분류 {args.classifier}]")

    body = dump(analysis)
    print(f"  크기 {len(raw)/1024/1024:.1f} MB -> {len(body)/1024/1024:.1f} MB")
    if not args.apply:
        print("  [dry-run] 쓰지 않았다 - --apply 로 쓴다")
        return 0
    shutil.copy2(ANALYSIS_PATH, ANALYSIS_PATH.with_suffix(".json.attire.bak"))
    ANALYSIS_PATH.write_bytes(body)
    print(f"  {ANALYSIS_PATH} 갱신 (.json.attire.bak 보관)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
