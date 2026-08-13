# -*- coding: utf-8 -*-
"""조합 추천의 불변식 테스트.

이전 시도(.experimental/2025/state_system)는 '함수가 뭔가 반환했는가' 를 hit rate
라고 부르다 죽었다. 그래서 여기서는 **동작이 아니라 계약**을 건다.

지표 자체의 검증(P@N_info / Hit_i@K, stub 이 0점인지)은 tools/reco_probe 의
프로브가 담당한다 - 그건 코퍼스가 필요해서 단위 테스트로 못 돌린다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tag_combo.model import MAX_LOCAL_VOCAB, ComboModel, write_model  # noqa: E402
from core.tag_combo.person import PERSON_GROUPS, person_group_of          # noqa: E402
from core.tag_combo.query import ComboQuery, Policy                        # noqa: E402


# ---------------------------------------------------------------- 인원 판정
class TestPersonGroup:
    def test_thirteen_groups(self):
        assert len(PERSON_GROUPS) == 13
        assert len(set(PERSON_GROUPS)) == 13

    @pytest.mark.parametrize("tags,expected", [
        ({"1girl", "solo"}, "1girl_solo"),
        ({"1boy", "solo"}, "1boy_solo"),
        ({"1girl"}, "1girl"),
        ({"1girl", "1boy"}, "1girl_1boy"),
        ({"2girls"}, "2girls"),
        ({"2boys"}, "2boys"),
        ({"multiple girls"}, "multiple_girls"),
        ({"multiple boys"}, "multiple_boys"),
        ({"1girl", "multiple boys"}, "1girl_multiple_boys"),
        ({"1boy", "multiple girls"}, "1boy_multiple_girls"),
        ({"multiple girls", "multiple boys"}, "multiple_girls_multiple_boys"),
    ])
    def test_known(self, tags, expected):
        assert person_group_of(tags) == expected

    def test_never_returns_empty(self):
        """원본 `_infer_person_id_from_prompt` 는 미매칭에 '' 를 낸다.

        그대로 쓰면 14번째 유령 버킷이 생긴다 - 실측으로 `other` 는 283,386건
        (3.8%)이라 무시할 수 없다. 여기서는 반드시 `other` 로 접혀야 한다.
        """
        for tags in ({"no humans"}, set(), {"scenery", "tree"}, {"cat"}):
            got = person_group_of(tags)
            assert got == "other", f"{tags} -> {got!r}"
            assert got in PERSON_GROUPS

    def test_mixed_beats_same_gender(self):
        """혼성이 동성보다 먼저 걸린다 - preset_input_bridge 와 같은 우선순위."""
        assert person_group_of({"1girl", "1boy", "2girls"}) == "1girl_1boy"
        assert person_group_of({"1girl", "multiple boys", "2girls"}) == \
            "1girl_multiple_boys"

    def test_output_always_in_vocabulary(self):
        import random
        rng = random.Random(1)
        pool = ["1girl", "1boy", "solo", "2girls", "2boys", "multiple girls",
                "multiple boys", "cat", "scenery", "no humans"]
        for _ in range(300):
            k = rng.randint(0, 5)
            assert person_group_of(set(rng.sample(pool, k))) in PERSON_GROUPS


# ------------------------------------------------------------------ 픽스처
def _toy(tmp_path: Path) -> ComboModel:
    """작은 인공 코퍼스. `maid` 를 고르면 앞치마 세트가 따라오게 만든다."""
    tags = ["maid", "maid headdress", "apron", "frills", "sword", "armor",
            "outdoors", "tree", "long hair", "smile"]
    tid = {t: i for i, t in enumerate(tags)}
    rows, ratings, chars = [], [], []
    # 메이드 60건 - 앞치마 세트가 항상 따라온다
    for i in range(60):
        r = ["maid", "maid headdress", "apron", "frills", "long hair"]
        if i % 3 == 0:
            r.append("smile")
        rows.append(sorted(tid[t] for t in r)); ratings.append(1); chars.append(0)
    # 검사 40건
    for i in range(40):
        r = ["sword", "armor", "long hair"]
        if i % 2 == 0:
            r.append("outdoors")
        rows.append(sorted(tid[t] for t in r)); ratings.append(0); chars.append(0)
    # 배경 100건 - long hair 를 흔하게 만들어 배경 태그로 만든다
    for i in range(100):
        rows.append(sorted(tid[t] for t in ("long hair", "smile", "tree")))
        ratings.append(1); chars.append(0)
    freq = [0] * len(tags)
    tag_rating = np.zeros((len(tags), 4), dtype=np.uint32)
    for row, r in zip(rows, ratings):
        for i in row:
            freq[i] += 1
            tag_rating[i, r] += 1
    p = tmp_path / "toy.ncsr"
    write_model(p, group="1girl_solo", rows=rows, tags=tags, freq=freq,
                post_rating=ratings, post_char=chars, tag_rating=tag_rating,
                sampled_from=len(rows))
    return ComboModel(p)


# ------------------------------------------------------------------- 포맷
class TestModelFormat:
    def test_roundtrip(self, tmp_path):
        m = _toy(tmp_path)
        assert m.header.posts == 200
        assert m.header.vocab == 10
        assert m.header.nnz == sum(np.diff(m.indptr))
        assert len(m.tags) == m.header.vocab
        assert m.post_char.shape[0] == m.header.posts
        assert m.tag_rating.shape == (m.header.vocab, 4)

    def test_rejects_oversize_vocab(self, tmp_path):
        """uint16 상한을 넘기면 조용히 깨지지 말고 즉시 죽어야 한다."""
        big = [f"t{i}" for i in range(MAX_LOCAL_VOCAB + 1)]
        with pytest.raises(ValueError, match="상한"):
            write_model(tmp_path / "x.ncsr", group="1girl_solo", rows=[[0]],
                        tags=big, freq=[1] * len(big), post_rating=[0],
                        post_char=[0],
                        tag_rating=np.zeros((len(big), 4), dtype=np.uint32),
                        sampled_from=1)

    def test_postings_sorted_and_unique(self, tmp_path):
        """`np.intersect1d(assume_unique=True)` 의 전제.

        unstable argsort 로 만들면 이 성질이 깨지고 **조용히 틀린 답**이 나온다
        (실측 정렬 위반 1,180만 건). 그래서 CSR->CSC 를 쓴다.
        """
        m = _toy(tmp_path)
        for t in m.tags:
            p = m.postings(t)
            assert p is not None
            assert np.all(np.diff(p) > 0), f"{t} 의 postings 가 정렬/유일하지 않다"

    def test_postings_match_rows(self, tmp_path):
        m = _toy(tmp_path)
        for t in m.tags:
            i = m.tag_to_id[t]
            expect = {p for p in range(m.header.posts) if i in set(m.row(p))}
            assert set(int(x) for x in m.postings(t)) == expect


# ------------------------------------------------------------------- 질의
class TestQuery:
    def test_finds_the_planted_combo(self, tmp_path):
        q = ComboQuery(_toy(tmp_path), Policy(floor=10, min_pair=5))
        r = q.recommend(["maid"])
        assert r.combos, "심어 둔 조합을 못 찾았다"
        top = set(r.combos[0].tags)
        assert "maid headdress" in top and "apron" in top

    def test_background_tag_is_not_recommended(self, tmp_path):
        """`long hair` 는 200건 중 200건에 있다 - 배경이지 조합이 아니다."""
        q = ComboQuery(_toy(tmp_path), Policy(floor=10, min_pair=5))
        r = q.recommend(["maid"])
        for c in r.combos:
            assert "long hair" not in c.tags

    def test_unknown_tag_does_not_zero_the_query(self, tmp_path):
        """Quick Search 는 어휘 밖 태그가 하나만 있어도 0건을 냈다.

        백오프가 있으면 아는 태그로 답해야 한다.
        """
        q = ComboQuery(_toy(tmp_path), Policy(floor=10, min_pair=5))
        r = q.recommend(["maid", "zzz-not-a-tag"])
        assert r.combos, "어휘 밖 태그 하나에 질의가 통째로 죽었다"

    def test_all_unknown_returns_empty_not_crash(self, tmp_path):
        q = ComboQuery(_toy(tmp_path), Policy(floor=10, min_pair=5))
        r = q.recommend(["zzz", "qqq"])
        assert r.combos == [] and r.matched == 0

    def test_prompt_tags_never_recommended_back(self, tmp_path):
        q = ComboQuery(_toy(tmp_path), Policy(floor=10, min_pair=5))
        for prompt in (["maid"], ["maid", "apron"], ["sword"]):
            r = q.recommend(prompt)
            for c in r.combos:
                assert not (set(c.tags) & set(prompt))

    def test_bundle_size_backoff(self, tmp_path):
        """크기 N 튜플이 없으면 N-1 로 내려간다.

        안 하면 실측 13%(106/800)의 질의가 빈 답이 된다.
        """
        m = _toy(tmp_path)
        q = ComboQuery(m, Policy(floor=10, min_pair=5, bundle=5, min_bundle=2))
        r = q.recommend(["sword"])
        assert r.combos, "크기 백오프가 동작하지 않았다"
        assert r.bundle_size < 5 and r.bundle_size >= 2

    def test_no_content_gating(self, tmp_path):
        """**콘텐츠를 막지 않는다** - 이 시스템의 제약이다.

        성인/금기 어휘라는 이유로 후보에서 빠지는 경로가 있으면 안 된다.
        """
        # 성인 군집을 **소수**로 둔다. 전체의 절반을 차지하게 만들면 배경 태그
        # 상한(P(B) <= 0.30)에 걸려서 안 나오는데, 그건 콘텐츠 게이팅이 아니라
        # '너무 흔한 태그는 조합이 아니다' 라는 일반 규칙이다. 처음에 50/50 으로
        # 짰다가 이 테스트가 엉뚱한 이유로 실패했다.
        tags = ["bondage", "rope", "collar", "blindfold", "1girl", "indoors",
                "smile", "outdoors"]
        tid = {t: i for i, t in enumerate(tags)}
        rows, ratings, chars = [], [], []
        for i in range(50):
            rows.append(sorted(tid[t] for t in
                               ("bondage", "rope", "collar", "blindfold")))
            ratings.append(3); chars.append(0)
        for i in range(450):
            r = ("1girl", "indoors") if i % 2 else ("1girl", "smile", "outdoors")
            rows.append(sorted(tid[t] for t in r))
            ratings.append(0); chars.append(0)
        freq = [0] * len(tags)
        tr = np.zeros((len(tags), 4), dtype=np.uint32)
        for row, r in zip(rows, ratings):
            for i in row:
                freq[i] += 1; tr[i, r] += 1
        p = tmp_path / "adult.ncsr"
        write_model(p, group="1girl_solo", rows=rows, tags=tags, freq=freq,
                    post_rating=ratings, post_char=chars, tag_rating=tr,
                    sampled_from=len(rows))
        q = ComboQuery(ComboModel(p), Policy(floor=10, min_pair=5))
        r = q.recommend(["bondage"])
        assert r.combos, "성인 컨텍스트에서 아무것도 안 나왔다 - 게이팅이 있는지 보라"
        got = set(r.combos[0].tags)
        assert {"rope", "collar"} & got

    def test_character_concentration_filter(self, tmp_path):
        """한 캐릭터가 매칭의 절반을 넘게 차지하면 그 태그는 캐릭터 디자인이다.

        반증 실험 8.2 에서 우위의 41%가 이 암기였다.
        """
        # 후보가 배경 상한(P(B)<=0.30)에 걸리지 않도록 **전체를 크게** 잡는다.
        # 처음엔 40건짜리 코퍼스로 짰는데 모든 후보가 P=1.0 이라 집중도 필터에
        # 닿기도 전에 잘려서, 조합이 비고 테스트가 아무것도 검증하지 않았다.
        tags = ["swimsuit", "bikini", "ocean", "pink halo", "indoors", "smile"]
        tid = {t: i for i, t in enumerate(tags)}
        rows, ratings, chars = [], [], []
        # 수영복 100건. 40건은 **한 캐릭터(7번)** 이고 그 캐릭터만 pink halo 를
        # 쓴다. 나머지 60건은 캐릭터가 전부 다르다 - 그래야 bikini/ocean 이
        # 집중도에 안 걸린다(둘 다 걸리면 후보가 통째로 비어 필터를 검증 못 한다).
        #   pink halo 집중도 40/40 = 1.00 -> 걸린다
        #   bikini     집중도 40/100 = 0.40 -> 통과
        for i in range(100):
            r = ["swimsuit", "bikini", "ocean"]
            if i < 40:
                r.append("pink halo")
                ch = 7
            else:
                ch = 100 + i        # 전부 다른 캐릭터
            rows.append(sorted(tid[t] for t in r))
            ratings.append(1); chars.append(ch)
        # 배경 400건. 그중 25건에 bikini/ocean 을 섞어 **lift 를 갈라 놓는다** -
        # 셋 다 lift 5.0 이면 pink halo 가 상위 2에 못 들어 필터 유무가 결과에
        # 안 나타난다.
        #   pink halo  conf 0.40 / P 0.08 -> lift 5.0  (가장 높다)
        #   bikini     conf 1.00 / P 0.25 -> lift 4.0
        for i in range(400):
            r = ["indoors", "smile"]
            if i < 25:
                r += ["bikini", "ocean"]
            rows.append(sorted(tid[t] for t in r))
            ratings.append(0); chars.append(0)
        freq = [0] * len(tags)
        tr = np.zeros((len(tags), 4), dtype=np.uint32)
        for row, r in zip(rows, ratings):
            for i in row:
                freq[i] += 1; tr[i, r] += 1
        p = tmp_path / "char.ncsr"
        write_model(p, group="1girl_solo", rows=rows, tags=tags, freq=freq,
                    post_rating=ratings, post_char=chars, tag_rating=tr,
                    sampled_from=len(rows))
        pol = Policy(floor=5, min_pair=3, bundle=2, min_bundle=2)
        mdl = ComboModel(p)
        r = ComboQuery(mdl, pol).recommend(["swimsuit"])
        # **먼저 필터가 실제로 탔는지 확인한다.** 처음엔 이 확인 없이 바로
        # `pink halo not in c.tags` 만 봤는데, combos 가 비어 있어서 루프가
        # 한 번도 안 돌고 통과했다 - 아무것도 검증하지 않는 테스트였다
        # (Codex 게이트가 잡았다).
        assert r.combos, "조합이 비어 필터를 검증하지 못한다 - 테스트가 무의미하다"
        for c in r.combos:
            assert "pink halo" not in c.tags, \
                "한 캐릭터에 몰린 태그가 조합으로 나왔다"
        # 그리고 필터를 끄면 나와야 한다 - 안 그러면 다른 이유로 빠진 것이다.
        loose = Policy(floor=5, min_pair=3, bundle=2, min_bundle=2,
                       max_char_share=1.0)
        r2 = ComboQuery(ComboModel(p), loose).recommend(["swimsuit"])
        assert any("pink halo" in c.tags for c in r2.combos), \
            "필터를 꺼도 안 나온다 - 집중도 때문에 빠진 것이 아니다"


class TestContracts:
    """Codex 게이트가 '없다' 고 지적한 계약들."""

    def test_top_k_does_not_change_ranking(self, tmp_path):
        """`top_k` 는 **자르는 수**이지 순위를 바꾸면 안 된다.

        처음엔 지지도 상위 top_k 를 뽑고 그 안에서 점수 정렬을 해서, 헤드 캐시
        (top_k=20)와 일반 질의(top_k=5)가 같은 태그에 **다른 답**을 냈다
        (실측 41개 중 15개 불일치).
        """
        m = _toy(tmp_path)
        base = Policy(floor=10, min_pair=5)
        small = ComboQuery(m, base).recommend(["maid"])
        big = ComboQuery(m, Policy(floor=10, min_pair=5, top_k=20)).recommend(["maid"])
        n = min(len(small.combos), len(big.combos))
        assert n > 0
        assert [c.tags for c in small.combos[:n]] == [c.tags for c in big.combos[:n]], \
            "top_k 를 바꾸니 순위가 달라졌다"

    def test_person_group_normalizes_input(self):
        """danbooru 원문(`multiple_boys`)과 화면 표기(`multiple boys`)가 같아야 한다.

        브릿지는 소문자화 + `_`->공백을 한다. 안 맞추면 같은 인원 설정에서
        프리셋과 조합이 다른 모델을 본다(실측 254개 중 200개 불일치).
        """
        pairs = [
            ({"1girl", "multiple_boys"}, {"1girl", "multiple boys"}),
            ({"MULTIPLE GIRLS", "MULTIPLE BOYS"}, {"multiple girls", "multiple boys"}),
            ({"1Girl", "Solo"}, {"1girl", "solo"}),
            ({"2Girls"}, {"2girls"}),
        ]
        for a, b in pairs:
            assert person_group_of(a) == person_group_of(b), f"{a} != {b}"

    def test_person_group_matches_preset_bridge(self):
        """프리셋 브릿지가 답을 내는 입력에서는 반드시 같아야 한다."""
        from itertools import combinations as _c
        import core.preset_input_bridge as bridge
        pool = ["1girl", "1boy", "solo", "2girls", "2boys",
                "multiple girls", "multiple boys"]
        checked = 0
        for k in range(1, len(pool) + 1):
            for sub in _c(pool, k):
                for variant in (list(sub), [t.replace(" ", "_") for t in sub],
                                [t.upper() for t in sub]):
                    want = bridge._infer_person_id_from_prompt(None, tags=variant)
                    if not want:
                        continue
                    checked += 1
                    got = person_group_of(variant)
                    assert got == want, f"{variant}: 조합 {got!r} vs 프리셋 {want!r}"
        assert checked > 300, f"검사한 조합이 {checked}개뿐이다"

    def test_backoff_is_bounded_for_large_prompts(self, tmp_path):
        """부분집합 전수 열거는 지수다 - 큰 프롬프트에서 사슬로 바뀌어야 한다.

        라우트가 24태그를 받는다. 전수면 16,777,215 개고 실측 20태그에 15.2초다.
        """
        import time
        m = _toy(tmp_path)
        q = ComboQuery(m, Policy(floor=10, min_pair=5))
        big = [f"unknown-{i}" for i in range(20)] + ["maid", "apron"]
        t0 = time.time()
        q.recommend(big)
        assert time.time() - t0 < 2.0, "큰 프롬프트에서 백오프가 폭발한다"

    def test_nbytes_counts_every_section(self, tmp_path):
        """LRU 가 이 값으로 예산을 잰다 - 섹션이 빠지면 그만큼 더 얹힌다."""
        m = _toy(tmp_path)
        want = (m.indptr.nbytes + m.indices.nbytes + m.post_rating.nbytes
                + m.post_char.nbytes + m.tag_rating.nbytes)
        assert m.nbytes == want
        m.ensure_inverted()
        assert m.nbytes > want, "역인덱스가 안 세어진다"

    def test_peek_bytes_is_not_an_underestimate(self, tmp_path):
        """LRU 는 적재 **전에** 이 값으로 자리를 비운다. 낮게 잡으면 겹친다."""
        m = _toy(tmp_path)
        m.ensure_inverted()
        peek = ComboModel.peek_bytes(tmp_path / "toy.ncsr")
        assert peek >= m.nbytes, f"peek {peek} < 실제 {m.nbytes}"
