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
 * [A|B] = 검은 반투명 배경의 비교 팝업(사용자 지시 2026-10-26): A = 기준 GT · B = 변형 그림을 슬라이더로(UC 큰 값 -> GT -> POS)
 * + [POS -1 확인]. 변형 그림은 HF 지연 다운로드 묶음(약 300MB · /api/thumb/variants) - 없으면 B 자리에서 [받기].
 * [Bench] 는 다음 단계(TODO) - 지금은 알림만.
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
    const ab = event.target.closest('[data-thw-ab]');
    if (ab) void openAb(ab.dataset.thwAb);
  }

  // ── A|B 팝업 ──────────────────────────────────────────────────────────────
  // 슬라이더 칸 = UC(큰 값부터) · GT · POS 양수(작은 값부터). POS 음수(-1 / -0.5)는 슬라이더 밖 - [POS -1 확인] 단추.
  let ab = null;                      // {tag, data, steps, idx, neg, showNeg, el, poll, seq}
  let abSeq = 0;

  function abSteps(data) {
    const vs = data.variants || [];
    const uc = vs.filter(v => v.place === 'uc');
    const pos = vs.filter(v => v.place !== 'uc' && Number(v.weight) > 0);
    return [...uc, {col: '__gt__', label: 'GT', url: data.gt_url, gt: true}, ...pos];
  }

  function abClose() {
    if (!ab) return;
    if (ab.poll) clearInterval(ab.poll);
    ab.el.remove();
    doc.removeEventListener('keydown', abKey, true);
    ab = null;
  }

  function abKey(event) {
    if (!ab) return;
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); abClose(); return; }
    if (!ab.steps.length || ab.showNeg) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      event.stopPropagation();
      abSet(ab.idx + (event.key === 'ArrowLeft' ? -1 : 1));
    }
  }

  function abSet(idx) {
    if (!ab || !ab.steps.length) return;
    ab.idx = Math.max(0, Math.min(ab.steps.length - 1, idx));
    ab.showNeg = false;
    abPaintB();
  }

  function abPaintB() {
    const box = ab?.el;
    if (!box) return;
    const step = ab.showNeg ? ab.neg : ab.steps[ab.idx];
    const img = box.querySelector('[data-thw-ab-b]');
    if (img && step) img.src = step.url || '';
    const label = box.querySelector('[data-thw-ab-label]');
    if (label && step) label.textContent = step.label || step.col;
    const range = box.querySelector('[data-thw-ab-range]');
    if (range) { range.value = String(ab.idx); range.disabled = ab.showNeg; }
    const neg = box.querySelector('[data-thw-ab-neg]');
    if (neg) neg.classList.toggle('is-on', ab.showNeg);
    const prompt = box.querySelector('[data-thw-ab-prompt]');
    if (prompt && step) {
      const text = abPromptText(step);
      prompt.textContent = text;
      prompt.dataset.copy = step.gt ? '' : text.replace(/^(UC|프롬프트 맨 앞:|프롬프트) \+? ?/, '');
    }
  }

  /** B 그림이 실제로 어떻게 만들어졌는가 - 기준 프롬프트/UC 에 덧붙인 것만(사용자 지시 2026-10-26). */
  function abPromptText(step) {
    if (step.gt) return '태그 없음 (기준 그대로)';
    const w = String(Number(step.weight));
    if (step.place === 'uc') return `UC + ${w}::${ab.tag} ::`;
    if (step.place === 'front') return `프롬프트 맨 앞: ${ab.tag}`;
    return `프롬프트 + ${w}::${ab.tag} ::`;
  }

  function abBaseNote() {
    const info = state?.bases?.[ab?.base];
    return info ? `기준 ${info.name}: ${info.note}` : '';
  }

  function abFrame(tag, base) {
    const baseName = state?.bases?.[base]?.name || '';
    const el = doc.createElement('div');
    el.className = 'thw-ab-overlay';
    el.innerHTML = `<div class="thw-ab-box" role="dialog" aria-label="${escAttr(tag)} A|B">`
      + `<div class="thw-ab-head"><b>${escHtml(tag)}</b><span class="thw-ab-sub">A | B${baseName ? ` · 기준: ${escHtml(baseName)}` : ''}</span>`
      + `<button type="button" class="thw-ab-x" data-thw-ab-close aria-label="닫기">×</button></div>`
      + `<div class="thw-ab-body"><figure class="thw-ab-pane"><div class="thw-ab-img"><img data-thw-ab-a alt="A - GT"></div>`
      + `<figcaption>A · GT (태그 없음)</figcaption></figure>`
      + `<figure class="thw-ab-pane"><div class="thw-ab-img" data-thw-ab-stage></div><figcaption data-thw-ab-ctl></figcaption></figure></div></div>`;
    el.addEventListener('click', event => {
      if (event.target === el || event.target.closest('[data-thw-ab-close]')) { abClose(); return; }
      if (event.target.closest('[data-thw-ab-neg]') && ab?.neg) { ab.showNeg = !ab.showNeg; abPaintB(); return; }
      if (event.target.closest('[data-thw-ab-get]')) { void abDownload(); return; }
      const prompt = event.target.closest('[data-thw-ab-prompt]');
      if (prompt?.dataset.copy) void copyTag(prompt.dataset.copy);
    });
    el.addEventListener('input', event => {
      if (event.target.closest('[data-thw-ab-range]')) abSet(Number(event.target.value));
    });
    doc.body.appendChild(el);
    doc.addEventListener('keydown', abKey, true);
    return el;
  }

  function abPaint() {
    const box = ab?.el;
    if (!box) return;
    const data = ab.data || {};
    const gtFallback = state?.bases?.[ab.base]?.gt_url || '';
    const a = box.querySelector('[data-thw-ab-a]');
    if (a) a.src = data.ready && data.gt_url ? data.gt_url : gtFallback;
    const stage = box.querySelector('[data-thw-ab-stage]');
    const ctl = box.querySelector('[data-thw-ab-ctl]');
    if (!data.ready) {
      const dl = ab.dl || {};
      const pct = Math.max(0, Math.min(100, Number(dl.percent || 0)));
      const size = data.download?.approx_mb ? `약 ${Number(data.download.approx_mb).toLocaleString()}MB · ` : '';
      stage.innerHTML = `<div class="thw-ab-missing"><b>변형 그림 묶음이 필요합니다</b>`
        + `<span>${size}한 번만 받습니다. 받는 동안 창을 닫아도 계속 받습니다.</span>`
        + (dl.active ? `<div class="thw-ab-bar"><i style="width:${pct}%"></i></div><span>${pct}%</span>`
          : `<button type="button" class="thw-hb" data-thw-ab-get>받기</button>`)
        + (ab.dlError ? `<span class="thw-ab-err">${escHtml(ab.dlError)}</span>` : '') + `</div>`;
      ctl.textContent = 'B · 변형 그림';
      return;
    }
    stage.innerHTML = `<img data-thw-ab-b alt="B">`;
    const last = ab.steps.length - 1;
    ctl.innerHTML = `<div class="thw-ab-ctl"><span class="thw-ab-end">${escHtml(ab.steps[0]?.label || '')}</span>`
      + `<input type="range" min="0" max="${last}" step="1" data-thw-ab-range>`
      + `<span class="thw-ab-end">${escHtml(ab.steps[last]?.label || '')}</span></div>`
      + `<div class="thw-ab-ctl"><b data-thw-ab-label></b>`
      + `<code class="thw-ab-prompt" data-thw-ab-prompt data-naia-title="${escAttr(abBaseNote())} · 누르면 복사"></code>`
      + (ab.neg ? `<button type="button" class="thw-hb" data-thw-ab-neg data-naia-title="프롬프트에 ${escAttr(ab.neg.label)} (음수 가중치) - 한 번 더 누르면 슬라이더로">${escHtml(ab.neg.label)} 확인</button>` : '')
      + `</div>`;
    abPaintB();
  }

  async function abFetch() {
    const mine = ab.seq;
    const response = await fetch(`/api/thumb/variants?tag=${encodeURIComponent(ab.tag)}`, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
    if (!ab || ab.seq !== mine) return;
    ab.data = data;
    ab.base = data.base || ab.base;
    ab.steps = data.ready ? abSteps(data) : [];
    ab.neg = data.ready ? (data.variants || []).find(v => v.place === 'pos' && Number(v.weight) < 0) || null : null;
    const p1 = ab.steps.findIndex(v => v.place === 'pos' && Number(v.weight) === 1);
    ab.idx = p1 >= 0 ? p1 : Math.max(0, ab.steps.length - 1);
    ab.showNeg = false;
    abPaint();
  }

  async function openAb(tag) {
    abClose();
    const base = cache.get(active)?.base || '';
    ab = {tag, base, data: null, steps: [], idx: 0, neg: null, showNeg: false, el: null, poll: 0, seq: ++abSeq, dl: null, dlError: ''};
    ab.el = abFrame(tag, base);
    ab.el.querySelector('[data-thw-ab-stage]').innerHTML = '<div class="thw-ab-missing"><span>불러오는 중…</span></div>';
    const a = ab.el.querySelector('[data-thw-ab-a]');
    if (a) a.src = state?.bases?.[base]?.gt_url || '';
    try {
      await abFetch();
      if (ab && !ab.data?.ready) void abPollInstall(false);
    } catch (error) {
      if (ab) ab.el.querySelector('[data-thw-ab-stage]').innerHTML = `<div class="thw-ab-missing"><span class="thw-ab-err">${escHtml(error.message || '불러오지 못했습니다')}</span></div>`;
    }
  }

  // 묶음 받기 - 이벤트 맵과 같은 설치 관리자(루프백만 시작할 수 있다 · 단일 비행).
  async function abInstallState() {
    const response = await fetch('/api/install-manager', {cache: 'no-store'});
    const snap = await response.json().catch(() => ({}));
    const info = snap.style_variants || {};
    const dl = info.download || {};
    const mine = String(dl.phase || '') === 'style_variants';
    return {ready: !!info.ready, active: !!(mine && dl.active), percent: mine ? dl.percent : 0, error: mine ? dl.error : ''};
  }

  async function abPollInstall(force) {
    if (!ab) return;
    if (ab.poll && !force) return;
    if (ab.poll) clearInterval(ab.poll);
    const tick = async () => {
      if (!ab) return;
      try {
        const st = await abInstallState();
        if (!ab) return;
        ab.dl = st;
        if (st.error) ab.dlError = `받지 못했습니다 - ${st.error}`;
        if (st.ready) { clearInterval(ab.poll); ab.poll = 0; ab.dlError = ''; await abFetch(); return; }
        if (!st.active && !force) { clearInterval(ab.poll); ab.poll = 0; }
        abPaint();
      } catch (_) { /* 다음 틱에 다시 */ }
    };
    ab.poll = setInterval(tick, 1500);
    await tick();
  }

  async function abDownload() {
    if (!ab) return;
    ab.dlError = '';
    try {
      const response = await fetch('/api/install-manager/style-variants/download', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    } catch (error) {
      ab.dlError = error.message || '받기를 시작하지 못했습니다';
      abPaint();
      return;
    }
    await abPollInstall(true);
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
