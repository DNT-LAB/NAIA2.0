// 관리형 ANIMA - 엔진이 켜지는 동안 결과 칸 아래쪽에 뜨는 임시 콘솔(사용자 지정 2026-09-29: "엔진이 켜지는 동안 ComfyUI
// 진행 상태를 알 수 있는 임시 커맨드 창을 띄워줍니다. 연결 완료 후 자동으로 사라집니다").
// ComfyUI 가 engine.log 에 적는 것을 GET /api/anima-engine/engine/log?since= 로 이어 받아 보인다(처음은 이번 기동의
// 머리줄부터). 켜지면(running) '연결됨' 을 잠깐 보이고 스스로 닫힌다 - 생성 쪽 감시(app.js watchAnimaEngineStart)가
// 먼저 끝나도(취소 등) 콘솔은 제 조회로 엔진 상태를 안다. 켜지지 못하면(crashed) 닫지 않고 까닭을 남긴다([×] 로 닫는다).
// 경과 시간만 보인다 - 남은 시간 · 예상 시간은 쓰지 않는다(화면에 예상 속도 금지).

const API = '/api/anima-engine/engine/log';
const POLL_MS = 500;
const CLOSE_MS = 1500;       // '연결됨' 을 보이고 닫기까지
const FADE_MS = 300;
const MAX_LINES = 400;
const STYLE_ID = 'animaEngineConsoleStyle';
// 결과 칸(#resultViewer, position: relative) 안 아래쪽. 왼쪽은 Interactive 팝업만큼 비켜선다(다른 오버레이와 같다).
const STYLE = `
.anima-console { position: absolute; left: calc(12px + var(--ia-shift, 0px)); right: 12px; bottom: 12px;
  height: min(38%, 300px); display: flex; flex-direction: column; z-index: var(--z-viewer-overlay);
  border: 1px solid rgba(124,106,239,0.35); border-radius: 9px; background: rgba(8,9,14,0.94);
  box-shadow: 0 12px 34px rgba(0,0,0,0.45); overflow: hidden; transition: opacity ${FADE_MS}ms ease; }
.anima-console[hidden] { display: none; }
.anima-console.is-closing { opacity: 0; }
.anima-console-head { display: flex; align-items: center; gap: 10px; padding: 6px 10px;
  border-bottom: 1px solid rgba(124,106,239,0.2); font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); }
.anima-console-head b { color: var(--text-primary); font-weight: 600; }
.anima-console-state { margin-left: auto; }
.anima-console-state.ok { color: var(--success); }
.anima-console-state.err { color: #f07070; }
.anima-console-x { background: none; border: 0; color: var(--text-dim); cursor: pointer; font-size: 12px; padding: 0 2px; }
.anima-console-x:hover { color: var(--text-primary); }
.anima-console-log { flex: 1; margin: 0; padding: 8px 10px; overflow: auto; white-space: pre-wrap; word-break: break-all;
  font-family: var(--font-mono); font-size: 10.5px; line-height: 1.45; color: #b8c0cc; user-select: text; }
`;

// 터미널 색 코드 · 진행 막대의 되감기(\r)를 걷어낸다 - 줄마다 마지막 덮어쓴 모양만
const ANSI = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
const cleanLine = line => String(line).replace(ANSI, '').split('\r').filter(Boolean).pop() || '';

export function createAnimaEngineConsole({ document, window: win = window, fetch: fetchFn = win.fetch.bind(win),
  getHost = () => document.getElementById('resultViewer') }) {
  let el = null;
  let logEl = null;
  let stateEl = null;
  let elapsedEl = null;
  let lines = [];
  let since = null;
  let phase = 'idle';        // idle | starting | closing | failed
  let seq = 0;
  let pollTimer = 0;
  let clockTimer = 0;
  let closeTimer = 0;
  let startedAt = 0;
  let seenStarting = false;

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
    el.className = 'anima-console';
    el.hidden = true;
    el.setAttribute('role', 'log');
    el.setAttribute('aria-label', 'ANIMA 엔진 켜는 중 - ComfyUI 출력');
    const head = document.createElement('div');
    head.className = 'anima-console-head';
    const title = document.createElement('b');
    title.textContent = 'ANIMA 엔진 · ComfyUI';
    elapsedEl = document.createElement('span');
    elapsedEl.className = 'anima-console-elapsed';
    stateEl = document.createElement('span');
    stateEl.className = 'anima-console-state';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'anima-console-x';
    close.textContent = '✕';
    close.title = '닫기';
    close.setAttribute('aria-label', '닫기');
    close.addEventListener('click', () => hide());
    head.append(title, elapsedEl, stateEl, close);
    logEl = document.createElement('pre');
    logEl.className = 'anima-console-log';
    el.append(head, logEl);
    host.appendChild(el);
    return el;
  }

  function setState(text, kind = '') {
    stateEl.textContent = text;
    stateEl.className = `anima-console-state${kind ? ` ${kind}` : ''}`;
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
  function append(text) {
    const atEnd = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 24;
    for (const raw of String(text).split('\n')) {
      const line = cleanLine(raw);
      if (line) lines.push(line);
    }
    if (lines.length > MAX_LINES) lines = lines.slice(-MAX_LINES);
    logEl.textContent = lines.join('\n');
    if (atEnd) logEl.scrollTop = logEl.scrollHeight;
  }

  function show() {
    if (phase === 'starting') return;               // 이미 떠 있다 - 같은 기동을 두 번 받지 않는다
    if (!ensure()) return;
    stopTimers();
    seq += 1;
    lines = [];
    since = null;
    seenStarting = false;
    phase = 'starting';
    startedAt = Date.now();
    logEl.textContent = '';
    el.classList.remove('is-closing');
    el.hidden = false;
    setState('켜는 중');
    paintClock();
    clockTimer = win.setInterval(paintClock, 100);
    poll(seq);
  }

  function hide() {
    seq += 1;
    stopTimers();
    phase = 'idle';
    if (el) {
      el.hidden = true;
      el.classList.remove('is-closing');
    }
  }

  function closeSoon(text, kind) {
    phase = 'closing';
    win.clearInterval(clockTimer);
    clockTimer = 0;
    setState(text, kind);
    const my = seq;
    closeTimer = win.setTimeout(() => {
      if (my !== seq) return;
      el.classList.add('is-closing');
      closeTimer = win.setTimeout(() => { if (my === seq) hide(); }, FADE_MS);
    }, CLOSE_MS);
  }

  function fail(engine) {
    phase = 'failed';
    stopTimers();
    const code = engine && engine.code ? ` · ${engine.code}` : '';
    setState(`켜지 못했습니다${code}`, 'err');
    append('\n엔진을 켜지 못했습니다 - API 설정 › 04 ANIMA 의 [자세히] · [에러 로그 복사] 로 확인할 수 있습니다.');
  }

  async function poll(my) {
    let data = null;
    try {
      const res = await fetchFn(since == null ? API : `${API}?since=${since}`, { cache: 'no-store' });
      data = res.ok ? await res.json() : null;
    } catch (_) {
      data = null;                                     // 끊겼다 - 다음 차례에 다시 묻는다
    }
    if (my !== seq || phase !== 'starting') return;
    if (data) {
      if (typeof data.since === 'number') since = data.since;
      if (data.text) append(data.text);
      const state = String((data.engine && data.engine.state) || '');
      if (state === 'starting') seenStarting = true;
      if (state === 'running') { closeSoon('연결됨', 'ok'); return; }
      if (state === 'crashed') { fail(data.engine); return; }
      // 처음의 stopped 는 아직 켜기 전일 수 있다(생성 요청이 엔진을 켜기 직전) - 켜는 걸 본 뒤의 stopped 만 끝이다
      if (state === 'stopped' && seenStarting) { closeSoon('엔진이 꺼졌습니다'); return; }
    }
    pollTimer = win.setTimeout(() => poll(my), POLL_MS);
  }

  return { show, hide, isShown: () => Boolean(el) && !el.hidden };
}
