/* 미니 프리셋 창(사용자 11-20) — 메인 프롬프트에서 `/의상` · `/자세` · `/표정` · `/배경` 을 다 치면 곧바로 그 탭으로
 * 캐럿 자리에 뜬다(`/preset` 은 PE 프롬프트 프리셋 그대로 - 사용자 11-20).
 *
 * 옛 `preset:` 팝업(분류 › 묶음 › 고르기)을 프리셋 벤치의 세트 목록으로 다시 그린 것:
 *   갈래 탭(의상 · 자세 · 2인 · 표정 · 배경) · 대분류 › 묶음 › 세트 그림.
 * **그림을 누르면 그 세트의 태그가 곧바로 그 자리에 들어가고 창이 닫힌다** — 넣기 단추는 없다(사용자 11-20
 * "이미지를 선택하면 그냥 바로 프롬프트로 변환"). [무작위] 는 지금 보이는 세트 중 하나를 넣는다.
 * 무작위 토큰(`preset:` · `&` 교차)은 남기지 않는다 — 들어가는 것은 늘 평범한 태그다.
 *
 * 목록 · 세트 · 썸네일 · 검색은 프리셋 벤치와 같은 라우트(/api/presets/*)를 쓴다. 형제 세트끼리 같은 태그는
 * 그림 밑 글에서 빼고 이 세트에만 있는 태그는 노랑(벤치 카드와 같은 규칙 - siblingTags).
 * - Esc · × = 닫고 캐럿으로 돌아간다. 바깥을 누르면 닫기만 한다(누른 곳의 초점을 뺏지 않는다).
 * - Esc · Enter 는 여기서 전파를 끊는다(Ctrl+Enter = Generate 가 버블 단계에 있다 - slashPopup 과 같다).
 * - CSS 는 이 모듈이 싣는다. ⚠️ CSS 템플릿 안에는 백틱을 쓰지 않는다.
 */
import { siblingTags } from './presetBenchModel.mjs?v=20261120-pl1';

const STYLE_ID = 'preset-mini-style';
const CSS = `
.pmini { position: fixed; z-index: 10002; width: min(720px, calc(100vw - 16px)); height: min(430px, calc(100vh - 16px));
  box-sizing: border-box; display: flex; flex-direction: column; border-radius: 8px; background: #16151f;
  border: 1px solid rgba(139,118,255,0.75); box-shadow: 0 6px 24px rgba(0,0,0,0.55); color: var(--text-primary); font-size: 11px; }
.pmini-head { display: flex; align-items: center; gap: 4px; padding: 6px 7px; border-bottom: 1px solid var(--border-dim); }
.pmini-tab { height: 22px; padding: 0 9px; border-radius: 5px; border: 1px solid var(--border-dim); background: transparent;
  color: var(--text-muted); font-size: 11px; cursor: pointer; white-space: nowrap; }
.pmini-tab:hover { color: var(--text-primary); }
.pmini-tab.is-on { border-color: rgba(139,118,255,0.85); background: rgba(88,76,170,0.4); color: var(--text-primary); }
.pmini-q { flex: 1 1 120px; min-width: 80px; height: 22px; box-sizing: border-box; padding: 0 7px; border-radius: 5px;
  border: 1px solid var(--border-dim); background: #0f0e16; color: var(--text-primary); font-size: 11px; outline: none; }
.pmini-q:focus { border-color: var(--accent); }
.pmini-btn { height: 22px; padding: 0 8px; border-radius: 5px; border: 1px solid var(--border-dim); background: transparent;
  color: var(--text-muted); font-size: 11px; cursor: pointer; white-space: nowrap; }
.pmini-btn:hover { color: var(--text-primary); border-color: var(--text-dim); }
.pmini-body { flex: 1 1 auto; min-height: 0; display: flex; }
.pmini-col { overflow-y: auto; border-right: 1px solid var(--border-dim); padding: 4px; box-sizing: border-box; }
.pmini-cats { width: 112px; flex: none; }
.pmini-seeds { width: 158px; flex: none; }
.pmini-row { display: flex; align-items: center; gap: 4px; padding: 3px 6px; border-radius: 4px; cursor: pointer; color: var(--text-muted); }
.pmini-row:hover { background: rgba(255,255,255,0.06); color: var(--text-primary); }
.pmini-row.is-on { background: rgba(88,76,170,0.4); color: var(--text-primary); }
.pmini-row > span:first-child { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pmini-row small { color: var(--text-dim); font-size: 9.5px; margin-left: 3px; }
.pmini-row > span:last-child { color: var(--text-dim); font-size: 10px; }
.pmini-sub { padding: 5px 6px 2px; color: var(--text-dim); font-size: 10px; }
.pmini-grid-wrap { flex: 1 1 auto; overflow-y: auto; padding: 5px; }
.pmini-ctx { padding: 0 2px 4px; color: var(--text-dim); font-size: 10px; }
.pmini-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(92px, 1fr)); gap: 5px; }
.pmini-card { cursor: pointer; border-radius: 5px; border: 1px solid transparent; background: #0f0e16; overflow: hidden; }
.pmini-card:hover { border-color: rgba(139,118,255,0.9); }
.pmini-th { display: block; width: 100%; aspect-ratio: 1 / 1; object-fit: cover; background: #000; }
.pmini-th.is-tall { aspect-ratio: 3 / 4; object-position: top; }
.pmini-none { display: flex; align-items: center; justify-content: center; color: var(--text-dim); font-size: 10px; }
.pmini-cap { padding: 2px 4px 3px; font-size: 9.5px; line-height: 1.3; color: var(--text-muted);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.pmini-cap .pmini-u { color: #ffd54f; }
.pmini-empty { padding: 14px 6px; color: var(--text-dim); text-align: center; }
`;

// 갈래 탭 - 서버 kind 와 짧은 이름(옛 팝업의 G/S/Q/E 자리)
export const MINI_KINDS = [
  {kind: 'outfit', label: '의상'},
  {kind: 'event', label: '자세'},
  {kind: 'link', label: '2인'},
  {kind: 'expression', label: '표정'},
  {kind: 'scene', label: '배경'},
];

/** 세트 하나 -> 넣을 글. 세트 태그 + 함께 싣는 태그(add) - 메인 프롬프트에 그대로 들어간다. */
export function setPromptText(set) {
  const seen = new Set();
  const out = [];
  for (const raw of [...(set?.tags || []), ...(set?.add || [])]) {
    const tag = String(raw || '').trim();
    if (tag && !seen.has(tag)) { seen.add(tag); out.push(tag); }
  }
  return out.join(', ');
}

export function createPresetMiniPopup({document = globalThis.document, window = globalThis.window, fetchJson = null, showToast = null} = {}) {
  const getJson = fetchJson || (async url => {
    const res = await window.fetch(url, {cache: 'no-store'});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  });
  const API = {
    catalog: (kind, pool) => `/api/presets/catalog?kind=${encodeURIComponent(kind)}&pool=${encodeURIComponent(pool)}`,
    sets: (kind, pool, seed) => `/api/presets/sets?kind=${encodeURIComponent(kind)}&pool=${encodeURIComponent(pool)}&seed=${encodeURIComponent(seed)}`,
    search: (q, kind) => `/api/presets/search?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`,
    thumb: key => `/api/presets/thumb/${encodeURIComponent(key)}`,
  };
  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const catalogCache = new Map();
  const setsCache = new Map();
  // 창을 닫아도 마지막 갈래 · 대분류 · 묶음은 기억한다(다음 /preset 이 그 자리에서 열린다).
  const memo = {kind: 'outfit', views: {}};
  let st = null;          // 열려 있을 때만

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
  }
  function catalogOf(kind) {
    if (!catalogCache.has(kind)) catalogCache.set(kind, getJson(API.catalog(kind, '')).catch(error => { catalogCache.delete(kind); throw error; }));
    return catalogCache.get(kind);
  }
  function setsOf(kind, pool, seed) {
    const key = `${kind}|${pool}|${seed}`;
    if (!setsCache.has(key)) {
      setsCache.set(key, getJson(API.sets(kind, pool, seed)).then(data => data.sets || [])
        .catch(error => { setsCache.delete(key); throw error; }));
    }
    return setsCache.get(key);
  }
  const viewOf = kind => (memo.views[kind] ||= {cat: '', sub: '', seed: '', q: '', hits: null});
  const setTotal = seeds => (seeds || []).reduce((sum, seed) => sum + Number(seed.sets || seed.count || 0), 0);
  const seedName = seed => (seed.ko && seed.ko !== seed.seed ? `${esc(seed.ko)}<small>${esc(seed.seed)}</small>` : esc(seed.seed));

  function open(ctx = {}) {
    close('replaced');
    ensureStyle();
    if (MINI_KINDS.some(item => item.kind === ctx.kind)) memo.kind = ctx.kind;
    const el = document.createElement('div');
    el.className = 'pmini';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', '프리셋 고르기');
    el.innerHTML = `<div class="pmini-head">
        ${MINI_KINDS.map(item => `<button type="button" class="pmini-tab" data-pm-kind="${item.kind}">${item.label}</button>`).join('')}
        <input class="pmini-q" data-pm-q type="text" autocomplete="off" spellcheck="false" placeholder="태그 · 한국어 이름 (Enter)">
        <button type="button" class="pmini-btn" data-pm-random title="지금 보이는 세트 중 하나를 넣습니다">무작위</button>
        <button type="button" class="pmini-btn" data-pm-close title="닫기 (Esc)">×</button>
      </div>
      <div class="pmini-body">
        <div class="pmini-col pmini-cats" data-pm-cats></div>
        <div class="pmini-col pmini-seeds" data-pm-seeds></div>
        <div class="pmini-grid-wrap" data-pm-grid></div>
      </div>`;
    document.body.appendChild(el);
    const vw = window.innerWidth, vh = window.innerHeight;
    const rect = el.getBoundingClientRect();
    const left = Number(ctx.left) || 8;
    const top = Number(ctx.top) || 8;
    el.style.left = `${Math.round(Math.max(8, Math.min(left, vw - rect.width - 8)))}px`;
    el.style.top = `${Math.round(Math.max(8, Math.min(top, vh - rect.height - 8)))}px`;
    const q = el.querySelector('[data-pm-q]');
    st = {el, ctx, q, shown: [], serial: 0};
    const onOutside = event => { if (st && !st.el.contains(event.target)) close('outside'); };
    st.onOutside = onOutside;
    // 엔트리를 연 그 클릭이 곧바로 닫지 않게 한 박자 뒤에 건다.
    window.setTimeout(() => { if (st?.onOutside === onOutside) document.addEventListener('pointerdown', onOutside, true); }, 0);
    el.addEventListener('keydown', onKey);
    el.addEventListener('click', onClick);
    const seed = String(ctx.seed || '').trim();
    if (seed) { q.value = seed; void runSearch(seed); } else void render();
    q.focus();
  }

  function close(reason = 'done') {
    const was = st;
    if (!was) return;
    st = null;
    document.removeEventListener('pointerdown', was.onOutside, true);
    was.el.remove();
    if (reason === 'esc' || reason === 'button') was.ctx.cancel?.();
  }

  function onKey(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close('esc');
      return;
    }
    if (event.key !== 'Enter') return;
    event.stopPropagation();                         // Ctrl+Enter 가 Generate 까지 누르지 않게
    if (event.target?.matches?.('[data-pm-q]')) {
      if (event.isComposing || event.keyCode === 229) return;
      event.preventDefault();
      void runSearch(st.q.value);
    }
  }

  function pick(set) {
    if (!st || !set) return;
    const text = setPromptText(set);
    if (!text) return;
    const ctx = st.ctx;
    close('done');
    const ok = typeof ctx.insert === 'function' ? ctx.insert(text) : false;
    if (!ok) showToast?.('프롬프트에 넣지 못했습니다 - 프롬프트 칸이 바뀌었을 수 있습니다', 'error');
  }

  function onClick(event) {
    if (!st) return;
    const t = event.target;
    if (t.closest('[data-pm-close]')) { close('button'); return; }
    const tab = t.closest('[data-pm-kind]');
    if (tab) {
      memo.kind = tab.dataset.pmKind;
      st.q.value = viewOf(memo.kind).q || '';
      void render();
      return;
    }
    if (t.closest('[data-pm-random]')) {
      const list = st.shown;
      if (list.length) pick(list[Math.floor(Math.random() * list.length)]);
      else showToast?.('고를 세트가 없습니다', 'error');
      return;
    }
    const card = t.closest('[data-pm-set]');
    if (card) { pick(st.shown.find(set => set.id === card.dataset.pmSet)); return; }
    const view = viewOf(memo.kind);
    const cat = t.closest('[data-pm-cat]');
    if (cat) {
      view.cat = cat.dataset.pmCat;
      view.sub = cat.dataset.pmSub || '';
      view.seed = '';
      view.hits = null;
      view.q = '';
      st.q.value = '';
      void render();
      return;
    }
    const seed = t.closest('[data-pm-seed]');
    if (seed) { view.seed = seed.dataset.pmSeed; void render(); }
  }

  async function runSearch(raw) {
    if (!st) return;
    const kind = memo.kind;
    const view = viewOf(kind);
    const text = String(raw || '').trim();
    view.q = text;
    view.seed = '';
    if (!text) { view.hits = null; await render(); return; }
    let rows = [];
    try { rows = await getJson(API.search(text, kind)); }
    catch (error) { showToast?.(`검색하지 못했습니다: ${error.message}`, 'error'); }
    if (!st || viewOf(kind).q !== text) return;
    // 따로 뺀 풀(남남 · 후타나리)은 빼고 찾는다 - 그 대분류를 열어 고른다(벤치와 같다).
    let apart = new Set();
    try { apart = new Set(((await catalogOf(kind)).groups || []).map(g => g.pool).filter(Boolean)); } catch (_) {}
    const bySeed = new Map();
    for (const row of Array.isArray(rows) ? rows : []) {
      if (apart.has(row.pool)) continue;
      const hit = bySeed.get(row.seed) || {seed: row.seed, ko: row.ko || '', count: 0};
      hit.count += 1;
      bySeed.set(row.seed, hit);
    }
    view.hits = [...bySeed.values()];
    await render();
  }

  async function render() {
    if (!st) return;
    const serial = ++st.serial;
    const kind = memo.kind;
    const view = viewOf(kind);
    const box = name => st.el.querySelector(`[data-pm-${name}]`);
    st.el.querySelectorAll('[data-pm-kind]').forEach(tab => tab.classList.toggle('is-on', tab.dataset.pmKind === kind));
    let catalog;
    try { catalog = await catalogOf(kind); }
    catch (error) {
      if (st && serial === st.serial) box('grid').innerHTML = `<div class="pmini-empty">목록을 읽지 못했습니다: ${esc(error.message)}</div>`;
      return;
    }
    if (!st || serial !== st.serial) return;
    const groups = catalog.groups || [];
    if (!groups.some(group => group.slot === view.cat)) { view.cat = groups[0]?.slot || ''; view.sub = ''; }
    const group = groups.find(item => item.slot === view.cat);
    if (view.sub && !(group?.subs || []).some(sub => sub.name === view.sub)) view.sub = '';
    const searching = Array.isArray(view.hits);
    box('cats').innerHTML = groups.map(item => {
      const on = !searching && item.slot === view.cat;
      const subs = on && (item.subs || []).length > 1
        ? item.subs.map(sub => `<div class="pmini-row${sub.name === view.sub ? ' is-on' : ''}" data-pm-cat="${esc(item.slot)}" data-pm-sub="${esc(sub.name)}" style="padding-left:14px"><span>${esc(sub.name)}</span><span>${setTotal(sub.seeds)}</span></div>`).join('')
        : '';
      return `<div class="pmini-row${on && !view.sub ? ' is-on' : ''}" data-pm-cat="${esc(item.slot)}"><span>${esc(item.label || item.slot)}</span><span>${setTotal(item.seeds)}</span></div>${subs}`;
    }).join('');

    const pool = searching ? '' : (group?.pool || '');
    let seeds;
    if (searching) {
      seeds = view.hits;
      box('seeds').innerHTML = seeds.length
        ? `<div class="pmini-sub">검색 '${esc(view.q)}' · ${seeds.length}</div>` + seeds.map(seed => `<div class="pmini-row${seed.seed === view.seed ? ' is-on' : ''}" data-pm-seed="${esc(seed.seed)}"><span>${seedName(seed)}</span><span>${seed.count}</span></div>`).join('')
        : `<div class="pmini-empty">'${esc(view.q)}' 결과 없음</div>`;
      if (!seeds.some(seed => seed.seed === view.seed)) view.seed = seeds[0]?.seed || '';
    } else {
      const sub = view.sub ? group.subs.find(item => item.name === view.sub) : null;
      seeds = sub ? sub.seeds : (group?.seeds || []);
      if (view.seed && !seeds.some(seed => seed.seed === view.seed)) view.seed = '';
      if (!view.seed) view.seed = seeds[0]?.seed || '';
      box('seeds').innerHTML = seeds.map(seed => `<div class="pmini-row${seed.seed === view.seed ? ' is-on' : ''}" data-pm-seed="${esc(seed.seed)}" title="${esc(seed.seed)}"><span>${seedName(seed)}</span><span>${seed.sets}</span></div>`).join('')
        || '<div class="pmini-empty">묶음이 없습니다</div>';
    }
    box('seeds').querySelectorAll('[data-pm-seed]').forEach(row => row.classList.toggle('is-on', row.dataset.pmSeed === view.seed));
    const grid = box('grid');
    if (!view.seed) { grid.innerHTML = ''; st.shown = []; return; }
    grid.innerHTML = '<div class="pmini-empty">불러오는 중…</div>';
    let sets;
    try { sets = await setsOf(kind, pool, view.seed); }
    catch (error) {
      if (st && serial === st.serial) grid.innerHTML = `<div class="pmini-empty">세트를 읽지 못했습니다: ${esc(error.message)}</div>`;
      return;
    }
    if (!st || serial !== st.serial) return;
    st.shown = sets;
    const info = siblingTags(sets);
    const common = sets.length > 1 ? new Set(info.common) : new Set();
    const cur = seeds.find(seed => seed.seed === view.seed);
    const title = cur?.ko && cur.ko !== view.seed ? `${cur.ko} ${view.seed}` : view.seed;
    const tall = kind === 'outfit' ? ' is-tall' : '';
    grid.innerHTML = `<div class="pmini-ctx">${esc(title)} · ${sets.length}세트${common.size ? ` · 공통: ${esc(info.common.join(', '))}` : ''} — 그림을 누르면 바로 넣습니다</div>`
      + (sets.length ? `<div class="pmini-grid">${sets.map(set => {
        const only = new Set(common.size ? info.distinct.get(set.id) || [] : []);
        const rest = (set.tags || []).filter(tag => !common.has(tag));
        const words = (rest.length ? rest : (set.tags || [])).map(tag => (only.has(tag) ? `<span class="pmini-u">${esc(tag)}</span>` : esc(tag))).join(', ');
        const picture = set.has_thumb
          ? `<img class="pmini-th${tall}" loading="lazy" src="${API.thumb(set.key)}" alt="">`
          : `<div class="pmini-th${tall} pmini-none">미생성</div>`;
        return `<div class="pmini-card" data-pm-set="${esc(set.id)}" title="${esc(setPromptText(set))}">${picture}<div class="pmini-cap">${words}</div></div>`;
      }).join('')}</div>` : '<div class="pmini-empty">세트가 없습니다</div>');
  }

  return {open, close: () => close('button'), isOpen: () => !!st};
}
