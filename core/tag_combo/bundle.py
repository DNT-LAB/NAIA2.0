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
import math
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"NCSB1\0\0\0"
# 부속 자산(레시피 뱅크·의미 그래프)이 붙으면 index 의 version 이 2 가 된다.
# 매직은 바꾸지 않는다 - 바꾸면 옛 판독기가 "형식이 다르다" 로 죽는데, 실제로는
# groups 만 읽으면 그대로 동작한다. 앞으로 나올 판독기를 위해 목록으로 둔다.
ACCEPT_MAGIC = (MAGIC,)
LEVEL = 6      # 실측 deflate-6 이 56% / 2초, 9는 55% / 11초 - 6이 맞다

# **배포 번들의 내용 그 자체.** 모델을 빼고 부속만 배포하므로(203MB -> 15MB),
# 이 셋 중 하나라도 깨지면 기능이 통째로 죽는다. `verify_all` 과 번들 빌더가
# 같은 목록을 본다 - 둘이 갈리면 빌더가 통과시킨 것을 런타임이 거부한다.
REQUIRED_AUX = ("recipe_bank", "semantic_graph", "anchor_feature_marginals")
# 뱅크 형식. `core/tag_combo/bank.py` 와 같은 값이어야 한다. 여기서 한 번 더
# 보는 이유는 **다운로드 직후** 걸러내야 하기 때문이다 - 그때 못 잡으면 옛
# 형식 번들이 정식 이름을 달고 설치되고, 서비스는 조용히 뱅크 없이 돈다.
BANK_FORMAT = "NRB3"


def _entry_answerable(e) -> bool:
    """이 앵커 엔트리로 **실제로 답할 수 있는가.**

    ⚠️ 컨테이너의 truthiness 로는 부족하다 - `rows: [{}]` 와 `tags: [{}]` 가
    통과했다(Codex 2차 지적 2026-08-17). `bank.lookup` 은 줄에서 `r["tags"]` 를
    직접 읽고 화면 칩은 `x["tag"]` 로 그린다. 그 필드가 있어야 답이 나온다.

    ⚠️ **이름만 보면 또 샌다.** 처음엔 `rows[].tags` 와 `tags[].tag` 만 봤는데,
    `lookup` 은 앵커를 고를 때 `rows[0]["coverage"]` / `tags[0]["p"]` 를 **직접
    인덱스**한다 - 그래서 숫자 없는 엔트리는 검증을 통과하고 `ready()` 도 참인데
    조회가 `KeyError` 로 죽었다(Codex 3차 실증 2026-08-17). 답할 수 있다는 말은
    **화면에 숫자를 띄울 수 있다**는 뜻까지 포함한다.
    """
    if not isinstance(e, dict):
        return False

    def _num(v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    for r in (e.get("rows") or []):
        if isinstance(r, dict) and (r.get("tags") or []) and _num(r.get("coverage")):
            return True
    for x in (e.get("tags") or []):
        if isinstance(x, dict) and str(x.get("tag") or "").strip() and _num(x.get("p")):
            return True
    return False


def _entry_wellformed(e) -> list[str]:
    """엔트리의 **모든** 항목이 런타임이 읽는 모양인가. 아니면 어긴 이유들.

    ⚠️ `_entry_answerable` 은 "하나라도 쓸 수 있으면" 통과다. 그런데 런타임은
    목록을 **전부** 소비한다 - 멀쩡한 첫 줄 뒤에 망가진 형제 줄이 있으면 게이트는
    통과하고 조회는 죽는다(Codex 4차 실증: `valid_sibling_masks_bad_first GATE
    PASS CRASH TypeError`). 그래서 배포 게이트는 전수로 본다.
    """
    def _num(v, lo=None, hi=None) -> bool:
        """유한한 수인가(선택적으로 범위까지).

        ⚠️ **`int` 를 `math.isfinite` 에 넘기지 마라.** JSON 정수는 임의 정밀도라
        `10**1000` 이 들어오면 float 변환에서 `OverflowError` 가 난다 - 그러면
        "불량 입력은 ValueError" 라는 이 게이트의 계약이 깨지고, `verify_all` 은
        목록 대신 예외를 던지며 번들 빌더의 `(OSError, ValueError)` 처리도
        우회한다(Codex 6차 실증 2026-08-18). 정수는 늘 유한하다 - 크기만 본다.
        """
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        if isinstance(v, int):
            if abs(v) > 10 ** 15:      # 코퍼스가 7.5M 이라 support 는 그 아래다
                return False
        elif not math.isfinite(v):     # NaN/inf 는 화면에서 `NaN%` 가 된다
            return False
        if lo is not None and v < lo:
            return False
        return not (hi is not None and v > hi)

    def _strs(v) -> bool:
        """`lookup` 이 `set(r["tags"])` 로 쓰므로 **원소가 해시 가능한 문자열**이어야
        한다. 원소 타입을 안 보던 시절 `["a", ["bad"]]` 가 통과했다(Codex 5차)."""
        return all(isinstance(t, str) and t.strip() for t in v)

    bad = []
    if not isinstance(e, dict):
        return ["entry is not a dict"]
    rows, flat = e.get("rows"), e.get("tags")
    if rows is not None and not isinstance(rows, list):
        bad.append("rows is not a list")
        rows = []
    if flat is not None and not isinstance(flat, list):
        bad.append("tags is not a list")
        flat = []
    for r in (rows or []):
        if not isinstance(r, dict):
            bad.append("row is not a dict")
        elif not isinstance(r.get("tags"), list) or not r.get("tags"):
            bad.append("row without tags")
        elif not _strs(r["tags"]):
            bad.append("row tags contain a non-string")
        elif not _num(r.get("coverage"), 0.0, 1.0) or not _num(r.get("support"), 0):
            # `coverage` 는 앵커 선택이, `support` 는 라우트 응답이 읽는다.
            #
            # 범위까지 보는 이유: 확률이 1 을 넘으면 화면에 `500%` 가 뜬다 -
            # 크래시가 아니라 **조용히 틀린 것**이라 더 나쁘다. 실제 뱅크 실측
            # (581,930줄)은 coverage [0.0001, 1.0] · support [30, 119,776] 이라
            # 이 문이 배포물을 거부하지 않는다.
            bad.append("row coverage/support out of range")
    for x in (flat or []):
        if not isinstance(x, dict):
            bad.append("flat entry is not a dict")
        elif not str(x.get("tag") or "").strip():
            bad.append("flat entry without tag")
        elif not _num(x.get("p"), 0.0, 1.0):
            # 실측 p 는 [0.0001, 1.0] 이다(964,243칩). 화면이 `p*100` 을 쓴다.
            bad.append("flat entry p out of range")
    return bad


def _smoke_lookup(d: dict, groups) -> None:
    """게이트가 **런타임 소비자를 앵커 전수로 돌린다.** 예외가 나면 배포 불가다.

    ⚠️ 이것이 이 영역의 구조적 교정이다. 필드 목록을 손으로 관리하면 계속 샌다 -
    같은 게이트가 **4라운드 연속** 뚫렸고 매번 "그 필드도 런타임이 읽더라" 였다
    (`tags` -> `coverage`/`p` -> `support`). 목록은 소비자가 바뀌면 낡는다.

    ⚠️ **표본으로는 그 보장이 성립하지 않는다.** 처음엔 그룹당 앵커 3개만 돌렸는데,
    Codex 5차가 정확히 그 틈을 찔렀다: 4번째 앵커에 `tags: ["a", ["bad"]]` 를 넣으면
    게이트를 통과하고 그 앵커 요청만 `TypeError` 로 죽는다. "정의상 전부 덮는다" 는
    말은 **전수**일 때만 참이다.
    실측(실제 뱅크 63,468앵커): prefer 경로 0.56s + 자동선택 경로 0.53s = **1.09s**.
    표본을 아낄 이유가 없었다 - 조회가 앵커당 9us 다.
    """
    from .bank import RecipeBank
    bk = RecipeBank.from_parsed(d)
    for g in groups:
        tab = bk.anchors(g)
        if not tab:
            continue
        answered = 0
        for anchor in tab:
            # 두 호출 모양을 다 돌린다 - 화면 경로(prefer)와 자동 선택 경로가
            # 서로 다른 코드를 탄다(후자에 옛 직접 인덱스가 있었다).
            for kw in ({"prefer": anchor}, {}):
                try:
                    r = bk.lookup([anchor], g, **kw)
                except Exception as exc:     # noqa: BLE001 - 무엇이든 배포 불가다
                    raise ValueError(
                        f"lookup crashed: group={g!r} anchor={anchor!r} "
                        f"{type(exc).__name__}: {exc}") from None
                if kw and not r.get("abstained"):
                    answered += 1
        if not answered:
            raise ValueError(f"group {g!r}: every anchor abstained")


def bank_answerable_groups(d: dict) -> list[str]:
    """뱅크 dict 에서 **답할 수 있는 엔트리를 가진** 그룹 이름들.

    `service.bank_groups()` 와 검증이 같은 눈을 쓰게 하려고 여기 둔다 - 갈리면
    "검증은 떨어뜨렸는데 서비스는 13그룹이라고 세는" 상태가 생긴다(그게 정확히
    Codex 가 잡은 P1 이었다).
    """
    groups = d.get("groups") or {}
    if not isinstance(groups, dict):
        return []
    return [g for g, tab in groups.items()
            if isinstance(tab, dict) and any(_entry_answerable(e) for e in tab.values())]


def _parse_bank(blob: bytes) -> dict:
    """바이트 -> 뱅크 dict. 형식만 본다.

    문구는 `RecipeBank` 와 **같은 것**을 쓴다(`unknown bank format: …`). 같은
    조건에 두 문구가 있으면 그걸 잡으려고 쓴 테스트가 경로에 따라 갈린다. ASCII
    인 이유는 이 문구가 `service.bank()` 의 `print` 로 흘러가기 때문이다 -
    콘솔이 cp949 라 한글은 `??` 로 깨져 정보가 남지 않는다.
    """
    d = json.loads(blob.decode("utf-8"))
    if d.get("format") != BANK_FORMAT:
        raise ValueError(f"unknown bank format: {d.get('format')!r}, "
                         f"want {BANK_FORMAT}")
    return d


def check_bank_partial(blob: bytes) -> dict:
    """형식이 맞고 **답할 수 있는 그룹이 하나라도** 있는지. 13그룹은 안 본다.

    개발 머신에서 한 그룹만 구워 시험하는 흐름을 위한 문이다. 배포 판정에는
    `check_bank_blob`(13그룹)을 쓴다 - 이 함수를 배포 게이트로 쓰지 마라.
    """
    d = _parse_bank(blob)
    if not bank_answerable_groups(d):
        raise ValueError("no answerable group in bank")
    return d


def check_bank_blob(blob: bytes) -> dict:
    """레시피 뱅크 바이트가 **배포에 쓸 수 있는지**. 아니면 ValueError.

    ⚠️ **빌더와 런타임이 이 하나를 쓴다.** 예전엔 번들 빌더와 `verify_all` 이
    각자 검사해서 강도가 갈렸다 - 런타임은 "그룹이 하나라도 있으면 통과" 였고
    빌더만 13그룹을 봤다(Codex 지적 2026-08-17). 갈리면 빌더가 통과시킨 것을
    런타임이 거부하거나, 더 나쁘게는 그 반대가 된다.

    배포에는 모델이 안 가므로 뱅크에 없는 인원 그룹은 폴백 없이 통째로 죽는다.
    그래서 "13그룹이 각각 비어 있지 않다" 가 계약이다.
    """
    from .person import PERSON_GROUPS
    # `check_bank_partial` 을 부르지 않는다 - 그쪽의 "하나라도" 검사는 아래
    # 그룹별 검사에 포함되고, 먼저 걸리면 **어느 그룹이 빈지** 못 알린다.
    d = _parse_bank(blob)
    groups = d.get("groups") or {}
    gone = [g for g in PERSON_GROUPS if not (groups.get(g) or {})]
    if gone:
        raise ValueError(f"앵커가 없는 그룹 {len(gone)}개: {gone[:4]}")
    # ⚠️ **"앵커가 있다" 로는 부족하다.** 각 그룹에 `{"x": {}}` 하나만 있어도
    # 통과했다(Codex 실증: `empty_anchor_entries_validator PASS groups 13`).
    # 그건 답할 수 없는 뱅크인데 검증을 통과하니 그대로 설치된다.
    # **실제로 답할 수 있는 엔트리**가 그룹마다 하나는 있어야 한다.
    ok = set(bank_answerable_groups(d))
    thin = [g for g in PERSON_GROUPS if g not in ok]
    if thin:
        raise ValueError(f"답할 수 있는 엔트리가 없는 그룹 {len(thin)}개: {thin[:4]}")
    # **배포 게이트는 전수로 본다.** `_entry_answerable` 의 "하나라도" 규칙은
    # 멀쩡한 첫 줄이 망가진 형제 줄을 가려 준다 - 런타임은 목록을 전부 소비하므로
    # 그건 통과 후 크래시다(Codex 4차). 여기서만 무겁게 본다: 런타임 적재 경로
    # (`check_bank_partial`)는 가볍게 두고 소비자가 `.get` 으로 방어한다.
    for g in PERSON_GROUPS:
        for anchor, e in (groups.get(g) or {}).items():
            bad = _entry_wellformed(e)
            if bad:
                raise ValueError(f"망가진 엔트리 {g}/{anchor}: {sorted(set(bad))[:3]}")
    # 마지막으로 **실제 조회를 돌린다** - 위 목록이 낡아도 이것이 잡는다.
    _smoke_lookup(d, PERSON_GROUPS)
    return d


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
            if magic not in ACCEPT_MAGIC:
                raise ValueError(f"번들 매직이 다르다: {magic!r} - {self.path}")
            (ilen,) = struct.unpack("<I", fh.read(4))
            self.index = json.loads(fh.read(ilen).decode("utf-8"))
        self.entries: dict[str, BundleEntry] = {
            g["name"]: BundleEntry(**g) for g in self.index["groups"]
        }
        # 부속 자산(레시피 뱅크·의미 그래프 등). NCSB1 에는 없다.
        self.aux_index: dict[str, dict] = {a["name"]: a
                                           for a in (self.index.get("aux") or [])}

    def aux(self, name: str, *, verify: bool = True) -> bytes | None:
        """부속 자산 원본 바이트. 없으면 None.

        **모델과 같은 파일에 넣는다.** 따로 배포하면 버전이 갈리고, 사용자는
        "레시피는 새 것인데 모델은 옛 것" 인 조합을 만나게 된다.
        """
        e = self.aux_index.get(name)
        if e is None:
            return None
        with self.path.open("rb") as fh:
            fh.seek(e["off"])
            blob = zlib.decompress(fh.read(e["len"]))
        if len(blob) != e["raw"]:
            raise ValueError(f"aux {name}: 길이가 다르다")
        if verify and hashlib.sha256(blob).hexdigest() != e["sha256"]:
            raise ValueError(f"aux {name}: sha256 불일치")
        return blob

    def groups(self) -> list[str]:
        return [g["name"] for g in self.index["groups"]]

    def total_bytes(self) -> int:
        return self.path.stat().st_size

    def verify_all(self) -> list[str]:
        """전 그룹 **과 필수 부속**의 sha256 을 대조하고 깨진 이름을 돌려준다.

        `read()` 는 **읽는 그룹만** 검증한다. 그건 평소엔 맞지만 다운로드 직후엔
        부족하다 - 안 쓰는 그룹이 깨진 채 남아 있다가 인원 수를 바꾸는 순간
        터진다. 설치 단계에서 한 번 이걸 돌린다(실측 13그룹 2초).

        ⚠️ **부속도 반드시 본다.** 예전에는 그룹만 순회했다. 그런데 배포 번들은
        이제 모델 없이 부속만 담으므로, 그 상태에서는 검증이 **아무것도 보지
        않고 통과**했다 - 레시피 뱅크가 깨진 번들이 "검증 성공" 으로 설치된다
        (Codex 지적 2026-08-17). 뱅크는 sha 뿐 아니라 형식까지 파싱해서 본다.
        """
        bad: list[str] = []
        for g in self.groups():
            try:
                self.read(g, verify=True)
            except (OSError, ValueError, KeyError, zlib.error):
                bad.append(g)
        # **옛 형식 판정은 `version` 으로 한다.** 예전엔 "그룹이 하나라도 있으면
        # 옛 번들" 로 봤는데, 그러면 version 2 번들이 부속을 잃어도 그룹이 있다는
        # 이유로 전부 통과했다(Codex 지적 2026-08-17).
        if int(self.index.get("version") or 1) < 2:
            return bad                     # NCSB1 = 부속이 없는 것이 정상이다
        for name in REQUIRED_AUX:
            if name not in self.aux_index:
                bad.append(f"aux:{name}")
                continue
            try:
                blob = self.aux(name, verify=True)
                if not blob:
                    raise ValueError("빈 부속")
                if name == "recipe_bank":
                    check_bank_blob(blob)
                else:
                    # 나머지도 최소한 JSON 으로 파싱은 돼야 한다 - 지금까지는
                    # "빈 바이트가 아니면 통과" 였다.
                    json.loads(blob.decode("utf-8"))
            except (OSError, ValueError, KeyError, zlib.error,
                    UnicodeDecodeError):
                bad.append(f"aux:{name}")
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


def write_bundle(out: Path, models: list[Path], *, source: str = "",
                 aux: dict[str, Path] | None = None,
                 built: str = "") -> dict:
    """느슨한 `.ncsr` + `.json` 들을 번들 하나로 묶는다.

    `aux` 는 이름 -> 파일 경로. 레시피 뱅크·의미 그래프처럼 모델과 **같은 버전이어야
    하는** 부속 자산을 같은 파일에 넣는다. 따로 배포하면 "레시피는 새 것인데 모델은
    옛 것" 인 조합이 생긴다.

    `built` 를 주면 그 값을 인덱스에 넣는다. 비우면 현재 시각이 들어가는데,
    그러면 **같은 입력으로 다시 구워도 sha256 이 달라진다**(Codex 지적). 재현
    가능한 빌드가 필요하면 고정 문자열을 넘겨라.
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    aux_items: list[tuple[str, bytes, dict]] = []
    for name, p in sorted((aux or {}).items()):
        raw = Path(p).read_bytes()
        aux_items.append((name, zlib.compress(raw, LEVEL),
                          {"raw": len(raw),
                           "sha256": hashlib.sha256(raw).hexdigest()}))
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
    stamp = built or time.strftime("%Y-%m-%dT%H:%M:%S")

    def build(offsets: list[tuple[int, int]], aoff: list[int]) -> bytes:
        groups = []
        for (name, mz, bz, info), (moff, boff) in zip(payloads, offsets):
            m = info["meta"]
            groups.append({
                "name": name, "meta_off": moff, "meta_len": len(mz),
                "body_off": boff, "body_len": len(bz), "body_raw": info["raw"],
                "sha256": info["sha"], "posts": int(m["posts"]),
                "vocab": int(m["vocab"]), "nnz": int(m["nnz"]),
            })
        aux_idx = [{"name": nm, "off": off, "len": len(bz), **info}
                   for (nm, bz, info), off in zip(aux_items, aoff)]
        d = {"version": 2 if aux_idx else 1, "source": source,
             "built": stamp, "groups": groups}
        if aux_idx:
            d["aux"] = aux_idx
        return json.dumps(d, ensure_ascii=False).encode("utf-8")

    def layout(head: int):
        offsets, cur = [], head
        for _, mz, bz, _ in payloads:
            offsets.append((cur, cur + len(mz)))
            cur += len(mz) + len(bz)
        aoff = []
        for _, bz, _ in aux_items:
            aoff.append(cur)
            cur += len(bz)
        return offsets, aoff

    zero_o, zero_a = layout(0)
    head = len(MAGIC) + 4 + len(build(zero_o, zero_a))
    offsets, aoff = layout(head)
    index = build(offsets, aoff)
    # 인덱스 길이가 바뀌면 오프셋이 밀린다. 같아질 때까지 다시 잡는다.
    while len(MAGIC) + 4 + len(index) != head:
        head = len(MAGIC) + 4 + len(index)
        offsets, aoff = layout(head)
        index = build(offsets, aoff)

    with out.open("wb") as fh:
        fh.write(MAGIC)
        fh.write(struct.pack("<I", len(index)))
        fh.write(index)
        for _, mz, bz, _ in payloads:
            fh.write(mz)
            fh.write(bz)
        for _, bz, _ in aux_items:
            fh.write(bz)
    # **부속 원본도 센다.** 예전엔 그룹 본문만 합산해서, 부속만 담은 번들의
    # `rawBytes` 가 0 이 됐다 - 압축률이 0 나눗셈으로 죽고, 그걸 `n/a` 로 가려도
    # 크기 회계는 여전히 틀린다(Codex 지적 2026-08-17).
    raw = (sum(i["raw"] for _, _, _, i in payloads)
           + sum(a["raw"] for _, _, a in aux_items))
    return {"path": str(out), "groups": len(payloads), "bytes": out.stat().st_size,
            "rawBytes": raw, "auxBytes": sum(a["raw"] for _, _, a in aux_items)}
