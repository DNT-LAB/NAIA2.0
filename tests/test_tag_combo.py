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
        tags = ["swimsuit", "beach", "pink halo", "ocean"]
        tid = {t: i for i, t in enumerate(tags)}
        rows, ratings, chars = [], [], []
        # 수영복 40건 - 그중 30건이 같은 캐릭터이고 그 캐릭터만 pink halo 를 쓴다
        for i in range(40):
            r = ["swimsuit", "beach", "ocean"]
            ch = 0
            if i < 30:
                r.append("pink halo")
                ch = 7          # 같은 캐릭터
            rows.append(sorted(tid[t] for t in r))
            ratings.append(1); chars.append(ch)
        freq = [0] * len(tags)
        tr = np.zeros((len(tags), 4), dtype=np.uint32)
        for row, r in zip(rows, ratings):
            for i in row:
                freq[i] += 1; tr[i, r] += 1
        p = tmp_path / "char.ncsr"
        write_model(p, group="1girl_solo", rows=rows, tags=tags, freq=freq,
                    post_rating=ratings, post_char=chars, tag_rating=tr,
                    sampled_from=len(rows))
        q = ComboQuery(ComboModel(p), Policy(floor=5, min_pair=3, bundle=2,
                                             min_bundle=2))
        r = q.recommend(["swimsuit"])
        for c in r.combos:
            assert "pink halo" not in c.tags, \
                "한 캐릭터에 몰린 태그가 조합으로 나왔다"
