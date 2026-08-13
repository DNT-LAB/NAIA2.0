# -*- coding: utf-8 -*-
"""조합 추천 질의.

## 흐름 (근거는 tools/reco_probe/SPEC.md)

    프롬프트 태그
      -> 정보량 최대 부분집합 백오프 (교집합이 floor 미만이면 줄인다)
      -> 매칭 게시물에서 후보 태그 점수화 (conf x min(log2 lift, 3))
      -> 캐릭터 집중도로 거른다 (한 캐릭터가 매칭의 절반을 넘으면 그 캐릭터의 디자인)
      -> 게시물마다 lift 순 상위 N개를 투영해 튜플을 센다
      -> 함의/동족 중복을 튜플 **안에서** 제거
      -> 크기 백오프: 크기 N 튜플이 없으면 N-1 로 내려간다

## 하지 않는 것

**콘텐츠 게이팅을 하지 않는다.** 연령/성인 어휘로 후보를 막지 않고, 배타쌍도
하드 배제가 아니라 감점이다. 사용자가 원하는 조합을 프로그램이 막을 근거가
없다는 것이 이 시스템의 제약이다(`build_tag_cooccurrence.py` 의 스택을 통째로
가져오면 그 제약이 깨진다 - SPEC 7.0).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from typing import Iterable, Sequence

import numpy as np

from .model import ComboModel


@dataclass(frozen=True)
class Policy:
    """실측으로 정한 값들. 근거는 SPEC 3~5장."""
    floor: int = 30              # 교집합이 이보다 작으면 백오프
    min_pair: int = 6            # 튜플 최소 지지도
    strict_lift: float = 2.0     # 후보 개별 lift 하한
    max_cand_prob: float = 0.30  # 후보 배경 확률 상한
    bundle: int = 3              # 튜플 크기(백오프로 줄어들 수 있다)
    min_bundle: int = 2          # 여기까지 줄인다
    top_k: int = 5               # 반환 튜플 수
    # **게이트 백오프.** 프롬프트가 너무 넓으면(`multiple boys` 는 그 그룹의 정의라
    # 100% 매칭, `hetero` 는 57%) 기본 게이트를 통과하는 후보가 하나도 없어 조용히
    # 빈 답이 된다(실측). 그때 게이트를 단계적으로 푼다 - 답이 약해지는 것이
    # 아무 말도 안 하는 것보다 낫고, `weak` 플래그로 그 사실을 알린다.
    gate_backoff: tuple[tuple[float, float], ...] = (
        (2.0, 0.30), (1.5, 0.50), (1.2, 0.80),
    )
    # **매칭 집합 표본추출은 기본적으로 끈다(0 = 무제한).**
    #
    # 넓은 질의가 느린 것은 사실이다 - `looking at viewer` 494,399건에 5.6초.
    # 그래서 40,000건으로 잘라 봤더니 527ms 로 줄었지만 **답이 망가졌다**(실측):
    #     상한 전  hetero -> sex + vaginal + missionary (10,933회)
    #     상한 후  hetero -> fisting + anal fisting / food on body + food on penis
    #     상한 후  looking at viewer -> saw + circular saw
    # 12배로 솎으면 흔한 조합이 파편화되고 희귀하지만 몰려 있는 것만 살아남는다.
    #
    # 지연을 위해 정확성을 파는 것은 잘못된 거래다. 제대로 된 답은
    # **헤드 컨텍스트 사전계산**이다 - freq>=5000 인 태그가 662개뿐이라 상위
    # 20튜플 캐시가 217KB 이고 전량 계산 결과를 그대로 담으므로 손실이 0이다
    # (SPEC 5.9). 그 빌드 단계가 붙기 전까지 넓은 질의는 느린 채로 둔다.
    # 값을 켜려면 그 대가를 위 숫자로 이해하고 켜라.
    scan_cap: int = 0
    max_char_share: float = 0.5  # 한 캐릭터가 이 비율을 넘으면 그 캐릭터 디자인
    char_min_pair: int = 8       # 이보다 적으면 집중도를 못 믿는다
    # 부분집합 전수 열거를 허용하는 프롬프트 크기 상한. 넘으면 사슬 백오프로
    # 바꾼다 - 2^24 = 16,777,215 개를 열거하면 워커가 분 단위로 묶인다.
    exact_subset_max: int = 10
    # 캐릭터 집중도 계산 대상 상한. 실측 `hetero` 질의가 후보 964개 x 39만 게시물로
    # RSS 60MB 를 더 썼다. 상위 후보만 보면 충분하다 - 아래쪽은 어차피 안 나간다.
    char_check_top: int = 300


@dataclass
class Combo:
    tags: list[str]
    support: int
    surprisal: float
    score: float


@dataclass
class Result:
    combos: list[Combo] = field(default_factory=list)
    used_prompt: list[str] = field(default_factory=list)
    matched: int = 0
    bundle_size: int = 0
    backed_off: bool = False
    weak: bool = False           # 게이트를 풀어서 얻은 답이다(프롬프트가 넓다)


class ComboQuery:
    def __init__(self, model: ComboModel, policy: Policy | None = None):
        self.m = model
        self.p = policy or Policy()
        n = max(1, model.header.posts)
        self.prob = model.freq / n
        with np.errstate(divide="ignore"):
            self.surp = -np.log2(np.maximum(self.prob, 1e-12))

    # ---- 백오프 --------------------------------------------------------
    def _intersect(self, tags: Sequence[str]) -> np.ndarray | None:
        ps = [self.m.postings(t) for t in tags]
        if any(p is None for p in ps):
            return None
        ps.sort(key=len)
        cur = ps[0]
        for nxt in ps[1:]:
            cur = np.intersect1d(cur, nxt, assume_unique=True)
        return cur

    def _backoff(self, prompt: Sequence[str]) -> tuple[np.ndarray | None, list[str]]:
        """**정보량 최대 부분집합**을 고른다.

        처음엔 '희귀한 태그부터 떨구기' 로 짰는데 그게 틀렸다 - 희귀 태그가 가장
        정보량이 크다. 실측으로 정밀도 +10.6% / surprisal +8.8% 차이가 났다.
        """
        known = [t for t in prompt if t in self.m.tag_to_id]
        if not known:
            return None, []
        info = {t: float(self.surp[self.m.tag_to_id[t]]) for t in known}
        # **부분집합 전수 열거는 지수다.** 라우트가 24태그까지 받는데 그러면
        # 16,777,215 개다 - 실측 20태그에 15.2초로 워커가 통째로 묶인다
        # (Codex 게이트). 정보량 순으로 정렬해 두고 **뒤에서부터 하나씩** 떨구는
        # 사슬만 본다: 크기 k 마다 후보 1개, 총 k 개. 전수 열거와 같은 답을 내지는
        # 않지만, 남는 정보량을 최대로 유지한다는 성질은 지킨다.
        if len(known) > self.p.exact_subset_max:
            order = sorted(known, key=lambda t: info[t])   # 정보량 적은 것부터
            use = list(known)
            first: tuple[np.ndarray, list[str]] | None = None
            for drop in [None] + order[:-1]:
                if drop is not None:
                    use.remove(drop)
                cur = self._intersect(use)
                if cur is None:
                    continue
                if first is None:
                    first = (cur, list(use))
                if len(cur) >= self.p.floor:
                    return cur, list(use)
            return (first if first is not None else (None, list(known)))
        for size in range(len(known), 0, -1):
            first_s: tuple[np.ndarray, list[str]] | None = None
            for sub in sorted(combinations(known, size),
                              key=lambda c: -sum(info[t] for t in c)):
                cur = self._intersect(sub)
                if cur is None:
                    continue
                if first_s is None:
                    first_s = (cur, list(sub))
                if len(cur) >= self.p.floor:
                    return cur, list(sub)
            if size == 1 and first_s is not None:
                return first_s
        return None, list(known)

    # ---- 후보 ----------------------------------------------------------
    def _counts(self, matched: np.ndarray) -> np.ndarray:
        cnt = np.zeros(self.m.header.vocab, dtype=np.int32)
        ip, ix = self.m.indptr, self.m.indices
        for pi in matched:
            cnt[ix[ip[pi]:ip[pi + 1]]] += 1
        return cnt

    def _char_share(self, matched: np.ndarray, cand: np.ndarray,
                    cnt: np.ndarray) -> dict[int, float]:
        """후보마다 '한 캐릭터가 차지하는 비율'. 매칭 집합 위에서 정확히 센다.

        `filter_character_bias.py` 가 별도 도구였던 이유는 그 빌더가 게시물 단위
        정보에 접근하지 못해서다. 여기서는 매칭 집합을 이미 들고 있으므로 그냥 센다.
        """
        chars = self.m.post_char
        ip, ix = self.m.indptr, self.m.indices
        want = set(int(c) for c in cand)
        per: dict[int, Counter] = {c: Counter() for c in want}
        for pi in matched:
            ch = int(chars[pi])
            if not ch:
                continue
            for t in ix[ip[pi]:ip[pi + 1]]:
                ti = int(t)
                if ti in per:
                    per[ti][ch] += 1
        out: dict[int, float] = {}
        for ti, c in per.items():
            total = int(cnt[ti])
            if total < self.p.char_min_pair or not c:
                out[ti] = 0.0
                continue
            out[ti] = c.most_common(1)[0][1] / total
        return out

    # ---- 질의 ----------------------------------------------------------
    def recommend(self, prompt: Iterable[str]) -> Result:
        pr = {str(t).strip() for t in prompt if str(t).strip()}
        # 단일 헤드 태그는 사전계산으로 답한다. 전량 계산 결과를 그대로 담으므로
        # 손실이 정의상 0이고, 실측 5.6초짜리 질의가 조회 한 번이 된다.
        if len(pr) == 1:
            hit = self.m.head_combos(next(iter(pr)))
            if hit is not None:
                combos = [Combo(tags=t, support=n,
                                surprisal=float(sum(self.surp[self.m.tag_to_id[x]]
                                                    for x in t)),
                                score=n * math.log2(1.0 + sum(
                                    self.surp[self.m.tag_to_id[x]] for x in t)))
                          for t, n in hit[:self.p.top_k]]
                if combos:
                    return Result(combos=combos, used_prompt=sorted(pr),
                                  matched=self.m.head_matched(next(iter(pr))),
                                  bundle_size=len(combos[0].tags))
        matched, used = self._backoff(sorted(pr))
        if matched is None or not len(matched):
            return Result(used_prompt=used)
        full = len(matched)
        scale = 1.0
        if self.p.scan_cap and full > self.p.scan_cap:
            # 균일 간격 표본. 게시물 순서는 시간순이므로 앞에서 자르면 시대가
            # 치우친다 - 반드시 코퍼스 전체에 걸쳐 고르게 뽑아야 한다.
            step = full / self.p.scan_cap
            idx = (np.arange(self.p.scan_cap) * step).astype(np.int64)
            matched = matched[idx]
            scale = full / len(matched)
        m = len(matched)
        cnt = self._counts(matched)

        gates = self.p.gate_backoff or ((self.p.strict_lift, self.p.max_cand_prob),)
        for gi, (min_lift, max_pb) in enumerate(gates):
            cand = []
            for c in np.nonzero(cnt)[0]:
                t = self.m.tags[int(c)]
                if t in pr or cnt[c] < self.p.min_pair:
                    continue
                pb = float(self.prob[c])
                if pb > max_pb:
                    continue
                lift = (cnt[c] / m) / pb if pb else 0.0
                if lift < min_lift:
                    continue
                cand.append(int(c))
            if not cand:
                continue

            # 집중도는 상위 후보만 본다 - 아래쪽은 어차피 튜플에 안 들어간다.
            # 전량을 보면 실측 RSS +60MB(후보 964개 x 39만 게시물).
            cand.sort(key=lambda c: -((cnt[c] / m) / max(float(self.prob[c]), 1e-12)))
            head = cand[:self.p.char_check_top]
            share = self._char_share(matched, np.asarray(head), cnt)
            cand = [c for c in head if share.get(c, 0.0) <= self.p.max_char_share]
            if not cand:
                continue

            keep = np.zeros(self.m.header.vocab, dtype=bool)
            keep[cand] = True
            lift_of = {c: (cnt[c] / m) / max(float(self.prob[c]), 1e-12)
                       for c in cand}

            # **크기 백오프.** 크기 N 튜플이 min_pair 를 못 넘으면 N-1 로 내려간다.
            # 안 하면 13% 의 질의가 빈 답이 된다(실측 106/800).
            for size in range(self.p.bundle, self.p.min_bundle - 1, -1):
                combos = self._tally(matched, keep, lift_of, size)
                if combos:
                    if scale > 1.0:
                        for c in combos:
                            c.support = int(round(c.support * scale))
                    return Result(combos=combos, used_prompt=used, matched=full,
                                  bundle_size=size, weak=gi > 0 or scale > 1.0,
                                  backed_off=size != self.p.bundle
                                  or set(used) != pr or gi > 0)
        return Result(used_prompt=used, matched=full)

    def _tally(self, matched: np.ndarray, keep: np.ndarray,
               lift_of: dict[int, float], size: int) -> list[Combo]:
        ip, ix = self.m.indptr, self.m.indices
        tally: Counter = Counter()
        for pi in matched:
            row = ix[ip[pi]:ip[pi + 1]]
            sel = [int(x) for x in row if keep[x]]
            if len(sel) < size:
                continue
            sel.sort(key=lambda c: -lift_of[c])
            picked = self._dedupe(sel, size)
            if len(picked) == size:
                tally[tuple(sorted(picked))] += 1
        # **점수 정렬을 먼저, 자르기를 나중에.**
        #
        # 처음엔 지지도 상위 top_k 개를 뽑아 놓고 그 안에서 점수 정렬을 했다.
        # 그러면 top_k 값에 따라 답이 달라진다 - 헤드 캐시는 top_k=20 으로 캐고
        # 일반 질의는 5로 캐서 **같은 태그가 다른 답을 냈다**(실측 41개 중 15개
        # 불일치, Codex 게이트). 점수 순위는 top_k 와 무관해야 한다.
        pool: list[Combo] = []
        for combo, n in tally.most_common(200):
            if n < self.p.min_pair:
                break
            names = [self.m.tags[c] for c in combo]
            surp = float(sum(self.surp[c] for c in combo))
            pool.append(Combo(tags=names, support=n, surprisal=surp,
                              score=n * math.log2(1.0 + surp)))
        pool.sort(key=lambda x: (-x.score, x.tags))
        return pool[:self.p.top_k]

    def _dedupe(self, sel: list[int], size: int) -> list[int]:
        """튜플 안의 함의/동족 중복을 뺀다.

        `sword` 가 `holding + weapon + holding weapon + holding sword` 를 내던 것을
        막는다 - 넷이 서로 함의라 한 칸을 네 번 쓴 셈이었다.

        **함의표는 빌드 시점에 구워 온다.** 질의 시점에 후보쌍을 다 계산하면
        실측 10~20배(19ms -> 1,440ms)가 된다. 여기서는 조회만 한다
        (`tools/build_tag_combo_implications.py`). 동족(머리 명사 동일)은
        문자열 규칙이라 표가 없어도 공짜로 걸린다.
        """
        picked: list[int] = []
        picked_names: list[str] = []
        heads: set[str] = set()
        implies = self.m.implies
        for c in sel:
            name = self.m.tags[c]
            words = name.split()
            head = words[-1] if len(words) > 1 else ""
            if head and head in heads:
                continue
            rel = implies.get(name)
            if rel and any(q in rel for q in picked_names):
                continue
            picked.append(c)
            picked_names.append(name)
            if head:
                heads.add(head)
            if len(picked) >= size:
                break
        return picked
