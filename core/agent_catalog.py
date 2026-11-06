"""Discover capabilities from source and registered transports, without importing services.

An inventory is not a claim that every public Python method is a product feature.
Only HTTP routes and dispatcher-backed WebSocket/module operations are callable.
Source-only symbols, unresolved schemas and frontend references remain visible in
the audit instead of disappearing behind a hand-written CLI allowlist.
"""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any

SOURCE_ROOTS = ("app", "core", "interfaces", "utils", "tools", "mcps")
CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".html"}
SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__", ".git", ".venv", "venv"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_CACHE: dict[str, Any] = {}
_LOCK = threading.RLock()


def source_files(root: Path) -> list[Path]:
    paths = {p for p in root.iterdir() if p.is_file() and p.suffix in CODE_SUFFIXES}
    for name in SOURCE_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        # Do not descend into generated/package trees, which can contain tens of
        # thousands of duplicate files in a maintainer's working checkout.
        import os
        for directory, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
            for filename in sorted(files):
                path = Path(directory) / filename
                if path.suffix in CODE_SUFFIXES:
                    paths.add(path)
    return sorted(paths)


def _literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return default


def _text(node):
    return ast.unparse(node) if node is not None else ""


def _location(file, node):
    return {"file": file, "line": getattr(node, "lineno", 1)}


def _signature(node):
    args = [*node.args.posonlyargs, *node.args.args]
    defaults = [None] * (len(args) - len(node.args.defaults)) + list(node.args.defaults)
    result = []
    for arg, default in [*zip(args, defaults), *zip(node.args.kwonlyargs, node.args.kw_defaults)]:
        if arg.arg in {"self", "cls"}:
            continue
        item = {"name": arg.arg, "annotation": _text(arg.annotation), "required": default is None}
        if default is not None:
            item["default_expression"] = _text(default)
        result.append(item)
    if node.args.kwarg:
        result.append({"name": node.args.kwarg.arg, "annotation": "**kwargs", "required": False})
    return result


def _input_hints(node):
    """Observed dictionary accesses, deliberately not a fabricated JSON Schema."""
    found = {}
    for child in ast.walk(node):
        receiver = key = None
        default = None
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "get" and child.args:
            key = _literal(child.args[0])
            receiver = _text(child.func.value)
            if len(child.args) > 1:
                default = _text(child.args[1])
        elif isinstance(child, ast.Subscript):
            key = _literal(child.slice)
            receiver = _text(child.value)
        if isinstance(key, str) and receiver and any(
            word in receiver.lower() for word in ("payload", "command", "body", "request", "data", "value", "options")
        ):
            found[(receiver, key)] = {"object": receiver, "key": key, "line": child.lineno,
                                      "default_expression": default, "required": "unknown"}
    return list(found.values())


def _actions(node, constants=None):
    constants = constants or {}
    literals, patterns = set(), set()
    names = {"key", "clean_key", "action", "command_type", "ctype", "kind", "clean_id", "module_id"}
    for child in ast.walk(node):
        if isinstance(child, ast.Compare) and isinstance(child.left, ast.Name) and child.left.id in names:
            for comparator in child.comparators:
                value = constants.get(comparator.id) if isinstance(comparator, ast.Name) else _literal(comparator)
                if isinstance(value, str):
                    literals.add(value)
                elif isinstance(value, (list, tuple, set, dict)):
                    literals.update(v for v in value if isinstance(v, str))
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "startswith":
            if isinstance(child.func.value, ast.Name) and child.func.value.id in names and child.args:
                value = _literal(child.args[0])
                for item in value if isinstance(value, (tuple, list)) else [value]:
                    if isinstance(item, str):
                        patterns.add(item + "*")
    return {"literal_keys": sorted(literals), "prefix_patterns": sorted(patterns),
            "completeness": "static_hints; delegated, computed and extension-defined keys may be absent"}


def _effects(label: str, method=""):
    words = label.lower()
    hints = []
    for pattern, effect in ((r"generat|encode|upscale|outpaint|inpaint|director", "provider_or_compute"),
                            (r"delete|remove|clear|reset|purge|logout", "destructive_possible"),
                            (r"save|upload|import|export|write|install|download|update|rename|migrat", "filesystem_or_network"),
                            (r"token|credential|auth|api_verify|account|proxy", "authentication_sensitive")):
        if re.search(pattern, words):
            hints.append(effect)
    if method and method not in {"GET", "HEAD", "OPTIONS"}:
        hints.append("state_change_possible")
    return {"hints": hints, "certainty": "heuristic", "read_only_guaranteed": False}


def _base(identifier, kind, name, source, doc=""):
    return {"id": identifier, "kind": kind, "name": name, "description": doc or name.replace("_", " "),
            "source": source, "callable": False, "availability": "source_only",
            "effects": _effects(name), "related": []}


def _frontend_inventory(content, relative):
    """Lexical evidence, not a JS parser or a claim of UI reachability."""
    records = []
    patterns = (
        ("module_call", r"setModuleParam\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]"),
        ("shell_ipc", r"ipcMain\.(?:handle|on)\(\s*['\"]([^'\"]+)['\"]"),
        ("export", r"export\s+(?:async\s+)?function\s+(\w+)\s*\("),
    )
    for category, expression in patterns:
        for match in re.finditer(expression, content):
            line = content.count("\n", 0, match.start()) + 1
            kind = "shell" if category == "shell_ipc" else "frontend"
            label = " ".join(match.groups())
            identifier = f"{kind}:{relative}:{category}:{line}:{match.group(1)}"
            entry = _base(identifier, kind, label, {"file": relative, "line": line})
            entry.update(evidence={"type": category, "text": match.group(0), "certainty": "lexical"},
                         unavailable_reason="Browser/Electron/source-only surface; no backend transport is asserted")
            if category == "module_call":
                entry["module_id"], entry["action_key"] = match.groups()
                entry["related"] = [f"module:{match.group(1)}:set"]
                entry["unavailable_reason"] = "Frontend callsite; use the linked module capability and inspect its action schema"
            records.append(entry)
    browser_evidence = {
        "clipboard": r"navigator\.clipboard|document\.execCommand\(['\"]copy",
        "canvas": r"\.getContext\(['\"]2d|\.toDataURL\(|\.toBlob\(",
        "local_preferences": r"localStorage\.(?:getItem|setItem|removeItem)|sessionStorage\.",
        "browser_files": r"new FileReader\b|new Blob\b|URL\.createObjectURL\(",
        "popup_window": r"window\.open\(|window\.close\(",
        "viewport": r"requestFullscreen\(|visualViewport\.|setPointerCapture\(",
    }
    for category, expression in browser_evidence.items():
        hits = list(re.finditer(expression, content))
        if hits:
            line = content.count("\n", 0, hits[0].start()) + 1
            entry = _base(f"frontend:{relative}:browser:{category}", "frontend", category, {"file": relative, "line": line})
            entry.update(evidence={"type": "browser_affordance", "apis": sorted({h.group(0) for h in hits}), "occurrences": len(hits), "certainty": "lexical"},
                         unavailable_reason="Browser-local behavior; no corresponding backend operation has been established")
            records.append(entry)
    return records


def _build_source_catalog(root: Path, files: list[Path], fingerprint: str):
    entries, records, errors, trees, constants_by_file = {}, [], [], {}, {}
    frontend_refs, dynamic_refs, development_refs, route_locations = [], [], [], set()
    command_sets = {}
    module_branches = []
    symbols = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        record = {"file": relative, "sha256": hashlib.sha256(content.encode()).hexdigest(),
                  "role": "development" if relative.startswith("tools/") else "runtime",
                  "language": "python" if path.suffix == ".py" else "frontend_or_shell"}
        records.append(record)
        if path.suffix != ".py":
            refs = re.finditer(r"[\"'`](/api/[^\"'`\s]*)[\"'`]", content)
            for match in refs:
                item = {"path": match.group(1).split("?")[0], "file": relative,
                        "line": content.count("\n", 0, match.start()) + 1}
                target = development_refs if record["role"] == "development" else dynamic_refs if "${" in item["path"] else frontend_refs
                target.append(item)
            if record["role"] == "runtime":
                for entry in _frontend_inventory(content, relative):
                    entries[entry["id"]] = entry
            record["coverage"] = "text_references_only"
            continue
        try:
            tree = ast.parse(content, filename=relative)
        except SyntaxError as exc:
            record["coverage"] = "parse_failed"
            errors.append({"file": relative, "line": exc.lineno, "message": exc.msg})
            continue
        record["coverage"] = "ast"
        trees[relative] = tree
        constants = {}
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = _literal(node.value)
                for target in targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = value
                        if relative.startswith("app/backend/server/") and target.id.endswith("COMMAND_TYPES") and isinstance(value, (set, list, tuple)):
                            command_sets[target.id] = (value, relative, node.lineno)
        constants_by_file[relative] = constants
        # Public Python symbols are searchable but never made callable by reflection.
        module = relative[:-3].replace("/", ".")
        for owner in tree.body:
            members = owner.body if isinstance(owner, ast.ClassDef) else [owner]
            for node in members:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                qualified = (owner.name + "." if isinstance(owner, ast.ClassDef) else "") + node.name
                symbols[(relative, qualified)] = node
                if node.name.startswith("_"):
                    continue
                identifier = f"python:{module}:{qualified}"
                doc = (ast.get_docstring(node) or "").strip()
                entry = _base(identifier, "python", qualified, _location(relative, node), doc)
                entry.update(parameters=_signature(node), return_annotation=_text(node.returns),
                             unavailable_reason="Internal source symbol; use a linked registered transport. No arbitrary Python invocation.",
                             role=record["role"])
                entries[identifier] = entry
        for node in ast.walk(tree):
            if record["role"] != "runtime":
                break
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr
                if method not in HTTP_METHODS or not decorator.args:
                    continue
                route = _literal(decorator.args[0])
                if not isinstance(route, str):
                    errors.append({"file": relative, "line": decorator.lineno, "message": "dynamic route path"})
                    continue
                if not route.startswith("/api/"):
                    continue
                identifier = f"http:{method.upper()}:{route}"
                entry = _base(identifier, "http", node.name, _location(relative, node), ast.get_docstring(node) or "")
                entry.update(callable=True, availability="source_declared; runtime_registration_unverified",
                             transport={"type": "http", "method": method.upper(), "path": route},
                             parameters=_signature(node), input_hints=_input_hints(node),
                             schema_status="source_hints_only", effects=_effects(route, method.upper()),
                             completion="HTTP response; generation/background work may only be accepted")
                if identifier in entries:
                    entry["duplicate_declarations"] = [entries[identifier]["source"], entry["source"]]
                entries[identifier] = entry
                route_locations.add((relative, node.lineno))

    # Use the actual dispatcher's referenced command families, not all unrelated
    # *_TYPES constants (scheduling sets aren't registrations).
    dispatch_file = "app/backend/server/websocket_session.py"
    dispatch_tree = trees.get(dispatch_file)
    referenced = set()
    if dispatch_tree:
        for function in dispatch_tree.body:
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) and function.name == "_dispatch_json_command":
                for node in ast.walk(function):
                    if isinstance(node, ast.Compare):
                        referenced.update(c.id for c in node.comparators if isinstance(c, ast.Name) and c.id.endswith("COMMAND_TYPES"))
    for family in sorted(referenced):
        if family not in command_sets:
            errors.append({"file": dispatch_file, "message": f"unresolved command family: {family}"})
            continue
        commands, file, line = command_sets[family]
        handlers = [n for n in ast.walk(trees[file]) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name.startswith("handle_")]
        hints = [hint for handler in handlers for hint in _input_hints(handler)]
        for command in sorted(commands):
            if not isinstance(command, str):
                continue
            identifier = f"ws:{command}"
            entry = _base(identifier, "websocket", command, {"file": file, "line": line})
            entry.update(callable=True, availability="dispatcher_registered", family=family,
                         transport={"type": "websocket", "path": "/ws", "command": {"type": command}},
                         input_hints=hints, schema_status="family_source_hints_only",
                         completion="agent_dispatch_complete acknowledges handler return, not background/provider completion")
            entries[identifier] = entry
    # Special startup marker has no business response, but is a real supported command.
    if dispatch_tree:
        for node in ast.walk(dispatch_tree):
            if isinstance(node, ast.Compare) and any(_literal(c) == "startup_ui_batch_end" for c in node.comparators):
                entry = _base("ws:startup_ui_batch_end", "websocket", "startup_ui_batch_end", _location(dispatch_file, node))
                entry.update(callable=True, availability="dispatcher_registered",
                             transport={"type": "websocket", "path": "/ws", "command": {"type": "startup_ui_batch_end"}},
                             input_hints=[], schema_status="source_hints_only", completion="dispatch_only")
                entries[entry["id"]] = entry
                break

    registry_file = "core/headless_service_registry.py"
    registry = {}
    if registry_file in trees:
        for node in ast.walk(trees[registry_file]):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(value, ast.Call) and _text(value.func) == "HeadlessServiceSpec" and len(value.args) >= 2:
                        name, module, cls = _literal(key), _literal(value.args[0]), _literal(value.args[1])
                        if all(isinstance(v, str) for v in (name, module, cls)):
                            registry[name] = (module.replace(".", "/") + ".py", cls)
                            entry = _base(f"service:{name}", "service", name, _location(registry_file, value))
                            entry.update(implementation={"module": module, "class": cls},
                                         unavailable_reason="Registered service; invoke its HTTP/WebSocket/module adapter, not arbitrary methods.")
                            entry["related"] = [i for i in entries if i.startswith(f"python:{module}:{cls}.")]
                            entries[entry["id"]] = entry

    context_file = "core/web_session_context.py"
    def action_hints(file, cls, target):
        # Follow only same-class calls forwarding the action selector; locks and
        # small wrappers must not hide the implementation's action vocabulary.
        pending, visited, nodes = [(target, 0)], set(), []
        while pending:
            node, depth = pending.pop()
            if node.name in visited or depth > 6:
                continue
            visited.add(node.name)
            nodes.append(node)
            for call in ast.walk(node):
                if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"):
                    continue
                forwarded = [*call.args, *(kw.value for kw in call.keywords)]
                if not any(isinstance(arg, ast.Name) and arg.id in {"key", "clean_key", "action"} for arg in forwarded):
                    continue
                child = symbols.get((file, cls + "." + call.func.attr))
                if child is not None:
                    pending.append((child, depth + 1))
        actions = [_actions(node, constants_by_file.get(file)) for node in nodes]
        return {"literal_keys": sorted({key for a in actions for key in a["literal_keys"]}),
                "prefix_patterns": sorted({key for a in actions for key in a["prefix_patterns"]}),
                "completeness": "static_hints; same-class delegation bounded to 6 levels; computed and external actions may be absent",
                "sources": [_location(file, node) | {"symbol": cls + "." + node.name} for node in nodes]}, [hint for node in nodes for hint in _input_hints(node)]

    def resolve_call(call, depth=0):
        if depth > 7 or not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            return None
        if isinstance(call.func.value, ast.Call):
            getter = symbols.get((context_file, "WebSessionContext." + call.func.value.func.attr)) if isinstance(call.func.value.func, ast.Attribute) else None
            if getter:
                for child in ast.walk(getter):
                    if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "_lazy_service" and child.args:
                        name = _literal(child.args[0])
                        if name in registry:
                            file, cls = registry[name]
                            return name, file, cls, call.func.attr
        wrapper = symbols.get((context_file, "WebSessionContext." + call.func.attr))
        if wrapper:
            for child in ast.walk(wrapper):
                if isinstance(child, ast.Return):
                    found = resolve_call(child.value, depth + 1)
                    if found:
                        return found
        return None

    # Include private context wrappers in resolution without advertising them.
    if context_file in trees:
        for cls in trees[context_file].body:
            if isinstance(cls, ast.ClassDef):
                for node in cls.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols[(context_file, cls.name + "." + node.name)] = node
    module_file = "core/headless_module_dispatch_service.py"
    module_tree = trees.get(module_file)
    if module_tree:
        for function in ast.walk(module_tree):
            if not isinstance(function, ast.FunctionDef) or function.name not in {"module_state_payload", "set_module_param"}:
                continue
            action = "get" if function.name == "module_state_payload" else "set"
            for branch in ast.walk(function):
                if not isinstance(branch, ast.If) or not isinstance(branch.test, ast.Compare):
                    continue
                if _text(branch.test.left) != "clean_id" or len(branch.test.comparators) != 1:
                    continue
                name = _literal(branch.test.comparators[0])
                if not isinstance(name, str):
                    continue
                entry = _base(f"module:{name}:{action}", "module", f"{name} {action}", _location(module_file, branch))
                command = {"type": "get_module_state" if action == "get" else "set_module_param", "module_id": name}
                entry.update(callable=True, availability="dispatcher_registered", transport={"type": "websocket", "path": "/ws", "command": command},
                             parameters=[] if action == "get" else [{"name": "key", "required": True}, {"name": "value", "required": True}],
                             schema_status="dynamic_module_action", completion="dispatch_only; inspect direct responses and later events")
                # Only examine this branch body, not its elif siblings.
                for statement in branch.body:
                    for call in ast.walk(statement):
                        resolved = resolve_call(call)
                        if resolved:
                            service_name, file, cls, method = resolved
                            entry["related"].append("service:" + service_name)
                            entry["implementation"] = {"file": file, "class": cls, "method": method}
                            target = symbols.get((file, cls + "." + method))
                            if target:
                                entry["actions"], entry["input_hints"] = action_hints(file, cls, target)
                            break
                    if "implementation" in entry:
                        break
                entries[entry["id"]] = entry
                module_branches.append(entry["id"])

    # Link source members by actual syntactic method calls in transport handlers.
    # These are navigation candidates, never proof that the entire member is exposed.
    by_method = {}
    for identifier, entry in entries.items():
        if entry["kind"] == "python":
            by_method.setdefault(entry["name"].split(".")[-1], []).append(identifier)
    for entry in list(entries.values()):
        if entry["kind"] != "http":
            continue
        file, line = entry["source"]["file"], entry["source"]["line"]
        tree = trees.get(file)
        function = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno == line), None)
        if function:
            calls = {_text(n.func).split(".")[-1] for n in ast.walk(function) if isinstance(n, ast.Call)}
            candidates = sorted({i for name in calls for i in by_method.get(name, [])})
            entry["source_call_candidates"] = candidates
            entry["source_call_link_certainty"] = "name_match_only"
    for entry in entries.values():
        if entry["kind"] == "frontend" and entry.get("module_id"):
            module_id = f"module:{entry['module_id']}:set"
            entry["module_transport_present"] = module_id in entries
            if module_id in entries:
                actions = entries[module_id].get("actions", {})
                key = entry["action_key"]
                entry["action_statically_recognized"] = key in actions.get("literal_keys", []) or any(
                    key.startswith(p[:-1]) for p in actions.get("prefix_patterns", []))
    contract = root / "release_assets/manifests/remote_web_feature_contract.json"
    if contract.is_file():
        try:
            labels = {}
            for feature in json.loads(contract.read_text(encoding="utf-8-sig")).get("feature_groups", []):
                for file in feature.get("source_files", []):
                    labels.setdefault(file, []).append({"id": feature.get("id"), "name": feature.get("name")})
            for entry in entries.values():
                entry["feature_groups"] = labels.get(entry["source"]["file"], [])
        except (OSError, ValueError) as exc:
            errors.append({"file": str(contract.relative_to(root)), "message": f"feature contract unreadable: {type(exc).__name__}"})
    evidence = "\n".join(r["file"] + ":" + r["sha256"] for r in records).encode()
    if contract.is_file():
        evidence += contract.read_bytes()
    content_fingerprint = hashlib.sha256(evidence).hexdigest()
    return {"schema_version": 1, "protocol_version": 1, "fingerprint": content_fingerprint,
            "scope": {"roots": list(SOURCE_ROOTS), "root_code_files": True,
                      "excluded": ["tests", "data/assets", "user-data/extensions", "NAIA-Portable", "release_package", "dependencies", "build outputs"],
                      "limits": "Static AST/text inventory is not proof of complete semantic coverage. Dynamic actions and external extensions require runtime inspection."},
            "entries": entries, "files": records, "scan_issues": errors,
            "frontend_references": frontend_refs, "dynamic_frontend_references": dynamic_refs,
            "development_frontend_references": development_refs,
            "registered_service_count": len(registry), "module_operations": module_branches}


def source_catalog(root: str | Path):
    root = Path(root).resolve()
    files = source_files(root)
    stamp = "\n".join(f"{p.relative_to(root).as_posix()}:{p.stat().st_mtime_ns}:{p.stat().st_size}" for p in files)
    contract = root / "release_assets/manifests/remote_web_feature_contract.json"
    if contract.is_file():
        stamp += f"\ncontract:{contract.stat().st_mtime_ns}:{contract.stat().st_size}"
    fingerprint = hashlib.sha256(stamp.encode()).hexdigest()
    key = (str(root), fingerprint)
    with _LOCK:
        if _CACHE.get("key") != key:
            _CACHE.clear()
            _CACHE.update(key=key, catalog=_build_source_catalog(root, files, fingerprint))
        return _CACHE["catalog"]


def _openapi_path(path):
    return re.sub(r"\{([^}:]+):[^}]+\}", r"{\1}", path)


def runtime_catalog(source, openapi: dict | None = None, *, routes=None):
    """Merge runtime truth without mutating the shared source cache."""
    if openapi is None:
        return source
    result = {**source, "entries": dict(source["entries"]), "runtime_verified": True,
              "schema_components": openapi.get("components", {})}
    registered = set()
    aliases = {_openapi_path(identifier): identifier for identifier, entry in source["entries"].items()
               if entry["kind"] == "http"}
    operations_by_route = {}
    for path, operations in openapi.get("paths", {}).items():
        if not path.startswith("/api/"):
            continue
        for method, operation in operations.items():
            if method not in HTTP_METHODS:
                continue
            operations_by_route[(method.upper(), path)] = operation
    actual = ([(method, route.path) for route in routes
               if getattr(route, "path", "").startswith("/api/")
               for method in sorted(getattr(route, "methods", None) or ())
               if method.lower() in HTTP_METHODS] if routes is not None else list(operations_by_route))
    for method, path in actual:
        normalized_id = f"http:{method}:{_openapi_path(path)}"
        identifier = aliases.get(normalized_id, f"http:{method}:{path}")
        registered.add(identifier)
        operation = operations_by_route.get((method, _openapi_path(path)))
        base = result["entries"].get(identifier) or _base(identifier, "http", (operation or {}).get("operationId", identifier), {"file": "<runtime>", "line": 0})
        transport_path = path if routes is not None else base.get("transport", {}).get("path", path)
        entry = {**base, "callable": True, "availability": "runtime_registered",
                 "transport": {"type": "http", "method": method, "path": transport_path},
                 "effects": _effects(transport_path, method),
                 "schema_status": "openapi_plus_source_hints" if operation is not None else "runtime_route_without_openapi"}
        if operation is not None:
            entry["openapi"] = operation
            if operation.get("description"):
                entry["description"] = operation["description"]
        result["entries"][identifier] = entry
    for identifier, entry in source["entries"].items():
        if entry["kind"] == "http" and identifier not in registered:
            result["entries"][identifier] = {**entry, "callable": False, "availability": "not_registered_on_target"}
    result["runtime_http_ids"] = sorted(registered)
    result["registration_evidence"] = "app.routes" if routes is not None else "openapi_only"
    result["source_fingerprint"] = source["fingerprint"]
    result["fingerprint"] = hashlib.sha256((source["fingerprint"] + json.dumps(openapi, sort_keys=True)
                                            + json.dumps(sorted(actual))).encode()).hexdigest()
    return result


def describe(catalog, identifier):
    try:
        entry = dict(catalog["entries"][identifier])
    except KeyError:
        raise ValueError(f"Unknown capability: {identifier}") from None
    transport = entry.get("transport", {})
    if transport.get("type") == "http":
        entry["schema_components"] = catalog.get("schema_components", {})
        example = {"path": {}, "query": {}}
        for name in re.findall(r"\{([^}:]+)(?::[^}]+)?\}", transport["path"]):
            example["path"][name] = "<required>"
        for parameter in entry.get("openapi", {}).get("parameters", []):
            if parameter.get("required") and parameter.get("in") in {"path", "query"}:
                example[parameter["in"]][parameter["name"]] = "<required>"
        if "requestBody" in entry.get("openapi", {}) or transport.get("method") in {"POST", "PUT", "PATCH"}:
            example["json"] = {}
        entry["call_input_example"] = example
        entry["call_input_fields"] = ["path", "query", "json", "body_file", "content_type", "headers"]
    elif transport.get("type") == "websocket":
        entry["call_input_example"] = ({"key": "<action key from actions>", "value": "<value>"}
                                       if entry["id"].endswith(":set") else {})
        entry["command_base"] = transport["command"]
    entry["discovery_hint"] = "Search related capabilities and inspect schemas before calling; source-only entries are gaps/navigation, not callable Python tools."
    entry["setup_hint"] = "Check /api/agent/assets (CLI: assets list) for required datasets. Pause on missing assets and ask the user before assets install <id> --approve-download <id>. Models: /api/agent/models or CLI models."
    return entry


def listing(catalog, *, query="", kind="", offset=0, limit=30):
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("offset must be >= 0 and limit must be 1..200")
    terms = [t for t in re.split(r"\s+", query.lower().strip()) if t]
    matches = []
    for entry in catalog["entries"].values():
        if kind and entry["kind"] != kind:
            continue
        text = " ".join([entry["id"], entry["description"], entry["source"]["file"],
                         json.dumps(entry.get("actions", {}), ensure_ascii=False),
                         json.dumps(entry.get("feature_groups", []), ensure_ascii=False)]).lower()
        score = sum(3 if term in entry["id"].lower() else 1 for term in terms if term in text)
        if terms and not score:
            continue
        matches.append((score, entry))
    matches.sort(key=lambda item: (-item[0], not item[1]["callable"], item[1]["id"]))
    summaries = [{key: entry[key] for key in ("id", "kind", "name", "callable", "availability", "source")}
                 | {"description": entry["description"][:240], "effects": entry["effects"]}
                 for _, entry in matches[offset:offset + limit]]
    return {"fingerprint": catalog["fingerprint"], "protocol_version": 1, "query": query, "search_mode": "token_any_substring",
            "total": len(matches), "offset": offset, "limit": limit, "items": summaries,
            "next_offset": offset + limit if offset + limit < len(matches) else None}


def overview(catalog):
    families = {}
    entries = list(catalog["entries"].values())
    for entry in entries:
        if entry["kind"] == "http":
            family = entry["transport"]["path"].split("/")[2]
        elif entry["kind"] == "module":
            family = "module:" + entry["transport"]["command"]["module_id"]
        else:
            continue
        group = families.setdefault(family, {"family": family, "operations": 0, "callable": 0, "examples": []})
        group["operations"] += 1
        group["callable"] += bool(entry["callable"])
        if len(group["examples"]) < 3:
            group["examples"].append(entry["id"])
    return {"protocol_version": 1, "fingerprint": catalog["fingerprint"], "scope": catalog["scope"],
            "counts": {"files": len(catalog["files"]), "by_kind": dict(Counter(e["kind"] for e in entries))},
            "families": sorted(families.values(), key=lambda g: g["family"]),
            "workflow": ["Search several terms related to the goal, including capabilities outside the initially named feature.",
                         "Inspect CLI models or GET /api/agent/models before choosing a model; do not silently use a default in a fresh environment.",
                         "Inspect CLI assets list or GET /api/agent/assets. Missing data pauses the task: ask about each item's source, size and destination; only then assets install <id> --approve-download <id>. Verify installation and resume the suspended step, not completed batch mutations.",
                         "Describe candidate IDs: inspect inputs, side effects, completion semantics and related source-only entries.",
                         "Call registered transports; use batch for multi-step workflows on one WebSocket session.",
                         "Inspect audit gaps, browser/shell-only surfaces and dynamic module state before concluding a feature is absent."]}


def audit(catalog):
    entries = list(catalog["entries"].values())
    http = [entry for entry in entries if entry["kind"] == "http"]
    route_patterns = [re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(entry["transport"]["path"])) + "$") for entry in http]
    unresolved = [r for r in catalog["frontend_references"] if not any(p.match(r["path"]) for p in route_patterns)]
    gaps = {
        "scan_issues": catalog["scan_issues"],
        "source_routes_not_registered": [e["id"] for e in http if e["availability"] == "not_registered_on_target"],
        "runtime_routes_without_source": [e["id"] for e in http if e["source"]["file"] == "<runtime>"],
        "runtime_routes_without_openapi": [e["id"] for e in http if e.get("schema_status") == "runtime_route_without_openapi"],
        "duplicate_route_declarations": [e["id"] for e in http if "duplicate_declarations" in e],
        "frontend_routes_unresolved": unresolved,
        "dynamic_frontend_references": catalog["dynamic_frontend_references"],
        "module_action_schema_unresolved": [e["id"] for e in entries if e["kind"] == "module" and e["id"].endswith(":set")
                                           and not (e.get("actions", {}).get("literal_keys") or e.get("actions", {}).get("prefix_patterns"))],
        "source_only_symbols": [e["id"] for e in entries if not e["callable"] and e["kind"] in {"python", "service"}],
        "http_without_declared_body_schema": [e["id"] for e in http if e["transport"]["method"] in {"POST", "PUT", "PATCH"} and not e.get("openapi", {}).get("requestBody")],
        "frontend_module_calls_unresolved": [e["id"] for e in entries if e["kind"] == "frontend" and e.get("module_id") and not e.get("action_statically_recognized")],
        "frontend_or_shell_without_backend_transport": [e["id"] for e in entries if e["kind"] in {"frontend", "shell"} and not e.get("module_transport_present")],
    }
    return {"schema_version": 1, "fingerprint": catalog["fingerprint"], "scope": catalog["scope"],
            "runtime_verified": bool(catalog.get("runtime_verified")),
            "registration_evidence": catalog.get("registration_evidence", "source_only"),
            "counts": {"files": len(catalog["files"]), "capabilities": len(entries),
                       "by_kind": dict(Counter(e["kind"] for e in entries)),
                       "callable": sum(e["callable"] for e in entries),
                       "gaps": {key: len(value) for key, value in gaps.items()}},
            "gaps": gaps, "files": catalog["files"],
            "interpretation": "Source-only symbols include internal helpers; unresolved entries are investigation candidates, not proof of missing user functionality. No whole-product completeness claim."}
