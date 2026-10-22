/**
 * Characters 창 - 오른쪽 탭 [Characters] 를 누르면 뜨는 떠 있는 창(사용자 결정 2026-10-22 · Artist 탭처럼).
 *
 *   [ 검색(이름 · 한글 · 초성 · work:) | ALL 여 남 외 | ★ | + 필터 ]
 *   [ 특징 칩 +포함 / −제외 / work: ]
 *   [ 그룹(전부 · 보이는 만큼만) |  썸네일 격자(전부 · 보이는 만큼만 · 창 폭에 맞춘 칸 수) ]
 *   [ 고른 캐릭터 줄: 이름 · 작품 · 게시물 · 프롬프트 줄 · [+ 슬롯] [+ 풀] [생성] [★] [복사] [숨김] [⋯] ]
 *
 * 탭 규칙(Artist 와 같다): 창이 없거나 접혀 있으면 창부터 세우고 탭으로 가지 않는다. 창이 펴져 있을 때 다시 누르면 탭으로.
 * Find(퀵 패널)와는 **따로**다(사용자 결정) - 다만 같은 인프라를 쓴다: 같은 검색 라우트(`/list` · 검색 색인) · 같은 특징 자동완성 ·
 * 슬롯 담기 · 풀 · 생성은 퀵 패널의 손잡이(`getActions()`) · 생성 옵션은 Find ⚙ 와 같은 생성 설정 창.
 *
 * 격자는 `/list?...&offset=&limit=` 로 **보이는 덩어리만** 받는다(서버 결과 캐시에서 자른다 - 검색 색인 f1706ad3).
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

const BLOCK = 60;                       // 한 번에 받는 칸 수
const CELL_MIN = 104;                   // 칸 최소 폭(px) - 창 폭에 맞춰 칸 수가 바뀐다
const CELL_GAP = 7;
const NAME_H = 34;                      // 칸 아래 이름 두 줄
const GROUP_ROW = 24;
const GENDER_KEY = 'naia_chw_gender';
const GENDERS = [['all', 'ALL', '전체'], ['girl', '여', '여성'], ['boy', '남', '남성'], ['other', '외', '비인간']];

export function createCharacterWindow({
  document: doc = document,
  window: win = window,
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  getActions = () => ({}),            // 퀵 패널 손잡이: addToSlot · poolAdd · generateThumb · openGenSettings · openPoolWindow · poolCount
  openCharacterPage = () => {},       // [⋯] Characters 탭에서 열기(옛 화면 - 연속 생성 등)
} = {}) {
  let panel = null;
  const escAttr = value => escHtml(String(value ?? '')).replace(/"/g, '&quot;');
  const readGender = () => { try { return storage?.getItem(GENDER_KEY) || 'girl'; } catch (_) { return 'girl'; } };

  // 검색 상태 - 바뀌면 결과(덩어리 캐시)를 처음부터.
  const state = {query: '', group: '__ALL__', gender: readGender(), fav: false, inc: [], exc: []};
  let total = 0;
  let genderCounts = null;
  let seq = 0;                          // 조건이 바뀔 때마다 올린다 - 옛 응답은 버린다
  let blocks = new Map();               // 덩어리 번호 -> items | 'loading'
  let stale = new Map();                // 바깥 갱신(softRefresh) 동안 보여 줄 옛 덩어리 - 새 것이 오면 그 덩어리만 바뀐다
  let aborts = new Map();
  let queryTimer = 0;
  let selected = null;                  // {group, character, count, favorite}
  let selectedLine = '';
  let busy = '';
  let groups = [];                      // [{key, name, count}]
  let groupQuery = '';
  let feat = {open: false, line: 'inc', text: '', rows: [], seq: 0, timer: 0};
  let failedSeq = -1;                   // 이 조건(seq)에서 이미 실패를 알렸다 - 토스트는 한 번만

  // ── 틀 ────────────────────────────────────────────────────────────────────
  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win,
      title: 'Characters',
      variant: 'chw',
      storageKey: 'character-window',
      width: 720, height: 640, minWidth: 480, minHeight: 360, maxWidth: 1600,
      resizable: true, collapsible: true,
      initial: {right: 24, y: 80},
      escHtml,
      onResize: () => layoutGrid(),
    });
    panel.slot.innerHTML = `<button type="button" class="chw-hb" data-chw-gset title="[생성] 이 붙이는 Prefix · Postfix · 옵션(Find ⚙ 와 같은 창)">생성 설정</button>`
      + `<button type="button" class="chw-hb" data-chw-pool title="세션 와일드카드(랜덤 풀) 창">풀</button>`;
    panel.slot.addEventListener('click', onSlotClick);
    panel.body.innerHTML = `<div class="chw">`
      + `<div class="chw-tools"><input class="chw-q" type="search" data-chw-q spellcheck="false" autocomplete="off"`
      + ` placeholder="이름 · 한글 · 초성 · work:작품">`
      + `<span class="chw-seg" data-chw-seg></span>`
      + `<button type="button" class="chw-tb" data-chw-fav title="즐겨찾기만">★</button>`
      + `<button type="button" class="chw-tb" data-chw-featbtn title="색 · 특징 · 작품으로 거르기(Find [필터] 와 같은 낱말)">+ 필터</button></div>`
      + `<div class="chw-feat" data-chw-feat hidden></div>`
      + `<div class="chw-chips" data-chw-chips hidden></div>`
      + `<div class="chw-main"><div class="chw-groups"><input class="chw-gq" type="search" data-chw-gq placeholder="그룹 검색" spellcheck="false">`
      + `<div class="chw-glist" data-chw-glist><div class="chw-gspacer" data-chw-gspacer></div></div></div>`
      + `<div class="chw-grid" data-chw-grid tabindex="0"><div class="chw-count" data-chw-count></div><div class="chw-spacer" data-chw-spacer></div></div></div>`
      + `<div class="chw-sel" data-chw-sel></div></div>`;
    const body = panel.body;
    body.addEventListener('click', onClick);
    body.addEventListener('input', onInput);
    body.addEventListener('keydown', onKey);
    body.querySelector('[data-chw-grid]').addEventListener('scroll', () => paintGrid(), {passive: true});
    body.querySelector('[data-chw-glist]').addEventListener('scroll', () => paintGroups(), {passive: true});
    if (typeof ResizeObserver === 'function') new ResizeObserver(() => layoutGrid()).observe(body.querySelector('[data-chw-grid]'));
    return panel;
  }

  const el = sel => panel?.body.querySelector(sel);

  // ── 서버 ──────────────────────────────────────────────────────────────────
  function listParams() {
    const p = new URLSearchParams();
    if (state.group && state.group !== '__ALL__') p.set('group', state.group);
    if (state.query.trim()) p.set('query', state.query.trim());
    if (state.fav) p.set('favorites_only', 'true');
    if (state.gender !== 'all') p.append('gender', state.gender);
    const enc = term => (term.kind === 'work' ? `work:${term.tag}` : term.tag);    // Find 와 같은 꼴
    state.inc.forEach(term => p.append('inc', enc(term)));
    state.exc.forEach(term => p.append('exc', enc(term)));
    return p;
  }

  function resetResults() {
    seq += 1;
    aborts.forEach(ctrl => { try { ctrl.abort(); } catch (_) {} });
    aborts = new Map();
    blocks = new Map();
    stale = new Map();
    total = 0;
    const grid = el('[data-chw-grid]');
    if (grid) grid.scrollTop = 0;
    void loadBlock(0);
  }

  async function loadBlock(index) {
    if (blocks.has(index)) return;
    const mine = seq;
    const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    blocks.set(index, 'loading');
    if (ctrl) aborts.set(index, ctrl);
    try {
      const p = listParams();
      p.set('offset', String(index * BLOCK));
      p.set('limit', String(BLOCK));
      const res = await fetch(`/api/character-viewer/list?${p}`, {cache: 'no-store', signal: ctrl?.signal});
      if (mine !== seq) return;                     // 조건이 바뀌었다 - 본문도 읽지 않는다
      const data = await res.json().catch(() => ({}));
      if (mine !== seq) return;
      if (!res.ok) throw new Error(data.error || '목록을 불러오지 못했습니다.');
      total = Number(data.total) || 0;
      genderCounts = data.gender_counts || genderCounts;
      const items = Array.isArray(data.items) ? data.items : [];
      blocks.set(index, items);
      stale.delete(index);
      // 3. 고른 캐릭터의 ★ 를 서버 값으로 맞춘다(Find 에서 바꿨을 수 있다 - 낡은 값의 반대를 보내면 토글이 헛돈다).
      const hit = selected && items.find(it => it.group === selected.group && it.character === selected.character);
      if (hit && !!hit.favorite !== !!selected.favorite) { selected.favorite = !!hit.favorite; paintSel(); }
    } catch (error) {
      if (mine !== seq || error?.name === 'AbortError') return;
      // 'error' 로 남긴다 - 지우면 그리기가 그 덩어리를 곧바로 다시 청해 실패가 끝없이 돈다. 조건을 바꾸거나 창을 다시 열면 새로 받는다.
      blocks.set(index, 'error');
      if (failedSeq !== seq) { failedSeq = seq; showToast(error.message || String(error), 'error'); }
    } finally {
      aborts.delete(index);
    }
    if (mine === seq) { paintTools(); layoutGrid(); }
  }

  async function loadGroups() {
    try {
      const res = await fetch('/api/character-viewer/groups?offset=0&limit=5000', {cache: 'no-store'});
      const data = await res.json().catch(() => ({}));
      if (res.ok) groups = Array.isArray(data.items) ? data.items : [];
    } catch (_) { /* 다음에 다시 */ }
    paintGroups();
  }

  // ── 격자(보이는 만큼만) ─────────────────────────────────────────────────────
  let geo = {cols: 1, cellW: CELL_MIN, rowH: CELL_MIN + NAME_H + CELL_GAP};

  function layoutGrid() {
    const grid = el('[data-chw-grid]');
    if (!grid) return;
    const width = grid.clientWidth - 16;
    const cols = Math.max(1, Math.floor((width + CELL_GAP) / (CELL_MIN + CELL_GAP)));
    const cellW = Math.floor((width - CELL_GAP * (cols - 1)) / cols);
    geo = {cols, cellW, rowH: cellW + NAME_H + CELL_GAP};
    el('[data-chw-spacer]').style.height = `${Math.ceil(total / cols) * geo.rowH + 8}px`;
    paintGrid();
  }

  function itemAt(i) {
    const b = Math.floor(i / BLOCK);
    const block = Array.isArray(blocks.get(b)) ? blocks.get(b) : stale.get(b);
    return Array.isArray(block) ? block[i % BLOCK] || null : null;
  }

  function cellHtml(item, i) {
    const x = (i % geo.cols) * (geo.cellW + CELL_GAP) + 8;
    const y = Math.floor(i / geo.cols) * geo.rowH + 8;
    const style = `transform:translate(${x}px,${y}px);width:${geo.cellW}px`;
    if (!item) return `<div class="chw-cell is-loading" style="${style}"><div class="chw-im" style="height:${geo.cellW}px"></div></div>`;
    const on = selected && selected.group === item.group && selected.character === item.character;
    const img = item.thumbnail_url
      ? `<img loading="lazy" decoding="async" alt="" src="${escAttr(item.thumbnail_url)}">`
      : `<span class="chw-ini">${escHtml(String(item.character || '?').charAt(0).toUpperCase())}</span>`;
    return `<button type="button" class="chw-cell${on ? ' is-on' : ''}" style="${style}" data-chw-i="${i}"`
      + ` title="${escAttr(`${item.character} · ${item.group}`)}">`
      + `<div class="chw-im" style="height:${geo.cellW}px">${img}${item.favorite ? '<span class="chw-star">★</span>' : ''}</div>`
      + `<div class="chw-nm">${escHtml(item.character)}</div>`
      + `<div class="chw-mt">${escHtml(item.group)} · ${Number(item.count || 0).toLocaleString()}</div></button>`;
  }

  function paintGrid() {
    const grid = el('[data-chw-grid]');
    if (!grid) return;
    const first = Math.max(0, Math.floor(grid.scrollTop / geo.rowH) - 1) * geo.cols;
    const last = Math.min(total, Math.ceil((grid.scrollTop + grid.clientHeight) / geo.rowH + 1) * geo.cols);
    for (let b = Math.floor(first / BLOCK); b <= Math.floor(Math.max(first, last - 1) / BLOCK); b += 1) {
      if (b * BLOCK < Math.max(total, 1)) void loadBlock(b);
    }
    let html = '';
    for (let i = first; i < last; i += 1) html += cellHtml(itemAt(i), i);
    const spacer = el('[data-chw-spacer]');
    if (spacer._html !== html) {
      const focused = doc.activeElement && spacer.contains(doc.activeElement) ? doc.activeElement.dataset.chwI : null;
      spacer._html = html;
      spacer.innerHTML = html;
      if (focused != null) spacer.querySelector(`[data-chw-i="${focused}"]`)?.focus();
    }
    const count = el('[data-chw-count]');
    const label = blocks.get(0) === 'error' && !total ? '불러오지 못했습니다 - 검색을 바꾸거나 창을 다시 여세요'
      : blocks.get(0) === 'loading' && !total ? '불러오는 중…' : total ? `${total.toLocaleString()}명` : '맞는 캐릭터가 없습니다';
    if (count.textContent !== label) count.textContent = label;
  }

  // ── 그룹(보이는 만큼만) ─────────────────────────────────────────────────────
  function shownGroups() {
    const q = groupQuery.trim().toLowerCase();
    return q ? groups.filter(g => g.key === '__ALL__' || String(g.name).toLowerCase().includes(q)) : groups;
  }

  function paintGroups() {
    const list = el('[data-chw-glist]');
    if (!list) return;
    const rows = shownGroups();
    const spacer = el('[data-chw-gspacer]');
    spacer.style.height = `${rows.length * GROUP_ROW}px`;
    const first = Math.max(0, Math.floor(list.scrollTop / GROUP_ROW) - 4);
    const last = Math.min(rows.length, Math.ceil((list.scrollTop + list.clientHeight) / GROUP_ROW) + 4);
    let html = '';
    for (let i = first; i < last; i += 1) {
      const g = rows[i];
      html += `<button type="button" class="chw-gi${g.key === state.group ? ' is-on' : ''}" style="transform:translateY(${i * GROUP_ROW}px)"`
        + ` data-chw-g="${escAttr(g.key)}" title="${escAttr(g.name)}"><span>${escHtml(g.name)}</span>`
        + `<i>${Number(g.count || 0).toLocaleString()}</i></button>`;
    }
    if (spacer._html !== html) { spacer._html = html; spacer.innerHTML = html; }
  }

  // ── 도구 줄 · 칩 · 특징 판 ──────────────────────────────────────────────────
  function paintTools() {
    const seg = el('[data-chw-seg]');
    if (!seg) return;
    const html = GENDERS.map(([key, label, tip]) => {
      const n = genderCounts && key !== 'all' ? Number(genderCounts[key] || 0) : null;
      return `<button type="button" class="${key === state.gender ? 'is-on' : ''}" data-chw-gender="${key}"`
        + ` title="${tip}${n != null ? ` ${n.toLocaleString()}명` : ''}">${label}</button>`;
    }).join('');
    if (seg._html !== html) { seg._html = html; seg.innerHTML = html; }
    el('[data-chw-fav]').classList.toggle('is-on', state.fav);
    const n = state.inc.length + state.exc.length;
    const featBtn = el('[data-chw-featbtn]');
    featBtn.textContent = n ? `필터 ${n}` : '+ 필터';
    featBtn.classList.toggle('is-on', feat.open || !!n);
    const chips = el('[data-chw-chips]');
    const chipHtml = [...state.inc.map(t => ['inc', t]), ...state.exc.map(t => ['exc', t])].map(([line, t]) =>
      `<button type="button" class="chw-chip is-${t.kind === 'work' ? 'work' : line}" data-chw-unchip="${line}"`
      + ` data-chw-tag="${escAttr(t.tag)}" data-chw-kind="${escAttr(t.kind)}" title="빼기">`
      + `${line === 'exc' ? '− ' : t.kind === 'work' ? 'work: ' : '+ '}${escHtml(t.tag)} ✕</button>`).join('');
    chips.hidden = !chipHtml;
    if (chips._html !== chipHtml) { chips._html = chipHtml; chips.innerHTML = chipHtml; }
  }

  function paintFeat() {
    const box = el('[data-chw-feat]');
    if (!box) return;
    box.hidden = !feat.open;
    if (!feat.open) return;
    if (!box.querySelector('[data-chw-ft]')) {
      box.innerHTML = `<div class="chw-feat-row"><span class="chw-fseg">`
        + `<button type="button" data-chw-fline="inc">포함</button><button type="button" data-chw-fline="exc">제외</button></span>`
        + `<input class="chw-ft" data-chw-ft type="search" placeholder="색 · 특징 · 가슴 · 작품 (예: pink hair)" spellcheck="false" autocomplete="off"></div>`
        + `<div class="chw-fsug" data-chw-fsug></div>`;
    }
    box.querySelectorAll('[data-chw-fline]').forEach(b => b.classList.toggle('is-on', b.dataset.chwFline === feat.line));
    const chosen = new Set([...state.inc, ...state.exc].map(t => `${t.kind}\u0000${t.tag}`));
    const html = feat.rows.filter(r => !chosen.has(`${r.kind}\u0000${r.tag}`)).slice(0, 12).map(r =>
      `<button type="button" class="chw-fs" data-chw-fs data-chw-tag="${escAttr(r.tag)}" data-chw-kind="${escAttr(r.kind)}">`
      + `<span>${escHtml(r.tag)}</span><i>${escHtml(r.label || r.kind)} · ${Number(r.count || 0).toLocaleString()}</i></button>`).join('')
      || (feat.text.trim() ? '<div class="chw-empty">맞는 낱말이 없습니다</div>' : '');
    const sug = box.querySelector('[data-chw-fsug]');
    if (sug._html !== html) { sug._html = html; sug.innerHTML = html; }
  }

  function suggest() {
    clearTimeout(feat.timer);
    feat.timer = setTimeout(async () => {
      const mine = ++feat.seq;
      const text = feat.text.trim();
      if (!text) { feat.rows = []; paintFeat(); return; }
      try {
        const res = await fetch(`/api/character-viewer/feature-suggest?q=${encodeURIComponent(text)}`);
        const data = await res.json().catch(() => ({}));
        if (mine !== feat.seq) return;
        if (data.pending) { feat.timer = setTimeout(suggest, 1500); return; }      // 색인 준비 중(Find 와 같다)
        feat.rows = Array.isArray(data.rows) ? data.rows : [];
      } catch (_) { feat.rows = []; }
      paintFeat();
    }, 150);
  }

  // ── 고른 캐릭터 줄 ───────────────────────────────────────────────────────────
  function paintSel() {
    const box = el('[data-chw-sel]');
    if (!box) return;
    if (!selected) { box.innerHTML = '<div class="chw-empty">캐릭터를 누르면 여기서 슬롯 · 풀 · 생성을 합니다.</div>'; return; }
    const s = selected;
    const off = busy ? ' disabled' : '';
    box.innerHTML = `<div class="chw-st"><b>${escHtml(s.character)}</b>`
      + `<span>${escHtml(s.group)} · ${Number(s.count || 0).toLocaleString()}${selectedLine ? ` · ${escHtml(selectedLine)}` : ''}</span></div>`
      + `<div class="chw-acts">`
      + `<button type="button" class="chw-act is-slot" data-chw-act="slot"${off}>+ 슬롯</button>`
      + `<button type="button" class="chw-act is-pool" data-chw-act="pool"${off}>+ 풀</button>`
      + `<button type="button" class="chw-act" data-chw-act="gen"${off} title="썸네일 생성(생성 설정 창의 Prefix · Postfix · 옵션)">생성</button>`
      + `<button type="button" class="chw-act${s.favorite ? ' is-on' : ''}" data-chw-act="fav"${off} title="즐겨찾기">★</button>`
      + `<button type="button" class="chw-act" data-chw-act="copy"${off} title="프롬프트 줄 복사">복사</button>`
      + `<button type="button" class="chw-act is-hide" data-chw-act="hide"${off} title="숨김(검색 · 랜덤에서 빠진다 · Find [제외] 에서 되돌린다)">숨김</button>`
      + `<button type="button" class="chw-act" data-chw-act="more"${off} title="썸네일 삭제 · Characters 탭에서 열기">⋯</button></div>`
      + `<div class="chw-more" data-chw-more hidden>`
      + `<button type="button" data-chw-act="delthumb">내 썸네일 삭제</button>`
      + `<button type="button" data-chw-act="tab">Characters 탭에서 열기(연속 생성 등)</button></div>`;
  }

  async function select(item) {
    selected = {group: item.group, character: item.character, count: item.count, favorite: !!item.favorite};
    // 고르기만 해도 생성 설정 창의 가상 슬롯에 담긴다(사용자 결정 2026-10-22).
    try { win.dispatchEvent(new CustomEvent('naia:character-picked', {detail: {group: item.group, character: item.character}})); } catch (_) {}
    selectedLine = '';
    paintSel();
    paintGrid();
    const mine = selected;
    try {
      // Find [+ 슬롯] 과 같은 옵션으로 - 슬롯에 담길 줄 그대로 보인다.
      const res = await fetch('/api/character-viewer/detail', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group: item.group, character: item.character, variant: '',
                              options: {hide_charname: false, cosplay_enabled: false, auto_copyright: true}}),
      });
      const data = await res.json().catch(() => ({}));
      if (mine !== selected) return;
      selectedLine = String(data.prompt?.character_prompt || '').trim();
      paintSel();
    } catch (_) { /* 줄만 못 보인다 */ }
  }

  async function act(kind) {
    if (!selected || busy) return;
    const s = selected;
    const actions = getActions() || {};
    if (kind === 'more') { const m = el('[data-chw-more]'); if (m) m.hidden = !m.hidden; return; }
    if (kind === 'copy') {
      try { await navigator.clipboard.writeText(selectedLine || s.character); showToast('프롬프트 줄을 복사했습니다.', 'info'); }
      catch (_) { showToast('복사하지 못했습니다.', 'error'); }
      return;
    }
    if (kind === 'tab') { openCharacterPage(s.group, s.character); return; }
    busy = kind;
    paintSel();
    try {
      if (kind === 'slot') await actions.addToSlot?.(s.group, s.character);
      else if (kind === 'pool') await actions.poolAdd?.(s.group, s.character);
      // [생성] = 가상 슬롯으로(그 슬롯에서 고친 줄 · 추가 프롬프트 · 네거티브가 함께 나간다).
      else if (kind === 'gen') await (actions.generateVirtual ? actions.generateVirtual(s.group, s.character)
        : actions.generateThumb?.(s.group, s.character));
      else if (kind === 'fav' || kind === 'hide') {
        const fav = kind === 'fav';
        const res = await fetch(fav ? '/api/character-viewer/favorite' : '/api/character-viewer/hidden', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(fav ? {group: s.group, character: s.character, favorite: !s.favorite}
            : {group: s.group, character: s.character, hidden: true}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || '처리하지 못했습니다.');
        if (fav) {
          s.favorite = !!data.favorite;
          showToast(s.favorite ? `${s.character} - 즐겨찾기에 넣었습니다` : `${s.character} - 즐겨찾기에서 뺐습니다`, 'info');
        } else {
          showToast(`${s.character} - 숨겼습니다. Find [제외] 에서 되돌립니다`, 'info');
          try { win.dispatchEvent(new CustomEvent('naia:character-hidden-changed')); } catch (_) {}
          selected = null;
        }
        resetResults();
      } else if (kind === 'delthumb') {
        const res = await fetch('/api/character-viewer/thumbnail/delete', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({group: s.group, character: s.character, variant: ''}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || '지우지 못했습니다.');
        showToast(`${s.character} - 내 썸네일을 지웠습니다(기본 팩 그림이 있으면 그것이 보입니다)`, 'info');
        resetResults();
      }
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      busy = '';
      paintSel();
    }
  }

  // 바깥에서 목록이 바뀌었다 - 썸네일 저장(생성 완료) · 숨김/되돌림 · 즐겨찾기(Find 쪽에서도). 자리는 지키고 덩어리만 새로.
  function softRefresh() {
    if (!panel || !panel.isOpen()) { blocks = new Map(); return; }    // 닫혀 있으면 열 때 새로 받는다
    seq += 1;
    aborts.forEach(ctrl => { try { ctrl.abort(); } catch (_) {} });
    aborts = new Map();
    blocks.forEach((value, key) => { if (Array.isArray(value)) stale.set(key, value); });
    blocks = new Map();
    paintGrid();
  }
  for (const name of ['naia:character-thumb-changed', 'naia:character-hidden-changed', 'naia:character-favorite-changed']) {
    try { win.addEventListener(name, softRefresh); } catch (_) { /* 이벤트가 없으면 다시 열 때 받는다 */ }
  }

  // ── 손 ──────────────────────────────────────────────────────────────────────
  function onSlotClick(event) {
    const actions = getActions() || {};
    if (event.target.closest('[data-chw-gset]')) actions.openGenSettings?.();
    else if (event.target.closest('[data-chw-pool]')) actions.openPoolWindow?.();
  }

  function onClick(event) {
    const t = event.target;
    const cell = t.closest('[data-chw-i]');
    if (cell) { const item = itemAt(Number(cell.dataset.chwI)); if (item) void select(item); return; }
    const g = t.closest('[data-chw-g]');
    if (g) { state.group = g.dataset.chwG || '__ALL__'; paintGroups(); resetResults(); return; }
    const gender = t.closest('[data-chw-gender]');
    if (gender) {
      state.gender = gender.dataset.chwGender;
      try { storage?.setItem(GENDER_KEY, state.gender); } catch (_) {}
      paintTools(); resetResults(); return;
    }
    if (t.closest('[data-chw-fav]')) { state.fav = !state.fav; paintTools(); resetResults(); return; }
    if (t.closest('[data-chw-featbtn]')) {
      feat.open = !feat.open; paintTools(); paintFeat();
      if (feat.open) el('[data-chw-ft]')?.focus();
      return;
    }
    const line = t.closest('[data-chw-fline]');
    if (line) { feat.line = line.dataset.chwFline; paintFeat(); return; }
    const fs = t.closest('[data-chw-fs]');
    if (fs) {
      const term = {tag: fs.dataset.chwTag, kind: fs.dataset.chwKind};
      (feat.line === 'exc' ? state.exc : state.inc).push(term);
      feat.text = ''; feat.rows = [];
      const input = el('[data-chw-ft]'); if (input) input.value = '';
      paintTools(); paintFeat(); resetResults(); return;
    }
    const chip = t.closest('[data-chw-unchip]');
    if (chip) {
      const same = term => term.tag === chip.dataset.chwTag && term.kind === chip.dataset.chwKind;
      if (chip.dataset.chwUnchip === 'exc') state.exc = state.exc.filter(x => !same(x));
      else state.inc = state.inc.filter(x => !same(x));
      paintTools(); paintFeat(); resetResults(); return;
    }
    const a = t.closest('[data-chw-act]');
    if (a) void act(a.dataset.chwAct);
  }

  function onInput(event) {
    if (event.target.closest('[data-chw-q]')) {
      state.query = event.target.value || '';
      seq += 1;                                     // 입력하는 즉시 옛 응답을 무효로(디바운스 중 반영 금지 - 성능 리뷰)
      clearTimeout(queryTimer);
      queryTimer = setTimeout(resetResults, 150);
      return;
    }
    if (event.target.closest('[data-chw-gq]')) {
      groupQuery = event.target.value || '';
      const list = el('[data-chw-glist]'); if (list) list.scrollTop = 0;
      paintGroups();
      return;
    }
    if (event.target.closest('[data-chw-ft]')) { feat.text = event.target.value || ''; suggest(); }
  }

  function onKey(event) {
    if (event.key === 'Enter' && event.target.closest('[data-chw-ft]')) {
      const first = el('[data-chw-fs]');
      if (first) { event.preventDefault(); first.click(); }
    }
  }

  // ── 바깥 ─────────────────────────────────────────────────────────────────────
  function open() {
    ensurePanel();
    if (panel.isOpen()) panel.raise(); else panel.open();
    if (panel.isCollapsed && panel.isCollapsed()) panel.expand();
    paintTools(); paintSel();
    if (!groups.length) void loadGroups();
    resetResults();
  }

  return {
    open,
    /** 탭 단추 규칙(Artist 와 같다) - 창을 세웠으면 false(탭으로 가지 않는다), 이미 펴져 있으면 true(탭으로). */
    requestTab() {
      if (!panel || !panel.isOpen() || (panel.isCollapsed && panel.isCollapsed())) { open(); return false; }
      return true;
    },
    isOpen: () => !!(panel && panel.isOpen()),
    refresh: () => { if (panel && panel.isOpen()) resetResults(); },
  };
}
