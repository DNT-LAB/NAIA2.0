"""Generic agent transport over registered NAIA HTTP and WebSocket operations.

No service-method reflection, ad-hoc provider credentials or alternate generation
pipeline: the live backend remains the state, credential and lifecycle owner.
"""
from __future__ import annotations

import json
from pathlib import Path
import queue
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

from core.agent_catalog import audit, describe, listing, overview, runtime_catalog, source_catalog
from core.agent_protocol import ACK_TYPE, CALL_ID_KEY, sanitize, secret_values


class AgentCallError(ValueError):
    def __init__(self, message, *, code="agent_call_failed", details=None):
        super().__init__(message)
        self.code, self.details = code, details


def read_input(value):
    import sys
    if value == "-":
        raw = sys.stdin.read()
    elif value.startswith("@"):
        raw = Path(value[1:]).expanduser().read_text(encoding="utf-8-sig")
    else:
        raw = value
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise AgentCallError("Input must be valid JSON (inline, @file, or - for stdin)", code="invalid_request") from exc


def write_new(path, data):
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as file:
            file.write(data)
    except FileExistsError as exc:
        raise AgentCallError("Output exists; choose a new path", code="output_exists") from exc
    return str(target)


class AgentClient:
    def __init__(self, root, server="http://127.0.0.1:7243", timeout=60):
        import requests
        parts = urlsplit(server)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise AgentCallError("--server must be an HTTP(S) origin without credentials, query or fragment", code="invalid_arguments")
        if parts.path not in {"", "/"}:
            raise AgentCallError("--server must be an origin, without a path", code="invalid_arguments")
        if not 0 < timeout <= 3600:
            raise AgentCallError("--timeout must be in (0, 3600]", code="invalid_arguments")
        self.root = Path(root)
        self.server = server.rstrip("/")
        self.timeout = timeout
        self.http = requests.Session()
        self.http.trust_env = False  # Local backend traffic must not leak to a proxy.
        self.socket = None
        self.secrets = []
        self.protocol_available = None
        self.fallback = None
        self._descriptions = {}
        self._reader = None
        self._reader_stop = threading.Event()
        self._frames = queue.Queue(maxsize=512)
        self._dropped_frames = 0

    def close(self):
        self._reader_stop.set()
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self._reader is not None:
            self._reader.join(timeout=2)
        self.http.close()

    def _request(self, method, path, **kwargs):
        import requests
        try:
            return self.http.request(method, self.server + path, timeout=self.timeout, allow_redirects=False, **kwargs)
        except requests.RequestException as exc:
            raise AgentCallError("Backend request failed or timed out; a submitted mutation may still be running. Do not retry blindly.",
                                 code="transport_failed", details={"submitted": method not in {"GET", "HEAD"}}) from exc

    def _discovery(self, path, params):
        response = self._request("GET", path, params=params)
        if response.status_code == 404:
            self.protocol_available = False
            return None
        if not response.ok:
            raise AgentCallError(f"Discovery returned HTTP {response.status_code}", code="discovery_failed")
        body = response.json()
        self.protocol_available = True
        return body

    def _legacy_catalog(self):
        if self.fallback is None:
            response = self._request("GET", "/openapi.json")
            if not response.ok:
                raise AgentCallError("Backend exposes neither agent discovery nor OpenAPI", code="discovery_unavailable")
            self.fallback = runtime_catalog(source_catalog(self.root), response.json())
            for identifier, entry in list(self.fallback["entries"].items()):
                if entry.get("transport", {}).get("type") == "websocket":
                    self.fallback["entries"][identifier] = {**entry, "callable": False,
                        "availability": "target_needs_agent_protocol", "unavailable_reason": "Restart an updated backend for correlated WebSocket calls"}
        return self.fallback

    def capabilities(self, *, query="", kind="", offset=0, limit=30):
        body = self._discovery("/api/agent/catalog", {"q": query, "kind": kind, "offset": offset, "limit": limit})
        return body if body is not None else listing(self._legacy_catalog(), query=query, kind=kind, offset=offset, limit=limit)

    def describe(self, identifier):
        if identifier not in self._descriptions:
            body = self._discovery("/api/agent/catalog", {"id": identifier})
            self._descriptions[identifier] = body["capability"] if body is not None else describe(self._legacy_catalog(), identifier)
        return self._descriptions[identifier]

    def overview(self):
        body = self._discovery("/api/agent/catalog", {"view": "overview"})
        return body if body is not None else overview(self._legacy_catalog())

    def audit(self, details=False):
        body = self._discovery("/api/agent/audit", {"details": str(details).lower()})
        if body is not None:
            return body
        result = audit(self._legacy_catalog())
        result["target_protocol"] = "unavailable; HTTP discovery fallback only"
        if not details:
            result = {k: v for k, v in result.items() if k not in {"files", "gaps"}}
        return result

    def call(self, identifier, payload=None, *, output=None, observe=0):
        payload = {} if payload is None else payload
        if not isinstance(payload, dict):
            raise AgentCallError("Capability input must be a JSON object", code="invalid_request")
        if not 0 <= observe <= 300:
            raise AgentCallError("Observation duration must be 0..300 seconds", code="invalid_request")
        if output and Path(output).expanduser().exists():
            raise AgentCallError("Output exists; choose a new path", code="output_exists")
        self.secrets.extend(secret_values(payload))
        entry = self.describe(identifier)
        if not entry.get("callable"):
            raise AgentCallError(entry.get("unavailable_reason") or entry.get("availability") or "Capability has no callable transport",
                                 code="not_callable", details={"id": identifier, "related": entry.get("related", [])})
        transport = entry.get("transport", {})
        self._check_setup(identifier, payload)
        if transport.get("type") == "http":
            return self._call_http(entry, payload, output=output)
        if transport.get("type") == "websocket":
            if output:
                raise AgentCallError("WebSocket call returns events; download the result through its discovered HTTP image endpoint", code="invalid_request")
            return self._call_websocket(entry, payload, observe=observe)
        raise AgentCallError("No supported transport; source symbols cannot be invoked by reflection", code="not_callable")

    def _check_setup(self, identifier, payload):
        from core.agent_setup import capability_assets, download_asset_id, request_assets, SetupRequired
        download = download_asset_id(identifier, payload)
        required = capability_assets(identifier, payload)
        if not download and not required:
            return
        catalog = self._discovery("/api/agent/assets", {})
        if catalog is None:
            raise AgentCallError("This backend cannot report asset prerequisites. Update it or inspect its installation manager before continuing.",
                                 code="setup_preflight_unavailable", details={"id": identifier, "submitted": False})
        by_id = {row["id"]: row for row in catalog["items"]}
        try:
            if download:
                if download in by_id:
                    request_assets(catalog, [download], reason="use_blocking_asset_installer",
                                   request={"id": identifier, "input": payload})
                raise AgentCallError("This installation needs explicit user approval and its owning installer. Generic CLI calls do not start unmanaged downloads.",
                                     code="download_approval_required", details={"id": identifier, "requires_user_input": True, "submitted": False})
            unknown = [key for key in required if key not in by_id]
            if unknown:
                raise AgentCallError("Select a concrete dataset from the asset catalog before using this operation.",
                                     code="asset_selection_required", details={"requested": unknown, "catalog": catalog, "submitted": False})
            missing = [key for key in required if not by_id[key]["ready"]]
            if missing:
                request_assets(catalog, missing, request={"id": identifier, "input": payload})
        except SetupRequired as exc:
            raise AgentCallError(str(exc), code=exc.code, details={**exc.details, "submitted": False}) from exc

    def _call_http(self, entry, payload, *, output):
        allowed = {"path", "query", "json", "body_file", "content_type", "headers"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise AgentCallError(f"Unknown HTTP input sections: {', '.join(unknown)}", code="invalid_request")
        path_values, query = payload.get("path", {}), payload.get("query", {})
        headers = payload.get("headers", {})
        if not all(isinstance(item, dict) for item in (path_values, query, headers)):
            raise AgentCallError("path, query and headers must be objects", code="invalid_request")
        route = entry["transport"]["path"]
        import re
        names = set()
        def substitute(match):
            name, _, converter = match.group(1).partition(":")
            names.add(name)
            if name not in path_values:
                raise AgentCallError(f"Missing path parameter: {name}", code="invalid_request")
            return quote(str(path_values[name]), safe="/" if converter == "path" else "")
        route = re.sub(r"\{([^}]+)\}", substitute, route)
        if set(path_values) - names:
            raise AgentCallError("Unknown path parameters", code="invalid_request")
        if "json" in payload and "body_file" in payload:
            raise AgentCallError("json and body_file are mutually exclusive", code="invalid_request")
        request = {"params": query, "headers": dict(headers)}
        if "json" in payload:
            request["json"] = payload["json"]
        if "body_file" in payload:
            request["data"] = Path(payload["body_file"]).expanduser().read_bytes()
            request["headers"]["Content-Type"] = str(payload.get("content_type") or "application/octet-stream")
        response = self._request(entry["transport"]["method"], route, **request)
        content_type = response.headers.get("Content-Type", "")
        try:
            data = sanitize(response.json(), self.secrets)
            is_json = True
        except (ValueError, TypeError):
            data, is_json = None, False
        result = {"id": entry["id"], "transport": "http", "http_status": response.status_code,
                  "content_type": content_type, "operation_complete": "unknown; inspect endpoint response",
                  "response": data if is_json else {"bytes": len(response.content), "binary": True}}
        if not response.ok or 300 <= response.status_code < 400:
            if response.status_code == 404 and entry["id"] == "http:GET:/api/character-viewer/thumbnail":
                from core.agent_setup import request_assets, SetupRequired
                catalog = self._discovery("/api/agent/assets", {})
                pack = next((r for r in (catalog or {}).get("items", []) if r["id"] == "character_pack"), None)
                if pack and not pack["ready"] and pack.get("downloadable"):
                    try:
                        request_assets(catalog, ["character_pack"], reason="optional_thumbnail_pack_missing",
                                       request={"id": entry["id"], "input": payload})
                    except SetupRequired as exc:
                        raise AgentCallError(str(exc), code=exc.code, details={**exc.details,
                            "note": "No local thumbnail was found. The optional expansion may provide it; coverage of this specific character is not guaranteed.",
                            "response": result}) from exc
            raise AgentCallError(f"Operation returned HTTP {response.status_code}", details=result)
        if output:
            contents = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8") if is_json else response.content
            result["output"] = write_new(output, contents)
        elif not is_json:
            result["download_hint"] = "Repeat with --output to save binary content; do not repeat a mutating operation just to download its result"
        return result

    def _connect(self):
        if self.socket is not None:
            return
        if not self.protocol_available:
            raise AgentCallError("Updated backend with agent correlation is required", code="protocol_unavailable")
        import websocket
        parts = urlsplit(self.server)
        url = urlunsplit(("wss" if parts.scheme == "https" else "ws", parts.netloc, "/ws", "", ""))
        self.socket = websocket.create_connection(url, timeout=self.timeout, http_no_proxy=[parts.hostname])

    def _start_reader(self):
        if self._reader is not None:
            return
        import websocket
        self.socket.settimeout(self.timeout)
        sock = self.socket

        def enqueue(kind, value):
            try:
                self._frames.put_nowait((kind, value))
            except queue.Full:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    pass
                self._dropped_frames += 1
                self._frames.put_nowait((kind, value))

        def read():
            while not self._reader_stop.is_set():
                try:
                    raw = sock.recv()  # websocket-client answers ping frames here.
                except websocket.WebSocketTimeoutException:
                    self._reader_stop.wait(.01)
                    continue
                except Exception as exc:
                    enqueue("error", type(exc).__name__)
                    return
                if raw == "":
                    enqueue("closed", None)
                    return
                if isinstance(raw, bytes):
                    raw = json.dumps({"type": "binary_frame", "bytes": len(raw)})
                enqueue("frame", raw)

        self._reader = threading.Thread(target=read, name="naia-agent-ws-reader", daemon=True)
        self._reader.start()

    def _call_websocket(self, entry, payload, *, observe):
        self._connect()
        base = entry["transport"]["command"]
        for key, value in base.items():
            if key in payload and payload[key] != value:
                raise AgentCallError(f"Input cannot override capability selector {key}", code="invalid_request")
        if any(key.startswith("_agent_") or key in {"_seq", "_seq_guard", "_tag_filter_client_key"} for key in payload):
            raise AgentCallError("Internal scheduling/correlation fields cannot be supplied", code="invalid_request")
        if entry["kind"] == "module" and entry["id"].endswith(":set") and not {"key", "value"} <= payload.keys():
            raise AgentCallError("Module set requires key and value", code="invalid_request")
        call_id = uuid.uuid4().hex
        command = {**payload, **base, CALL_ID_KEY: call_id}
        if self._reader is not None and not self._reader.is_alive():
            raise AgentCallError("WebSocket session closed before submission; inspect state in a new session before continuing",
                                 code="session_closed", details={"submitted": False})
        try:
            self.socket.send(json.dumps(command, ensure_ascii=False))
        except Exception as exc:
            raise AgentCallError("WebSocket submission failed; command may have executed. Do not retry blindly.",
                                 code="transport_failed", details={"call_id": call_id, "submitted": "unknown"}) from exc
        self._start_reader()
        direct, observed = [], []
        deadline = time.monotonic() + self.timeout
        ack = None
        while time.monotonic() < deadline:
            try:
                kind, raw = self._frames.get(timeout=max(.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if kind != "frame":
                break
            if not isinstance(raw, str):
                if len(observed) < 100:
                    observed.append({"type": "binary_frame", "bytes": len(raw)})
                continue
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(frame, dict):
                continue
            # 짝 판정은 가리기 전의 원본 필드로 한다 - 가린 뒤에 견주면 비밀값 치환이 ID 를 바꿔 ACK 를 놓친다(NEW-1).
            frame_call_id = frame.get(CALL_ID_KEY)
            frame = sanitize(frame, self.secrets)
            if frame_call_id == call_id:
                if frame.get("type") == ACK_TYPE:
                    ack = frame
                    if not observe:
                        break
                    deadline = time.monotonic() + observe
                elif len(direct) < 200:
                    direct.append(frame)
            elif ack is not None and len(observed) < 100:
                observed.append(frame)
        result = {"id": entry["id"], "transport": "websocket", "call_id": call_id,
                  "dispatch_complete": ack is not None, "operation_complete": False,
                  "messages": direct, "observed_broadcasts": observed,
                  "dropped_frames": self._dropped_frames,
                  "observation_note": "Broadcasts may belong to other callers; use generation/request IDs to correlate. Background work may outlive this command."}
        if ack is None:
            raise AgentCallError("No dispatch acknowledgment before timeout; command may have executed. Do not retry blindly.", code="dispatch_timeout", details=result)
        if ack.get("error"):
            raise AgentCallError(ack["error"], details=result)
        result["acknowledgment"] = ack
        return result


def run_discovery_command(args, root, secrets):
    if getattr(args, "standalone", False):
        from core.agent_local_session import local_agent_client
        with local_agent_client(args, root, secrets) as (client, session):
            result = _run_connected_command(args, client)
            result["execution_session"] = session
    elif args.command == "capabilities" and not args.server:
        catalog = source_catalog(root)
        if args.action == "describe":
            if not args.query:
                raise AgentCallError("describe requires a capability ID", code="invalid_arguments")
            result = describe(catalog, args.query)
        elif args.action == "overview":
            result = overview(catalog)
        elif args.action == "audit":
            result = audit(catalog)
            if not args.details and not args.output:
                result = {k: v for k, v in result.items() if k not in {"gaps", "files"}}
        else:
            result = listing(catalog, query=args.query, kind=args.kind, offset=args.offset, limit=args.limit)
    else:
        client = AgentClient(root, args.server or "http://127.0.0.1:7243", args.timeout)
        try:
            result = _run_connected_command(args, client)
        finally:
            secrets.extend(client.secrets)
            client.close()
    if args.command == "capabilities" and args.output:
        output = write_new(args.output, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
        return {"output": output, "counts": result.get("counts"), "fingerprint": result.get("fingerprint")}
    return result


def _run_connected_command(args, client):
    if args.command == "capabilities":
        if args.action == "describe":
            return client.describe(args.query)
        if args.action == "overview":
            return client.overview()
        if args.action == "audit":
            return client.audit(details=args.details or bool(args.output))
        return client.capabilities(query=args.query, kind=args.kind, offset=args.offset, limit=args.limit)
    if args.command == "call":
        return client.call(args.capability, read_input(args.input), output=args.output, observe=args.observe)
    calls = read_input(args.input)
    if not isinstance(calls, list) or not 1 <= len(calls) <= 100:
        raise AgentCallError("Batch input must be an array of 1..100 calls", code="invalid_request")
    results = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("id"), str):
            raise AgentCallError("Each batch item needs an id and optional input/output/observe", code="invalid_request", details={"completed": results})
        try:
            results.append(client.call(call["id"], call.get("input", {}), output=call.get("output"), observe=call.get("observe", args.observe)))
        except AgentCallError as exc:
            raise AgentCallError(str(exc), code=exc.code, details={"completed": results, "failed": exc.details}) from exc
    return {"calls": results, "session": "One WebSocket connection; backend state lasts for the selected session. Temporary search workspace ends on disconnect."}
