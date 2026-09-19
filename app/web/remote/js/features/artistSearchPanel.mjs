/** 아티스트 매칭 검색 — 조건을 쌓아 작가를 좁히는 판(사용자 지정 2026-09-19).
 *
 *  믹스 큐가 비우고 나간 **창 옆 보조 판**(`.rctl-side`)에 산다. 백엔드는
 *  `core/artist_search.py` 이고 **상태가 없다** - 이 판이 depth 목록을 쥐고
 *  매번 통째로 보낸다. 그래서 뒤로 가기가 그냥 `stack.slice(0, n)` 이다.
 *
 *      [캐릭터 | 작품 | 태그 | 등급]      <- 갈래 넷(사용자 지정)
 *      ┌ genshin impact ─┐ ┌ rating q+e ─┐
 *      │ count>=10       │ │ 비중>=45%    │
 *      │ post >=200      │ │ post >=100   │
 *      └── 1,159 ────────┘ └── 397 ──────┘
 *
 *  ⚠️ **갈래는 자리를 가리지 않는다.** 등급 → 캐릭터 → 태그 처럼 섞어 쌓는 것이
 *     본래 쓰임이다(사용자 지정). 상한만 **세 단계**다.
 *  ⚠️ **다음 depth 는 서버가 받아 준 뒤에 쌓는다.** 색인 밖 낱말은 검색이
 *     안 되는데(사용자 지정), 먼저 쌓아 두면 지우러 돌아가야 한다.
 *  ⚠️ **LIFT 는 정렬이 아니다.** 한 질의 안에서 P(태그)가 상수라 순서가 '날 비중'
 *     과 완전히 같아진다 - Wilson 이 막아 둔 '표본이 얇은 작가 1등' 이 되살아난다.
 *     보여 주기만 하고 고르게 하지 않는다.
 *  ⚠️ 카드는 `data-artist` 를 단다. 그래야 리모컨의 **확대 보기**와 **끌기**가
 *     격자와 같은 문으로 들어온다(선택자만 늘리면 된다).
 */

/** 갈래 넷. 앞의 셋은 **팩의 축 이름 그대로** 다 - 화면이 축을 실어 보내므로
 *  서버가 추정할 일이 없고, 같은 낱말이 두 축에 있어도 엉뚱한 쪽이 잡히지 않는다.
 *  ⚠️ 어느 축이 실제로 있는지는 `/state` 가 말해 준다. 여기 적힌 것은 **차례와
 *     이름표뿐**이고, 없는 축은 스스로 잠긴다(팩마다 담은 축이 다르다). */
const KINDS = [
  ['character', '캐릭터', '예: artoria pendragon (fate)'],
  ['copyright', '작품', '예: genshin impact'],
  ['general', '태그', '예: small breasts'],
  ['rating', '등급', ''],
];

const TAG_KINDS = KINDS.filter(([, , hint]) => hint).map(([value]) => value);
const isTagKind = value => TAG_KINDS.includes(value);

const ORDERS = [
  ['posts', '총 Post', '이 조건을 만족하는 작가를 게시물 수로 줄 세웁니다.'],
  ['count', '매칭 수', '마지막 단계에서 잡힌 수로 줄 세웁니다.'],
  ['wilson', 'Wilson', '비중의 신뢰 하한 - 표본이 얇은 작가를 스스로 낮춥니다.'],
];

/** 등급 묶음 둘(사용자 사양). 셋 이상을 열면 화면만 복잡해진다. */
const RATING_SETS = [
  ['e', 'e'],
  ['q+e', 'q+e'],
];

/** 사용자 지정 2026-09-19: **세 단계까지**. 백엔드의 `MAX_DEPTH` 와 같은 값이다. */
const MAX_DEPTH = 3;

/** 첫 depth 만 문턱이 다르다(사용자 예시: 최소 post 200 -> 그 뒤 100). */
function tagDefaults(depth) {
  return {minCount: 10, minPosts: depth === 0 ? 200 : 100};
}

const fmt = n => Number(n || 0).toLocaleString('en-US');

export function createArtistSearchPanel({
  document: doc,
  escHtml,
  showToast,
  getJson,
  postJson,
  describe = null,
  onPick = null,
  onDragStart = null,
  getBroker = null,
  // 결과가 바뀔 때마다 한 번. 판이 접혔을 때 보여 줄 요약을 바깥이 다시 심는다.
  onUpdate = null,
}) {
  const el = doc.createElement('div');
  el.className = 'asx';
  el.innerHTML = `
    <div class="asx-head">
      <span class="asx-title">아티스트 검색</span>
      <span class="asx-count"></span>
      <span class="asx-spacer"></span>
      <button type="button" class="asx-btn" data-asx-act="reset" title="단계를 모두 지웁니다">지우기</button>
    </div>
    <div class="asx-body rctl-fold-body">
      <div class="asx-stack" role="list"></div>
      <div class="asx-form">
        <div class="asx-seg asx-kinds" data-asx-seg="kind">
          ${KINDS.map(([value, label]) => `<button type="button" data-asx-kind="${value}">${escHtml(label)}</button>`).join('')}
        </div>
        <div class="asx-main">
          <div class="asx-tag">
            <div class="asx-input-wrap">
              <input class="asx-input" type="text" spellcheck="false" autocomplete="off">
              <div class="asx-sugg" hidden></div>
            </div>
          </div>
          <div class="asx-rating" hidden>
            <div class="asx-seg" data-asx-seg="ratings">
              ${RATING_SETS.map(([v, label]) => `<button type="button" data-asx-ratings="${v}">${escHtml(label)}</button>`).join('')}
            </div>
            <div class="asx-seg" data-asx-seg="mode">
              <button type="button" data-asx-mode="count">개수</button>
              <button type="button" data-asx-mode="ratio">비중</button>
            </div>
          </div>
          <!-- ⚠️ 자동완성 목록 **위**에 있어야 한다. 아래에 두면 목록이 덮어
               포인터를 먹고, 단추를 영영 못 누른다(실측). -->
          <button type="button" class="asx-btn primary" data-asx-act="add">추가</button>
        </div>
        <div class="asx-nums">
          <label class="asx-num" data-asx-for="count"><span>count ≥</span>
            <input class="asx-n" type="number" min="0" step="1" data-asx-num="count"></label>
          <label class="asx-num" data-asx-for="ratio" hidden><span>비중 ≥</span>
            <input class="asx-n" type="number" min="0" max="100" step="1" data-asx-num="ratio"><span class="asx-unit">%</span></label>
          <label class="asx-num"><span>post ≥</span>
            <input class="asx-n" type="number" min="0" step="1" data-asx-num="posts"></label>
        </div>
      </div>
      <div class="asx-seg asx-orders" data-asx-seg="order">
        ${ORDERS.map(([v, label, tip]) => `<button type="button" data-asx-order="${v}" title="${escHtml(tip)}">${escHtml(label)}</button>`).join('')}
      </div>
      <div class="asx-rows" role="list"></div>
      <div class="asx-note"></div>
    </div>`;

  const headCountEl = el.querySelector('.asx-count');
  const stackEl = el.querySelector('.asx-stack');
  const formEl = el.querySelector('.asx-form');
  const tagBoxEl = el.querySelector('.asx-tag');
  const ratingBoxEl = el.querySelector('.asx-rating');
  const inputEl = el.querySelector('.asx-input');
  const suggEl = el.querySelector('.asx-sugg');
  const rowsEl = el.querySelector('.asx-rows');
  const noteEl = el.querySelector('.asx-note');
  const addBtn = el.querySelector('[data-asx-act="add"]');
  const numEls = {
    count: el.querySelector('[data-asx-num="count"]'),
    ratio: el.querySelector('[data-asx-num="ratio"]'),
    posts: el.querySelector('[data-asx-num="posts"]'),
  };
  const numWrap = {
    count: el.querySelector('[data-asx-for="count"]'),
    ratio: el.querySelector('[data-asx-for="ratio"]'),
  };

  let packState = null;      // /state 응답 - `missing` 이면 판이 통째로 잠긴다
  let axesReady = new Set(); // 이 팩이 실제로 담은 축. 나머지 갈래는 스스로 잠긴다.
  let stack = [];            // 서버가 받아 준 depth 만 쌓인다
  let order = 'wilson';
  let kind = 'copyright';
  let ratingsPick = 'e';
  let ratingMode = 'count';
  let rows = [];
  let steps = [];
  let total = 0;
  let busy = false;
  let seq = 0;               // 늦게 온 응답이 새 결과를 덮지 않게
  let suggSeq = 0;
  let suggTimer = null;
  let suggRows = [];
  let thumbs = new Map();    // 이름 -> {image_url}

  const kindLabel = value => (KINDS.find(([v]) => v === value) || [, value])[1];
  const kindHint = value => (KINDS.find(([v]) => v === value) || [, , ''])[2];
  /** 갈래를 쓸 수 있는가. 등급은 팩만 있으면 늘 된다(축이 아니라 행의 속성이다). */
  const kindUsable = value => (value === 'rating' ? true : axesReady.has(value));

  // ── 화면 그리기 ───────────────────────────────────────────────────────

  function stepLabel(step) {
    if (step.kind === 'tag') return step.tag;
    const set = (step.ratings || []).join('+');
    return step.mode === 'ratio'
      ? `rating:${set} ${Math.round((step.min_ratio || 0) * 100)}%`
      : `rating:${set} ≥${fmt(step.min_count)}`;
  }

  function paintStack() {
    if (!stack.length) {
      stackEl.innerHTML = '<span class="asx-stack-empty">조건을 하나 넣어 시작하세요.</span>';
      return;
    }
    stackEl.innerHTML = stack.map((step, i) => {
      const passed = steps[i]?.passed;
      const count = passed === undefined ? '' : `<b>${fmt(passed)}</b>`;
      return `<button type="button" class="asx-chip" role="listitem" data-asx-depth="${i}"
        title="여기까지만 남기고 뒤를 지웁니다">${escHtml(stepLabel(step))}${count}</button>`;
    }).join('<span class="asx-chip-arrow">›</span>');
  }

  function rowHtml(row) {
    const info = thumbs.get(row.artist);
    const img = info?.image_url
      ? `<img src="${escHtml(info.image_url)}" alt="" loading="lazy" draggable="false">`
      : '<span class="asx-noimg">—</span>';
    return `<button type="button" class="asx-card" role="listitem" data-artist="${escHtml(row.artist)}">
      <span class="asx-img">${img}</span>
      <span class="asx-col">
        <span class="asx-name">${escHtml(row.artist)}</span>
        <span class="asx-nums-row">
          <span title="총 게시물">${fmt(row.total)}</span>
          <span title="마지막 단계 매칭 수">·${fmt(row.hit)}</span>
          <span class="asx-w" title="Wilson 하한 / 날 비중 ${row.share}">${row.wilson.toFixed(3)}</span>
        </span>
      </span>
    </button>`;
  }

  function paintRows() {
    rowsEl.innerHTML = rows.length
      ? rows.map(rowHtml).join('')
      : (stack.length ? '<div class="asx-empty">조건을 만족하는 작가가 없습니다.</div>' : '');
    headCountEl.textContent = stack.length ? `${fmt(total)}명` : '';
  }

  function paintForm() {
    const tagMode = isTagKind(kind);
    tagBoxEl.hidden = !tagMode;
    ratingBoxEl.hidden = tagMode;
    const isRatio = kind === 'rating' && ratingMode === 'ratio';
    numWrap.count.hidden = isRatio;
    numWrap.ratio.hidden = !isRatio;
    inputEl.placeholder = kindHint(kind);
    // 세그먼트 넷 - 각각 제 `data-asx-<이름>` 을 읽어 고른 것에 불을 켠다.
    for (const [seg, attr, on] of [['kind', 'asxKind', kind],
                                   ['ratings', 'asxRatings', ratingsPick],
                                   ['mode', 'asxMode', ratingMode],
                                   ['order', 'asxOrder', order]]) {
      el.querySelectorAll(`[data-asx-seg="${seg}"] button`).forEach(btn => {
        btn.classList.toggle('is-on', btn.dataset[attr] === on);
      });
    }
    // 이 팩에 없는 축은 **잠근다**(고장이 아니다 - 담은 것이 다를 뿐).
    el.querySelectorAll('[data-asx-kind]').forEach(btn => {
      const value = btn.dataset.asxKind;
      const usable = kindUsable(value);
      btn.classList.toggle('is-off', !usable);
      btn.title = usable ? `${kindLabel(value)} 로 좁힙니다`
        : `${kindLabel(value)} 축은 이 색인에 없습니다`;
    });
    const full = stack.length >= MAX_DEPTH;
    addBtn.disabled = full || !kindUsable(kind);
    formEl.classList.toggle('is-busy', busy);
    formEl.classList.toggle('is-full', full);
  }

  function resetNums() {
    const defaults = tagDefaults(stack.length);
    numEls.count.value = String(defaults.minCount);
    numEls.ratio.value = '45';
    numEls.posts.value = String(isTagKind(kind) ? defaults.minPosts : 100);
  }

  function note(text, kindName = '') {
    noteEl.textContent = text || '';
    noteEl.className = `asx-note${kindName ? ` is-${kindName}` : ''}`;
  }

  // ── 서버 ──────────────────────────────────────────────────────────────

  /** `candidate` 를 끝에 붙여 본다. 서버가 받아 주면 그때 `stack` 이 된다. */
  async function run(nextStack, {commit = true} = {}) {
    if (!nextStack.length) {
      stack = []; steps = []; rows = []; total = 0; thumbs = new Map();
      paintStack(); paintRows(); paintForm(); note('');
      onUpdate?.();
      return true;
    }
    const mine = ++seq;
    busy = true;
    paintForm();
    let data = null;
    try {
      data = await postJson('/api/artist-affinity/search',
                            {stack: nextStack, order, limit: 200});
    } catch (error) {
      if (mine !== seq) return false;
      busy = false; paintForm();
      note(`검색에 실패했습니다 — ${error.message}`, 'bad');
      return false;
    }
    if (mine !== seq) return false;
    busy = false;
    if (data?.state === 'unknown_tag') {
      paintForm();
      note(`색인에 없는 낱말입니다: ${data.tag}`, 'bad');
      return false;
    }
    if (data?.state && data.state !== 'ready') {
      paintForm();
      note(`검색을 쓸 수 없습니다 — ${data.reason || data.state}`, 'bad');
      return false;
    }
    if (commit) stack = nextStack;
    steps = data.steps || [];
    rows = data.rows || [];
    total = Number(data.total || 0);
    thumbs = new Map();
    paintStack(); paintRows(); paintForm();
    note(total
      ? (stack.length >= MAX_DEPTH ? `${MAX_DEPTH}단계까지입니다.` : '')
      : '조건이 너무 좁습니다 - 문턱을 낮춰 보세요.');
    resetNums();
    onUpdate?.();
    void loadThumbs(mine);
    return true;
  }

  /** 그림은 **격자와 같은 서버 한 곳**에서 받는다(`/api/artist-thumb/describe`). */
  async function loadThumbs(mine) {
    if (typeof describe !== 'function' || !rows.length) return;
    const names = rows.map(r => r.artist);
    let map = null;
    try { map = await describe(names); } catch (_) { return; }
    if (mine !== seq || !map) return;
    thumbs = new Map(Object.entries(map));
    paintRows();
  }

  function buildStep() {
    const minPosts = Math.max(Number(numEls.posts.value) || 0, 0);
    if (isTagKind(kind)) {
      const tag = inputEl.value.trim();
      if (!tag) { note(`${kindLabel(kind)} 를 적어 주세요.`, 'bad'); inputEl.focus(); return null; }
      // ⚠️ 축은 **화면이 정한다**(고른 갈래 그대로). 서버가 추정하게 두면 같은
      //    낱말이 두 축에 있을 때 사용자가 안 고른 쪽이 잡힌다.
      return {kind: 'tag', tag, axis: kind,
              min_count: Math.max(Number(numEls.count.value) || 0, 0), min_posts: minPosts};
    }
    const ratings = ratingsPick.split('+');
    if (ratingMode === 'ratio') {
      const pct = Math.min(Math.max(Number(numEls.ratio.value) || 0, 0), 100);
      return {kind: 'rating', ratings, mode: 'ratio', min_ratio: pct / 100, min_posts: minPosts};
    }
    return {kind: 'rating', ratings, mode: 'count',
            min_count: Math.max(Number(numEls.count.value) || 0, 0), min_posts: minPosts};
  }

  async function addDepth() {
    if (busy || packState?.state !== 'ready') return;
    if (stack.length >= MAX_DEPTH) { note(`${MAX_DEPTH}단계까지입니다.`, 'bad'); return; }
    if (!kindUsable(kind)) { note(`${kindLabel(kind)} 축은 이 색인에 없습니다.`, 'bad'); return; }
    const step = buildStep();
    if (!step) return;
    note('');
    const ok = await run([...stack, step]);
    if (ok) { inputEl.value = ''; closeSugg(); }
  }

  // ── 자동완성 ──────────────────────────────────────────────────────────
  //  ⚠️ 목록은 **`mousedown` 을 막아** 고른다. 안 그러면 누르는 순간 입력칸이 초점을
  //     잃고 `blur` 가 목록을 닫아 클릭이 허공에 떨어진다(이 저장소의 단골 함정).

  function closeSugg() {
    // ⚠️ 닫기만 하면 **예약된 조회가 뒤늦게 다시 연다**(실측: [추가] 를 누른 뒤에도
    //    목록이 남아 있었다). 시계와 답 둘 다 무효로 만든다.
    if (suggTimer) { clearTimeout(suggTimer); suggTimer = null; }
    suggSeq += 1;
    suggEl.hidden = true;
    suggEl.innerHTML = '';
    suggRows = [];
  }

  function paintSugg() {
    if (!suggRows.length) { closeSugg(); return; }
    // 오른쪽 숫자는 **그 태그가 달린 게시물 수**다(사용자 지정). 축은 고른 갈래라
    // 여기 다시 적지 않는다 - 좁은 칸에서는 숫자가 훨씬 쓸모 있다.
    suggEl.innerHTML = suggRows.map((row, i) => `
      <button type="button" data-asx-sugg="${i}"><span>${escHtml(row.tag)}</span><em>${fmt(row.posts)}</em></button>`).join('');
    suggEl.hidden = false;
  }

  function scheduleSuggest() {
    if (suggTimer) clearTimeout(suggTimer);
    const value = inputEl.value.trim();
    if (value.length < 2 || !isTagKind(kind)) { closeSugg(); return; }
    const axis = kind;
    suggTimer = setTimeout(async () => {
      suggTimer = null;
      const mine = ++suggSeq;
      let data = null;
      try {
        data = await getJson(`/api/artist-affinity/suggest?q=${encodeURIComponent(value)}`
                             + `&axis=${encodeURIComponent(axis)}`);
      } catch (_) { return; }
      if (mine !== suggSeq) return;
      suggRows = data?.rows || [];
      paintSugg();
    }, 160);
  }

  // ── 손잡이 ────────────────────────────────────────────────────────────

  el.addEventListener('click', event => {
    const act = event.target.closest('[data-asx-act]')?.dataset.asxAct;
    if (act === 'reset') { void run([]); note(''); return; }
    if (act === 'add') { void addDepth(); return; }

    const kindBtn = event.target.closest('[data-asx-kind]');
    if (kindBtn) {
      kind = kindBtn.dataset.asxKind;
      closeSugg();
      inputEl.value = '';
      paintForm(); resetNums();
      if (!kindUsable(kind)) { note(`${kindLabel(kind)} 축은 이 색인에 없습니다.`, 'bad'); return; }
      note('');
      if (isTagKind(kind)) inputEl.focus();
      return;
    }
    const ratingsBtn = event.target.closest('[data-asx-ratings]');
    if (ratingsBtn) { ratingsPick = ratingsBtn.dataset.asxRatings; paintForm(); return; }
    const modeBtn = event.target.closest('[data-asx-mode]');
    if (modeBtn) { ratingMode = modeBtn.dataset.asxMode; paintForm(); resetNums(); return; }

    const orderBtn = event.target.closest('[data-asx-order]');
    if (orderBtn) {
      const next = orderBtn.dataset.asxOrder;
      if (next === order) return;
      order = next;
      paintForm();
      // 정렬만 바뀌었으니 depth 는 그대로다 - 같은 stack 을 다시 던진다.
      if (stack.length) void run(stack);
      return;
    }

    const chip = event.target.closest('[data-asx-depth]');
    if (chip) {
      // 칩을 누르면 **거기까지만** 남는다. 마지막 칩이면 그 단계를 뺀다(뒤로 가기).
      const at = Number(chip.dataset.asxDepth);
      const next = at === stack.length - 1 ? stack.slice(0, at) : stack.slice(0, at + 1);
      void run(next);
      return;
    }

    const card = event.target.closest('.asx-card[data-artist]');
    if (card && typeof onPick === 'function') onPick(card.dataset.artist);
  });

  // 자동완성 목록은 **mousedown 에서** 고른다(초점을 잃기 전에).
  suggEl.addEventListener('mousedown', event => {
    const btn = event.target.closest('[data-asx-sugg]');
    if (!btn) return;
    event.preventDefault();
    const row = suggRows[Number(btn.dataset.asxSugg)];
    if (!row) return;
    inputEl.value = row.tag;
    closeSugg();
    inputEl.focus();
  });

  inputEl.addEventListener('input', scheduleSuggest);
  inputEl.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      // 목록이 떠 있고 딱 하나면 그것을 고른 것으로 친다.
      if (!suggEl.hidden && suggRows.length === 1) {
        inputEl.value = suggRows[0].tag;
        closeSugg();
      }
      void addDepth();
      return;
    }
    if (event.key === 'Escape' && !suggEl.hidden) {
      event.preventDefault();
      event.stopPropagation();
      closeSugg();
    }
  });
  inputEl.addEventListener('blur', () => { setTimeout(closeSugg, 0); });

  el.querySelectorAll('.asx-n').forEach(input => {
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); void addDepth(); }
    });
  });

  // 결과 카드는 끌기 원본이다 - 격자 카드와 **같은 짐**을 싣는다(믹스 띠가 받는다).
  el.addEventListener('pointerdown', event => {
    const card = event.target.closest('.asx-card[data-artist]');
    if (!card || typeof getBroker !== 'function') return;
    const artist = card.dataset.artist;
    if (!artist) return;
    const image = card.querySelector('img')?.getAttribute('src') || '';
    void Promise.resolve(getBroker()).then(broker => {
      if (!broker || !(event.buttons & 1)) return;
      broker.arm(event, {kind: 'artist', artist, weight: 1, image, label: artist},
                 {onStart: () => onDragStart?.()});
    });
  });

  // ── 바깥에서 부르는 것 ────────────────────────────────────────────────

  async function ensureState() {
    if (packState) return packState;
    try { packState = await getJson('/api/artist-affinity/state'); }
    catch (error) { packState = {state: 'missing', reason: error.message}; }
    const ready = packState?.state === 'ready';
    el.classList.toggle('is-missing', !ready);
    if (!ready) {
      note('검색 색인(artist_tag_affinity.naiapack)이 없습니다.', 'bad');
      paintForm();
      return packState;
    }
    // ⚠️ 어느 축이 있는지는 **서버가 말한다**. 화면에 박아 두면 팩을 바꿨을 때
    //    있지도 않은 갈래가 열려 있고, 누르면 그제야 400 이 난다.
    axesReady = new Set(Object.keys(packState.axes || {}));
    if (!kindUsable(kind)) {
      kind = KINDS.map(([v]) => v).find(kindUsable) || 'rating';
    }
    paintForm();
    resetNums();
    return packState;
  }

  paintStack();
  paintForm();
  resetNums();

  return {
    el,
    ensureState,
    /** 접혔을 때 판이 보여 줄 요약 줄. */
    summary: () => (stack.length
      ? [stack.map(stepLabel).join(' › '), `${fmt(total)}명`]
      : []),
    isReady: () => packState?.state === 'ready',
    focus: () => { if (isTagKind(kind) && kindUsable(kind)) inputEl.focus(); },
    reset: () => { void run([]); },
    destroy: () => { seq += 1; suggSeq += 1; if (suggTimer) clearTimeout(suggTimer); el.remove(); },
  };
}
