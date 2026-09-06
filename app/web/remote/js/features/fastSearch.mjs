/* Fast Search — Ctrl+F 로 여는 한 칸 검색.
 *
 * 태그·아티스트·캐릭터·와일드카드·프리셋·이벤트를 한 자리에서 찾고,
 * 고른 것은 **클립보드로만** 간다(사용자 지시 2026-09-05).
 *
 * ⚠️ 이 창은 **프롬프트를 절대 건드리지 않는다.** 붙여넣기는 사용자가 한다.
 *    "메인 프롬프트가 덮이는 것"은 이 저장소에서 반복해서 지적받은 사항이라,
 *    삽입 경로를 아예 만들지 않는 것이 계약이다.
 *
 * 검색기는 서버가 갖고 있다(`/api/fast-search`). 여기서는 그리기·키·복사만 한다.
 */

const SOURCES = [
  { id: 'tag', label: '태그' },
  { id: 'artist', label: '아티스트' },
  { id: 'character', label: '캐릭터' },
  { id: 'wildcard', label: '와일드카드' },
  { id: 'preset', label: '프리셋' },
  { id: 'event', label: '이벤트' },
];
const DEBOUNCE_MS = 170;
const PER_SOURCE = 8;

export function initFastSearch() {
  let overlay = null, input = null, body = null, countEl = null, chipRow = null;
  let open = false, seq = 0, timer = null;
  let rows = [];            // 평면화된 결과 - 키보드 이동의 단위
  let active = -1;
  // Lightweight dictionaries are enabled together; other sources remain opt-in.
  let enabled = new Set(['tag', 'artist', 'character']);
  let groups = new Map(), pending = new Set();
  const requests = new Map(SOURCES.map(s => [s.id, {busy: false, wanted: null}]));

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  function toast(message, kind) {
    if (typeof window !== 'undefined' && typeof window.showToast === 'function') {
      window.showToast(message, kind || 'info');
    }
  }

  function build() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'fs-overlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="fs-bar">
        <span class="fs-icon" aria-hidden="true">⌕</span>
        <input class="fs-input" type="search" autocomplete="off" spellcheck="false"
               aria-label="빠른 검색"
               placeholder="태그 · 아티스트 · 캐릭터 · 와일드카드 · 프리셋 · 이벤트">
        <span class="fs-count" role="status" aria-live="polite"></span>
        <button type="button" class="fs-close" aria-label="닫기">×</button>
      </div>
      <div class="fs-chips"></div>
      <div class="fs-body"></div>
      <div class="fs-foot">↑↓ 이동 · <b>Enter</b> 복사 · Esc 닫기 — 프롬프트에는 넣지 않습니다</div>`;
    document.body.append(overlay);
    input = overlay.querySelector('.fs-input');
    body = overlay.querySelector('.fs-body');
    countEl = overlay.querySelector('.fs-count');
    chipRow = overlay.querySelector('.fs-chips');

    chipRow.innerHTML = SOURCES.map(s =>
      `<button type="button" class="fs-chip${enabled.has(s.id) ? ' is-on' : ''}" aria-pressed="${enabled.has(s.id)}" data-fs-source="${s.id}">${esc(s.label)}</button>`).join('');
    chipRow.addEventListener('click', event => {
      const chip = event.target.closest('[data-fs-source]');
      if (!chip) return;
      const id = chip.dataset.fsSource;
      // 마지막 하나까지 끄면 아무것도 못 찾는 창이 된다 - 최소 하나는 남긴다.
      if (enabled.has(id) && enabled.size === 1) return;
      if (enabled.has(id)) enabled.delete(id); else enabled.add(id);
      chip.classList.toggle('is-on', enabled.has(id));
      chip.setAttribute('aria-pressed', String(enabled.has(id)));
      schedule(0);
    });

    overlay.querySelector('.fs-close').addEventListener('click', close);
    input.addEventListener('input', () => schedule(DEBOUNCE_MS));
    input.addEventListener('keydown', onKeyDown);
    body.addEventListener('click', event => {
      const row = event.target.closest('[data-fs-index]');
      if (!row) return;
      active = Number(row.dataset.fsIndex);
      paintActive();
      commit();
    });
    // 바깥을 누르면 닫는다. 창 안의 클릭은 위에서 이미 처리했다.
    document.addEventListener('pointerdown', event => {
      if (!open || overlay.contains(event.target)) return;
      close();
    }, true);
    window.addEventListener('resize', position);
    return overlay;
  }

  /** 결과 칸(오른쪽) 위에 얹는다. 그 자리가 없으면 화면 가운데로 물러선다. */
  function position() {
    if (!overlay || overlay.hidden) return;
    const host = document.querySelector('#rightTabResult') || document.querySelector('.app-layout');
    const r = host ? host.getBoundingClientRect() : null;
    if (!r || r.width < 240 || r.height < 160) {
      overlay.style.left = '50%';
      overlay.style.transform = 'translateX(-50%)';
      overlay.style.top = '64px';
      overlay.style.width = 'min(680px, calc(100vw - 32px))';
      overlay.style.maxHeight = 'calc(100dvh - 96px)';
      return;
    }
    const pad = 14;
    overlay.style.transform = 'none';
    overlay.style.left = `${Math.round(r.left + pad)}px`;
    overlay.style.top = `${Math.round(r.top + pad)}px`;
    overlay.style.width = `${Math.round(Math.max(240, r.width - pad * 2))}px`;
    overlay.style.maxHeight = `${Math.round(Math.max(200, r.height - pad * 2))}px`;
  }

  function schedule(delay) {
    clearTimeout(timer);
    const mine = ++seq; // Invalidate before the debounce, including Enter/copy.
    for (const slot of requests.values()) slot.wanted = null;
    rows = [];
    active = -1;
    groups = new Map();
    const query = input.value.trim();
    pending = new Set([...enabled].filter(id => query || id === 'wildcard'));
    renderCurrent(query);
    timer = setTimeout(() => run(mine), delay);
  }

  function run(mine) {
    if (mine !== seq || !open) return;
    const query = input.value.trim();
    for (const source of SOURCES) {
      if (!pending.has(source.id)) continue;
      requests.get(source.id).wanted = {query, mine};
      void drain(source);
    }
  }

  async function drain(source) {
    const slot = requests.get(source.id);
    if (slot.busy) return;
    slot.busy = true;
    try {
      // One in-flight request and at most one latest pending query per source.
      // Aborting fetch does not stop Python's worker, so don't enqueue a new
      // cold initialization for every keystroke while the first one is running.
      while (slot.wanted) {
        const {query, mine} = slot.wanted;
        slot.wanted = null;
        const params = new URLSearchParams({q: query, sources: source.id, limit: String(PER_SOURCE)});
        let group;
        try {
          const response = await fetch(`/api/fast-search?${params}`, {cache: 'no-store'});
          if (!response.ok) throw new Error('search failed');
          const payload = await response.json();
          group = payload.groups?.find(g => g.source === source.id);
          if (!group || !Array.isArray(group.items)) throw new Error('invalid group');
        } catch {
          group = {source: source.id, label: source.label, items: [], note: '검색에 실패했습니다. 다시 입력해 주세요.'};
        }
        if (mine !== seq || !open || !enabled.has(source.id)) continue;
        groups.set(source.id, group);
        pending.delete(source.id);
        renderCurrent(query);
      }
    } finally {
      slot.busy = false;
    }
  }

  function renderCurrent(query) {
    const current = SOURCES.filter(s => enabled.has(s.id)).map(source =>
      groups.get(source.id) || {source: source.id, label: source.label, items: [],
        note: pending.has(source.id) ? '준비 및 검색 중…' : ''});
    render({groups: current}, query);
  }

  function render(payload, query) {
    const selectedKey = rows[active]?._searchKey;
    rows = [];
    body.setAttribute('aria-busy', String(pending.size > 0));
    if (!payload) {
      body.innerHTML = '<div class="fs-empty">검색에 실패했습니다.</div>';
      countEl.textContent = '';
      return;
    }
    const parts = [];
    for (const group of payload.groups || []) {
      if (!group.items.length && !group.note) continue;
      parts.push(`<div class="fs-cap">${esc(group.label)}`
        + (group.note ? `<span class="fs-note">${esc(group.note)}</span>` : '')
        + '</div>');
      for (const item of group.items) {
        const index = rows.length;
        rows.push({...item, _searchKey: `${group.source}\u0000${item.value}`});
        parts.push(`<button type="button" class="fs-row" data-fs-index="${index}">`
          + `<span class="fs-title">${esc(item.title)}</span>`
          + (item.subtitle ? `<span class="fs-sub">${esc(item.subtitle)}</span>` : '')
          + (item.meta ? `<span class="fs-meta">${esc(item.meta)}</span>` : '')
          + '</button>');
      }
    }
    if (!rows.length && !pending.size) {
      parts.push(`<div class="fs-empty">${query ? '찾은 것이 없습니다.' : '검색어를 입력하세요.'}</div>`);
    }
    body.innerHTML = parts.join('');
    countEl.textContent = pending.size ? `${rows.length} · 검색 중` : (rows.length ? `${rows.length}` : '');
    const previousIndex = selectedKey == null ? -1 : rows.findIndex(r => r._searchKey === selectedKey);
    active = previousIndex >= 0 ? previousIndex : (rows.length ? 0 : -1);
    paintActive();
  }

  function paintActive() {
    const nodes = body.querySelectorAll('[data-fs-index]');
    nodes.forEach(node => node.classList.toggle('is-active',
      Number(node.dataset.fsIndex) === active));
    const node = body.querySelector(`[data-fs-index="${active}"]`);
    if (node) node.scrollIntoView({ block: 'nearest' });
  }

  function move(step) {
    if (!rows.length) return;
    active = (active + step + rows.length) % rows.length;
    paintActive();
  }

  async function commit() {
    const item = rows[active];
    if (!item) return;
    const text = String(item.value || '');
    if (!text) return;
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch { ok = false; }
    if (!ok) {
      // 클립보드 권한이 막힌 판이 실제로 있다 - 조용히 실패하지 않는다.
      try {
        const scratch = document.createElement('textarea');
        scratch.value = text;
        scratch.setAttribute('readonly', '');
        scratch.style.cssText = 'position:fixed;top:-1000px;opacity:0';
        document.body.append(scratch);
        scratch.select();
        ok = document.execCommand('copy');
        scratch.remove();
      } catch { ok = false; }
    }
    toast(ok ? `복사했습니다 — ${text.slice(0, 40)}` : '복사가 막혔습니다. 직접 선택해 Ctrl+C 하세요.',
      ok ? 'success' : 'error');
  }

  function onKeyDown(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key === 'ArrowDown') { event.preventDefault(); move(1); return; }
    if (event.key === 'ArrowUp') { event.preventDefault(); move(-1); return; }
    if (event.key === 'Enter') { event.preventDefault(); void commit(); }
  }

  function show() {
    build();
    open = true;
    overlay.hidden = false;
    position();
    input.select();
    input.focus();
    schedule(0);
  }

  function close() {
    if (!overlay) return;
    open = false;
    overlay.hidden = true;
    clearTimeout(timer);
    for (const slot of requests.values()) slot.wanted = null;
    rows = [];
    active = -1;
    pending.clear();
    seq += 1;                 // 도는 중인 요청의 결과를 버린다
  }

  // Ctrl+F. 브라우저에서는 기본 찾기 막대를 대신 가져오고(preventDefault),
  // Electron 에는 기본 동작이 없어 그대로 우리 것이 된다.
  document.addEventListener('keydown', event => {
    const hit = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key || '').toLowerCase() === 'f';
    if (!hit) return;
    event.preventDefault();
    if (open) { input.select(); input.focus(); return; }
    show();
  }, true);

  return { show, close, isOpen: () => open };
}
