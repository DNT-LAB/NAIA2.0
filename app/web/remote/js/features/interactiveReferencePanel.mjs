/**
 * Interactive 전용 캐릭터 레퍼런스 패널.
 *
 * NAI 캐릭터 레퍼런스 모듈과 **상태가 독립**이다 — 백엔드는
 * `core/headless_interactive_reference_service.py`, 이유는 그 파일 첫머리에 있다.
 * 여기서는 그 상태를 보여주고 붙이고 뗀다. NAI 모듈의 DOM·전역을 하나도 쓰지 않는다.
 *
 * 붙일 수 있는 곳은 둘이다:
 *   보관함        기존 레퍼런스 이미지 저장소(NAI 모듈과 파일을 공유한다 — 원본이지
 *                 상태가 아니다)
 *   캐릭터 에셋    캐릭터 에셋 라이브러리. 프롬프트까지 가져올지 3선택으로 묻는다.
 */
const API = {
  state: '/api/interactive-reference/state',
  attach: '/api/interactive-reference/attach',
  param: '/api/interactive-reference/param',
  remove: '/api/interactive-reference/remove',
  clear: '/api/interactive-reference/clear',
  assetList: '/api/character-asset/list',
  assetDetail: id => '/api/character-asset/detail?id=' + encodeURIComponent(id),
  assetThumb: (id, rev) =>
    `/api/character-asset/thumb?id=${encodeURIComponent(id)}&size=grid&v=${rev || 0}`,
  storageList: '/api/character-asset/reference/storage',
};

export function createInteractiveReferencePanel({
  document,
  escHtml = v => String(v == null ? '' : v),
  showToast = () => {},
  fetchFn = globalThis.fetch,
  // 에셋 프롬프트를 슬롯으로 나눠 넣는다. Interactive 패널이 소유한 동작이다.
  getInteractivePanel = () => null,
  onChange = () => {},
} = {}) {
  let host = null;
  let open = false;
  let source = 'asset';          // 'asset' | 'storage'
  let frames = [];
  let items = [];
  let busy = false;
  let ask = null;                // {id, name}

  // ---------------------------------------------------------------- 데이터
  async function json(url, init) {
    const r = await fetchFn(url, init);
    const d = await r.json().catch(() => ({}));
    if (!r.ok || d.error) throw new Error(d.error || `HTTP ${r.status}`);
    return d;
  }

  async function refresh() {
    try {
      const d = await json(API.state, {cache: 'no-store'});
      frames = Array.isArray(d.frames) ? d.frames : [];
    } catch (err) {
      frames = [];
      showToast('레퍼런스 목록을 불러오지 못했습니다: ' + err.message, 'error');
    }
    render();
    onChange(frames.length);
  }

  async function loadSource() {
    items = [];
    render();
    try {
      if (source === 'asset') {
        const d = await json(API.assetList, {cache: 'no-store'});
        items = (d.characters || []).map(e => ({
          id: String(e.id || ''), name: String(e.display_name || e.id || ''),
          thumb: API.assetThumb(e.id, e.revision),
        }));
      } else {
        const d = await json(API.storageList, {cache: 'no-store'});
        items = (d.items || []).map(e => ({
          id: String(e.file_hash || ''),
          name: String(e.character_name || e.file_name || e.file_hash || ''),
          thumb: String(e.thumbnail_url || ''),
        }));
      }
    } catch (err) {
      showToast('목록을 불러오지 못했습니다: ' + err.message, 'error');
    }
    render();
  }

  // ---------------------------------------------------------------- 동작
  async function attach(id, name, kind) {
    if (busy) return;
    busy = true; render();
    try {
      const d = await json(API.attach, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source, ref: id, label: name}),
      });
      showToast(d.duplicate ? '이미 붙어 있습니다' : '레퍼런스로 붙였습니다',
                d.duplicate ? 'info' : 'success');
      await refresh();
      // 프롬프트까지 가져오는 것은 에셋에서만 의미가 있다(보관함은 그림뿐이다).
      if (source === 'asset' && kind && kind !== 'image') await pullPrompt(id, kind);
    } catch (err) {
      showToast('붙이지 못했습니다: ' + err.message, 'error');
    } finally {
      busy = false; render();
    }
  }

  async function pullPrompt(id, kind) {
    const panel = getInteractivePanel();
    if (!panel || typeof panel.applyAssetPrompt !== 'function') {
      showToast('Interactive 패널이 없어 프롬프트는 넣지 못했습니다', 'warning');
      return;
    }
    try {
      const d = await json(API.assetDetail(id), {cache: 'no-store'});
      const prompt = String(d.character_prompt || '');
      if (!prompt.trim()) { showToast('이 에셋에는 캐릭터 프롬프트가 없습니다', 'warning'); return; }
      panel.applyAssetPrompt(prompt, kind === 'char' ? 'char' : 'all');
    } catch (err) {
      showToast('프롬프트를 가져오지 못했습니다: ' + err.message, 'error');
    }
  }

  async function post(url, body, done) {
    try {
      await json(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                       body: JSON.stringify(body || {})});
      await refresh();
      if (done) showToast(done, 'success');
    } catch (err) {
      showToast('실패: ' + err.message, 'error');
    }
  }

  // ---------------------------------------------------------------- 그리기
  function ensureHost() {
    if (host && document.body.contains(host)) return host;
    host = document.createElement('div');
    host.className = 'ia-ref-panel';
    host.hidden = true;
    document.body.appendChild(host);
    host.addEventListener('click', onClick);
    host.addEventListener('input', onInput);
    return host;
  }

  function frameHtml(f) {
    const t = f.thumbnail
      ? `<img class="ia-ref-thumb" src="data:image/webp;base64,${escHtml(f.thumbnail)}" alt="">`
      : '<div class="ia-ref-thumb is-empty"></div>';
    return `<div class="ia-ref-frame">${t}` +
      `<div class="ia-ref-fmeta"><div class="ia-ref-fname">${escHtml(f.label || f.file_hash)}</div>` +
      `<label class="ia-ref-slider">강도<input type="range" min="0" max="1" step="0.05"` +
      ` value="${Number(f.strength ?? 1)}" data-ref-param="strength"` +
      ` data-ref-hash="${escHtml(f.file_hash)}"><span>${Number(f.strength ?? 1).toFixed(2)}</span></label>` +
      `<label class="ia-ref-slider">충실도<input type="range" min="0" max="1" step="0.05"` +
      ` value="${Number(f.fidelity ?? 0.8)}" data-ref-param="fidelity"` +
      ` data-ref-hash="${escHtml(f.file_hash)}"><span>${Number(f.fidelity ?? 0.8).toFixed(2)}</span></label>` +
      `</div><button type="button" class="ia-ref-del" data-ref-del="${escHtml(f.file_hash)}"` +
      ' title="제거" aria-label="제거">✕</button></div>';
  }

  function render() {
    if (!open) return;
    const el = ensureHost();
    const tab = (id, label) =>
      `<button type="button" class="ia-ref-tab${source === id ? ' is-on' : ''}"` +
      ` data-ref-src="${id}">${label}</button>`;
    const grid = items.length
      ? '<div class="ia-ref-grid">' + items.map(it =>
          `<div class="ia-ref-item" data-ref-pick="${escHtml(it.id)}"` +
          ` data-ref-name="${escHtml(it.name)}" title="${escHtml(it.name)}">` +
          `<img src="${escHtml(it.thumb)}" alt="" loading="lazy" decoding="async">` +
          `<span>${escHtml(it.name)}</span></div>`).join('') + '</div>'
      : '<div class="ia-ref-empty">비어 있습니다.</div>';
    el.innerHTML =
      '<div class="ia-ref-head"><b>캐릭터 레퍼런스</b>' +
      '<span class="ia-ref-note">Interactive 전용 — NAI 모듈과 별개입니다</span>' +
      '<button type="button" class="ia-ref-close" data-ref-close="1" aria-label="닫기">✕</button></div>' +
      (frames.length
        ? '<div class="ia-ref-frames">' + frames.map(frameHtml).join('') +
          `<button type="button" class="ia-ref-clear" data-ref-clear="1">전부 비우기</button></div>`
        : '<div class="ia-ref-empty">붙인 레퍼런스가 없습니다.</div>') +
      `<div class="ia-ref-tabs">${tab('asset', '캐릭터 에셋')}${tab('storage', '보관함')}</div>` +
      (busy ? '<div class="ia-ref-empty">처리 중…</div>' : grid) +
      (ask ? askHtml() : '');
  }

  function askHtml() {
    return '<div class="ia-ref-ask"><div class="ia-ref-askname">' + escHtml(ask.name) + '</div>' +
      '<div class="ia-ref-asksub">무엇까지 가져올까요</div>' +
      '<button type="button" class="ia-ref-askbtn" data-ref-kind="image">이미지만</button>' +
      '<button type="button" class="ia-ref-askbtn" data-ref-kind="char">이미지 + 캐릭터 특징</button>' +
      '<button type="button" class="ia-ref-askbtn is-all" data-ref-kind="all">이미지 + 캐릭터 + 의상</button>' +
      '<button type="button" class="ia-ref-askcancel" data-ref-kind="">취소</button></div>';
  }

  function onClick(ev) {
    const t = ev.target.closest('[data-ref-close],[data-ref-src],[data-ref-pick],[data-ref-del],' +
                                '[data-ref-clear],[data-ref-kind]');
    if (!t) return;
    ev.preventDefault();
    if (t.dataset.refClose != null) { close(); return; }
    if (t.dataset.refSrc) { source = t.dataset.refSrc; ask = null; void loadSource(); return; }
    if (t.dataset.refDel) { void post(API.remove, {file_hash: t.dataset.refDel}, '뺐습니다'); return; }
    if (t.dataset.refClear != null) { void post(API.clear, {}, '비웠습니다'); return; }
    if (t.dataset.refKind != null) {
      const kind = t.dataset.refKind;
      const cur = ask; ask = null; render();
      if (kind && cur) void attach(cur.id, cur.name, kind);
      return;
    }
    if (t.dataset.refPick) {
      // 보관함은 그림뿐이라 물을 것이 없다 — 에셋일 때만 3선택을 낸다.
      if (source !== 'asset') { void attach(t.dataset.refPick, t.dataset.refName || '', 'image'); return; }
      ask = {id: t.dataset.refPick, name: t.dataset.refName || ''};
      render();
    }
  }

  function onInput(ev) {
    const el = ev.target.closest('[data-ref-param]');
    if (!el) return;
    const span = el.parentElement.querySelector('span');
    if (span) span.textContent = Number(el.value).toFixed(2);
    void post(API.param, {file_hash: el.dataset.refHash, key: el.dataset.refParam,
                          value: Number(el.value)});
  }

  function onKey(ev) { if (ev.key === 'Escape' && open) { ev.stopPropagation(); close(); } }

  function toggle() { open ? close() : void openPanel(); }

  async function openPanel() {
    open = true;
    ensureHost().hidden = false;
    document.addEventListener('keydown', onKey, true);
    render();
    await refresh();
    await loadSource();
  }

  function close() {
    open = false;
    ask = null;
    if (host) { host.hidden = true; host.innerHTML = ''; }
    document.removeEventListener('keydown', onKey, true);
  }

  return {
    open: openPanel,
    close,
    toggle,
    isOpen: () => open,
    refresh,
    count: () => frames.length,
  };
}
