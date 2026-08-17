# -*- coding: utf-8 -*-
"""인원 그룹 모델의 디스크 포맷(`NCSR1`)과 적재.

## 왜 이 포맷인가 (실측 근거는 tools/reco_probe/SPEC.md 5.8)

기존 Quick Search 의 `.tgp` 는 LZMA+pickle 이라 적재에 2.42~2.54초를 쓰고,
같은 데이터를 **두 번**(행 우선 CSR + 역인덱스) 담아 45MB 파일이 150MB 로 부푼다.
그리고 `uint16` 태그 id 라 65,536 이 구조적 상한인데 어디에도 적혀 있지 않다.

여기서는:
  - 압축하지 않는다. mmap 으로 열고 섹션만 잘라 쓴다.
  - **행 우선 CSR 만 저장한다.** 역인덱스는 적재 시 SciPy CSR->CSC 로 만든다
    (실측 134.7ms). 저장하면 731k 모델이 50MB -> 145MB 로 세 배가 된다.
  - 태그 id 는 그룹 지역(local) `uint16` 이지만, **어휘 상한을 헤더에 적고
    빌더가 검사한다.** 실측 최대 어휘는 1girl_solo 의 23,122 개다.
  - 문자열은 모델마다 복제하지 않는다. 지역 id -> 전역 id 표만 담고 문자열은
    전역 어휘 파일 하나에 둔다.

## ⚠️ unstable argsort 를 쓰지 마라

역인덱스를 `np.argsort(kind=None)` 으로 만들면 같은 태그 안에서 게시물 id 가
정렬되지 않는다 - 실측 정렬 위반 11,806,424건. 그 상태로
`np.intersect1d(..., assume_unique=True)` 를 부르면 **조용히 틀린 답**이 나온다.
그래서 CSR->CSC 변환을 쓴다(선형이고 정렬을 보장한다).
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAGIC = b"NCSR1"
# uint16 지역 id 의 상한. 실측 최대는 1girl_solo 23,122 이므로 여유가 크지만,
# `.tgp` 가 이 상한을 문서화하지 않아 사고가 났던 전례가 있어 명시한다.
MAX_LOCAL_VOCAB = 65_535

_HEADER = struct.Struct("<5sBHIIIQQQQQQ")
#                        magic ver flags posts vocab nnz  + 6개 섹션 오프셋


@dataclass(frozen=True)
class ModelHeader:
    version: int
    posts: int
    vocab: int
    nnz: int
    group: str
    source_hash: str
    sampled_from: int
    ratings: tuple[int, int, int, int]


class ComboModel:
    """한 인원 그룹의 조합 모델. mmap 으로 열고 역인덱스만 만든다."""

    def __init__(self, path: Path, *, meta: dict | None = None,
                 blob: bytes | None = None):
        """느슨한 파일과 번들 양쪽을 연다.

        개발 중에는 `data/tag_combo/*.ncsr` 을 그대로 쓴다 - 번들을 만들어야만
        돌아가면 빌드-검증 순환이 느려진다. 배포판은 번들에서 꺼낸 (meta, blob)
        을 그대로 넘긴다(`core/tag_combo/bundle.py`).
        """
        self.path = Path(path)
        if meta is None:
            meta_path = self.path.with_suffix(".json")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.meta = meta
        self.header = ModelHeader(
            version=int(self.meta["version"]),
            posts=int(self.meta["posts"]),
            vocab=int(self.meta["vocab"]),
            nnz=int(self.meta["nnz"]),
            group=str(self.meta["group"]),
            source_hash=str(self.meta.get("sourceHash", "")),
            sampled_from=int(self.meta.get("sampledFrom", self.meta["posts"])),
            ratings=tuple(self.meta.get("ratings", [0, 0, 0, 0])),  # type: ignore[arg-type]
        )
        self.tags: list[str] = list(self.meta["tags"])
        self.tag_to_id: dict[str, int] = {t: i for i, t in enumerate(self.tags)}
        self.freq = np.asarray(self.meta["freq"], dtype=np.int64)
        n = self.header.posts
        v = self.header.vocab
        nnz = self.header.nnz

        # 번들에서 왔으면 이미 메모리에 있다. 느슨한 파일이면 mmap 한다.
        blob = (np.frombuffer(blob, dtype=np.uint8) if blob is not None
                else np.memmap(self.path, dtype=np.uint8, mode="r"))
        off = 0

        def take(count: int, dtype) -> np.ndarray:
            nonlocal off
            width = np.dtype(dtype).itemsize
            arr = np.frombuffer(blob, dtype=dtype, count=count, offset=off)
            off += count * width
            return arr

        magic = bytes(blob[:len(MAGIC)])
        if magic != MAGIC:
            raise ValueError(f"매직이 다르다: {magic!r} (기대 {MAGIC!r}) - {self.path}")
        off = 8   # 매직 5 + 버전 1 + 패딩 2
        self.indptr = take(n + 1, np.int64)
        self.indices = take(nnz, np.uint16)
        self.post_rating = take(n, np.uint8)
        # 게시물의 대표 캐릭터 id(0 = 없음). 캐릭터 집중도를 **질의 시점에**
        # 매칭 집합 위에서 정확히 계산하기 위한 것이다. 반증 실험 8.2 에서
        # 우위의 41%가 캐릭터 의상 암기였으므로 이 필터는 선택이 아니다.
        # 4바이트 x 80만 = 3.2MB 로 싸다.
        self.post_char = take(n, np.uint32)
        self.tag_rating = take(v * 4, np.uint32).reshape(v, 4)

        self._inv_posts: np.ndarray | None = None
        self._bounds: np.ndarray | None = None
        # 헤드 컨텍스트 캐시. 매칭이 큰 단독 태그(실측 경계 5,000건)는 질의 시점
        # 계산이 초 단위가 된다 - `looking at viewer` 494,399건에 5.6초. 그런 태그는
        # freq>=5000 기준 662개뿐이라 전량 계산 결과를 통째로 담아도 작다.
        # 표본추출로 때우면 답이 망가진다(query.Policy.scan_cap 주석 참조).
        self._head: dict[str, dict] = self.meta.get("head") or {}
        # 함의 인접표. 질의 시점에 계산하면 실측 10~20배가 된다
        # (`sword` 19ms -> 1,440ms). tools/build_tag_combo_implications.py 가 굽는다.
        self.implies: dict[str, frozenset[str]] = {
            k: frozenset(v) for k, v in (self.meta.get("implies") or {}).items()
        }

    # ---- 역인덱스 ------------------------------------------------------
    def ensure_inverted(self) -> None:
        """열 우선 표를 만든다. 저장하지 않고 적재 시 만든다(포맷 주석 참조)."""
        if self._inv_posts is not None:
            return
        from scipy import sparse

        n, v = self.header.posts, self.header.vocab
        csr = sparse.csr_matrix(
            (np.ones(self.header.nnz, dtype=np.int8),
             self.indices.astype(np.int32), self.indptr),
            shape=(n, v))
        csc = csr.tocsc()
        # tocsc 는 각 열의 행 인덱스를 오름차순으로 낸다. assume_unique=True 를
        # 쓰려면 이 성질이 반드시 필요하다.
        self._inv_posts = csc.indices.astype(np.int32, copy=False)
        self._bounds = csc.indptr.astype(np.int64, copy=False)

    def postings(self, tag: str) -> np.ndarray | None:
        i = self.tag_to_id.get(tag)
        if i is None:
            return None
        self.ensure_inverted()
        assert self._inv_posts is not None and self._bounds is not None
        return self._inv_posts[self._bounds[i]:self._bounds[i + 1]]

    def row(self, post: int) -> np.ndarray:
        return self.indices[self.indptr[post]:self.indptr[post + 1]]

    def tag_counts(self, posts: np.ndarray, *, chunk: int = 50_000) -> np.ndarray:
        """주어진 게시물들에서 각 태그가 몇 번 나오는지. 길이 = vocab.

        ⚠️ **한 번에 이어 붙이지 않는다.** 원래 두 빌더가 똑같이
        `np.bincount(np.concatenate([ix[s:e] for s, e in ...]).astype(np.int64))`
        를 썼다. 80만 표본에서는 견뎠지만 전 코퍼스에서는 앵커 하나가 통째로
        메모리를 먹는다 - `looking at viewer` 는 게시물 2,431,879개에 태그 ID
        81,415,731개라, view 헤더 272MB + uint16 163MB + **int64 사본 651MB**
        로 일시 피크가 약 1.1GB 다(Codex 실측 2026-08-17).

        청크로 나눠 누적하면 총 연산량은 같고 피크만 묶인다. 같은 문제를
        `core/event_corpus_search_service.py:179` 가 이미 이렇게 풀었다.
        """
        # 0 이면 range 가 죽고, 음수면 루프를 한 번도 안 돌아 **조용히 0 을**
        # 돌려준다. 잘못된 청크 크기로 틀린 답을 내는 것보다 크기를 바로잡는
        # 편이 낫다(Codex 경계 시험).
        chunk = max(1, int(chunk))
        out = np.zeros(self.header.vocab, dtype=np.int64)
        p = np.asarray(posts)
        if p.size == 0:
            return out.astype(np.int32)
        ip, ix = self.indptr, self.indices
        for beg in range(0, int(p.size), chunk):
            part = p[beg:beg + chunk]
            starts = ip[part].astype(np.int64)
            lens = (ip[part + 1] - ip[part]).astype(np.int64)
            total = int(lens.sum())
            if total == 0:
                continue
            # 게시물별 시작점을 펼쳐 한 번의 fancy-index 로 모은다.
            offs = np.repeat(starts - np.concatenate(([0], np.cumsum(lens)[:-1])), lens)
            gathered = ix[offs + np.arange(total, dtype=np.int64)]
            # `minlength` 는 하한이라, tag id 가 조밀하지 않으면 결과가 더 길어진다.
            out += np.bincount(gathered, minlength=self.header.vocab)[:self.header.vocab]
        return out.astype(np.int32)

    # ---- 헤드 컨텍스트 --------------------------------------------------
    def head_combos(self, tag: str) -> list[tuple[list[str], int]] | None:
        """사전계산된 조합. 없으면 None(질의 시점 계산으로 넘어간다)."""
        rec = self._head.get(tag)
        if not rec:
            return None
        return [(list(t), int(n)) for t, n in rec.get("combos", ())]

    def head_matched(self, tag: str) -> int:
        rec = self._head.get(tag)
        return int(rec.get("matched", 0)) if rec else 0

    @property
    def nbytes(self) -> int:
        """상주 바이트. **모든 섹션을 센다.**

        처음에 `post_char` 를 빼먹어 실측 두 모델에서 6,074,200 바이트를 과소
        계상했다(Codex 게이트). LRU 가 이 값으로 예산을 재므로 빠지면 그만큼
        더 얹힌다.
        """
        base = (self.indptr.nbytes + self.indices.nbytes
                + self.post_rating.nbytes + self.post_char.nbytes
                + self.tag_rating.nbytes)
        if self._inv_posts is not None and self._bounds is not None:
            base += self._inv_posts.nbytes + self._bounds.nbytes
        return base

    @property
    def projected_bytes(self) -> int:
        """역인덱스까지 만들었을 때의 상주 추정. LRU 가 **적재 전에** 쓴다.

        `nbytes` 는 아직 안 만든 역인덱스를 안 센다. 그걸로 예산을 재면 새 모델이
        얼마나 커질지 모른 채 자리를 비우게 된다 - 실측으로 161MB 모델 두 개가
        같이 올라가 RSS 544MB 를 찍었다.
        역인덱스는 posts(int32 nnz) + bounds(int64 vocab+1) 이다.
        """
        inv = self.header.nnz * 4 + (self.header.vocab + 1) * 8
        if self._inv_posts is not None:
            return self.nbytes
        return self.nbytes + inv

    @staticmethod
    def size_from_meta(meta: dict) -> int:
        n, v, nnz = int(meta["posts"]), int(meta["vocab"]), int(meta["nnz"])
        return ((n + 1) * 8 + nnz * 2 + n * 1 + n * 4 + v * 16
                + nnz * 4 + (v + 1) * 8)

    @staticmethod
    def peek_bytes(path: Path) -> int:
        """파일을 열지 않고 사이드카만 읽어 상주 크기를 추정한다."""
        return ComboModel.size_from_meta(
            json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8")))


def write_model(path: Path, *, group: str, rows: list[list[int]], tags: list[str],
                freq: list[int], post_rating: list[int], post_char: list[int],
                tag_rating: np.ndarray, sampled_from: int,
                source_hash: str = "", head: dict | None = None) -> dict:
    """모델 한 벌을 쓴다. 반환값은 메타(호출부가 로그로 쓴다)."""
    if len(tags) > MAX_LOCAL_VOCAB:
        raise ValueError(f"어휘 {len(tags)} 가 uint16 상한 {MAX_LOCAL_VOCAB} 을 넘는다")
    n = len(rows)
    indptr = np.zeros(n + 1, dtype=np.int64)
    flat: list[int] = []
    for i, r in enumerate(rows):
        flat.extend(r)
        indptr[i + 1] = len(flat)
    indices = np.asarray(flat, dtype=np.uint16)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(MAGIC)
        fh.write(bytes([1]))
        fh.write(b"\0\0")           # 8바이트 경계 정렬
        fh.write(indptr.tobytes())
        fh.write(indices.tobytes())
        fh.write(np.asarray(post_rating, dtype=np.uint8).tobytes())
        fh.write(np.asarray(post_char, dtype=np.uint32).tobytes())
        fh.write(np.asarray(tag_rating, dtype=np.uint32).tobytes())

    ratings = [0, 0, 0, 0]
    for r in post_rating:
        if 0 <= r < 4:
            ratings[r] += 1
    meta = {
        "version": 1, "group": group, "posts": n, "vocab": len(tags),
        "nnz": int(len(indices)), "sampledFrom": sampled_from,
        "ratings": ratings, "sourceHash": source_hash,
        "tags": tags, "freq": freq, "head": head or {},
    }
    path.with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta
