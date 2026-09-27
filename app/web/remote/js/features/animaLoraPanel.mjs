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
.anima-lora-popup .alr-chain { flex: 0 1 auto; max-height: 132px; min-height: 0; overflow-y: auto;
  border-bottom: 1px solid var(--border-dim); }
.anima-lora-popup .alr-item { display: flex; align-items: center; gap: 8px; padding: 4px 10px;
  border-bottom: 1px solid rgba(42,42,61,0.5); }
.anima-lora-popup .alr-item:last-child { border-bottom: 0; }
.anima-lora-popup .alr-item.off .alr-name, .anima-lora-popup .alr-item.off .alr-w { opacity: 0.45; }
.anima-lora-popup .alr-item input[type=checkbox] { accent-color: var(--accent); cursor: pointer; margin: 0; flex: none; }
.anima-lora-popup .alr-idx { font-family: var(--font-mono); font-size: 9px; color: var(--text-dim); width: 14px; text-align: right; flex: none; }
.anima-lora-popup .alr-name { flex: 1; min-width: 0; font-family: var(--font-editor); font-size: 11.5px; color: var(--text-primary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.anima-lora-popup .alr-badge { font-family: var(--font-mono); font-size: 9px; padding: 0 5px; border-radius: 3px; flex: none;
  background: rgba(240,64,64,0.16); color: #f07070; }
.anima-lora-popup .alr-w { width: 52px; flex: none; font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);
  text-align: right; background: rgba(0,0,0,0.28); border: 1px solid var(--border-dim); border-radius: 5px; padding: 2px 5px;
  height: 22px; outline: none; }
.anima-lora-popup .alr-w:focus { border-color: var(--accent); color: var(--accent-glow); }
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
      else paintBadge();
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
    paintBadge();
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
        <input class="alr-w" data-lora-w="${i}" type="number" step="0.05" min="${STRENGTH_MIN}" max="${STRENGTH_MAX}"
               value="${fmtStrength(item.strength)}" aria-label="강도"${busy ? ' disabled' : ''}>
        <span class="alr-btns">
          <button type="button" data-lora-up="${i}" title="위로"${busy || i === 0 ? ' disabled' : ''}>▲</button>
          <button type="button" data-lora-down="${i}" title="아래로"${busy || i === view.length - 1 ? ' disabled' : ''}>▼</button>
          <button type="button" data-lora-rm="${i}" title="빼기"${busy ? ' disabled' : ''}>✕</button>
        </span></div>`;
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
    paintBadge();
    if (!popup) return;
    paintStatus(view);
    const chainEl = pick('.alr-chain');
    const libEl = pick('.alr-lib');
    if (chainEl) {
      const active = document.activeElement;
      const focusIndex = active && chainEl.contains(active) ? active.getAttribute('data-lora-w') : null;
      chainEl.innerHTML = isManaged() ? chainHtml(view) : '';
      if (focusIndex != null) chainEl.querySelector(`[data-lora-w="${focusIndex}"]`)?.focus();
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
    popup.addEventListener('click', onClick);
    popup.addEventListener('change', onChange);
    popup.addEventListener('input', onInput);
    popup.addEventListener('dragover', onDragOver);
    popup.addEventListener('dragleave', onDragLeave);
    popup.addEventListener('drop', onDrop);
    popup.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
    });
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
    const weight = event.target.closest('[data-lora-w]');
    if (weight) {
      const index = Number(weight.getAttribute('data-lora-w'));
      const value = Number(weight.value);
      if (!Number.isFinite(value) || value < STRENGTH_MIN || value > STRENGTH_MAX) {
        error = `강도는 ${STRENGTH_MIN} ~ ${STRENGTH_MAX} 사이로 적어 주세요.`;
        render();                  // 틀린 값은 저장하지 않고 원래 값으로 되돌린다(조용히 자르지 않는다)
        return;
      }
      if (Number(chain[index] && chain[index].strength) === value) return;
      save(chain.map((item, i) => (i === index ? { ...item, strength: value } : item)));
    }
  }

  function onInput(event) {
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
