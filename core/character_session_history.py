"""Session-pool image ledger; no disk scan and no persistent state.

Lock order: SESSION_POOL_LOCK -> character service _commit_lock -> result store
_mutation_lock. Result insertion acquires this order BEFORE taking the store lock;
nested retention reuses that thread's guard (the pool lock is not reentrant).
Saving and removal use the same
guard. Read-only store methods never acquire a pool/commit lock while holding the
store lock. Image encoding stays outside the guard; retention file writes remain
inside it to keep save-before-evict atomic. Helpers below require the guard.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlencode

def roll_name_token(prompt: str) -> str:
    """캐릭터 프롬프트의 이름 자리(맨 앞 머리말 girl / boy / other 다음 낱말) - 소문자 · SD 이스케이프(`\\(`) 를 걷는다."""
    tokens = [part.strip() for part in str(prompt or "").split(",") if part.strip()]
    if tokens and tokens[0].lower() in ("girl", "boy", "other"):
        tokens = tokens[1:]
    return tokens[0].replace("\\", "").lower() if tokens else ""


def _session_roster(context: Any) -> tuple[dict[str, Any] | None, Any]:
    """살아 있는 세션 와일드카드의 명단(이름 낱말 -> 그룹 · 캐릭터)과 와일드카드 관리자. 죽었으면 (None, 관리자)."""
    roster = getattr(context, "character_session_roster", None)
    manager = getattr(context, "wildcard_manager", None)
    live = getattr(manager, "session_wildcards", None) or {}
    if not isinstance(roster, dict) or roster.get("key") not in live:
        return None, manager
    return roster, manager


def _roll_identity(roster: dict[str, Any], prompt: str) -> tuple[str, str] | None:
    """프롬프트 -> (그룹, 캐릭터). 먼저 **줄 그대로**(같은 이름이 두 작품에 있어도 갈린다 - misumi uika), 안 되면 이름 자리로 -
    단 그 이름이 명단에서 **하나뿐**일 때만(둘 이상이면 어느 쪽인지 모른다 - 틀린 쪽에 별 · 숨김을 거느니 모른다고 한다)."""
    text = str(prompt or "").strip()
    lines = roster.get("lines") or {}          # 옵션이 바뀌면 새 사전으로 갈아 끼운다(`_rebuild_session_pool`) - 이 사전은 안 바뀐다
    if text in lines:
        # 풀의 줄 그대로다. None = 출력 옵션으로 둘 이상이 같은 줄이 됐다 - 이름으로 짐작하지 않는다(Codex 리뷰 15차:
        # `girl, shirayuki hime` 가 이름 사전의 다른 작품 캐릭터로 확정됐다).
        hit = lines[text]
        return tuple(hit) if hit else None
    # 랜덤 슬롯은 `__키__` 앞 · 뒤에 글을 붙일 수 있다(`smile, __키__`) - 그림의 글 **안에** 풀의 줄이 통째로 있으면 그것(긴 줄 먼저).
    # (값이 None 인 줄 = 출력 옵션으로 줄이 같아진 둘 이상 - 모른다.)
    #    ⚠️ 쉼표 토막 단위로 이어져 있어야 하고, 그 줄의 이름이 사전에서 **하나뿐**이어야 한다 - 짧은 줄이 다른 작품 같은 이름
    #    캐릭터 줄의 앞부분과 같을 수 있다(`girl, hello kitty (character)` - sanrio · vocaloid, Codex 리뷰).
    pieces = [piece.strip() for piece in text.split(",")]
    names = roster.get("names") or {}

    def contained(line: str) -> bool:
        want = [piece.strip() for piece in line.split(",")]
        return any(pieces[at:at + len(want)] == want for at in range(len(pieces) - len(want) + 1))

    inside = [line for line in lines if line and line in text and contained(line)]
    if inside:
        best = max(inside, key=len)
        owner = lines[best]
        if not owner:
            return None                    # 출력 옵션으로 같아진 줄 - 이름으로 짐작하지 않는다(Codex 리뷰 16차)
        original = any(line == best for line, _owner in roster.get("source") or [])
        # 원래 줄이면 그 이름이 사전에서 하나뿐이어야 한다(다른 작품 같은 이름의 앞부분일 수 있다 - hello kitty).
        # 옵션을 건 줄은 풀 안에서 같아지면 이미 None 이다.
        if not original or len(names.get(roll_name_token(best)) or []) == 1:
            return tuple(owner)
        return None
    # 줄이 그대로가 아니면(사람이 고친 그림 등) 쉼표 토막마다 이름을 찾는다 - 그 이름이 사전에서 **하나뿐**일 때만.
    for piece in text.split(","):
        owners = names.get(piece.strip().replace("\\", "").lower()) or []
        if len(owners) == 1:
            return tuple(owners[0])
    return None


HISTORY_CAP = 5000


def executed_pool_identity(context, roster, params):
    """Shared SRS2 ownership rule: current pool slot UUID AND unambiguous line."""
    from core.character_settings import _frame_uuid

    frames = context._character_service().settings_for(roster["mode"]).get("character_frames") or []
    owns = {str(_frame_uuid(frame) or "") for frame in frames
            if frame.get("session_wildcard")
            and f'__{roster["key"]}__' in str(frame.get("prompt") or "")}
    owns.discard("")
    ids = params.get("_executed_character_ids") or []
    prompts = params.get("_executed_characters") or []
    if not isinstance(ids, list) or not isinstance(prompts, list):
        return None
    for slot, prompt in zip(ids, prompts):
        if str(slot) in owns:
            identity = _roll_identity(roster, str(prompt))
            if identity is not None:
                return identity
    return None


def record_result(context, item):
    roster, _ = _session_roster(context)
    if roster is None:
        return
    identity = executed_pool_identity(context, roster, item.generation_params or {})
    if identity is None:
        return
    entries = roster.setdefault("history", {})
    entries[item.history_id] = {
        "history_id": item.history_id, "identity": identity,
        "created": item.created_at.isoformat(), "saved_path": None, "in_memory": True,
    }
    while len(entries) > HISTORY_CAP:
        del entries[next(iter(entries))]


def record_saved(context, item, filepath):
    roster, _ = _session_roster(context)
    entry = (roster.get("history") or {}).get(item.history_id) if roster else None
    if entry is not None:
        entry["saved_path"] = str(Path(filepath).resolve())


def record_removed(context, history_id, *, deleted=False):
    roster, _ = _session_roster(context)
    entries = (roster.get("history") or {}) if roster else {}
    if deleted:
        entries.pop(history_id, None)
    elif history_id in entries:
        # Unsaved tombstones are counted as lost, within the same bounded ledger.
        entries[history_id]["in_memory"] = False


def history_payload(roster):
    entries = list((roster.get("history") or {}).values())
    items = []
    counts = {}
    lost = 0
    for entry in reversed(entries):
        memory, saved = entry["in_memory"], bool(entry["saved_path"])
        if not memory and not saved:
            lost += 1
            continue
        history_id = entry["history_id"]
        identity = tuple(entry["identity"])
        counts[identity] = counts.get(identity, 0) + 1
        if memory:
            thumb = f"/api/history/thumb/{history_id}"
            full = f"/api/history/image/{history_id}"
        else:
            url = "/api/character-viewer/session-pool/file?" + urlencode(
                {"key": roster["pool_id"], "id": history_id})
            thumb, full = url + "&size=thumb", url + "&size=full"
        items.append({"id": history_id, "group": identity[0], "character": identity[1],
                      "created": entry["created"], "saved": saved, "in_memory": memory,
                      "thumbnail_url": thumb, "image_url": full})
    members = []
    seen = set()
    for _, owner in roster.get("source") or []:
        owner = tuple(owner)
        if owner not in seen and (owner in roster["present"] or owner in counts):
            seen.add(owner)
            members.append({"group": owner[0], "character": owner[1], "count": counts.get(owner, 0)})
    return {"key": roster["pool_id"], "total": len(items), "lost": lost,
            "members": members, "items": items}
