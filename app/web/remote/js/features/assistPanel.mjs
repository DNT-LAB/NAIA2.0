/* Assist — Ctrl+O 로 여는 한국어 어시스트(기억이 짧은 만능 어시스트).
 *
 * 말로 적으면 서버(`/api/assist`)가 E2B 1회 + 한국어 층(Kiwi) + 이벤트 맵으로 프롬프트를 찾는다.
 * 여기서는 그리기·키·넣기만 한다. 설계·실측: docs/ASSIST_V2_DESIGN_2026_09_23.md.
 *
 * - 입력하는 동안 알아본 캐릭터 이름을 칠한다(`/api/assist/names`, 모델 없이). 후보가 여럿이면 **모델이 아니라
 *   사용자가** 목록에서 고른다(사용자 사양 2026-09-23). `{이름}` 으로 감싸면 일반 낱말이어도 이름으로 찾는다.
 *   고른 것·'이름 아님' 은 창을 쓰는 동안 기억해 **요청마다 보낸다** — 서버는 기억이 짧다.
 * - ⚠️ [생성] 은 **가상 프롬프트**로 한 장 뽑는다 — 메인 칸·캐릭터 칸은 그대로다(사용자 지정 2026-09-24: "사용자의
 *   캐릭터 프롬프트를 간섭하면 곤란"). 서버(`/api/assist/generate`)가 메인은 이벤트 맵 [생성] 과 같은 바이패스로,
 *   캐릭터는 이 요청에만 싣는다. '생성해 줘' 는 [바로 생성] 을 켰을 때만 이 길로 뽑는다(기본 꺼짐 — 사용자 결정 2026-09-23).
 * - 칸에 넣는 것은 **[프롬프트에 넣기] 를 눌렀을 때만**이다. 메인 = 이벤트 맵 [적용] 과 같은 Random 파이프라인
 *   (PE 앞뒤·자동 숨김·와일드카드), 캐릭터 칸(NAI) = 기존 칸은 **비활성으로** 보내고 새로 덧붙인다(아무것도 잃지 않는다).
 * - 칠하기는 promptHighlighter 와 같은 방식이다: 입력칸 뒤에 같은 글을 담은 거울을 깔고 CSS Custom Highlight API
 *   로 범위만 칠한다(범위는 배치를 안 바꾼다 — 캐럿이 글자와 어긋나지 않는다). API 가 없으면 <mark> 로 칠한다.
 * - 크기·자리 규약은 Fast Search 와 같다(결과 칸 가운데, 폭 ≤ 720, 높이 ≤ 결과 칸의 절반).
 */

const RATINGS = [
  { id: 'g', label: 'G', title: 'General' },
  { id: 's', label: 'S', title: 'Sensitive' },
  { id: 'q', label: 'Q', title: 'Questionable' },
  { id: 'e', label: 'E', title: 'Explicit' },
];
const NAMES_DEBOUNCE_MS = 300;
const NAMES_RETRY_MS = 1200;       // 한국어 층이 데워지는 동안(ready=false) 다시 묻는 간격
const PICK_SEARCH_MS = 250;
const INSTALL_POLL_MS = 1000;
const MAX_LINES = 6;
const PREF_KEY = 'naia_assist_prefs_v1';
const HL_KINDS = ['found', 'chosen', 'miss', 'off'];
const HIGHLIGHT_API = typeof Highlight !== 'undefined' && typeof CSS !== 'undefined' && !!CSS.highlights;

function loadPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREF_KEY) || 'null');
    return raw && typeof raw === 'object' ? raw : {};
  } catch { return {}; }
}

function savePrefs(prefs) {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch { /* 저장 못 해도 동작한다 */ }
}

function clampCount(value, fallback) {
  const n = Number(value);
  return Number.isInteger(n) && n >= 0 && n <= 9 ? n : fallback;
}

export function initAssist({ showToast, getApiMode, applyCharacters, onRandomLink } = {}) {
  let overlay = null, input = null, mirror = null, namesRow = null, personsEl = null, ratingBar = null;
  let autoBox = null, banner = null, body = null, sendBtn = null, picker = null;
  let open = false;
  let heightCap = 0;

  const prefs = loadPrefs();
  let rating = RATINGS.some(r => r.id === prefs.rating) ? prefs.rating : 'g';
  let autoGenerate = !!prefs.autoGenerate;
  let personsMode = prefs.personsMode === 'manual' ? 'manual' : 'auto';
  let girls = clampCount(prefs.girls, 1);
  let boys = clampCount(prefs.boys, 0);

  let names = new Map();          // form -> {form, found, source, tag, candidates[]}
  let spans = [];                 // [{start, end, form}] — 원문 위치
  const choices = new Map();      // form -> 사용자가 고른 태그
  const notNames = new Set();     // 사용자가 '이름 아님' 으로 고른 낱말
  let recap = null;               // 직전 검색(기억 1개)
  let result = null;              // 마지막 응답
  let busy = false, askSeq = 0, namesSeq = 0, namesTimer = null, pollTimer = null;
  let status = null;
  let pickerForm = null, pickSeq = 0, pickTimer = null;

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const fmt = n => (Number.isFinite(Number(n)) ? Number(n).toLocaleString() : '');
  const genderMark = g => (g === 'girl' ? ' ♀' : g === 'boy' ? ' ♂' : '');

  function toast(message, kind) {
    if (typeof showToast === 'function') showToast(message, kind || 'info');
  }

  function persistPrefs() {
    savePrefs({ rating, autoGenerate, personsMode, girls, boys });
  }

  async function postJson(path, payload, { allowError = false } = {}) {
    const res = await fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload ?? {}), cache: 'no-store',
    });
    const data = await res.json().catch(() => ({}));
    if ((!res.ok || data.ok === false) && !allowError) {
      const error = new Error(data.error || data.message || `HTTP ${res.status}`);
      error.status = res.status;
      throw error;
    }
    return data;
  }

  async function getJson(path) {
    const res = await fetch(path, { cache: 'no-store' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  // ── 틀 ────────────────────────────────────────────────────────────────

  function build() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'as-overlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="as-bar">
        <span class="as-icon" aria-hidden="true">✦</span>
        <div class="as-edit">
          <div class="as-mirror" aria-hidden="true"></div>
          <textarea class="as-input" rows="1" maxlength="300" spellcheck="false" autocomplete="off"
                    aria-label="Assist 요청"
                    placeholder="말로 적어 주세요 — 예: 카나데가 나히다를 공주안기 하고 뛰어다니는 장면"></textarea>
        </div>
        <button type="button" class="as-send" data-as-send title="찾기 (Enter)">찾기</button>
        <button type="button" class="as-close" data-as-close aria-label="닫기">×</button>
      </div>
      <div class="as-names" data-as-names hidden></div>
      <div class="as-opts">
        <span class="as-persons" data-as-persons role="group" aria-label="인원"></span>
        <span class="fs-rating-bar as-rating" data-as-rating role="group" aria-label="등급(추론 방향)">${RATINGS.map(r =>
          `<button type="button" class="fs-rating-btn" data-r="${r.id}" title="${r.title}">${r.label}</button>`).join('')}</span>
        <label class="as-auto" title="요청이 '생성해 줘' 로 끝나면 이 결과로 바로 한 장 생성합니다 — 칸은 그대로(기본 꺼짐)">
          <input type="checkbox" data-as-auto> 생성해 줘 → 바로 생성</label>
        <button type="button" class="as-reset" data-as-reset title="기억(직전 검색)과 이름 선택을 지우고 새로 시작">새로</button>
      </div>
      <div class="as-banner" data-as-banner hidden></div>
      <div class="as-body" data-as-body></div>
      <div class="as-foot"><b>Enter</b> 찾기 · Esc 닫기 · <b>{이름}</b> 으로 감싸면 이름으로 찾습니다 — [생성] 은 메인·캐릭터 칸을 건드리지 않습니다</div>`;
    document.body.append(overlay);
    input = overlay.querySelector('.as-input');
    mirror = overlay.querySelector('.as-mirror');
    namesRow = overlay.querySelector('[data-as-names]');
    personsEl = overlay.querySelector('[data-as-persons]');
    ratingBar = overlay.querySelector('[data-as-rating]');
    autoBox = overlay.querySelector('[data-as-auto]');
    banner = overlay.querySelector('[data-as-banner]');
    body = overlay.querySelector('[data-as-body]');
    sendBtn = overlay.querySelector('[data-as-send]');

    autoBox.checked = autoGenerate;
    autoBox.addEventListener('change', () => { autoGenerate = autoBox.checked; persistPrefs(); });
    overlay.querySelector('[data-as-close]').addEventListener('click', close);
    overlay.querySelector('[data-as-reset]').addEventListener('click', reset);
    sendBtn.addEventListener('click', () => { void ask(); });
    input.addEventListener('input', onInput);
    input.addEventListener('keydown', onKeyDown);
    input.addEventListener('scroll', () => { mirror.scrollTop = input.scrollTop; });
    ratingBar.addEventListener('click', event => {
      const pill = event.target.closest('[data-r]');
      if (!pill || pill.dataset.r === rating) return;
      rating = pill.dataset.r;
      persistPrefs();
      paintRating();
      if (result && !busy) void ask();
    });
    personsEl.addEventListener('click', onPersonsClick);
    namesRow.addEventListener('mousedown', event => event.preventDefault());   // 포커스는 입력칸에
    namesRow.addEventListener('click', event => {
      const chip = event.target.closest('[data-as-name]');
      if (!chip) return;
      const form = chip.dataset.asName;
      if (picker && !picker.hidden && pickerForm === form) { closePicker(); return; }
      openPicker(form, chip);
    });
    banner.addEventListener('click', event => {
      if (event.target.closest('[data-as-kiwi-install]')) void installKiwi();
    });
    body.addEventListener('click', onBodyClick);
    document.addEventListener('pointerdown', event => {
      if (!open) return;
      const t = event.target;
      if (overlay.contains(t) || (picker && !picker.hidden && picker.contains(t))) return;
      close();
    }, true);
    window.addEventListener('resize', () => {
      position();
      if (open) autoGrow();          // 폭이 바뀌면 줄바꿈이 바뀐다
    });
    paintRating();
    paintPersons();
    return overlay;
  }

  function paintRating() {
    ratingBar?.querySelectorAll('[data-r]').forEach(pill => {
      const on = pill.dataset.r === rating;
      pill.classList.toggle('active', on);
      pill.setAttribute('aria-pressed', String(on));
    });
  }

  // ── 인원: [자동 | 여 n 남 m] ─────────────────────────────────────────────

  function detectedPersons() {
    const p = result?.persons;
    return p && p.mode === 'auto' ? p : null;
  }

  function paintPersons() {
    if (!personsEl) return;
    const auto = personsMode === 'auto';
    const seen = detectedPersons();
    const g = auto ? (seen ? seen.girls : null) : girls;
    const b = auto ? (seen ? seen.boys : null) : boys;
    const shown = n => (n == null ? '·' : esc(n));
    personsEl.innerHTML = `
      <button type="button" class="as-seg${auto ? ' is-on' : ''}" data-as-persons-auto aria-pressed="${auto}"
              title="요청에서 인원을 셉니다">자동</button>
      <span class="as-step${auto ? ' is-dim' : ''}" title="여성 수">여
        <button type="button" data-as-step="girls" data-d="-1" aria-label="여성 줄이기">−</button><b>${shown(g)}</b><button
                type="button" data-as-step="girls" data-d="1" aria-label="여성 늘리기">+</button></span>
      <span class="as-step${auto ? ' is-dim' : ''}" title="남성 수">남
        <button type="button" data-as-step="boys" data-d="-1" aria-label="남성 줄이기">−</button><b>${shown(b)}</b><button
                type="button" data-as-step="boys" data-d="1" aria-label="남성 늘리기">+</button></span>
      ${auto && seen?.confirm ? '<span class="as-confirm" title="요청만으로는 인원을 확실히 못 셌습니다 — 여·남 을 눌러 정해 주세요">확인</span>' : ''}`;
  }

  function onPersonsClick(event) {
    if (event.target.closest('[data-as-persons-auto]')) {
      if (personsMode === 'auto') return;
      personsMode = 'auto';
    } else {
      const step = event.target.closest('[data-as-step]');
      if (!step) return;
      if (personsMode === 'auto') {
        // 자동에서 처음 누르면 지금 보이는 수(센 것)에서 시작한다
        const seen = detectedPersons();
        if (seen) { girls = clampCount(seen.girls, girls); boys = clampCount(seen.boys, boys); }
        personsMode = 'manual';
      }
      const next = clampCount((step.dataset.asStep === 'girls' ? girls : boys) + Number(step.dataset.d), null);
      if (next == null) return;
      const g = step.dataset.asStep === 'girls' ? next : girls;
      const b = step.dataset.asStep === 'boys' ? next : boys;
      if (g + b < 1 || g + b > 9) return;               // 서버 규칙과 같다(1~9명)
      girls = g; boys = b;
    }
    persistPrefs();
    paintPersons();
    if (result && !busy) void ask();
  }

  // ── 이름: 칠하기 · 칩 · 고르기 ───────────────────────────────────────────

  function spanKind(form) {
    if (notNames.has(form)) return 'off';
    if (choices.has(form)) return 'chosen';
    const n = names.get(form);
    return n && n.found ? 'found' : 'miss';
  }

  function liveSpans() {
    const text = input.value;
    return spans.filter(s => text.slice(s.start, s.end) === s.form);   // 글이 바뀌어 자리가 어긋난 칠은 버린다
  }

  function paintHighlights() {
    if (!mirror) return;
    const text = input.value;
    const live = liveSpans().sort((a, b) => a.start - b.start);
    if (HIGHLIGHT_API) {
      mirror.textContent = `${text}​`;
      const node = mirror.firstChild;
      const buckets = Object.fromEntries(HL_KINDS.map(kind => [kind, []]));
      for (const s of live) {
        if (!node || s.end > node.length) continue;
        const range = document.createRange();
        range.setStart(node, s.start);
        range.setEnd(node, s.end);
        buckets[spanKind(s.form)].push(range);
      }
      for (const kind of HL_KINDS) {
        const name = `naia-as-${kind}`;
        if (buckets[kind].length) CSS.highlights.set(name, new Highlight(...buckets[kind]));
        else CSS.highlights.delete(name);
      }
      return;
    }
    let html = '';
    let at = 0;
    for (const s of live) {
      if (s.start < at) continue;
      html += `${esc(text.slice(at, s.start))}<mark class="as-hl as-hl-${spanKind(s.form)}">${esc(text.slice(s.start, s.end))}</mark>`;
      at = s.end;
    }
    mirror.innerHTML = `${html}${esc(text.slice(at))}​`;
  }

  function clearHighlights() {
    if (HIGHLIGHT_API) HL_KINDS.forEach(kind => CSS.highlights.delete(`naia-as-${kind}`));
  }

  function paintChips() {
    const text = input.value;
    const list = [...names.values()].filter(n => text.includes(n.form));
    namesRow.hidden = !list.length;
    namesRow.innerHTML = list.map(n => {
      const kind = spanKind(n.form);
      const tag = choices.get(n.form) || n.tag;
      const count = (n.candidates || []).length;
      const label = kind === 'off' ? '이름 아님' : kind === 'miss' ? '못 찾음' : tag;
      return `<button type="button" class="as-name as-name-${kind}" data-as-name="${esc(n.form)}"
                      title="${kind === 'chosen' ? '직접 고른 캐릭터' : '눌러서 후보 고르기'}">
        <b>${esc(n.form)}</b><span class="as-arrow">→</span><span class="as-name-tag">${esc(label)}</span>
        <span class="as-more">▾${count > 1 ? ` ${count}` : ''}</span></button>`;
    }).join('');
    fit();
  }

  function paintNames() {
    paintHighlights();
    paintChips();
  }

  /** 응답의 인물(모델이 찾은 이름 포함)을 이름 표에 합친다. 서버가 받지 않은 선택은 푼다. */
  function absorbNames(list, text) {
    for (const n of list || []) {
      const form = String(n.ko || '');
      if (!form) continue;
      const known = names.get(form);
      const candidates = Array.isArray(n.candidates) && n.candidates.length ? n.candidates : (known?.candidates || []);
      names.set(form, {
        form, found: true, source: known ? known.source : 'model',
        // tag = **자동(게시물 순 1위)**. 사용자가 고른 것은 choices 가 따로 쥔다 - 여기에 섞으면 [자동] 이 옛 선택을 보인다.
        tag: candidates[0]?.tag || n.tag,
        candidates,
      });
      if (choices.has(form) && !n.chosen) {
        choices.delete(form);
        toast(`'${form}' 의 선택을 쓸 수 없어 되돌렸습니다`, 'error');
      }
    }
    addModelSpans(text);
  }

  /** 모델이 찾은 이름(입력칸 인식이 놓친 것)도 글에서 찾아 칠한다. 긴 이름이 짧은 조각을 품으면
   *  (나토리 사나 ⊃ 나토리 — 사용자 제보 09-24) 조각을 걷고 긴 것을 칠한다. 칠이 안 남은 자동 이름은 칩에서도 뺀다. */
  function addModelSpans(text) {
    for (const n of names.values()) {
      if (n.source !== 'model' || !n.form) continue;
      let from = 0;
      for (;;) {
        const at = text.indexOf(n.form, from);
        if (at < 0) break;
        const end = at + n.form.length;
        const overlapping = spans.filter(s => at < s.end && end > s.start);
        if (overlapping.every(s => s.start >= at && s.end <= end && s.end - s.start < n.form.length)) {
          spans = spans.filter(s => !overlapping.includes(s));
          spans.push({ start: at, end, form: n.form });
        }
        from = end;
      }
    }
    const painted = new Set(spans.map(s => s.form));
    for (const [form, n] of [...names]) {
      if (n.source === 'auto' && !painted.has(form)) names.delete(form);
    }
  }

  function scheduleNames(delay = NAMES_DEBOUNCE_MS) {
    clearTimeout(namesTimer);
    namesTimer = setTimeout(() => { void fetchNames(); }, delay);
  }

  async function fetchNames() {
    if (!open) return;
    const text = input.value;
    const mine = ++namesSeq;
    if (!text.trim()) { spans = []; paintNames(); return; }
    let data;
    try { data = await postJson('/api/assist/names', { text }); } catch { return; }
    if (mine !== namesSeq || !open || input.value !== text) return;   // 그 사이 바뀌었다 - 다음 답이 온다
    const next = new Map();
    for (const n of data.names || []) next.set(n.form, n);
    for (const [form, n] of names) {
      if (n.source === 'model' && !next.has(form) && text.includes(form)) next.set(form, n);
    }
    names = next;
    spans = (data.spans || []).map(s => ({ start: s.start, end: s.end, form: s.form }));
    addModelSpans(text);
    paintNames();
    // 한국어 층이 데워지는 중이면 다시 묻는다. Kiwi 가 없어 못 데운 것(error)이면 묻지 않는다 - 설치가 끝나면 다시 부른다.
    if (!data.ready && !data.error) scheduleNames(NAMES_RETRY_MS);
  }

  function ensurePicker() {
    if (picker) return picker;
    picker = document.createElement('div');
    picker.className = 'as-pick';
    picker.hidden = true;
    document.body.append(picker);
    picker.addEventListener('mousedown', event => {
      if (!event.target.closest('input')) event.preventDefault();
    });
    picker.addEventListener('click', event => {
      const t = event.target;
      const row = t.closest('[data-as-pick]');
      if (row) { pick(pickerForm, row.dataset.asPick); return; }
      if (t.closest('[data-as-pick-auto]')) { pick(pickerForm, null); return; }
      if (t.closest('[data-as-pick-off]')) { rejectName(pickerForm); }
    });
    picker.addEventListener('input', event => {
      if (event.target.matches('[data-as-pick-q]')) {
        clearTimeout(pickTimer);
        pickTimer = setTimeout(() => { void searchCharacters(event.target.value.trim()); }, PICK_SEARCH_MS);
      }
    });
    picker.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target.matches('[data-as-pick-q]')) event.preventDefault();
    });
    return picker;
  }

  function openPicker(form, anchor) {
    const n = names.get(form);
    if (!n) return;
    ensurePicker();
    pickerForm = form;
    const current = notNames.has(form) ? '' : (choices.get(form) || n.tag);
    const rows = (n.candidates || []).map(c => `
      <button type="button" class="as-pick-row${c.tag === current ? ' is-on' : ''}" data-as-pick="${esc(c.tag)}">
        <span class="as-pick-tag">${esc(c.tag)}</span><span class="as-pick-meta">${fmt(c.posts)}${genderMark(c.gender)}</span></button>`).join('');
    picker.innerHTML = `
      <div class="as-pick-head"><b>${esc(form)}</b><span>${n.candidates?.length ? `후보 ${n.candidates.length} · 게시물 순` : '후보 없음'}</span></div>
      <div class="as-pick-list">${rows || '<div class="as-pick-empty">사전에서 찾지 못했습니다 — 아래에서 찾아 고르세요</div>'}</div>
      <div class="as-pick-search"><input type="search" data-as-pick-q placeholder="다른 캐릭터 찾기 (영문·한글)" autocomplete="off" spellcheck="false"></div>
      <div class="as-pick-list" data-as-pick-found></div>
      <div class="as-pick-foot">
        <button type="button" data-as-pick-auto title="게시물 순 1위로(선택 지우기)">자동</button>
        <button type="button" class="as-pick-off" data-as-pick-off title="캐릭터가 아니라 원래 뜻(호두를 먹는)">이름 아님</button>
      </div>`;
    picker.hidden = false;
    const r = anchor.getBoundingClientRect();
    const width = Math.min(340, window.innerWidth - 16);
    picker.style.width = `${width}px`;
    picker.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - width - 8))}px`;
    picker.style.top = `${Math.round(r.bottom + 4)}px`;
  }

  function closePicker() {
    if (!picker) return;
    picker.hidden = true;
    pickerForm = null;
    pickSeq += 1;
    clearTimeout(pickTimer);
  }

  async function searchCharacters(query) {
    const list = picker?.querySelector('[data-as-pick-found]');
    if (!list) return;
    const mine = ++pickSeq;
    if (!query) { list.innerHTML = ''; return; }
    let items = [];
    try {
      const params = new URLSearchParams({ q: query, sources: 'character', limit: '8' });
      const data = await getJson(`/api/fast-search?${params}`);
      items = (data.groups || []).find(g => g.source === 'character')?.items || [];
    } catch { items = []; }
    if (mine !== pickSeq || picker.hidden) return;
    list.innerHTML = items.length ? items.map(item => `
      <button type="button" class="as-pick-row" data-as-pick="${esc(item.value)}">
        <span class="as-pick-tag">${esc(item.title || item.value)}</span><span class="as-pick-meta">${esc(item.meta || item.subtitle || '')}</span></button>`).join('')
      : '<div class="as-pick-empty">찾지 못했습니다</div>';
  }

  function pick(form, tag) {
    if (!form) return;
    if (tag) choices.set(form, tag); else choices.delete(form);
    notNames.delete(form);
    closePicker();
    paintNames();
    if (result && !busy) void ask();
  }

  function rejectName(form) {
    if (!form) return;
    notNames.add(form);
    choices.delete(form);
    closePicker();
    paintNames();
    if (result && !busy) void ask();
  }

  // ── 묻기 · 그리기 ────────────────────────────────────────────────────────

  function onInput() {
    autoGrow();
    paintHighlights();          // 자리가 어긋난 칠은 바로 빠진다(liveSpans)
    scheduleNames();
  }

  /** 입력칸을 글 높이에 맞춘다(최대 MAX_LINES 줄, 넘치면 안에서 스크롤). 거울도 같은 높이로 —
   *  ⚠️ 스크롤바는 CSS 로 숨긴다: 보이면 글 폭이 줄어 입력칸과 거울의 줄바꿈이 어긋난다. */
  function autoGrow() {
    const cs = getComputedStyle(input);
    const line = parseFloat(cs.lineHeight) || 18;
    const max = line * MAX_LINES + (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    // ⚠️ 거울의 옛 높이를 먼저 푼다. 안 풀면 두 겹이 같은 격자 칸이라 옛 높이가 입력칸을 받쳐 scrollHeight 가
    //    그대로 나온다 - 폭 0 에서 처음 열었을 때 잡힌 6줄 높이가 영영 안 줄었다(실측).
    mirror.style.height = '';
    input.style.height = 'auto';
    const want = input.scrollHeight;
    const height = `${Math.min(want, max)}px`;
    input.style.height = height;
    input.style.overflowY = want > max ? 'auto' : 'hidden';
    mirror.style.height = height;
    mirror.scrollTop = input.scrollTop;
    fit();
  }

  function onKeyDown(event) {
    // ⚠️ 한글 입력(IME) 조합 중의 Enter 는 글자를 확정하는 키다 - 보내지 않는다.
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      void ask();
    }
  }

  function personsPayload() {
    return personsMode === 'manual' ? { mode: 'manual', girls, boys } : { mode: 'auto' };
  }

  async function ask() {
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    closePicker();
    const mine = ++askSeq;
    busy = true;
    paintBusy();
    const payload = {
      text, rating, persons: personsPayload(), previous: recap,
      names: Object.fromEntries(choices), not_names: [...notNames],
    };
    const mode = typeof getApiMode === 'function' ? String(getApiMode() || '') : '';
    if (mode) payload.api_mode = mode;
    let data;
    try { data = await postJson('/api/assist', payload, { allowError: true }); } catch (error) { data = { ok: false, error: error.message }; }
    if (mine !== askSeq) return;
    busy = false;
    if (!data || !data.ok) {
      result = null;
      body.innerHTML = `<div class="as-note as-note-warn">${esc((data && data.error) || '찾지 못했습니다')}</div>`;
      paintBusy();
      fit();
      return;
    }
    result = data;
    if (data.recap) recap = data.recap;
    absorbNames(data.names, input.value);
    paintPersons();
    paintNames();
    render();
    paintBusy();
    if (autoGenerate && data.goal === 'generate' && data.task === 'scene' && data.prompt?.main) {
      void generateVirtual();                  // 칸은 그대로 - 가상 프롬프트로 한 장
    }
  }

  function paintBusy() {
    if (!overlay) return;
    overlay.classList.toggle('is-busy', busy);
    if (sendBtn) { sendBtn.disabled = busy; sendBtn.textContent = busy ? '찾는 중…' : '찾기'; }
    if (busy && !result) body.innerHTML = '<div class="as-note">찾는 중…</div>';
  }

  function personsLabel(p) {
    const part = String(p?.partition || 'unknown');
    return part === 'unknown' ? '인원 모름' : part.replace(/_/g, ' ');
  }

  function sceneHtml(r) {
    const p = r.prompt || {};
    const chars = Array.isArray(p.characters) ? p.characters : [];
    const pool = r.pool || {};
    const lines = [
      `<div class="as-line"><span class="as-k">메인</span><span class="as-v">${esc(p.main || '(비어 있음)')}</span></div>`,
      ...chars.map((c, i) =>
        `<div class="as-line"><span class="as-k">캐릭터 ${i + 1}</span><span class="as-v">${esc(c.prompt)}</span></div>`),
    ];
    const meta = [];
    if (pool.posts) meta.push(`풀 ${fmt(pool.posts)}건`);
    meta.push(`${esc(String(r.rating || rating).toUpperCase())} · ${esc(personsLabel(r.persons))}`);
    if (pool.pins) meta.push(`핀 ${esc(String(pool.pins).split(',').join(', '))}`);
    if (r.leftovers?.length) meta.push(`못 꽂은 태그 ${esc(r.leftovers.join(', '))}`);
    if (r.actions?.length) meta.push(`랜덤 행동 ${esc(r.actions.join(', '))}`);
    const notes = [];
    if (r.message) notes.push(`<div class="as-note">${esc(r.message)}</div>`);
    if (r.persons?.confirm && personsMode === 'auto') {
      notes.push('<div class="as-note">인원을 확실히 못 셌습니다 — 위의 [여 · 남]으로 정해 주세요.</div>');
    }
    const samples = Array.isArray(r.samples) && r.samples.length
      ? `<details class="as-samples"><summary>실제 게시물 ${r.samples.length}</summary>${r.samples.map(s =>
          `<div class="as-sample">${esc((s.tags || []).join(', '))}</div>`).join('')}</details>` : '';
    const can = p.main ? '' : 'disabled';
    return `<div class="as-res">${lines.join('')}<div class="as-meta">${meta.join(' · ')}</div>${notes.join('')}
      <div class="as-actions">
        <button type="button" class="as-act as-act-main" data-as-generate ${can}
                title="메인 프롬프트·캐릭터 칸은 그대로 두고, 이 결과(가상 프롬프트)로 한 장 생성합니다">생성</button>
        <button type="button" class="as-act" data-as-apply ${can}
                title="메인 = Random 과 같은 파이프라인(PE 앞뒤·자동 숨김) · 캐릭터 칸 = 기존은 비활성으로 보내고 덧붙입니다">프롬프트에 넣기</button>
        <button type="button" class="as-act" data-as-link ${pool.pins ? '' : 'disabled'}
                title="Random·Auto Gen 이 이 조건(핀·인원·등급)의 실제 게시물에서 뽑습니다">Random 에 연결</button>
        <button type="button" class="as-act" data-as-copy ${can} title="클립보드로 복사">복사</button>
      </div>${samples}</div>`;
  }

  function rowsHtml(items, caption) {
    if (!items.length) return '<div class="as-note">찾지 못했습니다.</div>';
    return `${caption ? `<div class="as-cap">${caption}</div>` : ''}${items.map(item => `
      <button type="button" class="as-row" data-as-copy-value="${esc(item.value)}" title="눌러서 복사">
        <span class="as-row-title">${esc(item.title)}</span><span class="as-row-sub">${esc(item.sub || '')}</span>
        <span class="as-row-meta">${esc(item.meta || '')}</span></button>`).join('')}`;
  }

  function render() {
    if (!body) return;
    const r = result;
    if (!r) { body.innerHTML = ''; fit(); return; }
    let html;
    if (r.task === 'scene') {
      html = sceneHtml(r);
    } else if (r.task === 'tag') {
      html = rowsHtml((r.tags || []).map(t => ({ value: t.tag, title: t.tag, sub: t.desc || t.keywords, meta: fmt(t.count) })),
        '태그 — 눌러서 복사');
      if (r.message) html += `<div class="as-note">${esc(r.message)}</div>`;
    } else if (['character', 'artist', 'wildcard', 'preset'].includes(r.task)) {
      html = rowsHtml((r.items || []).map(i => ({ value: i.value, title: i.title || i.value, sub: i.subtitle, meta: i.meta })),
        r.query ? `‘${esc(r.query)}’ 로 찾음 — 눌러서 복사` : '눌러서 복사');
    } else {
      const g = r.guide || {};
      html = `<div class="as-guide"><b>${esc(g.title || '이런 걸 도와드릴 수 있어요')}</b>${(g.examples || []).map(ex =>
        `<button type="button" class="as-example" data-as-example="${esc(ex)}">${esc(ex)}</button>`).join('')}
        ${g.note ? `<div class="as-note">${esc(g.note)}</div>` : ''}</div>`;
    }
    const model = r.model || {};
    if (model.error) {
      const why = model.code === 'model_missing' || model.code === 'engine_missing'
        ? `${model.error} — 한국어 층만으로 찾았습니다.` : `모델을 부르지 못해 한국어 층만으로 찾았습니다 (${model.error}).`;
      html += `<div class="as-note as-note-warn">${esc(why)}</div>`;
    }
    body.innerHTML = html;
    fit();
  }

  function onBodyClick(event) {
    const t = event.target;
    if (t.closest('[data-as-generate]')) { void generateVirtual(); return; }
    if (t.closest('[data-as-apply]')) { void applyPrompt(); return; }
    if (t.closest('[data-as-link]')) { void linkRandom(); return; }
    if (t.closest('[data-as-copy]')) { void copyPrompt(); return; }
    const example = t.closest('[data-as-example]');
    if (example) {
      input.value = example.dataset.asExample;
      onInput();
      input.focus();
      return;
    }
    const row = t.closest('[data-as-copy-value]');
    if (row) void copyText(row.dataset.asCopyValue);
  }

  // ── 넣기 · 연결 · 복사 ──────────────────────────────────────────────────

  function characterPrompts() {
    return (result?.prompt?.characters || []).map(c => String(c.prompt || '').trim()).filter(Boolean);
  }

  function lockActions(on) {
    body.querySelectorAll('.as-act').forEach(b => { b.disabled = !!on; });
    if (!on && !result?.pool?.pins) body.querySelector('[data-as-link]')?.setAttribute('disabled', '');
  }

  /** [생성] — 이 결과를 **가상 프롬프트**로 한 장 뽑는다. 메인 칸·캐릭터 칸은 그대로다
   *  (사용자 지정 2026-09-24: "사용자의 캐릭터 프롬프트를 간섭하면 곤란"). 서버가 메인은 이벤트 맵 [생성] 과 같은
   *  바이패스로, 캐릭터는 이 요청에만 싣는다. 결과는 평소 생성처럼 Result·히스토리로 온다. */
  async function generateVirtual() {
    const p = result?.prompt;
    if (!p?.main) return;
    lockActions(true);
    try {
      const data = await postJson('/api/assist/generate', {
        main: p.main, characters: characterPrompts(), rating: result.rating || rating,
      });
      const n = (data.characters || []).length;
      toast(`생성을 요청했습니다 — 메인·캐릭터 칸은 그대로${n ? ` (가상 캐릭터 ${n}명)` : ''}`, 'success');
    } catch (error) {
      toast(`생성하지 못했습니다 — ${error.message}`, 'error');
    } finally {
      lockActions(false);
    }
  }

  /** [프롬프트에 넣기] — 사용자가 **원할 때만** 칸에 넣는다. 메인은 Random 파이프라인, 캐릭터 칸은 기존을 비활성으로. */
  async function applyPrompt() {
    const p = result?.prompt;
    if (!p?.main) return;
    lockActions(true);
    try {
      const chars = characterPrompts();
      if (chars.length) {
        const sent = typeof applyCharacters === 'function' ? applyCharacters(chars) : false;
        if (!sent) throw new Error('캐릭터 칸에 넣지 못했습니다');
      }
      const tags = String(p.main).split(',').map(t => t.trim()).filter(Boolean);
      await postJson('/api/event-map/apply', { tags, rating: result.rating || rating });
      toast(`프롬프트에 넣었습니다${chars.length ? ` · 캐릭터 ${chars.length}명(기존 칸은 비활성으로)` : ''}`, 'success');
    } catch (error) {
      toast(`넣지 못했습니다 — ${error.message}`, 'error');
    } finally {
      lockActions(false);
    }
  }

  async function linkRandom() {
    const pool = result?.pool;
    if (!pool?.pins) return;
    try {
      const state = await postJson('/api/event-map/random-link', {
        enabled: true, pins: pool.pins, exclude: pool.exclude || '',
        ratings: pool.ratings || rating, persons: pool.persons || '',
      });
      if (typeof onRandomLink === 'function') onRandomLink(state);
      toast('Random·Auto Gen 이 이 조건에서 뽑습니다 (끄기: 이벤트 맵의 [랜덤 버튼 연결])', 'success');
    } catch (error) {
      toast(`Random 연결 실패 — ${error.message}`, 'error');
    }
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(String(text || ''));
      toast('복사했습니다', 'success');
    } catch {
      toast('복사하지 못했습니다', 'error');
    }
  }

  function copyPrompt() {
    const p = result?.prompt;
    if (!p?.main) return;
    const lines = [p.main, ...(p.characters || []).map((c, i) => `캐릭터 ${i + 1}: ${c.prompt}`)];
    return copyText(lines.join('\n'));
  }

  // ── 한국어 분석기(Kiwi) 설치 · 모델 상태 ────────────────────────────────

  async function warm() {
    try { status = await postJson('/api/assist/warm', {}); } catch { return; }
    paintBanner();
    scheduleNames(0);
  }

  function paintBanner() {
    if (!banner) return;
    const kiwi = status?.kiwi || {};
    const parts = [];
    if (kiwi.active) {
      const pct = Math.max(0, Math.min(100, Number(kiwi.percent || 0)));
      parts.push(`<div class="as-banner-row"><span>한국어 분석기 설치 중 — ${esc(kiwi.message || '')}</span></div>
        <div class="as-bar-track"><i style="width:${pct}%"></i></div>`);
      schedulePoll();
    } else if (kiwi.installed === false) {
      parts.push(`<div class="as-banner-row"><span>한국어 분석기(Kiwi)가 없어 이름·동작을 덜 알아봅니다.</span>
        <button type="button" data-as-kiwi-install title="NAIA 를 켠 PC 에서만 설치할 수 있습니다">설치 (약 ${esc(kiwi.approx_mb || 90)}MB)</button></div>`);
      if (kiwi.error) {
        parts.push(`<div class="as-banner-err">${esc(kiwi.error)}${kiwi.manual_command
          ? ` · 직접 설치: <code>${esc(kiwi.manual_command)}</code>` : ''}</div>`);
      }
    }
    if (status && status.model_ready === false) {
      parts.push('<div class="as-banner-row as-banner-dim">E2B 모델이 없어 한국어 층만으로 찾습니다 — Auto Boost 설정의 [모델 받기].</div>');
    }
    banner.innerHTML = parts.join('');
    banner.hidden = !parts.length;
    fit();
  }

  async function installKiwi() {
    try {
      const state = await postJson('/api/assist/kiwi/install', {});
      status = { ...(status || {}), kiwi: state };
      paintBanner();
    } catch (error) {
      toast(error.status === 403 ? '한국어 분석기 설치는 NAIA 를 켠 PC 에서만 할 수 있습니다'
        : `설치를 시작하지 못했습니다 — ${error.message}`, 'error');
    }
  }

  function schedulePoll() {
    if (pollTimer) return;
    pollTimer = setTimeout(async () => {
      pollTimer = null;
      if (!open) return;                      // 창을 닫아도 설치는 계속된다 - 다시 열면 이어서 보여 준다
      const wasActive = !!status?.kiwi?.active;
      try { status = await getJson('/api/assist/status'); } catch { /* 다음에 다시 */ }
      paintBanner();
      if (wasActive && status?.kiwi?.installed) {
        toast('한국어 분석기를 설치했습니다', 'success');
        scheduleNames(0);
      }
    }, INSTALL_POLL_MS);
  }

  // ── 자리 · 열기 · 닫기 ──────────────────────────────────────────────────

  function position() {
    if (!overlay || overlay.hidden) return;
    const host = document.querySelector('#rightTabResult') || document.querySelector('.app-layout');
    const r = host ? host.getBoundingClientRect() : null;
    if (!r || r.width < 240 || r.height < 160) {
      overlay.style.left = '50%';
      overlay.style.transform = 'translateX(-50%)';
      overlay.style.top = '64px';
      overlay.style.width = 'min(680px, calc(100vw - 32px))';
      heightCap = Math.min(520, window.innerHeight - 96);
      fit();
      return;
    }
    const pad = 14;
    const width = Math.round(Math.min(720, Math.max(240, r.width - pad * 2)));
    overlay.style.transform = 'none';
    overlay.style.left = `${Math.round(r.left + (r.width - width) / 2)}px`;
    overlay.style.top = `${Math.round(r.top + pad)}px`;
    overlay.style.width = `${width}px`;
    heightCap = Math.round(Math.min(r.height - pad * 2, Math.max(300, r.height * 0.5)));
    fit();
  }

  function fit() {
    if (!overlay || overlay.hidden || !heightCap) return;
    overlay.style.maxHeight = `${heightCap}px`;
  }

  function reset() {
    recap = null;
    result = null;
    choices.clear();
    notNames.clear();
    names = new Map();
    spans = [];
    closePicker();
    render();
    paintPersons();
    scheduleNames(0);
    input.focus();
    toast('기억과 이름 선택을 지웠습니다', 'info');
  }

  function show() {
    build();
    open = true;
    overlay.hidden = false;
    position();
    autoGrow();
    paintNames();
    input.focus();
    input.select();
    void warm();
  }

  function close() {
    if (!overlay) return;
    open = false;
    overlay.hidden = true;                 // .as-overlay[hidden] 규칙이 실제로 감춘다
    closePicker();
    clearTimeout(namesTimer);
    clearTimeout(pollTimer);
    pollTimer = null;
    namesSeq += 1;
    clearHighlights();
  }

  // Ctrl+O. 브라우저의 '파일 열기' 를 대신 가져온다(preventDefault). 한글 자판에서도 잡히게 code 도 본다.
  // Esc 는 창 안 어디에 포커스가 있든 닫는다 - 후보 팝업이 열려 있으면 그것만 먼저 닫는다.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      event.stopPropagation();
      if (picker && !picker.hidden) { closePicker(); return; }
      close();
      return;
    }
    const hit = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && (event.code === 'KeyO' || String(event.key || '').toLowerCase() === 'o');
    if (!hit) return;
    event.preventDefault();
    if (open) { input.focus(); return; }
    show();
  }, true);

  return { show, close, toggle: () => (open ? close() : show()), isOpen: () => open };
}
