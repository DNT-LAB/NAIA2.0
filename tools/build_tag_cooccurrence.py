# -*- coding: utf-8 -*-
"""함께 쓰이는 태그 사전 — `data/tag_cooccurrence.json`.

## 무엇을 고치려는 것인가

오른쪽 태그 사전 카드는 `implications` / `related`(비슷한 것) / `specific`(더 구체적인 것)
셋 중 하나라도 있어야 렌더된다. 그런데 랭커를 바로잡은 뒤 **freq>=1000 태그의 65.4%가
셋 다 비었다**(실측 2026-07-30). 근거 없는 유사어를 안 내놓기로 한 결과라 그 자체는
맞지만, 사용자에게는 "일부 태그는 정보창이 안 뜬다" 로 보인다.

사용자 판단: **"없으면 만들면 되는게 아닐까 싶어요."** 맞다 — 사전에 관계가 없을 뿐,
실제 게시물에는 그 태그와 함께 쓰인 태그가 있다.

## '비슷한 것' 과 다른 것이다

여기서 만드는 것은 **동반**이다. 유사가 아니다. `sweater` 와 함께 쓰이는 것은
`long sleeves` 나 `plaid skirt` 이지, `sweater` 와 비슷한 옷이 아니다. 그래서 UI 에도
"함께 쓰이는 것" 이라는 다른 줄로 나간다 — 이름을 섞으면 오늘 고친 결함이 되돌아온다.

## 근거

`data/quick_search/` 52개 파티션(449만 이벤트)의 동반 행렬.

**순위는 confidence, lift 는 게이트다.** 두 역할을 갈라 놓는다:

    confidence(a -> b) = P(b | a)                      <- 정렬
    lift(a, b)         = P(a AND b) / (P(a) * P(b))    <- 통과/탈락

빈도 그대로 쓰면 어떤 태그를 넣어도 `1girl` · `long hair` 가 1위가 된다(앵커 추출에서
실측했다 — `breasts` / `blush` 가 전부 1위였다). lift 게이트가 그 배경을 걷어낸다.
거꾸로 lift 로 정렬하면 표본 2건짜리 희귀 변형이 최상위에 온다. 그래서 동반수 하한도 건다.

## 확정 정책 (2026-07-30, 골드셋 16태그 실측)

`int8` 오버플로를 고쳐 카운트가 정확해지자 confidence 단독은 고빈도 독식이 드러났다
(`sweater -> long sleeves, blush, smile`). 점수식 여섯 개를 같은 골드셋으로 채점했다:

    confidence 단독 .289 / lift = PMI .281 / nPMI .375 / 차분형 P(b|a)-P(b) .484
    혼합 conf x min(log2 lift, 3) .586 / + 관계 중복제거 .625 / + P(B) 상한 .633

그리고 **몇 개를 보여주는가가 점수식보다 크게 작용했다**:

    top-3 .778 / top-4 .746 / top-5 .712 / top-6 .655 / top-8 .574

8칸을 채우면 뒤쪽은 순위가 낮아서 넣은 것이고 그게 오답이다. 사용자 결정은
**"유의미한 결과가 나오는 케이스만 남기고 나머지는 출력하지 않는다"** 다. 그래서:

  1. 순위 = `confidence x min(log2 lift, 3)`
  2. 후보 `P(B) > 0.30` 제외 — `breasts`(.452) 같은 코퍼스 배경
  3. 후보 개별 `lift >= 2.0` — 못 넘으면 안 내보낸다. 하나도 없으면 **빈 목록**
  4. UI 의 다른 관계 줄(딸려오는 것/비슷한 것/구체적인 것)과 겹치면 제외
  5. **함의 제외** — `P(후보|대상)` 또는 `P(대상|후보)` 가 0.95 이상이면 부모/자식이다.
     관계 사전에 그 쌍이 없어도 통계로 잡힌다(`panties -> underwear` = 1.000).
     이게 필요한 이유는 관계 사전 자체에 공백이 있어서다 — `underwear` 의 children 에
     `panties` 가 없다. 사전을 못 믿을 때 동반 통계가 그 역할을 대신한다.
  6. 중심 명사가 같으면 변형이다(`same_family`) — 색 배경 계열이 여기서 걸린다
  7. 일반 태그에 성인 후보 금지, 작가·캐릭터·메타태그 분류 후보 금지
  8. 상위 **4개**만

`blush` 는 이 정책에서 빈 목록이 된다(최고 lift 1.784). 특징적으로 동반하는 것이 없는
태그이고, 8칸을 채우면 전부 배경 태그가 된다 — 그게 없어야 한다는 것이 이 설계의 요지다.
정책을 바꾸면 `--eval` 로 다시 채점하고 이 주석과 아래 `note` 를 같이 고쳐라
(문서·구현·메타데이터가 서로 다른 말을 하고 있던 적이 있다).

## 무엇을 배제하는가

  · 배타쌍(`data/tag_exclusive_pairs.json`) — 함께 안 쓰이는 쌍
  · 부정쌍(`no X` <-> `X`) — `core.tag_relation_ranker._is_negation_pair`
  · 연령·금기 어휘 — `tools.thumb_age_guard`
  세 필터를 여기서 **미리** 적용한다. 런타임에 다시 걸 필요가 없게.

## 쓰는 법

    python tools/build_tag_cooccurrence.py --dry-run
    python tools/build_tag_cooccurrence.py --top 8 --min-pair 30
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy import sparse

from core.event_corpus_index import EventCorpusIndex, normalize_tag
from core.kr_tag_loader import load_kr_tag_records
from core.tag_relation_ranker import _is_negation_pair, is_exclusive_pair
from tools.thumb_age_guard import danger_age_hits

OUT = Path("data/tag_cooccurrence.json")
DATA_ROOTS = [Path("NAIA-Portable/user-data/data"), Path("data")]
AXIS_DIRS = (Path("wildcards/thumb"), Path("wildcards/nsfw"))
# 축이 아닌 원본 목록. 이것들을 넣으면 같은 태그가 두 번 들어온다.
# 축 판정은 emit 이 내는 인덱스가 SSOT 다. 전에는 여기 목록을 적어 뒀는데
# 없어진 `nsfw_heavy` 를 계속 참조하고 새로 생긴 축은 몰랐다.
from tools.thumb_axis_index import is_axis  # noqa: E402
# 어떤 태그와도 함께 나오는 것들. 동반 후보로 내놓을 값이 없다.
def _relation_neighbors(raw: dict) -> dict[str, set[str]]:
    """태그 -> 이미 UI 의 다른 줄에 표시되는 관계 태그들.

    UI 는 관계를 '함께 딸려오는 것 / 비슷한 것 / 더 구체적인 것' 세 줄로 나눈다.
    동반 추천은 **네 번째 줄**이므로 앞 세 줄과 겹치면 같은 태그를 두 번 보여주는 것이다.
    실측: 겹침을 안 걷으면 `sweater` 의 동반에 `turtleneck sweater` · `ribbed sweater` ·
    `off-shoulder sweater` 가 올라와 8칸의 절반을 변형이 먹는다.
    """
    out: dict[str, set[str]] = {}
    for tag, rec in raw.items():
        rel = (rec or {}).get("relations") or {}
        near: set[str] = set()
        for kind in ("parent", "children", "siblings", "word_match", "implications"):
            v = rel.get(kind)
            if isinstance(v, str):
                near.add(v)
            elif isinstance(v, (list, tuple, set)):
                near.update(x for x in v if isinstance(x, str))
        if near:
            out[tag] = {normalize_tag(x) for x in near}
    return out


def _adult_vocab() -> set[str]:
    """성인 도감 어휘. 일반 태그의 동반 추천에서 뺀다.

    실측: `silent princess`(젤다의 꽃, 401건)의 동반에 `pussy` · `no panties` ·
    `spread legs` 가 올라왔다. 표본이 적은 태그는 소수의 게시물이 lift 를 지배한다.
    성인 태그를 고른 사용자에게는 성인 후보가 맞지만, 꽃을 고른 사용자에게는 사고다.
    """
    vocab: set[str] = set()
    d = Path("wildcards/nsfw")
    if d.exists():
        for f in d.glob("nsfw_*.txt"):
            for line in f.read_text(encoding="utf-8").splitlines():
                t = line.strip()
                if t:
                    vocab.add(normalize_tag(t))
    return vocab


# 동반 후보가 될 수 없는 분류. 태그 DB 의 group/subgroup 이 판정한다 —
# 이름으로 적으면 새 태그가 계속 샌다.
#   실측 오답: `medallion -> oda uri`(캐릭터 심볼), `anemone -> aged down · dual persona ·
#   time paradox`(메타태그), `twintails -> 6+girls · 4girls`(인원수), `sweater -> meme attire`.
# `Composition_Meta` 를 통째로 막으면 안 된다 — `male focus` 는 `muscular` 의 정답이고
# subgroup 이 `focus` 다. 그래서 **subgroup 단위로** 막는다.
#
# **죽은 항목을 두지 마라.** 처음에 `year` 와 `signature` 를 적었는데 실제 subgroup 이름은
# `year_tags` 이고 `signature` 는 subgroup 이 아니라 태그다(`text` 소속) — 둘 다 한 번도
# 매칭되지 않았다. 그 사이 `copyright name` · `english text` · `speech bubble` 이 후보로
# 새어 나왔다(실측: `cassette tape -> copyright name`). 목록을 적을 때는 실제 값을 세어라.
BAD_GROUPS = {"artist", "작가", "character", "copyright", "Danger", "메타 > 정보"}
BAD_SUBGROUPS = {
    "meta", "metatags", "count", "symbols", "memes",
    "year_tags",    # `2021` · `retro artstyle` — 그림 요소가 아니라 시기 라벨
    "text",         # artist name · signature · watermark · speech bubble (224개)
    "subjective",   # bad anatomy · manly · hot · yandere — 품평이지 선택 요소가 아니다
    "pokemon",      # `pokemon (creature)`(8.5만) 가 무관한 태그에 계속 붙었다(실측)
}
# 일부러 남긴 것:
#   `effects`(338: blurry · wet · sparkle) — 정당한 연출 태그다
#   `scan`(54: sketch · watercolor (medium) · 3d) — 화풍/매체. 벤치 베이스도 쓴다
#   `focus` / `focus_tags` — `male focus` 는 `muscular` 의 골드 정답이다
#   `colors` · `image_composition` · `lighting` — 그림 요소다


STOP = {
    "1girl", "1boy", "2girls", "2boys", "solo", "multiple girls", "multiple boys",
    "looking at viewer", "simple background", "white background", "highres",
    "absurdres", "commentary", "commentary request", "translated", "artist name",
    "signature", "watermark", "bad id", "bad pixiv id", "general", "sensitive",
    "questionable", "explicit", "safe", "nsfw",
    # ── 아래는 **추측이 아니라 실측이다.** Codex 전수 검수(상위 2,100태그 / 후보 8,379개)
    # 에서 오분류로 잡힌 630건 중, 이 여섯 개가 반복만으로 213건을 차지했다:
    #   solo focus 59 · nude 49 · monochrome 40 · greyscale · spread legs 12 · completely nude 3
    # 전부 20만~27만회짜리 고빈도이고, 분류가 서로 달라(focus / colors / clothing_state /
    # posture) subgroup 으로는 한 번에 못 막는다. `male focus`(32만, 같은 focus subgroup)는
    # `muscular` 의 골드 정답이므로 subgroup 을 통째로 막을 수도 없다. 그래서 태그로 적는다.
    # 새로 적을 때는 반드시 **몇 건인지 세고** 그 숫자를 여기 남겨라.
    "solo focus", "monochrome", "greyscale",
    "nude", "completely nude", "spread legs",
}


class PoolSource:
    """게시물 원본(`data/tag_pool_*.parquet`)을 코퍼스와 같은 인터페이스로 내놓는다.

    ## 왜 출처를 바꿨나

    이벤트 코퍼스(`data/quick_search/`)는 **태그 정체성이 어긋나 있다.** 원본 게시물과
    대조하니 간선 35,515개 중 3,499개(9.9%)가 게시물에서 거의/전혀 동반되지 않는다:

        hooded coat + cow ears   코퍼스 3,333회(44.6%)  게시물 0회
        blue fire   + ramen      코퍼스 1,183회(25.0%)  게시물 2회(0.1%)

    지문도 뚜렷하다 — `racing suit` 의 후보 넷이 127/127/126/126 으로 거의 같은 수다.
    무관한 태그가 한 '이벤트' 에 통째로 묶여 있다는 뜻이다. 빈도와 무관하게 퍼져 있어
    (층화 표본 253개, 빈도대별 미지지율 0~7.5%) 문턱으로는 못 가른다.

    그래서 출처를 게시물 원본 하나로 통일한다. 부수 효과로 어휘가 16,625 -> 58,326 이 되어,
    코퍼스 어휘 밖이라 후보를 못 얻던 축 태그 215개(`collared shirt` 27만 등)도 살아난다.

    대가는 두 가지다. 표본이 449만 -> 140만 으로 줄고(하한을 낮춰야 한다), 샤드가 시간 순
    슬라이스라 그 시기 유행이 부풀려진다(`--max-era-ratio` 가 막는다).
    """

    def __init__(self, path: Path, batch: int = 100_000):
        import pyarrow.parquet as pq
        self._pq = pq
        self.path = path
        self.batch = batch
        self.tag_to_id: dict[str, int] = {}
        self.id_to_tag: dict[int, str] = {}
        self.num_tags = 0

    def _rows(self):
        pf = self._pq.ParquetFile(self.path)
        for b in pf.iter_batches(batch_size=self.batch, columns=["general"]):
            yield b.column(0).to_pylist()

    def build_vocab(self) -> None:
        """어휘를 먼저 확정한다. 배치마다 새 태그가 나오면 열 번호가 흔들린다."""
        seen: dict[str, int] = {}
        n = 0
        for chunk in self._rows():
            for g in chunk:
                if not g:
                    continue
                n += 1
                for x in str(g).split(","):
                    x = x.strip().lower()
                    if x and x not in seen:
                        seen[x] = len(seen)
        self.tag_to_id = seen
        self.id_to_tag = {v: k for k, v in seen.items()}
        self.num_tags = len(seen)
        print(f"풀 어휘 {self.num_tags:,}개 / 게시물 {n:,}건")

    def batches(self):
        """(indptr, indices, n_events) — 코퍼스의 `csr_arrays` 와 같은 모양."""
        t2i = self.tag_to_id
        for chunk in self._rows():
            indptr = [0]
            indices: list[int] = []
            for g in chunk:
                if g:
                    for x in str(g).split(","):
                        i = t2i.get(x.strip().lower())
                        if i is not None:
                            indices.append(i)
                indptr.append(len(indices))
            yield (np.asarray(indptr, dtype=np.int64),
                   np.asarray(indices, dtype=np.int64), len(indptr) - 1)


def same_family(raw: dict, a: str, b: str) -> bool:
    """**중심 명사(마지막 낱말)가 같으면 변형이다** — 동반이 아니라 '더 구체적인 것'.

    Codex 전수 검수의 `variant`/`parent`/`same` 87건 중 29건이 이 조건으로 잡히고,
    그 29건은 전부 실제 변형이었다(실측):

        simple background -> grey background · brown background
        gradient background -> grey/blue/pink background
        ribbed sweater <-> turtleneck sweater · maid apron <-> frilled apron
        hakama skirt <-> hakama short skirt · bed <-> on bed · doll <-> character doll
        footwear bow -> bow · front-tie top <-> front-tie bikini top

    **처음에 'subgroup 도 같아야 한다' 를 걸었는데 그러면 하나도 안 잡힌다.**
    `grey background` · `blue background` 같은 색 배경은 태그 DB 에 subgroup 이 아예 없다
    (87건 중 subgroup 이 같은 것은 30건, 둘 다 같은 것은 12건뿐이었다). 그래서 조건을
    중심 명사 하나로 좁혔다 — 숫자를 세지 않고 규칙을 적으면 이렇게 헛돈다.

    골드셋 16태그의 '나와야' 목록에는 대상과 중심 명사가 같은 후보가 없다(손실 0):
    `beach -> ocean/sand/sky`, `sweater -> long sleeves/skirt`, `cat ears -> tail/bell` 등.

    `raw` 는 지금 쓰지 않지만 인자로 남긴다 — 분류를 다시 조건에 넣을 여지를 두고,
    호출부 두 곳(빌더·채움)의 서명을 흔들지 않기 위해서다.
    """
    if a == b:
        return False
    wa, wb = a.split(), b.split()
    if not wa or not wb:
        return False
    if len(wa) == 1 and len(wb) == 1:
        return False          # 낱말 하나짜리 둘이면 변형 관계가 아니다
    return wa[-1] == wb[-1]


def axis_tags() -> list[str]:
    """UI 가 실제로 보여주는 태그. 축 파일이 SSOT 다 — 여기 목록을 손으로 적지 않는다."""
    out: set[str] = set()
    for d in AXIS_DIRS:
        for p in d.glob("*.txt"):
            if not is_axis(p.stem):
                continue
            out |= {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="함께 쓰이는 태그 사전 생성")
    # **4개다.** 8칸을 채우면 정밀도가 .574 로 떨어진다(골드셋 실측):
    #   top-3 .778 / top-4 .746 / top-5 .712 / top-6 .655 / top-8 .574
    # 뒤쪽 칸은 순위가 낮아서 채운 것이고, 그게 곧 오답이다. 사용자 결정은
    # "유의미한 것만 남기고 나머지는 출력하지 않는다" 이므로 칸을 줄인다.
    ap.add_argument("--top", type=int, default=4, help="태그당 후보 수 (기본 4)")
    ap.add_argument("--min-pair", type=int, default=30,
                    help="동반 이벤트 하한. 이하면 표본 부족으로 버린다 (기본 30)")
    # **순위는 confidence 로 낸다.** "A 를 쓸 때 B 가 함께 나오는 비율" 이 곧 동반이다.
    # lift 로 순위를 내면 고빈도 태그가 통째로 빈다 — `twintails`(48만)의 동반 후보는
    # 죄다 고빈도라 lift 가 1 근처이고, 1.5 하한에 전부 걸렸다(실측: 상위 400개 중 24%만 채워졌다).
    # lift 는 순위가 아니라 **게이트**로만 쓴다: 1 미만이면 배경보다 덜 붙는 쌍이다.
    ap.add_argument("--min-lift", type=float, default=1.15,
                    help="배경 대비 이 배수 미만이면 버린다. 순위가 아니라 게이트다 (기본 1.15)")
    # **절대 하한만으로는 부족하다.** freq 50만짜리 태그에 30건 동반은 사실상 우연인데
    # 파트너가 희귀하면 lift 가 폭발한다(실측: `+_+` -> `sacabambaspis`).
    # 대상 빈도에 비례한 하한과 파트너 빈도 하한을 함께 건다.
    ap.add_argument("--support-ratio", type=float, default=0.01,
                    help="동반수가 대상 등장수의 이 비율 이상이어야 한다 (기본 0.02)")
    ap.add_argument("--min-cand-freq", type=int, default=800,
                    help="후보 자체가 이만큼은 등장해야 한다 — 희귀 태그가 lift 를 부풀린다")
    # ── 정밀도 우선 정책 (2026-07-30 사용자 결정) ─────────────────────────────
    # "유의미한 결과가 나오는 케이스만 남기고 나머지는 그냥 출력하지 않는다."
    # 골드셋 실측으로 어떤 점수식도 P@8 .633 을 못 넘겼고 저빈도는 .554 였다.
    # 8칸을 억지로 채우면 3개는 배경 태그다. 그래서 recall 을 버리고 문턱을 올린다.
    ap.add_argument("--strict-lift", type=float, default=2.0,
                    help="후보 개별 lift 하한. 이걸 못 넘는 후보는 아예 내보내지 않는다. "
                         "살아남는 후보가 0개면 그 태그는 사전에서 빠진다(빈 목록)")
    ap.add_argument("--implication-conf", type=float, default=0.95,
                    help="P(후보|대상) 또는 P(대상|후보) 가 이 이상이면 함의로 보고 제외. "
                         "관계 사전에 없는 부모/자식 쌍을 통계로 잡는다")
    ap.add_argument("--max-cand-prob", type=float, default=0.30,
                    help="후보의 전역 등장 확률 P(B) 상한. `breasts`(.452) 처럼 배경이 "
                         "너무 흔한 후보를 뺀다. 골드 손실 0 으로 실측된 값이 .30")
    ap.add_argument("--eval", action="store_true",
                    help="data/tag_companion_goldset.json 으로 채점만 한다(쓰지 않음). "
                         "--strict-lift 를 여러 값으로 sweep 해 precision 과 커버리지를 낸다")
    ap.add_argument("--keep-relations", action="store_true",
                    help="UI 의 다른 관계 줄과 겹치는 후보를 남긴다(기본은 제외)")
    ap.add_argument("--keep-adult", action="store_true",
                    help="일반 태그의 동반에 성인 도감 태그를 남긴다(기본은 제외)")
    # 사람(또는 서브에이전트)이 손으로 고를 수 있게 **탈락한 차순위까지** 내보낸다.
    # 규칙으로 못 묶이는 `unrelated` 오분류는 대안을 보여줘야 판단할 수 있는데,
    # 사전에는 상위 4개만 있어서 "그럼 뭘 넣지" 에 답할 재료가 없었다.
    # 출처. 기본이 풀이다 — 코퍼스는 태그 정체성이 어긋나 있다(PoolSource 독스트링).
    ap.add_argument("--source", choices=("pool", "corpus"), default="pool")
    ap.add_argument("--pool", default="data/tag_pool_120_139.parquet")
    # 풀은 코퍼스의 1/3 이라 절대 하한을 그대로 쓰면 통과하던 쌍이 떨어진다.
    ap.add_argument("--max-era-ratio", type=float, default=3.0,
                    help="풀 등장률 / 전체기간 등장률 상한. 샤드가 시간 순 슬라이스라 "
                         "그 시기 유행 태그가 무엇에든 lift 를 띄운다(풀 소스에서만 적용)")
    ap.add_argument("--danbooru-total", type=int, default=10_000_000)
    ap.add_argument("--dump-tags", default="",
                    help="한 줄 한 태그 파일. 그 태그들의 상위 후보를 점수와 함께 덤프한다")
    ap.add_argument("--dump-out", default="data/_companion_review/candidates.json")
    ap.add_argument("--dump-top", type=int, default=20)
    # ── 조언 카드('함께 쓰는 것')용 두 번째 산출물 ────────────────────────────
    # 사전 카드는 한 줄에 4개다. 조언 카드는 후보를 **축별로 묶어** 보여주므로 같은
    # 4개로는 그룹이 하나밖에 안 나온다. 같은 통계·같은 게이트에서 더 깊이 뽑되,
    # 화면에 몇 개를 띄울지는 프론트가 정한다(현재 3그룹 x 6개).
    # 정책을 둘로 갈라 두지 않으려고 별도 빌더를 만들지 않았다 — 게이트가 갈라지면
    # 두 카드가 서로 다른 말을 하게 된다.
    # 사전은 사람 손이 얹힌 이력이 있다(Codex 전수 검수 -> STOP/BAD_* 반영,
    # filter_character_bias 후처리). 조언용만 새로 뽑고 싶을 때 덮어쓰지 않도록
    # 출력 경로를 열어 둔다.
    ap.add_argument("--out", default=str(OUT), help="동반 사전 출력 경로")
    ap.add_argument("--harmony-out", default="data/interactive_tag_harmony.json")
    ap.add_argument("--harmony-top", type=int, default=16,
                    help="조언 카드용 태그당 후보 수. 축별로 묶이므로 사전(4)보다 깊다")
    ap.add_argument("--no-harmony", action="store_true", help="조언 카드용 산출물을 만들지 않는다")
    ap.add_argument("--axis-labels", default="data/interactive_axis_labels.json")
    ap.add_argument("--axis-tags", default="data/interactive_axis_tags.json")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 통계만")
    args = ap.parse_args()
    # 사전 목록은 항상 상위 `--top` 개다. 아래 루프는 조언용/덤프용으로 더 깊이
    # 도는데, 그때 `picked` 를 그대로 쓰면 사전 목록까지 같이 길어진다.
    #
    # 조언 카드는 사전 카드와 달리 **축 어휘만** 받는다. 이유가 둘이다:
    #   1. 카드가 후보를 축(그룹)별로 묶는다 — 축이 없으면 묶을 데가 없어 전부
    #      '기타' 한 덩어리가 된다. 실측 879종이 거기 쌓였고 `2024` · `+ +` 같은
    #      메타 잡음의 온상이었다.
    #   2. 성인 어휘 인접 태그가 SFW 씨앗에 붙는 경로였다(실측 43건:
    #      `bathtub -> mixed-sex bathing` · `biting -> nipple stimulation`).
    #      성인 어휘 목록(wildcards/nsfw)에 없는 것들이라 기존 필터가 못 걸렀다.
    # 대가는 간선 19.2% 손실인데 빈 목록이 되는 씨앗은 61개(0.6%)뿐이고 그 대부분이
    # 후보가 전부 성인 어휘였던 성인 씨앗이다(실측).
    axis_vocab: set[str] = set()
    if not args.no_harmony:
        _ax_path = Path(args.axis_tags)
        if _ax_path.exists():
            axis_vocab = {t for v in json.loads(
                _ax_path.read_text(encoding="utf-8"))["axes"].values() for t in v}
        else:
            print(f"!! 축 소속표가 없습니다: {_ax_path} — 조언용 산출물을 만들지 않습니다")
            args.no_harmony = True
    # 축 밖 후보를 건너뛰며 더 깊이 파야 조언 목록이 채워진다.
    #
    # **사전은 그 깊이에 딸려가면 안 된다.** 깊이만 늘렸더니 9개 태그의 사전 목록이
    # 길어졌는데(실측), 늘어난 자리는 전부 꼬리다 — `ahoge -> pink halo`(우마무스메
    # 캐릭터 장식) · `ponytail -> one-piece swimsuit`. 골드셋이 말하는 그대로다
    # (top-4 .746 / top-8 .574). 그래서 사전이 원래 훑던 깊이를 상수로 못 박고
    # 조언용 수집만 더 내려간다.
    dict_cap = max(30, args.dump_top)
    scan_cap = dict_cap if args.no_harmony else max(dict_cap, args.harmony_top * 3)

    raw = load_kr_tag_records().raw
    if args.source == "pool":
        pool_path = Path(args.pool)
        if not pool_path.exists():
            print(f"!! 풀이 없습니다: {pool_path} — tools/merge_tag_shards.py 120 139")
            return 2
        idx = PoolSource(pool_path)
        idx.build_vocab()
        # 풀은 코퍼스의 1/3 이라 절대 하한을 그대로 쓰면 통과하던 쌍이 떨어진다.
        # 사용자가 명시하지 않았으면 풀 크기에 맞춘 값으로 내린다(채움 도구와 같은 값).
        if "--min-pair" not in sys.argv:
            args.min_pair = 12
        if "--min-cand-freq" not in sys.argv:
            args.min_cand_freq = 400
        print(f"  풀 소스 — min-pair {args.min_pair} / min-cand-freq {args.min_cand_freq}")
    else:
        idx = EventCorpusIndex([p for p in DATA_ROOTS if p.exists()])
        idx._ensure_metadata()
        if not idx.tag_to_id:
            print("!! 이벤트 코퍼스를 읽지 못했습니다 (data/quick_search 확인)")
            return 2

    # 풀은 게시물 태그 원문(소문자)이 곧 키다. 코퍼스는 `normalize_tag` 를 거친 키라
    # 소스마다 조회 방식이 다르다 — 한쪽 규칙을 다른 쪽에 쓰면 대상이 통째로 빈다.
    _key = (lambda t: t.strip().lower()) if args.source == "pool" else normalize_tag
    targets = [t for t in axis_tags() if _key(t) in idx.tag_to_id]
    print(f"대상 {len(targets)}개 (축 태그 중 코퍼스에 있는 것)")
    # **후보는 코퍼스 전체다.** 처음엔 축 태그로 제한했는데(그림 없는 칩을 피하려고)
    # `twintails` · `pantyhose` · `cat ears` 같은 고빈도 태그가 통째로 비었다 —
    # 그것들의 자연스러운 동반 태그(`long hair` · `hair ribbon`)가 축이 아니라
    # 슬라이더/팔레트 소관이라 열에 없었기 때문이다(실측: 상위 400개 중 63%만 채워졌다).
    # `recThumbsHtml` 이 그림 없는 태그를 이름만으로 그릴 수 있으므로 제한할 이유가 없다.
    row_of = {idx.tag_to_id[_key(t)]: i for i, t in enumerate(targets)}
    name = list(targets)
    nrow = len(name)
    ncol = idx.num_tags
    rlut = np.full(ncol, -1, dtype=np.int32)
    for tid, i in row_of.items():
        rlut[tid] = i
    id_to_tag = idx.id_to_tag

    pair = sparse.csr_matrix((nrow, ncol), dtype=np.int32)
    freq = np.zeros(nrow, dtype=np.int64)      # 대상(행) 등장 수
    cfreq = np.zeros(ncol, dtype=np.int64)     # 후보(열) 등장 수
    total = 0
    def _source_batches():
        """소스가 달라도 (이름, indptr, indices, n_events) 하나로 내놓는다."""
        if args.source == "pool":
            for bi, (ip, ix, ne) in enumerate(idx.batches(), 1):
                yield f"batch{bi}", ip, ix, ne
            return
        for part in sorted(p.stem for p in idx.root.glob("*.tgp")) if idx.root else []:
            try:
                store = idx.store(part)
            except Exception as exc:
                print(f"  !! {part}: {exc}")
                continue
            ip, ix, ne = idx.csr_arrays(store)
            yield part, ip, ix, ne

    for pi, (part, indptr, indices, n_events) in enumerate(_source_batches(), 1):
        total += n_events
        rows = np.repeat(np.arange(n_events, dtype=np.int64), np.diff(indptr))
        # 전체 열 행렬 F(이벤트 x 전체 태그)와 대상만 남긴 T(이벤트 x 대상).
        # `T.T @ F` 가 (대상 x 전체) 동반 횟수다.
        full = sparse.csr_matrix(
            (np.ones(len(indices), dtype=np.int8), (rows, indices.astype(np.int64))),
            shape=(n_events, ncol))
        mapped = rlut[indices]
        keep = mapped >= 0
        # int8 @ int8 은 SciPy 희소행렬 곱에서도 int8 로 누산되어 127을 넘으면
        # 오버플로한다. 대상 행렬만 int32 로 올리면 full 의 메모리는 유지하면서
        # 동반 횟수는 최대 전체 이벤트 수까지 정확하게 센다.
        tgt = sparse.csr_matrix(
            (np.ones(int(keep.sum()), dtype=np.int32), (rows[keep], mapped[keep])),
            shape=(n_events, nrow))
        freq += np.asarray(tgt.sum(axis=0)).ravel().astype(np.int64)
        cfreq += np.asarray(full.sum(axis=0)).ravel().astype(np.int64)
        pair = pair + (tgt.T @ full).astype(np.int32)
        print(f"  [{pi}] {part}  nnz={pair.nnz:,}", flush=True)

    print(f"\n전체 이벤트 {total:,} / 동반 nnz {pair.nnz:,}")
    pair = pair.tolil()
    for tid, i in row_of.items():          # 자기 자신은 동반이 아니다
        pair[i, tid] = 0
    pair = pair.tocsr()
    pair.eliminate_zeros()

    def _bad_class(t: str) -> bool:
        m = raw.get(t) or {}
        return (str(m.get("group") or "") in BAD_GROUPS
                or str(m.get("subgroup") or "").lower() in BAD_SUBGROUPS)

    neighbors = {} if args.keep_relations else _relation_neighbors(raw)
    adult = set() if args.keep_adult else _adult_vocab()
    print(f"관계 사전 {len(neighbors)}태그 / 성인 어휘 {len(adult)}개 (동반에서 제외)")
    _era_on = args.source == "pool"
    result: dict[str, list[str]] = {}
    harmony_rec: dict[str, list[str]] = {}
    dropped = {"support": 0, "lift": 0, "exclusive": 0, "negation": 0, "danger": 0,
               "stop": 0, "too_common": 0, "weak_lift": 0,
               "relation": 0, "adult": 0, "bad_class": 0,
               "same_family": 0, "implication": 0, "era": 0}
    gold = None
    if args.eval:
        gold_path = Path("data/tag_companion_goldset.json")
        gold = {c["tag"]: c for c in json.loads(
            gold_path.read_text(encoding="utf-8"))["cases"]}
        print(f"골드셋 {len(gold)}태그 로드: {gold_path.name}")
    ranked_gold: dict[str, list[tuple[str, float, float]]] = {}   # tag -> [(b, lift, score)]
    dump_want: set[str] = set()
    if args.dump_tags:
        dump_want = {l.strip().lower() for l in
                     Path(args.dump_tags).read_text(encoding="utf-8").splitlines() if l.strip()}
        print(f"후보 덤프 대상 {len(dump_want)}개 -> {args.dump_out}")
    dumped: dict[str, list[dict]] = {}
    for i, a in enumerate(name):
        if freq[i] <= 0:
            continue
        lo, hi = pair.indptr[i], pair.indptr[i + 1]
        if lo == hi:
            continue
        cand = pair.indices[lo:hi]
        cnt = pair.data[lo:hi].astype(np.float64)
        floor = max(args.min_pair, args.support_ratio * float(freq[i]))
        ok = (cnt >= floor) & (cfreq[cand] >= args.min_cand_freq)
        dropped["support"] += int((~ok).sum())
        cand, cnt = cand[ok], cnt[ok]
        if not len(cand):
            continue
        # lift = 동반확률 / 무관할 때의 기대확률.
        expected = (freq[i] / total) * (cfreq[cand] / total)
        lift = np.divide(cnt / total, expected, out=np.zeros_like(cnt), where=expected > 0)
        ok = lift >= args.min_lift
        dropped["lift"] += int((~ok).sum())
        cand, cnt, lift = cand[ok], cnt[ok], lift[ok]
        # 후보가 너무 흔하면 뺀다. `breasts` 는 전체 이벤트의 45% 에 나와서 무엇을 넣어도
        # confidence 1 위가 된다 — 그건 동반 정보가 아니라 코퍼스 배경이다.
        ok = (cfreq[cand] / float(total)) <= args.max_cand_prob
        dropped["too_common"] += int((~ok).sum())
        cand, cnt, lift = cand[ok], cnt[ok], lift[ok]
        if not len(cand):
            continue
        # 순위 = confidence x min(log2 lift, 3).
        #   confidence 만 쓰면 고빈도가 독식하고(P@8 .289), lift 만 쓰면 표본 적은 변형이
        #   독식한다(.281). 혼합이 .586, 관계 중복제거까지 .625, P(B) 상한까지 .633 이었다.
        #   상한 3 은 lift 8 에서 포화 — 그 위는 희귀도 차이일 뿐 유용성 차이가 아니다.
        conf = cnt / float(freq[i])
        # **함의는 동반이 아니다.** 후보가 대상의 상위/하위 개념이면 UI 의 다른 줄이 담당한다.
        # 관계 사전에 그 쌍이 없어도 **동반 통계 자체로 판정할 수 있다** — 조건부 확률의 비대칭이다:
        #   P(underwear | panties) = 1.000  <- panties 를 쓰면 반드시 underwear 다 (부모)
        #   P(hair ornament | hairclip) = 1.000  <- 역방향. hairclip 은 hair ornament 의 하나 (자식)
        # 실측(게시물 풀 140만, Codex 가 variant/parent/same 로 잡은 87쌍 대상):
        #   0.95 하한 -> 23쌍 적출, 골드 '나와야' 손실 0, 다른 유형 오탐 0
        #   0.90 으로 낮추면 `silent princess -> pointy ears`(0.923) 가 골드에서 잘린다
        # 골드 정답은 한참 아래다: beach->ocean 0.528 · cat ears->tail 0.555 · sweater->long sleeves 0.469
        rev = cnt / np.maximum(cfreq[cand].astype(np.float64), 1.0)
        ok = (conf < args.implication_conf) & (rev < args.implication_conf)
        dropped["implication"] += int((~ok).sum())
        cand, cnt, lift, conf = cand[ok], cnt[ok], lift[ok], conf[ok]
        if not len(cand):
            continue
        score = conf * np.minimum(np.log2(np.maximum(lift, 1.0)), 3.0)
        order = np.argsort(-score)
        picked: list[str] = []
        picked_axis: list[str] = []      # 조언 카드용 — 축 어휘만
        dict_closed = False              # 사전 몫이 원래 끝났을 자리를 지난 뒤
        ranked: list[tuple[str, float, float]] = []
        for j in order:
            b = id_to_tag.get(int(cand[j]))
            if not b:
                continue
            if b in STOP:
                dropped["stop"] += 1
                continue
            if danger_age_hits(b):
                dropped["danger"] += 1
                continue
            if _is_negation_pair(a, b):
                dropped["negation"] += 1
                continue
            if is_exclusive_pair(a, b):
                dropped["exclusive"] += 1
                continue
            # 앞 세 줄과 겹치면 동반 줄에서 뺀다(같은 것을 두 번 보여주지 않는다).
            if b in neighbors.get(a, ()) or a in neighbors.get(b, ()):
                dropped["relation"] += 1
                continue
            # 일반 태그에 성인 후보를 붙이지 않는다. 성인 태그 자신은 예외.
            if b in adult and a not in adult:
                dropped["adult"] += 1
                continue
            if _bad_class(b):
                dropped["bad_class"] += 1
                continue
            # 시대 편향 — 샤드가 시간 순 슬라이스라 그 시기 유행이 무엇에든 lift 를 띄운다.
            # 태그 DB 의 freq 는 전체 기간이므로 그것과 대조한다(풀 소스에서만 의미가 있다).
            if _era_on:
                _all = int((raw.get(b) or {}).get("freq", 0) or 0)
                if _all > 0 and (cfreq[cand[j]] / total) / (_all / args.danbooru_total) > args.max_era_ratio:
                    dropped["era"] += 1
                    continue
            if same_family(raw, a, b):
                dropped["same_family"] += 1
                continue
            ranked.append((b, float(lift[j]), float(score[j])))
            # **정밀도 우선.** lift 문턱을 못 넘는 후보는 순위가 높아도 내보내지 않는다.
            if lift[j] < args.strict_lift:
                dropped["weak_lift"] += 1
                continue
            # **사전의 경계를 글자 그대로 재현한다.** 약한 후보는 위에서 `continue`
            # 하므로 상한 검사를 아예 건너뛴다 — 즉 `ranked` 가 30 을 넘긴 뒤에도
            # 강한 후보가 처음 나오면 그건 담긴다. 이걸 `len(ranked) <= 30` 으로
            # 바꿔 적었더니 커밋본에 있던 16개 태그의 목록이 짧아졌다(실측).
            if not dict_closed:
                picked.append(b)
            if b in axis_vocab and len(picked_axis) < args.harmony_top:
                picked_axis.append(b)
            keep_going = (gold is not None and a in gold) or a in dump_want
            if not dict_closed and ((len(picked) >= args.top and not keep_going)
                                    or len(ranked) >= dict_cap):
                dict_closed = True      # 여기가 원래 `break` 가 걸리던 자리다
            if dict_closed and (args.no_harmony
                                or len(picked_axis) >= args.harmony_top):
                break
            if len(ranked) >= scan_cap:
                break
        if gold is not None and a in gold:
            ranked_gold[a] = ranked
        if a in dump_want:
            dumped[a] = [{"tag": b, "lift": round(lf, 2), "score": round(sc, 4)}
                         for b, lf, sc in ranked[:args.dump_top]]
        if picked:
            # **자르는 것을 잊지 마라.** 루프는 조언용/덤프용으로 더 깊이 도는데
            # 사전 목록은 상위 `--top` 개라는 계약이다(골드셋 실측: top-4 .746 / top-8 .574).
            result[a] = picked[:args.top]
        if picked_axis:
            harmony_rec[a] = picked_axis

    print(f"동반 사전 {len(result)}개 태그 / 간선 {sum(len(v) for v in result.values()):,}")
    n_targets = int((freq > 0).sum())
    print(f"커버리지 {len(result)}/{n_targets} 대상 태그 "
          f"({len(result) / max(n_targets, 1) * 100:.1f}%) — 나머지는 빈 목록이다")
    if gold is not None:
        print()
        print("=== 골드셋 채점 (문턱 sweep) ===")
        print("정밀도 = 내보낸 후보 중 골드 '나와야' 에 있는 비율. 분모는 실제로 내보낸 수다")
        print("(억지로 8개 채우지 않으므로 P@8 이 아니라 P@내보낸수 로 센다).")
        header = f"{'strict-lift':>11} {'내보낸 태그':>10} {'후보 합':>7} {'정밀도':>7} {'오답':>5} {'beach':>6} {'blush':>6}"
        print(header)
        for th in (1.15, 1.5, 2.0, 2.5, 3.0, 4.0):
            emitted, good_n, bad_n, tot_n, per = 0, 0, 0, 0, {}
            for t, rk in ranked_gold.items():
                keep = [b for b, lf, sc in rk if lf >= th][: args.top]
                per[t] = keep
                if keep:
                    emitted += 1
                g = set(gold[t]["good"]); bad = set(gold[t].get("bad") or [])
                tot_n += len(keep)
                good_n += sum(1 for b in keep if b in g)
                bad_n += sum(1 for b in keep if b in bad)
            prec = good_n / tot_n if tot_n else 0.0
            bs = per.get("beach") or []
            bl = per.get("blush") or []
            bg = set(gold["beach"]["good"]) if "beach" in gold else set()
            print(f"{th:>11.2f} {emitted:>10} {tot_n:>7} {prec:>7.3f} {bad_n:>5} "
                  f"{sum(1 for b in bs if b in bg)}/{len(bs):<4} {len(bl):>6}")
        print()
        print("=== 몇 개까지 보여줄까 (strict-lift 고정, top-k sweep) ===")
        print("골드 '나와야' 목록이 4~8개라 8칸을 채우면 분모만 커진다.")
        print(f"{'top-k':>6} {'내보낸 태그':>10} {'후보 합':>7} {'정밀도':>7} {'오답':>5}")
        for k in (3, 4, 5, 6, 8):
            emitted, good_n, bad_n, tot_n = 0, 0, 0, 0
            for t, rk in ranked_gold.items():
                keep = [b for b, lf, sc in rk if lf >= args.strict_lift][:k]
                if keep:
                    emitted += 1
                g = set(gold[t]["good"]); bad = set(gold[t].get("bad") or [])
                tot_n += len(keep)
                good_n += sum(1 for b in keep if b in g)
                bad_n += sum(1 for b in keep if b in bad)
            print(f"{k:>6} {emitted:>10} {tot_n:>7} {good_n / tot_n if tot_n else 0:>7.3f} {bad_n:>5}")
        print()
        print("선택한 문턱에서의 실제 목록:")
        for t in sorted(ranked_gold):
            keep = [b for b, lf, sc in ranked_gold[t] if lf >= args.strict_lift][: args.top]
            g = set(gold[t]["good"])
            mark = "".join("O" if b in g else "." for b in keep)
            print(f"  {t:<18}{mark:<10} {', '.join(keep) or '(빈 목록)'}")
        return 0
    print("버린 후보:", dropped)
    # 알파벳 앞머리(기호 태그)만 보면 품질을 오판한다 — 실제로 쓰는 태그를 뽑아 본다.
    F = lambda t: int((raw.get(t) or {}).get("freq", 0) or 0)   # noqa: E731
    sample = ["sweater", "pantyhose", "muscular", "open vest", "thumb ring",
              "twintails", "school uniform", "cat ears", "sitting", "beach"]
    print()
    print("샘플:")
    for a in sample:
        v = result.get(a)
        print(f"  {a:<18}({F(a):>7}) -> " + (", ".join(v) if v else "(없음)"))
    print()
    print("빈도 상위 태그 커버리지:")
    top = sorted((t for t in name if F(t) >= 5000), key=lambda t: -F(t))[:400]
    have = sum(1 for t in top if t in result)
    print(f"  freq>=5000 상위 400개 중 {have}개 ({have / max(len(top), 1) * 100:.0f}%)")
    if dump_want:
        dp = Path(args.dump_out)
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_text(json.dumps(
            {"note": ["동반 후보 상위 N개(점수 포함). 사람이 고르기 위한 재료다.",
                      "사전에 실제로 나간 것은 이 중 상위 4개다 - 나머지는 탈락한 차순위.",
                      "필터(STOP/성인/분류/관계/함의/변형)는 이미 적용된 뒤의 목록이다."],
             "top": args.dump_top, "count": len(dumped), "candidates": dumped},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"후보 덤프: {dp}  ({len(dumped)}태그)")

    if args.dry_run:
        print("\n--dry-run: 쓰지 않았습니다.")
        return 0

    _src_desc = (f"게시물 풀 {total:,}건 ({args.pool})" if args.source == "pool"
                 else f"이벤트 코퍼스 {total:,}건")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "note": [
            "함께 쓰이는 태그. tools/build_tag_cooccurrence.py 가 만든다.",
            "'비슷한 것'이 아니라 '동반'이다 — UI 에서도 다른 줄로 나간다.",
            f"근거는 {_src_desc}. 순위=confidence x min(log2 lift, 3).",
            "후보 P(B)<=0.30 · 개별 lift>=2.0 · 상위 4개만. 못 넘으면 빈 목록이다.",
            "배타쌍·부정쌍·연령 어휘, UI 의 다른 관계 줄과 겹치는 후보,",
            "성인/작가/캐릭터/메타태그 분류 후보는 미리 제외했다.",
            "골드셋 16태그 실측 정밀도 0.746 (tools/build_tag_cooccurrence.py --eval).",
            "사전에 관계가 없는 태그(전체의 다수)를 위한 폴백이다.",
        ],
        "top": args.top, "minPair": args.min_pair, "minLift": args.min_lift,
        "totalEvents": total, "count": len(result),
        "companions": result,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"저장: {out_path}  ({out_path.stat().st_size / 1024:.0f} KB)")

    if not args.no_harmony:
        # 후보를 어느 그룹 머리말 아래 묶을지. 한 태그가 여러 축에 속하므로
        # **가장 작은 축**을 고른다 — 큰 컨테이너 축(pose_solo 1592)이 이기면
        # 머리말이 죄다 '자세' 하나로 뭉개진다. 동률은 이름순으로 고정한다.
        axis_of: dict[str, str] = {}
        axes = json.loads(Path(args.axis_tags).read_text(encoding="utf-8"))["axes"]
        size = {k: len(v) for k, v in axes.items()}
        for ax in sorted(axes, key=lambda k: (size[k], k)):
            for t in axes[ax]:
                axis_of.setdefault(t, ax)
        # 묶는 단위는 축이 아니라 **슬롯**이다. 축은 114개나 되는데 카드는 3그룹만
        # 띄우므로, 축으로 묶으면 한 칸짜리 그룹이 12개 생기고 정작 특징적인 후보가
        # 가린다(실측: `office lady` 가 12그룹 -> id card·high heels·glasses 가 밀려남).
        # 슬롯(의상·배경·자세·소품·장식…)으로 묶으면 3~4그룹에 4~6개씩 들어온다.
        disp: dict[str, str] = {}
        slot_of: dict[str, str] = {}
        lb_path = Path(args.axis_labels)
        if lb_path.exists():
            _lb = json.loads(lb_path.read_text(encoding="utf-8"))
            disp = _lb.get("display") or {}
            slot_of = _lb.get("slots") or {}
        else:
            print(f"  !! 축 라벨이 없습니다: {lb_path} — tools/thumb_axes_emit.py 를 돌려라")
        cands = {t for v in harmony_rec.values() for t in v}
        # 후보를 축 어휘로 이미 걸렀으므로 축 없는 후보는 있을 수 없다.
        assert not (cands - set(axis_of)), sorted(cands - set(axis_of))[:8]
        # 슬롯이 없는 축(컨테이너 축 등)은 축 표시 라벨을 그대로 그룹으로 쓴다.
        group_of = {t: (slot_of.get(axis_of[t]) or disp.get(axis_of[t]) or axis_of[t])
                    for t in cands}
        used = set(group_of.values())
        hp = Path(args.harmony_out)
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(json.dumps({
            "note": [
                "조언 카드 '함께 쓰는 것' 의 일반 어휘 층.",
                "tools/build_tag_cooccurrence.py 가 사전과 **같은 통계·같은 게이트**로 만든다.",
                "다른 점은 깊이뿐이다 — 사전은 4개, 여기는 축별로 묶으므로 더 깊다.",
                f"근거는 {_src_desc}.",
                "의상 어휘는 data/interactive_clothing_harmony.json 이 우선한다(부위별 큐레이션).",
                "후보는 축 어휘로 제한한다 — 묶을 그룹이 있어야 하고, 축 밖에는",
                "메타 잡음(2024 · + +)과 성인 어휘 인접 태그가 섞인다(실측).",
                "group=슬롯(카드가 3그룹만 띄우므로 축은 너무 잘다) · axis=원래 축.",
                "손으로 고치지 말 것.",
            ],
            "source": args.pool if args.source == "pool" else "data/quick_search",
            "totalEvents": total,
            "thresholds": {"top": args.harmony_top, "minPair": args.min_pair,
                           "minLift": args.min_lift, "strictLift": args.strict_lift,
                           "maxCandProb": args.max_cand_prob,
                           "implicationConf": args.implication_conf},
            "count": len(harmony_rec),
            "groupLabels": {g: g for g in sorted(used)},
            "group": {t: group_of[t] for t in sorted(cands)},
            "axis": {t: axis_of[t] for t in sorted(cands)},
            "recommend": harmony_rec,
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        edges = sum(len(v) for v in harmony_rec.values())
        print(f"저장: {hp}  ({hp.stat().st_size / 1024:.0f} KB) — "
              f"{len(harmony_rec)}태그 / 간선 {edges:,} / 후보 어휘 {len(cands)}종 / 그룹 {len(used)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
