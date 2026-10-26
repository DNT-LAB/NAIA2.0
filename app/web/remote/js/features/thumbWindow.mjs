/**
 * Thumb 창 - 오른쪽 탭 [Thumb] 을 누르면 뜨는 떠 있는 창(사용자 결정 2026-10-26 · Characters 창과 같은 탭 규칙).
 *
 *   머리줄: [태그 검색] [Bench]
 *   [ 분류 목록 | 소제목별 카드 격자 ]
 *   카드 = POS 1 썸네일 · 태그(누르면 프롬프트에 넣기 · 우클릭 = 복사) · [A|B]
 *
 * 데이터 = /api/thumb/state · /api/thumb/category/<key> (data/taglist/style_meta_tags.json v3 - 2026-10-26 생성 실험).
 * 분류마다 생성 기준(base: 프리셋 / 맨바탕)이 다르다 - 상태 줄에 그 기준을 적는다.
 * 'Novel AI 공식' 은 이 페이지에서 창을 처음 열 때 늘 맨 먼저 보인다(서버의 selected · 사용자 지시) - 그 뒤로는 이 세션에서
 * 마지막에 본 분류(메모리만 - 저장하지 않는다).
 * [Bench] · [A|B] 는 다음 단계(TODO) - 지금은 알림만.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

export function createThumbWindow({
  document: doc = document,
  window: win = window,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
  promptEdit = null,                  // 메인 프롬프트 칸 - 태그를 커서 자리에 넣는다
  onPromptEdit = null,                // 넣은 뒤 부른다(작성 편집 알림)
} = {}) {
  let panel = null;
  let state = null;                   // /api/thumb/state
  let statePromise = null;
  let active = '';                    // 지금 분류 키
  const cache = new Map();            // 분류 키 -> 분류 응답
  let seq = 0;
  const escAttr = value => escHtml(String(value ?? '')).replace(/"/g, '&quot;');

  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win,
      title: 'Thumb',
      variant: 'thw',
      storageKey: 'thumb-window',
      width: 760, height: 620, minWidth: 460, minHeight: 320, maxWidth: 1600,
      resizable: true, collapsible: true,
      initial: {right: 24, y: 80},
      escHtml,
    });
    panel.slot.innerHTML = `<input class="thw-q" type="search" data-thw-q placeholder="태그 검색" spellcheck="false" autocomplete="off">`
      + `<button type="button" class="thw-hb" data-thw-bench data-naia-title="Bench 모드 - 고정된 GT 와 캐릭터 프롬프트로 프롬프트를 깎는 화면(준비 중)">Bench</button>`;
    panel.body.innerHTML = `<div class="thw">`
      + `<nav class="thw-cats" data-thw-cats aria-label="스타일 분류"></nav>`
      + `<section class="thw-main"><div class="thw-status" data-thw-status>불러오는 중…</div>`
      + `<div class="thw-grid" data-thw-grid></div></section></div>`;
    panel.slot.addEventListener('input', event => { if (event.target.closest('[data-thw-q]')) paintGrid(); });
    panel.slot.addEventListener('click', event => {
      if (event.target.closest('[data-thw-bench]')) showToast('Bench 모드는 준비 중입니다', 'info');
    });
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('contextmenu', onContextMenu);
    return panel;
  }

  const el = sel => panel?.el.querySelector(sel);
  const query = () => String(el('[data-thw-q]')?.value || '').trim().toLowerCase();

  // ── 서버 ──────────────────────────────────────────────────────────────────
  async function loadState() {
    if (state) return state;
    if (!statePromise) {
      statePromise = fetch('/api/thumb/state', {cache: 'no-store'})
        .then(async response => {
          const data = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
          state = data;
          if (!active) active = data.selected || data.categories?.[0]?.key || '';
          return data;
        })
        .catch(error => { statePromise = null; throw error; });
    }
    return statePromise;
  }

  async function loadCategory(key) {
    if (cache.has(key)) return cache.get(key);
    const response = await fetch(`/api/thumb/category/${encodeURIComponent(key)}`, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    cache.set(key, data);
    return data;
  }

  // ── 그리기 ────────────────────────────────────────────────────────────────
  function setStatus(text, tone = '') {
    const node = el('[data-thw-status]');
    if (!node) return;
    node.textContent = text;
    if (tone) node.dataset.tone = tone; else delete node.dataset.tone;
  }

  function paintCats() {
    const nav = el('[data-thw-cats]');
    if (!nav || !state) return;
    nav.innerHTML = (state.categories || []).map(cat => `<button type="button" class="thw-cat${cat.key === active ? ' is-on' : ''}"`
      + ` data-thw-cat="${escAttr(cat.key)}" data-naia-title="${escAttr(cat.description || cat.name)}">`
      + `<span>${escHtml(cat.name)}</span><span class="thw-n">${Number(cat.available || 0)}</span></button>`).join('');
  }

  function card(tag, url, single) {
    return `<article class="thw-card" data-thw-tag="${escAttr(tag)}">`
      + `<img loading="lazy" decoding="async" src="${escAttr(url)}" alt="${escAttr(tag)}">`
      + `<div class="thw-ft"><button type="button" class="thw-tag" data-thw-insert="${escAttr(tag)}"`
      + ` data-naia-title="누르면 프롬프트에 넣습니다 · 우클릭 = 복사">${escHtml(tag)}</button>`
      + (single ? `<span class="thw-single" data-naia-title="가중치 없이 한 장만 뽑은 태그입니다">단일</span>`
        : `<button type="button" class="thw-ab" data-thw-ab="${escAttr(tag)}" data-naia-title="GT 와 나란히 비교(준비 중)">A|B</button>`)
      + `</div></article>`;
  }

  function paintGrid() {
    const grid = el('[data-thw-grid]');
    const data = cache.get(active);
    if (!grid || !data) return;
    const q = query();
    const urls = new Map((data.tags || []).map(item => [item.tag, item.image_url]));
    const match = tag => !q || tag.toLowerCase().includes(q);
    // 소제목이 있는 분류(Novel AI 공식)는 묶음별로, 없으면 한 덩어리로.
    const groups = data.sections?.length
      ? data.sections.map(sec => ({name: sec.name, single: sec.single, tags: sec.tags}))
      : [{name: '', single: false, tags: (data.tags || []).map(item => item.tag)}];
    let shown = 0;
    grid.innerHTML = groups.map(group => {
      const tags = group.tags.filter(match);
      shown += tags.length;
      if (!tags.length) return '';
      const head = group.name ? `<div class="thw-sec">${escHtml(group.name)} · ${tags.length}</div>` : '';
      return head + `<div class="thw-cards">${tags.map(tag => card(tag, urls.get(tag) || '', group.single)).join('')}</div>`;
    }).join('') || `<div class="thw-empty">맞는 태그가 없습니다</div>`;
    const base = state?.bases?.[data.base]?.name;
    setStatus(`${data.name} · ${shown}${q ? ` / ${(data.tags || []).length}` : ''}개${base ? ` · 기준: ${base}` : ''}`);
  }

  async function select(key) {
    if (!key) return;
    active = key;
    paintCats();
    const mine = ++seq;
    if (!cache.has(key)) setStatus('불러오는 중…', 'busy');
    try {
      await loadCategory(key);
      if (mine !== seq) return;
      paintGrid();
      const grid = el('[data-thw-grid]');
      if (grid) grid.scrollTop = 0;
    } catch (error) {
      if (mine !== seq) return;
      setStatus(error.message || '불러오지 못했습니다', 'error');
    }
  }

  // ── 동작 ──────────────────────────────────────────────────────────────────
  function insertTag(tag) {
    const target = promptEdit;
    if (!target || !tag) return false;
    const text = target.value || '';
    const start = target.selectionStart != null ? target.selectionStart : text.length;
    const end = target.selectionEnd != null ? target.selectionEnd : start;
    const before = text.substring(0, start);
    const after = text.substring(end);
    const prefix = before.trim() ? (/[,\s]$/.test(before) ? '' : ', ') : '';
    const insert = `${prefix}${tag}, `;
    target.value = before + insert + after;
    target.selectionStart = target.selectionEnd = before.length + insert.length;
    if (onPromptEdit) onPromptEdit();
    return true;
  }

  async function copyTag(tag) {
    try {
      await win.navigator.clipboard.writeText(tag);
      showToast(`복사했습니다: ${tag}`, 'success');
    } catch (_) {
      showToast('복사하지 못했습니다', 'error');
    }
  }

  function onClick(event) {
    const cat = event.target.closest('[data-thw-cat]');
    if (cat) { void select(cat.dataset.thwCat); return; }
    const insert = event.target.closest('[data-thw-insert]');
    if (insert) {
      if (insertTag(insert.dataset.thwInsert)) showToast(`넣었습니다: ${insert.dataset.thwInsert}`, 'success');
      return;
    }
    if (event.target.closest('[data-thw-ab]')) showToast('A|B 비교는 준비 중입니다', 'info');
  }

  function onContextMenu(event) {
    const tagEl = event.target.closest('[data-thw-tag]');
    if (!tagEl) return;
    event.preventDefault();
    void copyTag(tagEl.dataset.thwTag);
  }

  // ── 바깥 ──────────────────────────────────────────────────────────────────
  async function open() {
    ensurePanel();
    if (panel.isOpen()) panel.raise(); else panel.open();
    if (panel.isCollapsed && panel.isCollapsed()) panel.expand();
    try {
      await loadState();
      paintCats();
      await select(active);
    } catch (error) {
      setStatus(error.message || '불러오지 못했습니다', 'error');
      showToast(error.message || 'Thumb 을 불러오지 못했습니다', 'error');
    }
  }

  return {
    open,
    /** 탭 단추 규칙(Characters · Artist 와 같다) - 창을 세웠으면 false(탭으로 가지 않는다), 이미 펴져 있으면 true(탭으로). */
    requestTab() {
      if (!panel || !panel.isOpen() || (panel.isCollapsed && panel.isCollapsed())) { void open(); return false; }
      return true;
    },
    isOpen: () => !!(panel && panel.isOpen()),
  };
}
