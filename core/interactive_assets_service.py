# -*- coding: utf-8 -*-
"""Interactive Assets — 캐릭터 조합 스냅샷 · 즐겨찾기.

## 왜 Assets 탭과 분리하나

Assets 탭(`headless_character_asset_service`)은 **사용자가 의도적으로 만든 자산**
이다 — 이름 붙인 PNG + 프롬프트. 스냅샷은 **자동으로 쌓이는 기록**이다(조합을
바꿀 때마다, 500한도). 같은 트리에 두면 목록이 스냅샷으로 뒤덮인다.

    user-data/save/character_asset/        Assets 탭 (기존, 건드리지 않는다)
    user-data/save/interactive_snapshot/   스냅샷 (신설)
    user-data/save/interactive_favorite/   즐겨찾기 (신설, 참조만)

## 기존 체계에 영향이 없다

이 서비스는 **Interactive 모드에서만** 불린다. 다른 경로에서 import 하지 않으며,
`WebSessionContext` 에 지연 생성으로 붙는다. 생성 파이프라인에는 훅 한 줄만
들어가고, 그 훅도 스냅샷이 없으면 아무것도 하지 않는다.

## 인덱스와 본문을 나눈다

레코드 하나가 1~2KB 이고 500개면 인덱스가 1MB 가까워진다. 조합을 바꿀 때마다
그걸 통째로 다시 쓰면 느리고, 쓰다 죽으면 전부 잃는다.

    index.json    메타만 — id · created_at · origin · thumb · prompt_hash · summary
    s<id>.json    조합 본문(chars). 복구할 때만 읽는다

인덱스는 50KB 수준으로 떨어진다.

## 스냅샷 레코드

    index.json  { "snapshots": [ {id, created_at, origin, thumb, prompt_hash, summary} ] }
    s<id>.json  { "id", "created_at", "chars": [ {name, gender, fields, alt, gaze, preset} ] }

캐릭터 슬롯의 조합만 담는다 — 씬 슬롯·파라미터는 담지 않는다(사용자 지정).

`prompt_hash` 는 조합을 정규화해 만든다. **직전과 같으면 새로 쌓지 않고
`created_at` 만 올린다** — 슬롯을 한 글자 고칠 때마다 쌓이면 500칸이 몇 분 만에
찬다. `preset` 라벨과 캔버스 위치(`pos`)는 해시에 넣지 않는다(프롬프트에 나가는
값만 본다 / 사용자 판단).

## origin 판정

캐릭터 슬롯에 **Danbooru 캐릭터 태그**가 하나라도 있으면 `known`, 없으면
`original`. 출처는 `data/character_analysis.json` — 캐릭터 뷰어·프리셋과 같은 SSOT.

## 프루닝

500 초과 시 오래된 것부터. **즐겨찾기에 올라간 것은 건너뛴다.** 즐겨찾기 자체에는
한도를 두지 않는다(사용자 판단: 실제로 크게 쓰지 않고 비용도 싸다).

## 조용히 사라지지 않게

세 지점을 막았다.

  1. 인덱스가 깨졌을 때 `[]` 를 돌려주면, 다음 `record()` 가 빈 배열로 덮어써
     500개가 날아간다 -> 손상 파일을 `.bak` 로 옮기고 그 사실을 남긴다.
  2. 즐겨찾기가 깨졌을 때 `[]` 를 돌려주면 **보호 대상이 통째로 프루닝된다**
     -> 파싱 실패면 프루닝을 하지 않는다.
  3. 인덱스 쓰기 중 죽으면 반쪽 파일이 남는다 -> 임시 파일에 쓰고 교체한다.

동시 접근은 `RLock` 으로 막는다(`headless_character_asset_service` 와 같은 규약).
Remote Web 은 탭이 여럿 붙을 수 있다.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SNAPSHOT_DIR_NAME = "interactive_snapshot"
# 씬(=이벤트) 기록. 캐릭터 스냅샷과 **다른 트리**에 둔다 - 단위가 다르다
# (생성 1회 = 캐릭터 N장 / 씬 1장). 같은 트리에 섞으면 목록·프루닝·복구가 전부
# 두 종류를 구분해야 한다.
SCENE_DIR_NAME = "interactive_scene"
FAVORITE_DIR_NAME = "interactive_favorite"
INDEX_NAME = "index.json"
FAVORITE_NAME = "favorites.json"

SNAPSHOT_LIMIT = 500
THUMB_SIZE = 384
THUMB_QUALITY = 72
SUMMARY_MAX = 120

# 즐겨찾기가 가리킬 수 있는 것. 실체를 복사하지 않고 참조만 담는다 —
# 원본이 지워지면 목록에서 빠질 뿐 반쪽이 남지 않는다.
FAVORITE_TYPES = ("snapshot", "asset", "character", "scene")


def _now() -> int:
    return int(time.time())


# 해시 직렬화의 구분자. 값 안에 이 글자가 있으면 경계를 흉내 낼 수 있다.
_HASH_DELIMS = ("\\", "|", "=", ",")
# 역슬래시가 **먼저**여야 한다 - 나중에 하면 앞서 넣은 이스케이프를 다시 이스케이프한다.
_HASH_ESCAPES = (("\\", "\\\\"), ("|", "\\p"), ("=", "\\e"), (",", "\\c"))


def _hash_esc(text: Any) -> str:
    """해시 조각 하나를 구분자와 섞이지 않게 만든다.

    **구분자가 없으면 글자 그대로 돌려준다.** 그래야 기존 기록의 해시가 바뀌지 않는다 -
    바뀌면 중복 판정이 풀려 같은 캐릭터를 다시 그렸을 때 갱신 대신 새 카드가 쌓인다
    (실측 2026-08-11: 사용자 기록 11건 · 태그 183개 중 구분자를 품은 태그 0개).
    """
    out = str(text)
    if not any(ch in out for ch in _HASH_DELIMS):
        return out
    for ch, rep in _HASH_ESCAPES:
        out = out.replace(ch, rep)
    return out


def snapshot_hash(chars: list[dict[str, Any]]) -> str:
    """같은 조합인지 판정하는 키. 순서와 대소문자를 정규화한다.

    프롬프트에 나가는 값만 본다 — `preset` 라벨과 `pos`(캔버스 위치)는 넣지 않는다.

    조각은 전부 `_hash_esc` 를 지난다. json.dumps 로 안쪽 경계를 지켜도 **바깥 join**
    이 날것이면 소용없다 - `flat` 은 `|` 로, 필드 값은 `,` 로 잇기 때문에 태그 하나가
    `x|neg={"b": ["y"]}` 이면 다른 조합과 같은 줄이 된다(Codex 5차 · 실측). 가중치
    묶음 `0.5::x,y ::` 도 두 태그 `["0.5::x", "y ::"]` 와 충돌했다 - 이건 우클릭
    가중치로 사용자가 실제로 만드는 값이다.
    """
    parts: list[str] = []
    for c in chars or []:
        fields = c.get("fields") or {}
        flat = [
            _hash_esc(k) + "="
            + ",".join(sorted(_hash_esc(str(x).strip().lower()) for x in (fields.get(k) or [])))
            for k in sorted(fields)
        ]
        # 슬롯별 네거티브도 프롬프트에 나가는 값이다. 빼면 네거티브만 다른 두
        # 조합이 같은 해시가 되어 record() 가 먼저 만든 조합을 덮어쓴다
        # (Fast 에서 이미 한 번 겪은 함정 - 같은 실수를 반복하지 않는다).
        # **경계를 지키는 직렬화**여야 한다. `;`/`=`/`,` 를 날것으로 이으면 태그
        # 안의 쉼표(가중치 묶음 `0.5::a, b ::`)나 특수문자가 구분자를 흉내 내
        # 서로 다른 조합이 같은 해시가 된다(Codex 4차 · 실측: {'a':['x;b=y']} 와
        # {'a':['x'],'b':['y']} 가 충돌). 바로 아래 fast 가 json 을 쓰는 이유와 같다.
        neg = c.get("neg") or {}
        if isinstance(neg, dict):
            neg_norm = {
                str(k): sorted(str(x).strip().lower() for x in (neg.get(k) or []))
                for k in sorted(neg) if neg.get(k)
            }
            if neg_norm:
                flat.append("neg=" + _hash_esc(
                    json.dumps(neg_norm, ensure_ascii=False, sort_keys=True)))
        flat.append("gender=" + _hash_esc(c.get("gender") or ""))
        flat.append("alt=" + ",".join(sorted(_hash_esc(str(x).lower()) for x in (c.get("alt") or []))))
        flat.append("gaze=" + ",".join(sorted(_hash_esc(str(x).lower()) for x in (c.get("gaze") or []))))
        # Fast(캐릭터별 추가 프롬프트·네거티브)도 프롬프트에 나가는 값이다.
        # 빼면 Fast 만 다른 두 조합이 같은 해시가 되고, record() 가 같은 행을
        # 찾아 본문·썸네일을 덮어써 먼저 만든 조합이 조용히 사라진다(Codex 리뷰).
        #
        # **비어 있으면 아무것도 더하지 않는다.** 그래야 Fast 를 쓰지 않은 기존
        # 기록의 해시가 그대로 유지된다 — 무조건 넣으면 옛 행이 전부 새 해시와
        # 어긋나 중복 판정이 풀리고 같은 조합이 두 벌로 쌓인다.
        #
        # **경계를 살려 직렬화한다.** `"fastp=" + 값` 을 `|` 로 이으면 사용자가
        # 적은 문자열이 구분자를 흉내 낼 수 있다 — `{p: "foo|fastn=bar", n: ""}`
        # 와 `{p: "foo", n: "bar"}` 가 같은 줄이 되어 서로를 덮어쓴다(Codex 리뷰
        # 2026-08-10). json.dumps 는 따옴표를 이스케이프하므로 섞이지 않는다.
        fast = c.get("fast") or {}
        if isinstance(fast, dict):
            fp = str(fast.get("p") or "").strip().lower()
            fn = str(fast.get("n") or "").strip().lower()
            if fp or fn:
                flat.append("fast=" + _hash_esc(
                    json.dumps([fp, fn], ensure_ascii=False, sort_keys=True)))
        parts.append("|".join(flat))
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def snapshot_summary(chars: list[dict[str, Any]]) -> str:
    """목록에 보여줄 한 줄. 본문을 안 읽고도 무엇인지 알아야 검색이 된다."""
    bits: list[str] = []
    for c in chars or []:
        fields = c.get("fields") or {}
        name = (fields.get("캐릭터") or [""])[0] or str(c.get("name") or "")
        rest = [x for k in fields if k != "캐릭터" for x in (fields.get(k) or [])]
        bits.append(", ".join([b for b in [name] if b] + rest[:4]))
    text = " / ".join(b for b in bits if b)
    return text[:SUMMARY_MAX]


def scene_hash(globals_: dict[str, Any], chars: list[dict[str, Any]]) -> str:
    """씬(=이벤트) 하나의 중복 판정 키.

    **복원이 실제로 적용하는 것만 본다.** 그래야 "되돌리면 똑같아지는" 두 기록이
    한 장으로 모인다. 캐릭터 쪽은 프론트가 이미 정체성(캐릭터·머리·눈얼굴·신체·
    종족)을 걷어낸 뒤 보낸다 - 무엇을 복원할지의 정의는 프론트 한 곳에만 둔다
    (백엔드가 슬롯 이름을 또 알면 축이 바뀔 때 조용히 갈라진다).

    씬 값은 `getSnapshotGlobals()` 가 준다: 씬 슬롯 8칸 · 구도 콤보 · 자유 입력 ·
    Rating · 전역 추가 네거티브. 전부 그림에 나가는 값이라 전부 센다.
    구분자 이스케이프는 `snapshot_hash` 와 같은 이유다.
    """
    g = globals_ if isinstance(globals_, dict) else {}
    flat: list[str] = []

    slots = g.get("slots") or {}
    if isinstance(slots, dict):
        for k in sorted(slots):
            vals = sorted(_hash_esc(str(x).strip().lower()) for x in (slots.get(k) or []))
            flat.append(_hash_esc(k) + "=" + ",".join(vals))

    comp = g.get("composition") or {}
    if isinstance(comp, dict):
        flat.append("comp=" + _hash_esc(
            json.dumps({str(k): comp.get(k) for k in sorted(comp)},
                       ensure_ascii=False, sort_keys=True, default=str)))

    for key in ("free_text", "fast_negative"):
        text = str(g.get(key) or "").strip().lower()
        if text:
            flat.append(key + "=" + _hash_esc(text))

    rating = g.get("rating") or {}
    if isinstance(rating, dict):
        # 프론트가 **뽑힌 값으로 접어서** 보낸다(사용자 지정: 카드는 그 그림 그대로).
        # 후보 목록을 그대로 세면 같은 Random 풀에서 나온 서로 다른 그림들이 한
        # 해시가 되어 덮어쓴다(Codex 6차). mode 는 세지 않는다 - 접힌 뒤엔 항상
        # single 이고, 세면 옛 기록과 갈라지기만 한다.
        picks = sorted(str(x).strip().lower() for x in (rating.get("picks") or []))
        # 'none'/빈 값은 아무것도 더하지 않는다 - Rating 을 안 쓴 기록의 해시를 지킨다.
        picks = [p for p in picks if p and p != "none"]
        if picks:
            flat.append("rating=" + _hash_esc(
                json.dumps(picks, ensure_ascii=False)))

    # 캐릭터의 '상황' 부분. 사람 수와 순서도 그림을 바꾸므로 그대로 센다.
    if chars:
        # **캐릭터별 Fast 는 빼고 센다.** 본문에는 담지만(사용자 지정 2026-08-11:
        # 비싸지 않으니 기록은 해 두고 나중에 복원 기능을 붙일 수 있게) 지금은
        # 복원하지 않는다. 해시는 '복원되는 것'만 봐야 한다 - 넣으면 Fast 한 글자에
        # 같은 씬이 여러 장으로 갈린다.
        no_fast = [{k: v for k, v in (c or {}).items() if k != "fast"} for c in chars]
        flat.append("chars=" + _hash_esc(snapshot_hash(no_fast)))
        # **배치는 여기서 따로 센다.** `snapshot_hash` 는 pos 를 일부러 뺀다(캐릭터
        # 에셋에서는 같은 캐릭터가 어디 서 있든 한 장이어야 한다). 하지만 씬에서는
        # 다인원 배치가 곧 그 이벤트다 - 위임만 하면 배치만 다른 두 씬이 한 장으로
        # 뭉개져 서로를 덮어쓴다(Codex 6차 설계 인스펙션).
        flat.append("pos=" + ",".join(
            _hash_esc(str(c.get("pos") or "")) for c in chars))

    return hashlib.sha1("|".join(flat).encode("utf-8")).hexdigest()[:16]


def _str_list(value: Any) -> list[str]:
    """리스트가 아니면 버린다. 문자열로 못박고 빈 값을 뺀다.

    **`None` 은 먼저 버린다.** `str(None)` 은 `"None"` 이고 그건 공백이 아니라
    필터를 통과한다 - 손상되거나 옛 형식의 기록이 프롬프트에 `None` 이라는 태그를
    실어 보낸다(Codex 7차 · 실측). dict/list 처럼 태그일 수 없는 값도 버린다.
    """
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for x in value:
        if x is None or isinstance(x, (dict, list, tuple, set)):
            continue
        text = str(x).strip()
        if text:
            out.append(str(x))
    return out


def normalize_scene_globals(value: Any) -> dict[str, Any]:
    """씬 값의 모양을 못박는다.

    본문은 파싱만 되면 무엇이든 돌아온다(스키마 검증이 없다). 복원 직전에
    임시 상태로 정규화해 두지 않으면, 옛 기록이나 손편집이 반쯤 적용된 작업판을
    남긴다(Codex 6차 설계 인스펙션). 쓰기와 읽기 양쪽에서 같은 함수를 지난다.

    **모르는 키는 버린다.** 씬은 이 여섯 조각이 전부다.
    """
    g = value if isinstance(value, dict) else {}
    slots = g.get("slots")
    comp = g.get("composition")
    rating = g.get("rating")
    picks = _str_list((rating or {}).get("picks")) if isinstance(rating, dict) else []
    return {
        "slots": ({str(k): _str_list(v) for k, v in slots.items()}
                  if isinstance(slots, dict) else {}),
        # 구도 콤보는 축 이름과 값이 프론트 소관이라 값 종류를 못박지 않는다.
        # 다만 dict 가 아니면 버린다 - 그래야 복원이 spread 로 안전하게 합쳐진다.
        "composition": dict(comp) if isinstance(comp, dict) else {},
        "composition_tags": _str_list(g.get("composition_tags")),
        "free_text": str(g.get("free_text") or ""),
        # 프론트가 뽑힌 값으로 접어서 보낸다 - mode 는 항상 single 로 둔다.
        "rating": {"mode": "single", "picks": picks},
        "fast_negative": str(g.get("fast_negative") or ""),
    }


def normalize_scene_chars(value: Any) -> list[dict[str, Any]]:
    """씬이 담는 캐릭터 '상황'의 모양을 못박는다.

    정체성(이름·프리셋)은 프론트가 이미 걷어내고 보내지만, 여기서도 **담지 않는다** -
    옛 기록이나 손편집으로 들어와도 씬이 캐릭터를 바꾸는 일이 없게 한다.
    `fast` 는 담는다(사용자 지정: 기록만 해 두고 복원은 나중에).
    """
    rows = value if isinstance(value, (list, tuple)) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        c = row if isinstance(row, dict) else {}
        fields = c.get("fields")
        neg = c.get("neg")
        fast = c.get("fast")
        out.append({
            "gender": "male" if str(c.get("gender") or "") == "male" else "female",
            "pos": str(c.get("pos") or ""),
            "fields": ({str(k): _str_list(v) for k, v in fields.items()}
                       if isinstance(fields, dict) else {}),
            "neg": ({str(k): _str_list(v) for k, v in neg.items()}
                    if isinstance(neg, dict) else {}),
            "alt": _str_list(c.get("alt")),
            "gaze": _str_list(c.get("gaze")),
            "fast": {"p": str((fast or {}).get("p") or ""),
                     "n": str((fast or {}).get("n") or "")} if isinstance(fast, dict)
                    else {"p": "", "n": ""},
        })
    return out


def scene_is_meaningful(globals_: dict[str, Any], chars: list[dict[str, Any]]) -> bool:
    """기록할 값어치가 있는 씬인가(사용자 지정 2026-08-11).

    **구도 축과 Rating 만으로는 값어치가 없다.** 사용자 표현: "축만 들어있는
    데이터 같은건 쓸모가 없을 가능성이 높습니다". 구도는 슬라이더 기본값이나
    한 번의 클릭으로도 채워지므로, 그것만 든 카드가 쌓이면 목록이 잡음이 된다.

    값어치의 근거는 **사용자가 실제로 넣은 태그·글**이다:
      - 씬 슬롯에 태그가 하나라도 있거나
      - 자유 입력이나 전역 추가 네거티브에 글이 있거나
      - 캐릭터의 '상황'(의상/자세/표정/사물/구도/ALT/시선/네거티브)에 값이 있거나
      - 캐릭터별 Fast 에 글이 있다
    """
    g = normalize_scene_globals(globals_)
    if any(v for v in g["slots"].values()):
        return True
    if g["free_text"].strip() or g["fast_negative"].strip():
        return True
    for c in normalize_scene_chars(chars):
        if any(v for v in c["fields"].values()):
            return True
        if any(v for v in c["neg"].values()):
            return True
        if c["alt"] or c["gaze"]:
            return True
        if c["fast"]["p"].strip() or c["fast"]["n"].strip():
            return True
    return False


def scene_summary(globals_: dict[str, Any], chars: list[dict[str, Any]]) -> str:
    """씬 카드의 한 줄. 씬 태그를 앞에 두고 모자라면 캐릭터 상황으로 채운다."""
    g = globals_ if isinstance(globals_, dict) else {}
    bits: list[str] = []
    slots = g.get("slots") or {}
    if isinstance(slots, dict):
        for k in slots:
            bits.extend(str(x) for x in (slots.get(k) or []) if str(x).strip())
    for tag in (g.get("composition_tags") or []):
        if str(tag).strip():
            bits.append(str(tag))
    if len(bits) < 4:
        for c in chars or []:
            fields = c.get("fields") or {}
            bits.extend(x for v in fields.values() for x in (v or []))
    free = str(g.get("free_text") or "").strip()
    if free:
        bits.append(free)
    return ", ".join(bits)[:SUMMARY_MAX]


class InteractiveAssetsService:
    """스냅샷·즐겨찾기 저장소. 쓰기 루트는 하나다(Assets 서비스와 같은 정책)."""

    def __init__(self, context) -> None:
        self._context = context
        self._lock = threading.RLock()
        self._known_names: set[str] | None = None
        # 손상 감지 플래그와 지연 삭제 큐. 빈 목록으로 덮어쓰거나, 인덱스보다
        # 파일을 먼저 지워 되돌릴 수 없게 되는 사고를 막는다(Codex 리뷰 2026-08-02).
        self._favorites_broken = False
        self._pending_delete: list[dict] = []

    # ── 경로 ────────────────────────────────────────────────────────────────
    @property
    def snapshot_root(self) -> Path:
        return self._context._save_path(SNAPSHOT_DIR_NAME)

    @property
    def favorite_root(self) -> Path:
        return self._context._save_path(FAVORITE_DIR_NAME)

    def _index_path(self) -> Path:
        return self.snapshot_root / INDEX_NAME

    def _body_path(self, snapshot_id: str) -> Path:
        return self.snapshot_root / f"{snapshot_id}.json"

    def _favorite_path(self) -> Path:
        return self.favorite_root / FAVORITE_NAME

    # ── 안전한 쓰기 ─────────────────────────────────────────────────────────
    @staticmethod
    def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
        """임시 파일에 쓰고 교체한다. 쓰다 죽어도 반쪽 파일이 남지 않는다."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def _quarantine(path: Path) -> None:
        """깨진 파일을 옆으로 치운다. 덮어써서 없애지 않는다.

        **고정 `.bak` 를 쓰면 두 번째 손상이 첫 백업을 덮어쓴다**(Codex 지적).
        비어 있는 번호를 찾아 붙인다.
        """
        for n in range(1, 100):
            dst = path.with_suffix(path.suffix + (".bak" if n == 1 else f".bak{n}"))
            if dst.exists():
                continue
            try:
                path.replace(dst)
                print(f"[interactive-assets] corrupt file moved aside: {dst.name}")
            except Exception:
                pass
            return

    # ── origin 판정 ─────────────────────────────────────────────────────────
    def _known_character_names(self) -> set[str]:
        if self._known_names is not None:
            return self._known_names
        names: set[str] = set()
        try:
            p = Path(self._context.repo_root) / "data" / "character_analysis.json"
            doc = json.loads(p.read_text(encoding="utf-8"))
            for work, chars in doc.items():
                if str(work).startswith("_"):
                    continue
                names.update(str(n).strip().lower() for n in chars)
        except Exception:
            names = set()
        self._known_names = names
        return names

    def classify_origin(self, chars: list[dict[str, Any]]) -> str:
        known = self._known_character_names()
        if not known:
            return "original"
        for c in chars or []:
            for tag in (c.get("fields") or {}).get("캐릭터", []) or []:
                if str(tag).strip().lower() in known:
                    return "known"
            if str(c.get("name") or "").strip().lower() in known:
                return "known"
        return "original"

    # ── 인덱스 ──────────────────────────────────────────────────────────────
    def load_index(self) -> list[dict[str, Any]]:
        """메타 목록. **손상되면 옆으로 치우고 빈 목록을 준다** — 그냥 `[]` 를
        돌려주면 다음 쓰기가 그대로 덮어써 500개가 조용히 날아간다."""
        p = self._index_path()
        if not p.exists():
            return []
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            rows = doc.get("snapshots") if isinstance(doc, dict) else doc
            if not isinstance(rows, list):
                raise ValueError("snapshots is not a list")
            return rows
        except Exception:
            # **여기서 `[]` 를 돌려주면 다음 `record()` 가 새 인덱스를 써서 기존 본문
            # 500개가 통째로 고아가 된다**(Codex 지적). 본문 파일이 살아 있으므로
            # 거기서 인덱스를 되짚는다.
            #
            # **되짚은 것을 바로 저장한다.** 안 그러면 이 호출만 복구된 것처럼 보이고,
            # 손상본은 이미 .bak 으로 치웠으므로 **다음 호출은 빈 목록**이다 - 그
            # 상태에서 record() 가 한 줄짜리 인덱스를 써서 옛 카드가 전부 인덱스에서
            # 사라진다(Codex 7차 · 실측: 1회차 3 -> 2회차 0 -> 기록 후 1).
            self._quarantine(p)
            rows = self._rebuild_index_from_bodies()
            if rows:
                try:
                    self._save_index(rows)
                except Exception as exc:            # 저장 실패해도 이번 목록은 준다
                    print(f"[interactive-assets] rebuilt index save failed: {exc}")
            return rows

    def _rebuild_index_from_bodies(self) -> list[dict[str, Any]]:
        """본문(`s<id>.json`)에서 인덱스를 복원한다. 인덱스가 깨져도 조합은 남는다."""
        rows: list[dict[str, Any]] = []
        for body in sorted(self.snapshot_root.glob("s*.json")):
            # **행 조립까지 전부 이 안에서** 한다. 파싱만 감싸면 손편집된 본문 하나의
            # `created_at` 이 숫자가 아니거나 `chars` 가 리스트가 아닐 때 int()/len()
            # 이 터져 **복구가 통째로 죽는다**. 인덱스는 이미 .bak 으로 치운 뒤라
            # 여기서 죽으면 목록이 영영 빈다(Codex 7차 · 씬 쪽에서 실측).
            try:
                doc = json.loads(body.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    raise ValueError("body is not an object")
                chars = doc.get("chars")
                if not isinstance(chars, list):
                    chars = []
                sid = str(doc.get("id") or body.stem)
                try:
                    created = int(doc.get("created_at") or 0)
                except (TypeError, ValueError):
                    created = 0
                thumb = f"{sid}.webp"
                rows.append({
                    "id": sid, "created_at": created,
                    "origin": self.classify_origin(chars),
                    "prompt_hash": snapshot_hash(chars),
                    "summary": snapshot_summary(chars),
                    "char_count": len(chars),
                    "thumb": thumb if (self.snapshot_root / thumb).exists() else None,
                })
            except Exception as exc:
                print(f"[interactive-assets] skipped broken body {body.name}: {exc}")
                continue
        rows.sort(key=lambda r: r.get("created_at") or 0)
        if rows:
            print(f"[interactive-assets] index rebuilt from {len(rows)} body files")
        return rows

    def _save_index(self, rows: list[dict[str, Any]]) -> None:
        self._write_atomic(self._index_path(), {
            "note": ["Interactive 캐릭터 조합 스냅샷의 메타. 본문은 s<id>.json 이다.",
                     "core/interactive_assets_service.py 가 만든다.",
                     f"{SNAPSHOT_LIMIT}개를 넘으면 오래된 것부터 지운다(즐겨찾기는 건너뛴다)."],
            "limit": SNAPSHOT_LIMIT, "count": len(rows), "snapshots": rows,
        })

    def load_body(self, snapshot_id: str) -> dict[str, Any] | None:
        p = self._body_path(snapshot_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self._quarantine(p)
            return None

    # ── 스냅샷 ──────────────────────────────────────────────────────────────
    def record(self, chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """**캐릭터 한 명이 에셋 하나다**(사용자 결정 2026-08-07). 목록을 돌려준다.

        예전에는 한 번 생성한 조합 전체가 카드 하나였다. 그러면 두 명을 그린
        순간 그 둘이 영영 한 덩어리라, 나중에 한 명만 꺼내 쓰려면 카드를 펼쳐야
        했다. 슬롯마다 따로 쌓으면 캐릭터가 곧 에셋이 된다.

        같은 캐릭터는 **목록 어디에 있든** 한 장으로 모은다. 옛 방식은 맨 뒷줄
        하나만 비교했는데, 여러 명을 한 번에 기록하면 마지막 한 명 말고는 전부
        새로 쌓인다.

        **씬 값(글로벌 태그·구도)은 담지 않는다**(사용자 결정 2026-08-07). 씬은
        따로 관리하고 그쪽에서 캐릭터 슬롯 캡처를 기록한다 — 여기에 사본을 두면
        캐릭터 수만큼 같은 씬이 복제되고, 나중에 어느 쪽이 진짜인지 알 수 없다.
        """
        if not chars:
            return []
        out: list[dict[str, Any]] = []
        with self._lock:
            rows = self.load_index()
            for char in chars:
                one = [char]
                digest = snapshot_hash(one)
                hit = next((r for r in rows if r.get("prompt_hash") == digest), None)
                if hit is not None:
                    hit["created_at"] = _now()
                    hit["summary"] = snapshot_summary(one)
                    hit["origin"] = self.classify_origin(one)
                    hit["char_count"] = 1
                    # 본문도 갱신한다. 해시가 안 보는 필드(활성/비활성, 위치, 프리셋
                    # 라벨)는 같은 해시로도 달라질 수 있는데 썸네일은 같은 id 파일을
                    # 덮어쓴다. 본문을 두면 카드의 그림과 복원 결과가 어긋난다.
                    self._write_atomic(
                        self._body_path(hit["id"]),
                        {"id": hit["id"], "created_at": hit["created_at"],
                         "chars": one})
                    # **끝으로 옮긴다.** 이 목록은 자리가 곧 최신순이다 — 화면은
                    # reversed() 로 읽고 _prune 은 앞쪽을 오래된 것으로 보고 지운다.
                    # 제자리에 두면 방금 쓴 에셋이 낡은 것으로 취급돼 먼저 사라진다.
                    rows.remove(hit)
                    rows.append(hit)
                    out.append(hit)
                    continue
                sid = "s" + uuid.uuid4().hex[:16]
                meta = {
                    "id": sid, "created_at": _now(),
                    "origin": self.classify_origin(one), "thumb": None,
                    "prompt_hash": digest, "summary": snapshot_summary(one),
                    # 한 명짜리가 되었지만 키는 남긴다 — 프론트가 이 값으로
                    # '펼치지 않고 바로 꽂을 수 있는가'를 판단한다.
                    "char_count": 1,
                }
                # 본문을 먼저 쓴다 — 인덱스에만 있고 본문이 없는 상태를 만들지 않는다.
                self._write_atomic(self._body_path(sid),
                                   {"id": sid, "created_at": meta["created_at"],
                                    "chars": one})
                rows.append(meta)
                out.append(meta)
            self._pending_delete = []
            self._prune(rows)
            self._save_index(rows)
            self._flush_deletes()            # 인덱스가 확정된 뒤에만 지운다
        return out

    def attach_thumb(self, snapshot_id: str, image_bytes: bytes) -> bool:
        """생성 결과를 384px WEBP 로 줄여 붙인다. 생성 훅이 호출한다."""
        if not snapshot_id or not image_bytes:
            return False
        try:
            from PIL import Image
        except ImportError:
            return False
        with self._lock:
            rows = self.load_index()
            row = next((r for r in rows if r.get("id") == snapshot_id), None)
            if row is None:
                return False
            with Image.open(io.BytesIO(image_bytes)) as im:
                im.load()
                img = im.convert("RGB")
                w, h = img.size
                if w != h:                   # 정사각 크롭(인물은 위쪽이 중요)
                    side = min(w, h)
                    img = img.crop(((w - side) // 2, (h - side) // 3,
                                    (w - side) // 2 + side, (h - side) // 3 + side))
                img = img.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "WEBP", quality=THUMB_QUALITY, method=6)
            self.snapshot_root.mkdir(parents=True, exist_ok=True)
            name = f"{snapshot_id}.webp"
            (self.snapshot_root / name).write_bytes(buf.getvalue())
            row["thumb"] = name
            self._save_index(rows)
            return True

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """스냅샷 하나를 지운다. 없으면 False(예외 아님 — 두 번 눌러도 조용하다).

        인덱스를 먼저 확정하고 파일을 나중에 지운다. 반대로 하면 지우다 죽었을 때
        인덱스에는 있는데 본문이 없는 항목이 남아 목록이 계속 404 를 부른다.
        즐겨찾기 참조도 함께 뗀다 — 안 그러면 '즐겨찾기만' 목록이 사라진 것을 센다.
        """
        sid = str(snapshot_id or "")
        if not sid:
            return False
        with self._lock:
            rows = self.load_index()
            hit = next((r for r in rows if r.get("id") == sid), None)
            if hit is None:
                return False
            rows = [r for r in rows if r.get("id") != sid]
            self._save_index(rows)
            thumb = hit.get("thumb")
            if thumb:
                (self.snapshot_root / str(thumb)).unlink(missing_ok=True)
            self._body_path(sid).unlink(missing_ok=True)
            self._drop_favorite_ref("snapshot", sid)
            return True

    def _drop_favorite_ref(self, kind: str, ref: str) -> None:
        """지워진 대상의 즐겨찾기 참조를 뗀다. 실패해도 삭제 자체는 되돌리지 않는다."""
        try:
            rows = self.load_favorites()
            if self._favorites_broken:
                self._favorites_broken = False
                return                      # 손상본을 방금 치웠다 — 빈 목록으로 덮지 않는다
            kept = [f for f in rows if not (f.get("type") == kind and f.get("ref") == ref)]
            if len(kept) == len(rows):
                return
            self._write_atomic(self._favorite_path(), {
                "note": ["Interactive 즐겨찾기. 실체가 아니라 참조만 담는다 —",
                         "원본이 지워지면 목록에서 빠질 뿐 반쪽이 남지 않는다.",
                         f"type: {' | '.join(FAVORITE_TYPES)}"],
                "count": len(kept), "favorites": kept,
            })
        except Exception as exc:            # pragma: no cover - defensive
            print(f"[interactive-assets] favorite cleanup failed: {exc}")

    def _prune(self, rows: list[dict[str, Any]]) -> None:
        """한도를 넘으면 오래된 것부터. **즐겨찾기에 올라간 것은 건너뛴다.**

        즐겨찾기를 못 읽으면 **아무것도 지우지 않는다** — 보호 대상을 모르는 채로
        지우면 사용자가 명시적으로 지킨 것이 사라진다.
        """
        if len(rows) <= SNAPSHOT_LIMIT:
            return
        pinned, ok = self._pinned_snapshot_ids()
        if not ok:
            print("[interactive-assets] favorites unreadable; pruning skipped")
            return
        drop = len(rows) - SNAPSHOT_LIMIT
        kept: list[dict[str, Any]] = []
        doomed: list[dict[str, Any]] = []
        for row in rows:                     # 오래된 것이 앞에 있다
            if drop > 0 and row.get("id") not in pinned:
                doomed.append(row)
                drop -= 1
                continue
            kept.append(row)
        # **인덱스를 먼저 확정하고 파일을 지운다.** 반대로 하면 인덱스 저장이
        # 실패했을 때 살아 있는 인덱스가 이미 지워진 파일을 가리킨다(Codex 지적).
        rows[:] = kept
        self._pending_delete = doomed

    def _flush_deletes(self) -> None:
        """프루닝이 정한 삭제를 인덱스 확정 뒤에 실행한다."""
        for row in self._pending_delete:
            sid = str(row.get("id"))
            thumb = row.get("thumb")
            if thumb:
                (self.snapshot_root / str(thumb)).unlink(missing_ok=True)
            self._body_path(sid).unlink(missing_ok=True)
        self._pending_delete = []

    # ── 씬(=이벤트) ─────────────────────────────────────────────────────────
    #
    # 캐릭터 스냅샷과 **단위가 다르다**: 생성 1회 = 캐릭터 N장이지만 씬은 1장이다.
    # 본문은 자기 완결이다 - 캐릭터 쪽 id 를 참조만 하면 그쪽이 프루닝될 때
    # 씬 카드가 반쪽이 된다(참조 무결성을 지킬 방법이 없다). 대신 프론트가
    # 정체성을 걷어낸 뒤 보내므로 캐릭터가 통째로 복제되지는 않는다.
    @property
    def scene_root(self) -> Path:
        return self._context._save_path(SCENE_DIR_NAME)

    def _scene_index_path(self) -> Path:
        return self.scene_root / INDEX_NAME

    def _scene_body_path(self, scene_id: str) -> Path:
        return self.scene_root / f"{scene_id}.json"

    def load_scene_index(self) -> list[dict[str, Any]]:
        """씬 메타 목록. 손상 처리는 캐릭터 쪽과 같은 규약이다."""
        p = self._scene_index_path()
        if not p.exists():
            return []
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            rows = doc.get("scenes") if isinstance(doc, dict) else doc
            if not isinstance(rows, list):
                raise ValueError("scenes is not a list")
            return rows
        except Exception:
            # 되짚은 것을 **바로 저장한다** — 캐릭터 쪽 load_index 의 주석 참조.
            self._quarantine(p)
            rows = self._rebuild_scene_index_from_bodies()
            if rows:
                try:
                    self._save_scene_index(rows)
                except Exception as exc:
                    print(f"[interactive-scene] rebuilt index save failed: {exc}")
            return rows

    def _rebuild_scene_index_from_bodies(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for body in sorted(self.scene_root.glob("e*.json")):
            # **행 조립까지 전부 이 안에서** 한다. 예전에는 파싱만 감쌌는데,
            # 손편집된 본문 하나의 `created_at` 이 숫자가 아니거나 `chars` 가
            # 리스트가 아니면 int()/len() 이 터져 **복구가 통째로 죽었다**
            # (Codex 7차 · 실측: ValueError 로 멀쩡한 3개까지 못 살렸다).
            # 인덱스는 이미 .bak 으로 치운 뒤라, 여기서 죽으면 목록이 영영 빈다.
            try:
                doc = json.loads(body.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    raise ValueError("body is not an object")
                sid = str(doc.get("id") or body.stem)
                g = normalize_scene_globals(doc.get("globals"))
                chars = normalize_scene_chars(doc.get("chars"))
                try:
                    created = int(doc.get("created_at") or 0)
                except (TypeError, ValueError):
                    created = 0
                thumb = f"{sid}.webp"
                rows.append({
                    "id": sid, "created_at": created,
                    "prompt_hash": scene_hash(g, chars),
                    "summary": scene_summary(g, chars),
                    "char_count": len(chars),
                    "thumb": thumb if (self.scene_root / thumb).exists() else None,
                })
            except Exception as exc:
                print(f"[interactive-scene] skipped broken body {body.name}: {exc}")
                continue
        rows.sort(key=lambda r: r.get("created_at") or 0)
        if rows:
            print(f"[interactive-scene] index rebuilt from {len(rows)} body files")
        return rows

    def _save_scene_index(self, rows: list[dict[str, Any]]) -> None:
        self._write_atomic(self._scene_index_path(), {
            "note": ["Interactive 씬(이벤트) 기록의 메타. 본문은 e<id>.json 이다.",
                     "core/interactive_assets_service.py 가 만든다.",
                     f"{SNAPSHOT_LIMIT}개를 넘으면 오래된 것부터 지운다(즐겨찾기는 건너뛴다)."],
            "limit": SNAPSHOT_LIMIT, "count": len(rows), "scenes": rows,
        })

    def load_scene_body(self, scene_id: str) -> dict[str, Any] | None:
        """씬 본문. **읽을 때도 정규화한다** — 옛 기록이나 손편집이 반쯤 적용된
        작업판을 남기지 않도록, 프론트에 나가기 전에 모양을 못박는다."""
        p = self._scene_body_path(scene_id)
        if not p.exists():
            return None
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            self._quarantine(p)
            return None
        if not isinstance(doc, dict):
            self._quarantine(p)
            return None
        return {
            "id": str(doc.get("id") or scene_id),
            "created_at": int(doc.get("created_at") or 0),
            "globals": normalize_scene_globals(doc.get("globals")),
            "chars": normalize_scene_chars(doc.get("chars")),
        }

    def record_scene(self, globals_: dict[str, Any],
                     chars: list[dict[str, Any]]) -> dict[str, Any] | None:
        """씬 하나를 기록한다. 같은 씬이면 새로 쌓지 않고 시각만 올린다.

        무엇을 복원하는가의 정의는 프론트에 있다 - `chars` 는 이미 정체성이
        걷어내진 채 온다. 여기서는 **모양만** 못박는다(정규화).

        **값어치가 없으면 아무것도 하지 않고 None 을 준다**(사용자 지정
        2026-08-11). 구도 축만 든 카드가 쌓이면 목록이 잡음이 된다.
        """
        g = normalize_scene_globals(globals_)
        rows_in = normalize_scene_chars(chars)
        if not scene_is_meaningful(g, rows_in):
            return None
        digest = scene_hash(g, rows_in)
        with self._lock:
            rows = self.load_scene_index()
            hit = next((r for r in rows if r.get("prompt_hash") == digest), None)
            if hit is not None:
                hit["created_at"] = _now()
                hit["summary"] = scene_summary(g, rows_in)
                hit["char_count"] = len(rows_in)
                self._write_atomic(
                    self._scene_body_path(hit["id"]),
                    {"id": hit["id"], "created_at": hit["created_at"],
                     "globals": g, "chars": rows_in})
                # 끝으로 옮긴다 — 자리가 곧 최신순이다(캐릭터 쪽과 같은 규약).
                rows.remove(hit)
                rows.append(hit)
                out = hit
            else:
                sid = "e" + uuid.uuid4().hex[:16]
                out = {
                    "id": sid, "created_at": _now(), "thumb": None,
                    "prompt_hash": digest, "summary": scene_summary(g, rows_in),
                    "char_count": len(rows_in),
                }
                # 본문을 먼저 쓴다 — 인덱스에만 있고 본문이 없는 상태를 만들지 않는다.
                self._write_atomic(self._scene_body_path(sid),
                                   {"id": sid, "created_at": out["created_at"],
                                    "globals": g, "chars": rows_in})
                rows.append(out)
            self._pending_delete = []
            self._prune_scenes(rows)
            self._save_scene_index(rows)
            self._flush_scene_deletes()
        return out

    def attach_scene_thumb(self, scene_id: str, image_bytes: bytes) -> bool:
        """생성 결과를 384px WEBP 로 붙인다. 캐릭터 쪽과 같은 크롭 규칙."""
        if not scene_id or not image_bytes:
            return False
        try:
            from PIL import Image
        except ImportError:
            return False
        with self._lock:
            rows = self.load_scene_index()
            row = next((r for r in rows if r.get("id") == scene_id), None)
            if row is None:
                return False
            with Image.open(io.BytesIO(image_bytes)) as im:
                im.load()
                img = im.convert("RGB")
                w, h = img.size
                if w != h:
                    side = min(w, h)
                    img = img.crop(((w - side) // 2, (h - side) // 3,
                                    (w - side) // 2 + side, (h - side) // 3 + side))
                img = img.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "WEBP", quality=THUMB_QUALITY, method=6)
            self.scene_root.mkdir(parents=True, exist_ok=True)
            name = f"{scene_id}.webp"
            (self.scene_root / name).write_bytes(buf.getvalue())
            row["thumb"] = name
            self._save_scene_index(rows)
            return True

    def delete_scene(self, scene_id: str) -> bool:
        sid = str(scene_id or "")
        if not sid:
            return False
        with self._lock:
            rows = self.load_scene_index()
            hit = next((r for r in rows if r.get("id") == sid), None)
            if hit is None:
                return False
            rows = [r for r in rows if r.get("id") != sid]
            self._save_scene_index(rows)
            thumb = hit.get("thumb")
            if thumb:
                (self.scene_root / str(thumb)).unlink(missing_ok=True)
            self._scene_body_path(sid).unlink(missing_ok=True)
            self._drop_favorite_ref("scene", sid)
            return True

    def _prune_scenes(self, rows: list[dict[str, Any]]) -> None:
        """캐릭터 쪽과 같은 규칙 — 즐겨찾기는 건너뛰고, 못 읽으면 아무것도 안 지운다."""
        if len(rows) <= SNAPSHOT_LIMIT:
            return
        pinned, ok = self._pinned_ids("scene")
        if not ok:
            print("[interactive-scene] favorites unreadable; pruning skipped")
            return
        drop = len(rows) - SNAPSHOT_LIMIT
        kept: list[dict[str, Any]] = []
        doomed: list[dict[str, Any]] = []
        for row in rows:
            if drop > 0 and row.get("id") not in pinned:
                doomed.append(row)
                drop -= 1
                continue
            kept.append(row)
        rows[:] = kept
        self._pending_delete = doomed

    def _flush_scene_deletes(self) -> None:
        for row in self._pending_delete:
            sid = str(row.get("id"))
            thumb = row.get("thumb")
            if thumb:
                (self.scene_root / str(thumb)).unlink(missing_ok=True)
            self._scene_body_path(sid).unlink(missing_ok=True)
        self._pending_delete = []

    # ── 즐겨찾기 ────────────────────────────────────────────────────────────
    def _pinned_ids(self, kind: str) -> tuple[set[str], bool]:
        """(보호 대상, 읽기 성공 여부). 실패를 빈 집합과 구분해야 한다 —
        구분하지 않으면 보호 대상을 모르는 채로 프루닝이 돈다."""
        p = self._favorite_path()
        if not p.exists():
            return set(), True
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            rows = doc.get("favorites") if isinstance(doc, dict) else doc
            if not isinstance(rows, list):
                raise ValueError("favorites is not a list")
        except Exception:
            return set(), False
        return {str(f.get("ref")) for f in rows if f.get("type") == kind}, True

    def _pinned_snapshot_ids(self) -> tuple[set[str], bool]:
        return self._pinned_ids("snapshot")

    def load_favorites(self) -> list[dict[str, Any]]:
        p = self._favorite_path()
        if not p.exists():
            return []
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            rows = doc.get("favorites") if isinstance(doc, dict) else doc
            if not isinstance(rows, list):
                raise ValueError("favorites is not a list")
            return rows
        except Exception:
            # 빈 목록으로 덮어쓰면 기존 즐겨찾기와 **프루닝 보호 정보**를 잃는다
            # (Codex 지적). 치워 두고 한 번은 쓰기를 거부한다.
            self._favorites_broken = True
            self._quarantine(p)
            return []

    def toggle_favorite(self, kind: str, ref: str, label: str = "") -> bool:
        """켜면 True, 끄면 False. 한도는 두지 않는다(사용자 판단)."""
        if kind not in FAVORITE_TYPES or not ref:
            raise ValueError(f"unknown favorite target: {kind!r}")
        with self._lock:
            rows = self.load_favorites()
            if self._favorites_broken:
                # 손상본을 방금 옆으로 치웠다. 빈 목록 위에 바로 쓰면 되살릴 수
                # 없으므로 한 번 거부한다 — .bak 을 손으로 복구할 기회를 준다.
                self._favorites_broken = False
                raise RuntimeError(
                    "favorites file was corrupt and moved aside (.bak); "
                    "retry to start a fresh list")
            hit = next((f for f in rows
                        if f.get("type") == kind and f.get("ref") == ref), None)
            if hit is not None:
                rows.remove(hit)
                on = False
            else:
                rows.append({"type": kind, "ref": ref, "label": label, "added_at": _now()})
                on = True
            self._write_atomic(self._favorite_path(), {
                "note": ["Interactive 즐겨찾기. 실체가 아니라 참조만 담는다 —",
                         "원본이 지워지면 목록에서 빠질 뿐 반쪽이 남지 않는다.",
                         f"type: {' | '.join(FAVORITE_TYPES)}"],
                "count": len(rows), "favorites": rows,
            })
            return on
