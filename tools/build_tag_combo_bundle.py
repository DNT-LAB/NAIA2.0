# -*- coding: utf-8 -*-
"""느슨한 모델들을 배포용 단일 파일 `data/tag_combo/tag_combo.ncsb` 로 묶는다.

배포판은 Interactive 를 처음 열 때 이 파일 하나를 내려받는다. 추출 단계가 없다 -
받은 파일을 그대로 열고, 실제로 쓰는 인원 그룹만 메모리로 푼다.

    python tools/build_tag_combo_bundle.py
    python tools/build_tag_combo_bundle.py --out dist/tag_combo.ncsb --verify
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tag_combo.bundle import ComboBundle, write_bundle   # noqa: E402
from core.tag_combo.download import (                         # noqa: E402
    BUNDLE_BYTES, BUNDLE_NAME, BUNDLE_SHA256)
from core.tag_combo.person import PERSON_GROUPS               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "tag_combo"


def main() -> int:
    ap = argparse.ArgumentParser(description="조합 모델 단일 번들 생성")
    # 배포되는 번들의 이름은 core/tag_combo/download.py 가 정한다. 기본값이 달라서
    # 실수로 `tag_combo.ncsb` 를 올리면 런타임이 영영 못 찾는다.
    ap.add_argument("--out", default=str(D / BUNDLE_NAME))
    ap.add_argument("--verify", action="store_true",
                    help="쓴 뒤 전 그룹을 다시 읽어 sha256 을 대조한다")
    ap.add_argument("--built", default="",
                    help="인덱스에 넣을 빌드 스탬프. 비우면 현재 시각이 들어가 **같은 "
                         "입력으로 다시 구워도 sha 가 달라진다**. 배포용은 고정값을 줘라")
    ap.add_argument("--allow-partial", action="store_true",
                    help="13그룹이 안 차도 진행한다(디버깅용, 배포 금지)")
    args = ap.parse_args()

    models = [D / f"{g}.ncsr" for g in PERSON_GROUPS if (D / f"{g}.ncsr").exists()]
    if not models:
        print(f"!! 모델이 없다: {D} - tools/build_tag_combo_models.py 먼저")
        return 2
    missing = [g for g in PERSON_GROUPS if not (D / f"{g}.ncsr").exists()]
    if missing and not args.allow_partial:
        # **부분 번들을 조용히 만들면 안 된다.** 런타임은 인덱스에 이름이 있는
        # 그룹만 열 수 있어서, 빠진 그룹은 사용자가 인원 수를 바꾸는 순간에야
        # 드러난다. 그때는 이미 배포된 뒤다.
        print(f"!! 그룹 {len(missing)}개가 없다: {missing}")
        print("   전부 구운 뒤 다시 실행하라. 정말 부분 번들이 필요하면 --allow-partial")
        return 2
    if missing:
        print(f"   (빠진 그룹 {len(missing)}개: {missing}) - 배포하지 마라")

    # 부속 자산은 **모델과 같은 파일**에 넣는다. 따로 배포하면 "레시피는 새 것인데
    # 모델은 옛 것" 인 조합이 생기고, 그건 사용자가 알아챌 방법이 없다.
    aux = {}
    for name in ("recipe_bank", "semantic_graph", "anchor_feature_marginals"):
        p = D / f"{name}.json"
        if p.exists():
            aux[name] = p
        else:
            print(f"   (부속 없음: {name}.json)")
    if aux:
        print(f"   부속 자산 {len(aux)}개: {', '.join(sorted(aux))}")

    t0 = time.time()
    info = write_bundle(Path(args.out), models, source="data/tags/*.parquet",
                        aux=aux, built=args.built)
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

    # 배포 상수를 **여기서 뱉는다.** 안 고치면 신규 설치는 179MB 를 받아놓고
    # sha256 불일치로 통째로 버리고, 기존 설치는 파일이 있다는 이유로 옛 번들을
    # 계속 쓴다 - 양쪽 다 조용히 틀린다.
    p = Path(args.out)
    digest = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    got, size = digest.hexdigest(), p.stat().st_size
    same = got == BUNDLE_SHA256 and size == BUNDLE_BYTES
    print("\n--- core/tag_combo/download.py 에 반영할 상수 ---")
    print(f'BUNDLE_SHA256 = "{got}"')
    print(f"BUNDLE_BYTES = {size:_}")
    print("현재 코드와 " + ("일치한다 - 고칠 것 없음" if same else
                            "다르다 !! 위 두 줄로 바꾸고 업로드하라"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
