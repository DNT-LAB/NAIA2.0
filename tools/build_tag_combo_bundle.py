# -*- coding: utf-8 -*-
"""느슨한 모델들을 배포용 단일 파일 `data/tag_combo/tag_combo.ncsb` 로 묶는다.

배포판은 Interactive 를 처음 열 때 이 파일 하나를 내려받는다. 추출 단계가 없다 -
받은 파일을 그대로 열고, 실제로 쓰는 인원 그룹만 메모리로 푼다.

    python tools/build_tag_combo_bundle.py
    python tools/build_tag_combo_bundle.py --out dist/tag_combo.ncsb --verify
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tag_combo.bundle import ComboBundle, write_bundle   # noqa: E402
from core.tag_combo.person import PERSON_GROUPS               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "tag_combo"


def main() -> int:
    ap = argparse.ArgumentParser(description="조합 모델 단일 번들 생성")
    ap.add_argument("--out", default=str(D / "tag_combo.ncsb"))
    ap.add_argument("--verify", action="store_true",
                    help="쓴 뒤 전 그룹을 다시 읽어 sha256 을 대조한다")
    args = ap.parse_args()

    models = [D / f"{g}.ncsr" for g in PERSON_GROUPS if (D / f"{g}.ncsr").exists()]
    if not models:
        print(f"!! 모델이 없다: {D} - tools/build_tag_combo_models.py 먼저")
        return 2
    missing = [g for g in PERSON_GROUPS if not (D / f"{g}.ncsr").exists()]
    if missing:
        print(f"   (빠진 그룹 {len(missing)}개: {missing})")

    t0 = time.time()
    info = write_bundle(Path(args.out), models, source="data/tags/*.parquet")
    el = time.time() - t0
    raw, out = info["rawBytes"], info["bytes"]
    print(f"번들 {info['groups']}그룹 · 원본 {raw/1e6:.0f}MB -> {out/1e6:.0f}MB "
          f"({out/raw:.0%}) · {el:.0f}s")
    print(f"저장: {info['path']}")

    if args.verify:
        t0 = time.time()
        b = ComboBundle(Path(args.out))
        for g in b.groups():
            meta, body = b.read(g)          # sha256 대조가 read 안에 있다
            assert int(meta["nnz"]) > 0 and len(body) > 0
        print(f"검증 {len(b.groups())}그룹 전부 통과 ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
