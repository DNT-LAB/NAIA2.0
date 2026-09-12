# -*- coding: utf-8 -*-
"""이벤트 맵을 **손으로 만져 보는** 도구. NAIA 본체와 분리된 개발용이다.

왜 따로 두는가: 맵의 값어치는 숫자가 아니라 "타고 들어가 보면 그럴듯한가" 다.
그건 눌러 봐야 안다. 본체 라우트·화면을 건드리기 전에 여기서 먼저 만져 본다.

    python tools/event_map_playground.py --index <event_map.sqlite3> [--port 7361]

읽기 전용이다. 사용자 데이터·프리셋·프롬프트를 건드리지 않고, 127.0.0.1 에만 연다.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.event_map import EventMapIndex  # noqa: E402

PAGE = Path(__file__).with_suffix(".html")
RATINGS = ("g", "s", "q", "e")
INDEX: EventMapIndex | None = None


def _split(value: str) -> list[str]:
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def suggest(query: str, limit: int = 20) -> list[dict]:
    """이름으로 태그를 찾는다. 맵에 못 꽂는 태그는 왜 못 꽂는지 같이 말한다."""
    q = query.strip().casefold()
    if not q:
        return []
    starts, inside = [], []
    for name, tid in INDEX.by_name.items():
        if not name.startswith(q):
            if q in name:
                inside.append((INDEX.observed[tid], name, tid))
            continue
        starts.append((INDEX.observed[tid], name, tid))
    starts.sort(reverse=True)
    inside.sort(reverse=True)
    out = []
    for observed, name, tid in (starts + inside)[:limit]:
        blocked = None
        if INDEX.color[tid]:
            blocked = "색상"
        elif not INDEX.eligible[tid]:
            blocked = "후보 아님"
        out.append({"tag": name, "observed": observed,
                    "role": INDEX.role.get(tid), "blocked": blocked})
    return out


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args) -> None:      # 콘솔을 조용히 (cp949 안전)
        pass

    def _send(self, body: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict) -> None:
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:                   # noqa: N802 (BaseHTTPRequestHandler 규약)
        url = urlparse(self.path)
        args = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/suggest":
                self._json({"items": suggest(args.get("q", ""))})
            elif url.path == "/api/explore":
                pins = _split(args.get("pins", ""))
                if not pins:
                    self._json({"status": "no_pins", "candidates": [], "pins": []})
                    return
                self._json(INDEX.explore(
                    pins,
                    exclude=_split(args.get("exclude", "")),
                    ratings=[r for r in _split(args.get("ratings", "")) if r in RATINGS],
                    persons=_split(args.get("persons", "")),
                    limit=int(args.get("limit", 40)),
                    include_color=args.get("color") == "1",
                    roles=_split(args.get("roles", "")) or None,
                ))
            elif url.path == "/api/sample":
                # 핀 전부를 포함하는 **실제 게시물**을 무작위로 골라 태그 전체를 준다
                # (Dev0714 Interactive Quick Search 의 랜덤 프롬프트와 같은 동작).
                pins = _split(args.get("pins", ""))
                if not pins:
                    self._json({"status": "no_pins", "samples": [], "pins": []})
                    return
                self._json(INDEX.sample(
                    pins,
                    exclude=_split(args.get("exclude", "")),
                    ratings=[r for r in _split(args.get("ratings", "")) if r in RATINGS],
                    persons=_split(args.get("persons", "")),
                    n=int(args.get("n", 5)),
                    include_color=args.get("color") == "1",
                ))
            elif url.path == "/api/meta":
                # 지금 연 색인이 어떤 형식인지 화면 머리에 보여 준다 - 한 파일(.naiamap)을
                # 시험하는 중인지, 예전 두 파일을 보고 있는지 헷갈리지 않게.
                files = [INDEX.path] if INDEX.body_path == INDEX.path else [INDEX.path, INDEX.body_path]
                self._json({
                    "tags": len(INDEX.by_name), "posts": INDEX.total_posts,
                    "partitions": INDEX.partitions, "policy": INDEX.meta.get("schema"),
                    "index": str(INDEX.path), "body": str(INDEX.body_path),
                    "format": "naiamap" if INDEX.body_path == INDEX.path else "legacy-pair",
                    "files": [{"name": f.name, "mb": round(f.stat().st_size / 1048576, 1)}
                              for f in files],
                    # 어느 판을 보고 있는지 - 정책·거르개·연령 하한이 다른 판이 여럿 있다.
                    "build": {
                        "policy_mode": INDEX.meta.get("policy_mode"),
                        "row_guard": INDEX.meta.get("row_guard") or "source",
                        "age_floor": INDEX.meta.get("age_floor") or "on",
                        "color_policy": INDEX.meta.get("color_policy"),
                        "lanes": INDEX.meta.get("lanes") or {},
                        "record_width": INDEX.meta.get("record_width") or 2,
                        "built_at": INDEX.meta.get("built_at"),
                        "source_schema": (INDEX.meta.get("source") or {}).get("schema"),
                    },
                })
            else:
                self._send(b"not found", "text/plain; charset=utf-8")
        except Exception as exc:                # 도구가 죽지 않고 화면에 이유를 말한다
            self._json({"status": "error", "error": "%s: %s" % (type(exc).__name__, exc),
                        "candidates": [], "pins": []})


def main() -> None:
    global INDEX
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index", required=True, help="event_map.sqlite3")
    ap.add_argument("--port", type=int, default=7361)
    args = ap.parse_args()

    INDEX = EventMapIndex(args.index)
    print("index : %s" % INDEX.path)
    print("tags  : %d   posts: %d" % (len(INDEX.by_name), INDEX.total_posts))
    print("open  : http://127.0.0.1:%d/" % args.port)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        INDEX.close()


if __name__ == "__main__":
    main()
