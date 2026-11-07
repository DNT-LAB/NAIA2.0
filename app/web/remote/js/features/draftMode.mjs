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
const SUGGEST_DEBOUNCE_MS = 150;
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
    if (now && !was) { drawnDismissed = false; shownRid = null; }
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
    <div class="dr-zone" data-dr-zone="include">
      <div class="dr-zh"><span class="dr-zt">포함</span></div>
      <div class="dr-chips" data-dr-chips="include"></div>
    </div>
    <div class="dr-zone" data-dr-zone="exclude">
      <div class="dr-zh"><span class="dr-zt dr-zt--ex">제외</span></div>
      <div class="dr-chips" data-dr-chips="exclude"></div>
    </div>
    <div class="dr-sum" data-dr-sum></div>
    <div class="dr-zone dr-zone--extra">
      <div class="dr-zh"><span class="dr-zt">Extra</span></div>
      <textarea class="dr-extra-text" data-dr-extra rows="2" maxlength="2000" spellcheck="false" aria-label="Extra Prompt"
        placeholder="이벤트 맵과 상관없는 태그 · 와일드카드 - 예: 1.2::artist:kim eb ::, __season__"></textarea>
    </div>
    <div class="dr-band dr-band--post"><span class="dr-band-name">postfix</span>
      <textarea class="dr-band-text" data-dr-pe="post_prompt" rows="1" spellcheck="false" aria-label="Postfix Prompt"></textarea></div>
    <div class="dr-suggest" data-dr-suggest hidden role="listbox"></div>`;
  const footer = host.querySelector('.prompt-token-footer');
  host.insertBefore(board, footer || null);
  const extraEl = board.querySelector('[data-dr-extra]');
  const sumEl = board.querySelector('[data-dr-sum]');
  const suggestEl = board.querySelector('[data-dr-suggest]');
  const bands = [...board.querySelectorAll('[data-dr-pe]')];
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
  let drawnPanel = null;
  let drawnDismissed = false;   // 이번 Draft 에서 사용자가 x 로 닫았다 - 새로 뽑혀도 저절로 열지 않는다
  let drawnSystemClose = false; // 화면이 닫는 중(Draft 끔 등) - 사용자가 닫은 것으로 치지 않는다
  let shownRid = null;          // 창을 마지막으로 연 게시물 - 같은 게시물로는 다시 열지 않는다
  function ensureDrawnPanel() {
    if (drawnPanel) return drawnPanel;
    drawnPanel = createDraggablePanel({
      document, window, title: '뽑힌 결과', variant: 'drw', storageKey: 'draft-drawn',
      width: 340, minWidth: 240, maxWidth: 720, height: 320, minHeight: 120, resizable: true, escHtml: esc,
      onClose: () => {
        if (!drawnSystemClose) drawnDismissed = true;
        closeMenu();
        paintSum();
      },
    });
    drawnPanel.body.appendChild(drawnEl);
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
    if (!drawnPanel?.isOpen()) return;
    drawnSystemClose = true;
    try { drawnPanel.close(); } finally { drawnSystemClose = false; }
  }
  function openDrawnPanel() {
    const panel = ensureDrawnPanel();
    if (!panel.isOpen()) panel.open();
    if (panel.isCollapsed()) panel.expand();
    panel.raise();
  }
  function toggleDrawnPanel() {
    if (drawnPanel?.isOpen()) { drawnPanel.close(); return; }
    drawnDismissed = false;
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
    box.innerHTML = html;
    box.append(input, counting);
  }
  function paintDrawn() {
    const st = snap?.state || {};
    const der = snap?.derived || {};
    const drawn = st.drawn;
    if (!drawn) {
      drawnEl.innerHTML = '';
      shownRid = null;
      closeDrawnPanel();
      return;
    }
    const gray = der.gray || [];
    const hidden = gray.filter(g => g.pe_hidden).length;
    const head = `${gray.filter(g => !g.dropped).length}개${hidden ? ` · PE 가 ${hidden}개 지움` : ''}`;
    if (drawnPanel || drawn.rid !== shownRid) ensureDrawnPanel().setTitle(`뽑힌 결과 · #${drawn.rid}`);
    if (drawn.rid !== shownRid) {
      shownRid = drawn.rid;
      if (!drawnDismissed) openDrawnPanel();
    }
    drawnEl.innerHTML = `<div class="drw-meta">${head}</div><div class="dr-chips dr-chips--drawn">${gray.map(g =>
      `<span class="dr-chip is-drawn${g.pe_hidden ? ' is-pe-hidden' : ''}${g.dropped ? ' is-dropped' : ''}" data-dr-gray="${esc(g.tag)}" tabindex="0" role="button"
        title="${g.dropped ? '이번만 뺀 태그 - 눌러서 다시 넣기' : (g.pe_hidden ? 'PE 필터가 지운 태그' : '뽑힌 태그 · 다음 Random 에 바뀜')}"><span class="dr-t">${esc(g.tag)}</span></span>`).join('')}</div>`;
  }
  function paintSum() {
    const der = snap?.derived || {};
    const remaining = der.remaining;
    const drawn = snap?.state?.drawn;
    const drawnOpen = !!drawnPanel?.isOpen();
    const drawnBtn = drawn ? `<button type="button" class="dr-btn${drawnOpen ? ' is-on' : ''}" data-dr-drawn-open aria-pressed="${drawnOpen}"
        title="뽑힌 게시물 #${esc(drawn.rid)} 의 태그 창 열기 · 닫기">뽑힌 결과 ${fmt((der.gray || []).filter(g => !g.dropped).length)}</button>` : '';
    const rating = der.rating_out ? `<span class="dr-rating" title="이 등급 태그가 프롬프트에 들어갑니다">${esc(der.rating_out)}</span>` : '';
    sumEl.innerHTML = `<span>남은 게시물</span><span class="dr-big">${remaining == null ? '—' : fmt(remaining)}</span>${rating}
      <span class="dr-gap"></span>
      ${drawnBtn}
      <button type="button" class="dr-btn" data-dr-stage title="지금 칩 조건을 스테이징 줄 하나로 보냅니다">스테이징으로 보내기</button>
      <button type="button" class="dr-btn" data-dr-from title="S 창을 엽니다 - 줄의 [드래프트로 불러오기]">불러오기</button>`;
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
    if (!on) { closeMenu(); hideSuggest(); closeDrawnPanel(); return; }
    paintZone('include');
    paintZone('exclude');
    paintDrawn();
    paintSum();
    paintBands();
    if (extraEl !== document.activeElement) {
      const text = String(snap?.state?.extra || '');
      if (extraEl.value !== text) extraEl.value = text;
    }
  }

  // ---- 칩 입력 ----
  function markBad(zone, on) { inputs[zone].input.classList.toggle('is-bad', !!on); }
  async function commit(zone, raw) {
    const text = String(raw || '').trim().replace(/,+$/, '').trim();
    if (!text) return;
    const { input, counting } = inputs[zone];
    hideSuggest();
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
    } catch (error) {
      markBad(zone, true);
      if (error.code !== 'zero_match') showToast(error.message || '칩을 넣지 못했습니다', 'warning');
      else showToast(error.message || '이 조건이면 남는 게시물이 없습니다', 'warning');
    } finally {
      clearTimeout(timer);
      counting.hidden = true;
    }
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
        void commit(zone, input.value);
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
        void (async () => { for (const part of parts) await commit(zone, part); })();
        return;
      }
      scheduleSuggest(zone);
    });
    input.addEventListener('blur', () => setTimeout(() => { if (!board.contains(document.activeElement)) hideSuggest(); }, 120));
  });

  // ---- 자동완성(포함 · 제외 = 맵 색인 안) ----
  let suggestTimer = null, suggestSeq = 0, suggestZone = '', suggestItems = [], suggestIndex = -1;
  function hideSuggest() {
    suggestEl.hidden = true;
    suggestEl.innerHTML = '';
    suggestItems = [];
    suggestIndex = -1;
    suggestZone = '';
  }
  function scheduleSuggest(zone) {
    clearTimeout(suggestTimer);
    let enabled = true;
    try { enabled = isAutocompleteEnabled() !== false; } catch (_) {}
    const q = inputs[zone].input.value.trim();
    if (!enabled || q.replace(/^\*/, '').length < 1) { hideSuggest(); return; }
    suggestTimer = setTimeout(() => void loadSuggest(zone, q), SUGGEST_DEBOUNCE_MS);
  }
  async function loadSuggest(zone, q) {
    const seq = ++suggestSeq;
    let data;
    // `*` 를 그대로 보낸다 - 서버가 퍼펙트 매칭으로 센다.
    try { data = await request(`/draft/suggest?q=${encodeURIComponent(q)}&zone=${zone}`); } catch (_) { return; }
    if (seq !== suggestSeq || inputs[zone].input.value.trim() !== q || document.activeElement !== inputs[zone].input) return;
    suggestItems = (data.items || []).filter(it => !it.blocked || it.kind === 'tag');
    suggestZone = zone;
    suggestIndex = -1;
    if (!suggestItems.length) { hideSuggest(); return; }
    suggestEl.innerHTML = suggestItems.map((it, i) => {
      const name = it.kind === 'rating' ? (it.label || RATING_LABEL[it.rating] || it.tag) : it.tag;
      const kr = it.kr ? `<span class="dr-sg-kr">${esc(it.kr)}</span>` : '';
      // 서버는 0건 후보도 blocked 로 준다 - '영구 제외' 는 수가 0 이 아닌데 막힌 것뿐이다.
      const count = (it.blocked && it.count_after !== 0) ? '<span class="dr-sg-n">영구 제외</span>'
        : (it.slow ? '<span class="dr-sg-n" title="걸리는 태그가 많아 세지 않았습니다">…</span>'
          // 후보 수는 그 태그 하나로 센 값이다 - 텍스트 칩이면 포함 칸은 하한(≥) · 제외 칸은 남는 수의 상한(≤).
          : (Number.isFinite(it.count_after) ? `<span class="dr-sg-n">${zone === 'exclude' ? '남음 ' : ''}${it.bound === 'min' ? '≥' : (it.bound === 'max' ? '≤' : '')}${fmt(it.count_after)}</span>` : ''));
      return `<div class="dr-sg${it.blocked ? ' is-blocked' : ''}${it.count_after === 0 ? ' is-zero' : ''}" role="option" data-dr-sg="${i}"><span class="dr-sg-t">${esc(name)}</span>${kr}${count}</div>`;
    }).join('');
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
  async function flushExtra() {
    if (!active()) return;
    const text = extraEl.value;
    if (text === String(snap?.state?.extra || '')) return;
    try { receive(await edit('/draft/extra', { text })); }
    catch (error) { showToast(error.message || 'Extra 를 저장하지 못했습니다', 'error'); }
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
