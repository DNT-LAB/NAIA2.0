# -*- coding: utf-8 -*-
"""조합 추천의 불변식 테스트.

이전 시도(.experimental/2025/state_system)는 '함수가 뭔가 반환했는가' 를 hit rate
라고 부르다 죽었다. 그래서 여기서는 **동작이 아니라 계약**을 건다.

지표 자체의 검증(P@N_info / Hit_i@K, stub 이 0점인지)은 tools/reco_probe 의
프로브가 담당한다 - 그건 코퍼스가 필요해서 단위 테스트로 못 돌린다.
"""
from __future__ import annotations

import json
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
        tags = ["swimsuit", "bikini", "ocean", "winged halo", "indoors", "smile"]
        tid = {t: i for i, t in enumerate(tags)}
        rows, ratings, chars = [], [], []
        # 수영복 100건. 40건은 **한 캐릭터(7번)** 이고 그 캐릭터만 winged halo 를
        # 쓴다. 나머지 60건은 캐릭터가 전부 다르다 - 그래야 bikini/ocean 이
        # 집중도에 안 걸린다(둘 다 걸리면 후보가 통째로 비어 필터를 검증 못 한다).
        #   winged halo 집중도 40/40 = 1.00 -> 걸린다
        #   bikini     집중도 40/100 = 0.40 -> 통과
        for i in range(100):
            r = ["swimsuit", "bikini", "ocean"]
            if i < 40:
                r.append("winged halo")
                ch = 7
            else:
                ch = 100 + i        # 전부 다른 캐릭터
            rows.append(sorted(tid[t] for t in r))
            ratings.append(1); chars.append(ch)
        # 배경 400건. 그중 25건에 bikini/ocean 을 섞어 **lift 를 갈라 놓는다** -
        # 셋 다 lift 5.0 이면 winged halo 가 상위 2에 못 들어 필터 유무가 결과에
        # 안 나타난다.
        #   winged halo  conf 0.40 / P 0.08 -> lift 5.0  (가장 높다)
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
        # `winged halo not in c.tags` 만 봤는데, combos 가 비어 있어서 루프가
        # 한 번도 안 돌고 통과했다 - 아무것도 검증하지 않는 테스트였다
        # (Codex 게이트가 잡았다).
        assert r.combos, "조합이 비어 필터를 검증하지 못한다 - 테스트가 무의미하다"
        for c in r.combos:
            assert "winged halo" not in c.tags, \
                "한 캐릭터에 몰린 태그가 조합으로 나왔다"
        # 그리고 필터를 끄면 나와야 한다 - 안 그러면 다른 이유로 빠진 것이다.
        loose = Policy(floor=5, min_pair=3, bundle=2, min_bundle=2,
                       max_char_share=1.0)
        r2 = ComboQuery(ComboModel(p), loose).recommend(["swimsuit"])
        assert any("winged halo" in c.tags for c in r2.combos), \
            "필터를 꺼도 안 나온다 - 집중도 때문에 빠진 것이 아니다"


class TestBundle:
    """배포판은 이 경로로만 돈다 - 느슨한 파일이 없다."""

    def _bundle(self, tmp_path):
        from core.tag_combo.bundle import ComboBundle, write_bundle
        _toy(tmp_path)                      # toy.ncsr + toy.json 생성
        out = tmp_path / "b.ncsb"
        write_bundle(out, [tmp_path / "toy.ncsr"], source="test")
        return ComboBundle(out), out

    def test_roundtrip_is_byte_identical(self, tmp_path):
        b, _ = self._bundle(tmp_path)
        meta, body = b.read("toy")
        assert body == (tmp_path / "toy.ncsr").read_bytes()
        assert meta == json.loads((tmp_path / "toy.json").read_text(encoding="utf-8"))

    def test_model_opens_from_bundle(self, tmp_path):
        b, _ = self._bundle(tmp_path)
        meta, body = b.read("toy")
        loose = ComboModel(tmp_path / "toy.ncsr")
        fromb = ComboModel(tmp_path / "toy.ncsr", meta=meta, blob=body)
        assert fromb.header.posts == loose.header.posts
        assert fromb.tags == loose.tags
        assert np.array_equal(fromb.indices, loose.indices)
        assert np.array_equal(fromb.post_char, loose.post_char)
        # 질의 결과까지 같아야 한다 - 포맷이 아니라 동작이 계약이다.
        pol = Policy(floor=10, min_pair=5)
        assert ([c.tags for c in ComboQuery(fromb, pol).recommend(["maid"]).combos]
                == [c.tags for c in ComboQuery(loose, pol).recommend(["maid"]).combos])

    def test_corruption_is_caught(self, tmp_path):
        """다운로드 산물이다. 조용히 틀린 답을 내느니 죽어야 한다."""
        b, out = self._bundle(tmp_path)
        e = b.entries["toy"]
        raw = bytearray(out.read_bytes())
        raw[e.body_off + 8] ^= 0xFF
        bad = tmp_path / "bad.ncsb"
        bad.write_bytes(raw)
        from core.tag_combo.bundle import ComboBundle
        assert ComboBundle(bad).verify_all() == ["toy"]

    def test_verify_all_scans_every_group(self, tmp_path):
        """read() 는 읽는 그룹만 본다. 설치 단계는 전부 봐야 한다."""
        b, _ = self._bundle(tmp_path)
        assert b.verify_all() == []
        assert set(b.groups()) == {"toy"}

    # ---- aux-only 번들 (배포 형태) --------------------------------------
    @staticmethod
    def _aux_files(d: Path, *, bank_format: str = "NRB3", groups=("1girl_solo",)):
        from core.tag_combo.person import PERSON_GROUPS as _PG
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe_bank.json").write_text(json.dumps({
            "format": bank_format, "policy": {},
            "groups": {g: {"maid": {"rows": [], "tags": [
                {"tag": "apron", "p": 0.66, "lift": 5.0}]}} for g in groups},
        }), encoding="utf-8")
        (d / "semantic_graph.json").write_text(
            json.dumps({"edges": []}), encoding="utf-8")
        (d / "anchor_feature_marginals.json").write_text(
            json.dumps({"anchors": {}}), encoding="utf-8")
        return {n: d / f"{n}.json" for n in
                ("recipe_bank", "semantic_graph", "anchor_feature_marginals")}

    def _aux_bundle(self, tmp_path, **kw):
        from core.tag_combo.bundle import ComboBundle, write_bundle
        aux = self._aux_files(tmp_path / "src", **kw)
        out = tmp_path / "auxonly.ncsb"
        write_bundle(out, [], source="test", aux=aux, built="t")
        return ComboBundle(out), out

    def test_aux_only_bundle_roundtrips(self, tmp_path):
        """배포 번들에는 그룹 모델이 없다(203MB -> 15MB)."""
        b, out = self._aux_bundle(tmp_path)
        assert b.groups() == [], "aux-only 인데 그룹이 있다"
        assert set(b.aux_index) == {"recipe_bank", "semantic_graph",
                                    "anchor_feature_marginals"}
        assert b.verify_all() == []
        d = json.loads(b.aux("recipe_bank").decode("utf-8"))
        assert d["format"] == "NRB3"

    @pytest.mark.parametrize("name", ["recipe_bank", "semantic_graph",
                                      "anchor_feature_marginals"])
    def test_aux_corruption_is_caught(self, tmp_path, name):
        """**그룹만 보던 검증은 aux-only 번들에서 아무것도 안 봤다.**

        모델 없이 부속만 담으면 `verify_all` 이 빈 루프를 돌고 "성공" 을 냈다 -
        레시피 뱅크가 깨진 번들이 그대로 설치된다(Codex 지적 2026-08-17).
        """
        from core.tag_combo.bundle import ComboBundle
        b, out = self._aux_bundle(tmp_path)
        e = b.aux_index[name]
        raw = bytearray(out.read_bytes())
        raw[e["off"] + max(0, e["len"] // 2)] ^= 0xFF
        bad = tmp_path / f"bad_{name}.ncsb"
        bad.write_bytes(raw)
        assert ComboBundle(bad).verify_all() == [f"aux:{name}"]

    def test_aux_only_rejects_old_bank_format(self, tmp_path):
        """sha 가 맞아도 형식이 옛것이면 설치 단계에서 걸러야 한다."""
        b, _ = self._aux_bundle(tmp_path, bank_format="NRB2")
        assert b.verify_all() == ["aux:recipe_bank"]

    def test_aux_only_rejects_empty_bank(self, tmp_path):
        b, _ = self._aux_bundle(tmp_path, groups=())
        assert b.verify_all() == ["aux:recipe_bank"]

    def test_old_bundle_without_aux_is_not_called_corrupt(self, tmp_path):
        """NCSB1 은 부속이 없다. 그건 손상이 아니라 옛 형식이다."""
        b, _ = self._bundle(tmp_path)          # 그룹만, aux 없음
        assert b.aux_index == {}
        assert b.verify_all() == []

    def test_rejects_foreign_file(self, tmp_path):
        p = tmp_path / "nope.ncsb"
        p.write_bytes(b"not a bundle at all")
        from core.tag_combo.bundle import ComboBundle
        with pytest.raises(ValueError, match="매직"):
            ComboBundle(p)


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



class TestDataRoot:
    """받는 곳 / 찾는 곳. 이걸 틀리면 두 런타임이 다 틀린다.

    소스 실행은 179MB 를 git 트리에 받고, 포터블은 업데이트가 지우는 자리
    (`resources/naia-backend/data/`)에 받는다. 저장소 관례는
    `runtime_paths.data_dir` -> `repo_root/data` 다.
    """

    def test_downloads_into_runtime_data_dir_not_the_repo(self, tmp_path):
        from core.runtime_paths import resolve_runtime_paths
        from core.tag_combo.service import resolve_dirs
        target, search = resolve_dirs(tmp_path)
        want = Path(resolve_runtime_paths(tmp_path).data_dir) / "tag_combo"
        assert target == want, f"{target} 에 받으려 한다"
        assert target != tmp_path / "data" / "tag_combo", "저장소 안에 받는다"

    def test_repo_is_still_searched_first(self, tmp_path):
        """개발 중에 방금 구운 모델이 내려받은 것보다 우선이어야 한다."""
        from core.tag_combo.service import resolve_dirs
        _, search = resolve_dirs(tmp_path)
        assert search[0] == tmp_path / "data" / "tag_combo"
        assert len(search) == 2

    @staticmethod
    def _group(d: Path, name: str) -> None:
        """`_toy` 를 그룹 이름의 모델 파일로 만든다(사이드카 포함)."""
        d.mkdir(parents=True, exist_ok=True)
        _toy(d)
        for f in list(d.glob("toy.*")):
            f.rename(d / f.name.replace("toy.", f"{name}.", 1))

    def test_finds_models_outside_the_download_dir(self, tmp_path):
        """받는 곳과 찾는 곳이 다르므로, 저장소에 있는 모델도 보여야 한다."""
        from core.tag_combo.service import ComboService
        repo, dl = tmp_path / "repo", tmp_path / "userdata"
        self._group(repo, "1girl_solo")
        svc = ComboService(dl, search_dirs=[repo, dl])
        assert "1girl_solo" in svc.available(), "저장소의 모델이 안 보인다"

    @staticmethod
    def _bank_file(d: Path, groups) -> None:
        """느슨한 `recipe_bank.json`. 그룹마다 앵커 하나씩."""
        import json
        d.mkdir(parents=True, exist_ok=True)
        (d / "recipe_bank.json").write_text(json.dumps({
            "format": "NRB3", "policy": {},
            "groups": {g: {"maid": {
                "rows": [{"tags": ["apron"], "support": 99, "coverage": 0.49}],
                "tags": [{"tag": "apron", "p": 0.66, "lift": 5.0}]}}
                for g in groups},
        }), encoding="utf-8")

    def test_models_do_not_make_it_ready(self, tmp_path):
        """**준비 판정은 모델이 아니라 뱅크다.**

        배포 번들에는 그룹 모델이 들어가지 않는다(203MB -> 15MB). 모델 목록으로
        판정하던 시절의 계약을 그대로 두면 정상 설치가 영원히 `incomplete` 가
        된다(Codex 지적 2026-08-17). 반대로 모델이 13개 다 있어도 뱅크가 없으면
        화면에는 추천이 없다 - 그것도 ready 가 아니다.
        """
        from core.tag_combo.service import ComboService
        d = tmp_path / "models_only"
        for g in PERSON_GROUPS:
            self._group(d, g)
        svc = ComboService(d, search_dirs=[d])
        assert len(svc.available()) == len(PERSON_GROUPS), "모델은 다 있다"
        assert not svc.ready(), "모델만으로 ready 라고 하면 화면은 빈다"
        assert svc.download_status()["state"] != "ready"

    def test_bank_alone_is_ready_without_any_model(self, tmp_path):
        """모델 0개 + 뱅크 13그룹 = 준비 완료. 이게 배포 형태다."""
        from core.tag_combo.service import ComboService
        d = tmp_path / "bank_only"
        self._bank_file(d, PERSON_GROUPS)
        svc = ComboService(d, search_dirs=[d])
        assert svc.available() == [], "모델이 없어야 하는 상황이다"
        assert svc.ready(), "뱅크 13그룹인데 ready 가 아니다"
        st = svc.download_status()
        assert st["state"] == "ready" and st["missing"] == []
        assert len(st["bankGroups"]) == len(PERSON_GROUPS)
        r = svc.recommend(["maid"], group="2boys", anchor="maid")
        assert [x["tag"] for x in r["tags"]] == ["apron"], r

    def test_partial_bank_does_not_stand_in_for_thirteen(self, tmp_path):
        """**부분 뱅크를 완성으로 치면 안 된다.**

        빠진 인원 그룹은 사용자가 인원 수를 바꾸는 순간에야 드러난다. 그때까지
        다운로드는 시작되지 않는다.
        """
        from core.tag_combo.service import ComboService
        d = tmp_path / "partial_bank"
        self._bank_file(d, ["1girl_solo"])
        svc = ComboService(d, search_dirs=[d])
        assert not svc.ready()
        st = svc.download_status()
        assert st["state"] != "ready"
        assert len(st["missing"]) == len(PERSON_GROUPS) - 1

    def test_missing_bank_group_is_a_data_error_not_a_fallback(self, tmp_path):
        """뱅크에 없는 그룹은 **오류로 드러낸다.**

        예전에는 온라인 모델로 폴백했다. 배포에 모델이 없으므로 폴백 대상이
        없고, 조용한 니치 추천보다 오류가 정직하다.
        """
        from core.tag_combo.service import ComboService
        d = tmp_path / "one_group"
        self._bank_file(d, ["1girl_solo"])
        svc = ComboService(d, search_dirs=[d])
        r = svc.recommend(["maid"], group="2boys", anchor="maid")
        assert r.get("error") == "bank group missing", r
        assert not r.get("tags") and not r.get("combos")

    def test_downloads_when_nothing_is_present(self, tmp_path):
        from core.tag_combo.service import ComboService
        svc = ComboService(tmp_path / "dl", search_dirs=[tmp_path / "dl"])
        assert not svc.ready()
        assert svc.download_status()["state"] != "ready"

    def test_bank_attaches_after_the_file_arrives(self, tmp_path):
        """받기 전에 한 번 열어 본 설치가 **재시작 없이** 붙어야 한다.

        예전에는 첫 조회의 `None` 을 프로세스 수명 동안 물고 있었다.
        """
        from core.tag_combo.service import ComboService
        d = tmp_path / "late"
        d.mkdir()
        svc = ComboService(d, search_dirs=[d])
        assert svc.bank() is None and not svc.ready()
        self._bank_file(d, PERSON_GROUPS)
        assert svc.bank() is not None, "파일이 왔는데도 옛 None 을 물고 있다"
        assert svc.ready()


class TestRecovery:
    """깨진 데이터에서 **빠져나올 수 있는가.** 못 빠져나오면 그 설치는 끝이다."""

    def test_corrupt_group_does_not_escape_as_an_exception(self, tmp_path, monkeypatch):
        """본문이 깨진 그룹은 `zlib.error` 를 낸다 - 좁은 except 로는 못 잡는다.

        예전엔 `(OSError, ValueError, KeyError)` 만 잡아서 `recommend()` 가
        그대로 터졌다(실측: 1girl_solo 본문에 0 을 2KB 쓰면 재현).
        """
        import zlib
        from core.tag_combo.service import ComboService

        class BoomBundle:
            path = tmp_path / "x.ncsb"
            entries = {"1girl_solo": object()}

            def read(self, group):
                raise zlib.error("incorrect data check")

        svc = ComboService(tmp_path)
        monkeypatch.setattr(svc, "bundle", lambda: BoomBundle())
        out = svc.recommend(["maid"], group="1girl_solo")     # 터지면 실패다
        assert out["combos"] == []
        assert "1girl_solo" in svc._bad_groups
        assert not svc._have_models(), "깨진 그룹을 세고 있어 복구가 안 걸린다"

    def test_failed_bundle_is_retried_when_the_file_changes(self, tmp_path):
        """실패를 영구 캐시하면 다시 받아도 안 읽는다.

        조언 카드에서 실패를 `null` 로 영구 캐시해 같은 사고를 낸 전례가 있다.
        """
        from core.tag_combo.download import BUNDLE_NAME
        from core.tag_combo.service import ComboService
        p = tmp_path / BUNDLE_NAME
        p.write_bytes(b"NOTABUNDLE" * 8)
        svc = ComboService(tmp_path, search_dirs=[tmp_path])
        assert svc.bundle() is None and svc._bundle_bad
        sig = svc._bad_sig
        p.write_bytes(b"NOTABUNDLE" * 9)      # 파일이 바뀌었다 = 다시 받았다
        assert svc._bundle_sig() != sig, "지문이 안 바뀌면 재시도 판정이 불가능하다"
        svc.bundle()
        assert svc._bad_sig == svc._bundle_sig(), "새 파일로 다시 시도하지 않았다"

    def test_error_state_does_not_auto_restart_the_download(self, tmp_path):
        """179MB 다.

        `start()` 는 스레드가 죽었으면 그냥 다시 받는데, 실패 상태에서는 그게
        폴링/재진입마다 전체 재다운로드가 된다. retry() 로만 풀려야 한다.
        """
        from core.tag_combo.download import BundleDownloader
        d = BundleDownloader(tmp_path, url="http://example.invalid/x", sha256="")
        d.state.state = "error"
        d.state.error = "boom"
        assert d.start()["state"] == "error", "실패에서 저절로 다시 받는다"
        assert d._thread is None


class TestRecipeBank:
    """오프라인 레시피 뱅크 — 온라인 지명 병목을 대체한다."""

    @staticmethod
    def _bank(tmp_path, groups):
        # NRB3 는 `앵커 -> {rows, tags}` 다. 테스트는 묶음만 쓰므로 여기서 감싼다.
        groups = {g: {a: (v if isinstance(v, dict) else {"rows": v, "tags": []})
                      for a, v in tab.items()} for g, tab in groups.items()}
        import json
        from core.tag_combo.bank import RecipeBank
        p = tmp_path / "recipe_bank.json"
        p.write_text(json.dumps({"format": "NRB3", "policy": {}, "groups": groups}),
                     encoding="utf-8")
        return RecipeBank(p)

    def test_rejects_unknown_format(self, tmp_path):
        """형식이 바뀌면 조용히 오해하지 말고 즉시 죽어야 한다."""
        import json
        from core.tag_combo.bank import RecipeBank
        p = tmp_path / "recipe_bank.json"
        p.write_text(json.dumps({"format": "NRB2", "groups": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="unknown bank format"):
            RecipeBank(p)

    def test_tags_only_anchor_is_not_abandoned(self, tmp_path):
        """묶음이 없어도 **평면 태그가 있으면 답이다.**

        앵커 선택이 `rows` 만 보던 시절, `rows=[]` 인데 `tags` 는 16개인 앵커가
        4,999개(9.01%) 있었고 전부 기권했다 - `dark background` 가 그 예다.
        `blush` 를 놓쳤던 지명 병목과 같은 모양이다(Codex 지적 2026-08-16).
        """
        b = self._bank(tmp_path, {"1girl_solo": {
            "dark background": {"rows": [],
                                "tags": [{"tag": "glowing", "p": 0.10, "lift": 3.0},
                                         {"tag": "light particles", "p": 0.06, "lift": 4.0}]},
        }})
        r = b.lookup(["dark background"], "1girl_solo")
        assert not r["abstained"], f"평면 태그를 갖고도 기권했다: {r}"
        assert [x["tag"] for x in r["tags"]] == ["glowing", "light particles"]

    def test_rows_anchor_still_wins_over_tags_only(self, tmp_path):
        """묶음이 있는 앵커가 여전히 우선이다 - 기존 출력이 안 바뀌어야 한다."""
        b = self._bank(tmp_path, {"1girl_solo": {
            "dark background": {"rows": [],
                                "tags": [{"tag": "glowing", "p": 0.99, "lift": 3.0}]},
            "maid": {"rows": [{"tags": ["apron"], "support": 99, "coverage": 0.49}],
                     "tags": [{"tag": "apron", "p": 0.66, "lift": 5.0}]},
        }})
        r = b.lookup(["dark background", "maid"], "1girl_solo")
        assert r["anchor"] == "maid", f"평면뿐인 앵커가 묶음 앵커를 이겼다: {r}"

    def test_named_anchor_wins(self, tmp_path):
        """화면이 보고 있는 태그가 기준이다 - 커버리지 자동 선택을 이긴다."""
        b = self._bank(tmp_path, {"1girl_solo": {
            "thick thighs": {"rows": [{"tags": ["thighhighs"], "support": 99,
                                       "coverage": 0.49}],
                             "tags": [{"tag": "thighhighs", "p": 0.32, "lift": 3.0}]},
            "wide hips": {"rows": [], "tags": [{"tag": "thighs", "p": 0.56, "lift": 4.0}]},
        }})
        r = b.lookup(["wide hips", "thick thighs"], "1girl_solo", prefer="wide hips")
        assert r["anchor"] == "wide hips", r

    def test_unknown_named_anchor_abstains_instead_of_answering_about_another_tag(
            self, tmp_path):
        """**모르면 비운다.** 남의 답을 내놓지 않는다.

        예전에는 지정한 앵커가 없으면 조용히 자동 선택으로 돌아갔다. 그러면
        `triple amputee` 를 살펴보는데 카드는 `thick thighs` 를 말한다 - 사용자는
        그 숫자가 지금 보는 태그의 것이라고 읽는다(사용자 지적 2026-08-17).
        """
        b = self._bank(tmp_path, {"1girl_solo": {
            "thick thighs": {"rows": [{"tags": ["thighhighs"], "support": 99,
                                       "coverage": 0.49}],
                             "tags": [{"tag": "thighhighs", "p": 0.32, "lift": 3.0}]},
        }})
        r = b.lookup(["triple amputee", "thick thighs"], "1girl_solo",
                     prefer="triple amputee")
        assert r["abstained"] and not r["tags"] and not r["combos"], r
        assert r["anchor"] == ""

    def test_no_named_anchor_still_auto_selects(self, tmp_path):
        """`prefer` 를 안 준 호출(API 직접 사용)은 예전 그대로다."""
        b = self._bank(tmp_path, {"1girl_solo": {
            "thick thighs": {"rows": [{"tags": ["thighhighs"], "support": 99,
                                       "coverage": 0.49}],
                             "tags": [{"tag": "thighhighs", "p": 0.32, "lift": 3.0}]},
        }})
        r = b.lookup(["triple amputee", "thick thighs"], "1girl_solo")
        assert r["anchor"] == "thick thighs" and not r["abstained"], r

    def test_zero_percent_chips_are_cut(self, tmp_path):
        """`0%` 라고 적힌 칩은 사용자에게 아무 말도 하지 않는다."""
        b = self._bank(tmp_path, {"1girl_solo": {
            "maid": {"rows": [{"tags": ["apron"], "support": 99, "coverage": 0.49}],
                     "tags": [{"tag": "apron", "p": 0.66, "lift": 5.0},
                              {"tag": "dust", "p": 0.004, "lift": 9.0}]},
        }})
        r = b.lookup(["maid"], "1girl_solo")
        assert [x["tag"] for x in r["tags"]] == ["apron"], r["tags"]

    def test_broken_bank_is_loud_but_missing_bank_is_quiet(self, tmp_path):
        """**없는 것**과 **있는데 못 읽는 것**은 다르다.

        둘 다 조용히 None 이면, 형식이 안 맞는 번들을 만나도 아무 말 없이 옛
        온라인 경로로 내려앉는다 - 추천이 니치해지는데 로그 한 줄이 없다.
        """
        import json
        from core.tag_combo.bank import load
        empty = tmp_path / "empty"
        empty.mkdir()
        assert load([empty]) is None, "없는 것에 예외를 올리면 기능이 죽는다"

        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "recipe_bank.json").write_text(
            json.dumps({"format": "NRB2", "groups": {}}), encoding="utf-8")
        with pytest.raises(ValueError, match="unknown bank format"):
            load([broken])

    def test_picks_the_anchor_with_the_best_coverage(self, tmp_path):
        """앵커는 빈도가 아니라 **잘 맞는 것**으로 고른다.

        결합빈도 1위 조합이 최악의 추천을 낸 실측이 있다
        (long hair+blue eyes+large breasts -> flag print, 0.22%).
        """
        b = self._bank(tmp_path, {"1girl_solo": {
            "long hair": [{"tags": ["a", "b"], "support": 9, "coverage": 0.02}],
            "maid": [{"tags": ["apron", "maid headdress"], "support": 99,
                      "coverage": 0.49}],
        }})
        r = b.lookup(["long hair", "maid"], "1girl_solo")
        assert r["anchor"] == "maid"
        assert r["combos"][0]["tags"] == ["apron", "maid headdress"]

    def test_abstains_when_nothing_passes(self, tmp_path):
        """**넓은 seed 에는 흔한 조합이 없다.** 억지로 채우면 니치가 나온다."""
        b = self._bank(tmp_path, {"1girl_solo": {}})
        r = b.lookup(["smile"], "1girl_solo")
        assert r["combos"] == [] and r["abstained"]

    def test_never_recommends_tags_already_in_the_prompt(self, tmp_path):
        b = self._bank(tmp_path, {"1girl_solo": {
            "maid": [{"tags": ["apron", "frills"], "support": 50, "coverage": 0.4},
                     {"tags": ["dress", "ribbon"], "support": 40, "coverage": 0.3}],
        }})
        r = b.lookup(["maid", "apron", "frills"], "1girl_solo")
        assert all(set(c["tags"]) - {"maid", "apron", "frills"} for c in r["combos"])

    def test_rows_do_not_repeat_each_other(self, tmp_path):
        """행 사이 중복이 5행을 2행어치로 만들던 결함(칩 15개 중 고유 9개)."""
        b = self._bank(tmp_path, {"1girl_solo": {
            "x": [{"tags": ["a", "b"], "support": 50, "coverage": 0.4},
                  {"tags": ["a", "b", "c"], "support": 40, "coverage": 0.3},
                  {"tags": ["d", "e"], "support": 30, "coverage": 0.2}],
        }})
        r = b.lookup(["x"], "1girl_solo", top_k=5)
        got = [c["tags"] for c in r["combos"]]
        assert ["a", "b", "c"] not in got, "앞 행과 2개 겹치는 행이 남았다"
        assert ["d", "e"] in got

    def test_missing_group_is_reported_not_silently_answered(self, tmp_path):
        """뱅크에 없는 그룹은 **오류로 드러낸다.**

        옛 계약은 "부분 빌드에서 안 구운 그룹은 온라인 폴백" 이었다. 그런데 그
        테스트는 `recommend()` 를 **호출조차 하지 않고** 뱅크 내부만 봤다 - 계약을
        건 척했을 뿐이다(Codex 지적 2026-08-17). 지금은 배포에 모델이 안 가므로
        폴백 대상도 없다.
        """
        from core.tag_combo.service import ComboService
        self._bank(tmp_path, {"1girl_solo": {"maid": [
            {"tags": ["apron"], "support": 9, "coverage": 0.4}]}})
        svc = ComboService(tmp_path, search_dirs=[tmp_path])
        assert svc.bank() is not None
        assert not svc.bank().anchors("2girls"), "빈 그룹이 앵커를 들고 있다"
        # **여기까지가 예전 테스트였다.** 실제 호출을 걸어야 계약이다.
        r = svc.recommend(["maid"], group="2girls", anchor="maid")
        assert r.get("error") == "bank group missing", r
        assert not r.get("tags") and not r.get("combos")
        assert r.get("bankGroups") == ["1girl_solo"], r
        # 있는 그룹은 정상으로 답한다.
        ok = svc.recommend(["maid"], group="1girl_solo", anchor="maid")
        assert ok.get("source") == "bank" and not ok.get("error"), ok
