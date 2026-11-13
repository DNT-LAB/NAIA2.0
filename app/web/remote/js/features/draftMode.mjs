/* Draft Mode — 메인 프롬프트 칸을 포함 · 제외 · Extra 세 칸의 칩 판으로 바꾼다(사용자 구상 2026-11-07).
 *
 * 사양: docs/DRAFT_MODE_SRS_2026_11_07.md · 화면-서버 형식: docs/DRAFT_MODE_API.md(Codex 작업 트리에 함께 둠).
 *
 *  · 투명 BG 옆 [Draft] 알약 - 모든 백엔드에서 보인다(D1). 켜면 서버가 지금 메인 글을 보관했다가 끌 때 되돌린다(D3).
 *  · 칩 상태 · 셈 · 뽑기는 **전부 서버**(D19). 여기서는 그리기 · 입력 · 단추뿐이다. 서버가 보내는 스냅숏 하나가 화면 전체다.
 *  · 메인 칸 글은 서버가 파이프라인으로 조립한 최종 글이다. 숨긴 `#promptEdit` 를 그 글로 늘 맞춘다(재검수 C3) -
 *    Generate 는 여전히 그 칸을 보내고, 서버도 Draft 중에는 자기 글을 쓴다(두 겹).
 *  · prefix / postfix 는 판의 위 · 아래 띠다. 평소엔 한 줄 미리보기 단추이고, 누르면 판 위에 덮이는 편집 패널이 뜬다
 *    (사용자 승인 11-12 - 패널은 칸을 가릴 뿐 밀지 않는다 · 높이만 조절 · 한 번에 하나). 패널의 글은 PE 칸 그 자체다 -
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
import { initDraftTagFinder } from './draftTagFinder.mjs?v=20261113-perm4';
import { initDraftChipCard } from './draftChipCard.mjs?v=20261112-drcard2';
import { initDraftPermExclude } from './draftPermExclude.mjs?v=20261113-perm8';

const RATING_LABEL = { g: 'rating:general', s: 'rating:sensitive', q: 'rating:questionable', e: 'rating:explicit' };
const SUGGEST_DEBOUNCE_MS = 60;   // 이름만 받는 첫 요청은 수 ms(11-07) - 수는 따로 늦게 받는다
const COUNTING_DELAY_MS = 250;

export function initDraftMode({
  host,                          // `.prompt-highlight-wrap` (메인 프롬프트)
  pill,                          // #draftPill
  escHtml,
  showToast = () => {},
  getPeField = () => '',         // (key) => string - PE 칸의 지금 글
  setPeField = () => {},         // (key, text, seenPreset) => void · 못 보내면 던진다
  getPePreset = () => '',        // () => string - 지금 PE 프리셋 이름(보고 친 프리셋의 도장용)
  bindTagAssist = null,          // Extra 칸의 일반 자동완성
  attachHighlight = null,        // prefix / postfix 패널의 색칠(PE 칸과 같은 하이라이터) - 없어도 칸은 그대로 동작한다
  isAutocompleteEnabled = () => true,
  applyServerPrompt = () => {},  // (prompt, source) => void - 숨긴 #promptEdit 를 서버 확정 글로
  takePendingPrompt = () => null,// () => string|null - 안 보낸 메인 글 편집(있으면 지금 보내고 그 글을 돌려준다)
  prepareEnter = async () => ({ ok: true }), // 겹치는 기능(Interactive 등)을 끄거나 막는다 - {ok:false, message}
  dropForeignOwners = () => {},  // 다른 창이 Draft 를 켰다 - 이 탭이 쥔 기능을 원문 복원 없이 내려놓는다(C6)
  openEventMap = () => {},
  openStaging = () => {},
  onActiveChange = () => {},
  onPermanentExcludeChange = () => {}, // (text) => void - 영구 제외 글이 바뀌었다(Search 칸도 같은 글로)
  permanentExcludeFieldText = () => null, // () => Search 영구 제외 칸의 지금 글(없으면 null) - 늦은 읽기가 새 글을 덮지 않게
} = {}) {
  if (!host || !pill) return null;
  // app.js 의 escHtml 은 글만 받는다(숫자 rid 를 넣자 throw -> 그리기 전체가 멈췄다, 11-07 실측) - 늘 글로 바꿔 넘긴다.
  const esc = escHtml ? (s => escHtml(String(s ?? ''))) : (s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
  const fmt = n => (Number.isFinite(n) ? Number(n).toLocaleString('en-US') : '');

  let snap = null;                // 마지막으로 받은 스냅숏
  let gen = null, rev = -1;
  let busy = 0;
  let pendingRebuild = false;     // 띠에서 PE 를 고쳤다 - PE 상태가 돌아오면 다시 조립
  let rebuilding = null;          // 돌고 있는 /draft/rebuild
  let rebuildFailed = false;
  let menuEl = null;
  let finder = null;              // '남은 태그' 창(draftTagFinder.mjs) - 맨 아래에서 만든다
  let chipCard = null;            // 칩 카드(draftChipCard.mjs) - 칩 메뉴와 함께 뜬다 · 맨 아래에서 만든다
  let permBox = null;             // 영구 제외 창(draftPermExclude.mjs) - [제외 : N] 이 연다 · 맨 아래에서 만든다
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
  let editsInFlight = 0;
  function edit(path, body) {
    // 받은 판을 여기서 바로 싣는다 - 다음 차례가 새 판 번호를 읽게(receive 는 옛 판을 버리므로 두 번 불려도 된다)
    const run = () => request(path, { ...body, base_rev: rev }).then(data => { receive(data); return data; });
    editsInFlight += 1;      // 생성은 보낸 편집이 다 끝난 뒤에 나가야 한다(settle 이 기다린다 - 리뷰 2차 #3)
    const next = editChain.then(run, run).finally(() => { editsInFlight -= 1; });
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
    finder?.sync(snap);
    chipCard?.sync(snap);
    permBox?.sync();
    if (was && !now) permBox?.close();
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
    <button type="button" class="dr-band dr-band--pre" data-dr-band="pre_prompt" aria-expanded="false" title="눌러서 prefix 편집"><span
      class="dr-band-name">prefix</span><span class="dr-band-preview" data-dr-band-preview></span><span class="dr-band-caret"
      aria-hidden="true"><svg viewBox="0 0 10 6" width="10" height="6"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor"
      stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button>
    <div class="dr-sum" data-dr-sum></div>
    <div class="dr-zone" data-dr-zone="include">
      <div class="dr-zh"><span class="dr-zt">포함</span><button type="button" class="dr-zclear" data-dr-clear="include"
        title="포함 칩을 모두 지웁니다" hidden>초기화</button></div>
      <div class="dr-chips" data-dr-chips="include"></div>
      <div class="dr-zone-foot" data-dr-drawn-foot hidden>
        <button type="button" class="dr-drawn-btn" data-dr-drawn-open aria-pressed="false"></button>
      </div>
    </div>
    <div class="dr-zone" data-dr-zone="exclude">
      <div class="dr-zh"><span class="dr-zt dr-zt--ex">제외</span><button type="button" class="dr-zclear" data-dr-clear="exclude"
        title="제외 칩을 모두 지웁니다" hidden>초기화</button></div>
      <div class="dr-chips" data-dr-chips="exclude"></div>
    </div>
    <div class="dr-zone dr-zone--extra">
      <div class="dr-zh"><span class="dr-zt">Extra</span></div>
      <textarea class="dr-extra-text" data-dr-extra rows="2" maxlength="2000" spellcheck="false" aria-label="Extra Prompt"
        placeholder="고정적으로 추가하고 싶은 태그를 자유롭게 작성합니다."></textarea>
    </div>
    <button type="button" class="dr-band dr-band--post" data-dr-band="post_prompt" aria-expanded="false" title="눌러서 postfix 편집"><span
      class="dr-band-name">postfix</span><span class="dr-band-preview" data-dr-band-preview></span><span class="dr-band-caret"
      aria-hidden="true"><svg viewBox="0 0 10 6" width="10" height="6"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor"
      stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button>`;
  const footer = host.querySelector('.prompt-token-footer');
  host.insertBefore(board, footer || null);
  // prefix / postfix 편집 패널(사용자 승인 11-12). 판(.dr-board)은 스크롤 상자라 그 안에 두면 스크롤에 딸려 가거나 잘린다 -
  // host 의 자식으로 두고 띠의 자리를 재서 놓는다. textarea 는 한 번만 만든다(다시 만들면 초점이 날아간다).
  const PE_KEYS = ['pre_prompt', 'post_prompt'];
  const PE_NAME = { pre_prompt: 'prefix', post_prompt: 'postfix' };
  const bandEls = {};
  const previewEls = {};
  const pePanels = {};
  const peTexts = {};
  PE_KEYS.forEach(key => {
    bandEls[key] = board.querySelector(`[data-dr-band="${key}"]`);
    previewEls[key] = bandEls[key].querySelector('[data-dr-band-preview]');
    const side = key === 'pre_prompt' ? 'pre' : 'post';
    const panel = document.createElement('div');
    panel.className = `dr-pe-panel dr-pe-panel--${side}`;
    panel.hidden = true;
    panel.dataset.drPePanel = key;
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', `${key === 'pre_prompt' ? 'Prefix' : 'Postfix'} Prompt 편집`);
    panel.innerHTML = `<div class="dr-pe-rh" data-dr-pe-rh title="끌어서 높이 조정 · 두 번 누르면 기본" aria-hidden="true"></div>
      <div class="dr-pe-head"><span class="dr-band-name">${PE_NAME[key]}</span>
        <button type="button" class="dr-zclear" data-dr-pe-revert title="저장하지 못한 글을 버리고 지금 글로 되돌립니다" hidden>되돌리기</button>
        <button type="button" class="dr-pe-x" data-dr-pe-close title="닫기 (Esc)" aria-label="닫기">&times;</button></div>
      <div class="dr-pe-box"><div class="dr-pe-hl" aria-hidden="true"></div>
        <textarea class="dr-band-text" data-dr-pe="${key}" spellcheck="false"
          aria-label="${key === 'pre_prompt' ? 'Prefix' : 'Postfix'} Prompt"></textarea></div>`;
    host.insertBefore(panel, footer || null);
    pePanels[key] = panel;
    peTexts[key] = panel.querySelector('[data-dr-pe]');
  });
  // 색칠은 빌려 온다(app.js 의 attachPromptHighlight · palette 'pe'). 하이라이터는 칸에 손을 걸지 않는다 - 여기서 건다.
  const peHl = {};
  if (typeof attachHighlight === 'function') {
    PE_KEYS.forEach(key => {
      const ta = peTexts[key];
      Promise.resolve(attachHighlight(ta, pePanels[key].querySelector('.dr-pe-hl')))
        .then(handle => {
          if (!handle) return;
          peHl[key] = handle;
          ta.addEventListener('scroll', () => { try { handle.syncScroll(); } catch (_) {} }, { passive: true });
          for (const type of ['focus', 'blur']) ta.addEventListener(type, () => { try { handle.applyState(); } catch (_) {} });
          handle.applyState();
          handle.update();
        })
        .catch(() => { /* 색이 없을 뿐이다 */ });
    });
  }
  const extraEl = board.querySelector('[data-dr-extra]');
  let extraShown = null;   // 칸에 마지막으로 반영한 서버 Extra - 칸의 글이 이것과 다르면 아직 저장 못 한 사용자 글
  const sumEl = board.querySelector('[data-dr-sum]');
  // 자동완성 목록은 화면 위 고정(body)이다 - 판 안에 두면 판의 가로 넘침에 잘려 넓힐 수 없다(사용자 지시 11-11: 펼치기 모드).
  // 줄 = [종류][태그][수]. 아래 띠의 [펼치기] 를 누르면 넓어지고 태그 아래에 설명이 두 줄까지 보인다. 고른 모드는 브라우저에 기억한다.
  const SUGGEST_EXPANDED_KEY = 'naia.draft.suggestExpanded.v1';
  const suggestEl = document.createElement('div');
  suggestEl.className = 'dr-suggest';
  suggestEl.hidden = true;
  suggestEl.innerHTML = '<div class="dr-sg-list" role="listbox" data-dr-sg-list></div>'
    + '<div class="dr-sg-foot"><button type="button" class="dr-sg-exp" data-dr-sg-exp aria-expanded="false"></button></div>';
  document.body.appendChild(suggestEl);
  const suggestListEl = suggestEl.querySelector('[data-dr-sg-list]');
  const suggestExpEl = suggestEl.querySelector('[data-dr-sg-exp]');
  const suggestTipEl = document.createElement('div');
  suggestTipEl.className = 'dr-sg-tip';
  suggestTipEl.hidden = true;
  document.body.appendChild(suggestTipEl);
  let suggestExpanded = false;
  try { suggestExpanded = localStorage.getItem(SUGGEST_EXPANDED_KEY) === '1'; } catch (_) {}
  const bands = PE_KEYS.map(key => peTexts[key]);
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
  function hidePeek() { peekEl.hidden = true; clearTimeout(peekTimer); peekTimer = 0; }
  // DR Random 을 **눌렀을 때** 뽑힌 글을 잠깐(1초) 보여 준다(사용자 지시 11-12). Auto Gen 이 매 장 뽑는 것에는 띄우지 않는다 -
  // app.js 가 누른 때를 알려 주고(armPeek), 그 뒤 곧 온 새 뽑기에만 띄운다. 마우스가 단추 위면 그대로 둔다.
  const PEEK_FLASH_MS = 1000;
  const PEEK_ARM_MS = 35000;      // Random 응답을 기다리는 한도(연결된 Random 의 안전 시간과 같은 자릿수)
  let peekTimer = 0;
  let peekArmedAt = 0;
  function armPeek() { if (active()) peekArmedAt = Date.now(); }
  /** 누른 Random 이 실패 · 끊김으로 끝났다 - 예약을 푼다(리뷰 #7: 남은 예약이 뒤의 다른 뽑기에 떴다). */
  function disarmPeek() { peekArmedAt = 0; }
  function flashPeek() {
    showPeek();
    if (peekEl.hidden) return;
    clearTimeout(peekTimer);
    peekTimer = setTimeout(() => { peekTimer = 0; if (!drawnBtnEl.matches(':hover')) hidePeek(); }, PEEK_FLASH_MS);
  }
  drawnBtnEl.addEventListener('mouseenter', () => { clearTimeout(peekTimer); peekTimer = 0; showPeek(); });
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
    // 끌기 전에 이미 넘친 만큼(창이 아주 작을 때)은 그대로 두고, 그 이상 판을 넘기지 않는다 - 넘치면 postfix 띠가
    // 판 아래로 밀려 사라졌다(사용자 제보 11-13). 남는 높이만큼만 늘어난다.
    const baseOver = Math.max(0, board.scrollHeight - board.clientHeight);
    let last = h0;
    let moved = false;
    h.classList.add('is-drag');
    try { h.setPointerCapture(event.pointerId); } catch (_) {}
    const move = ev => {
      moved = true;
      last = Math.max(min, Math.min(900, h0 + ev.clientY - y0));
      setZoneHeight(name, last);
      const over = board.scrollHeight - board.clientHeight - baseOver;
      if (over > 0) {
        last = Math.max(min, last - over);
        setZoneHeight(name, last);
      }
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
    // 등급 = G · S · Q · E 켜고 끄기(사용자 지시 11-12 - 글로 치지 않는다). 넷 다 켬 = 등급 조건 없음.
    // 남는 게시물이 없는 축은 켤 수 없다(is-zero). 켜 둔 축이 나중에 0건이 되면 켜진 채 흐리게만 - 저절로 끄지 않는다.
    // 프롬프트에 들어가는 등급(뽑힌 게시물의 등급)은 그 단추 아래 노란 줄로 보인다.
    const on = new Set(der.ratings_on || ['g', 's', 'q', 'e']);
    const counts = der.rating_counts || null;
    const out = String(der.rating_out || '').replace(/^rating:/, '').charAt(0);
    const rating = `<span class="dr-rates" role="group" aria-label="등급">${['g', 's', 'q', 'e'].map(r => {
      const n = counts ? Number(counts[r] || 0) : null;
      const zero = n === 0;
      const name = RATING_LABEL[r].replace('rating:', '');
      const tip = zero ? `${name} - 이 조건에는 게시물이 없습니다${on.has(r) ? '' : ' (켤 수 없음)'}`
        : `${name}${n == null ? '' : ` ${fmt(n)}`}${out === r ? ' · 이 등급 태그가 프롬프트에 들어갑니다' : ''}`;
      return `<button type="button" class="dr-rate${on.has(r) ? ' is-on' : ''}${zero ? ' is-zero' : ''}${out === r ? ' is-out' : ''}"`
        + ` data-dr-rate="${r}" aria-pressed="${on.has(r)}"${zero && !on.has(r) ? ' aria-disabled="true"' : ''} title="${esc(tip)}">${r.toUpperCase()}</button>`;
    }).join('')}</span>`;
    // [제외 : N] = 영구 제외(Search 의 붉은 줄과 같은 목록) - 남은 게시물은 여기 걸린 게시물을 뺀 수다(사용자 지시 11-13).
    const perm = der.perm || null;
    const permTerms = perm?.terms || [];
    const permTip = permTerms.length
      ? `영구 제외${Number.isFinite(perm?.dropped) ? ` · 빠진 게시물 ${fmt(perm.dropped)}` : ''} — ${permTerms.join(', ')} (누르면 고칩니다)`
      : '영구 제외 - 비어 있습니다. 누르면 태그를 더합니다(Search · 이벤트 맵과 같은 목록)';
    const permBtn = `<button type="button" class="dr-btn dr-perm${permTerms.length ? ' is-on' : ''}" data-dr-perm
      aria-pressed="${!!permBox?.isOpen()}" title="${esc(permTip)}">제외 : ${permTerms.length}</button>`;
    sumEl.innerHTML = `<span>남은 게시물</span><span class="dr-big">${remaining == null ? '—' : fmt(remaining)}</span>${rating}${permBtn}
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
      if (peekArmedAt && Date.now() - peekArmedAt < PEEK_ARM_MS) flashPeek();
      peekArmedAt = 0;
      drawnBtnEl.classList.remove('is-flash');
      void drawnBtnEl.offsetWidth;   // 같은 애니메이션을 다시 처음부터
      drawnBtnEl.classList.add('is-flash');
    }
  }
  /** 패널 글을 PE 와 맞춘다 - 포커스 중인 칸은 덮지 않는다(치는 중인 글). 띠의 한 줄 미리보기는 늘 칸의 글을 따른다. */
  function paintBands() {
    bands.forEach(el => {
      if (el !== document.activeElement && !peUnsaved[el.dataset.drPe]) {
        const text = String(getPeField(el.dataset.drPe) || '');
        if (el.value !== text) el.value = text;
      }
      paintPreview(el.dataset.drPe);
    });
  }
  function paintPreview(key) {
    const line = String(peTexts[key].value || '').replace(/\s+/g, ' ').trim();
    const el = previewEls[key];
    el.textContent = line || '비어 있음';
    el.classList.toggle('is-empty', !line);
    try { peHl[key]?.update(); } catch (_) {}   // 칸의 글이 바뀌는 길(입력 · PE 상태 · 열기)은 모두 여기를 지난다
  }
  function paint() {
    paintPill();
    const on = active();
    board.hidden = !on;
    document.body.classList.toggle('draft-mode', on);
    if (!on) { closeMenu(); hideSuggest(); closeDrawnPanel(); hidePeek(); closePePanel(); disarmPeek(); return; }
    paintZone('include');
    paintZone('exclude');
    {   // [초기화] 는 지울 것이 있을 때만 보인다
      const st = snap?.state || {};
      const has = {
        include: (st.include || []).length + (st.tags?.persons || []).length > 0,
        exclude: (st.exclude || []).length + (st.tags?.groups || []).length > 0,
      };
      board.querySelectorAll('[data-dr-clear]').forEach(el => { el.hidden = !has[el.dataset.drClear]; });
    }
    paintDrawn();
    paintSum();
    paintBands();
    schedulePlacePe();   // 칩이 바뀌어 띠가 움직였을 수 있다
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
  let ratingsWant = null;         // 답을 기다리는 동안의 바란 등급 집합
  let ratingsSeq = 0;
  /** 등급 단추 - 켜 둘 집합을 통째로 보낸다(`op: ratings`). 서버가 한 번 더 막는다(0건 축 · 전부 끔). */
  function toggleRating(r) {
    const der = snap?.derived || {};
    // 앞선 누름의 답이 오기 전에 또 누르면 그 **바란 집합**에서 이어 간다 - 스냅숏에서 다시 세면 앞 누름이 되돌아갔다
    // (리뷰 #3: G · S 를 잇달아 끄면 QE 가 아니라 GQE).
    const on = new Set(ratingsWant || der.ratings_on || ['g', 's', 'q', 'e']);
    if (on.has(r)) {
      if (on.size === 1) { showToast('등급은 하나 이상 켜져 있어야 합니다', 'warning'); return; }
      on.delete(r);
    } else {
      if (der.rating_counts && !Number(der.rating_counts[r] || 0)) {
        showToast('이 조건에는 그 등급의 게시물이 없어 켤 수 없습니다', 'warning');
        return;
      }
      on.add(r);
    }
    ratingsWant = on;
    const mine = ++ratingsSeq;
    void chipOp({ op: 'ratings', text: ['g', 's', 'q', 'e'].filter(x => on.has(x)).join('') })
      .finally(() => { if (mine === ratingsSeq) ratingsWant = null; });
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
  // 남는 게시물이 적은 조건이면 서버가 첫 응답에 수까지 실어 보낸다(counted: true · 조건 안에 있는 태그가 앞) - 한 번으로 끝난다.
  const SUGGEST_COUNT_DELAY_MS = 180;
  const SUGGEST_TIP_DELAY_MS = 350;
  let suggestTimer = null, countTimer = null, tipTimer = null, suggestSeq = 0, suggestZone = '', suggestItems = [], suggestIndex = -1;
  let suggestQ = '';   // 지금 떠 있는 목록이 어느 입력의 것인가 - 다른 글이면 키보드로 고르지 못한다(옛 목록에서 Enter = 엉뚱한 칩)
  let tipRow = -1;     // 말풍선을 띄웠거나 띄우려는 줄
  function hideSuggestTip() {
    clearTimeout(tipTimer);
    tipRow = -1;
    suggestTipEl.hidden = true;
  }
  function hideSuggest() {
    // 기다리는 조회도 끊는다 - Escape 로 닫은 뒤 늦게 온 이름 응답이 목록을 다시 열었다(Codex 리뷰 11-07)
    clearTimeout(suggestTimer);
    clearTimeout(countTimer);
    hideSuggestTip();
    suggestSeq++;
    suggestEl.hidden = true;
    suggestListEl.innerHTML = '';
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
    // 조건이 작아 서버가 정확히 센 줄은 bound 가 없다(기호 없이 수만).
    if (Number.isFinite(it.count_after)) {
      return `<span class="dr-sg-n">${zone === 'exclude' ? '남음 ' : ''}${it.bound === 'min' ? '≥' : (it.bound === 'max' ? '≤' : '')}${fmt(it.count_after)}</span>`;
    }
    return '<span class="dr-sg-n is-pending" aria-hidden="true"></span>';
  }
  function suggestRowClass(it) {
    // is-absent = 지금 조건의 게시물에 없는 태그(흐리게 · 서버가 맨 뒤로 보낸다)
    return `dr-sg${it.blocked ? ' is-blocked' : ''}${it.count_after === 0 ? ' is-zero' : ''}${it.hits === 0 ? ' is-absent' : ''}`;
  }
  /** 한 줄 = [종류][태그][수] + 설명(펼치기 모드에서만 보인다 - CSS). 수 칸(.dr-sg-n)은 줄에 하나뿐이어야 한다(나중에 갈아 끼운다). */
  function suggestRowHtml(it, i, zone) {
    const name = it.kind === 'rating' ? (it.label || RATING_LABEL[it.rating] || it.tag) : it.tag;
    const major = it.major && typeof it.major === 'object' ? it.major : null;
    const kind = `<span class="dr-sg-k"${major?.id ? ` data-g="${esc(major.id)}"` : ''}>${esc(major?.label || '')}</span>`;
    const desc = it.desc ? `<span class="dr-sg-d">${esc(it.desc)}</span>` : '';
    return `<div class="${suggestRowClass(it)}" role="option" data-dr-sg="${i}">${kind}<span class="dr-sg-t">${esc(name)}</span>${suggestCountHtml(it, zone)}${desc}</div>`;
  }
  function paintSuggestMode() {
    suggestEl.classList.toggle('is-expanded', suggestExpanded);
    suggestExpEl.textContent = suggestExpanded ? '« 접기' : '» 펼치기';
    suggestExpEl.setAttribute('aria-expanded', String(suggestExpanded));
  }
  /** 입력칸 바로 아래에 고정으로 놓는다. 아래가 좁고 위가 더 넓으면 위로. 화면 밖으로 나가지 않게 폭 · 높이를 줄인다. */
  function placeSuggest() {
    if (suggestEl.hidden || !suggestZone) return;
    const box = inputs[suggestZone].input.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const width = Math.min(suggestExpanded ? 500 : 320, vw - 8);
    const wantList = suggestExpanded ? 440 : 300;
    const foot = suggestExpEl.parentElement.offsetHeight || 24;
    const below = vh - box.bottom - 10, above = box.top - 10;
    const up = below < Math.min(wantList, 200) + foot && above > below;
    suggestListEl.style.maxHeight = `${Math.max(96, Math.min(wantList, (up ? above : below) - foot))}px`;
    suggestEl.style.width = `${width}px`;
    suggestEl.style.left = `${Math.max(4, Math.min(box.left, vw - width - 4))}px`;
    suggestEl.style.top = up ? `${Math.max(4, box.top - 2 - suggestEl.offsetHeight)}px` : `${box.bottom + 2}px`;
  }
  /** 줄의 설명 말풍선 - 목록 옆(오른쪽에 자리가 없으면 왼쪽)에 그 줄 높이로 띄운다. 목록을 가리지 않는다.
   *  일반 모드: 설명이나 지도 경로가 있는 줄. 펼치기 모드: 두 줄을 넘겨 잘린 줄만(이미 보이는 글을 또 띄우지 않는다). */
  function showSuggestTip(i) {
    const it = suggestItems[i];
    const row = suggestListEl.querySelector(`[data-dr-sg="${i}"]`);
    if (!it || !row || it.kind !== 'tag' || suggestEl.hidden) { suggestTipEl.hidden = true; return; }
    const descEl = row.querySelector('.dr-sg-d');
    const clipped = !!descEl && descEl.scrollHeight > descEl.clientHeight + 1;
    if (suggestExpanded ? !clipped : !(it.desc || it.path)) { suggestTipEl.hidden = true; return; }
    const where = [it.major?.label, it.minor].filter(Boolean).join(' › ');
    const counts = [Number.isFinite(it.hits) ? `이 조건 ${fmt(it.hits)}` : '', Number.isFinite(it.observed) ? `전체 ${fmt(it.observed)}` : '']
      .filter(Boolean).join(' · ');
    suggestTipEl.innerHTML = `<div class="dr-sg-tip-t">${esc(it.tag)}</div>`
      + (where || counts ? `<div class="dr-sg-tip-m">${esc([where, counts].filter(Boolean).join(' · '))}</div>` : '')
      + (it.path ? `<div class="dr-sg-tip-m">지도: ${esc(it.path)}</div>` : '')
      + (it.desc ? `<div class="dr-sg-tip-d">${esc(it.desc)}</div>` : '');
    suggestTipEl.hidden = false;
    const pop = suggestEl.getBoundingClientRect(), r = row.getBoundingClientRect();
    const vw = window.innerWidth, vh = window.innerHeight;
    const w = Math.min(340, vw - 16);
    suggestTipEl.style.width = `${w}px`;
    const h = suggestTipEl.offsetHeight;
    const left = pop.right + 6 + w <= vw - 4 ? pop.right + 6 : (pop.left - 6 - w >= 4 ? pop.left - 6 - w : Math.max(4, vw - w - 4));
    suggestTipEl.style.left = `${left}px`;
    suggestTipEl.style.top = `${Math.max(4, Math.min(r.top, vh - h - 4))}px`;
  }
  function scheduleSuggestTip(i) {
    clearTimeout(tipTimer);
    suggestTipEl.hidden = true;
    tipRow = i;
    if (i < 0) return;
    tipTimer = setTimeout(() => showSuggestTip(i), SUGGEST_TIP_DELAY_MS);
  }
  async function loadSuggestCounts(zone, q, seq) {
    let data;
    try { data = await request(`/draft/suggest?q=${encodeURIComponent(q)}&zone=${zone}&counts=1`); } catch (_) { return; }
    if (seq !== suggestSeq || suggestZone !== zone || inputs[zone].input.value.trim() !== q || suggestEl.hidden) return;
    const byTag = new Map((data.items || []).map(it => [`${it.kind}:${it.tag}`, it]));
    suggestItems.forEach((it, i) => {
      const got = byTag.get(`${it.kind}:${it.tag}`);
      const row = suggestListEl.querySelector(`[data-dr-sg="${i}"]`);
      if (!row) return;
      if (got) Object.assign(it, { count_after: got.count_after, blocked: got.blocked, bound: got.bound, slow: got.slow, hits: got.hits ?? null });
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
    hideSuggestTip();
    suggestListEl.innerHTML = suggestItems.map((it, i) => suggestRowHtml(it, i, zone)).join('');
    suggestListEl.scrollTop = 0;
    if (data.counted === false) {
      clearTimeout(countTimer);
      countTimer = setTimeout(() => void loadSuggestCounts(zone, q, seq), SUGGEST_COUNT_DELAY_MS);
    }
    paintSuggestMode();
    suggestEl.hidden = false;
    placeSuggest();
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
      suggestListEl.querySelectorAll('[data-dr-sg]').forEach((el, i) => el.classList.toggle('is-on', i === suggestIndex));
      suggestListEl.querySelector('.is-on')?.scrollIntoView({ block: 'nearest' });
      scheduleSuggestTip(suggestIndex);   // 키보드로 고른 줄의 설명도 같은 말풍선으로
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
  suggestEl.addEventListener('mousedown', event => event.preventDefault());   // 입력칸 초점을 지킨다(줄 · 펼치기 단추 모두)
  suggestEl.addEventListener('click', event => {
    if (event.target.closest('[data-dr-sg-exp]')) {
      suggestExpanded = !suggestExpanded;
      try { localStorage.setItem(SUGGEST_EXPANDED_KEY, suggestExpanded ? '1' : '0'); } catch (_) {}
      hideSuggestTip();
      paintSuggestMode();
      placeSuggest();
      suggestListEl.querySelector('.is-on')?.scrollIntoView({ block: 'nearest' });
      return;
    }
    const row = event.target.closest('[data-dr-sg]');
    if (row) pickSuggest(Number(row.dataset.drSg));
  });
  suggestListEl.addEventListener('mouseover', event => {
    const row = event.target.closest('[data-dr-sg]');
    const i = row ? Number(row.dataset.drSg) : -1;
    if (i !== tipRow) scheduleSuggestTip(i);
  });
  suggestListEl.addEventListener('mouseleave', hideSuggestTip);
  suggestListEl.addEventListener('scroll', hideSuggestTip, { passive: true });
  // 창 크기가 바뀌면 닫지 않고 다시 놓는다 - 휴대폰은 화면 키보드가 뜰 때마다 resize 가 온다(닫으면 치는 도중에 목록이 사라진다)
  window.addEventListener('resize', () => { if (!suggestEl.hidden) { hideSuggestTip(); placeSuggest(); } });
  // 입력칸을 품은 것(판 · 왼쪽 패널)이 스크롤되면 목록이 입력칸을 따라간다 - 목록은 화면에 고정이라 저절로는 안 움직인다.
  document.addEventListener('scroll', event => {
    if (suggestEl.hidden || !suggestZone) return;
    const t = event.target;
    if (t instanceof Node && t !== suggestListEl && t.contains(inputs[suggestZone].input)) { hideSuggestTip(); placeSuggest(); }
  }, true);

  // ---- 칩 메뉴 ----
  function closeMenu() { menuEl?.remove(); menuEl = null; chipCard?.close(); }
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
    chipCard?.open(el, chip, zone);   // 메뉴와 함께 태그 카드(openMenu 가 먼저 닫은 뒤에 연다)
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
    const clear = t.closest('[data-dr-clear]');
    if (clear) { void chipOp({ op: 'clear', zone: clear.dataset.drClear }); return; }
    const rate = t.closest('[data-dr-rate]');
    if (rate) { toggleRating(rate.dataset.drRate); return; }
    if (t.closest('[data-dr-stage]')) { void sendToStaging(); return; }
    if (t.closest('[data-dr-perm]')) { permBox?.toggle(); paintSum(); return; }
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
  // 칩 카드 안을 누르는 것은 '바깥' 이 아니다 - 카드의 칩을 누르기 전에 메뉴(와 카드)가 닫히지 않게
  document.addEventListener('mousedown', event => {
    if (menuEl && !menuEl.contains(event.target) && !chipCard?.contains(event.target)) closeMenu();
  }, true);

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

  // ---- prefix / postfix 띠 · 편집 패널(사용자 승인 11-12) ----
  // 띠 = 한 줄 미리보기 단추. 누르면 판 위에 덮이는 패널(postfix 는 띠 위로 · prefix 는 띠 아래로). 패널은 칸을 가릴 뿐
  // 밀지 않는다. 옮길 수 없고 높이만 - 띠에서 먼 가장자리 손잡이. 한 번에 하나. 닫히면 반드시 저장(blur 와 같은 규칙).
  const PE_HEIGHT_KEY = 'naia.draft.pePanelHeights.v1';
  const PE_DEFAULT_H = 138;       // 띠 자리(28) + 글 서너 줄 - 패널이 열린 띠의 자리까지 덮는다
  let openPe = null;              // 열린 패널의 키(pre_prompt | post_prompt)
  const peUnsaved = {};           // 저장하지 못한 글이 칸에 남아 있다 - 서버 글로 덮지 않는다
  const peSeenPreset = {};        // 칸을 채울 때의 PE 프리셋 - 저장할 때 그 이름을 도장으로 보낸다
  const peSent = {};              // 보냈지만 서버가 아직 돌려주지 않은 글들(key -> [text…] 보낸 차례)
  const peSentAt = {};            // 마지막으로 보낸 때
  const peEchoes = {};            // 마지막으로 보낸 뒤에 받은 서버 상태 수(보낸 글이 안 든 것)
  const peServer = {};            // 서버가 마지막으로 보낸 글(가공 전)
  const PE_REJECT_MS = 1500;      // 보낸 뒤 이만큼 지나도록 서버 상태에 그 글이 없으면 거절된 것으로 본다
  const pePending = key => !!(peSent[key] && peSent[key].length);
  let peSuppressBlur = false;     // 닫으면서 이미 저장했다 - 그 blur 에서 또 저장(실패 토스트 두 번)하지 않게
  let pePlaceRaf = 0;
  const peShownH = {};            // 마지막으로 놓은 (자르기 전) 높이 - 끌기의 시작점
  function readPeHeights() {
    try {
      const v = JSON.parse(localStorage.getItem(PE_HEIGHT_KEY) || '{}');
      return v && typeof v === 'object' ? v : {};
    } catch (_) { return {}; }
  }
  function writePeHeights(v) { try { localStorage.setItem(PE_HEIGHT_KEY, JSON.stringify(v)); } catch (_) {} }
  const peHeights = readPeHeights();
  function wantPeHeight(key) {
    const v = Number(peHeights[key]);
    return Number.isFinite(v) && v > 0 ? v : PE_DEFAULT_H;
  }
  /** 머리 줄 + 글 두 줄 - 패널이 보일 때 잰다. */
  function pePanelMin(key) {
    const panel = pePanels[key];
    const ta = peTexts[key];
    const cs = getComputedStyle(panel);
    const tcs = getComputedStyle(ta);
    const box = (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0)
      + (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    const head = panel.querySelector('.dr-pe-head')?.offsetHeight || 0;
    const lh = parseFloat(tcs.lineHeight) || 18;
    return Math.ceil(box + head + lh * 2 + (parseFloat(tcs.paddingTop) || 0) + (parseFloat(tcs.paddingBottom) || 0));
  }
  /** 최대 = 두 띠 사이의 판 높이(판이 스크롤되면 보이는 판 높이를 넘지 않게). */
  function pePanelMax(key, min) {
    const pre = bandEls.pre_prompt.getBoundingClientRect();
    const post = bandEls.post_prompt.getBoundingClientRect();
    // 열린 띠는 감추고 패널이 그 자리까지 덮는다 - 반대쪽 띠만 남긴다
    const room = Math.min(key === 'post_prompt' ? post.bottom - pre.bottom : post.top - pre.top, board.clientHeight);
    return Math.max(min, Math.floor(room));
  }
  /** 띠의 자리를 재서 패널을 놓는다. 판의 보이는 영역 밖은 잘라 낸다(띠가 스크롤로 나가도 판 밖으로 삐져나가지 않게). */
  function placePePanel() {
    const key = openPe;
    if (!key) return;
    const panel = pePanels[key];
    // 판이 숨겨졌다(Draft 끔 · 화면 전환으로 0 크기) - 닫는다. 휴대폰 키보드의 resize 는 판을 줄일 뿐 0 으로 만들지 않는다.
    if (board.hidden || !board.clientHeight || !board.clientWidth) { closePePanel(); return; }
    const hostR = host.getBoundingClientRect();
    const ox = hostR.left + host.clientLeft - host.scrollLeft;
    const oy = hostR.top + host.clientTop - host.scrollTop;
    const boardR = board.getBoundingClientRect();
    const viewTop = boardR.top + board.clientTop;
    const viewBottom = viewTop + board.clientHeight;
    const r = bandEls[key].getBoundingClientRect();
    const min = pePanelMin(key);
    const max = pePanelMax(key, min);
    const h = Math.max(min, Math.min(max, wantPeHeight(key)));
    peShownH[key] = h;
    const top = key === 'post_prompt' ? r.bottom - h : r.top;
    const visTop = Math.max(top, viewTop);
    const visBottom = Math.min(top + h, viewBottom);
    const headH = panel.querySelector('.dr-pe-head')?.offsetHeight || 0;
    panel.style.left = `${Math.round(r.left - ox)}px`;
    panel.style.width = `${Math.round(r.width)}px`;
    panel.style.top = `${Math.round(visTop - oy)}px`;
    panel.style.height = `${Math.max(0, Math.round(visBottom - visTop))}px`;
    // 머리 줄도 안 들어갈 만큼 잘렸으면 감춰 둔다(열린 채 - 띠가 다시 보이면 돌아온다)
    panel.style.visibility = visBottom - visTop < headH + 4 ? 'hidden' : '';
  }
  function schedulePlacePe() {
    if (!openPe || pePlaceRaf) return;
    pePlaceRaf = requestAnimationFrame(() => { pePlaceRaf = 0; placePePanel(); });
  }
  /** blur 와 닫기가 함께 쓴다 - 값이 다르면 PE 에 쓰고 다시 조립을 예약한다. */
  function commitPeText(el) {
    const key = el.dataset.drPe;
    if (el.value === String(getPeField(key) || '')) { peUnsaved[key] = false; paintPeRevert(key); return true; }
    const name = key === 'pre_prompt' ? 'Prefix' : 'Postfix';
    // 보고 친 프리셋이 그사이 바뀌었으면(다른 탭) 보내지 않는다 - 지금 프리셋의 도장으로 보내면 앞 프리셋의 글이
    // 새 프리셋을 덮는다(Codex 리뷰 2026-11-12 #2). 글은 칸에 남긴다 - 사용자가 보고 옮기거나 버린다.
    let now = '';
    try { now = String(getPePreset() || ''); } catch (_) {}
    const seen = peSeenPreset[key];
    if (seen != null && seen !== now) {
      if (!peUnsaved[key]) showToast(`프리셋이 바뀌어 ${name} 편집을 저장하지 않았습니다 - 글은 칸에 남겨 두었습니다([되돌리기] 로 버릴 수 있습니다)`, 'warning');
      peUnsaved[key] = true;
      paintPeRevert(key);
      return false;
    }
    try {
      const text = el.value;
      setPeField(key, text, seen);
      // 서버가 이 글을 돌려줄 때까지는 저장된 것으로 치지 않는다. 잇달아 보낸 글은 차례대로 쌓는다 -
      // 앞 글의 답을 뒤 글의 확인으로 치지 않게(리뷰 3차 #1).
      (peSent[key] || (peSent[key] = [])).push(text);
      peSentAt[key] = Date.now();
      peEchoes[key] = 0;
      pendingRebuild = true;
      peUnsaved[key] = false;
      paintPeRevert(key);
      return true;
    } catch (error) {
      // 못 보낸 글은 칸에 남긴다 - 다시 열거나 PE 상태가 와도 덮지 않는다(리뷰 #4: 끊긴 채 닫았다 열면 글이 사라졌다)
      peUnsaved[key] = true;
      paintPeRevert(key);
      showToast(`${name} 저장 실패 — ${error.message || ''}`, 'error');
      return false;
    }
  }
  /** 저장 못 한 글이 남은 패널에만 [되돌리기] 를 보인다 - 그 글을 버리고 지금 PE 글 · 지금 프리셋에서 다시 시작한다
   *  (리뷰 2차 #5: 프리셋이 바뀐 뒤에는 남은 글을 버릴 길이 없어 저장도 생성도 계속 막혔다). */
  function paintPeRevert(key) {
    const btn = pePanels[key].querySelector('[data-dr-pe-revert]');
    if (btn) btn.hidden = !peUnsaved[key];
  }
  function revertPeText(key) {
    peUnsaved[key] = false;
    // 서버가 마지막으로 보낸 글로 되돌린다(화면 안의 비추기 값이 아니라). 가는 중인 저장의 확인은 건드리지 않는다 -
    // 그 글이 서버에 닿으면 서버 글이 되고, 그때 칸도 그 글을 따른다.
    peTexts[key].value = String(peServer[key] ?? getPeField(key) ?? '');
    try { peSeenPreset[key] = String(getPePreset() || ''); } catch (_) { peSeenPreset[key] = null; }
    paintPreview(key);
    paintPeRevert(key);
  }
  function openPePanel(key) {
    if (openPe === key) return;
    closePePanel();
    if (!active() || board.hidden) return;
    const panel = pePanels[key];
    const ta = peTexts[key];
    const text = String(getPeField(key) || '');
    if (!peUnsaved[key]) {
      if (ta.value !== text) ta.value = text;
      try { peSeenPreset[key] = String(getPePreset() || ''); } catch (_) { peSeenPreset[key] = null; }
    }
    paintPreview(key);
    openPe = key;
    panel.hidden = false;
    bandEls[key].classList.add('is-open');
    bandEls[key].setAttribute('aria-expanded', 'true');
    placePePanel();
    if (openPe !== key) return;   // 놓다가 닫혔다(판이 안 보인다)
    try {
      ta.focus({ preventScroll: true });
      const n = ta.value.length;
      ta.setSelectionRange(n, n);
    } catch (_) {}
  }
  /** 닫기 - 저장이 반드시 먼저 일어난다(포커스가 칸에 없어도 값이 다르면 저장). */
  function closePePanel({ focusBand = false } = {}) {
    const key = openPe;
    if (!key) return;
    const panel = pePanels[key];
    const ta = peTexts[key];
    openPe = null;
    if (pePlaceRaf) { cancelAnimationFrame(pePlaceRaf); pePlaceRaf = 0; }
    commitPeText(ta);
    if (panel.contains(document.activeElement)) {
      peSuppressBlur = true;
      try { document.activeElement.blur(); } finally { peSuppressBlur = false; }
    }
    panel.hidden = true;
    panel.style.visibility = '';
    bandEls[key].classList.remove('is-open');
    bandEls[key].setAttribute('aria-expanded', 'false');
    paintPreview(key);
    if (focusBand) { try { bandEls[key].focus({ preventScroll: true }); } catch (_) {} }
  }
  PE_KEYS.forEach(key => {
    const band = bandEls[key];
    const panel = pePanels[key];
    const ta = peTexts[key];
    band.addEventListener('click', () => openPePanel(key));   // 열린 띠는 감춰져 있다 - 닫기는 x · Esc · 바깥
    ta.addEventListener('input', () => paintPreview(key));
    ta.addEventListener('blur', () => { if (!peSuppressBlur) commitPeText(ta); });
    panel.querySelector('[data-dr-pe-close]').addEventListener('click', () => closePePanel({ focusBand: true }));
    const revertBtn = panel.querySelector('[data-dr-pe-revert]');
    // 누르는 순간 칸이 초점을 잃으면 blur 가 '버릴 글' 을 먼저 저장한다(리뷰 3차 #3) - 초점을 옮기지 않는다
    revertBtn.addEventListener('pointerdown', event => event.preventDefault());
    revertBtn.addEventListener('click', () => { revertPeText(key); try { ta.focus({ preventScroll: true }); } catch (_) {} });
    // 높이 손잡이 - 칸 손잡이(.dr-rh)와 같은 포인터 캡처 방식. postfix 패널은 위로, prefix 패널은 아래로 늘어난다.
    const grip = panel.querySelector('[data-dr-pe-rh]');
    grip.addEventListener('pointerdown', event => {
      if (event.button !== 0 || openPe !== key) return;
      event.preventDefault();
      const y0 = event.clientY;
      const h0 = peShownH[key] || wantPeHeight(key);
      const min = pePanelMin(key);
      const max = pePanelMax(key, min);
      const sign = key === 'post_prompt' ? -1 : 1;
      let last = h0;
      let moved = false;
      grip.classList.add('is-drag');
      try { grip.setPointerCapture(event.pointerId); } catch (_) {}
      const move = ev => {
        moved = true;
        last = Math.max(min, Math.min(max, h0 + sign * (ev.clientY - y0)));
        peHeights[key] = Math.round(last);
        placePePanel();
      };
      const up = () => {
        grip.classList.remove('is-drag');
        grip.removeEventListener('pointermove', move);
        grip.removeEventListener('pointerup', up);
        grip.removeEventListener('pointercancel', up);
        if (!moved) return;
        const saved = readPeHeights();
        saved[key] = Math.round(last);
        writePeHeights(saved);
      };
      grip.addEventListener('pointermove', move);
      grip.addEventListener('pointerup', up);
      grip.addEventListener('pointercancel', up);
    });
    grip.addEventListener('dblclick', event => {
      event.preventDefault();
      delete peHeights[key];
      const saved = readPeHeights();
      delete saved[key];
      writePeHeights(saved);
      placePePanel();
    });
  });
  // 패널 · 띠 바깥을 누르면 닫는다(다른 띠를 누르면 먼저 것이 닫히고 그 띠가 열린다)
  document.addEventListener('pointerdown', event => {
    if (!openPe) return;
    const t = event.target;
    if (pePanels[openPe].contains(t) || bandEls[openPe].contains(t)) return;
    closePePanel();
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !openPe) return;
    const t = event.target;
    if (!(pePanels[openPe].contains(t) || bandEls[openPe].contains(t) || t === document.body)) return;
    event.preventDefault();
    closePePanel({ focusBand: true });
  });
  // 다시 놓기: 판 스크롤 · 창 크기(휴대폰 키보드 포함 - 닫지 않는다) · 판 · 칸 크기 변화
  board.addEventListener('scroll', schedulePlacePe, { passive: true });
  window.addEventListener('resize', schedulePlacePe);
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => schedulePlacePe());
    ro.observe(board);
    [...board.children].forEach(el => ro.observe(el));
  }
  /** PE 상태가 왔다(app.js 가 부른다) - 띠를 맞추고, 띠에서 고친 뒤면 서버에 다시 조립을 청한다. */
  function syncPe(serverState = null) {
    // serverState = 서버가 보낸 PE 상태(app.js 의 모듈 상태 수신). 없으면 화면 안의 비추기 알림(다른 칸을 친 것 등)이다 -
    // 그것을 저장 완료로 치면 저장이 닿기 전에 재조립이 나가 옛 글로 조립됐다(리뷰 2차 #1). 재조립은 서버 상태에만 건다.
    if (!active()) return;
    paintBands();
    if (!serverState || !pendingRebuild) return;
    if (PE_KEYS.some(pePending)) return;     // 보낸 글이 아직 안 돌아왔다 - 그 상태가 올 때 조립한다
    void rebuild();
  }
  /** 서버가 보낸 PE 글(가공 전 · app.js 가 모듈 상태를 받자마자 부른다). 보낸 글의 확인은 여기서만 한다. */
  function notePeServer(texts) {
    PE_KEYS.forEach(key => {
      if (!texts || texts[key] === undefined) return;
      const text = String(texts[key] ?? '');
      peServer[key] = text;
      const queue = peSent[key];
      if (!queue || !queue.length) return;
      // 맨 앞의 같은 글까지만 확인한다 - A → B → A 로 보냈을 때 첫 A 의 답을 마지막 A 의 확인으로 치면 중간 글 B 로
      // 조립된 채 끝난다(Codex 리뷰 2026-11-12 4차 #1).
      const at = queue.indexOf(text);
      if (at >= 0) queue.splice(0, at + 1);      // 그 글과 그 앞에 보낸 글들까지 확인됐다
      else peEchoes[key] = (peEchoes[key] || 0) + 1;
    });
  }
  /** 보낸 글이 거절됐나 - 서버가 그 뒤로 상태를 보냈는데도 그 글이 없고 시간이 지났다(프리셋 도장 불일치 · 랜덤 프리셋의
   *  읽기 전용). 거절이면 글을 칸에 남기고 [되돌리기] 를 보인다 - 무기한 기다리지 않는다(리뷰 3차 #2). */
  function dropRejectedPe() {
    let rejected = false;
    PE_KEYS.forEach(key => {
      if (!pePending(key) || !peEchoes[key] || Date.now() - (peSentAt[key] || 0) < PE_REJECT_MS) return;
      peSent[key] = [];
      rejected = true;
      const name = key === 'pre_prompt' ? 'Prefix' : 'Postfix';
      if (peTexts[key].value !== String(peServer[key] ?? '')) {
        peUnsaved[key] = true;
        paintPeRevert(key);
        showToast(`${name} 편집이 저장되지 않았습니다(프리셋이 바뀌었거나 읽기 전용입니다) - [되돌리기] 로 버릴 수 있습니다`, 'warning');
      }
    });
    return rejected;
  }
  function rebuild() {
    pendingRebuild = false;
    rebuildFailed = false;
    const run = edit('/draft/rebuild', {}).then(() => true)
      .catch(error => { rebuildFailed = true; showToast(error.message || 'Draft 다시 조립 실패', 'error'); return false; })
      .finally(() => { if (rebuilding === run) rebuilding = null; });
    rebuilding = run;
    return run;
  }
  /** 생성 직전에 부른다: 아직 저장 · 재조립 안 된 편집이 있나(있으면 app.js 가 settle 을 기다린다). */
  function needsSettle() {
    if (!active()) return false;
    if (pendingRebuild || rebuilding || rebuildFailed || editsInFlight > 0) return true;
    if (PE_KEYS.some(key => peUnsaved[key] || pePending(key)
      || peTexts[key].value !== String(getPeField(key) || ''))) return true;
    return extraEl.value !== String(snap?.state?.extra || '');
  }
  /** 저장 · 재조립이 끝날 때까지 기다린다. 못 끝내면 false - 생성은 보내지 않는다. 안 기다리면 판에는 새 글이 보이는데
   *  생성은 옛 글로 나간다(Codex 리뷰 2026-11-12 #1: prefix 를 고치고 곧바로 Generate). */
  async function settle() {
    if (!active()) return true;
    const until = Date.now() + 6000;
    const late = () => {
      showToast('방금 고친 내용을 아직 프롬프트에 반영하지 못했습니다 - 잠시 뒤 다시 눌러 주세요', 'warning');
      return false;
    };
    // 한 바퀴 = 저장 → 보낸 편집 끝 → 서버가 PE 글을 돌려줌 → 재조립 → **다시 확인**. 기다리는 사이 또 고쳤으면 한 바퀴 더
    // (리뷰 2차 #4: 기다리는 동안 친 글을 안 보고 옛 조립 글로 보냈다).
    // 모든 기다림에 남은 시간을 건다 - 답이 끝내 안 오는 요청이 생성을 붙잡거나, 기한이 한참 지난 뒤에 뒤늦게 생성이
    // 나가지 않게(리뷰 3차 #4). LATE = 기한 안에 못 끝냈다.
    const LATE = Symbol('late');
    const within = promise => {
      const left = until - Date.now();
      if (left <= 0) return Promise.resolve(LATE);
      let timer = 0;
      const clock = new Promise(resolve => { timer = setTimeout(() => resolve(LATE), left); });
      return Promise.race([Promise.resolve(promise).finally(() => clearTimeout(timer)), clock]);
    };
    for (;;) {
      // 저장 못 한 글(거절 · 끊김)이 남은 칸은 다시 보내지 않는다 - 사용자가 [되돌리기] 하거나 고쳐야 풀린다
      if (PE_KEYS.some(key => peUnsaved[key] && peTexts[key].value !== String(peServer[key] ?? getPeField(key) ?? ''))
        && !PE_KEYS.some(pePending)) {
        const stuck = PE_KEYS.find(key => peUnsaved[key]);
        if (peSeenPreset[stuck] != null && peSeenPreset[stuck] === String(getPePreset() || '') && !peEchoes[stuck]) {
          // 끊김으로 못 보낸 글 - 다시 보내 본다(아래 commitPeText)
        } else {
          showToast('저장되지 않은 prefix / postfix 글이 있습니다 - 패널의 [되돌리기] 로 버리거나 다시 저장한 뒤 눌러 주세요', 'warning');
          return false;
        }
      }
      for (const key of PE_KEYS) {
        if (!commitPeText(peTexts[key])) return false;      // 알림은 commitPeText 가 했다
      }
      if ((await within(flushExtra())) !== true) return Date.now() >= until ? late() : false;
      // 보낸 편집(칩 · 등급 · Extra · 재조립 - 리뷰 2차 #3)과 서버의 PE 상태(#1)를 **함께** 기다린다. 따로 차례로 기다리면
      // PE 상태가 오자마자 나가는 재조립이 '안 끝난 편집' 으로 남아 여기서 곧바로 물러났다(실측 11-12).
      while ((editsInFlight > 0 || PE_KEYS.some(pePending)) && Date.now() < until) {
        if (editsInFlight > 0) { if ((await within(editChain)) === LATE) return late(); }
        else {
          if (dropRejectedPe()) return false;                 // 서버가 받지 않았다 - 알림은 dropRejectedPe 가 했다
          await new Promise(resolve => setTimeout(resolve, 30));
        }
      }
      if (editsInFlight > 0 || PE_KEYS.some(pePending)) return late();
      if (rebuilding && (await within(rebuilding)) === LATE) return late();
      // 실패했던 재조립은 여기서 다시 한다 - 성공해야 풀린다(리뷰 2차 #2: 두 번째 누름이 실패 검사를 건너뛰었다)
      if (pendingRebuild || rebuildFailed) {
        const done = await within(rebuild());
        if (done === LATE) return late();
        if (!done) return false;
      }
      if (Date.now() >= until) return late();
      if (!needsSettle()) return true;
    }
  }

  // ---- 스테이징 ----
  async function sendToStaging() {
    // 저장 못 한 Extra 로 스테이징 줄을 만들지 않는다(리뷰 #6: 실패를 무시하고 옛 Extra 로 보낸 뒤 성공이라고 했다)
    if (!(await flushExtra())) return;
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

  // ---- 남은 태그 창(사용자 지시 11-12) ----
  // E 단추 · Ctrl+E 가 Draft 중에 연다(eventMapPanel.mjs 가 가른다). 칩 넣기는 이 파일의 편집 줄(edit)을 빌려준다 -
  // 칸 입력과 같은 판 번호 차례 · 같은 receive. 실패는 던진다(창이 서버 메시지를 토스트한다).
  finder = initDraftTagFinder({
    esc, fmt, showToast, isActive: active, getSnapshot: () => snap, refreshSnapshot: load,
    addChip: async (zone, text) => {
      const data = await edit('/draft/chips', { op: 'add', zone, text });
      receive(data);      // 소켓 알림을 기다리지 않고 답으로 바로 그린다(칸 입력의 commit 과 같다)
      return data;
    },
  });
  // ---- 칩 카드(사용자 결정 11-12) - 칩 메뉴와 함께 뜨는 태그 카드. 넣기 · 지우기는 '남은 태그' 창과 같은 편집 줄을 빌려준다 ----
  chipCard = initDraftChipCard({
    esc, fmt, showToast, isActive: active, getSnapshot: () => snap,
    addChip: async (zone, text) => {
      const data = await edit('/draft/chips', { op: 'add', zone, text });
      receive(data);
      return data;
    },
    replaceChip: async (id, to) => {
      const data = await edit('/draft/chips', { op: 'replace', id, text: to });
      receive(data);
      return data;
    },
    onDone: () => closeMenu(),
    isMenuTarget: node => !!(menuEl && node && menuEl.contains(node)),
  });
  // ---- 영구 제외 창(사용자 지시 11-13) - 저장되면 스냅숏을 다시 받아 남은 게시물이 곧바로 바뀐다 ----
  permBox = initDraftPermExclude({
    esc, fmt, showToast, getSnapshot: () => snap, refreshSnapshot: load,
    onTextChange: text => onPermanentExcludeChange(text),
    searchFieldText: () => permanentExcludeFieldText(),
  });

  paintPill();
  void load();
  return {
    isActive: active,
    isAvailable: () => snap?.available !== false,
    savedPrompt: () => String(snap?.state?.saved_prompt ?? ''),
    /** WS `event_map_draft` */
    receive: message => receive({ ...message, __fromSocket: true }),
    reload: load,
    enter, exit, syncPe, notePeServer, sendToStaging, loadFromStaging, armPeek, disarmPeek, needsSettle, settle,
    toggleTagFinder: () => finder?.toggle(),
    isTagFinderOpen: () => !!finder?.isOpen(),
  };
}
