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
 *
 * 크기 규약(사용자 지적 2026-09-07): Spotlight 처럼 **작게**. 결과 칸 폭의 가운데에
 * 최대 720px, 높이는 내용을 따라 자라되 결과 칸의 **절반**을 넘지 않는다 — 결과
 * 이미지를 통째로 가리면 안 된다. 나머지는 안에서 스크롤한다.
 *
 * 이벤트는 "더 보기" 버튼 없이 **스크롤로 이어서** 본다: 3–8태그 조합을 다 보이면
 * 9–16태그 조합으로 넘어가고, 끝나면 끝이라고 말한다. 이벤트 안에서 다시 좁히는
 * 칸(AND)이 따로 있다.
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
const EVENT_PAGE = 8;
const EVENT_PHASES = ['basic', 'deep'];   // 3–8태그 -> 9–16태그 -> 끝
const PERSON_OPTIONS = ['1girl_solo', '1girl', '1girl_1boy', '1girl_multiple_boys',
  '2girls', 'multiple_girls', '1boy_solo', '1boy', '1boy_multiple_girls',
  '2boys', 'multiple_boys', 'multiple_girls_multiple_boys', 'other'];

export function initFastSearch() {
  let overlay = null, input = null, body = null, countEl = null, chipRow = null;
  let open = false, seq = 0, timer = null, eventTimer = null;
  let rows = [];            // 평면화된 결과 - 키보드 이동의 단위
  let active = -1;
  // 가벼운 사전들만 기본으로 켠다. 나머지는 사용자가 칩으로 켠다(지연 로딩).
  let enabled = new Set(['tag', 'artist', 'character']);
  let groups = new Map(), pending = new Set();
  let eventOptions = null, eventRating = '', eventPerson = '', eventRefine = '';
  // 이벤트 페이징 상태. phase 는 EVENT_PHASES 의 인덱스, offset 은 그 phase 안의 위치.
  let eventPaging = freshEventPaging();
  const requests = new Map(SOURCES.map(s => [s.id, {busy: false, wanted: null}]));

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  function freshEventPaging() {
    return {phase: 0, offset: 0, done: false, items: [], deepStart: -1};
  }

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
      <div class="fs-event-options" hidden>
        <label>인원 <select data-fs-person aria-label="이벤트 인원"><option value="">전체 인원</option>${PERSON_OPTIONS.map(id => `<option value="${id}">${id.replaceAll('_', ' ')}</option>`).join('')}</select></label>
        <label>등급 <select data-fs-rating aria-label="이벤트 등급"><option value="">전체 등급</option><option value="g">G · General</option><option value="s">S · Sensitive</option><option value="q">Q · Questionable</option><option value="e">E · Explicit</option></select></label>
        <input class="fs-event-refine" type="search" autocomplete="off" spellcheck="false"
               data-fs-event-refine aria-label="이벤트 안에서 찾기"
               placeholder="이벤트 안에서 찾기 (쉼표 = AND)">
      </div>
      <div class="fs-body"></div>
      <div class="fs-foot">↑↓ 이동 · <b>Enter</b> 복사 · Esc 닫기 — 프롬프트에는 넣지 않습니다</div>`;
    document.body.append(overlay);
    input = overlay.querySelector('.fs-input');
    body = overlay.querySelector('.fs-body');
    countEl = overlay.querySelector('.fs-count');
    chipRow = overlay.querySelector('.fs-chips');
    eventOptions = overlay.querySelector('.fs-event-options');
    eventOptions.addEventListener('change', event => {
      if (event.target.matches('[data-fs-event-refine]')) return;
      eventRating = eventOptions.querySelector('[data-fs-rating]').value;
      eventPerson = eventOptions.querySelector('[data-fs-person]').value;
      scheduleEvents(0);
    });
    const refine = eventOptions.querySelector('[data-fs-event-refine]');
    refine.addEventListener('input', () => {
      eventRefine = refine.value.trim();
      scheduleEvents(DEBOUNCE_MS);
    });
    refine.addEventListener('keydown', onKeyDown);

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
    // 이벤트는 버튼 없이 스크롤로 이어 본다 - 바닥에 가까워지면 다음 쪽을 부른다.
    body.addEventListener('scroll', maybeLoadMoreEvents, {passive: true});
    // 바깥을 누르면 닫는다. 창 안의 클릭은 위에서 이미 처리했다.
    document.addEventListener('pointerdown', event => {
      if (!open || overlay.contains(event.target)) return;
      close();
    }, true);
    window.addEventListener('resize', position);
    return overlay;
  }

  /** Spotlight 크기. 결과 칸 가운데, 폭 ≤ 720, 높이 ≤ 결과 칸의 절반. */
  function position() {
    if (!overlay || overlay.hidden) return;
    const host = document.querySelector('#rightTabResult') || document.querySelector('.app-layout');
    const r = host ? host.getBoundingClientRect() : null;
    if (!r || r.width < 240 || r.height < 160) {
      overlay.style.left = '50%';
      overlay.style.transform = 'translateX(-50%)';
      overlay.style.top = '64px';
      overlay.style.width = 'min(680px, calc(100vw - 32px))';
      overlay.style.maxHeight = 'min(420px, calc(100dvh - 96px))';
      return;
    }
    const pad = 14;
    const width = Math.round(Math.min(720, Math.max(240, r.width - pad * 2)));
    // 이미지를 통째로 가리지 않는다: 결과 칸 높이의 절반이 상한. 너무 작아지면
    // 목록이 못 쓰게 되니 260px 은 보장한다(그래도 칸보다 크진 않게).
    const maxH = Math.round(Math.min(r.height - pad * 2, Math.max(260, r.height * 0.5)));
    overlay.style.transform = 'none';
    overlay.style.left = `${Math.round(r.left + (r.width - width) / 2)}px`;
    overlay.style.top = `${Math.round(r.top + pad)}px`;
    overlay.style.width = `${width}px`;
    overlay.style.maxHeight = `${maxH}px`;
  }

  function schedule(delay) {
    clearTimeout(timer);
    clearTimeout(eventTimer);
    const mine = ++seq; // 디바운스 전에 무효화한다 - Enter/복사도 포함.
    for (const slot of requests.values()) slot.wanted = null;
    rows = [];
    active = -1;
    groups = new Map();
    eventPaging = freshEventPaging();
    eventOptions.hidden = !enabled.has('event');
    const query = input.value.trim();
    pending = new Set([...enabled].filter(id => query || id === 'wildcard'));
    renderCurrent(query);
    timer = setTimeout(() => run(mine), delay);
  }

  /** 이벤트 조건(인원·등급·안에서 찾기)만 바뀌었을 때 - 다른 갈래는 그대로 둔다. */
  function scheduleEvents(delay) {
    clearTimeout(eventTimer);
    if (!enabled.has('event')) return;
    const mine = seq;
    const slot = requests.get('event');
    slot.wanted = null;
    groups.delete('event');
    eventPaging = freshEventPaging();
    const query = input.value.trim();
    if (query) pending.add('event');
    renderCurrent(query);
    eventTimer = setTimeout(() => {
      if (mine !== seq || !open || !query) return;
      requestEventPage(mine);
    }, delay);
  }

  function run(mine) {
    if (mine !== seq || !open) return;
    const query = input.value.trim();
    for (const source of SOURCES) {
      if (!pending.has(source.id)) continue;
      if (source.id === 'event') { requestEventPage(mine); continue; }
      requests.get(source.id).wanted = {query, mine};
      void drain(source);
    }
  }

  function requestEventPage(mine) {
    if (eventPaging.done) return;
    const query = input.value.trim();
    if (!query) return;
    const slot = requests.get('event');
    slot.wanted = {
      query, mine, rating: eventRating, person: eventPerson, refine: eventRefine,
      detail: EVENT_PHASES[eventPaging.phase], offset: eventPaging.offset,
    };
    void drain(SOURCES.find(s => s.id === 'event'));
  }

  function maybeLoadMoreEvents() {
    if (!open || !enabled.has('event') || eventPaging.done) return;
    if (requests.get('event').busy || requests.get('event').wanted) return;
    if (!groups.has('event')) return;                   // 첫 쪽이 아직 안 왔다
    const nearBottom = body.scrollTop + body.clientHeight >= body.scrollHeight - 120;
    const cannotScroll = body.scrollHeight <= body.clientHeight + 4;
    if (nearBottom || cannotScroll) requestEventPage(seq);
  }

  async function drain(source) {
    const slot = requests.get(source.id);
    if (slot.busy) return;
    slot.busy = true;
    try {
      // 갈래마다 진행 요청 하나·최신 대기 하나만 둔다. fetch 를 끊어도 파이썬 쪽
      // 작업은 안 멈추니, 글자마다 새 초기화를 줄 세우지 않는다.
      while (slot.wanted) {
        const request = slot.wanted;
        const {query, mine} = request;
        slot.wanted = null;
        const isEvent = source.id === 'event';
        const params = new URLSearchParams({q: query, sources: source.id, limit: String(isEvent ? EVENT_PAGE : PER_SOURCE)});
        if (isEvent) {
          // 이벤트 안에서 찾기 = 서버의 쉼표 AND 조건에 그대로 붙인다.
          params.set('q', request.refine ? `${query}, ${request.refine}` : query);
          params.set('rating', request.rating);
          params.set('person', request.person);
          params.set('event_detail', request.detail);
          params.set('event_offset', String(request.offset));
        }
        let group;
        try {
          const response = await fetch(`/api/fast-search?${params}`, {cache: 'no-store'});
          if (!response.ok) throw new Error('search failed');
          const payload = await response.json();
          group = payload.groups?.find(g => g.source === source.id);
          if (!group || !Array.isArray(group.items)) throw new Error('invalid group');
        } catch {
          group = {source: source.id, label: source.label, items: [], note: '검색에 실패했습니다. 다시 입력해 주세요.', exhausted: true};
        }
        if (mine !== seq || !open || !enabled.has(source.id)) continue;
        if (isEvent) {
          // 같은 phase/offset 이 아니면 낡은 쪽이다 - 조건이 바뀐 뒤에 온 답.
          if (request.detail !== EVENT_PHASES[eventPaging.phase] || request.offset !== eventPaging.offset
              || request.refine !== eventRefine || request.rating !== eventRating || request.person !== eventPerson) continue;
          if (eventPaging.phase === 1 && eventPaging.deepStart < 0 && group.items.length) {
            eventPaging.deepStart = eventPaging.items.length;
          }
          eventPaging.items.push(...group.items);
          eventPaging.offset += group.items.length;
          const exhausted = group.exhausted === true || group.items.length < EVENT_PAGE;
          if (exhausted) {
            if (eventPaging.phase + 1 < EVENT_PHASES.length) { eventPaging.phase += 1; eventPaging.offset = 0; }
            else eventPaging.done = true;
          }
          groups.set('event', {source: 'event', label: source.label, items: eventPaging.items, note: group.note || ''});
          pending.delete('event');
          renderCurrent(query);
          // 한 쪽으로 화면이 안 차면 스크롤이 생길 때까지 이어서 부른다.
          if (!eventPaging.done && body.scrollHeight <= body.clientHeight + 4) requestEventPage(mine);
          continue;
        }
        groups.set(source.id, group);
        pending.delete(source.id);
        renderCurrent(query);
      }
    } finally {
      slot.busy = false;
    }
  }

  function renderCurrent(query) {
    const visible = SOURCES.filter(s => enabled.has(s.id));
    const current = visible.map(source =>
      groups.get(source.id) || {source: source.id, label: source.label, items: [],
        note: pending.has(source.id) ? '준비 및 검색 중…' : ''});
    render({groups: current}, query);
  }

  function render(payload, query) {
    const selectedKey = rows[active]?._searchKey;
    const keepScroll = body.scrollTop;
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
      const isEvent = group.source === 'event';
      parts.push(`<div class="fs-cap">${esc(group.label)}`
        + (group.note ? `<span class="fs-note">${esc(group.note)}</span>` : '')
        + '</div>');
      group.items.forEach((item, i) => {
        if (isEvent && i === eventPaging.deepStart) {
          parts.push('<div class="fs-cap fs-cap-sub">9–16태그 조합</div>');
        }
        const index = rows.length;
        const deep = isEvent && eventPaging.deepStart >= 0 && i >= eventPaging.deepStart;
        const subtitle = deep ? item.value : item.subtitle;
        rows.push({...item, _searchKey: `${group.source} ${item.value}`});
        parts.push(`<button type="button" class="fs-row${deep ? ' fs-row-deep' : ''}" data-fs-index="${index}">`
          + `<span class="fs-title">${esc(item.title)}</span>`
          + (subtitle ? `<span class="fs-sub">${esc(subtitle)}</span>` : '')
          + (item.meta ? `<span class="fs-meta">${esc(item.meta)}</span>` : '')
          + '</button>');
      });
      if (isEvent && group.items.length) {
        parts.push(`<div class="fs-end">${eventPaging.done ? '이벤트 끝' : '아래로 내리면 더 불러옵니다…'}</div>`);
      } else if (!group.items.length && !pending.has(group.source) && query) {
        // 갈래 머리만 남고 아래가 비면 "안 왔나?" 로 읽힌다 - 없다고 말한다.
        parts.push(`<div class="fs-end">${isEvent ? '조건에 맞는 조합이 없습니다' : '찾은 것이 없습니다'}</div>`);
      }
    }
    if (!rows.length && !pending.size) {
      parts.push(`<div class="fs-empty">${query ? '찾은 것이 없습니다.' : '검색어를 입력하세요.'}</div>`);
    }
    body.innerHTML = parts.join('');
    body.scrollTop = keepScroll;          // 이어 붙인 뒤 위로 튀지 않게
    countEl.textContent = pending.size ? `${rows.length} · 검색 중` : (rows.length ? `${rows.length}` : '');
    const previousIndex = selectedKey == null ? -1 : rows.findIndex(r => r._searchKey === selectedKey);
    active = previousIndex >= 0 ? previousIndex : (rows.length ? 0 : -1);
    paintActive(previousIndex >= 0);
  }

  function paintActive(keepView = false) {
    const nodes = body.querySelectorAll('[data-fs-index]');
    nodes.forEach(node => node.classList.toggle('is-active',
      Number(node.dataset.fsIndex) === active));
    if (keepView) return;                 // 이어 붙이기일 땐 스크롤을 건드리지 않는다
    const node = body.querySelector(`[data-fs-index="${active}"]`);
    if (node) node.scrollIntoView({ block: 'nearest' });
  }

  function move(step) {
    if (!rows.length) return;
    active = (active + step + rows.length) % rows.length;
    paintActive();
    maybeLoadMoreEvents();
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
    overlay.hidden = true;                // CSS 의 .fs-overlay[hidden] 이 실제로 감춘다
    clearTimeout(timer);
    clearTimeout(eventTimer);
    for (const slot of requests.values()) slot.wanted = null;
    rows = [];
    active = -1;
    pending.clear();
    seq += 1;                 // 도는 중인 요청의 결과를 버린다
  }

  // Ctrl+F. 브라우저에서는 기본 찾기 막대를 대신 가져오고(preventDefault),
  // Electron 에는 기본 동작이 없어 그대로 우리 것이 된다.
  // Esc 는 창 안 어디에 포커스가 있든 닫는다 - 행을 누른 뒤에도.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && open) { event.preventDefault(); close(); return; }
    const hit = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key || '').toLowerCase() === 'f';
    if (!hit) return;
    event.preventDefault();
    if (open) { input.select(); input.focus(); return; }
    show();
  }, true);

  return { show, close, isOpen: () => open };
}
