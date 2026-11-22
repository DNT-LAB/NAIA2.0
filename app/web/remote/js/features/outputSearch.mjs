// Output Search - 저장된 출력 이미지 전체를 태그 칩으로 찾는 화면(11-22 사용자 지정).
// 같은 본문을 두 곳이 쓴다: 앱 안의 떠 있는 창(outputSearchWindow.mjs)과 외부 브라우저 화면
// (output-search.html). 진입점이 둘이라도 본문은 하나다 - 한쪽만 고치는 일이 없게.
// 데이터는 전부 /api/output-index/* 이다. 바꾸는 요청(삭제 · 폴더 열기 · 폴더 추가)은
// 서버가 이 PC 에서 온 요청만 받는다 - 원격이면 그 단추를 아예 그리지 않는다.

const API = '/api/output-index';
const PAGE = 80;
const PREFS_KEY = 'naia.outputSearch.prefs';
const SOURCES = ['NAI', 'WEBUI', 'ComfyUI', 'NAIA', 'unknown'];
const SIZES = {s: {tile: 96, thumb: 192}, m: {tile: 136, thumb: 256}, l: {tile: 190, thumb: 384}};

export const OUTPUT_SEARCH_STYLE = `
.osr {display:flex;flex-direction:column;min-height:0;height:100%;font-size:12px;color:var(--text-primary,#e8e8f0)}
.osr [hidden] {display:none!important}
.osr button {font:inherit;color:inherit;background:transparent;border:1px solid var(--border-dim,#2a2a3d);
  border-radius:4px;padding:2px 7px;cursor:pointer;white-space:nowrap}
.osr button:hover {border-color:var(--border-glow,#3d3d5c);background:var(--bg-hover,rgba(255,255,255,.06))}
.osr button.on {color:var(--text-primary,#e8e8f0);background:rgba(124,106,239,.22);border-color:var(--accent,#7c6aef)}
.osr button.off {color:var(--text-dim,#9ea0b4);opacity:.7}
.osr button.warn {color:#e8c46a;border-color:rgba(232,196,106,.45);cursor:default}
.osr button.danger:hover {border-color:#e05561;color:#ff8a94}
.osr-row {display:flex;align-items:center;gap:5px;padding:5px 8px;border-bottom:1px solid var(--border-dim,#2a2a3d);flex-wrap:wrap}
.osr-sep {width:1px;height:16px;background:var(--border-dim,#2a2a3d);margin:0 2px}
.osr-grow {flex:1}
.osr-dim {color:var(--text-dim,#9ea0b4);font-size:11px}
.osr-box {position:relative;flex:1 1 280px;display:flex;flex-wrap:wrap;align-items:center;gap:4px;min-height:26px;
  padding:2px 6px;background:var(--bg-deep,#0a0a0f);border:1px solid var(--border-glow,#3d3d5c);border-radius:4px;cursor:text}
.osr-box:focus-within {border-color:var(--accent,#7c6aef)}
.osr-box input {flex:1;min-width:110px;border:0;outline:none;background:transparent;color:inherit;font:inherit;padding:2px 0}
.osr-chip {display:inline-flex;align-items:center;gap:4px;border:1px solid rgba(124,106,239,.55);border-radius:4px;
  padding:0 5px;background:rgba(124,106,239,.18);cursor:pointer;line-height:18px}
.osr-chip.ex {border-color:rgba(224,85,97,.55);background:rgba(224,85,97,.16);color:#ffb3b9}
.osr-chip.ex .osr-ct {text-decoration:line-through}
.osr-chip.tx {border-color:rgba(92,184,122,.55);background:rgba(92,184,122,.14)}
.osr-chip .osr-x {opacity:.6;padding:0 1px}
.osr-chip .osr-x:hover {opacity:1}
.osr-sug {position:absolute;left:-1px;right:-1px;top:calc(100% + 2px);z-index:5;max-height:260px;overflow:auto;
  background:var(--bg-card,#1a1a26);border:1px solid var(--border-glow,#3d3d5c);border-radius:4px}
.osr-sug div {display:flex;justify-content:space-between;gap:10px;padding:4px 8px;cursor:pointer}
.osr-sug div.act,.osr-sug div:hover {background:rgba(124,106,239,.22)}
.osr-sug i {font-style:normal;color:var(--text-dim,#9ea0b4)}
.osr-addroot {display:flex;gap:5px;flex:1 1 100%}
.osr-addroot input {flex:1;min-width:0;background:var(--bg-deep,#0a0a0f);color:inherit;font:inherit;
  border:1px solid var(--border-glow,#3d3d5c);border-radius:4px;padding:2px 6px;outline:none}
.osr-body {flex:1;display:flex;min-height:0}
.osr-left {flex:1;min-width:0;display:flex;flex-direction:column}
.osr-selbar {display:flex;align-items:center;gap:6px;padding:4px 8px;background:rgba(124,106,239,.12);
  border-bottom:1px solid var(--border-dim,#2a2a3d)}
.osr-list {flex:1;min-height:0;overflow:auto;padding:4px 6px 10px;user-select:none}
.osr-fold {display:flex;justify-content:space-between;padding:6px 2px 3px;color:var(--text-dim,#9ea0b4);font-size:11px;
  border-bottom:1px solid var(--border-dim,#2a2a3d);margin-bottom:3px}
.osr-grid {display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--osr-tile,136px),1fr));gap:3px}
.osr-th {position:relative;aspect-ratio:7/9;background:var(--bg-surface,#12121a);border:2px solid transparent;
  border-radius:3px;overflow:hidden;cursor:pointer}
.osr-th img {width:100%;height:100%;object-fit:cover;display:block}
.osr-th.sel {border-color:var(--accent-glow,#9d8bff)}
.osr-th.cur {border-color:#e8c46a}
.osr-th .osr-tick {position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:3px;font-size:10px;line-height:14px;
  text-align:center;background:var(--accent,#7c6aef);color:#fff}
.osr-more {padding:10px;text-align:center;color:var(--text-dim,#9ea0b4);font-size:11px}
.osr-right {width:290px;flex:none;border-left:1px solid var(--border-dim,#2a2a3d);overflow:auto;padding:8px;
  display:flex;flex-direction:column;gap:6px}
.osr-prev {aspect-ratio:7/9;max-height:52vh;background:var(--bg-surface,#12121a);border-radius:3px;display:flex;
  align-items:center;justify-content:center;overflow:hidden;cursor:zoom-in}
.osr-prev img {max-width:100%;max-height:100%;object-fit:contain}
.osr-path {word-break:break-all;color:var(--text-dim,#9ea0b4);font-size:11px}
.osr-meta {display:flex;flex-wrap:wrap;gap:4px}
.osr-meta span {border:1px solid var(--border-dim,#2a2a3d);border-radius:3px;padding:0 5px;font-size:11px;color:var(--text-muted,#c6c6d8)}
.osr-prompt {font-size:11px;line-height:1.45;color:var(--text-muted,#c6c6d8);border:1px solid var(--border-dim,#2a2a3d);
  border-radius:3px;padding:5px 6px;background:var(--bg-deep,#0a0a0f);max-height:180px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.osr-hl {background:rgba(124,106,239,.3);color:var(--text-primary,#e8e8f0);border-radius:2px}
.osr-acts {display:flex;flex-wrap:wrap;gap:4px}
.osr-empty {padding:24px 10px;text-align:center;color:var(--text-dim,#9ea0b4)}
.osr.narrow .osr-right {display:none}
`;

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
}

function fmt(n) {
  return Number(n || 0).toLocaleString('en-US');
}

function folderOf(path) {
  const i = String(path || '').lastIndexOf('/');
  return i < 0 ? '' : path.slice(0, i);
}

function nameOf(path) {
  const i = String(path || '').lastIndexOf('/');
  return i < 0 ? String(path || '') : path.slice(i + 1);
}

function readPrefs(storage) {
  try {
    const raw = JSON.parse(storage?.getItem(PREFS_KEY) || '{}');
    return {
      sort: raw.sort === 'mtime_asc' ? 'mtime_asc' : 'mtime_desc',
      view: raw.view === 'flat' ? 'flat' : 'folder',
      size: SIZES[raw.size] ? raw.size : 'm',
    };
  } catch (_) {
    return {sort: 'mtime_desc', view: 'folder', size: 'm'};
  }
}

/** 칩 하나 = {kind:'tag'|'text', text, exact, ex}. 서버 문법: exact 는 `*tag`, 아니면 부분 일치. */
export function chipQuery(chips) {
  const include = [], exclude = [];
  let text = '';
  for (const chip of chips) {
    if (chip.kind === 'text') { text = chip.text; continue; }
    (chip.ex ? exclude : include).push(chip.exact ? `*${chip.text}` : chip.text);
  }
  return {include, exclude, text};
}

/** 프롬프트에서 포함 칩에 걸린 태그를 강조한다. 부분 칩은 서버가 펼친 목록(matched)으로 판정한다. */
export function highlightPrompt(prompt, chips, matched = []) {
  const exact = new Set(chips.filter(c => c.kind === 'tag' && !c.ex).map(c => c.text.toLowerCase()));
  for (const tag of matched) exact.add(String(tag).toLowerCase());
  const partial = chips.filter(c => c.kind === 'tag' && !c.ex && !c.exact).map(c => c.text.toLowerCase());
  return String(prompt || '').split(/(,)/).map(part => {
    if (part === ',') return ',';
    const bare = part.trim().toLowerCase().replace(/^[\d.]+::/, '').replace(/::$/, '').replace(/[(){}\[\]]/g, '').trim();
    const hit = bare && (exact.has(bare) || partial.some(p => bare.includes(p)));
    if (!hit) return esc(part);
    const lead = part.match(/^\s*/)[0];
    return `${lead}<span class="osr-hl">${esc(part.trim())}</span>${part.slice(lead.length + part.trim().length)}`;
  }).join('');
}

export function createOutputSearch({
  document: doc,
  window: win,
  host,
  storage = null,
  initial = {},
  // 앱 안에서만 오는 손: 메인 프롬프트에 넣기. 없으면 [프롬프트] 단추는 복사로 동작한다.
  applyPrompt = null,
  openUrl = url => { win.open(url, '_blank'); return true; },
  confirmAsk = async message => win.confirm(message),
  toast = () => {},
  onStatus = () => {},
}) {
  const prefs = readPrefs(storage);
  const st = {
    chips: [],
    sources: new Set(SOURCES),
    roots: null,          // null = 전부. 아니면 켠 root id 집합
    allRoots: [],
    local: false,
    items: [], count: 0, matched: [], matchedTotal: 0,
    loading: false, done: false, seq: 0,
    sel: new Set(), anchor: -1, current: null,
    partial: false, rows: 0,
    textMode: false,
  };
  for (const tag of initial.include || []) st.chips.push(parseChip(tag, false));
  for (const tag of initial.exclude || []) st.chips.push(parseChip(tag, true));
  if (initial.text) st.chips.push({kind: 'text', text: String(initial.text)});

  function parseChip(raw, ex) {
    const text = String(raw || '').trim();
    const exact = text.startsWith('*');
    return {kind: 'tag', text: (exact ? text.slice(1) : text).toLowerCase(), exact, ex};
  }

  host.classList.add('osr');
  host.innerHTML = `
    <div class="osr-row">
      <div class="osr-box" data-box>
        <span class="osr-chips" data-chips></span>
        <input data-input type="text" placeholder="태그 추가" autocomplete="off" spellcheck="false" aria-label="태그 검색">
        <div class="osr-sug" data-sug hidden></div>
      </div>
      <button type="button" data-act="text" title="프롬프트 본문에서 글자 그대로 찾기 (느림)">본문</button>
      <span class="osr-sep"></span>
      <button type="button" data-act="sort" title="정렬"></button>
      <button type="button" data-act="view" title="보기 방식"></button>
      <button type="button" data-size="s" title="작게">S</button>
      <button type="button" data-size="m" title="보통">M</button>
      <button type="button" data-size="l" title="크게">L</button>
    </div>
    <div class="osr-row" data-filters>
      <span data-sources></span>
      <span class="osr-sep"></span>
      <span data-roots></span>
      <button type="button" data-act="addroot" data-local title="색인할 폴더 추가 (이 PC 에서만)" hidden>+ 폴더</button>
      <span class="osr-grow"></span>
      <span class="osr-dim" data-count></span>
    </div>
    <div class="osr-row" data-addroot-row hidden>
      <div class="osr-addroot">
        <input data-rootpath type="text" placeholder="D:\\images\\naia_old" spellcheck="false" aria-label="폴더 경로">
        <button type="button" data-act="addroot-ok">추가</button>
        <button type="button" data-act="addroot-cancel">취소</button>
      </div>
    </div>
    <div class="osr-body">
      <div class="osr-left">
        <div class="osr-selbar" data-selbar hidden>
          <span data-selcount></span>
          <span class="osr-grow"></span>
          <button type="button" data-act="seldelete" data-local class="danger" title="고른 그림을 휴지통으로 (Del)">삭제</button>
          <button type="button" data-act="selclear" title="선택 해제 (Esc)">해제</button>
        </div>
        <div class="osr-list" data-list tabindex="0"></div>
      </div>
      <div class="osr-right" data-detail></div>
    </div>`;
  const $ = sel => host.querySelector(sel);
  const input = $('[data-input]');
  const list = $('[data-list]');

  // ── 머리 상태 ──────────────────────────────────────────────────────────────
  async function api(path, body) {
    const options = body === undefined ? {cache: 'no-store'}
      : {method: 'POST', cache: 'no-store', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
    const response = await win.fetch(API + path, options);
    let data = null;
    try { data = await response.json(); } catch (_) { data = null; }
    if (!response.ok) {
      if (response.status === 403) throw new Error('이 PC 에서 연 화면에서만 할 수 있습니다.');
      throw new Error((data && (data.error || data.detail)) || `요청 실패 (${response.status})`);
    }
    return data;
  }

  let statusTimer = 0;
  async function loadStatus() {
    win.clearTimeout(statusTimer);
    let status;
    try { status = await api('/status'); } catch (_) { statusTimer = win.setTimeout(loadStatus, 5000); return; }
    const wasPartial = st.partial;
    st.partial = Boolean(status.partial);
    st.rows = status.live_rows || 0;
    st.allRoots = status.roots || [];
    // 원격 화면에는 서버가 경로를 빼서 준다 - 그것으로 '이 PC' 인지 안다.
    st.local = st.allRoots.length > 0 && st.allRoots.every(r => typeof r.path === 'string');
    host.querySelectorAll('[data-local]').forEach(node => { node.hidden = !st.local; });
    drawRoots();
    onStatus({partial: st.partial, rows: st.rows, foldersDone: status.folders_done, pending: status.pending_dirs});
    if (st.partial || status.running) statusTimer = win.setTimeout(loadStatus, 2000);
    if (wasPartial && !st.partial) runQuery();
  }

  // ── 칩 · 후보 ─────────────────────────────────────────────────────────────
  function drawChips() {
    $('[data-chips]').innerHTML = st.chips.map((chip, i) => {
      const cls = chip.kind === 'text' ? 'tx' : chip.ex ? 'ex' : '';
      const mark = chip.kind === 'text' ? '“' : chip.ex ? '−' : chip.exact ? '' : '~';
      const tip = chip.kind === 'text' ? '본문 글자 검색' : chip.exact ? '이 태그만 · 클릭: 포함/제외' : '이 글자가 든 태그 전부 · 클릭: 포함/제외';
      return `<span class="osr-chip ${cls}" data-chip="${i}" title="${tip}">${mark}<span class="osr-ct">${esc(chip.text)}</span>`
        + `<span class="osr-x" data-rm="${i}" title="빼기">×</span></span>`;
    }).join('');
    $('[data-act="text"]').classList.toggle('on', st.textMode);
    input.placeholder = st.textMode ? '본문 글자 (Enter)' : (st.chips.length ? '' : '태그 추가');
  }

  let sugSeq = 0, sugTimer = 0, sugItems = [], sugAct = -1;
  function closeSug() { $('[data-sug]').hidden = true; sugItems = []; sugAct = -1; }
  function drawSug() {
    const box = $('[data-sug]');
    const q = input.value.trim();
    if (!q || st.textMode) { closeSug(); return; }
    const rows = [`<div data-sug-i="-1" class="${sugAct < 0 ? 'act' : ''}"><span>~ ${esc(q)} <i>포함 전부</i></span><i>Enter</i></div>`];
    sugItems.forEach((item, i) => rows.push(
      `<div data-sug-i="${i}" class="${sugAct === i ? 'act' : ''}"><span>${esc(item.tag)}</span><i>${fmt(item.condition_count ?? item.count)}</i></div>`));
    box.innerHTML = rows.join('');
    box.hidden = false;
  }
  async function loadSug() {
    const q = input.value.trim();
    const seq = ++sugSeq;
    if (!q || st.textMode) { closeSug(); return; }
    const {include, exclude} = chipQuery(st.chips);
    const params = new URLSearchParams({q, limit: '12'});
    include.forEach(t => params.append('include', t));
    exclude.forEach(t => params.append('exclude', t));
    try {
      const data = await api('/suggest?' + params.toString());
      if (seq !== sugSeq) return;
      sugItems = data.items || [];
      sugAct = -1;
      drawSug();
    } catch (_) { /* 후보가 없어도 Enter 는 된다 */ }
  }
  function addChip(text, exact) {
    const value = String(text || '').trim().toLowerCase();
    if (!value) return;
    if (st.textMode) {
      st.chips = st.chips.filter(c => c.kind !== 'text');
      st.chips.push({kind: 'text', text: String(text).trim()});
      st.textMode = false;
    } else if (!st.chips.some(c => c.kind === 'tag' && c.text === value && c.exact === exact)) {
      st.chips.push({kind: 'tag', text: value, exact, ex: false});
    }
    input.value = '';
    closeSug();
    drawChips();
    runQuery();
  }

  // ── 거르개 줄 ─────────────────────────────────────────────────────────────
  function drawSources() {
    $('[data-sources]').innerHTML = SOURCES.map(s =>
      `<button type="button" data-src="${s}" class="${st.sources.has(s) ? 'on' : 'off'}" title="${s === 'unknown' ? '메타 없음 · 스텔스' : s}">${s}</button>`).join(' ');
  }
  function drawRoots() {
    const label = r => r.kind === 'save' ? '저장 폴더' : r.kind === 'quicksave' ? '빠른 저장' : nameOf(String(r.path || '').replace(/\\/g, '/')) || `폴더 ${r.id}`;
    $('[data-roots]').innerHTML = st.allRoots.filter(r => !r.shadowed).map(r => {
      if (r.unreachable) return `<button type="button" class="warn" title="연결 안 됨${r.path ? ' · ' + esc(r.path) : ''}">${esc(label(r))} ⚠</button>`;
      if (!r.enabled) return '';
      const on = !st.roots || st.roots.has(r.id);
      const rm = st.local && r.kind === 'user' ? `<span class="osr-x" data-rmroot="${r.id}" title="색인에서 빼기"> ×</span>` : '';
      return `<button type="button" data-root="${r.id}" class="${on ? 'on' : 'off'}" title="${esc(r.path || label(r))}">${esc(label(r))}${rm}</button>`;
    }).join(' ');
  }
  function drawCount() {
    const loaded = st.items.length;
    let text = `${fmt(st.count)}장`;
    if (st.partial) text += ` · 색인 중 ${fmt(st.rows)}`;
    const node = $('[data-count]');
    node.textContent = text;
    node.title = st.matchedTotal ? `부분 일치로 펼친 태그 ${st.matchedTotal}개: ${st.matched.slice(0, 30).join(', ')}` : `${fmt(loaded)}장 불러옴`;
  }
  function drawPrefs() {
    $('[data-act="sort"]').textContent = prefs.sort === 'mtime_asc' ? '오래된순' : '최신순';
    $('[data-act="view"]').textContent = prefs.view === 'flat' ? '한 줄' : '폴더별';
    host.querySelectorAll('[data-size]').forEach(b => b.classList.toggle('on', b.dataset.size === prefs.size));
    host.style.setProperty('--osr-tile', `${SIZES[prefs.size].tile}px`);
  }
  function savePrefs() {
    try { storage?.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (_) { /* 기억 못 해도 화면은 된다 */ }
  }

  // ── 질의 · 무한 스크롤 ────────────────────────────────────────────────────
  function queryBody(offset) {
    const {include, exclude, text} = chipQuery(st.chips);
    const body = {include, exclude, sort: prefs.sort, offset, limit: PAGE};
    if (text) body.text = text;
    if (st.sources.size !== SOURCES.length) body.source = [...st.sources];
    if (st.roots) body.roots = [...st.roots];
    return body;
  }
  async function runQuery() {
    const seq = ++st.seq;
    st.items = []; st.done = false; st.loading = false;
    st.sel.clear(); st.anchor = -1;
    list.scrollTop = 0;
    list.innerHTML = '';
    drawSel();
    await loadMore(seq);
  }
  async function loadMore(seq = st.seq) {
    if (st.loading || st.done || seq !== st.seq) return;
    st.loading = true;
    drawTail();
    try {
      const data = await api('/query', queryBody(st.items.length));
      if (seq !== st.seq) return;
      const items = data.items || [];
      st.count = data.count || 0;
      st.matched = data.matched || [];
      st.matchedTotal = data.matched_total || 0;
      const start = st.items.length;
      st.items.push(...items);
      st.done = items.length < PAGE || st.items.length >= st.count;
      appendTiles(start);
      if (!st.current && st.items.length) select(0, {});
      if (!st.items.length) drawDetail();
    } catch (error) {
      if (seq === st.seq) toast(error.message, 'error');
      st.done = true;
    } finally {
      if (seq === st.seq) { st.loading = false; drawTail(); drawCount(); }
    }
    // 첫 장이 화면을 다 못 채우면 스크롤이 생기지 않는다 - 그때는 바로 더 부른다.
    if (seq === st.seq && !st.done && list.scrollHeight <= list.clientHeight + 40) loadMore(seq);
  }
  function tile(item, index) {
    const size = SIZES[prefs.size].thumb;
    const cls = ['osr-th', st.sel.has(index) ? 'sel' : '', st.current === index ? 'cur' : ''].join(' ');
    return `<div class="${cls}" data-i="${index}" title="${esc(nameOf(item.path))}">`
      + `<img loading="lazy" decoding="async" alt="" src="${API}/thumb?row=${item.row}&size=${size}">`
      + `${st.sel.has(index) && st.sel.size > 1 ? '<span class="osr-tick">✓</span>' : ''}</div>`;
  }
  function appendTiles(start) {
    const html = [];
    let grid = list.lastElementChild?.matches?.('.osr-group') ? list.lastElementChild : null;
    let lastFolder = grid ? grid.dataset.folder : null;
    let chunk = [];
    const flush = () => {
      if (!chunk.length) return;
      if (grid) grid.querySelector('.osr-grid').insertAdjacentHTML('beforeend', chunk.join(''));
      else html.push(chunk.join(''));
      chunk = [];
    };
    if (prefs.view === 'flat') {
      if (!grid) {
        list.insertAdjacentHTML('beforeend', '<div class="osr-group" data-folder=""><div class="osr-grid"></div></div>');
        grid = list.lastElementChild;
      }
      grid.querySelector('.osr-grid').insertAdjacentHTML('beforeend',
        st.items.slice(start).map((item, k) => tile(item, start + k)).join(''));
    } else {
      for (let i = start; i < st.items.length; i += 1) {
        const folder = folderOf(st.items[i].path);
        if (folder !== lastFolder) {
          flush();
          if (html.length) { list.insertAdjacentHTML('beforeend', html.join('')); html.length = 0; }
          list.insertAdjacentHTML('beforeend',
            `<div class="osr-group" data-folder="${esc(folder)}"><div class="osr-fold"><span>${esc(folder || '(뿌리)')}</span><span data-fc>0</span></div><div class="osr-grid"></div></div>`);
          grid = list.lastElementChild;
          lastFolder = folder;
        }
        chunk.push(tile(st.items[i], i));
      }
      flush();
      list.querySelectorAll('.osr-group').forEach(g => {
        const counter = g.querySelector('[data-fc]');
        if (counter) counter.textContent = fmt(g.querySelectorAll('.osr-th').length);
      });
    }
    drawTail();
  }
  function drawTail() {
    let tail = list.querySelector('.osr-more');
    if (!tail) {
      list.insertAdjacentHTML('beforeend', '<div class="osr-more" data-tail></div>');
      tail = list.querySelector('.osr-more');
    } else if (tail !== list.lastElementChild) {
      list.appendChild(tail);
    }
    if (st.loading) tail.textContent = '불러오는 중…';
    else if (!st.items.length) tail.textContent = st.partial ? '아직 색인하는 중입니다.' : '맞는 그림이 없습니다.';
    else tail.textContent = st.done ? `${fmt(st.items.length)}장` : '';
  }
  list.addEventListener('scroll', () => {
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - 400) loadMore();
  }, {passive: true});

  // ── 고르기 ────────────────────────────────────────────────────────────────
  function paintTile(index) {
    const node = list.querySelector(`.osr-th[data-i="${index}"]`);
    if (!node) return;
    node.classList.toggle('sel', st.sel.has(index));
    node.classList.toggle('cur', st.current === index);
    const tick = node.querySelector('.osr-tick');
    const want = st.sel.has(index) && st.sel.size > 1;
    if (want && !tick) node.insertAdjacentHTML('beforeend', '<span class="osr-tick">✓</span>');
    if (!want && tick) tick.remove();
  }
  function repaintAll() {
    list.querySelectorAll('.osr-th').forEach(node => paintTile(Number(node.dataset.i)));
  }
  function select(index, {ctrl = false, shift = false} = {}) {
    if (!st.items[index]) return;
    const before = st.sel.size;
    if (shift && st.anchor >= 0) {
      const [a, b] = st.anchor < index ? [st.anchor, index] : [index, st.anchor];
      if (!ctrl) st.sel.clear();
      for (let i = a; i <= b; i += 1) st.sel.add(i);
    } else if (ctrl) {
      if (st.sel.has(index)) st.sel.delete(index); else st.sel.add(index);
      st.anchor = index;
    } else {
      st.sel.clear();
      st.sel.add(index);
      st.anchor = index;
    }
    const prev = st.current;
    st.current = index;
    if (before > 1 || st.sel.size > 1 || shift) repaintAll();
    else { paintTile(prev); paintTile(index); }
    drawSel();
    drawDetail();
  }
  function drawSel() {
    const n = st.sel.size;
    $('[data-selbar]').hidden = n < 2;
    $('[data-selcount]').textContent = `${fmt(n)}장 선택`;
  }
  function clearSel() {
    if (st.sel.size < 2) return;
    st.sel = new Set(st.current != null ? [st.current] : []);
    repaintAll();
    drawSel();
  }

  // ── 상세 ──────────────────────────────────────────────────────────────────
  let metaSeq = 0;
  function drawDetail() {
    const box = $('[data-detail]');
    const item = st.items[st.current];
    if (!item) { box.innerHTML = `<div class="osr-empty">${st.items.length ? '' : '그림을 고르면 여기에 보입니다.'}</div>`; return; }
    const date = new Date(item.mtime * 1000);
    const when = Number.isFinite(date.getTime()) ? date.toLocaleString() : '';
    box.innerHTML = `
      <div class="osr-prev" data-act="original" title="원본 열기"><img alt="" src="${API}/thumb?row=${item.row}&size=384"></div>
      <div class="osr-path">${esc(item.path)}</div>
      <div class="osr-meta">
        ${item.width ? `<span>${item.width}×${item.height}</span>` : ''}
        <span>${esc(item.source)}</span>
        ${item.seed != null ? `<span title="seed">${esc(item.seed)}</span>` : ''}
        ${when ? `<span>${esc(when)}</span>` : ''}
      </div>
      <div class="osr-prompt" data-prompt>${item.prompt ? highlightPrompt(item.prompt, st.chips, st.matched) : '<i class="osr-dim">메타 없음</i>'}</div>
      <div class="osr-acts">
        <button type="button" data-act="original" title="원본을 브라우저로">원본</button>
        <button type="button" data-act="prompt" title="${applyPrompt ? '프롬프트 · 네거티브를 메인에 넣기' : '프롬프트 복사'}" ${item.prompt ? '' : 'disabled'}>${applyPrompt ? '프롬프트 넣기' : '프롬프트 복사'}</button>
        <button type="button" data-act="locate" data-local title="탐색기에서 이 파일 보기" ${st.local ? '' : 'hidden'}>폴더 열기</button>
        <button type="button" data-act="delete" data-local class="danger" title="휴지통으로 (Del)" ${st.local ? '' : 'hidden'}>삭제</button>
      </div>`;
    // 목록의 프롬프트는 300자로 잘려 온다 - 긴 것만 전체를 따로 받는다.
    if (item.prompt && item.prompt.length >= 300) {
      const seq = ++metaSeq;
      api(`/meta?row=${item.row}`).then(meta => {
        if (seq !== metaSeq || st.items[st.current] !== item) return;
        const node = $('[data-prompt]');
        if (node && meta?.prompt) node.innerHTML = highlightPrompt(meta.prompt, st.chips, st.matched);
      }).catch(() => {});
    }
  }

  async function doDelete(indices) {
    const targets = [...indices].filter(i => st.items[i]).sort((a, b) => a - b);
    if (!targets.length) return;
    const ok = await confirmAsk(targets.length === 1
      ? `${nameOf(st.items[targets[0]].path)} 을(를) 휴지통으로 보낼까요?`
      : `${fmt(targets.length)}장을 휴지통으로 보낼까요?`);
    if (!ok) return;
    const deleted = new Set();
    const failed = [];
    for (let k = 0; k < targets.length; k += 200) {
      const part = targets.slice(k, k + 200);
      try {
        const data = await api('/delete', {rows: part.map(i => st.items[i].row)});
        (data.deleted || []).forEach(row => deleted.add(row));
        failed.push(...(data.failed || []));
      } catch (error) {
        toast(error.message, 'error');
        break;
      }
    }
    if (deleted.size) removeRows(deleted);
    if (failed.length) toast(`${fmt(failed.length)}장은 지우지 못했습니다: ${failed[0].error || ''}`, 'error');
    else if (deleted.size) toast(`${fmt(deleted.size)}장을 휴지통으로 보냈습니다.`, 'success');
  }
  function removeRows(rows) {
    const keepCurrent = st.items[st.current];
    const nextIndex = st.current;
    st.items = st.items.filter(item => !rows.has(item.row));
    st.count = Math.max(0, st.count - rows.size);
    st.sel.clear();
    list.innerHTML = '';
    appendTiles(0);
    const stay = keepCurrent && !rows.has(keepCurrent.row) ? st.items.indexOf(keepCurrent) : Math.min(nextIndex ?? 0, st.items.length - 1);
    st.current = null;
    if (stay >= 0) select(stay, {}); else drawDetail();
    drawCount();
    drawSel();
    if (!st.done && list.scrollHeight <= list.clientHeight + 40) loadMore();
  }

  async function doPrompt(item) {
    let meta;
    try { meta = await api(`/meta?row=${item.row}`); } catch (error) { toast(error.message, 'error'); return; }
    if (applyPrompt) { applyPrompt({prompt: meta.prompt || '', negative: meta.negative || '', meta}); return; }
    try {
      await win.navigator.clipboard.writeText(meta.prompt || '');
      toast('프롬프트를 복사했습니다.', 'success');
    } catch (_) {
      toast('클립보드에 쓰지 못했습니다.', 'error');
    }
  }

  // ── 손 ────────────────────────────────────────────────────────────────────
  host.addEventListener('click', async event => {
    const t = event.target;
    const rmIndex = t.closest('[data-rm]')?.dataset.rm;
    if (rmIndex != null) { st.chips.splice(Number(rmIndex), 1); drawChips(); runQuery(); return; }
    const chip = t.closest('[data-chip]');
    if (chip) {
      const c = st.chips[Number(chip.dataset.chip)];
      if (c && c.kind === 'tag') { c.ex = !c.ex; drawChips(); runQuery(); }
      return;
    }
    const sug = t.closest('[data-sug-i]');
    if (sug) {
      const i = Number(sug.dataset.sugI);
      if (i < 0) addChip(input.value, false); else addChip(sugItems[i]?.tag, true);
      input.focus();
      return;
    }
    if (t.closest('[data-box]')) { input.focus(); return; }
    const rmRoot = t.closest('[data-rmroot]')?.dataset.rmroot;
    if (rmRoot) {
      event.stopPropagation();
      if (await confirmAsk('이 폴더를 색인에서 뺄까요? (파일은 그대로)')) {
        try { await api('/roots', {action: 'remove', root_id: Number(rmRoot)}); await loadStatus(); runQuery(); }
        catch (error) { toast(error.message, 'error'); }
      }
      return;
    }
    const src = t.closest('[data-src]')?.dataset.src;
    if (src) {
      // 전부 켜진 상태에서 하나를 누르면 '그것만' 이 사람이 바라는 것이다. 다시 누르면 전부로.
      if (st.sources.size === SOURCES.length) st.sources = new Set([src]);
      else if (st.sources.has(src) && st.sources.size === 1) st.sources = new Set(SOURCES);
      else if (st.sources.has(src)) st.sources.delete(src);
      else st.sources.add(src);
      drawSources(); runQuery(); return;
    }
    const root = t.closest('[data-root]')?.dataset.root;
    if (root) {
      const id = Number(root);
      const live = st.allRoots.filter(r => r.enabled && !r.unreachable && !r.shadowed).map(r => r.id);
      if (!st.roots) st.roots = new Set([id]);
      else if (st.roots.has(id) && st.roots.size === 1) st.roots = null;
      else if (st.roots.has(id)) st.roots.delete(id);
      else st.roots.add(id);
      if (st.roots && live.every(r => st.roots.has(r))) st.roots = null;
      drawRoots(); runQuery(); return;
    }
    const size = t.closest('[data-size]')?.dataset.size;
    if (size) { prefs.size = size; savePrefs(); drawPrefs(); runQuery(); return; }
    const th = t.closest('.osr-th');
    if (th) {
      select(Number(th.dataset.i), {ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey});
      list.focus({preventScroll: true});
      return;
    }
    const act = t.closest('[data-act]')?.dataset.act;
    const item = st.items[st.current];
    switch (act) {
      case 'text': st.textMode = !st.textMode; drawChips(); closeSug(); input.focus(); break;
      case 'sort': prefs.sort = prefs.sort === 'mtime_asc' ? 'mtime_desc' : 'mtime_asc'; savePrefs(); drawPrefs(); runQuery(); break;
      case 'view': prefs.view = prefs.view === 'flat' ? 'folder' : 'flat'; savePrefs(); drawPrefs(); runQuery(); break;
      case 'addroot': $('[data-addroot-row]').hidden = false; $('[data-rootpath]').focus(); break;
      case 'addroot-cancel': $('[data-addroot-row]').hidden = true; break;
      case 'addroot-ok': await addRoot(); break;
      case 'seldelete': await doDelete(st.sel); break;
      case 'selclear': clearSel(); break;
      case 'original': if (item && !openUrl(`${API}/file?row=${item.row}`)) toast('브라우저를 열지 못했습니다.', 'error'); break;
      case 'prompt': if (item) await doPrompt(item); break;
      case 'locate':
        if (item) { try { await api('/open-location', {row: item.row}); } catch (error) { toast(error.message, 'error'); } }
        break;
      case 'delete': if (item) await doDelete(new Set([st.current])); break;
      default: break;
    }
  });
  host.addEventListener('dblclick', event => {
    const th = event.target.closest('.osr-th');
    const item = th ? st.items[Number(th.dataset.i)] : null;
    if (item) openUrl(`${API}/file?row=${item.row}`);
  });

  async function addRoot() {
    const path = $('[data-rootpath]').value.trim();
    if (!path) return;
    try {
      await api('/roots', {action: 'add', path});
      $('[data-addroot-row]').hidden = true;
      $('[data-rootpath]').value = '';
      toast('폴더를 추가했습니다. 색인이 끝나면 결과에 나옵니다.', 'success');
      await loadStatus();
    } catch (error) {
      toast(error.message, 'error');
    }
  }

  input.addEventListener('input', () => {
    win.clearTimeout(sugTimer);
    if (!input.value.trim()) { closeSug(); return; }
    drawSug();
    sugTimer = win.setTimeout(loadSug, 120);
  });
  input.addEventListener('keydown', event => {
    const sugOpen = !$('[data-sug]').hidden;
    if (event.key === 'ArrowDown' && sugOpen) { event.preventDefault(); sugAct = Math.min(sugAct + 1, sugItems.length - 1); drawSug(); }
    else if (event.key === 'ArrowUp' && sugOpen) { event.preventDefault(); sugAct = Math.max(sugAct - 1, -1); drawSug(); }
    else if (event.key === 'Enter') {
      event.preventDefault();
      if (sugAct >= 0 && sugItems[sugAct]) addChip(sugItems[sugAct].tag, true);
      else addChip(input.value, false);
    } else if (event.key === 'Escape') { if (sugOpen) { event.stopPropagation(); closeSug(); } }
    else if (event.key === 'Backspace' && !input.value && st.chips.length) { st.chips.pop(); drawChips(); runQuery(); }
  });
  $('[data-rootpath]').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); addRoot(); }
  });
  doc.addEventListener('pointerdown', event => {
    if (!event.target.closest?.('[data-box]')) closeSug();
  });
  list.addEventListener('keydown', event => {
    if (event.key === 'Delete' && st.local) { event.preventDefault(); doDelete(st.sel.size ? st.sel : new Set([st.current])); }
    else if (event.key === 'Escape' && st.sel.size > 1) { event.stopPropagation(); clearSel(); }
    else if ((event.key === 'a' || event.key === 'A') && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      st.items.forEach((_, i) => st.sel.add(i));
      repaintAll(); drawSel();
    } else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault();
      const next = (st.current ?? -1) + (event.key === 'ArrowRight' ? 1 : -1);
      if (st.items[next]) {
        select(next, {shift: event.shiftKey});
        list.querySelector(`.osr-th[data-i="${next}"]`)?.scrollIntoView({block: 'nearest'});
        if (next >= st.items.length - 6) loadMore();
      }
    }
  });

  // 좁은 창에서는 상세를 접는다(목록이 먼저다).
  const ro = typeof win.ResizeObserver === 'function'
    ? new win.ResizeObserver(() => host.classList.toggle('narrow', host.clientWidth < 620)) : null;
  ro?.observe(host);

  drawChips();
  drawSources();
  drawPrefs();
  drawDetail();
  loadStatus();
  runQuery();

  return {
    refresh() { loadStatus(); runQuery(); },
    focus() { input.focus(); },
    state() { return {chips: st.chips.map(c => ({...c})), count: st.count, loaded: st.items.length}; },
    externalParams() {
      const p = new URLSearchParams();
      const {include, exclude, text} = chipQuery(st.chips);
      include.forEach(t => p.append('inc', t));
      exclude.forEach(t => p.append('exc', t));
      if (text) p.set('text', text);
      return p.toString();
    },
    destroy() { win.clearTimeout(statusTimer); ro?.disconnect(); host.innerHTML = ''; },
  };
}
