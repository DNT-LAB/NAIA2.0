# -*- coding: utf-8 -*-
"""프리셋 썸네일 생성 지켜보기 서버 (2026-11-18 · 개발 전용 · 런타임 미사용).

    python tools/preset_thumb_viewer.py [--port 7398] [--no-autostart]

- 켜지면 생성기 두 계정(MYT · 0UY)을 `--any` 로 띄운다(이미 돌고 있으면 그대로 둔다).
- 화면은 2초마다 갈래별 된 수 · 계정 상태 · 최근 그림을 다시 읽는다.
- [정지] = 출력 폴더에 STOP 파일(생성기는 지금 장을 마치고 끝난다). [시작] = STOP 을 지우고 안 돌고 있는 계정을 띄운다.
- 이 서버를 꺼도 생성기는 계속 돈다(따로 띄운 프로세스) - 멈추려면 [정지].
- 의상 그림의 태그를 누르면 '다른 의상' 탐색(core/outfit_tag_semantics.py) - 의미 색인 확인용.
  다른 포트로 하나 더 띄워 볼 때는 `--no-autostart` (생성기를 또 띄우지 않게).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter, OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / ".experimental" / "preset_thumb_src" / "20261118"
GENERATOR = ROOT / "tools" / "preset_thumb_generate.py"
ACCOUNTS = ("MYT", "0UY")
KINDS = ("outfit", "event", "expression", "scene", "link")
TERMINAL = {"account_done", "stop_file", "give_up_streak", "anlas_dropped", "bucket_empty", "account_refused"}

_lock = threading.Lock()
_thumb_cache: "OrderedDict[str, bytes]" = OrderedDict()
_targets: dict | None = None
_targets_mtime = 0.0


def _say(msg: str) -> None:
    print(msg.encode("ascii", "backslashreplace").decode("ascii"), flush=True)


def targets() -> dict:
    # 대상 목록을 다시 구우면(틀 · 팩 변경) 뷰어를 껐다 켜지 않아도 새 목록을 본다.
    global _targets, _targets_mtime
    path = OUT / "_targets.json"
    mtime = path.stat().st_mtime
    if _targets is None or mtime != _targets_mtime:
        doc = json.loads(path.read_text(encoding="utf-8"))
        _targets, _targets_mtime = {t["key"]: t for t in doc["targets"]}, mtime
    return _targets


def _tail_jsonl(path: Path, max_bytes: int = 200_000) -> list[dict]:
    if not path.is_file():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read().decode("utf-8", "replace")
    rows = []
    for line in data.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _pid_path(label: str) -> Path:
    return OUT / f"viewer_pid_{label}.txt"


def _alive(label: str) -> int | None:
    """띄운 생성기가 아직 도는가 - pid 파일 + 커맨드라인으로 확인(남의 프로세스를 내 것으로 오인하지 않게)."""
    try:
        import psutil
        pid = int(_pid_path(label).read_text(encoding="ascii").strip())
        proc = psutil.Process(pid)
        cmd = " ".join(proc.cmdline())
        if proc.is_running() and "preset_thumb_generate.py" in cmd and f"--account {label}" in cmd:
            return pid
    except Exception:
        pass
    return None


def start_accounts() -> list[str]:
    (OUT / "STOP").unlink(missing_ok=True)
    started = []
    for label in ACCOUNTS:
        if _alive(label):
            continue
        log = (OUT / f"console_{label}.log").open("ab")
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        args = [sys.executable, "-X", "utf8", str(GENERATOR), "run", "--account", label, "--any"]
        # 미리보기 도구가 서버를 끌 때 작업 객체(job)째 죽인다 - 실측 11-18: 뷰어 재시작에 생성기 둘이 같이 죽었다.
        # 작업 밖으로 떼어 띄운다(CREATE_BREAKAWAY_FROM_JOB). 작업이 떼기를 막으면 예전처럼 띄운다.
        try:
            proc = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, creationflags=flags | 0x01000000)
        except OSError:
            proc = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, creationflags=flags)
        _pid_path(label).write_text(str(proc.pid), encoding="ascii")
        started.append(label)
        _say(f"started {label} pid={proc.pid}")
    return started


def stop_accounts() -> None:
    (OUT / "STOP").write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="ascii")
    _say("STOP written")


def status() -> dict:
    tg = targets()
    done_keys = {p.stem for p in OUT.glob("*.png")}
    total = Counter(t["kind"] for t in tg.values())
    done = Counter(tg[k]["kind"] for k in done_keys if k in tg)
    now = time.time()
    accounts = []
    for label in ACCOUNTS:
        run = _tail_jsonl(OUT / f"run_{label}.jsonl")
        man = _tail_jsonl(OUT / f"manifest_{label}.jsonl")
        last = run[-1] if run else {}
        usage = next((r.get("percent") for r in reversed(run) if r.get("ev") == "v5_usage"), None)
        anlas = next((r.get("anlas") for r in reversed(run)
                      if r.get("ev") in ("progress", "account_start") and r.get("anlas") is not None), None)
        stamps = [time.mktime(time.strptime(r["t"], "%Y-%m-%d %H:%M:%S")) for r in man[-400:] if r.get("t")]
        recent = [s for s in stamps if now - s <= 300]
        stop_reason = last.get("ev") if last.get("ev") in TERMINAL else None
        accounts.append({
            # 최근 5분(막 시작했으면 시작부터)의 속도 - 5분으로 나누면 시작 직후 속도가 낮게 나온다.
            "label": label, "running": bool(_alive(label)),
            "per_min": round(len(recent) * 60 / max(60.0, now - min(recent)), 1) if recent else 0.0,
            "last_event": last.get("ev"), "last_t": last.get("t"), "stop_reason": stop_reason,
            "usage": usage, "anlas": anlas, "made": len(man) if len(man) < 400 else None,
            "last_err": next((r.get("err") for r in reversed(run[-20:]) if r.get("err")), None),
        })
    recent_files = sorted(OUT.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)[:200]
    recent_items = [{"key": p.stem, "kind": tg[p.stem]["kind"], "tags": tg[p.stem]["tags"],
                     "seed": tg[p.stem]["seed_tag"], "t": int(p.stat().st_mtime)}
                    for p in recent_files if p.stem in tg]
    rate = round(sum(a["per_min"] for a in accounts), 1)
    remaining = len(tg) - sum(done.values())
    return {
        "kinds": [{"kind": k, "done": done[k], "total": total[k]} for k in KINDS],
        "done": sum(done.values()), "total": len(tg), "remaining": remaining,
        "eta_min": round(remaining / rate) if rate else None, "rate": rate,
        "stop_file": (OUT / "STOP").is_file(), "accounts": accounts, "recent": recent_items,
        "now": time.strftime("%H:%M:%S"),
    }


def thumb(key: str) -> bytes | None:
    if key not in targets():
        return None
    with _lock:
        if key in _thumb_cache:
            _thumb_cache.move_to_end(key)
            return _thumb_cache[key]
    path = OUT / f"{key}.png"
    if not path.is_file():
        return None
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((256, 256))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
    data = buf.getvalue()
    with _lock:
        _thumb_cache[key] = data
        while len(_thumb_cache) > 600:
            _thumb_cache.popitem(last=False)
    return data


_semantics = None


def outfit_related(tag: str, pool: str, context: list[str]) -> dict | None:
    global _semantics
    if _semantics is None:
        from core.outfit_tag_semantics import OutfitTagSemantics
        _semantics = OutfitTagSemantics()
    result = _semantics.related(tag, pool=pool, context=context or None)
    if result is not None:
        for group in result["groups"]:
            for row in group["sets"]:
                row["done"] = (OUT / f"{row['key']}.png").is_file()
    return result


PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Preset Thumb Viewer</title><style>
:root{--bg:#15171c;--panel:#1e2128;--line:#2c313b;--fg:#e6e8ee;--dim:#8b93a3;--ok:#4fb477;--warn:#d9a441;--bad:#d9605a;--acc:#5b8def}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.45 system-ui,"Malgun Gothic",sans-serif}
header{display:flex;gap:12px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--bg);z-index:2;flex-wrap:wrap}
h1{font-size:15px;margin:0}.sum{color:var(--dim)}button{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 12px;cursor:pointer}
button.stop{border-color:var(--bad);color:#ffb3ae}button.go{border-color:var(--ok);color:#a9e7bf}.sp{flex:1}
main{padding:12px 16px;display:grid;gap:12px}.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 10px;cursor:pointer}.card.sel{border-color:var(--acc)}
.bar{height:6px;background:#2a2f39;border-radius:3px;overflow:hidden;margin-top:6px}.bar i{display:block;height:100%;background:var(--acc)}
.n{font-size:16px;font-weight:600}.dim{color:var(--dim)}.acc{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;background:var(--dim)}.dot.on{background:var(--ok)}.dot.err{background:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}.it{background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:hidden}
.it img{width:100%;aspect-ratio:1;object-fit:contain;background:#fff;display:block}.it.tall img{aspect-ratio:525/768}
.it div{padding:4px 6px;font-size:11px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.err{color:#ffb3ae;font-size:11px;word-break:break-all}
.it .tg{white-space:normal;line-height:1.7}.t{display:inline-block;padding:0 5px;margin:1px 2px 1px 0;border:1px solid var(--line);border-radius:4px;color:var(--fg);cursor:pointer;background:#262a33}
.t:hover{border-color:var(--acc)}.t.on{border-color:var(--acc);background:#24324d}.it.none img{background:#000}.it.none{opacity:.65}
#ex{display:none;background:var(--panel);border:1px solid var(--acc);border-radius:8px;padding:10px 12px}#ex.show{display:block}
#ex h2{font-size:14px;margin:0 8px 0 0;display:inline}#ex .hop{margin:6px 0}#ex .hop b{display:inline-block;min-width:76px;color:var(--dim);font-weight:400}
#ex h3{font-size:12px;margin:12px 0 6px;color:var(--dim);font-weight:400}#ex .grid{grid-template-columns:repeat(auto-fill,minmax(120px,1fr))}
</style></head><body>
<header><h1>프리셋 썸네일 생성</h1><span class="sum" id="sum"></span><span class="sp"></span>
<span class="dim" id="clock"></span><button class="go" onclick="act('start')">시작</button><button class="stop" onclick="act('stop')">정지</button></header>
<main><div id="ex"></div><div class="row" id="kinds"></div><div class="acc" id="acc"></div><div class="dim" id="gtitle"></div><div class="grid" id="grid"></div></main>
<script>
const NAMES={all:'전체',outfit:'의상',event:'자세',expression:'표정',scene:'배경',link:'연결'};
let sel=localStorage.getItem('ptv.kind')||'all',last=null,shown='';
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function act(a){if(a==='stop'&&!confirm('정지할까요? 지금 그리는 장은 마치고 멈춥니다.'))return;await fetch('/api/'+a,{method:'POST'});tick()}
function pick(k){sel=k;try{localStorage.setItem('ptv.kind',k)}catch(e){}shown='';render()}
function render(){if(!last)return;const s=last;
 document.getElementById('sum').textContent=`${s.done.toLocaleString()} / ${s.total.toLocaleString()} · 남은 ${s.remaining.toLocaleString()} · ${s.rate}장/분`+(s.eta_min!=null?` · 약 ${Math.floor(s.eta_min/60)}시간 ${s.eta_min%60}분`:'')+(s.stop_file?' · STOP':'');
 document.getElementById('clock').textContent=s.now;
 const all={kind:'all',done:s.done,total:s.total};
 document.getElementById('kinds').innerHTML=[all,...s.kinds].map(k=>`<div class="card ${sel===k.kind?'sel':''}" onclick="pick('${k.kind}')"><div class="dim">${NAMES[k.kind]}</div><div class="n">${k.done.toLocaleString()} <span class="dim">/ ${k.total.toLocaleString()}</span></div><div class="bar"><i style="width:${k.total?100*k.done/k.total:0}%"></i></div></div>`).join('');
 document.getElementById('acc').innerHTML=s.accounts.map(a=>`<div class="card" style="cursor:default"><div><span class="dot ${a.running?'on':(a.stop_reason&&a.stop_reason!=='stop_file'&&a.stop_reason!=='account_done'?'err':'')}"></span><b>${a.label}</b> <span class="dim">${a.running?'도는 중':'멈춤'} · ${a.per_min}장/분 · 사용량 ${a.usage??'?'}% · Anlas ${a.anlas??'?'}</span></div><div class="dim">마지막: ${esc(a.last_event||'-')} ${esc(a.last_t||'')}${a.stop_reason?' · 멈춘 이유 '+esc(a.stop_reason):''}</div>${a.last_err?`<div class="err">${esc(a.last_err)}</div>`:''}</div>`).join('');
 const items=s.recent.filter(r=>sel==='all'||r.kind===sel).slice(0,60);
 document.getElementById('gtitle').textContent=`최근 ${NAMES[sel]} ${items.length}장`;
 const sig=sel+'|'+items.map(r=>r.key).join(',');if(sig===shown)return;shown=sig;
 document.getElementById('grid').innerHTML=items.map(r=>r.kind==='outfit'?card(r,''):`<div class="it" title="${esc(r.tags.join(', '))}"><img loading="lazy" src="/thumb/${r.key}"><div>${esc(NAMES[r.kind])} · ${esc(r.tags.join(', '))}</div></div>`).join('');}
// ── 의상 태그 탐색 ── 태그를 누르면 그 의상을 맥락으로 '다른 의상' 세 갈래를 보여 준다.
let ex={tag:null,pool:'female',ctx:[]};
function card(r,cur){const ctx=encodeURIComponent(JSON.stringify(r.tags)).replace(/'/g,'%27');const none=r.done===false;
 return `<div class="it tall ${none?'none':''}" title="${esc(r.tags.join(', '))}${r.id?' · '+esc(r.id):''}">${none?'<img alt="">':`<img loading="lazy" src="/thumb/${r.key}">`}<div class="tg">${r.tags.map(t=>`<span class="t ${t===cur?'on':''}" onclick="explore('${esc(t).replace(/'/g,"\\'")}','${ctx}')">${esc(t)}</span>`).join('')}</div></div>`}
function explore(tag,ctx){ex.tag=tag;ex.ctx=ctx?JSON.parse(decodeURIComponent(ctx)):[];loadEx();scrollTo({top:0,behavior:'smooth'})}
function hop(tag){ex.tag=tag;ex.ctx=[];loadEx()}
function setPool(p){ex.pool=p;loadEx()}
async function loadEx(){const q=new URLSearchParams({tag:ex.tag,pool:ex.pool,ctx:ex.ctx.join('|')});
 const r=await fetch('/api/outfit-related?'+q);const box=document.getElementById('ex');box.className='show';
 if(!r.ok){box.innerHTML=`<b>${esc(ex.tag)}</b> <span class="dim">- 의상 색인에 없는 태그</span> <button onclick="closeEx()">닫기</button>`;return}
 const d=await r.json();const H={broader:'넓은 이름',narrower:'좁은 이름',siblings:'같은 종류',swaps:'바꿔 입기'};
 const chips=a=>a.map(t=>`<span class="t" onclick="hop('${esc(t).replace(/'/g,"\\'")}')">${esc(t)}</span>`).join('');
 box.innerHTML=`<div><h2>${esc(d.tag)}</h2><span class="dim">${d.slot} · ${esc(d.kind)} · 세트 ${d.count}${d.stale?' · ⚠ 색인이 팩보다 오래됨':''}${ex.ctx.length?' · 맥락: '+esc(ex.ctx.join(', ')):''}</span>
 <span style="float:right"><button class="${ex.pool==='female'?'go':''}" onclick="setPool('female')">여성 풀</button> <button class="${ex.pool==='male'?'go':''}" onclick="setPool('male')">남성 풀</button> <button onclick="closeEx()">닫기</button></span></div>`+
 Object.keys(H).filter(k=>d.hops[k].length).map(k=>`<div class="hop"><b>${H[k]}</b>${chips(d.hops[k])}</div>`).join('')+
 d.groups.map(g=>`<h3>${esc(g.label)} · ${g.sets.length}</h3><div class="grid">${g.sets.map(x=>card(x,d.tag)).join('')||'<span class="dim">없음</span>'}</div>`).join('')}
function closeEx(){ex.tag=null;document.getElementById('ex').className=''}
async function tick(){try{const r=await fetch('/api/status');last=await r.json();render()}catch(e){document.getElementById('clock').textContent='연결 끊김'}}
tick();setInterval(tick,2000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - 조용히
        pass

    def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/status":
            return self._send(200, json.dumps(status(), ensure_ascii=False).encode("utf-8"), "application/json")
        if path == "/api/outfit-related":
            q = parse_qs(urlparse(self.path).query)
            tag = (q.get("tag") or [""])[0]
            pool = (q.get("pool") or ["female"])[0]
            ctx = [t for t in (q.get("ctx") or [""])[0].split("|") if t]
            try:
                result = outfit_related(tag, pool, ctx)
            except ValueError as exc:
                return self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            if result is None:
                return self._send(404, b'{"error":"unknown tag"}', "application/json")
            return self._send(200, json.dumps(result, ensure_ascii=False).encode("utf-8"), "application/json")
        if path.startswith("/thumb/"):
            data = thumb(path[len("/thumb/"):])
            if data is None:
                return self._send(404, b"", "text/plain")
            return self._send(200, data, "image/jpeg", "max-age=86400")
        self._send(404, b"", "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/stop":
            stop_accounts()
            return self._send(200, b'{"ok":true}', "application/json")
        if path == "/api/start":
            started = start_accounts()
            return self._send(200, json.dumps({"ok": True, "started": started}).encode(), "application/json")
        self._send(404, b"", "text/plain")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=7398)
    ap.add_argument("--no-autostart", action="store_true")
    a = ap.parse_args()
    targets()
    # 사용자가 [정지]해 둔 상태(STOP 파일)면 뷰어를 다시 띄워도 생성을 시작하지 않는다 - 재개는 [시작] 단추로만.
    if not a.no_autostart and not (OUT / "STOP").is_file():
        start_accounts()
    elif (OUT / "STOP").is_file():
        _say("STOP file present - autostart skipped")
    server = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    _say(f"viewer http://127.0.0.1:{a.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
