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

from core.tag_combo.bundle import (                           # noqa: E402
    REQUIRED_AUX, ComboBundle, check_bank_blob, write_bundle)
from core.tag_combo.download import (                         # noqa: E402
    BUNDLE_BYTES, BUNDLE_NAME, BUNDLE_SHA256)
from core.tag_combo.person import PERSON_GROUPS               # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "data" / "tag_combo"


def _check_bank_groups(bank_path: Path) -> int:
    """aux-only 번들은 뱅크가 유일한 답이다 - 13그룹을 여기서 강제한다.

    배포에 모델이 없으면 온라인 폴백도 없다. 뱅크에 없는 인원 그룹은 통째로
    죽는데, 사용자는 인원 수를 바꾸는 순간에야 안다. 그때는 이미 배포된 뒤다.

    ⚠️ 판정은 `core.tag_combo.bundle.check_bank_blob` **하나**로 한다. 여기서
    따로 검사하면 런타임과 강도가 갈린다(Codex 지적 2026-08-17).
    """
    try:
        d = check_bank_blob(bank_path.read_bytes())
    except (OSError, ValueError) as exc:
        print(f"!! 뱅크를 쓸 수 없다: {exc}")
        print("   python tools/build_recipe_bank.py 를 13그룹으로 다시 돌려라")
        return 2
    groups = d.get("groups") or {}
    tot = sum(len(v or {}) for v in groups.values())
    print(f"   뱅크 {len(groups)}그룹 · 앵커 {tot:,}")
    return 0


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
    ap.add_argument("--aux-only", action="store_true",
                    help="그룹 모델을 넣지 않고 부속 자산만 굽는다. **배포 기본값**이다 "
                         "- 화면 추천은 전적으로 레시피 뱅크에서 나오고, 모델은 "
                         "개발 머신에서 뱅크를 캐는 데만 쓴다. 실측 203MB -> 15MB")
    args = ap.parse_args()

    models = [D / f"{g}.ncsr" for g in PERSON_GROUPS if (D / f"{g}.ncsr").exists()]
    if args.aux_only:
        # 모델을 넣지 않는다. 대신 **뱅크가 13그룹을 다 갖췄는지**를 여기서 본다 -
        # 배포에 모델이 없으면 온라인 폴백도 없으므로, 빠진 인원 그룹은 통째로
        # 죽는다. 그 검사가 아래 `_check_bank_groups` 다.
        models = []
    elif not models:
        print(f"!! 모델이 없다: {D} - tools/build_tag_combo_models.py 먼저")
        return 2
    missing = [] if args.aux_only else [
        g for g in PERSON_GROUPS if not (D / f"{g}.ncsr").exists()]
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
    for name in REQUIRED_AUX:
        p = D / f"{name}.json"
        if p.exists():
            aux[name] = p
        else:
            print(f"   (부속 없음: {name}.json)")
    if aux:
        print(f"   부속 자산 {len(aux)}개: {', '.join(sorted(aux))}")
    # aux-only 번들은 부속이 곧 내용이다. 하나라도 없으면 굽지 않는다.
    if args.aux_only:
        gone = [n for n in REQUIRED_AUX if n not in aux]
        if gone:
            print(f"!! 필수 부속이 없다: {gone}")
            return 2
        rc = _check_bank_groups(aux["recipe_bank"])
        if rc:
            return rc

    t0 = time.time()
    info = write_bundle(Path(args.out), models, source="data/tags/*.parquet",
                        aux=aux, built=args.built)
    el = time.time() - t0
    raw, out = info["rawBytes"], info["bytes"]
    # aux-only 는 `rawBytes` 가 0 이다(그룹이 없다) - 압축률을 못 낸다.
    ratio = f"{out/raw:.0%}" if raw else "n/a"
    print(f"번들 {info['groups']}그룹 · 원본 {raw/1e6:.0f}MB -> {out/1e6:.1f}MB "
          f"({ratio}) · {el:.0f}s")
    print(f"저장: {info['path']}")

    # aux-only 는 **항상** 검증한다. 선택 옵션으로 두면 재독해 없이 sha 상수를
    # 뱉을 수 있고, 그 sha 로 올린 파일이 깨져 있을 수 있다(Codex 지적).
    if args.verify or args.aux_only:
        t0 = time.time()
        b = ComboBundle(Path(args.out))
        for g in b.groups():
            meta, body = b.read(g)          # sha256 대조가 read 안에 있다
            assert int(meta["nnz"]) > 0 and len(body) > 0
        # **부속까지 본다.** aux-only 번들은 그룹이 0개라, 그룹만 돌면 검증이
        # 아무것도 보지 않고 통과한다.
        bad = b.verify_all()
        if bad:
            print(f"!! 검증 실패: {bad}")
            return 2
        print(f"검증 {len(b.groups())}그룹 + 부속 {len(REQUIRED_AUX)}종 전부 통과 "
              f"({time.time()-t0:.0f}s)")

    # 배포 상수를 **여기서 뱉는다.** 안 고치면 신규 설치는 번들을 받아놓고
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
