/* Draft Mode — 메인 프롬프트 칸을 포함 · 제외 · Extra 세 칸의 칩 판으로 바꾼다(사용자 구상 2026-11-07).
 *
 * 사양: docs/DRAFT_MODE_SRS_2026_11_07.md · 화면-서버 형식: docs/DRAFT_MODE_API.md(Codex 작업 트리에 함께 둠).
 *
 *  · 투명 BG 옆 [Draft] 알약 - 모든 백엔드에서 보인다(D1). 켜면 서버가 지금 메인 글을 보관했다가 끌 때 되돌린다(D3).
 *  · 칩 상태 · 셈 · 뽑기는 **전부 서버**(D19). 여기서는 그리기 · 입력 · 단추뿐이다. 서버가 보내는 스냅숏 하나가 화면 전체다.
 *  · 메인 칸 글은 서버가 파이프라인으로 조립한 최종 글이다. 숨긴 `#promptEdit` 를 그 글로 늘 맞춘다(재검수 C3) -
 *    Generate 는 여전히 그 칸을 보내고, 서버도 Draft 중에는 자기 글을 쓴다(두 겹).
 *  · prefix / postfix 는 판의 위 · 아래 띠에 펼쳐 둔다(D2 · 사용자 "모두 펼쳐둡니다"). 띠의 글은 PE 칸 그 자체다 -
 *    고치면 PE 에 쓰고, PE 상태가 돌아오면 서버에 다시 조립을 청한다(`/draft/rebuild`).
 *  · 칩 입력: 쉼표 · Enter = 칩으로. 서버가 0건이면 막는다 - 글은 남기고 붉게(D9). 색인 밖 글은 Extra 로 간다(D6).
 *    `*tag` = 퍼펙트(D4). 빈 칸 Backspace = 그 칸 마지막 칩 지우기.
 *  · [Random] 으로 뽑힌 게시물의 태그는 포함 칸이 아니라 **'뽑힌 결과' 떠 있는 창**에 보인다(사용자 지시 11-07 -
 *    포함 칸은 조건만 · 뽑힌 것은 미리보기). 창은 디버그 창들이 처음 뜨는 자리(왼쪽 패널 | 결과 탭 경계)에서 열리고
 *    반투명 · 접기/펼치기. 새로 뽑힐 때마다 열린다 - 이번 Draft 에서 사용자가 닫았으면 [뽑힌 결과] 단추로만 다시 연다.
 *  · ⚠️ 판은 **뼈대를 한 번만** 만든다. 다시 그릴 때는 칩 줄 · 요약만 갈아 끼운다 - 입력 · Extra · 띠 칸을 갈아 끼우면
 *    초점 · 커서 · 자동완성이 날아간다(eventMapStaging 의 같은 교훈).
 */

import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

const RATING_LABEL = { g: 'rating:general', s: 'rating:sensitive', q: 'rating:questionable', e: 'rating:explicit' };
const SUGGEST_DEBOUNCE_MS = 60;   // 이름만 받는 첫 요청은 수 ms(11-07) - 수는 따로 늦게 받는다
const COUNTING_DELAY_MS = 250;

export function initDraftMode({
  host,                          // `.prompt-highlight-wrap` (메인 프롬프트)
  pill,                          // #draftPill
  escHtml,
  showToast = () => {},
  getPeField = () => '',         // (key) => string - PE 칸의 지금 글
  setPeField = () => {},         // (key, text) => void · 못 보내면 던진다
  bindTagAssist = null,          // Extra 칸의 일반 자동완성
  isAutocompleteEnabled = () => true,
  applyServerPrompt = () => {},  // (prompt, source) => void - 숨긴 #promptEdit 를 서버 확정 글로
  takePendingPrompt = () => null,// () => string|null - 안 보낸 메인 글 편집(있으면 지금 보내고 그 글을 돌려준다)
  prepareEnter = async () => ({ ok: true }), // 겹치는 기능(Interactive 등)을 끄거나 막는다 - {ok:false, message}
  dropForeignOwners = () => {},  // 다른 창이 Draft 를 켰다 - 이 탭이 쥔 기능을 원문 복원 없이 내려놓는다(C6)
  openEventMap = () => {},
  openStaging = () => {},
  onActiveChange = () => {},
} = {}) {
  if (!host || !pill) return null;
  // app.js 의 escHtml 은 글만 받는다(숫자 rid 를 넣자 throw -> 그리기 전체가 멈췄다, 11-07 실측) - 늘 글로 바꿔 넘긴다.
  const esc = escHtml ? (s => escHtml(String(s ?? ''))) : (s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
  const fmt = n => (Number.isFinite(n) ? Number(n).toLocaleString('en-US') : '');

  let snap = null;                // 마지막으로 받은 스냅숏
  let gen = null, rev = -1;
  let busy = 0;
  let pendingRebuild = false;     // 띠에서 PE 를 고쳤다 - PE 상태가 돌아오면 다시 조립
  let menuEl = null;
  const active = () => !!snap?.state?.active;

  // ---- 서버 ----
  async function request(path, body, { method } = {}) {
    const res = await fetch(`/api/event-map${path}`, {
      method: method || (body ? 'POST' : 'GET'), cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(30000),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      if (data.snapshot) receive(data.snapshot);
      throw Object.assign(new Error(data.message || `HTTP ${res.status}`), { code: data.error || '', status: res.status, data });
    }
    return data;
  }
  /** 판 번호(base_rev)를 싣는 편집은 **한 줄로** 보낸다. 앞 요청이 끝나기 전에 다음 칩을 치면 옛 판 번호가 나가
   *  `stale` 로 거절됐다(실측 11-07: '*1girl' Enter 직후 'smile' Enter -> 빨간 칸). 판 번호는 차례가 왔을 때 읽는다. */
  let editChain = Promise.resolve();
  function edit(path, body) {
    // 받은 판을 여기서 바로 싣는다 - 다음 차례가 새 판 번호를 읽게(receive 는 옛 판을 버리므로 두 번 불려도 된다)
    const run = () => request(path, { ...body, base_rev: rev }).then(data => { receive(data); return data; });
    const next = editChain.then(run, run);
    editChain = next.catch(() => {});
    return next;
  }
  /** 같은 세대의 옛 판은 버린다 - 세대가 바뀌었으면(파일을 새로 만들었다) 판 번호와 상관없이 받는다. */
  function fresh(data) {
    if (!data || data.gen == null) return false;
    return data.gen !== gen || Number(data.rev) >= rev;
  }
  function receive(data) {
    if (!fresh(data)) return;
    const was = active();
    snap = data;
    gen = data.gen;
    rev = Number(data.rev) || 0;
    const now = active();
    if (now && !was) shownRid = null;
    if (now && !was && data.__fromSocket) dropForeignOwners();
    if (typeof data.prompt === 'string' && (now || was)) applyServerPrompt(data.prompt, 'event_map_draft');
    paint();
    if (now !== was) onActiveChange(now);
  }
  async function load() {
    try { receive(await request('/draft')); } catch (_) { /* 색인 · 서버가 아직이면 알약만 꺼진 채로 */ paintPill(); }
  }
  async function run(fn, { quiet = false } = {}) {
    busy++;
    paintPill();
    try { return await fn(); }
    catch (error) {
      if (!quiet) showToast(error.message || 'Draft 요청 실패', 'error');
      throw error;
    } finally { busy--; paintPill(); }
  }

  // ---- 켜기 · 끄기 ----
  async function enter() {
    if (active()) return;
    if (snap && snap.available === false) {
      showToast('이벤트 맵 색인이 없습니다 — 이벤트 맵(Ctrl+E)에서 먼저 받으세요', 'warning');
      openEventMap();
      return;
    }
    const ready = await prepareEnter();
    if (!ready?.ok) { if (ready?.message) showToast(ready.message, 'warning'); return; }
    const pending = takePendingPrompt();
    try {
      receive(await run(() => request('/draft/enter', pending == null ? {} : { prompt: pending }), { quiet: true }));
    } catch (error) {
      if (error.code === 'owned_by') showToast('인페인트 세션을 닫은 뒤 Draft 를 켜세요', 'warning');
      else if (error.code === 'unavailable') { showToast('이벤트 맵 색인이 없습니다 — 이벤트 맵(Ctrl+E)에서 먼저 받으세요', 'warning'); openEventMap(); }
      else showToast(error.message || 'Draft 를 켜지 못했습니다', 'error');
    }
  }
  async function exit({ toast = '' } = {}) {
    if (!active()) return;
    closeMenu();
    hideSuggest();
    await flushExtra();
    try {
      receive(await run(() => request('/draft/exit', {})));
      if (toast) showToast(toast, 'info');
    } catch (_) { /* run 이 알렸다 */ }
  }
  pill.addEventListener('click', () => { if (busy) return; if (active()) void exit(); else void enter(); });

  // ---- 판 뼈대(한 번만) ----
  const board = document.createElement('div');
  board.className = 'dr-board';
  board.hidden = true;
  board.innerHTML = `
    <div class="dr-band dr-band--pre"><span class="dr-band-name">prefix</span>
      <textarea class="dr-band-text" data-dr-pe="pre_prompt" rows="1" spellcheck="false" aria-label="Prefix Prompt"></textarea></div>
    <div class="dr-sum" data-dr-sum></div>
    <div class="dr-zone" data-dr-zone="include">
      <div class="dr-zh"><span class="dr-zt">포함</span></div>
      <div class="dr-chips" data-dr-chips="include"></div>
      <div class="dr-zone-foot" data-dr-drawn-foot hidden>
        <button type="button" class="dr-drawn-btn" data-dr-drawn-open aria-pressed="false"></button>
      </div>
    </div>
    <div class="dr-zone" data-dr-zone="exclude">
      <div class="dr-zh"><span class="dr-zt dr-zt--ex">제외</span></div>
      <div class="dr-chips" data-dr-chips="exclude"></div>
    </div>
    <div class="dr-zone dr-zone--extra">
      <div class="dr-zh"><span class="dr-zt">Extra</span></div>
      <textarea class="dr-extra-text" data-dr-extra rows="2" maxlength="2000" spellcheck="false" aria-label="Extra Prompt"
        placeholder="고정적으로 추가하고 싶은 태그를 자유롭게 작성합니다."></textarea>
    </div>
    <div class="dr-band dr-band--post"><span class="dr-band-name">postfix</span>
      <textarea class="dr-band-text" data-dr-pe="post_prompt" rows="1" spellcheck="false" aria-label="Postfix Prompt"></textarea></div>
    <div class="dr-suggest" data-dr-suggest hidden role="listbox"></div>`;
  const footer = host.querySelector('.prompt-token-footer');
  host.insertBefore(board, footer || null);
  const extraEl = board.querySelector('[data-dr-extra]');
  let extraShown = null;   // 칸에 마지막으로 반영한 서버 Extra - 칸의 글이 이것과 다르면 아직 저장 못 한 사용자 글
  const sumEl = board.querySelector('[data-dr-sum]');
  const suggestEl = board.querySelector('[data-dr-suggest]');
  const bands = [...board.querySelectorAll('[data-dr-pe]')];
  // [이번에 뽑힌 프롬프트 : N] - 포함 칸 오른쪽 아래(사용자 지시 11-07). 새로 뽑힐 때마다 배경이 깜빡인다(Usage 알약처럼).
  const drawnFootEl = board.querySelector('[data-dr-drawn-foot]');
  const drawnBtnEl = board.querySelector('.dr-drawn-btn');
  let lastDrawnRid;          // undefined = 아직 안 그렸다 - 새로고침 · 처음 그릴 때는 깜빡이지 않는다
  let drawnFlashPending = false;
  drawnBtnEl.addEventListener('animationend', () => drawnBtnEl.classList.remove('is-flash'));
  // 단추 위에 마우스 = 실제로 들어간 태그만 반투명 판에 미리보기(사용자 지시 11-07).
  // PE 가 지운 것 · 이번만 뺀 것은 넣지 않는다. 상세보기 창이 열려 있으면 띄우지 않는다.
  const peekEl = document.createElement('div');
  peekEl.className = 'dr-drawn-peek';
  peekEl.hidden = true;
  document.body.appendChild(peekEl);
  function showPeek() {
    if (!active() || !snap?.state?.drawn || drawnPanel?.isOpen()) { hidePeek(); return; }
    const tags = (snap?.derived?.gray || []).filter(g => !g.dropped && !g.pe_hidden).map(g => g.tag);
    peekEl.textContent = tags.length ? tags.join(', ') : '들어간 태그가 없습니다';
    peekEl.hidden = false;
    const r = drawnBtnEl.getBoundingClientRect();
    const w = Math.min(420, window.innerWidth - 16);
    peekEl.style.width = `${w}px`;
    const h = peekEl.offsetHeight;
    // 왼쪽 판 바깥 오른쪽(결과 화면 위)에 - 판 안에 띄우면 칩을 가린다(사용자 지시 11-07). 판 옆 E · S · A 탭도 비켜 간다.
    // 아래 끝을 단추 아래 끝에 맞춘다. 오른쪽에 자리가 없으면(좁은 화면) 단추 위로.
    const panel = board.closest('.control-panel')?.getBoundingClientRect();
    let edge = panel ? panel.right : 0;
    document.querySelectorAll('.em-tab').forEach(tab => {
      const t = tab.getBoundingClientRect();
      if (t.width && t.left < edge + 8 && t.right > edge - 8) edge = Math.max(edge, t.right);
    });
    if (panel && edge + 12 + w <= window.innerWidth - 8) {
      peekEl.style.left = `${edge + 12}px`;
      peekEl.style.top = `${Math.max(8, Math.min(r.bottom - h, window.innerHeight - h - 8))}px`;
      return;
    }
    peekEl.style.left = `${Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8))}px`;
    const top = r.top - h - 8 >= 8 ? r.top - h - 8 : Math.min(r.bottom + 8, window.innerHeight - h - 8);
    peekEl.style.top = `${Math.max(8, top)}px`;
  }
  function hidePeek() { peekEl.hidden = true; }
  drawnBtnEl.addEventListener('mouseenter', showPeek);
  drawnBtnEl.addEventListener('mouseleave', hidePeek);
  drawnBtnEl.addEventListener('click', hidePeek);

  // ---- 칸 높이 손잡이(사용자 지시 11-07) ----
  // 칸 위 색 줄이 곧 손잡이다: 제외 위 줄 = 포함 높이 · Extra 위 줄 = 제외 높이 · postfix 위 줄 = Extra 높이.
  // 끈 칸만 고정 높이가 되고 나머지는 남은 높이를 나눠 갖는다. 최소 = 칩 두 줄(Extra 는 글 두 줄). 두 번 누르면 기본으로.
  // 높이는 이 브라우저에만 기억한다(화면 취향 - 서버에 두지 않는다. PC · 휴대폰이 서로 덮지 않게).
  const ZONE_KEY = 'naia.draft.zoneHeights.v1';
  const zoneEls = {
    include: board.querySelector('.dr-zone[data-dr-zone="include"]'),
    exclude: board.querySelector('.dr-zone[data-dr-zone="exclude"]'),
    extra: board.querySelector('.dr-zone--extra'),
  };
  // 손잡이는 칸 **사이**의 높이 0 짜리 형제다 - 칸 안에 두면 고정 높이 칸의 넘침(스크롤)에 잘린다.
  const handleBefore = { include: zoneEls.exclude, exclude: zoneEls.extra, extra: board.querySelector('.dr-band--post') };
  function readZoneHeights() {
    try {
      const v = JSON.parse(localStorage.getItem(ZONE_KEY) || '{}');
      return v && typeof v === 'object' ? v : {};
    } catch (_) { return {}; }
  }
  function writeZoneHeights(v) { try { localStorage.setItem(ZONE_KEY, JSON.stringify(v)); } catch (_) {} }
  function setZoneHeight(name, px) {
    const el = zoneEls[name];
    if (px == null) { el.classList.remove('is-sized'); el.style.height = ''; return; }
    el.classList.add('is-sized');
    el.style.height = `${Math.round(px)}px`;
  }
  /** 칩 두 줄(Extra 는 글 두 줄)이 들어가는 높이 - 끌기 시작할 때 잰다(판이 보일 때). */
  function zoneMin(name) {
    const el = zoneEls[name];
    const cs = getComputedStyle(el);
    const box = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + parseFloat(cs.borderTopWidth);
    const head = el.querySelector('.dr-zh');
    const headH = head ? head.offsetHeight + (parseFloat(getComputedStyle(head).marginBottom) || 0) : 0;
    if (name === 'extra') {
      const lh = parseFloat(getComputedStyle(extraEl).lineHeight) || 18;
      return Math.ceil(box + headH + lh * 2 + 2);
    }
    const chips = el.querySelector('.dr-chips');
    const chip = chips.querySelector('.dr-chip');
    const row = Math.max(chip ? chip.offsetHeight : 0, 22);
    const gap = parseFloat(getComputedStyle(chips).rowGap) || 5;
    const foot = el.querySelector('.dr-zone-foot');
    const footH = foot && !foot.hidden ? foot.offsetHeight : 0;
    return Math.ceil(box + headH + row * 2 + gap + footH);
  }
  Object.entries(handleBefore).forEach(([name, next]) => {
    if (!next) return;
    const h = document.createElement('div');
    h.className = `dr-rh dr-rh--${name}`;
    h.dataset.drRh = name;
    h.title = '끌어서 위 칸 높이 조정 · 두 번 누르면 기본';
    h.setAttribute('aria-hidden', 'true');
    next.before(h);
  });
  {
    const saved = readZoneHeights();
    Object.keys(zoneEls).forEach(name => {
      const v = Number(saved[name]);
      if (Number.isFinite(v) && v > 0) setZoneHeight(name, v);
    });
  }
  board.addEventListener('pointerdown', event => {
    const h = event.target.closest?.('[data-dr-rh]');
    if (!h || event.button !== 0) return;
    const name = h.dataset.drRh;
    const el = zoneEls[name];
    event.preventDefault();
    const y0 = event.clientY;
    const h0 = el.getBoundingClientRect().height;
    const min = zoneMin(name);
    let last = h0;
    let moved = false;
    h.classList.add('is-drag');
    try { h.setPointerCapture(event.pointerId); } catch (_) {}
    const move = ev => {
      moved = true;
      last = Math.max(min, Math.min(900, h0 + ev.clientY - y0));
      setZoneHeight(name, last);
    };
    const up = () => {
      h.classList.remove('is-drag');
      h.removeEventListener('pointermove', move);
      h.removeEventListener('pointerup', up);
      h.removeEventListener('pointercancel', up);
      if (!moved) return;
      const saved = readZoneHeights();
      saved[name] = Math.round(last);
      writeZoneHeights(saved);
    };
    h.addEventListener('pointermove', move);
    h.addEventListener('pointerup', up);
    h.addEventListener('pointercancel', up);
  });
  board.addEventListener('dblclick', event => {
    const h = event.target.closest?.('[data-dr-rh]');
    if (!h) return;
    event.preventDefault();
    const name = h.dataset.drRh;
    setZoneHeight(name, null);
    const saved = readZoneHeights();
    delete saved[name];
    writeZoneHeights(saved);
  });
  const inputs = {};
  ['include', 'exclude'].forEach(zone => {
    const input = document.createElement('input');
    input.className = 'dr-in';
    input.dataset.drIn = zone;
    input.spellcheck = false;
    input.autocomplete = 'off';
    input.placeholder = zone === 'include' ? '태그, 쉼표 · *tag 퍼펙트' : '뺄 태그, 쉼표';
    input.setAttribute('aria-label', zone === 'include' ? '포함 태그 입력' : '제외 태그 입력');
    const counting = document.createElement('span');
    counting.className = 'dr-counting';
    counting.hidden = true;
    counting.textContent = '세는 중…';
    inputs[zone] = { input, counting };
  });
  if (bindTagAssist) { try { bindTagAssist(extraEl, {}); } catch (_) {} }

  // ---- 뽑힌 결과 창 ----
  const drawnEl = document.createElement('div');
  drawnEl.className = 'drw-body';
  // 뽑힌 결과 창은 저절로 열지 않는다 - [이번에 뽑힌 프롬프트 : N] 을 눌렀을 때만(사용자 지시 11-07).
  let drawnPanel = null;
  let shownRid = null;          // 창 글이 보여 주는 게시물 - [이 결과를 메인 프롬프트로] 는 이 게시물로만
  function ensureDrawnPanel() {
    if (drawnPanel) return drawnPanel;
    drawnPanel = createDraggablePanel({
      document, window, title: '뽑힌 결과', variant: 'drw', storageKey: 'draft-drawn',
      width: 340, minWidth: 240, maxWidth: 720, height: 320, minHeight: 120, resizable: true, escHtml: esc,
      onClose: () => {
        closeMenu();
        paintSum();
      },
    });
    drawnPanel.body.appendChild(drawnEl);
    // [이 결과를 메인 프롬프트로](사용자 지시 11-07) - Draft 를 끄고 이 결과로 조립된 글을 메인 칸에 남겨 바로 고치게 한다.
    const foot = document.createElement('div');
    foot.className = 'drw-foot';
    foot.innerHTML = '<button type="button" class="ctrl-btn drw-keep" data-drw-keep'
      + ' title="Draft 를 끄고 이 결과(뽑힌 태그 + 내 칩 + Extra)로 조립된 글을 메인 프롬프트에 남깁니다">이 결과를 메인 프롬프트로</button>';
    foot.addEventListener('click', event => { if (event.target.closest('[data-drw-keep]')) void keepToMain(); });
    drawnPanel.body.appendChild(foot);
    drawnEl.addEventListener('click', event => {
      const gray = event.target.closest('[data-dr-gray]');
      if (gray) grayMenu(gray);
    });
    drawnEl.addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const el = event.target.closest?.('[data-dr-gray]');
      if (!el || event.target !== el) return;
      event.preventDefault();
      grayMenu(el);
    });
    return drawnPanel;
  }
  function closeDrawnPanel() {
    if (drawnPanel?.isOpen()) drawnPanel.close();
  }
  function openDrawnPanel() {
    const panel = ensureDrawnPanel();
    const rid = snap?.state?.drawn?.rid;
    if (rid != null) panel.setTitle(`뽑힌 결과 · #${rid}`);
    if (!panel.isOpen()) panel.open();
    if (panel.isCollapsed()) panel.expand();
    panel.raise();
  }
  async function keepToMain() {
    if (!active() || busy) return;
    const rid = snap?.state?.drawn?.rid;
    // 창이 보여 주는 게시물로만 - 서버도 rid 가 지금 것이 아니면 거절한다(stale)
    if (rid == null || rid !== shownRid) return;
    closeMenu();
    hideSuggest();
    if (!(await flushExtra())) return;
    if (!active() || snap?.state?.drawn?.rid !== rid) return;   // 저장하는 사이 다른 탭이 끄거나 다시 뽑았다
    try {
      receive(await run(() => request('/draft/exit', { keep: true, rid })));
    } catch (_) { return; /* run 이 알렸다 */ }
    showToast('이 결과를 메인 프롬프트로 옮겼습니다 - Draft 를 껐습니다', 'info');
    requestAnimationFrame(() => {
      const editor = document.getElementById('promptEdit');
      if (!editor || editor.offsetParent === null) return;
      editor.focus();
      try { const end = editor.value.length; editor.setSelectionRange(end, end); } catch (_) {}
    });
  }
  function toggleDrawnPanel() {
    if (drawnPanel?.isOpen()) { drawnPanel.close(); return; }
    openDrawnPanel();
    paintSum();
  }

  // ---- 그리기 ----
  function paintPill() {
    const on = active();
    pill.setAttribute('aria-pressed', on ? 'true' : 'false');
    pill.classList.toggle('is-busy', busy > 0);
    const mark = pill.querySelector('.draft-pill-mark');
    if (mark) mark.textContent = on ? 'v' : 'x';
    pill.title = snap && snap.available === false
      ? 'Draft Mode - 이벤트 맵 색인이 있어야 씁니다'
      : (on ? 'Draft Mode 끄기 - 켜기 전 프롬프트로 돌아갑니다' : 'Draft Mode - 이벤트 맵 칩으로 프롬프트를 짭니다');
  }
  function derivedOf(list, id) { return (list || []).find(d => d.id === id) || {}; }
  function chipHtml(chip, zone, d) {
    const label = (chip.exact ? '*' : '') + (zone === 'exclude' ? '-' : '') + chip.text;
    const count = Number.isFinite(d.count) ? `<span class="dr-c">(${fmt(d.count)})</span>` : '';
    const hits = (!chip.exact && d.hits > 1) ? `<span class="dr-k" title="이름에 '${esc(chip.text)}' 가 든 태그 ${fmt(d.hits)}개를 함께 셉니다">≈${fmt(d.hits)}태그</span>` : '';
    const out = (!chip.exact && Array.isArray(d.chip_hits) && d.chip_hits.length && !(d.chip_hits.length === 1 && d.chip_hits[0] === chip.text))
      ? `<span class="dr-hit" title="뽑힌 게시물에서 이 칩에 걸린 태그">→ ${esc(d.chip_hits.join(', '))}</span>` : '';
    const cls = `dr-chip${chip.exact ? ' is-exact' : ''}${zone === 'exclude' ? ' is-ex' : ''}`;
    return `<span class="${cls}" data-dr-chip="${esc(chip.id)}" data-dr-zone="${zone}" tabindex="0" role="button"
      title="${chip.exact ? '퍼펙트 매칭' : '텍스트 매칭'} - 눌러서 바꾸기 · 옮기기"><span class="dr-t">${esc(label)}</span>${count}${hits}${out}<span class="dr-x" data-dr-del aria-label="지우기">×</span></span>`;
  }
  function tagChipHtml(id, label, title, extraClass = '') {
    return `<span class="dr-chip is-tag${extraClass}" data-dr-chip="${esc(id)}" data-dr-tag title="${esc(title)}"><span class="dr-t">${esc(label)}</span><span class="dr-x" data-dr-del aria-label="지우기">×</span></span>`;
  }
  function paintZone(zone) {
    const box = board.querySelector(`[data-dr-chips="${zone}"]`);
    const st = snap?.state || {};
    const der = snap?.derived || {};
    let html = '';
    if (zone === 'include') {
      html += (st.ratings || []).map(r => tagChipHtml(`r:${r}`, RATING_LABEL[r] || r, '등급 - 여럿이면 그중 하나(OR)', ' is-rating')).join('');
      if ((st.tags?.persons || []).length) html += tagChipHtml('persons', `인원: ${der.persons_label || st.tags.persons.join(', ')}`, '스테이징에서 온 인원 분면 - 지우기만 됩니다');
      html += (st.include || []).map(c => chipHtml(c, 'include', derivedOf(der.include, c.id))).join('');
    } else {
      html += (st.exclude || []).map(c => chipHtml(c, 'exclude', derivedOf(der.exclude, c.id))).join('');
      html += (st.tags?.groups || []).map(g => tagChipHtml(g.id, `-(${(g.terms || []).join(' · ')})`, '스테이징에서 온 묶음 제외 - 이 낱말을 모두 가진 게시물을 뺍니다 · 지우기만 됩니다', ' is-ex')).join('');
    }
    // 입력칸 노드는 살린다 - 칩만 갈아 끼우고 입력칸을 끝에 다시 붙인다.
    const { input, counting } = inputs[zone];
    // 입력칸 · '세는 중' 노드는 떼지 않고 칩만 갈아 끼운다 - 떼었다 붙이면 포커스가 빠져 칩 하나를 넣을 때마다
    // 입력칸을 다시 눌러야 했다(Codex 리뷰 11-07).
    [...box.childNodes].forEach(node => { if (node !== input && node !== counting) node.remove(); });
    if (input.parentNode !== box) box.append(input);
    if (counting.parentNode !== box) box.append(counting);
    input.insertAdjacentHTML('beforebegin', html);
  }
  function paintDrawn() {
    const st = snap?.state || {};
    const der = snap?.derived || {};
    const drawn = st.drawn;
    if (!drawn) {
      drawnEl.innerHTML = '';
      shownRid = null;
      lastDrawnRid = null;
      closeDrawnPanel();
      return;
    }
    if (lastDrawnRid !== undefined && drawn.rid !== lastDrawnRid) drawnFlashPending = true;
    lastDrawnRid = drawn.rid;
    const gray = der.gray || [];
    // PE 가 지운 태그는 쓸모가 없으니 아래 '숨겨진 태그:' 한 줄로(사용자 지시 11-07). 이번만 뺀 태그는 위 줄에 둔다 - 눌러 다시 넣는다.
    // (이번만 뺀 태그도 프롬프트에 없어 pe_hidden 이 켜진다 - 그래서 dropped 를 먼저 본다)
    const isHidden = g => g.pe_hidden && !g.dropped;
    const shown = gray.filter(g => !isHidden(g));
    const hiddenTags = gray.filter(isHidden);
    const applied = shown.filter(g => !g.dropped).length;
    const head = `${applied}개 들어감${hiddenTags.length ? ` · PE 가 ${hiddenTags.length}개 숨김` : ''}`;
    if (drawnPanel) drawnPanel.setTitle(`뽑힌 결과 · #${drawn.rid}`);
    shownRid = drawn.rid;
    // 칩이 아니라 **글**로 - 쉼표로 이은 태그 줄(사용자 지시 11-07). 낱말을 누르면 같은 메뉴(고정 · 제외 · 이번만 빼기).
    const tagHtml = g => `<span class="drw-tag${isHidden(g) ? ' is-pe-hidden' : ''}${g.dropped ? ' is-dropped' : ''}" data-dr-gray="${esc(g.tag)}" tabindex="0" role="button"
        title="${g.dropped ? '이번만 뺀 태그 - 눌러서 다시 넣기' : (isHidden(g) ? 'PE 필터가 지운 태그' : '뽑힌 태그 · 다음 Random 에 바뀜')}">${esc(g.tag)}</span>`;
    drawnEl.innerHTML = `<div class="drw-meta">${head}</div><div class="drw-text">${shown.map(tagHtml).join(', ')}</div>`
      + (hiddenTags.length ? `<div class="drw-hidden"><span class="drw-hidden-k">숨겨진 태그:</span> ${hiddenTags.map(tagHtml).join(', ')}</div>` : '');
  }
  function paintSum() {
    const der = snap?.derived || {};
    const remaining = der.remaining;
    const rating = der.rating_out ? `<span class="dr-rating" title="이 등급 태그가 프롬프트에 들어갑니다">${esc(der.rating_out)}</span>` : '';
    sumEl.innerHTML = `<span>남은 게시물</span><span class="dr-big">${remaining == null ? '—' : fmt(remaining)}</span>${rating}
      <span class="dr-gap"></span>
      <button type="button" class="dr-btn dr-btn--icon" data-dr-stage title="스테이징으로 보내기 - 지금 칩 조건을 스테이징 줄 하나로"
        aria-label="스테이징으로 보내기">&rarr;</button>
      <button type="button" class="dr-btn" data-dr-from title="S 창을 엽니다 - 줄의 [드래프트로 불러오기]">불러오기</button>`;
    paintDrawnBtn();
  }
  function paintDrawnBtn() {
    const drawn = snap?.state?.drawn;
    drawnFootEl.hidden = !drawn;
    if (!drawn) { drawnFlashPending = false; return; }
    const open = !!drawnPanel?.isOpen();
    const n = (snap?.derived?.gray || []).filter(g => !g.dropped).length;
    drawnBtnEl.textContent = `이번에 뽑힌 프롬프트 : ${fmt(n)}`;
    drawnBtnEl.classList.toggle('is-on', open);
    drawnBtnEl.setAttribute('aria-pressed', String(open));
    drawnBtnEl.title = '누르면 상세보기 창이 열립니다';
    if (!peekEl.hidden) showPeek();   // 마우스를 올린 채 새로 뽑혔다 - 미리보기도 새 글로
    if (drawnFlashPending) {
      drawnFlashPending = false;
      drawnBtnEl.classList.remove('is-flash');
      void drawnBtnEl.offsetWidth;   // 같은 애니메이션을 다시 처음부터
      drawnBtnEl.classList.add('is-flash');
    }
  }
  function paintBands() {
    bands.forEach(el => {
      if (el === document.activeElement) return;
      const text = String(getPeField(el.dataset.drPe) || '');
      if (el.value !== text) el.value = text;
      fitBand(el);
    });
  }
  function fitBand(el) {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 90)}px`;
  }
  function paint() {
    paintPill();
    const on = active();
    board.hidden = !on;
    document.body.classList.toggle('draft-mode', on);
    if (!on) { closeMenu(); hideSuggest(); closeDrawnPanel(); hidePeek(); return; }
    paintZone('include');
    paintZone('exclude');
    paintDrawn();
    paintSum();
    paintBands();
    // 저장 못 한 Extra(칸의 글 != 마지막으로 받은 서버 글)는 덮지 않는다 - 저장이 409 로 실패하면 request() 가 오류 응답의
    // 스냅숏을 먼저 그려 친 글이 옛 값으로 사라졌다(Codex 재리뷰 11-07). 저장되면(서버 글 = 칸의 글) 다시 서버를 따른다.
    const extraText = String(snap?.state?.extra || '');
    const extraUnsaved = extraShown !== null && extraEl.value !== extraShown;
    if (extraEl !== document.activeElement && !extraUnsaved && extraEl.value !== extraText) extraEl.value = extraText;
    if (extraEl.value === extraText) extraShown = extraText;   // 칸이 실제로 서버 글을 보일 때만(포커스 중엔 안 썼다 - Codex 3차)
  }

  // ---- 칩 입력 ----
  function markBad(zone, on) { inputs[zone].input.classList.toggle('is-bad', !!on); }
  /** 칩 하나 넣기. 넣었으면(또는 넣을 것이 없으면) true - 붙여 넣기 루프는 false 에서 멈추고 남은 글을 되돌린다. */
  async function commit(zone, raw) {
    const text = String(raw || '').trim().replace(/,+$/, '').trim();
    if (!text) return true;
    const { input, counting } = inputs[zone];
    hideSuggest();
    // 칩이 Extra 로 갈 수 있다(색인 밖 태그) - 저장 못 한 Extra 가 있으면 먼저 저장한다. 못 하면 멈춘다: 그대로 두면
    // 서버가 붙인 태그는 칸에 안 보이고 다음 저장이 그것을 지웠다(Codex 3차 11-07).
    if (!(await flushExtra())) return false;
    const timer = setTimeout(() => { counting.hidden = false; }, COUNTING_DELAY_MS);
    try {
      const data = await edit('/draft/chips', { op: 'add', zone, text });
      receive(data);
      if (input.value.trim().replace(/,+$/, '').trim() === text) input.value = '';
      markBad(zone, false);
      if (data.routed === 'extra') {
        extraEl.classList.remove('is-flash');
        void extraEl.offsetWidth;
        extraEl.classList.add('is-flash');
        showToast(`'${text}' 은(는) 이벤트 맵에 없어 Extra 로 보냈습니다`, 'info');
      }
      return true;
    } catch (error) {
      markBad(zone, true);
      if (error.code !== 'zero_match') showToast(error.message || '칩을 넣지 못했습니다', 'warning');
      else showToast(error.message || '이 조건이면 남는 게시물이 없습니다', 'warning');
      return false;
    } finally {
      clearTimeout(timer);
      counting.hidden = true;
    }
  }
  /** 쉼표로 나뉜 여러 조각을 하나씩 칩으로. 처음 실패에서 멈추고 그 조각과 남은 조각을 입력칸 앞에 되돌린다 -
   *  입력칸에서 먼저 지운 뒤라 그냥 멈추면 사라졌다(Codex 4차 11-07). 붙여 넣기 · Enter · 쉼표 키가 같이 쓴다. */
  async function commitParts(zone, parts) {
    const { input } = inputs[zone];
    for (let i = 0; i < parts.length; i++) {
      if (await commit(zone, parts[i])) continue;
      const rest = parts.slice(i).map(part => part.trim()).filter(Boolean).join(', ');
      if (rest) input.value = input.value.trim() ? `${rest}, ${input.value.trim()}` : rest;
      return false;
    }
    return true;
  }
  async function chipOp(body) {
    try { receive(await edit('/draft/chips', body)); }
    catch (error) { showToast(error.message || 'Draft 요청 실패', error.code === 'zero_match' ? 'warning' : 'error'); }
  }
  async function drawnOp(op, tag) {
    try { receive(await edit('/draft/drawn', { op, tag })); }
    catch (error) { showToast(error.message || 'Draft 요청 실패', error.code === 'zero_match' ? 'warning' : 'error'); }
  }
  function lastChipId(zone) {
    const st = snap?.state || {};
    if (zone === 'include') {
      if ((st.include || []).length) return st.include[st.include.length - 1].id;
      if ((st.tags?.persons || []).length) return 'persons';
      if ((st.ratings || []).length) return `r:${st.ratings[st.ratings.length - 1]}`;
      return '';
    }
    if ((st.tags?.groups || []).length) return st.tags.groups[st.tags.groups.length - 1].id;
    if ((st.exclude || []).length) return st.exclude[st.exclude.length - 1].id;
    return '';
  }
  Object.entries(inputs).forEach(([zone, { input }]) => {
    input.addEventListener('keydown', event => {
      if (event.isComposing) return;
      if (handleSuggestKey(event, zone)) return;
      if (event.key === 'Enter' || event.key === ',') {
        event.preventDefault();
        // 되돌려 놓은 'a, b' 처럼 쉼표가 든 글은 붙여 넣기와 같이 조각마다 - 통째로 보내면 색인 밖 글로 Extra 에 들어가
        // 제외하려던 태그가 프롬프트에 들어갔다(Codex 5차 11-07).
        const text = input.value;
        if (text.includes(',')) { input.value = ''; void commitParts(zone, text.split(',')); }
        else void commit(zone, text);
        return;
      }
      if (event.key === 'Backspace' && !input.value) {
        const id = lastChipId(zone);
        if (id) { event.preventDefault(); void chipOp({ op: 'remove', id }); }
      }
    });
    input.addEventListener('input', () => {
      markBad(zone, false);
      // 붙여 넣은 글에 쉼표가 있으면 앞부분부터 칩으로(하나씩 - 서버 판정을 차례로 받는다).
      if (input.value.includes(',')) {
        const parts = input.value.split(',');
        input.value = parts.pop();
        void commitParts(zone, parts);
        return;
      }
      scheduleSuggest(zone);
    });
    input.addEventListener('blur', () => setTimeout(() => { if (!board.contains(document.activeElement)) hideSuggest(); }, 120));
  });

  // ---- 자동완성(포함 · 제외 = 맵 색인 안) ----
  // 두 번에 나눠 받는다(사용자 지시 11-07: 자동완성은 미리, 수만 잠시 후에): 이름 20개(counts=0 · 수 ms) 를 바로 띄우고,
  // 입력이 멈추면 같은 20개의 수(counts=1)를 받아 **제자리에** 채운다 - 줄 차례는 안 바뀐다(고르던 줄이 도망가지 않게).
  const SUGGEST_COUNT_DELAY_MS = 180;
  let suggestTimer = null, countTimer = null, suggestSeq = 0, suggestZone = '', suggestItems = [], suggestIndex = -1;
  let suggestQ = '';   // 지금 떠 있는 목록이 어느 입력의 것인가 - 다른 글이면 키보드로 고르지 못한다(옛 목록에서 Enter = 엉뚱한 칩)
  function hideSuggest() {
    // 기다리는 조회도 끊는다 - Escape 로 닫은 뒤 늦게 온 이름 응답이 목록을 다시 열었다(Codex 리뷰 11-07)
    clearTimeout(suggestTimer);
    clearTimeout(countTimer);
    suggestSeq++;
    suggestEl.hidden = true;
    suggestEl.innerHTML = '';
    suggestItems = [];
    suggestIndex = -1;
    suggestZone = '';
    suggestQ = '';
  }
  function scheduleSuggest(zone) {
    clearTimeout(suggestTimer);
    clearTimeout(countTimer);
    let enabled = true;
    try { enabled = isAutocompleteEnabled() !== false; } catch (_) {}
    const q = inputs[zone].input.value.trim();
    if (!enabled || q.replace(/^\*/, '').length < 1) { hideSuggest(); return; }
    suggestTimer = setTimeout(() => void loadSuggest(zone, q), SUGGEST_DEBOUNCE_MS);
  }
  function suggestCountHtml(it, zone) {
    // 서버는 0건 후보도 blocked 로 준다 - '영구 제외' 는 수가 0 이 아닌데 막힌 것뿐이다.
    if (it.blocked && it.count_after !== 0 && (it.count_after != null || it.kind === 'tag')) return '<span class="dr-sg-n">영구 제외</span>';
    if (it.slow) return '<span class="dr-sg-n" title="걸리는 태그가 많아 세지 않았습니다">…</span>';
    // 후보 수는 그 태그 하나로 센 값이다 - 텍스트 칩이면 포함 칸은 하한(≥) · 제외 칸은 남는 수의 상한(≤).
    if (Number.isFinite(it.count_after)) {
      return `<span class="dr-sg-n">${zone === 'exclude' ? '남음 ' : ''}${it.bound === 'min' ? '≥' : (it.bound === 'max' ? '≤' : '')}${fmt(it.count_after)}</span>`;
    }
    return '<span class="dr-sg-n is-pending" aria-hidden="true"></span>';
  }
  function suggestRowClass(it) {
    return `dr-sg${it.blocked ? ' is-blocked' : ''}${it.count_after === 0 ? ' is-zero' : ''}`;
  }
  async function loadSuggestCounts(zone, q, seq) {
    let data;
    try { data = await request(`/draft/suggest?q=${encodeURIComponent(q)}&zone=${zone}&counts=1`); } catch (_) { return; }
    if (seq !== suggestSeq || suggestZone !== zone || inputs[zone].input.value.trim() !== q || suggestEl.hidden) return;
    const byTag = new Map((data.items || []).map(it => [`${it.kind}:${it.tag}`, it]));
    suggestItems.forEach((it, i) => {
      const got = byTag.get(`${it.kind}:${it.tag}`);
      const row = suggestEl.querySelector(`[data-dr-sg="${i}"]`);
      if (!row) return;
      if (got) Object.assign(it, { count_after: got.count_after, blocked: got.blocked, bound: got.bound, slow: got.slow });
      else it.count_after = it.count_after ?? null;
      row.className = `${suggestRowClass(it)}${i === suggestIndex ? ' is-on' : ''}`;
      const old = row.querySelector('.dr-sg-n');
      const html = got ? suggestCountHtml(it, zone) : '';
      if (old) old.outerHTML = html || '<span class="dr-sg-n"></span>';
    });
  }
  async function loadSuggest(zone, q) {
    const seq = ++suggestSeq;
    let data;
    // `*` 를 그대로 보낸다 - 서버가 퍼펙트 매칭으로 센다.
    try { data = await request(`/draft/suggest?q=${encodeURIComponent(q)}&zone=${zone}&counts=0`); } catch (_) { return; }
    if (seq !== suggestSeq || inputs[zone].input.value.trim() !== q || document.activeElement !== inputs[zone].input) return;
    suggestItems = (data.items || []).filter(it => !it.blocked || it.kind === 'tag');
    suggestZone = zone;
    suggestQ = q;
    suggestIndex = -1;
    if (!suggestItems.length) { hideSuggest(); return; }
    suggestEl.innerHTML = suggestItems.map((it, i) => {
      const name = it.kind === 'rating' ? (it.label || RATING_LABEL[it.rating] || it.tag) : it.tag;
      const kr = it.kr ? `<span class="dr-sg-kr">${esc(it.kr)}</span>` : '';
      return `<div class="${suggestRowClass(it)}" role="option" data-dr-sg="${i}"><span class="dr-sg-t">${esc(name)}</span>${kr}${suggestCountHtml(it, zone)}</div>`;
    }).join('');
    if (data.counted === false) {
      clearTimeout(countTimer);
      countTimer = setTimeout(() => void loadSuggestCounts(zone, q, seq), SUGGEST_COUNT_DELAY_MS);
    }
    const { input } = inputs[zone];
    const boardBox = board.getBoundingClientRect();
    const box = input.getBoundingClientRect();
    suggestEl.style.left = `${Math.max(4, Math.min(box.left - boardBox.left, boardBox.width - 260))}px`;
    suggestEl.style.top = `${box.bottom - boardBox.top + board.scrollTop + 2}px`;
    suggestEl.hidden = false;
  }
  function pickSuggest(i) {
    const it = suggestItems[i];
    const zone = suggestZone;
    if (!it || !zone || it.blocked) return;
    const typedExact = inputs[zone].input.value.trim().startsWith('*');
    const text = it.kind === 'rating' ? (it.label || RATING_LABEL[it.rating] || it.tag) : `${typedExact ? '*' : ''}${it.tag}`;
    inputs[zone].input.value = text;
    void commit(zone, text);
    inputs[zone].input.focus();
  }
  function handleSuggestKey(event, zone) {
    if (suggestEl.hidden || suggestZone !== zone || !suggestItems.length) return false;
    // 친 글이 목록보다 앞섰다(새 목록이 오는 중) - 옛 목록에서 고르지 않는다. Enter 는 친 글 그대로 칩이 된다.
    if (suggestQ !== inputs[zone].input.value.trim() && event.key !== 'Escape') return false;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const n = suggestItems.length;
      suggestIndex = event.key === 'ArrowDown' ? (suggestIndex + 1) % n : (suggestIndex - 1 + n) % n;
      suggestEl.querySelectorAll('[data-dr-sg]').forEach((el, i) => el.classList.toggle('is-on', i === suggestIndex));
      suggestEl.querySelector('.is-on')?.scrollIntoView({ block: 'nearest' });
      return true;
    }
    if ((event.key === 'Enter' || event.key === 'Tab') && suggestIndex >= 0) {
      event.preventDefault();
      pickSuggest(suggestIndex);
      return true;
    }
    if (event.key === 'Escape') { event.preventDefault(); hideSuggest(); return true; }
    return false;
  }
  suggestEl.addEventListener('mousedown', event => event.preventDefault());
  suggestEl.addEventListener('click', event => {
    const row = event.target.closest('[data-dr-sg]');
    if (row) pickSuggest(Number(row.dataset.drSg));
  });

  // ---- 칩 메뉴 ----
  function closeMenu() { menuEl?.remove(); menuEl = null; }
  function openMenu(anchor, items, label) {
    closeMenu();
    menuEl = document.createElement('div');
    menuEl.className = 'dr-menu';
    menuEl.setAttribute('role', 'menu');
    menuEl.innerHTML = `<div class="dr-menu-label">${esc(label)}</div>${items.map((it, i) =>
      `<button type="button" role="menuitem" data-dr-mi="${i}"${it.danger ? ' class="is-danger"' : ''}>${esc(it.label)}</button>`).join('')}`;
    // 화면 위에 고정으로 띄운다 - 판 · 뽑힌 결과 창 어느 쪽에서 열어도 그 창의 넘침에 잘리지 않게.
    document.body.append(menuEl);
    const box = anchor.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const mh = menuEl.offsetHeight || 120, mw = menuEl.offsetWidth || 180;
    menuEl.style.left = `${Math.max(4, Math.min(box.left, vw - mw - 4))}px`;
    menuEl.style.top = `${box.bottom + 3 + mh > vh ? Math.max(4, box.top - mh - 3) : box.bottom + 3}px`;
    menuEl.addEventListener('click', event => {
      const btn = event.target.closest('[data-dr-mi]');
      if (!btn) return;
      event.stopPropagation();
      const it = items[Number(btn.dataset.drMi)];
      closeMenu();
      it?.run();
    });
  }
  function userChipMenu(el) {
    const id = el.dataset.drChip, zone = el.dataset.drZone;
    const chip = (snap?.state?.[zone] || []).find(c => c.id === id);
    if (!chip) return;
    openMenu(el, [
      { label: chip.exact ? '텍스트 매칭으로' : '퍼펙트 매칭으로', run: () => chipOp({ op: 'mode', id, exact: !chip.exact }) },
      { label: zone === 'include' ? '제외로 옮기기' : '포함으로 옮기기', run: () => chipOp({ op: 'move', id, zone: zone === 'include' ? 'exclude' : 'include' }) },
      { label: '지우기', danger: true, run: () => chipOp({ op: 'remove', id }) },
    ], chip.exact ? '퍼펙트 매칭' : '텍스트 매칭');
  }
  function grayMenu(el) {
    const tag = el.dataset.drGray;
    const g = (snap?.derived?.gray || []).find(x => x.tag === tag);
    if (!g) return;
    if (g.dropped) { void drawnOp('undrop', tag); return; }
    openMenu(el, [
      { label: '내 칩으로 고정', run: () => drawnOp('keep', tag) },
      { label: '제외로 (다시 안 뽑힘)', run: () => drawnOp('exclude', tag) },
      { label: '이번만 빼기', run: () => drawnOp('drop', tag) },
    ], '뽑힌 태그 · 다음 Random 에 바뀜');
  }
  board.addEventListener('click', event => {
    const t = event.target;
    if (menuEl && !menuEl.contains(t)) closeMenu();
    const del = t.closest('[data-dr-del]');
    if (del) {
      const chip = del.closest('[data-dr-chip]');
      if (chip) void chipOp({ op: 'remove', id: chip.dataset.drChip });
      return;
    }
    const user = t.closest('[data-dr-chip]:not([data-dr-tag])');
    if (user) { userChipMenu(user); return; }
    const gray = t.closest('[data-dr-gray]');
    if (gray) { grayMenu(gray); return; }
    if (t.closest('[data-dr-drawn-open]')) { toggleDrawnPanel(); return; }
    if (t.closest('[data-dr-stage]')) { void sendToStaging(); return; }
    if (t.closest('[data-dr-from]')) { openStaging(); return; }
    const zone = t.closest('[data-dr-zone]');
    if (zone && !t.closest('input, textarea, button')) inputs[zone.dataset.drZone]?.input.focus();
  });
  board.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const el = event.target.closest?.('[data-dr-chip]:not([data-dr-tag]), [data-dr-gray]');
    if (!el || event.target !== el) return;
    event.preventDefault();
    if (el.dataset.drGray != null) grayMenu(el); else userChipMenu(el);
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && menuEl) closeMenu(); });
  document.addEventListener('mousedown', event => { if (menuEl && !menuEl.contains(event.target)) closeMenu(); }, true);

  // ---- Extra ----
  // 저장했거나 저장할 것이 없으면 true. 실패면 false - [이 결과를 메인 프롬프트로] 는 멈춘다(Codex 리뷰 11-07:
  // 실패를 삼키면 고친 Extra 가 빠진 글을 남기고 '옮겼습니다' 까지 띄웠다).
  async function flushExtra() {
    if (!active()) return true;
    const text = extraEl.value;
    if (text === String(snap?.state?.extra || '')) return true;
    try { receive(await edit('/draft/extra', { text })); }
    catch (error) { showToast(error.message || 'Extra 를 저장하지 못했습니다', 'error'); return false; }
    // 저장 응답보다 새 스냅숏(다른 탭)이 먼저 와서 칸과 서버 글이 다르면 이어서 하지 않는다(Codex 4차 11-07)
    if (extraEl.value !== String(snap?.state?.extra || '')) {
      showToast('다른 창에서 Extra 가 바뀌었습니다 - Extra 를 확인한 뒤 다시 해 주세요', 'warning');
      return false;
    }
    return true;
  }
  extraEl.addEventListener('blur', () => { void flushExtra(); });
  extraEl.addEventListener('animationend', () => extraEl.classList.remove('is-flash'));

  // ---- prefix / postfix 띠 ----
  bands.forEach(el => {
    el.addEventListener('input', () => fitBand(el));
    el.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); el.blur(); }
    });
    el.addEventListener('blur', () => {
      const key = el.dataset.drPe;
      if (el.value === String(getPeField(key) || '')) return;
      try {
        setPeField(key, el.value);
        pendingRebuild = true;
      } catch (error) {
        showToast(`${key === 'pre_prompt' ? 'Prefix' : 'Postfix'} 저장 실패 — ${error.message || ''}`, 'error');
      }
    });
  });
  /** PE 상태가 왔다(app.js 가 부른다) - 띠를 맞추고, 띠에서 고친 뒤면 서버에 다시 조립을 청한다. */
  function syncPe() {
    if (!active()) return;
    paintBands();
    if (!pendingRebuild) return;
    pendingRebuild = false;
    void edit('/draft/rebuild', {}).then(receive).catch(error => showToast(error.message || 'Draft 다시 조립 실패', 'error'));
  }

  // ---- 스테이징 ----
  async function sendToStaging() {
    await flushExtra();
    try {
      const data = await request('/draft/to-staging', {});
      if (data.snapshot) receive(data.snapshot);
      showToast('스테이징에 보냈습니다', 'success');
    } catch (error) {
      showToast(error.message || '스테이징으로 보내지 못했습니다', 'warning');
    }
  }
  async function loadFromStaging(itemId) {
    // 불러오기는 서버의 Extra 를 바꾼다 - 저장 못 한 Extra 를 먼저 저장하고, 못 하면 멈춘다(칩 넣기와 같은 이유 · Codex 3차)
    if (!(await flushExtra())) return false;
    try {
      const data = await request('/draft/from-staging', { item_id: itemId });
      receive(data);
      if ((data.dropped || []).includes('compress')) showToast('압축 조합은 Draft 에 적용되지 않아 뺐습니다', 'info');
      else showToast('스테이징 조건을 불러왔습니다', 'success');
      return true;
    } catch (error) {
      showToast(error.message || '불러오지 못했습니다', 'warning');
      return false;
    }
  }

  paintPill();
  void load();
  return {
    isActive: active,
    isAvailable: () => snap?.available !== false,
    savedPrompt: () => String(snap?.state?.saved_prompt ?? ''),
    /** WS `event_map_draft` */
    receive: message => receive({ ...message, __fromSocket: true }),
    reload: load,
    enter, exit, syncPe, sendToStaging, loadFromStaging,
  };
}
