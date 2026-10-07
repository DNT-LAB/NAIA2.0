// 외부 ComfyUI(API 모드) - Generate 가 도는 동안 결과 칸 아래쪽에 ComfyUI 서버 출력을 보이는 읽기 전용 콘솔(사용자 지정
// 2026-10-01: "API 모드에서도 Generate 를 통한 ComfyUI 백엔드 터미널 보여주는 기능". 인계 = docs/COMFYUI_API_TERMINAL_HANDOFF_2026_10_01.md).
// 관리형 ANIMA 의 기동 콘솔(animaEngineConsole.mjs)과 따로 둔다 - 그쪽은 '엔진이 켜지는 동안', 이쪽은 '생성이 도는 동안' 이다.
// Settings ▸ 화면 의 [ComfyUI 서버 출력 보기](옵션 show_comfyui_server_console, **기본 꺼짐**)를 켠 경우에만 app.js setGen 이 연다
// (결과 이미지를 가려서 - 사용자 지시 2026-10-07). 꺼져 있으면 서버 로그도 조회하지 않는다.
//
// GET /api/comfyui/server-log 가 외부 서버의 /internal/logs/raw 를 이어 붙여 준다. 첫 조회 = 지금부터.
// 첫 조회가 오류 출력까지 기준선으로 삼은 빠른 실패는 마지막 응답의 최근 서버 출력을 별도 안내와 함께 보여 준다.
// 서버 전체의 출력이라 머리에 'ComfyUI 서버 출력' 이라 적는다 - 이 요청만의 로그라고 단정하지 않는다.
// - 성공으로 끝나면 마지막 출력을 한 번 더 받아 붙이고 '완료' 를 잠깐 보인 뒤 닫힌다. 실패면 열어 둔다([✕] - 생성은 그대로).
// - 로그 API 가 없는 서버(404 · 권한 · 모양이 다름)는 한 줄로 알리고 현재 생성의 조회를 끝낸다. 닿지 않으면 한 번 알리고 간격을 늘려 다시
//   묻는다. 어느 쪽도 생성 실패로 바꾸지 않고 토스트를 띄우지 않는다.
// - 진행 막대는 '\r' 로 같은 줄을 고쳐 쓴다 - 조각을 넘어 이어지므로 아직 안 닫힌 줄을 따로 들고 있다.
// 경과 시간만 보인다(화면에 예상 속도 금지).

const API = '/api/comfyui/server-log';
const POLL_MS = 800;
const RETRY_MAX_MS = 8000;
const CLOSE_MS = 1500;       // '완료' 를 보이고 닫기까지
const FADE_MS = 300;
const MAX_LINES = 400;
const NOTE = '[NAIA] ';      // 서버 출력이 아니라 NAIA 가 붙인 줄
const QUIET_MS = 10 * 60 * 1000;   // Generate 마다 같은 미지원 안내를 반복하지 않는 시간(지원 서버는 즉시 연다)
const STYLE_ID = 'comfyServerConsoleStyle';
// 결과 칸(#resultViewer, position: relative) 안 아래쪽 - 관리형 기동 콘솔과 같은 자리(두 모드는 함께 오지 않는다)
const STYLE = `
.comfy-console { position: absolute; left: calc(12px + var(--ia-shift, 0px)); right: 12px; bottom: 12px;
  height: min(38%, 300px); display: flex; flex-direction: column; z-index: var(--z-viewer-overlay);
  border: 1px solid rgba(40,120,216,0.4); border-radius: 9px; background: rgba(8,9,14,0.94);
  box-shadow: 0 12px 34px rgba(0,0,0,0.45); overflow: hidden; transition: opacity ${FADE_MS}ms ease; }
.comfy-console[hidden] { display: none; }
.comfy-console.is-closing { opacity: 0; }
.comfy-console-head { display: flex; align-items: center; gap: 10px; padding: 6px 10px;
  border-bottom: 1px solid rgba(40,120,216,0.22); font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); }
.comfy-console-head b { color: var(--text-primary); font-weight: 600; }
.comfy-console-state { margin-left: auto; }
.comfy-console-state.ok { color: var(--success); }
.comfy-console-state.err { color: #f07070; }
.comfy-console-x { background: none; border: 0; color: var(--text-dim); cursor: pointer; font-size: 12px; padding: 0 2px; }
.comfy-console-x:hover, .comfy-console-x:focus-visible { color: var(--text-primary); }
.comfy-console-log { flex: 1; margin: 0; padding: 8px 10px; overflow: auto; white-space: pre-wrap; word-break: break-all;
  font-family: var(--font-mono); font-size: 10.5px; line-height: 1.45; color: #b8c0cc; user-select: text; }
`;

const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;

export function createComfyServerConsole({ document, window: win = window, fetch: fetchFn = win.fetch.bind(win),
  getHost = () => document.getElementById('resultViewer'), isActive = () => true }) {
  let el = null;
  let logEl = null;
  let stateEl = null;
  let elapsedEl = null;
  let lines = [];
  let current = '';          // 아직 줄바꿈이 오지 않은 줄 - 진행 막대가 '\r' 로 고쳐 쓴다
  let pendingCr = false;     // 바로 앞이 '\r' 였다 - 다음 글자가 그 줄을 처음부터 고쳐 쓴다
  let since = null;
  let phase = 'idle';        // idle | running | finishing | closing | failed
  let seq = 0;
  let pollTimer = 0;
  let clockTimer = 0;
  let closeTimer = 0;
  let startedAt = 0;
  let delay = POLL_MS;
  let streaming = true;      // false = 이 서버에는 더 묻지 않는다(로그 API 없음)
  let troubleShown = false;  // '읽지 못했다' 를 이미 알렸다 - 다시 읽힐 때까지 되풀이하지 않는다
  let quietUntil = 0;        // 미지원 안내 반복만 숨긴다. 현재 서버의 지원 여부는 매 생성 첫 조회로 확인한다.
  let inFlight = null;       // 종료할 때 첫 조회를 포함한 진행 중 조회를 먼저 회수한다
  let hasServerText = false;

  function ensure() {
    if (el) return el;
    const host = getHost();
    if (!host) return null;
    if (!document.getElementById(STYLE_ID)) {
      const style = document.createElement('style');
      style.id = STYLE_ID;
      style.textContent = STYLE;
      document.head.appendChild(style);
    }
    el = document.createElement('div');
    el.className = 'comfy-console';
    el.hidden = true;
    el.setAttribute('role', 'log');
    el.setAttribute('aria-label', 'ComfyUI 서버 출력');
    const head = document.createElement('div');
    head.className = 'comfy-console-head';
    const title = document.createElement('b');
    title.textContent = 'ComfyUI 서버 출력';
    elapsedEl = document.createElement('span');
    elapsedEl.className = 'comfy-console-elapsed';
    stateEl = document.createElement('span');
    stateEl.className = 'comfy-console-state';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'comfy-console-x';
    close.textContent = '✕';
    close.title = '닫기 - 생성은 계속됩니다';
    close.setAttribute('aria-label', '닫기');
    close.addEventListener('click', () => hide());
    head.append(title, elapsedEl, stateEl, close);
    logEl = document.createElement('pre');
    logEl.className = 'comfy-console-log';
    el.append(head, logEl);
    host.appendChild(el);
    return el;
  }

  function setState(text, kind = '') {
    stateEl.textContent = text;
    stateEl.className = `comfy-console-state${kind ? ` ${kind}` : ''}`;
  }

  function stopTimers() {
    win.clearTimeout(pollTimer);
    win.clearInterval(clockTimer);
    win.clearTimeout(closeTimer);
    pollTimer = clockTimer = closeTimer = 0;
  }

  function paintClock() {
    elapsedEl.textContent = `${((Date.now() - startedAt) / 1000).toFixed(1)}s`;
  }

  // 끝에 붙어 있으면 따라 내려가고, 사람이 위로 올려 읽는 중이면 그대로 둔다
  function render(atEnd) {
    logEl.textContent = (current ? [...lines, current] : lines).join('\n');
    if (atEnd) logEl.scrollTop = logEl.scrollHeight;
  }

  function atEnd() {
    return logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 24;
  }

  function commit(line) {
    if (line) lines.push(line);
    if (lines.length > MAX_LINES) lines = lines.slice(-MAX_LINES);
  }

  // ComfyUI 의 write 조각을 이어 받는다 - '\n' 은 줄을 닫고, '\r' 뒤의 글자는 아직 안 닫힌 줄을 처음부터 고쳐 쓴다
  function appendStream(text) {
    if (text) hasServerText = true;
    const follow = atEnd();
    const parts = String(text).replace(ANSI, '').split('\n');
    parts.forEach((part, index) => {
      part.split('\r').forEach((piece, i) => {
        if (i > 0) pendingCr = true;
        if (!piece) return;
        current = pendingCr ? piece : current + piece;
        pendingCr = false;
      });
      if (index < parts.length - 1) {
        commit(current);
        current = '';
        pendingCr = false;
      }
    });
    render(follow);
  }

  function notice(text) {
    const follow = atEnd();
    commit(NOTE + text);
    render(follow);
  }

  // 읽지 못했다(NAIA · 외부 서버) - 한 번만 알리고 간격을 늘려 다시 묻는다. 생성 실패로 바꾸지 않는다.
  function trouble(text) {
    if (!troubleShown) notice(`${text} - 다시 시도합니다`);
    troubleShown = true;
    delay = Math.min(delay * 2, RETRY_MAX_MS);
  }

  async function read(url) {
    try {
      const res = await fetchFn(url, { cache: 'no-store' });
      return res.ok ? await res.json() : null;
    } catch (_) {
      return null;
    }
  }

  // 답 하나를 화면에 - 더 물을지(true) 말지(false)
  function absorb(data) {
    if (!data) { trouble('NAIA 에서 서버 출력을 받지 못했습니다'); return true; }
    const state = String(data.state || '');
    // 관리형으로 바뀌었다(그쪽은 기동 콘솔) · 외부 URL 이 없다 - 이 콘솔이 보일 것이 없다
    if (state === 'managed' || state === 'unconfigured') { hide(); return false; }
    if (state === 'unsupported') {
      streaming = false;
      if (Date.now() < quietUntil) { hide(); return false; }
      quietUntil = Date.now() + QUIET_MS;
      notice(`이 서버는 터미널 로그를 제공하지 않습니다${data.reason ? ` (${data.reason})` : ''} - 생성 상태만 보입니다`);
      return false;
    }
    // 매 Generate 의 첫 조회는 숨긴 상태에서도 한다. 미지원 캐시는 백엔드가 URL 별로 판단한다.
    // 새 서버가 로그를 주면 앞 서버 때문에 닫혀 있던 콘솔을 즉시 다시 연다.
    quietUntil = 0;
    el.hidden = false;
    const first = since == null;
    if (typeof data.since === 'number') since = data.since;
    if (state === 'unreachable') {
      trouble(`ComfyUI 서버 출력을 읽지 못했습니다${data.reason ? ` (${data.reason})` : ''}`);
      return true;
    }
    delay = POLL_MS;
    troubleShown = false;
    if (first) return true;                  // 기준선 - 그 전 출력(앞 요청의 것)은 실려 와도 붙이지 않는다
    if (data.gap) notice('앞 출력과 이어지지 않습니다 - 서버가 다시 시작됐거나 출력이 너무 많았습니다');
    if (data.text) appendStream(data.text);
    return true;
  }

  function poll(my) {
    const pending = read(since == null ? API : `${API}?since=${since}`).then(data => {
      if (my !== seq || (phase !== 'running' && phase !== 'finishing')) return;
      if (!isActive()) { hide(); return; }      // 모드 · 엔진이 바뀌었다
      if (absorb(data) && phase === 'running') pollTimer = win.setTimeout(() => poll(my), delay);
    });
    inFlight = pending;
    pending.finally(() => { if (inFlight === pending) inFlight = null; });
    return pending;
  }

  // 생성이 시작됐다(외부 ComfyUI) - 앞 생성의 출력 · 실패 표시는 지우고 지금부터 받는다
  function start() {
    if (!ensure()) return;
    stopTimers();
    seq += 1;
    lines = [];
    current = '';
    hasServerText = false;
    pendingCr = false;
    since = null;
    delay = POLL_MS;
    streaming = true;
    troubleShown = false;
    phase = 'running';
    startedAt = Date.now();
    logEl.textContent = '';
    el.classList.remove('is-closing');
    el.hidden = Date.now() < quietUntil;
    setState('생성 중');
    paintClock();
    clockTimer = win.setInterval(paintClock, 100);
    poll(seq);
  }

  function hide() {
    seq += 1;
    stopTimers();
    phase = 'idle';
    inFlight = null;
    if (el) {
      el.hidden = true;
      el.classList.remove('is-closing');
    }
  }

  function closeSoon(text, kind) {
    phase = 'closing';
    setState(text, kind);
    const my = seq;
    closeTimer = win.setTimeout(() => {
      if (my !== seq) return;
      el.classList.add('is-closing');
      closeTimer = win.setTimeout(() => { if (my === seq) hide(); }, FADE_MS);
    }, CLOSE_MS);
  }

  // 이 콘솔을 연 생성이 끝났다 - app.js setGen 이 생성 상태가 풀릴 때 부른다(ok = 그림이 왔다 · completed)
  async function finish(ok) {
    if (phase !== 'running') return;
    const my = seq;
    phase = 'finishing';
    win.clearTimeout(pollTimer);
    win.clearInterval(clockTimer);
    pollTimer = clockTimer = 0;
    paintClock();
    // 첫 응답보다 먼저 끝난 생성도 커서를 받는다. 다음 생성/닫기가 시작됐으면 옛 응답은 버린다.
    await inFlight;
    if (my !== seq || phase !== 'finishing') return;
    if (!isActive()) { hide(); return; }
    // 마지막 출력("Prompt executed in …")이 아직 안 붙었을 수 있다 - 간격과 관계없이 지금 서버를 한 번 더 읽는다
    if (streaming) {
      const data = await read(`${API}?${since == null ? '' : `since=${since}&`}fresh=1`);
      if (my !== seq || phase !== 'finishing') return;
      if (!isActive()) { hide(); return; }
      absorb(data);
      if (my !== seq || phase !== 'finishing') return;
      if (data && String(data.state || '') === 'ok') {
        // 첫 스냅숏 자체에 실패 내용이 있었다면 delta 는 비어 있다. 서버 전체의 최근 출력임을 명시한다.
        if (!hasServerText && data.tail) {
          notice('새로 수신한 출력이 없어 최근 서버 출력을 표시합니다 (이전 생성의 출력이 포함될 수 있습니다)');
          appendStream(data.tail);
        }
      }
    }
    if (ok) {
      closeSoon('완료', 'ok');
    } else {
      phase = 'failed';                       // 실패 - 까닭을 읽을 수 있게 남긴다([✕] 로 닫는다)
      setState('실패', 'err');
    }
  }

  return { start, finish, hide, isShown: () => Boolean(el) && !el.hidden };
}
