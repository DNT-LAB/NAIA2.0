"""Wire-Flow(조건부 와일드카드) 워크플로우 저장소 - user-data 의 JSON 한 파일(사용자 지시 2026-10-31).

노드(입력 · 조건 Switch · 처리 · 출력)를 선으로 잇는 그래프를 여러 벌 둔다. 목록은 **공용**이고(프리셋과 무관),
한 번에 **하나만** 쓴다(`active_id`). 모드(`mode_on`)가 켜지면 조건부 프롬프트가 일시 해제된다
(`conditional_prompt_runtime._active_settings` 가 `wireflow_mode_on` 을 본다).

⚠️ 초안 단계: 그래프는 저장만 한다 - 생성 파이프라인은 아직 그래프를 실행하지 않는다.
    노드 종류 · 포트 이름은 다음 단계(실행 엔진)의 입력이므로 여기 화이트리스트가 계약이다.

선(wire)은 **실행 흐름**이다: 노드는 공유 프롬프트 상태(메인 · 캐릭터 · 네거티브 · 변수)를 고치고 다음 노드로
넘긴다. Switch 만 갈래가 여럿이다 - if / elif 줄마다 `b1` `b2` … 하나씩 + `else`(줄 수만큼 포트가 생긴다).
옛 Switch · 태그 / Switch · 변수(예 / 아니오)는 읽을 때 Switch 로 옮긴다(예 -> b1 · 아니오 -> else).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
FILE_NAME = "wireflow_workflows.json"

# 노드 종류 -> (입력 포트, 출력 포트). 입력 노드는 흐름의 시작이라 입력 포트가 없다.
NODE_PORTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "input_main": ((), ("out",)),
    "input_character": ((), ("out",)),
    "switch": (("in",), ("else",)),          # + 조건 줄마다 b1 · b2 … (out_ports)
    "wildcard_open": (("in",), ("out",)),
    "tag_edit": (("in",), ("out",)),
    "var_set": (("in",), ("out",)),
    "output_prompt": (("in",), ("out",)),
    "output_negative": (("in",), ("out",)),
    "concat": (("in",), ("out",)),
    "instant_wildcard": (("in",), ("out",)),   # 노드 안 글칸에서 한 줄 - 흘러온 줄기에 끼운다
    "final_prompt": (("in",), ()),          # 끝 노드 - PE 선행/후행을 붙여 메인 프롬프트를 대치한다
}

MAX_WORKFLOWS = 200
MAX_NODES = 300
MAX_EDGES = 600
MAX_NAME = 60
MAX_PARAM_TEXT = 2000
MAX_LINES_TEXT = 20000      # 인스턴트 와일드카드 글칸 · Switch 조건 줄(줄 하나 = 후보 / 갈래 하나)
_LONG_TEXT_KEYS = {"lines", "conds"}
_BRANCH_PORT = re.compile(r"^b([1-9]\d*)$")
_OLD_SWITCH_PORTS = {"yes": "b1", "no": "else"}
MAX_PARAMS = 12
_COORD_LIMIT = 100_000


class WireFlowError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 거절."""


def _clean_name(value: Any) -> str:
    name = " ".join(str(value or "").split())
    if not name:
        raise WireFlowError("이름을 적어 주세요.")
    return name[:MAX_NAME]


def _clean_params(raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for key, value in list(raw.items())[:MAX_PARAMS]:
        key = str(key)[:40]
        if isinstance(value, bool) or value is None:
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = value if abs(value) < 1e12 else 0
        else:
            out[key] = str(value)[:MAX_LINES_TEXT if key in _LONG_TEXT_KEYS else MAX_PARAM_TEXT]
    return out


def switch_rows(params: Any) -> list[str]:
    """Switch 의 조건 줄 - 첫 줄 = if · 나머지 = elif. 빈 줄도 한 갈래다(줄이 곧 포트)."""
    text = params.get("conds") if isinstance(params, dict) else ""
    return str(text or "").replace("\r", "").split("\n")


def out_ports(kind: str, params: Any) -> tuple[str, ...]:
    if kind == "switch":
        return (*(f"b{n}" for n in range(1, len(switch_rows(params)) + 1)), "else")
    return NODE_PORTS[kind][1]


def _number_text(value: Any) -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "0"
    return str(int(num)) if num.is_integer() else f"{num:g}"


def _migrate_old_switch(node: dict[str, Any]) -> dict[str, Any] | None:
    """옛 Switch · 태그 / Switch · 변수 -> Switch 한 줄(if). 옮긴 게 아니면 None."""
    kind = node.get("type")
    if kind not in ("switch_tag", "switch_var"):
        return None
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    if kind == "switch_tag":
        cond = str(params.get("cond") or "").strip()
    else:
        name = str(params.get("var") or "").strip()
        cond = f"%{name} {params.get('op') or '>='} {_number_text(params.get('value'))}" if name else ""
    return {**node, "type": "switch", "params": {"conds": cond}}


def _clean_coord(value: Any) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    if num != num:  # NaN
        return 0.0
    return round(max(-_COORD_LIMIT, min(_COORD_LIMIT, num)), 1)


def clean_graph(raw: Any) -> dict[str, Any]:
    """화면이 보낸 그래프를 계약 모양으로 거른다. 모르는 노드 종류 · 없는 포트를 잇는 선은 거절한다."""
    if not isinstance(raw, dict):
        raise WireFlowError("그래프 형식이 아닙니다.")
    nodes_in = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    edges_in = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    if len(nodes_in) > MAX_NODES:
        raise WireFlowError(f"노드는 최대 {MAX_NODES}개입니다.")
    if len(edges_in) > MAX_EDGES:
        raise WireFlowError(f"선은 최대 {MAX_EDGES}개입니다.")
    nodes: list[dict[str, Any]] = []
    kinds: dict[str, str] = {}
    ports: dict[str, tuple[str, ...]] = {}
    migrated: set[str] = set()
    for node in nodes_in:
        if not isinstance(node, dict):
            raise WireFlowError("노드 형식이 아닙니다.")
        moved = _migrate_old_switch(node)
        if moved is not None:
            node = moved
            migrated.add(str(node.get("id") or "")[:40])
        kind = str(node.get("type") or "")
        if kind not in NODE_PORTS:
            raise WireFlowError(f"모르는 노드 종류입니다: {kind[:40]}")
        node_id = str(node.get("id") or "")[:40]
        if not node_id or node_id in kinds:
            raise WireFlowError("노드 id 가 비었거나 겹칩니다.")
        kinds[node_id] = kind
        params = _clean_params(node.get("params"))
        ports[node_id] = out_ports(kind, params)
        nodes.append({"id": node_id, "type": kind, "x": _clean_coord(node.get("x")),
                      "y": _clean_coord(node.get("y")), "params": params})
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for edge in edges_in:
        if not isinstance(edge, dict):
            raise WireFlowError("선 형식이 아닙니다.")
        src, dst = edge.get("from") or {}, edge.get("to") or {}
        if not isinstance(src, dict) or not isinstance(dst, dict):
            raise WireFlowError("선 형식이 아닙니다.")
        a, ap = str(src.get("node") or ""), str(src.get("port") or "")
        b, bp = str(dst.get("node") or ""), str(dst.get("port") or "")
        if a in migrated:
            ap = _OLD_SWITCH_PORTS.get(ap, ap)
        if a not in kinds or b not in kinds:
            raise WireFlowError("선이 없는 노드를 가리킵니다.")
        if a == b:
            raise WireFlowError("노드를 자기 자신에 이을 수 없습니다.")
        if ap not in ports[a] or bp not in NODE_PORTS[kinds[b]][0]:
            raise WireFlowError("없는 포트를 잇는 선입니다.")
        key = (a, ap, b, bp)
        if key in seen:
            continue
        seen.add(key)
        edge_id = str(edge.get("id") or "")[:40] or uuid.uuid4().hex[:10]
        edges.append({"id": edge_id, "from": {"node": a, "port": ap}, "to": {"node": b, "port": bp}})
    return {"nodes": nodes, "edges": edges}


def _summary(workflow: dict[str, Any]) -> dict[str, Any]:
    return {"id": workflow["id"], "name": workflow["name"], "updated": workflow.get("updated", 0),
            "nodes": len(workflow.get("nodes") or [])}


class WireFlowStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None

    # ── 파일 ────────────────────────────────────────────────────────────
    def _read(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        data: dict[str, Any] = {"mode_on": False, "active_id": "", "workflows": []}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = None
        except (OSError, ValueError):
            raw = None      # 상한 파일 - 빈 목록으로 산다(다음 저장이 새로 쓴다)
        if isinstance(raw, dict):
            data["mode_on"] = raw.get("mode_on") is True
            workflows = []
            ids: set[str] = set()
            for wf in raw.get("workflows") if isinstance(raw.get("workflows"), list) else []:
                try:
                    graph = clean_graph(wf)
                    name = _clean_name(wf.get("name"))
                except (WireFlowError, AttributeError):
                    continue    # 한 벌이 상해도 나머지는 산다
                wf_id = str(wf.get("id") or "")[:40]
                if not wf_id or wf_id in ids:
                    continue
                ids.add(wf_id)
                updated = wf.get("updated") if isinstance(wf.get("updated"), (int, float)) else 0
                workflows.append({"id": wf_id, "name": name, "updated": updated, **graph})
            data["workflows"] = workflows
            active = str(raw.get("active_id") or "")
            data["active_id"] = active if active in ids else ""
        self._cache = data
        return data

    def _write(self, data: dict[str, Any]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": SCHEMA_VERSION, **data}, ensure_ascii=False, indent=1) + "\n"
        temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        try:
            os.replace(temp_path, path)
        except PermissionError:
            path.write_text(payload, encoding="utf-8")
            try:
                temp_path.unlink(missing_ok=True)
            except PermissionError:
                pass
        self._cache = data

    def _find(self, data: dict[str, Any], wf_id: Any) -> dict[str, Any]:
        wf_id = str(wf_id or "")
        for wf in data["workflows"]:
            if wf["id"] == wf_id:
                return wf
        raise WireFlowError("이미 지워졌거나 없는 워크플로우입니다.")

    # ── 읽기 ────────────────────────────────────────────────────────────
    def state(self) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            return {"mode_on": data["mode_on"], "active_id": data["active_id"],
                    "workflows": [_summary(wf) for wf in data["workflows"]]}

    def mode_on(self) -> bool:
        with self._lock:
            return bool(self._read()["mode_on"])

    def get(self, wf_id: Any) -> dict[str, Any]:
        with self._lock:
            wf = self._find(self._read(), wf_id)
            return json.loads(json.dumps(wf))

    # ── 쓰기 ────────────────────────────────────────────────────────────
    def save_new(self, name: Any, graph: Any) -> str:
        clean = clean_graph(graph if graph is not None else {})
        name = _clean_name(name)
        with self._lock:
            data = self._read()
            if len(data["workflows"]) >= MAX_WORKFLOWS:
                raise WireFlowError(f"워크플로우는 최대 {MAX_WORKFLOWS}개입니다.")
            wf_id = uuid.uuid4().hex[:12]
            workflows = [*data["workflows"], {"id": wf_id, "name": name, "updated": int(time.time()), **clean}]
            self._write({**data, "workflows": workflows})
            return wf_id

    def save(self, wf_id: Any, graph: Any) -> None:
        clean = clean_graph(graph)
        with self._lock:
            data = self._read()
            target = self._find(data, wf_id)
            workflows = [{**wf, **clean, "updated": int(time.time())} if wf is target else wf
                         for wf in data["workflows"]]
            self._write({**data, "workflows": workflows})

    def rename(self, wf_id: Any, name: Any) -> None:
        name = _clean_name(name)
        with self._lock:
            data = self._read()
            target = self._find(data, wf_id)
            workflows = [{**wf, "name": name} if wf is target else wf for wf in data["workflows"]]
            self._write({**data, "workflows": workflows})

    def delete(self, wf_id: Any) -> None:
        with self._lock:
            data = self._read()
            target = self._find(data, wf_id)
            workflows = [wf for wf in data["workflows"] if wf is not target]
            active = "" if data["active_id"] == target["id"] else data["active_id"]
            self._write({**data, "workflows": workflows, "active_id": active})

    def activate(self, wf_id: Any) -> None:
        """하나만 쓴다 - 빈 값이면 아무것도 안 쓴다."""
        with self._lock:
            data = self._read()
            active = self._find(data, wf_id)["id"] if wf_id else ""
            self._write({**data, "active_id": active})

    def set_mode(self, on: Any) -> None:
        with self._lock:
            data = self._read()
            self._write({**data, "mode_on": on is True})


def wireflow_store(context: Any) -> WireFlowStore | None:
    """세션 컨텍스트에 붙은 저장소. 저장 경로를 모르는 컨텍스트(가짜 · 시험)면 None."""
    store = getattr(context, "wireflow_store", None)
    if isinstance(store, WireFlowStore):
        return store
    save_path = getattr(context, "_save_path", None)
    if not callable(save_path):
        return None
    try:
        store = WireFlowStore(save_path(FILE_NAME))
    except Exception:
        return None
    try:
        context.wireflow_store = store
    except Exception:
        pass
    return store


def wireflow_mode_on(context: Any) -> bool:
    """Wire-Flow 모드가 켜져 있나 - 켜져 있으면 조건부 프롬프트는 일시 해제된다."""
    store = wireflow_store(context)
    if store is None:
        return False
    try:
        return store.mode_on()
    except Exception:
        return False
