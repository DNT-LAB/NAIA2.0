/**
 * Thumb 창 - 오른쪽 탭 [Thumb] 을 누르면 뜨는 떠 있는 창(사용자 결정 2026-10-26). [Thumb] 은 창을 띄우거나 앞으로 가져오기만 한다 -
 * 옛 Thumb 탭 화면으로는 가지 않는다(Bench 모드는 만들지 않기로 했다 · 사용자 결정 2026-10-26).
 *
 *   머리줄: [태그 검색]
 *   [ 분류 목록 | 소제목별 카드 격자 ]
 *   카드 = POS 1 썸네일(마우스를 올리면 큰 그림 세 장 UC 2.5(없으면 UC 1) | GT | POS +1 을 카드 위/아래에) · 이름(누르면 복사 · 툴팁 = 전체 이름 ·
 *   우클릭 = 복사) · [A|B]
 *
 * 데이터 = /api/thumb/state · /api/thumb/category/<key> (data/taglist/style_meta_tags.json v3 - 2026-10-26 생성 실험).
 * 분류마다 생성 기준(base: 프리셋 / 맨바탕)이 다르다 - 상태 줄에 그 기준을 적는다.
 * 'Novel AI 공식' 은 이 페이지에서 창을 처음 열 때 늘 맨 먼저 보인다(서버의 selected · 사용자 지시) - 그 뒤로는 이 세션에서
 * 마지막에 본 분류(메모리만 - 저장하지 않는다).
 * [A|B] = 검은 반투명 배경의 비교 팝업(사용자 지시 2026-10-26): A = 기준 GT · B = 변형 그림을 단추 줄로
 * (빼기 붉은 계열 = UC · 그 줄 끝에 POS 음수 파란 계열 / 넣기 연두 계열 = POS 양수 · GT 는 A 에 있으니 생략 · 마우스를 올려도 바뀐다). 변형 그림은 HF 지연 다운로드 묶음(약 300MB · /api/thumb/variants) - 없으면 B 자리에서 [받기].
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

export function createThumbWindow({
  document: doc = document,
  window: win = window,
  escHtml = value => String(value ?? ''),
  showToast = () => {},
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
      // 처음 크기 = 한 줄에 카드 3장(사용자 지시 2026-10-26) - 분류 목록 150 + 격자 약 420(카드 최소 128 · 간격 7).
      width: 600, height: 620, minWidth: 460, minHeight: 320, maxWidth: 1600,
      resizable: true, collapsible: true,
      initial: {right: 24, y: 80},
      escHtml,
    });
    panel.slot.innerHTML = `<input class="thw-q" type="search" data-thw-q placeholder="태그 검색" spellcheck="false" autocomplete="off">`;
    panel.body.innerHTML = `<div class="thw">`
      + `<nav class="thw-cats" data-thw-cats aria-label="스타일 분류"></nav>`
      + `<section class="thw-main"><div class="thw-status" data-thw-status>불러오는 중…</div>`
      + `<div class="thw-grid" data-thw-grid></div></section></div>`;
    panel.slot.addEventListener('input', event => { if (event.target.closest('[data-thw-q]')) paintGrid(); });
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('contextmenu', onContextMenu);
    panel.body.addEventListener('mouseover', onPeekOver);
    panel.body.addEventListener('mouseout', onPeekOut);
    panel.body.addEventListener('scroll', hidePeek, true);
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
      // 그림 = 마우스를 올리면 큰 그림 세 장(-1 | 0 | 1) · 이름 = 복사(툴팁에 전체 이름) - 사용자 지시 2026-10-26.
      + `<img loading="lazy" decoding="async" src="${escAttr(url)}" alt="${escAttr(tag)}" data-thw-peek="${escAttr(tag)}"`
      + `${single ? ' data-thw-single="1"' : ''}>`
      + `<div class="thw-ft"><button type="button" class="thw-tag" data-thw-copy="${escAttr(tag)}"`
      + ` data-naia-title="${escAttr(tag)} · 누르면 복사">${escHtml(tag)}</button>`
      + (single ? `<span class="thw-single" data-naia-title="가중치 없이 한 장만 뽑은 태그입니다">단일</span>`
        : `<button type="button" class="thw-ab" data-thw-ab="${escAttr(tag)}" data-naia-title="GT 와 나란히 비교">A|B</button>`)
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
    hidePeek();
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
    const copy = event.target.closest('[data-thw-copy]');
    if (copy) { void copyTag(copy.dataset.thwCopy); return; }
    const ab = event.target.closest('[data-thw-ab]');
    if (ab) void openAb(ab.dataset.thwAb);
  }

  // ── 큰 그림 세 장(마우스를 올리면) ─────────────────────────────────────────
  // 빼기 쪽(UC 2.5 · 없으면 UC 1) | GT | POS +1 을 나란히 - 카드가 화면 아래쪽이면 카드 위에, 위쪽이면 아래에(사용자 지시 2026-10-26).
  // GT · POS 1 은 번들 썸네일, 빼기 칸은 변형 묶음(없으면 '묶음 필요'). 데이터셋(단일)은 GT | 그 그림 두 장.
  const variantCache = new Map();     // tag -> /api/thumb/variants 응답(Promise)
  let peekEl = null;
  let peekTimer = 0;
  let peekTag = '';

  function variantsOf(tag) {
    if (!variantCache.has(tag)) {
      variantCache.set(tag, fetch(`/api/thumb/variants?tag=${encodeURIComponent(tag)}`, {cache: 'no-store'})
        .then(r => (r.ok ? r.json() : null)).catch(() => null)
        // 실패 · 묶음 없음은 남기지 않는다 - 다음에 올리면 다시 묻는다(그 사이 받았을 수 있다).
        .then(data => { if (!data?.ready) variantCache.delete(tag); return data; }));
    }
    return variantCache.get(tag);
  }

  function hidePeek() {
    clearTimeout(peekTimer);
    peekTag = '';
    if (peekEl) { peekEl.hidden = true; peekEl.dataset.tag = ''; }
  }

  function onPeekOut(event) {
    const img = event.target.closest?.('[data-thw-peek]');
    if (img && !img.contains(event.relatedTarget)) hidePeek();
  }

  function onPeekOver(event) {
    const img = event.target.closest?.('[data-thw-peek]');
    if (!img || img.dataset.thwPeek === peekTag) return;
    clearTimeout(peekTimer);
    // 격자 위를 훑고 지나갈 때 깜빡이지 않게 잠깐 머문 뒤에 띄운다.
    peekTimer = setTimeout(() => void showPeek(img), 140);
  }

  function peekCell(src, label, note = '') {
    return `<figure class="thw-peek-cell"><div class="thw-peek-img">`
      + (src ? `<img src="${escAttr(src)}" alt="${escAttr(label)}">` : `<span>${escHtml(note || '없음')}</span>`)
      + `</div><figcaption>${escHtml(label)}</figcaption></figure>`;
  }

  async function showPeek(img) {
    const tag = img.dataset.thwPeek;
    peekTag = tag;
    const data = cache.get(active);
    const base = data?.base || '';
    const gt = state?.bases?.[base]?.gt_url || '';
    const pos1 = img.getAttribute('src') || '';
    // 빼기 그림은 번들에 있다(2026-10-26 - 상하좌우 10% 를 미리 잘라 구운 UC 2.5 · 없으면 UC 1). 그러면 묶음을 묻지 않는다.
    const item = (data?.tags || []).find(row => row.tag === tag);
    const bundled = item?.minus_url ? {url: item.minus_url, label: item.minus_label || '빼기'} : null;
    if (!peekEl) {
      peekEl = doc.createElement('div');
      peekEl.className = 'thw-peek';
      peekEl.hidden = true;
      doc.body.appendChild(peekEl);
    }
    // 어떤 태그를 그렸는지는 미리보기 자신에 적는다 - 응답을 기다리는 사이 스크롤 등으로 peekTag 가 지워져도
    // 미리보기가 그 태그로 떠 있으면 다시 그린다(처음 한 번 -1 칸이 '묶음 필요' 로 남던 것).
    const paint = variants => {
      if (variants && (peekEl.hidden || peekEl.dataset.tag !== tag)) return;
      peekEl.dataset.tag = tag;
      let cells;
      if (img.dataset.thwSingle) {
        cells = peekCell(gt, 'GT (태그 없음)') + peekCell(pos1, `${tag} (맨 앞)`);
      } else {
        // 왼쪽 칸 = 빼기 쪽(사용자 지시 2026-10-26 - 태그마다 가중치 범위가 다르다): UC 2.5 가 있으면 그것,
        // 없으면 UC 1(복잡도처럼 UC 가 1 까지인 태그), 그것도 없으면 POS 음수. POS -1 은 [A|B] 에서 본다.
        const vs = variants?.ready ? variants.variants || [] : [];
        const uc = w => vs.find(v => v.place === 'uc' && Number(v.weight) === w);
        const neg = bundled || uc(2.5) || uc(1) || vs.find(v => v.place === 'pos' && Number(v.weight) < 0) || null;
        // 응답 전(variants === null)은 '불러오는 중' - 서버가 막 켜졌으면 묶음 색인에 1~2초 걸린다.
        const note = variants === null ? '불러오는 중…' : variants?.ready ? '없음' : '변형 묶음 필요 ([A|B] 에서 받기)';
        cells = peekCell(neg?.url || '', neg ? neg.label : '빼기', note)
          + peekCell(gt, 'GT (0)') + peekCell(pos1, 'POS +1');
      }
      // 머리줄 = 태그 이름 + 설명(자동완성과 같은 출처 · Novel AI 공식 · 시대/연대는 설명 없음 - 사용자 지시 2026-10-26).
      const desc = item?.desc ? `<span class="thw-peek-desc">${escHtml(item.desc)}</span>` : '';
      peekEl.innerHTML = `<div class="thw-peek-head"><b>${escHtml(tag)}</b>${desc}</div><div class="thw-peek-row">${cells}</div>`;
      peekEl.hidden = false;
      placePeek(img);
    };
    paint(null);
    if (!img.dataset.thwSingle && !bundled) paint((await variantsOf(tag)) || {ready: false});   // 실패도 '응답 옴' 으로 그린다
  }

  function placePeek(img) {
    const r = img.getBoundingClientRect();
    const vw = win.innerWidth, vh = win.innerHeight;
    const w = peekEl.offsetWidth, h = peekEl.offsetHeight;
    const left = Math.max(8, Math.min(vw - w - 8, r.left + r.width / 2 - w / 2));
    // 카드가 화면 아래쪽이면 위에, 위쪽이면 아래에 - 그래도 넘치면 화면 안으로 민다.
    let top = r.top + r.height / 2 > vh / 2 ? r.top - h - 8 : r.bottom + 8;
    top = Math.max(8, Math.min(vh - h - 8, top));
    peekEl.style.left = `${Math.round(left)}px`;
    peekEl.style.top = `${Math.round(top)}px`;
  }

  // ── A|B 팝업 ──────────────────────────────────────────────────────────────
  // B 는 단추 줄로 고른다(사용자 지시 2026-10-26 - 슬라이더가 불편했다). GT 는 A 에 있으니 뺀다.
  // 첫 줄 = 빼기(붉은 계열 · UC 큰 값부터) ……… 맨 끝에 POS 음수(파란 계열) / 둘째 줄 = 넣기(연두 계열 · POS 양수 작은 값부터).
  // 누르거나 마우스를 올리면 B 가 바뀐다 · 좌우 화살표로도 옮긴다.
  let ab = null;                      // 지금 팝업 {tag, base, data, steps, idx, el, poll, seq, dl, dlError}
  let abSeq = 0;

  function abSteps(data) {
    const vs = data.variants || [];
    const minus = vs.filter(v => v.place === 'uc');
    const neg = vs.filter(v => v.place === 'pos' && Number(v.weight) < 0);
    const plus = vs.filter(v => v.place !== 'uc' && Number(v.weight) > 0);
    return [...minus.map(v => ({...v, side: 'minus'})), ...neg.map(v => ({...v, side: 'neg'})),
      ...plus.map(v => ({...v, side: 'plus'}))];
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
    if (!ab.steps.length) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      event.stopPropagation();
      abSet(ab.idx + (event.key === 'ArrowLeft' ? -1 : 1));
    }
  }

  function abSet(idx) {
    if (!ab || !ab.steps.length) return;
    ab.idx = Math.max(0, Math.min(ab.steps.length - 1, idx));
    abPaintB();
  }

  function abPaintB() {
    const box = ab?.el;
    if (!box) return;
    const step = ab.steps[ab.idx];
    const img = box.querySelector('[data-thw-ab-b]');
    if (img && step) img.src = step.url || '';
    const label = box.querySelector('[data-thw-ab-label]');
    if (label && step) label.textContent = step.label || step.col;
    box.querySelectorAll('[data-thw-ab-step]').forEach(btn => btn.classList.toggle('is-on', Number(btn.dataset.thwAbStep) === ab.idx));
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
    // 단추에 마우스를 올려도 B 를 바꾼다(사용자 지시 2026-10-26).
    el.addEventListener('mouseover', event => {
      const stepBtn = event.target.closest('[data-thw-ab-step]');
      if (stepBtn && ab && Number(stepBtn.dataset.thwAbStep) !== ab.idx) abSet(Number(stepBtn.dataset.thwAbStep));
    });
    el.addEventListener('click', event => {
      if (event.target === el || event.target.closest('[data-thw-ab-close]')) { abClose(); return; }
      const stepBtn = event.target.closest('[data-thw-ab-step]');
      if (stepBtn) { abSet(Number(stepBtn.dataset.thwAbStep)); return; }
      if (event.target.closest('[data-thw-ab-get]')) { void abDownload(); return; }
      const prompt = event.target.closest('[data-thw-ab-prompt]');
      if (prompt?.dataset.copy) void copyTag(prompt.dataset.copy);
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
    if (a) {
      const fromPack = !!(data.ready && data.gt_url);
      a.src = fromPack ? data.gt_url : gtFallback;
      a.toggleAttribute('data-precropped', !fromPack);      // 번들 GT 는 미리 잘렸다 - 7% 를 또 자르지 않는다
    }
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
    const btn = (step, i) => `<button type="button" class="thw-ab-v is-${step.side}" data-thw-ab-step="${i}"`
      + ` data-naia-title="${escAttr(abPromptText(step))}">${escHtml(step.label || step.col)}</button>`;
    const side = name => ab.steps.map((step, i) => [step, i]).filter(([step]) => step.side === name)
      .map(([step, i]) => btn(step, i)).join('');
    ctl.innerHTML = `<div class="thw-ab-btns">${side('minus')}${side('neg')}</div>`
      + `<div class="thw-ab-btns">${side('plus')}</div>`
      + `<div class="thw-ab-ctl"><b data-thw-ab-label></b>`
      + `<code class="thw-ab-prompt" data-thw-ab-prompt data-naia-title="${escAttr(abBaseNote())} · 누르면 복사"></code></div>`;
    abPaintB();
  }

  // ⚠️ 비동기 일은 시작할 때의 팝업(pop)을 붙잡고, 끝났을 때 그 팝업이 아직 지금 팝업인지(ab === pop) 본다 -
  // 다른 태그로 바꿔 연 뒤 옛 응답이 새 팝업을 덮거나 새 폴링을 끊던 것(Codex 리뷰 2026-10-26 #1). 폴링 타이머도 그 팝업이 가진다.
  async function abFetch(pop) {
    const response = await fetch(`/api/thumb/variants?tag=${encodeURIComponent(pop.tag)}`, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || data.detail || `HTTP ${response.status}`);
    if (ab !== pop) return;
    pop.data = data;
    pop.base = data.base || pop.base;
    pop.steps = data.ready ? abSteps(data) : [];
    const p1 = pop.steps.findIndex(v => v.place === 'pos' && Number(v.weight) === 1);
    pop.idx = p1 >= 0 ? p1 : Math.max(0, pop.steps.length - 1);
    abPaint();
  }

  async function openAb(tag) {
    hidePeek();
    abClose();
    const base = cache.get(active)?.base || '';
    const pop = {tag, base, data: null, steps: [], idx: 0, el: null, poll: 0, seq: ++abSeq, dl: null, dlError: ''};
    ab = pop;
    pop.el = abFrame(tag, base);
    pop.el.querySelector('[data-thw-ab-stage]').innerHTML = '<div class="thw-ab-missing"><span>불러오는 중…</span></div>';
    const a = pop.el.querySelector('[data-thw-ab-a]');
    if (a) { a.src = state?.bases?.[base]?.gt_url || ''; a.setAttribute('data-precropped', ''); }
    try {
      await abFetch(pop);
      if (ab === pop && !pop.data?.ready) void abPollInstall(pop, false);
    } catch (error) {
      if (ab === pop) {
        pop.el.querySelector('[data-thw-ab-stage]').innerHTML = `<div class="thw-ab-missing"><span class="thw-ab-err">${escHtml(error.message || '불러오지 못했습니다')}</span></div>`;
      }
    }
  }

  // 묶음 받기 - 이벤트 맵과 같은 설치 관리자(루프백만 시작할 수 있다 · 단일 비행).
  // 조회 실패(HTTP 오류 · JSON 아님 · 항목 없음)는 던진다 - 빈 응답을 '쉬는 중' 으로 읽어 받는 중에 폴링을 끊었다(재리뷰 N2).
  async function abInstallState() {
    const response = await fetch('/api/install-manager', {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const snap = await response.json();
    const info = snap?.style_variants;
    if (!info || typeof info !== 'object') throw new Error('설치 상태 없음');
    const dl = info.download || {};
    const mine = String(dl.phase || '') === 'style_variants';
    return {ready: !!info.ready, active: !!(mine && dl.active), percent: mine ? dl.percent : 0, error: mine ? dl.error : ''};
  }

  /** 설치 상태를 본다. afterStart = [받기] 를 막 눌렀다 - 받기가 시작될 때까지 몇 번 기다려 준다.
   *  받는 중이 아니게 되면(끝 · 실패 · 취소) 멈춘다(Codex 리뷰 #5: 실패해도 팝업을 닫을 때까지 1.5초마다 계속 물었다).
   *  틱은 겹치지 않는다(응답이 늦으면 다음 틱을 건너뛴다).
   *  조회가 실패하면 마지막 상태를 그대로 두고 다시 묻는다 - 연달아 MAX_FAILS 번 실패할 때만 멈춘다(재리뷰 N2).
   *  다 받았으면 그림 목록을 받아 온 뒤에 멈춘다 - 목록 조회가 실패하면 다음 틱에 다시(재리뷰 A1: 먼저 멈춰서 99% 에 섰다). */
  async function abPollInstall(pop, afterStart) {
    if (ab !== pop) return;
    if (pop.poll) clearInterval(pop.poll);
    let busy = false;
    let waits = afterStart ? 5 : 0;           // 받기 시작 전 '쉬는 중' 으로 보이는 틱을 몇 번까지 봐준다
    let sawActive = false;
    let fails = 0;
    const MAX_FAILS = 20;                     // 1.5초 x 20 = 30초 동안 한 번도 못 물으면 멈춘다
    const stop = () => { clearInterval(timer); if (pop.poll === timer) pop.poll = 0; };
    const tick = async () => {
      if (ab !== pop) { stop(); return; }
      if (busy) return;
      busy = true;
      try {
        const st = await abInstallState();
        if (ab !== pop) { stop(); return; }
        if (st.ready) {
          await abFetch(pop);                 // 실패하면 catch 로 - 타이머는 살아 있어 다음 틱에 다시
          if (ab === pop) { stop(); pop.dlError = ''; abPaint(); }
          return;
        }
        fails = 0;
        pop.dl = st;
        if (st.error) pop.dlError = `받지 못했습니다 - ${st.error}`;
        if (st.active) sawActive = true;
        else if (st.error || sawActive || waits-- <= 0) stop();
        abPaint();
      } catch (_) {
        if (ab !== pop) { stop(); return; }
        if (++fails >= MAX_FAILS) {
          stop();
          pop.dlError = '받기 상태를 확인하지 못했습니다 - 창을 다시 열어 주세요';
          abPaint();
        }
      } finally { busy = false; }
    };
    const timer = setInterval(tick, 1500);
    pop.poll = timer;
    await tick();
  }

  async function abDownload() {
    const pop = ab;
    if (!pop) return;
    pop.dlError = '';
    try {
      const response = await fetch('/api/install-manager/style-variants/download', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    } catch (error) {
      if (ab !== pop) return;                 // 그 사이 닫았거나 다른 팝업을 열었다
      pop.dlError = error.message || '받기를 시작하지 못했습니다';
      abPaint();
      return;
    }
    await abPollInstall(pop, true);
  }

  function onContextMenu(event) {
    const tagEl = event.target.closest('[data-thw-tag]');
    if (!tagEl) return;
    event.preventDefault();
    void copyTag(tagEl.dataset.thwTag);
  }

  // ── 바깥 ──────────────────────────────────────────────────────────────────
  let rendered = false;                // 첫 분류를 한 번 그렸다 - 그 뒤 [Thumb] 은 창을 앞으로만(다시 그리지 않는다)

  async function open() {
    ensurePanel();
    if (panel.isOpen()) panel.raise(); else panel.open();
    if (panel.isCollapsed && panel.isCollapsed()) panel.expand();
    // 이미 그려 둔 창(닫았다 다시 연 경우 포함)은 내용 · 스크롤을 그대로 둔다(Codex 리뷰 #4: 앞으로 가져올 때마다
    // 격자를 다시 그려 스크롤이 맨 위로 갔다). 분류를 바꿀 때만 다시 그린다.
    if (rendered) return;
    try {
      await loadState();
      paintCats();
      await select(active);
      rendered = cache.has(active);
    } catch (error) {
      setStatus(error.message || '불러오지 못했습니다', 'error');
      showToast(error.message || 'Thumb 을 불러오지 못했습니다', 'error');
    }
  }

  return {
    open,
    hidePeek,
    isOpen: () => !!(panel && panel.isOpen()),
  };
}
