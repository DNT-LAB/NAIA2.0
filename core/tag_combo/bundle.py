# -*- coding: utf-8 -*-
"""`NCSB1` — 인원 그룹 모델 13개를 파일 하나로 묶는다.

## 왜

배포판은 이 데이터를 **런타임에 내려받는다**(저장소 관례: `RuntimeInstallManager`
+ `ArchiveSpec`). 그런데 느슨한 형태는 26개 파일 / 364MB 라 배포에 불편하다.

세 방식을 재고 골랐다(실측):

    A 무압축 단일 컨테이너   다운로드 364MB · 디스크 364MB · 적재 375ms(mmap)
    B 그룹별 압축 컨테이너   다운로드 200MB · 디스크 200MB · 적재 +0.5s   <- 채택
    C zip 26파일            다운로드 200MB · 디스크 364MB · 추출 단계 필요

압축률 실측: `.ncsr` deflate-6 이 56%, 사이드카 JSON 이 22%.
B 를 고른 이유는 **추출 단계가 없다**는 것이다 - 받은 파일을 그대로 열고, 실제로
쓰는 그룹만 메모리로 푼다. 어차피 모델은 상주시키므로(1girl_solo 161MB) mmap
이점이 크지 않다.

## 포맷

    magic  8B   b"NCSB1\\0\\0\\0"
    ilen   u32  인덱스 JSON 길이
    index  ilen JSON: {"version":1, "groups":[{...}], "built":"...", "source":"..."}
    payloads   인덱스가 가리키는 오프셋에 그룹별로
                 meta   deflate(JSON utf-8)
                 body   deflate(.ncsr 원본)

그룹 항목: name · metaOff/metaLen/metaRaw · bodyOff/bodyLen/bodyRaw ·
           sha256(body 원본) · posts/vocab/nnz(다운로드 전 표시용)

## 느슨한 형태도 계속 지원한다

개발 중에는 `data/tag_combo/*.ncsr` 을 그대로 쓴다. 번들을 만들어야만 돌아가면
빌드-검증 순환이 느려진다. `ComboModel` 이 둘 다 연다.
"""

from __future__ import annotations

import hashlib
import json
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"NCSB1\0\0\0"
LEVEL = 6      # 실측 deflate-6 이 56% / 2초, 9는 55% / 11초 - 6이 맞다


@dataclass(frozen=True)
class BundleEntry:
    name: str
    meta_off: int
    meta_len: int
    body_off: int
    body_len: int
    body_raw: int
    sha256: str
    posts: int
    vocab: int
    nnz: int


class ComboBundle:
    """번들 읽기. 인덱스만 먼저 읽고 payload 는 요청할 때 푼다."""

    def __init__(self, path: Path):
        self.path = Path(path)
        with self.path.open("rb") as fh:
            magic = fh.read(len(MAGIC))
            if magic != MAGIC:
                raise ValueError(f"번들 매직이 다르다: {magic!r} - {self.path}")
            (ilen,) = struct.unpack("<I", fh.read(4))
            self.index = json.loads(fh.read(ilen).decode("utf-8"))
        self.entries: dict[str, BundleEntry] = {
            g["name"]: BundleEntry(**g) for g in self.index["groups"]
        }

    def groups(self) -> list[str]:
        return [g["name"] for g in self.index["groups"]]

    def total_bytes(self) -> int:
        return self.path.stat().st_size

    def verify_all(self) -> list[str]:
        """전 그룹의 sha256 을 대조하고 깨진 그룹 이름을 돌려준다.

        `read()` 는 **읽는 그룹만** 검증한다. 그건 평소엔 맞지만 다운로드 직후엔
        부족하다 - 안 쓰는 그룹이 깨진 채 남아 있다가 인원 수를 바꾸는 순간
        터진다. 설치 단계에서 한 번 이걸 돌린다(실측 13그룹 2초).
        """
        bad: list[str] = []
        for g in self.groups():
            try:
                self.read(g, verify=True)
            except (OSError, ValueError, KeyError, zlib.error):
                bad.append(g)
        return bad

    def read(self, group: str, *, verify: bool = True) -> tuple[dict, bytes]:
        """(meta, .ncsr 원본 바이트). 손상은 여기서 잡는다 - 다운로드 산물이다."""
        e = self.entries.get(group)
        if e is None:
            raise KeyError(f"번들에 없는 그룹: {group}")
        with self.path.open("rb") as fh:
            fh.seek(e.meta_off)
            meta = json.loads(zlib.decompress(fh.read(e.meta_len)).decode("utf-8"))
            fh.seek(e.body_off)
            body = zlib.decompress(fh.read(e.body_len))
        if len(body) != e.body_raw:
            raise ValueError(f"{group}: 길이가 다르다 {len(body)} != {e.body_raw}")
        if verify:
            got = hashlib.sha256(body).hexdigest()
            if got != e.sha256:
                raise ValueError(f"{group}: sha256 불일치 - 다운로드가 깨졌다")
        return meta, body


def write_bundle(out: Path, models: list[Path], *, source: str = "") -> dict:
    """느슨한 `.ncsr` + `.json` 들을 번들 하나로 묶는다."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payloads: list[tuple[str, bytes, bytes, dict]] = []
    for p in models:
        p = Path(p)
        meta = json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
        body = p.read_bytes()
        payloads.append((p.stem,
                         zlib.compress(json.dumps(meta, ensure_ascii=False)
                                       .encode("utf-8"), LEVEL),
                         zlib.compress(body, LEVEL),
                         {"meta": meta, "sha": hashlib.sha256(body).hexdigest(),
                          "raw": len(body)}))

    # 인덱스 길이가 오프셋에 영향을 주므로 두 번 만든다. 자리표시자를 실제와
    # 같은 자릿수로 채우면 한 번에 되지만, 그런 요령은 나중에 조용히 깨진다.
    def build(offsets: list[tuple[int, int]]) -> bytes:
        groups = []
        for (name, mz, bz, info), (moff, boff) in zip(payloads, offsets):
            m = info["meta"]
            groups.append({
                "name": name, "meta_off": moff, "meta_len": len(mz),
                "body_off": boff, "body_len": len(bz), "body_raw": info["raw"],
                "sha256": info["sha"], "posts": int(m["posts"]),
                "vocab": int(m["vocab"]), "nnz": int(m["nnz"]),
            })
        return json.dumps({"version": 1, "source": source,
                           "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "groups": groups}, ensure_ascii=False).encode("utf-8")

    zero = [(0, 0)] * len(payloads)
    head = len(MAGIC) + 4 + len(build(zero))
    offsets, cur = [], head
    for _, mz, bz, _ in payloads:
        offsets.append((cur, cur + len(mz)))
        cur += len(mz) + len(bz)
    index = build(offsets)
    # 인덱스 길이가 바뀌면 오프셋이 밀린다. 같아질 때까지 다시 잡는다.
    while len(MAGIC) + 4 + len(index) != head:
        head = len(MAGIC) + 4 + len(index)
        offsets, cur = [], head
        for _, mz, bz, _ in payloads:
            offsets.append((cur, cur + len(mz)))
            cur += len(mz) + len(bz)
        index = build(offsets)

    with out.open("wb") as fh:
        fh.write(MAGIC)
        fh.write(struct.pack("<I", len(index)))
        fh.write(index)
        for _, mz, bz, _ in payloads:
            fh.write(mz)
            fh.write(bz)
    raw = sum(i["raw"] for _, _, _, i in payloads)
    return {"path": str(out), "groups": len(payloads), "bytes": out.stat().st_size,
            "rawBytes": raw}
