// ANIMA 모드 PARAMS › Model 줄의 [Manage](사용자 지정 2026-09-30) — 모델 폴더 열기 · 내장 ComfyUI 새로고침으로 모델 갱신.
//   GET  /api/anima-engine/models          -> {models, skipped, folders: [{path, source, exists}]}  (훑기만)
//   POST /api/anima-engine/models/refresh {known} -> + {added, removed, engine: {state, checked, missing, restarted, error?}}
//        known = 지금 Model 칸에 보이는 목록(getModelOptions) — 새로 찾음 · 사라짐의 기준
//   POST /api/anima-engine/models/open-folder {index}  (폴더 차례 번호만 보낸다 · 이 PC 에서만 — 원격은 403)
// 새로고침 = 서버가 폴더를 다시 훑고, 엔진이 켜져 있으면 ComfyUI 에게도 목록을 다시 읽힌다(/object_info/UNETLoader).
// 그 뒤 onModelsChanged(= app.js 의 ws 'sync')로 Model 칸 목록을 새로 받는다 — ANIMA 설정의 모델 폴더가 바뀔 때와 같은 길.
// 단추를 보일지는 app.js(syncAnimaModelManageButton — 관리형 ANIMA 일 때만)가 정한다.
// 컴팩트 팝업 규약(Memo · Tagger): 좁은 창 · 머리줄 28px · 글자 9.5~11px. style.css 는 건드리지 않는다(아래 STYLE).

const API = '/api/anima-engine';
const STYLE_ID = 'animaModelManageStyle';
const REMOTE_FOLDER = '폴더 열기는 NAIA 를 켠 PC 에서만 할 수 있습니다.';
const SOURCE_LABEL = { managed: '기본 폴더', reuse: '가져온 설치' };
const STYLE = `
.amm-pop { position: fixed; z-index: var(--z-floating-module-aux); width: min(380px, calc(100vw - 16px));
  display: flex; flex-direction: column; border: 1px solid rgba(130,150,255,0.30); border-radius: 8px;
  background: rgba(15,15,23,0.98); box-shadow: 0 18px 42px rgba(0,0,0,0.42); overflow: hidden; }
.amm-head { min-height: 28px; display: flex; align-items: center; gap: 6px; padding: 0 4px 0 10px;
  border-bottom: 1px solid var(--border-dim); background: rgba(22,24,38,0.9); }
.amm-title { font-family: var(--font-mono); font-size: 10.5px; font-weight: 700; letter-spacing: 0.3px; color: var(--text-primary); }
.amm-count { flex: 1; min-width: 0; font-size: 9.5px; color: var(--text-dim); }
.amm-x { width: 22px; height: 22px; border: 0; border-radius: 5px; background: none; color: var(--text-dim); cursor: pointer; }
.amm-x:hover { background: var(--bg-hover); color: var(--text-primary); }
.amm-body { display: flex; flex-direction: column; gap: 4px; padding: 8px 10px; }
.amm-folder { display: flex; align-items: center; gap: 8px; width: 100%; padding: 5px 8px; border: 1px solid var(--border-dim);
  border-radius: 5px; background: rgba(124,106,239,0.06); color: var(--text-muted); font-size: 11px; text-align: left; cursor: pointer; }
.amm-folder:hover:not(:disabled) { border-color: var(--accent); color: var(--text-primary); }
.amm-folder:disabled { opacity: 0.5; cursor: default; }
.amm-folder:focus-visible, .amm-refresh:focus-visible, .amm-x:focus-visible { outline: 1px solid var(--accent); outline-offset: 1px; }
.amm-src { flex: none; font-family: var(--font-mono); font-size: 9.5px; color: var(--accent-glow); }
.amm-path { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.amm-open { flex: none; font-size: 9.5px; color: var(--text-dim); }
.amm-note { font-size: 9.5px; line-height: 1.45; color: var(--text-dim); }
.amm-foot { display: flex; align-items: center; gap: 8px; padding: 6px 10px 8px; border-top: 1px solid rgba(42,42,61,0.5); }
.amm-refresh { flex: none; height: 22px; padding: 0 10px; border: 1px solid rgba(124,106,239,0.55); border-radius: 5px;
  background: rgba(124,106,239,0.16); color: var(--text-primary); font-size: 10.5px; cursor: pointer; }
.amm-refresh:hover:not(:disabled) { background: rgba(124,106,239,0.28); }
.amm-refresh:disabled { opacity: 0.55; cursor: default; }
.amm-status { flex: 1; min-width: 0; font-size: 9.5px; line-height: 1.4; color: var(--text-dim); }
.amm-status.warn { color: #e0b46a; }
`;

export function createAnimaModelManage({ document, window: win = window, fetch: fetchFn = win.fetch.bind(win),
  showToast = () => {}, onModelsChanged = () => {}, getModelOptions = () => null }) {
  let popup = null;
  let anchor = null;
  let data = null;          // 마지막 GET /models 또는 새로고침 응답
  let status = '';          // 발밑 한 줄(새로고침 결과)
  let warn = false;
  let busy = false;
  let seq = 0;              // 닫았다 다시 열면 앞서 연 창의 늦은 응답을 버린다
  const listeners = [];

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = STYLE;
    document.head.appendChild(style);
  }

  async function call(method, path, body) {
    const init = { method, cache: 'no-store' };
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    const res = await fetchFn(`${API}${path}`, init);
    const out = await res.json().catch(() => ({}));
    if (!res.ok || out.ok === false) {
      const err = new Error(out.error || `요청 실패 (${res.status})`);
      err.status = res.status;
      throw err;
    }
    return out;
  }

  /** 경로의 끝 두 폴더만 보인다 — 전체 경로는 말풍선에 */
  function tail(path) {
    const parts = String(path || '').split(/[\\/]+/).filter(Boolean);
    return parts.length > 2 ? `…\\${parts.slice(-2).join('\\')}` : String(path || '');
  }

  function listShort(names, max = 3) {
    const shown = names.slice(0, max).join(', ');
    return names.length > max ? `${shown} 외 ${names.length - max}개` : shown;
  }

  /** 새로고침 결과 한 줄 — 몇 개 · 새로 찾은 것 · 사라진 것 · 엔진이 못 본 것 */
  function summarize(out) {
    const parts = [`모델 ${(out.models || []).length}개`];
    if ((out.added || []).length) parts.push(`새로 찾음 ${listShort(out.added)}`);
    if ((out.removed || []).length) parts.push(`사라짐 ${listShort(out.removed)}`);
    if (!(out.added || []).length && !(out.removed || []).length) parts.push('바뀐 것 없음');
    const engine = out.engine || {};
    let caution = false;
    if (engine.restarted) {
      parts.push('엔진이 새 목록을 못 봐서 내렸습니다 — 다음 생성이 새로 켭니다');
    } else if ((engine.missing || []).length) {
      parts.push(`엔진이 아직 못 본 모델 ${listShort(engine.missing)} — 생성이 끝난 뒤 이 PC 에서 다시 새로고침`);
      caution = true;
    } else if (engine.error) {
      parts.push('엔진에 목록을 묻지 못했습니다');
      caution = true;
    }
    return { text: parts.join(' · '), caution };
  }

  function html() {
    const folders = (data && data.folders) || [];
    const count = data ? `${(data.models || []).length}개` : '불러오는 중…';
    const skipped = (data && data.skipped) || [];
    const rows = folders.map((folder, index) => {
      const label = SOURCE_LABEL[folder.source] || '추가 폴더';
      return `<button type="button" class="amm-folder" data-amm-open="${index}" ${folder.exists ? '' : 'disabled'}
        title="${esc(folder.path)}${folder.exists ? ' — 눌러서 열기' : ' — 폴더가 없습니다'}">
        <span class="amm-src">${esc(label)}</span><span class="amm-path">${esc(tail(folder.path))}</span>
        <span class="amm-open">${folder.exists ? '열기' : '없음'}</span></button>`;
    }).join('');
    const skippedNote = skipped.length
      ? `<div class="amm-note" title="${esc(skipped.map(item => item.name).join('\n'))}">앞 폴더에 같은 이름이 있어 뺀 파일 ${skipped.length}개</div>`
      : '';
    return `<div class="amm-head"><span class="amm-title">ANIMA 모델</span><span class="amm-count">${esc(count)}</span>
        <button type="button" class="amm-x" data-amm-close aria-label="닫기">×</button></div>
      <div class="amm-body">${rows || '<div class="amm-note">모델 폴더를 읽지 못했습니다.</div>'}${skippedNote}
        <div class="amm-note">모델 파일(.safetensors)을 폴더에 넣고 [새로고침] — 하위 폴더도 읽습니다. 폴더를 더하려면 API 설정 › ANIMA.</div></div>
      <div class="amm-foot"><button type="button" class="amm-refresh" data-amm-refresh ${busy ? 'disabled' : ''}
          title="폴더를 다시 읽고, 엔진이 켜져 있으면 내장 ComfyUI 에게도 목록을 다시 읽힙니다">${busy ? '새로고침 중…' : '새로고침'}</button>
        <span class="amm-status${warn ? ' warn' : ''}">${esc(status)}</span></div>`;
  }

  function paint() {
    if (!popup) return;
    popup.innerHTML = html();
    place();
  }

  /** 단추 바로 아래 · 오른쪽 끝을 맞춘다. 화면 밖으로 나가면 안쪽으로(위로 뒤집기 포함) — 실측으로 가둔다 */
  function place() {
    if (!popup || !anchor) return;
    const rect = anchor.getBoundingClientRect();
    const vw = win.innerWidth || document.documentElement.clientWidth || 800;
    const vh = win.innerHeight || document.documentElement.clientHeight || 600;
    const box = popup.getBoundingClientRect();
    let left = rect.right - box.width;
    left = Math.max(8, Math.min(left, vw - box.width - 8));
    let top = rect.bottom + 4;
    if (top + box.height > vh - 8) top = Math.max(8, rect.top - box.height - 4);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  async function load() {
    const mine = ++seq;
    try {
      const out = await call('GET', '/models');
      if (mine !== seq || !popup) return;
      data = out;
    } catch (error) {
      if (mine !== seq || !popup) return;
      data = { models: [], skipped: [], folders: [] };
      status = `목록을 읽지 못했습니다 — ${error.message}`;
      warn = true;
    }
    paint();
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    status = '';
    warn = false;
    paint();
    const mine = seq;
    try {
      const known = getModelOptions();
      const out = await call('POST', '/models/refresh', Array.isArray(known) ? { known } : {});
      const { text, caution } = summarize(out);
      if (popup && mine === seq) {
        data = out;
        status = text;
        warn = caution;
      }
      showToast(`ANIMA 모델 새로고침 — ${text}`, caution ? 'warning' : 'success');
      onModelsChanged();
    } catch (error) {
      if (popup && mine === seq) {
        status = `새로고침하지 못했습니다 — ${error.message}`;
        warn = true;
      }
      showToast(`ANIMA 모델 새로고침 실패 — ${error.message}`, 'error');
    } finally {
      busy = false;
      paint();
    }
  }

  async function openFolder(index) {
    try {
      const out = await call('POST', '/models/open-folder', { index });
      showToast(`모델 폴더를 열었습니다 — ${out.path || ''}`, 'success');
    } catch (error) {
      showToast(error.status === 403 ? REMOTE_FOLDER : `폴더를 열지 못했습니다 — ${error.message}`, 'error');
    }
  }

  function onClick(event) {
    const target = event.target;
    if (target.closest('[data-amm-close]')) { close(); return; }
    if (target.closest('[data-amm-refresh]')) { void refresh(); return; }
    const row = target.closest('[data-amm-open]');
    if (row && !row.disabled) void openFolder(Number(row.dataset.ammOpen));
  }

  function on(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    listeners.push(() => target.removeEventListener(type, handler, options));
  }

  function open(anchorEl) {
    if (popup) { close(); return; }             // 같은 단추를 다시 누르면 닫는다
    ensureStyle();
    anchor = anchorEl || null;
    status = '';
    warn = false;
    popup = document.createElement('div');
    popup.className = 'amm-pop';
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', 'ANIMA 모델');
    document.body.appendChild(popup);
    paint();
    on(popup, 'click', onClick);
    // 바깥을 누르면 닫는다 — 여는 단추는 제외(그 단추의 click 이 토글한다)
    on(document, 'pointerdown', event => {
      if (!popup || popup.contains(event.target) || (anchor && anchor.contains(event.target))) return;
      close();
    }, true);
    on(document, 'keydown', event => { if (event.key === 'Escape') close(); });
    on(win, 'resize', () => place());
    void load();
  }

  function close() {
    seq += 1;
    while (listeners.length) listeners.pop()();
    popup?.remove();
    popup = null;
    anchor = null;
  }

  return { open, close, isOpen: () => !!popup };
}
