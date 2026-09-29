// ANIMA 전용 도구 > LoRA 창 — 관리형 엔진의 LoRA 컨테이너(사용자 지정 2026-09-27: 백엔드보다 먼저 화면).
// "COMFYUI 전용 도구" 자리에 ANIMA 전용 도구[해상도 프리셋 · LoRA]를 두고 LoRA 는 따로 뜨는 창으로.
// LoRA 컨테이너 규칙(사용자 지정): ① 폴더 열기로 LoRA 폴더에 접근 ② LoRA 마다 PNG 1장 칸 + 스키마 칸
//   (스키마는 복잡한 걸 보이지 않고 트리거 워드가 있으면 알려 준다) ③ (TODO) 썸네일 채우기 — 이번엔 없다.
// 창은 Memo 처럼 Tag Search 의 뼈대(tagsearch-*)를 입는다 — 컴팩트 팝업 규약(Memo · Tagger).
// 관리형 여부(COMFYUI 모드 + comfyui_engine 'managed' + 설치 준비됨)도 여기서 판단해 런처에 알린다(isManaged).
// 계약 = docs/ANIMA_MANAGED_ENGINE_CONTRACT_2026_09_27.md §3.3 · §8.3 · §8.4:
//   GET /loras -> {available: [{name, size, source, conflict, triggers, thumb}], chain, warnings}
//   PUT /loras {chain: [{name, strength, enabled}]} · GET/PUT/DELETE /loras/thumb?name= · POST /loras/open-folder {name?}
// 적힌 순서대로 LoraLoaderModelOnly 사슬이 된다 — 정렬하지 않는다. 끈 항목은 그래프에서만 빠지고 목록 · 순서는 남는다.
// 서버는 생성을 큐에 넣는 순간의 체인을 요청에 박는다(여기서 바꿔도 이미 대기 중인 생성은 그대로).
// 서버가 돌려준 체인이 정본이다 — 거절(422)되면 이유를 보이고 서버 것을 다시 읽는다(몰래 고치지 않는다).
// style.css 는 건드리지 않는다(아래 STYLE — 새 클래스의 CSS 를 같은 파일에 둔다).

const API = '/api/anima-engine';
const STYLE_ID = 'animaLoraStyle';
const BADGE_ID = 'badgeAnimaLora';   // 런처의 LoRA 항목 배지(카테고리 칩 "L{켜진 수}")
const MAX_CHAIN = 32;                // 계약서 §3.3 — 요청 크기 보호용 상한(임의의 4개 같은 상한은 두지 않는다)
const STRENGTH_MIN = -2;
const STRENGTH_MAX = 2;
const SLIDER_MAX = 2;               // 슬라이더는 0 ~ 2(흔히 쓰는 쪽) - 음수는 칸에 적는다
const STEP = 0.05;
const WHEEL_SAVE_MS = 400;          // 휠은 멈춘 뒤 한 번 저장한다(돌리는 동안 매번 보내지 않는다)
const DOCK_ID = 'animaLoraDock';    // 프롬프트 밑 LoRA 줄(Estimated Tokens 위)
const RECHECK_MS = 5000;             // params 에코마다 상태를 다시 묻지 않는다
const MAX_THUMB_BYTES = 10 * 1024 * 1024;
const FLASH_MS = 1600;
const REMOTE_FOLDER = '폴더 열기는 NAIA 를 켠 PC 에서만 할 수 있습니다.';
const STYLE = `
.anima-lora-popup { width: min(460px, calc(100vw - 16px)); height: min(560px, calc(100vh - 16px)); }
.anima-lora-popup .alr-headbtn { height: 22px; padding: 0 8px; font-size: 10px; flex: none; }
.anima-lora-popup .alr-sec { display: flex; align-items: center; gap: 6px; padding: 5px 10px 4px;
  font-family: var(--font-mono); font-size: 9.5px; letter-spacing: 0.4px; color: var(--text-dim);
  border-bottom: 1px solid rgba(42,42,61,0.5); }
.anima-lora-popup .alr-chain { flex: 0 1 auto; max-height: 186px; min-height: 0; overflow-y: auto;
  border-bottom: 1px solid var(--border-dim); }
.anima-lora-popup .alr-item { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; row-gap: 3px; padding: 5px 10px;
  border-bottom: 1px solid rgba(42,42,61,0.5); }
/* 강도는 이름 밑 둘째 줄 - 순서 단추(↑↓)가 강도 칸 바로 옆에 있어 강도를 올리고 내리는 단추로 읽혔다
   (사용자 지적 09-29 "가중치 조절이 비직관적"). */
.anima-lora-popup .alr-item > .alr-strength { flex-basis: 100%; padding-left: 44px; }
.anima-lora-popup .alr-item:last-child { border-bottom: 0; }
.anima-lora-popup .alr-item.off .alr-name, .anima-lora-popup .alr-item.off .alr-strength { opacity: 0.45; }
.anima-lora-popup .alr-item input[type=checkbox] { accent-color: var(--accent); cursor: pointer; margin: 0; flex: none; }
.anima-lora-popup .alr-idx { font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); width: 14px; text-align: right; flex: none; }
.anima-lora-popup .alr-name { flex: 1; min-width: 0; font-family: var(--font-editor); font-size: 11.5px; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-badge { font-family: var(--font-mono); font-size: 9px; padding: 0 5px; border-radius: 3px; flex: none;
  background: rgba(240,64,64,0.16); color: #f07070; }
/* 강도 - 슬라이더(0~2 · 0.05)로 끌고, 칸에는 정확한 값(-2~2, 음수 포함). 창과 프롬프트 밑 LoRA 줄이 같이 쓴다. */
.alr-strength { display: flex; align-items: center; gap: 8px; min-width: 0; }
.alr-strength input[type=range] { flex: 1; min-width: 60px; height: 16px; margin: 0; accent-color: var(--accent);
  cursor: pointer; background: transparent; }
.alr-strength input[type=range]:disabled { cursor: default; opacity: 0.5; }
.alr-strength .alr-w { width: 52px; flex: none; font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);
  text-align: right; background: rgba(0,0,0,0.28); border: 1px solid var(--border-dim); border-radius: 5px; padding: 2px 5px;
  height: 22px; outline: none; }
.alr-strength .alr-w:focus { border-color: var(--accent); color: var(--accent-glow); }
/* 프롬프트 밑 LoRA 줄(사용자 지정 09-29) - Estimated Tokens 바로 위. 켜고 끄기 · 강도만, 순서 · 넣기 · 빼기는 창([편집]).
   부모(.prompt-token-footer)가 pointer-events:none 이라 여기서 다시 연다. 입력칸은 그 높이만큼 아래를 비운다. */
.anima-lora-dock { align-self: stretch; pointer-events: auto; display: flex; flex-direction: column; gap: 3px;
  padding: 0 0 5px; margin-bottom: 2px; border-bottom: 1px solid rgba(232,232,240,0.08); max-height: 104px; overflow-y: auto; }
.anima-lora-dock[hidden] { display: none !important; }
.anima-lora-dock .ald-head { display: flex; align-items: center; gap: 8px; font-size: 9.5px; letter-spacing: 0.4px;
  color: var(--text-dim); }
.anima-lora-dock .ald-head b { color: var(--accent-glow); font-weight: 600; }
.anima-lora-dock .ald-edit { margin-left: auto; height: 18px; padding: 0 8px; font-family: var(--font-mono); font-size: 9.5px;
  color: var(--text-muted); background: rgba(96,120,255,0.1); border: 1px solid rgba(130,150,255,0.3); border-radius: 5px;
  cursor: pointer; }
.anima-lora-dock .ald-edit:hover { color: var(--text-primary); background: rgba(96,120,255,0.2); }
.anima-lora-dock .ald-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.anima-lora-dock .ald-row input[type=checkbox] { accent-color: var(--accent); cursor: pointer; margin: 0; flex: none; }
.anima-lora-dock .ald-name { flex: 0 1 36%; min-width: 0; font-family: var(--font-editor); font-size: 11px;
  color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-dock .ald-row > .alr-strength { flex: 1; }
.anima-lora-dock .ald-row.off .ald-name, .anima-lora-dock .ald-row.off .alr-strength { opacity: 0.45; }
.prompt-highlight-wrap.has-anima-lora-dock .prompt-edit,
.prompt-highlight-wrap.has-anima-lora-dock .prompt-highlight { padding-bottom: calc(66px + var(--anima-lora-dock-h, 0px)); }
.anima-lora-popup .alr-btns { display: inline-flex; gap: 1px; flex: none; }
.anima-lora-popup .alr-btns button { background: none; border: 0; color: var(--text-dim); cursor: pointer; font-size: 10px;
  width: 20px; height: 22px; padding: 0; border-radius: 4px; line-height: 22px; }
.anima-lora-popup .alr-btns button:hover:not(:disabled) { color: var(--text-primary); background: rgba(96,120,255,0.14); }
.anima-lora-popup .alr-btns button[data-lora-rm]:hover:not(:disabled) { color: #f07070; background: rgba(255,90,90,0.14); }
.anima-lora-popup .alr-btns button:disabled { opacity: 0.25; cursor: default; }
.anima-lora-popup .alr-searchrow { padding: 6px 10px; }
.anima-lora-popup .alr-searchrow .tagsearch-input { height: 26px; font-size: 11px; }
.anima-lora-popup .alr-lib { flex: 1; min-height: 0; overflow-y: auto; }
.anima-lora-popup .alr-card { display: flex; gap: 10px; padding: 7px 10px; border-bottom: 1px solid rgba(42,42,61,0.5); }
.anima-lora-popup .alr-card.in-chain { background: rgba(96,120,255,0.07); }
.anima-lora-popup .alr-png { position: relative; flex: none; width: 54px; height: 72px; border-radius: 6px; overflow: hidden;
  border: 1px dashed var(--border-glow); background: rgba(0,0,0,0.28); cursor: pointer; padding: 0;
  display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-family: var(--font-mono); font-size: 9px; }
.anima-lora-popup .alr-png.has-img { border-style: solid; border-color: var(--border-dim); }
.anima-lora-popup .alr-png.drop { border-color: var(--accent); background: rgba(124,106,239,0.16); }
.anima-lora-popup .alr-png img { width: 100%; height: 100%; object-fit: cover; display: block; }
.anima-lora-popup .alr-card-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.anima-lora-popup .alr-card-top { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
.anima-lora-popup .alr-card-name { flex: 1; min-width: 0; font-family: var(--font-editor); font-size: 11.5px; font-weight: 600;
  color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-card-meta { flex: none; font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); }
.anima-lora-popup .alr-trig { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: 10px; color: var(--text-dim); }
.anima-lora-popup .alr-chip { font-family: var(--font-editor); font-size: 10.5px; padding: 1px 6px; border-radius: 4px; cursor: pointer;
  border: 1px solid rgba(130,150,255,0.36); background: rgba(96,120,255,0.12); color: var(--text-primary); }
.anima-lora-popup .alr-chip:hover { background: rgba(96,120,255,0.24); }
.anima-lora-popup .alr-guess { font-size: 9px; color: #f5df8b; }
.anima-lora-popup .alr-card-acts { display: flex; align-items: center; gap: 6px; margin-top: auto; }
.anima-lora-popup .alr-card-acts .tagsearch-act { height: 22px; padding: 0 8px; font-size: 10px; }
.anima-lora-popup .alr-inchain { font-family: var(--font-mono); font-size: 9.5px; color: var(--accent-glow); }
.anima-lora-popup .alr-mini { background: none; border: 0; padding: 0; color: var(--text-dim); cursor: pointer; font-size: 10px; }
.anima-lora-popup .alr-mini:hover { color: var(--text-primary); text-decoration: underline; }
.anima-lora-popup .alr-empty { padding: 16px 12px; text-align: center; font-size: 11px; color: var(--text-dim); line-height: 1.6; }
.anima-lora-popup .alr-foot { padding: 6px 10px; border-top: 1px solid var(--border-dim); display: flex; flex-direction: column; gap: 3px; }
.anima-lora-popup .alr-note { font-size: 10px; color: var(--text-dim); line-height: 1.5; }
.anima-lora-popup .alr-warn { font-size: 10px; color: #f5df8b; line-height: 1.5; }
.anima-lora-popup .alr-error { font-size: 10px; color: #f07070; line-height: 1.5; }
.anima-lora-popup .alr-link { background: none; border: 0; padding: 0; color: var(--accent-glow); cursor: pointer; font-size: inherit; }
.anima-lora-popup .alr-link:hover { text-decoration: underline; }
`;

export function createAnimaLoraPanel({ document, window: win = window, fetch: fetchFn = win.fetch.bind(win),
  onOpenSetup = () => {}, onStateChange = () => {} }) {
  let mode = '';
  let managed = false;       // 관리형 + 준비됨 — 런처가 ANIMA 전용 도구를 보일지 여기로 묻는다
  let checkedAt = 0;
  let checking = null;       // 진행 중인 상태 확인(Promise) — 겹쳐 묻지 않는다
  let available = [];
  let chain = [];
  let warnings = [];
  let error = '';
  let busy = false;
  let filter = '';
  let flashText = '';
  let flashTimer = 0;
  let pngTarget = '';        // 파일 고르기 창을 연 카드의 LoRA 이름
  let popup = null;
  let onResize = null;
  let dock = null;           // 프롬프트 밑 LoRA 줄 - 켜진 관리형 체인이 있을 때만 보인다
  let dragging = false;      // 강도 슬라이더를 끄는 중 - 그동안 줄을 다시 그리지 않는다(손잡이가 사라진다)
  let wheelTimer = 0;

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const shortName = name => String(name || '').replace(/\.safetensors$/i, '');
  const fmtStrength = value => (Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '1.00');
  const fmtSize = bytes => (Number(bytes) >= 1048576 ? `${Math.round(Number(bytes) / 1048576)}MB` : `${Math.max(1, Math.round((Number(bytes) || 0) / 1024))}KB`);
  const pick = selector => (popup ? popup.querySelector(selector) : null);
  const thumbUrl = item => `${API}/loras/thumb?name=${encodeURIComponent(item.name)}&v=${encodeURIComponent(item.thumb.version ?? '')}`;

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
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const err = new Error(data.error || `요청 실패 (${res.status})`);
      err.status = res.status;
      err.code = data.code || '';
      throw err;
    }
    return data;
  }

  function flash(text) {
    flashText = text;
    win.clearTimeout?.(flashTimer);
    flashTimer = win.setTimeout?.(() => { flashText = ''; paintStatus(); }, FLASH_MS);
    paintStatus();
  }

  // ---- 관리형인가(런처가 묻는다) ----

  function isManaged() {
    return managed && mode === 'COMFYUI';
  }

  function check() {
    if (checking) return checking;
    checking = (async () => {
      const before = isManaged();
      try {
        const st = await call('GET', '/status');
        managed = st.comfyui_engine === 'managed' && ((st.install || {}).state === 'ready');
      } catch (err) {
        managed = false;          // 백엔드가 없는 판(404) · 끊김 — ANIMA 전용 도구를 숨긴다
      }
      checkedAt = Date.now();
      checking = null;
      if (isManaged()) await load();
      else paintOutside();
      if (before !== isManaged()) onStateChange();
    })();
    return checking;
  }

  function setMode(next) {
    const before = isManaged();
    mode = String(next || '').toUpperCase();
    if (mode === 'COMFYUI' && Date.now() - checkedAt > RECHECK_MS) check();
    if (before !== isManaged()) {
      if (!isManaged()) close();
      onStateChange();
    }
    paintOutside();
  }

  function refresh() {
    checkedAt = 0;
    if (mode === 'COMFYUI') return check();
    return Promise.resolve();
  }

  // ---- 서버 ----

  async function load() {
    try {
      const data = await call('GET', '/loras');
      available = Array.isArray(data.available) ? data.available : [];
      chain = Array.isArray(data.chain) ? data.chain : [];
      warnings = Array.isArray(data.warnings) ? data.warnings : [];
    } catch (err) {
      error = err.message;
    }
    render();
  }

  async function save(next) {
    busy = true;
    error = '';
    render(next);
    try {
      const data = await call('PUT', '/loras', {
        chain: next.map(item => ({ name: item.name, strength: Number(item.strength), enabled: item.enabled !== false })),
      });
      chain = Array.isArray(data.chain) ? data.chain : next;
      busy = false;
      render();
    } catch (err) {
      busy = false;
      error = err.message;
      await load();                // 거절됐다 — 서버가 들고 있는 체인으로 되돌린다
    }
  }

  // LoRA 마다 PNG 한 장(계약서 §8.4) — 받은 바이트를 그대로 보내고 서버가 시그니처 · 크기를 다시 본다.
  async function uploadThumb(name, file) {
    if (!name || !file) return;
    if (file.type !== 'image/png' || Number(file.size) > MAX_THUMB_BYTES) {
      error = 'PNG 파일만 넣을 수 있습니다(10MB 이하).';
      render();
      return;
    }
    busy = true;
    error = '';
    render();
    try {
      const res = await fetchFn(`${API}/loras/thumb?name=${encodeURIComponent(name)}`, {
        method: 'PUT', headers: { 'Content-Type': 'image/png' }, body: await file.arrayBuffer(), cache: 'no-store',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) throw new Error(data.error || `요청 실패 (${res.status})`);
      flash('PNG 를 넣었습니다');
    } catch (err) {
      error = err.message;
    }
    busy = false;
    await load();
  }

  async function deleteThumb(name) {
    busy = true;
    render();
    try {
      await call('DELETE', `/loras/thumb?name=${encodeURIComponent(name)}`);
    } catch (err) {
      error = err.message;
    }
    busy = false;
    await load();
  }

  async function openFolder(name) {
    try {
      await call('POST', '/loras/open-folder', name ? { name } : {});
      flash('폴더를 열었습니다');
    } catch (err) {
      error = err.status === 403 ? REMOTE_FOLDER : err.message;
      render();
    }
  }

  // ---- 그리기 ----

  // 런처 LoRA 항목의 배지 — 켜진 LoRA 수(0 이면 숨김). 카테고리 칩은 런처가 "L{n}" 으로 모은다.
  function paintBadge() {
    const badge = document.getElementById(BADGE_ID);
    if (!badge) return;
    const on = isManaged() ? chain.filter(item => item.enabled !== false).length : 0;
    const text = on ? String(on) : '';
    if (badge.textContent !== text) badge.textContent = text;
    badge.classList.toggle('hidden', !on);
  }

  // 창 밖에 보이는 것 - 런처 배지와 프롬프트 밑 LoRA 줄
  function paintOutside(view = chain) {
    paintBadge();
    paintDock(view);
  }

  // 강도 - 슬라이더(0~2)로 끌고 칸에는 정확한 값을 적는다(-2~2, 음수 포함). 놓을 때 한 번 저장한다.
  // 더블클릭 = 1.00 · 휠 = ±0.05(Shift ±0.25). 음수면 슬라이더는 0 에 서 있다(칸이 정본).
  function strengthHtml(i, strength) {
    const value = Number.isFinite(Number(strength)) ? Number(strength) : 1;
    const slider = Math.min(SLIDER_MAX, Math.max(0, value));
    return `<span class="alr-strength" title="강도 · 더블클릭 = 1.00 · 휠 = ±0.05 · 음수는 칸에 적습니다">
        <input type="range" data-lora-slider="${i}" min="0" max="${SLIDER_MAX}" step="${STEP}" value="${slider}"
               aria-label="강도"${busy ? ' disabled' : ''}>
        <input class="alr-w" data-lora-w="${i}" type="number" step="${STEP}" min="${STRENGTH_MIN}" max="${STRENGTH_MAX}"
               value="${fmtStrength(strength)}" aria-label="강도"${busy ? ' disabled' : ''}></span>`;
  }

  // 다시 그린 뒤 초점을 같은 조작으로 돌려놓는다 - 칸만이 아니라 슬라이더도(키보드 ←→ 로 연달아 움직일 때 저장마다
  // 줄이 새로 그려져 초점이 사라졌다, 라이브 09-29). ⚠️ 저장하는 동안(busy)은 조작이 잠겨 초점을 받지 못한다 - 그때는
  // 자리를 기억해 두고 다음 그리기(저장이 끝난 뒤)에서 준다. 그사이 사람이 다른 곳을 눌렀으면 그쪽이 이긴다.
  const pendingFocus = new WeakMap();

  function focusKey(container) {
    const active = document.activeElement;
    if (active && container.contains?.(active)) {
      for (const attr of ['data-lora-w', 'data-lora-slider']) {
        const index = active.getAttribute?.(attr);
        if (index != null) return [attr, index];
      }
      return null;
    }
    return !active || active === document.body ? pendingFocus.get(container) || null : null;
  }

  function restoreFocus(container, key) {
    pendingFocus.delete(container);
    const target = key ? container.querySelector?.(`[${key[0]}="${key[1]}"]`) : null;
    if (!target) return;
    if (target.disabled) pendingFocus.set(container, key);
    else target.focus?.();
  }

  function ensureDock() {
    if (dock) return dock;
    const footer = document.getElementById('promptTokenFooter');
    if (!footer || typeof footer.insertBefore !== 'function') return null;
    dock = document.createElement('div');
    dock.className = 'anima-lora-dock';
    dock.id = DOCK_ID;
    dock.hidden = true;
    footer.insertBefore(dock, footer.firstChild);   // Estimated Tokens 줄 바로 위
    listen(dock);
    return dock;
  }

  // 프롬프트 밑 LoRA 줄(사용자 지정 09-29) - 관리형 ANIMA 이고 체인이 있을 때만. 켜기 · 강도만 여기서, 순서 · 넣기 ·
  // 빼기는 창([편집]). 체인은 창과 하나다(같은 save) - 어느 쪽에서 바꿔도 둘 다 다시 그린다.
  function paintDock(view = chain) {
    const el = ensureDock();
    if (!el) return;
    const wrap = typeof el.closest === 'function' ? el.closest('.prompt-highlight-wrap') : null;
    if (!isManaged() || !view.length) {
      el.hidden = true;
      el.innerHTML = '';
      wrap?.classList.remove('has-anima-lora-dock');
      return;
    }
    if (dragging) return;
    const on = view.filter(item => item.enabled !== false).length;
    const focused = focusKey(el);
    el.innerHTML = `<div class="ald-head">LoRA <b>${on} / ${view.length}</b>
        <button type="button" class="ald-edit" data-lora-act="open" title="LoRA 창 - 넣기 · 빼기 · 순서">편집</button></div>
      ${view.map((item, i) => `<div class="ald-row${item.enabled === false ? ' off' : ''}">
        <input type="checkbox" data-lora-on="${i}"${item.enabled === false ? '' : ' checked'}${busy ? ' disabled' : ''}
               title="켜기 / 끄기">
        <span class="ald-name" title="${esc(item.name)}">${esc(shortName(item.name))}</span>
        ${strengthHtml(i, item.strength)}</div>`).join('')}`;
    el.hidden = false;
    restoreFocus(el, focused);
    wrap?.classList.add('has-anima-lora-dock');
    wrap?.style?.setProperty?.('--anima-lora-dock-h', `${Math.ceil(el.offsetHeight || 0) + 2}px`);
  }

  function paintStatus(view = chain) {
    const status = pick('.tagsearch-status');
    if (!status) return;
    const on = view.filter(item => item.enabled !== false).length;
    status.textContent = busy ? '저장 중…' : flashText || (view.length ? `켜짐 ${on} / ${view.length}` : '');
    status.className = `tagsearch-status${busy ? ' busy' : flashText ? ' ok' : ''}`;
  }

  function chainHtml(view) {
    const names = new Map(available.map(item => [item.name, item]));
    if (!view.length) return '<div class="alr-empty">체인이 비어 있습니다 — 아래 목록에서 [+ 체인] 으로 넣으세요.</div>';
    return view.map((item, i) => {
      const meta = names.get(item.name);
      const badge = !meta ? '<span class="alr-badge" title="폴더에 이 파일이 없습니다 — 생성이 거절됩니다">없음</span>'
        : meta.conflict ? '<span class="alr-badge" title="같은 이름의 파일이 여러 폴더에 있습니다">이름 겹침</span>' : '';
      return `<div class="alr-item${item.enabled === false ? ' off' : ''}">
        <input type="checkbox" data-lora-on="${i}"${item.enabled === false ? '' : ' checked'}${busy ? ' disabled' : ''}
               title="켜기 / 끄기(끈 항목은 사슬에서 빠지고 자리는 남습니다)">
        <span class="alr-idx">${i + 1}</span>
        <span class="alr-name" title="${esc(item.name)}">${esc(shortName(item.name))}</span>${badge}
        <span class="alr-btns">
          <button type="button" data-lora-up="${i}" title="적용 순서 위로"${busy || i === 0 ? ' disabled' : ''}>↑</button>
          <button type="button" data-lora-down="${i}" title="적용 순서 아래로"${busy || i === view.length - 1 ? ' disabled' : ''}>↓</button>
          <button type="button" data-lora-rm="${i}" title="체인에서 빼기"${busy ? ' disabled' : ''}>✕</button>
        </span>
        ${strengthHtml(i, item.strength)}</div>`;
    }).join('');
  }

  // 스키마 칸 — 복잡한 건 보이지 않는다: 트리거 워드가 있으면 그것만(누르면 복사), 캡션 추정은 "추정" 표시.
  function triggerHtml(item) {
    const triggers = Array.isArray(item.triggers) ? item.triggers : [];
    if (!triggers.length) return '<div class="alr-trig">트리거 워드 없음</div>';
    const guessed = triggers.some(t => t.source === 'caption');
    return `<div class="alr-trig">트리거 ${triggers.map(t => `<button type="button" class="alr-chip" data-lora-copy="${
      esc(t.word)}" title="눌러서 복사">${esc(t.word)}</button>`).join('')}${
      guessed ? '<span class="alr-guess" title="학습 캡션에서 추정했습니다">추정</span>' : ''}</div>`;
  }

  function libraryHtml() {
    if (!available.length) {
      return `<div class="alr-empty">LoRA 파일이 없습니다.<br>
        <button type="button" class="alr-link" data-lora-act="folder">폴더 열기</button> 로 넣거나
        <button type="button" class="alr-link" data-lora-act="setup">API 설정 › ANIMA</button> 에서 LoRA 폴더를 추가하세요.</div>`;
    }
    const needle = filter.trim().toLowerCase();
    const shown = available.filter(item => !needle || item.name.toLowerCase().includes(needle)
      || (item.triggers || []).some(t => String(t.word).toLowerCase().includes(needle)));
    if (!shown.length) return '<div class="alr-empty">찾는 LoRA 가 없습니다.</div>';
    const full = chain.length >= MAX_CHAIN;
    return shown.map(item => {
      const at = chain.findIndex(c => c.name === item.name);
      const thumb = item.thumb && item.thumb.kind;
      const png = thumb
        ? `<img src="${esc(thumbUrl(item))}" alt="">`
        : 'PNG';
      const acts = [
        item.conflict ? '<span class="alr-badge">이름 겹침</span>'
          : at >= 0 ? `<span class="alr-inchain">체인 ${at + 1}번</span>`
            : `<button type="button" class="tagsearch-act" data-lora-addname="${esc(item.name)}"${busy || full ? ' disabled' : ''}>+ 체인</button>`,
        item.thumb && item.thumb.kind === 'naia'
          ? `<button type="button" class="alr-mini" data-lora-thumbdel="${esc(item.name)}"${busy ? ' disabled' : ''}>PNG 지우기</button>` : '',
        `<button type="button" class="alr-mini" data-lora-reveal="${esc(item.name)}" title="이 LoRA 가 든 폴더를 엽니다">폴더</button>`,
      ].join('');
      return `<div class="alr-card${at >= 0 ? ' in-chain' : ''}">
        <button type="button" class="alr-png${thumb ? ' has-img' : ''}" data-lora-png="${esc(item.name)}"
                title="PNG 넣기 — 누르거나 끌어다 놓으세요"${busy ? ' disabled' : ''}>${png}</button>
        <div class="alr-card-body">
          <div class="alr-card-top"><span class="alr-card-name" title="${esc(item.name)}">${esc(shortName(item.name))}</span>
            <span class="alr-card-meta">${fmtSize(item.size)}</span></div>
          ${triggerHtml(item)}
          <div class="alr-card-acts">${acts}</div>
        </div></div>`;
    }).join('');
  }

  function render(view = chain) {
    paintOutside(view);
    if (!popup) return;
    paintStatus(view);
    const chainEl = pick('.alr-chain');
    const libEl = pick('.alr-lib');
    if (chainEl) {
      const focused = focusKey(chainEl);
      if (!dragging) chainEl.innerHTML = isManaged() ? chainHtml(view) : '';
      restoreFocus(chainEl, focused);
    }
    if (libEl) {
      libEl.innerHTML = isManaged() ? libraryHtml()
        : `<div class="alr-empty">ANIMA 관리형 엔진이 준비되지 않았습니다.<br>
          <button type="button" class="alr-link" data-lora-act="setup">API 설정 › ANIMA</button> 에서 설치하고 고르세요.</div>`;
    }
    const foot = pick('.alr-foot');
    if (foot) {
      const notes = [];
      if (isManaged() && view.length) notes.push('<div class="alr-note">위에서부터 차례로 적용합니다 · 끈 항목은 빠집니다</div>');
      warnings.forEach(w => notes.push(`<div class="alr-warn">⚠ ${esc(w.message || w)}</div>`));
      if (error) notes.push(`<div class="alr-error">${esc(error)}</div>`);
      foot.innerHTML = notes.join('');
      foot.style.display = notes.length ? '' : 'none';
    }
  }

  // ---- 창 ----

  // Memo · Tag Search 와 같은 자리(결과 이미지 영역 좌하단) — 스테이지 안으로 실측해서 가둔다.
  function position() {
    if (!popup) return;
    const margin = 10;
    const pw = popup.offsetWidth || 460;
    const ph = popup.offsetHeight || 420;
    const host = document.getElementById('resultViewer')
      || document.getElementById('rightTabResult')
      || document.querySelector('.right-tab-pane.active');
    const rect = host ? host.getBoundingClientRect() : null;
    let left;
    let top;
    if (rect && rect.width > pw + margin * 2 && rect.height > ph + margin * 2) {
      left = rect.left + margin;
      top = rect.bottom - ph - margin;
    } else {
      left = margin;
      top = win.innerHeight - ph - margin;
    }
    left = Math.max(margin, Math.min(left, win.innerWidth - pw - margin));
    top = Math.max(margin, Math.min(top, win.innerHeight - ph - margin));
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
  }

  function build() {
    popup = document.createElement('div');
    // Tag Search 의 뼈대를 그대로 쓴다(Memo 와 같은 규약). anima-lora-popup 은 크기 · 칸만 손보는 갈고리다.
    popup.className = 'tagsearch-popup anima-lora-popup';
    popup.innerHTML = `
      <div class="tagsearch-head">
        <span class="tagsearch-title">LoRA · ANIMA</span>
        <span class="tagsearch-status"></span>
        <button type="button" class="tagsearch-act alr-headbtn" data-lora-act="folder" title="LoRA 폴더를 탐색기로 엽니다">폴더 열기</button>
        <button type="button" class="tagsearch-act alr-headbtn" data-lora-act="reload" title="LoRA 폴더를 다시 읽습니다">↻</button>
        <button type="button" class="tagsearch-x" data-lora-act="close" aria-label="닫기">&times;</button>
      </div>
      <div class="alr-sec">적용 순서</div>
      <div class="alr-chain"></div>
      <div class="tagsearch-searchrow alr-searchrow">
        <input class="tagsearch-input" type="search" data-lora-filter autocomplete="off" spellcheck="false"
               placeholder="LoRA 찾기 (이름 · 트리거 워드)">
      </div>
      <div class="alr-lib"></div>
      <div class="alr-foot"></div>
      <input type="file" accept="image/png" data-lora-file hidden>
    `;
    document.body.appendChild(popup);
    listen(popup);
    popup.addEventListener('dragover', onDragOver);
    popup.addEventListener('dragleave', onDragLeave);
    popup.addEventListener('drop', onDrop);
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
    });
  }

  // 창과 LoRA 줄이 같은 조작을 듣는다(켜기 · 강도 · 편집)
  function listen(el) {
    el.addEventListener('click', onClick);
    el.addEventListener('change', onChange);
    el.addEventListener('input', onInput);
    el.addEventListener('dblclick', onDblClick);
    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('pointerdown', event => {
      if (event.target?.closest?.('[data-lora-slider]')) dragging = true;
    });
    const release = () => { dragging = false; };
    el.addEventListener('pointerup', release);
    el.addEventListener('pointercancel', release);
  }

  function isOpen() {
    return Boolean(popup) && popup.style.display !== 'none';
  }

  function open() {
    if (!popup) build();
    popup.style.display = 'flex';
    render();
    onResize = () => position();
    win.addEventListener('resize', onResize);
    position();
    win.requestAnimationFrame?.(() => position());
    onStateChange();
    // 목록은 열 때마다 다시 받는다 — 다른 기기에서 바꿨거나 폴더에 파일을 넣었을 수 있다.
    if (isManaged()) load();
    else refresh();
  }

  function close() {
    if (!isOpen()) return;
    if (onResize) { win.removeEventListener('resize', onResize); onResize = null; }
    popup.style.display = 'none';
    onStateChange();
  }

  function toggle() {
    if (isOpen()) close();
    else open();
  }

  // ---- 조작 ----

  function move(index, delta) {
    const next = chain.slice();
    const to = index + delta;
    if (to < 0 || to >= next.length) return null;
    [next[index], next[to]] = [next[to], next[index]];
    return next;
  }

  function onClick(event) {
    const act = event.target.closest('[data-lora-act]');
    if (act) {
      const which = act.getAttribute('data-lora-act');
      if (which === 'close') close();
      else if (which === 'open') open();
      else if (which === 'setup') onOpenSetup();
      else if (which === 'folder') openFolder('');
      else if (which === 'reload' && !busy) { error = ''; refresh(); }
      return;
    }
    const copy = event.target.closest('[data-lora-copy]');
    if (copy) {
      const word = copy.getAttribute('data-lora-copy');
      Promise.resolve(win.navigator?.clipboard?.writeText(word))
        .then(() => flash(`복사했습니다: ${word}`))
        .catch(() => { error = '복사하지 못했습니다'; render(); });
      return;
    }
    const reveal = event.target.closest('[data-lora-reveal]');
    if (reveal) { openFolder(reveal.getAttribute('data-lora-reveal')); return; }
    if (busy) return;
    const png = event.target.closest('[data-lora-png]');
    if (png) {
      pngTarget = png.getAttribute('data-lora-png');
      const input = pick('[data-lora-file]');
      if (input) { input.value = ''; input.click(); }
      return;
    }
    const thumbDel = event.target.closest('[data-lora-thumbdel]');
    if (thumbDel) { deleteThumb(thumbDel.getAttribute('data-lora-thumbdel')); return; }
    const addName = event.target.closest('[data-lora-addname]');
    if (addName) {
      if (chain.length >= MAX_CHAIN) return;
      save([...chain, { name: addName.getAttribute('data-lora-addname'), strength: 1, enabled: true }]);
      return;
    }
    const up = event.target.closest('[data-lora-up]');
    const down = event.target.closest('[data-lora-down]');
    const rm = event.target.closest('[data-lora-rm]');
    let next = null;
    if (up) next = move(Number(up.getAttribute('data-lora-up')), -1);
    else if (down) next = move(Number(down.getAttribute('data-lora-down')), 1);
    else if (rm) {
      next = chain.slice();
      next.splice(Number(rm.getAttribute('data-lora-rm')), 1);
    }
    if (next) save(next);
  }

  function onChange(event) {
    const fileInput = event.target.closest('[data-lora-file]');
    if (fileInput) {
      const file = fileInput.files && fileInput.files[0];
      uploadThumb(pngTarget, file);
      return;
    }
    if (busy) return;
    const toggleBox = event.target.closest('[data-lora-on]');
    if (toggleBox) {
      const index = Number(toggleBox.getAttribute('data-lora-on'));
      save(chain.map((item, i) => (i === index ? { ...item, enabled: toggleBox.checked } : item)));
      return;
    }
    const slider = event.target.closest('[data-lora-slider]');
    if (slider) {                  // 놓았다 - 한 번 저장한다
      dragging = false;
      setStrength(Number(slider.getAttribute('data-lora-slider')), Number(slider.value));
      return;
    }
    const weight = event.target.closest('[data-lora-w]');
    if (weight) setStrength(Number(weight.getAttribute('data-lora-w')), Number(weight.value));
  }

  function setStrength(index, value) {
    if (!chain[index]) return;
    if (!Number.isFinite(value) || value < STRENGTH_MIN || value > STRENGTH_MAX) {
      error = `강도는 ${STRENGTH_MIN} ~ ${STRENGTH_MAX} 사이로 적어 주세요.`;
      render();                    // 틀린 값은 저장하지 않고 원래 값으로 되돌린다(조용히 자르지 않는다)
      return;
    }
    const next = Math.round(value * 100) / 100;
    if (Number(chain[index].strength) === next) return;
    save(chain.map((item, i) => (i === index ? { ...item, strength: next } : item)));
  }

  // 슬라이더와 칸을 함께 맞춘다(저장 없이) - 끄는 동안 · 휠을 돌리는 동안
  function showStrength(control, value) {
    const box = control.parentElement?.querySelector?.('[data-lora-w]');
    const bar = control.parentElement?.querySelector?.('[data-lora-slider]');
    if (box) box.value = fmtStrength(value);
    if (bar) bar.value = String(Math.min(SLIDER_MAX, Math.max(0, value)));
  }

  function onDblClick(event) {
    const slider = event.target.closest('[data-lora-slider]');
    if (!slider || busy) return;
    event.preventDefault?.();
    dragging = false;
    setStrength(Number(slider.getAttribute('data-lora-slider')), 1);
  }

  function onWheel(event) {
    const control = event.target.closest('[data-lora-slider], [data-lora-w]');
    if (!control || busy || control.disabled) return;
    const index = Number(control.getAttribute('data-lora-slider') ?? control.getAttribute('data-lora-w'));
    const item = chain[index];
    if (!item) return;
    event.preventDefault?.();      // 휠이 강도 위에 있으면 목록 · 입력칸을 굴리지 않는다
    const shown = Number(control.parentElement?.querySelector?.('[data-lora-w]')?.value ?? item.strength);
    const delta = (event.shiftKey ? 0.25 : STEP) * (event.deltaY < 0 ? 1 : -1);
    const value = Math.min(STRENGTH_MAX, Math.max(STRENGTH_MIN, Math.round(((Number.isFinite(shown) ? shown : 1) + delta) * 100) / 100));
    showStrength(control, value);
    win.clearTimeout?.(wheelTimer);
    wheelTimer = win.setTimeout?.(() => setStrength(index, value), WHEEL_SAVE_MS);
  }

  function onInput(event) {
    const slider = event.target.closest('[data-lora-slider]');
    if (slider) {                  // 끄는 동안 칸만 따라 바꾼다 - 저장은 놓을 때(change)
      dragging = true;
      showStrength(slider, Number(slider.value));
      return;
    }
    const box = event.target.closest('[data-lora-filter]');
    if (!box) return;
    filter = box.value;
    const libEl = pick('.alr-lib');
    if (libEl && isManaged()) libEl.innerHTML = libraryHtml();   // 목록만 다시 — 찾기 칸 글자는 그대로
  }

  // PNG 칸에 끌어다 놓기
  function onDragOver(event) {
    const slot = event.target.closest?.('[data-lora-png]');
    if (!slot || busy) return;
    event.preventDefault();
    slot.classList?.add('drop');
  }

  function onDragLeave(event) {
    event.target.closest?.('[data-lora-png]')?.classList?.remove('drop');
  }

  function onDrop(event) {
    const slot = event.target.closest?.('[data-lora-png]');
    if (!slot) return;
    event.preventDefault();
    slot.classList?.remove('drop');
    if (busy) return;
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    uploadThumb(slot.getAttribute('data-lora-png'), file);
  }

  function init() {
    ensureStyle();
  }

  return { init, setMode, refresh, isManaged, open, close, toggle, isOpen, paintBadge };
}
