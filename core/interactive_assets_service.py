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
FAVORITE_DIR_NAME = "interactive_favorite"
INDEX_NAME = "index.json"
FAVORITE_NAME = "favorites.json"

SNAPSHOT_LIMIT = 500
THUMB_SIZE = 384
THUMB_QUALITY = 72
SUMMARY_MAX = 120

# 즐겨찾기가 가리킬 수 있는 것. 실체를 복사하지 않고 참조만 담는다 —
# 원본이 지워지면 목록에서 빠질 뿐 반쪽이 남지 않는다.
FAVORITE_TYPES = ("snapshot", "asset", "character")


def _now() -> int:
    return int(time.time())


def snapshot_hash(chars: list[dict[str, Any]]) -> str:
    """같은 조합인지 판정하는 키. 순서와 대소문자를 정규화한다.

    프롬프트에 나가는 값만 본다 — `preset` 라벨과 `pos`(캔버스 위치)는 넣지 않는다.
    """
    parts: list[str] = []
    for c in chars or []:
        fields = c.get("fields") or {}
        flat = [f"{k}={','.join(sorted(str(x).strip().lower() for x in (fields.get(k) or [])))}"
                for k in sorted(fields)]
        flat.append("gender=" + str(c.get("gender") or ""))
        flat.append("alt=" + ",".join(sorted(str(x).lower() for x in (c.get("alt") or []))))
        flat.append("gaze=" + ",".join(sorted(str(x).lower() for x in (c.get("gaze") or []))))
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
            self._quarantine(p)
            return self._rebuild_index_from_bodies()

    def _rebuild_index_from_bodies(self) -> list[dict[str, Any]]:
        """본문(`s<id>.json`)에서 인덱스를 복원한다. 인덱스가 깨져도 조합은 남는다."""
        rows: list[dict[str, Any]] = []
        for body in sorted(self.snapshot_root.glob("s*.json")):
            try:
                doc = json.loads(body.read_text(encoding="utf-8"))
                chars = doc.get("chars") or []
                sid = str(doc.get("id") or body.stem)
            except Exception:
                continue
            thumb = f"{sid}.webp"
            rows.append({
                "id": sid, "created_at": int(doc.get("created_at") or 0),
                "origin": self.classify_origin(chars),
                "prompt_hash": snapshot_hash(chars),
                "summary": snapshot_summary(chars),
                "char_count": len(chars),
                "thumb": thumb if (self.snapshot_root / thumb).exists() else None,
            })
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
    def record(self, chars: list[dict[str, Any]],
               globals_: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """조합을 기록한다. 직전과 같으면 시각만 올리고 새로 쌓지 않는다.

        `globals_` 는 씬 슬롯·구도처럼 캐릭터에 속하지 않는 값이다. 미리보기가
        '이 그림이 어떤 설정에서 나왔는가'를 보여 주려면 본문에 함께 있어야 한다.
        **해시에는 넣지 않는다** — 같은 캐릭터 조합인데 배경만 바꿨다고 카드가
        새로 쌓이면 목록이 금방 같은 얼굴로 가득 찬다. 대신 아래 갱신 경로가
        본문을 덮어쓰므로 마지막 값이 남는다.
        """
        if not chars:
            return None
        body_globals = globals_ if isinstance(globals_, dict) else {}
        with self._lock:
            digest = snapshot_hash(chars)
            rows = self.load_index()
            if rows and rows[-1].get("prompt_hash") == digest:
                rows[-1]["created_at"] = _now()
                rows[-1]["summary"] = snapshot_summary(chars)
                rows[-1]["origin"] = self.classify_origin(chars)
                rows[-1]["char_count"] = len(chars)
                # 본문도 갱신한다. 해시가 안 보는 필드(활성/비활성, 위치, 프리셋 라벨)는
                # 같은 해시로도 달라질 수 있는데, 썸네일은 같은 id 파일을 덮어쓴다.
                # 본문을 두면 카드의 그림과 복원 결과가 어긋난다.
                self._write_atomic(
                    self._body_path(rows[-1]["id"]),
                    {"id": rows[-1]["id"], "created_at": rows[-1]["created_at"],
                     "chars": chars, "globals": body_globals})
                self._save_index(rows)
                return rows[-1]
            sid = "s" + uuid.uuid4().hex[:16]
            meta = {
                "id": sid, "created_at": _now(),
                "origin": self.classify_origin(chars), "thumb": None,
                "prompt_hash": digest, "summary": snapshot_summary(chars),
                # 프론트가 본문을 읽지 않고도 "한 명짜리 조합"을 알아야 한다 —
                # 그래야 카드를 펼치지 않고 바로 슬롯에 꽂을 수 있다.
                "char_count": len(chars),
            }
            # 본문을 먼저 쓴다 — 인덱스에만 있고 본문이 없는 상태를 만들지 않는다.
            self._write_atomic(self._body_path(sid),
                               {"id": sid, "created_at": meta["created_at"],
                                "chars": chars, "globals": body_globals})
            rows.append(meta)
            self._pending_delete = []
            self._prune(rows)
            self._save_index(rows)
            self._flush_deletes()            # 인덱스가 확정된 뒤에만 지운다
            return meta

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

    # ── 즐겨찾기 ────────────────────────────────────────────────────────────
    def _pinned_snapshot_ids(self) -> tuple[set[str], bool]:
        """(보호 대상, 읽기 성공 여부). 실패를 빈 집합과 구분해야 한다."""
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
        return {str(f.get("ref")) for f in rows if f.get("type") == "snapshot"}, True

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
