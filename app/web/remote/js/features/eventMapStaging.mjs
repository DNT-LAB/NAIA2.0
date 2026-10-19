/* S · 조합 — 스테이징(동결한 이벤트 맵 조합의 랜덤 풀)과 저장된 조합을 한 창에서(사용자 지시 2026-10-14).
 *
 * 왼쪽 가장자리 E · A 아래의 [S] 단추로 연다. 단추는 스테이징 또는 저장된 조합이 있을 때만 보이고, 오른쪽 위 배지는
 * 스테이징된 조합 수다.
 *
 *  · 맨 위 체크박스 = '스테이징 이벤트를 랜덤 버튼에 연결' - 메인 [Random] · Auto Gen 이 스테이징에서 조합 하나를 골라
 *    그 실제 게시물 하나를 뽑는다(버튼 글자 ST Random). 이벤트 맵의 '랜덤 버튼 연결' 과 **한 상태**라 한쪽을 켜면 다른
 *    쪽이 꺼진다(서버가 정한다 - /api/event-map/random-link mode).
 *  · [스테이징] 탭: 줄마다 [랜덤] [랜덤+생성] [맵에서 열기] [제외]. 아래 [통째로 저장] = 저장된 조합의 '묶음' · [비우기].
 *  · [저장된 조합] 탭: 예전 '조합 불러오기' 창을 대신한다. 줄마다 [스테이징 +] [맵에서 열기](묶음은 없음) [⋯]
 *    (이름 · 분류 · 삭제). 묶음의 [스테이징 +] 는 조합 전부를 넣는다.
 *  · 추가 프롬프트(사용자 지시 2026-10-19 - core/event_map/extra_prompt.py): 뽑힌 조합의 게시물 태그 뒤에 붙는 글.
 *    펼친 줄의 [추가 프롬프트] 체크 = 그 조합 것(켜면 칸이 열린다) · 하단 칸 = 공통(켜기 · 끄기). 개별이 있을 때 무엇을
 *    붙일지는 하단 [옵션](확장 기능 팝업과 같은 옷) - 합치기(기본) · 공통만 · 개별 우선. 글은 칸을 떠날 때 저장한다
 *    (칠 때마다 저장하면 다른 창이 계속 다시 받는다). 치던 글은 `drafts` 에 두고, 다시 그려도 초점 · 커서를 돌려준다.
 *    어느 줄의 글을 붙일지는 서버가 정한다 - [랜덤] 은 줄 id(저장된 묶음은 id + 몇 번째)만 보낸다.
 *
 * 서버가 다 한다(/api/event-map/staging · library · sample · apply). 여기서는 그리기와 단추뿐이다.
 */
import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

export function initEventMapStaging({ showToast, getPromptText, generateNow, confirmDialog,
                                      getEventMap = () => window.eventMap, isTabHidden = () => false } = {}) {
  const tabBtn = document.getElementById('stagingTab');
  const badge = tabBtn?.querySelector('.st-badge');
  let panel = null, open = false, tab = 'stage', busy = 0;
  let staged = [], saved = [], categories = [], stagedCount = 0, savedCount = 0;
  let category = '*', query = '', renaming = '';
  let openRow = '';                 // 스테이징 탭에서 펼친 줄(단추가 보이는 줄) - 한 번에 하나
  let reloadSeq = 0;
  let stagingRev = -1, stagingGen = null;   // 서버 스테이징 판 번호 · 세대 - 같은 세대의 옛 응답은 버린다(늦게 온 POST · GET 이 새 목록을 덮었다)
  const fresh = data => {
    if (typeof data?.rev !== 'number') return true;
    // 세대가 바뀌면(깨진 파일을 비우기로 되살림 · 파일이 새로 생김) 번호가 다시 낮아진다 - 번호와 상관없이 받는다.
    if (data.gen === stagingGen && data.rev < stagingRev) return false;
    stagingGen = data.gen; stagingRev = data.rev;
    return true;
  };
  let counts = null;                // 서버가 센 게시물 수: { per: {id: n}, total(겹침 제외), sum }
  // 수를 다시 세야 하는데 아직 못 받았다 - 그 사이 온 추가 프롬프트 알림(수 그대로)이 재집계를 끊고 옛 수를 다시 쓰지 않게
  // (Codex 리뷰 2026-10-19). 수를 실은 응답을 받아야 풀린다.
  let needCounts = false;
  let common = { on: false, text: '', mode: 'merge' };   // 공통 추가 프롬프트 · 방식(서버 staging.json 의 extra)
  const drafts = new Map();          // 저장 전 치던 글: 줄 id | 'common' -> 글
  let optEl = null, optOpen = false;   // 하단 [옵션] 팝업
  // 누르고 아직 답을 못 받은 켜기 · 방식: '줄 id | common' + 필드 -> {key, field, value}. 서버 목록을 받을 때마다 다시 얹는다 -
  // 앞선 저장의 응답(옛 값)이 방금 끈 스위치를 되켜고, 그 상태로 다음 글 저장이 켜짐을 보내지 않게(Codex 5차).
  // 필드마다 그 요청이 소유한다 - 합치면 실패한 필드가 뒤 요청 몫으로 남아 화면만 켜진 채가 된다(Codex 6차).
  const pending = new Map();
  const overlayPending = () => {
    for (const { key, field, value } of pending.values()) {
      if (key === 'common') common = { ...common, [field]: value };
      else { const r = staged.find(x => x.id === key); if (r) r.extra = { ...(r.extra || {}), [field]: value }; }
    }
  };
  const holdPending = (key, patch, done) => {
    for (const [field, value] of Object.entries(patch)) {
      const slot = `${key}|${field}`, entry = { key, field, value };
      pending.set(slot, entry);
      // 끝나면(성공이든 실패든) 이 요청 몫만 내려놓는다. 실패면 reload 가 서버 값으로 되돌린다.
      done.then(() => { if (pending.get(slot) === entry) pending.delete(slot); });
    }
  };
  const takeCommon = data => {   // 목록을 받은 곳마다 staged 다음에 부른다 - 대기 중인 켜기 · 방식을 다시 얹는다
    const x = data?.extra;
    if (x && typeof x === 'object') common = { on: x.on === true, text: String(x.text || ''), mode: x.mode || 'merge' };
    overlayPending();
  };
  let menuEl = null, menuFor = '';   // 저장된 조합 [분류 변경] 메뉴(분류 · 삭제). 이름은 이름 뒤 ✎ 로(사용자 지시 2026-10-14)

  // 켜진 조합 수 = 배지 · 이벤트 맵 숫자 단추(사용자 지정 2026-10-15). 꺼진 조합은 ST Random 후보가 아니다.
  const activeCount = () => staged.filter(r => r.enabled !== false).length;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const toast = (message, kind = 'info') => { if (typeof showToast === 'function') showToast(message, kind); };
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID()
    : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => { const r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16); }));

  async function request(path, body) {
    const res = await fetch(path, { method: body ? 'POST' : 'GET', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(20000) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw Object.assign(new Error(data.message || `HTTP ${res.status}`), { code: data.code });
    return data;
  }
  // 서버의 지문(library._fingerprint · normalize_tag)과 같은 뜻: 태그는 소문자 · 밑줄 = 빈칸 · 빈칸 접기, 네 목록 모두 순서 무시.
  const norm = t => String(t || '').trim().toLowerCase().replace(/_/g, ' ').replace(/\s+/g, ' ');
  const fingerprint = s => JSON.stringify([[...new Set(s.pins.map(norm))].sort(), [...new Set(s.exclude.map(norm))].sort(),
    [...s.ratings].sort(), [...s.persons].sort()]);
  /** 이미 스테이징에 있는 조합인가 - [스테이징 +] · 이벤트 맵 '스테이징에 넣기' 를 미리 끈다(사용자 지시 2026-10-14). */
  const isStaged = s => !!s && staged.some(r => fingerprint(r.selection) === fingerprint(s));
  // 인원 · 등급 = 색 칩(사용자 지시 2026-10-14). 인원은 여성 · 남성 · 혼성 셋으로만 칠한다(수에 따라 나누지 않는다).
  const PERSON = {
    '1girl_solo': ['여1 단독', 'f'], '1girl': ['여1', 'f'], '2girls': ['여2', 'f'], multiple_girls: ['여다수', 'f'],
    '1girl_1boy': ['여1 남1', 'x'], '1girl_multiple_boys': ['여1 남다수', 'x'], '1boy_multiple_girls': ['남1 여다수', 'x'],
    multiple_girls_multiple_boys: ['여다수 남다수', 'x'],
    '1boy_solo': ['남1 단독', 'm'], '1boy': ['남1', 'm'], '2boys': ['남2', 'm'], multiple_boys: ['남다수', 'm'], other: ['기타', 'o'],
  };
  const metaHtml = s => {
    const ps = s.persons.map(p => { const [label, kind] = PERSON[p] || [p.replaceAll('_', ' '), 'o'];
      return `<span class="st-chip st-p-${kind}">${esc(label)}</span>`; }).join('');
    const rs = ['g', 's', 'q', 'e'].filter(r => s.ratings.includes(r))
      .map(r => `<span class="st-chip st-r-${r}">${r.toUpperCase()}</span>`).join('');
    return `<span class="st-chips">${ps}${rs}</span>${s.exclude.length ? `<span class="st-ex">제외 ${esc(s.exclude.join(', '))}</span>` : ''}`;
  };
  // 접힌 줄에서도 추가 프롬프트가 있는 줄을 알아보게(켜져 있고 글이 있을 때만).
  const extraChip = (ex, label = '+ 추가') => (ex?.on && ex.text
    ? `<span class="st-chip st-xp" title="추가 프롬프트: ${esc(ex.text)}">${label}</span>` : '');
  const extraText = (key, ex) => (drafts.has(key) ? drafts.get(key) : String(ex?.text || ''));
  function extraHtml(r) {
    const on = r.extra?.on === true;
    return `<div class="st-extra">
      <label class="st-extra-on"><input type="checkbox" data-st-extra-on ${on ? 'checked' : ''}>추가 프롬프트</label>
      ${on ? `<textarea class="st-extra-text" data-st-extra-text rows="2" maxlength="2000" spellcheck="false" aria-label="이 조합의 추가 프롬프트"
        placeholder="이 조합이 뽑혔을 때 뒤에 붙일 태그 - 예: from behind, sweat, __outfit__">${esc(extraText(r.id, r.extra))}</textarea>` : ''}
    </div>`;
  }

  // ── 단추 · 배지 ─────────────────────────────────────────────────────────────
  function paintTab() {
    if (!tabBtn) return;
    // Settings '스테이징 단추 숨기기' 면 감춘다 - 이벤트 맵 [스테이징] 옆 숫자 단추로는 그대로 연다(사용자 지시 2026-10-14).
    tabBtn.hidden = Boolean(isTabHidden()) || !(stagedCount || savedCount);
    tabBtn.setAttribute('aria-pressed', String(open));
    tabBtn.classList.toggle('is-linked', getEventMap()?.randomLinkMode?.() === 'staging');
    if (badge) {
      const on = staged.length ? activeCount() : stagedCount;
      badge.hidden = !stagedCount;
      badge.textContent = String(on);
      badge.classList.toggle('is-off', !on);   // 전부 꺼짐 - 흐린 0
    }
    getEventMap()?.syncStaged?.();   // 이벤트 맵 [스테이징] 옆 숫자 단추
  }
  async function refreshCounts() {
    // counts=0 - 배지는 개수만 있으면 된다. 수를 세면 서버가 색인을 연다(첫 기동 lazy - 리뷰 2026-10-14).
    try {
      const s = await request('/api/event-map/staging?counts=0');
      if (fresh(s)) { staged = s.items; stagedCount = staged.length; takeCommon(s); }
    } catch { /* 서버가 없으면 그대로 */ }
    try { savedCount = (await request('/api/event-map/library')).items.length; } catch { /* 같은 이유 */ }
    paintTab();
  }

  // ── 창 ─────────────────────────────────────────────────────────────────────
  function build() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document, window, id: 'stagingWindow', title: 'S · 조합', variant: 'em-overlay em-window st-window',
      storageKey: 'staging', width: 400, height: 460, minWidth: 340, minHeight: 240, maxWidth: 900,
      initial: { x: 430, y: 64 }, resizable: true, onClose: close,
    });
    panel.body.innerHTML = `
      <label class="st-link"><input type="checkbox" data-st-link>스테이징 이벤트를 랜덤 버튼에 연결 적용합니다</label>
      <div class="st-total" role="status"></div>
      <div class="st-tabs" role="tablist"><button type="button" data-st-tab="stage" role="tab"></button><button type="button" data-st-tab="saved" role="tab"></button></div>
      <div class="st-body"></div>
      <div class="st-foot"></div>`;
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('change', onChange);
    panel.body.addEventListener('input', event => {
      // 칸은 두고 목록만 - 칸까지 갈아 끼우면 첫 글자에서 초점이 나가 연속 입력 · 한글 조합이 끊긴다(리뷰 2026-10-14).
      if (event.target.matches('[data-st-search]')) { query = event.target.value; paintSavedList(); }
      // 추가 프롬프트는 치는 동안 저장하지 않는다(칸을 떠날 때 change) - 그 사이 다시 그려도 글이 남게 둔다.
      if (event.target.matches('[data-st-extra-text]')) drafts.set(event.target.closest('[data-st-id]')?.dataset.stId, event.target.value);
      if (event.target.matches('[data-st-common-text]')) drafts.set('common', event.target.value);
    });
    panel.body.addEventListener('focusout', event => {
      if (event.target.matches?.('[data-st-extra-text], [data-st-common-text]')) commitText(event.target);
    });
    panel.body.addEventListener('keydown', event => {
      event.stopPropagation();
      // Ctrl+Enter = 칸을 떠나며 저장(Enter 는 줄바꿈 그대로)
      if (event.target.matches('.st-extra-text') && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault(); event.target.blur(); return;
      }
      if (!event.target.matches('[data-st-name]')) return;
      if (event.key === 'Escape') { renaming = ''; paintBody(); return; }
      if (event.key !== 'Enter' || event.isComposing) return;
      const id = event.target.closest('[data-st-id]')?.dataset.stId, name = event.target.value.trim();
      renaming = '';
      if (id && name) void run(() => mutateSaved({ action: 'rename', id, name }, '이름을 바꿨습니다'));
      else paintBody();
    });
    return panel;
  }
  async function show(which = tab) {
    build();
    tab = which;
    open = true;
    panel.open();
    paintTab();
    await reload();
  }
  function close() {
    if (!open) return;
    closeMenu();
    closeOpt();
    open = false;
    if (panel?.isOpen()) panel.close();
    paintTab();
  }
  /** keepCounts = 게시물 수가 안 바뀐 변경(추가 프롬프트) - 이미 센 수를 두고 다시 세지 않는다. */
  async function reload({ keepCounts = false } = {}) {
    const mine = ++reloadSeq;   // 늦게 온 옛 응답이 새 결과(빼기 등)를 덮지 않게
    const reuse = keepCounts && counts && !needCounts;
    if (!reuse) needCounts = true;
    try {
      const [s, l] = await Promise.all([request(`/api/event-map/staging${reuse ? '?counts=0' : ''}`), request('/api/event-map/library')]);
      if (mine !== reloadSeq) return;
      if (fresh(s)) { staged = s.items; if (!reuse) { counts = s.counts || null; needCounts = false; } takeCommon(s); }
      saved = l.items; categories = l.categories || [];
      stagedCount = staged.length; savedCount = saved.length;
      if (s.random_link) getEventMap()?.receiveRandomLink?.(s.random_link);
    } catch (error) { toast(`조합을 불러오지 못했습니다 — ${error.message}`, 'error'); }
    paint();
  }
  function paint() {
    paintTab();
    if (!panel || !open) return;
    const linkBox = panel.body.querySelector('[data-st-link]');
    linkBox.checked = getEventMap()?.randomLinkMode?.() === 'staging';
    linkBox.disabled = !activeCount() && !linkBox.checked;
    // 전체 프롬프트 수 = 스테이징 조합들에 맞는 게시물(겹치는 게시물은 한 번만) - 사용자 지시 2026-10-14
    const total = panel.body.querySelector('.st-total');
    total.hidden = !staged.length;
    total.innerHTML = counts ? `총 프롬프트 <b>${Number(counts.total).toLocaleString('en-US')}</b>건${counts.sum !== counts.total
      ? ` <span title="여러 조합에 함께 걸리는 게시물은 한 번만 셉니다">· 중복 ${Number(counts.sum - counts.total).toLocaleString('en-US')}건 제외</span>` : ''}`
      : '<span>이벤트 맵 색인이 열리면 프롬프트 수를 셉니다</span>';
    const offN = staged.length - activeCount();
    if (offN) total.insertAdjacentHTML('beforeend', ` <span class="st-off-n" title="꺼진 조합은 랜덤 후보와 전체 수에서 빠집니다">· 꺼짐 ${offN}</span>`);
    if (optOpen) paintOpt();
    panel.body.querySelectorAll('[data-st-tab]').forEach(b => {
      const on = b.dataset.stTab === tab;
      b.classList.toggle('is-on', on); b.setAttribute('aria-selected', String(on));
      const live = activeCount();
      b.textContent = b.dataset.stTab === 'stage' ? `스테이징 ${live === staged.length ? live : `${live}/${staged.length}`}`
        : `저장된 조합 ${saved.length}`;
    });
    paintBody();
  }
  function paintBody() {
    const body = panel.body.querySelector('.st-body'), foot = panel.body.querySelector('.st-foot');
    panel.body.inert = busy > 0;
    if (tab === 'stage') {
      // 추가 프롬프트 칸에서 치던 중이면 다시 그린 뒤 초점 · 커서를 돌려준다(저장 응답 · 다른 창의 알림으로 다시 그린다).
      const act = document.activeElement;
      const focusKey = act?.matches?.('[data-st-common-text]') ? 'common'
        : act?.matches?.('[data-st-extra-text]') ? act.closest('[data-st-id]')?.dataset.stId || '' : '';
      const caret = focusKey ? [act.selectionStart, act.selectionEnd, act.scrollTop] : null;
      paintStage(body, foot);
      if (focusKey) {
        const field = focusKey === 'common' ? foot.querySelector('[data-st-common-text]')
          : [...body.querySelectorAll('[data-st-extra-text]')].find(f => f.closest('[data-st-id]')?.dataset.stId === focusKey);
        if (field) { field.focus({ preventScroll: true }); field.setSelectionRange(caret[0], caret[1]); field.scrollTop = caret[2]; }
      }
      return;
    }
    paintSavedTab(body, foot);
  }
  function paintStage(body, foot) {
    // 줄은 태그 · 칩만. 누르면 펼쳐져 단추가 아래 줄에 나온다(마우스를 대면 펼치면 줄이 밀려 다른 줄을 집는다).
    // 맨 앞 스위치 = 켜기 · 끄기(사용자 지시 2026-10-15). 꺼진 줄은 흐리게 - 랜덤 후보 · 전체 수에서 빠진다.
    // 펼친 줄 맨 아래 = [추가 프롬프트] 체크(켜면 칸이 열린다 - 사용자 지시 2026-10-19).
    body.innerHTML = staged.length ? staged.map(r => `<div class="st-row st-pick${openRow === r.id ? ' is-open' : ''}${r.enabled === false ? ' is-off' : ''}" data-st-id="${esc(r.id)}" data-st-pick
        aria-expanded="${openRow === r.id}" title="${openRow === r.id ? '' : '눌러서 랜덤 · 랜덤+생성 · 맵에서 열기 · 제외 · 추가 프롬프트'}">
        <button type="button" class="st-sw" data-st-toggle role="switch" aria-checked="${r.enabled !== false}"
          title="${r.enabled === false ? '꺼짐 - 눌러서 랜덤 후보에 넣기' : '켜짐 - 눌러서 랜덤 후보에서 빼기'}"></button>
        <div class="st-bd"><div class="st-head"><span class="st-name">${esc(r.selection.pins.join(', '))}</span>${counts?.per?.[r.id] != null
          ? `<span class="st-count" title="이 조합에 맞는 게시물(프롬프트) 수">${Number(counts.per[r.id]).toLocaleString('en-US')}</span>` : ''}</div>
        <div class="st-meta">${metaHtml(r.selection)}${extraChip(r.extra)}</div>
        </div>
        ${openRow === r.id ? `<div class="st-acts st-acts-open"><button type="button" data-st-random>랜덤</button><button type="button" class="is-primary" data-st-random-gen>랜덤+생성</button><button type="button" data-st-open>맵에서 열기</button><button type="button" class="is-danger" data-st-remove>제외</button></div>${extraHtml(r)}` : ''}
      </div>`).join('')
      : '<div class="st-empty">스테이징된 조합이 없습니다. 이벤트 맵 [⋯] 의 <b>스테이징에 넣기</b>, 또는 저장된 조합의 <b>스테이징 +</b>.</div>';
    // 하단 = 공통 추가 프롬프트(켜기 · 끄기 - 꺼도 글은 남는다) + [통째로 저장] [비우기] ...... [옵션]
    foot.innerHTML = `<div class="st-common${common.on ? '' : ' is-off'}">
        <label class="st-extra-on"><input type="checkbox" data-st-common-on ${common.on ? 'checked' : ''}>추가 프롬프트 <span>· 공통 - 뽑힌 조합 뒤에 붙습니다</span></label>
        <textarea class="st-extra-text" data-st-common-text rows="2" maxlength="2000" spellcheck="false" aria-label="공통 추가 프롬프트"
          placeholder="모든 조합 뒤에 붙일 태그 - 예: masterpiece, detailed background">${esc(extraText('common', common))}</textarea>
      </div>
      <button type="button" data-st-bundle ${staged.length ? '' : 'disabled'} title="지금 스테이징을 저장된 조합의 '묶음' 하나로(추가 프롬프트 포함)">통째로 저장</button>
      <button type="button" data-st-clear ${staged.length ? '' : 'disabled'} title="조합만 비웁니다 - 공통 추가 프롬프트는 남습니다">비우기</button>
      <span class="st-foot-gap"></span>
      <button type="button" class="st-opt-btn${common.mode !== 'merge' ? ' has-on' : ''}" data-st-opt aria-haspopup="true"
        aria-expanded="${optOpen}" title="개별 추가 프롬프트가 있을 때 무엇을 붙일지">옵션</button>`;
  }
  function paintSavedTab(body, foot) {
    const options = (selected, all) => (all ? `<option value="*">전체 분류</option>` : '')
      + `<option value="" ${selected === '' ? 'selected' : ''}>미분류</option>`
      + categories.map(c => `<option value="${esc(c)}" ${selected === c ? 'selected' : ''}>${esc(c)}</option>`).join('');
    // 다시 그려도 검색 칸에 치던 중이면 초점 · 커서를 돌려준다(다른 창의 알림으로 다시 받은 경우).
    const typing = document.activeElement?.matches?.('[data-st-search]') ? document.activeElement : null;
    const caret = typing ? [typing.selectionStart, typing.selectionEnd] : null;
    body.innerHTML = `<div class="st-search"><select class="st-filter" data-st-filter aria-label="분류">${options(category, true)}</select>
        <input data-st-search placeholder="이름 · 태그 검색…" value="${esc(query)}" aria-label="저장된 조합 검색"></div>
      <div class="st-list"></div>`;
    paintSavedList();
    if (caret) {
      const field = body.querySelector('[data-st-search]');
      field.focus({ preventScroll: true });
      field.setSelectionRange(...caret);
    }
    foot.innerHTML = '';
  }
  function paintSavedList() {
    const list = panel?.body.querySelector('.st-list');
    if (!list) return;
    const q = query.trim().toLowerCase();
    const rows = saved.filter(r => (category === '*' || r.category === category)
      && (!q || [r.name, ...(r.selections || [r.selection]).flatMap(s => [...s.pins, ...s.exclude])].join(' ').toLowerCase().includes(q)));
    list.innerHTML = rows.length ? rows.map(r => {
        const bundle = r.kind === 'bundle';
        const sel = r.selections || [r.selection];
        const inStage = sel.every(isStaged);   // 묶음은 전부 들어가 있어야 '스테이징됨'
        // 줄 = 분류 · 이름 · 칩 + [스테이징 +](지금 자리). 누르면 펼쳐져 나머지 단추가 아래 줄에(사용자 지시 2026-10-17 -
        // 줄마다 단추 다섯이 정신없다 · 스테이징 탭과 같은 손버릇). 한 번에 한 줄만.
        const opened = openRow === r.id;
        return `<div class="st-row st-saved-pick${opened ? ' is-open' : ''}" data-st-id="${esc(r.id)}" data-st-pick aria-expanded="${opened}"
            title="${opened ? '' : '눌러서 이름 · 분류 변경 · 맵에서 열기 · 랜덤'}">
          <div class="st-head"><span class="st-cat">${esc(r.category || '미분류')}</span>${bundle
            ? `<span class="st-chip st-bundle" title="조합 ${sel.length}개를 묶은 것 - 스테이징하면 전부 들어갑니다">묶음 ${sel.length}</span>` : ''}${bundle
            && ((r.extras || []).some(e => e?.on && e.text) || (r.extra?.on && r.extra.text))
            ? '<span class="st-chip st-xp" title="추가 프롬프트가 함께 저장된 묶음 - 스테이징하면 줄마다 따라 들어가고, 지금 공통 칸이 비어 있으면 공통도 가져옵니다">+ 추가</span>' : ''}${renaming === r.id
            ? `<input class="st-rename" data-st-name maxlength="100" value="${esc(r.name)}" aria-label="새 이름 - Enter 저장 · Esc 취소">`
            : `<span class="st-name">${esc(r.name)}</span>`}</div>
          ${!bundle && r.name !== r.selection.pins.join(', ') ? `<div class="st-pins">${esc(r.selection.pins.join(', '))}</div>` : ''}
          <div class="st-line"><div class="st-meta">${bundle ? `${esc(sel.slice(0, 3).map(s => s.pins.join(', ')).join(' / '))}${sel.length > 3 ? ' …' : ''}` : metaHtml(r.selection)}</div>
            <div class="st-acts"><button type="button" class="${inStage ? 'is-done' : 'is-primary'}" data-st-stage-saved ${inStage ? 'disabled title="이미 스테이징에 있는 조합입니다"' : ''}>${inStage ? '✓ 스테이징됨' : '스테이징 +'}</button></div></div>
          ${opened ? `<div class="st-acts st-acts-open st-saved-acts"><button type="button" data-st-pen title="이름 바꾸기">✎ 이름</button><button type="button" data-st-more aria-haspopup="menu" aria-expanded="${menuFor === r.id}" title="분류 옮기기 · 삭제">분류 변경</button><span class="st-acts-gap"></span>${bundle ? '' : '<button type="button" data-st-open-saved>맵에서 열기</button>'}<button type="button" data-st-random-saved title="${bundle ? '묶음의 켜진 조합 하나에서 ' : ''}실제 게시물 하나를 프롬프트로">랜덤</button><button type="button" data-st-random-gen-saved title="랜덤 뒤 바로 생성">랜덤+생성</button></div>` : ''}
        </div>`;
      }).join('') : saved.length ? '<div class="st-empty">맞는 조합이 없습니다.</div>'
      : '<div class="st-empty">저장된 조합이 없습니다. 이벤트 맵 [⋯] 의 <b>이 조합 저장하기</b>.</div>';
  }

  // ── 동작 ───────────────────────────────────────────────────────────────────
  /** 저장 안 된 초안(저장이 실패해 서버 글과 다른 채 남은 칸)이 있나 - 줄이 사라진 초안은 셈하지 않는다. */
  function unsavedDraft() {
    for (const [key, value] of drafts) {
      const ex = key === 'common' ? common : staged.find(r => r.id === key)?.extra;
      if (ex && String(value).trim() !== String(ex.text || '').trim()) return true;
    }
    return false;
  }
  /** readsExtras = 추가 프롬프트를 읽는 동작(통째로 저장 · 스테이징 줄의 랜덤). */
  async function run(task, { readsExtras = false } = {}) {
    // 묶음 저장 · 랜덤 등은 추가 프롬프트를 읽는다 - 치던 칸을 먼저 확정하고, 저장 큐가 빈 뒤에 보낸다(Codex 2차).
    const typing = document.activeElement;
    if (typing?.matches?.('[data-st-extra-text], [data-st-common-text]')) commitText(typing);
    busy++; paint();
    try {
      await saveQueue;
      // 저장이 실패해 화면의 글과 서버 글이 다르면 멈춘다 - 옛 글로 묶거나 뽑지 않는다(Codex 7차). 칸을 다시 떠나면 다시 저장한다.
      if (readsExtras && unsavedDraft()) throw new Error('저장되지 않은 추가 프롬프트가 있습니다 - 칸을 눌렀다 떠나 다시 저장해주세요');
      await task();
    } catch (error) { toast(error.message, 'error'); } finally { busy--; paint(); }
  }
  /** keepCounts = 게시물 수가 안 바뀐 변경(추가 프롬프트) - 수 없는 응답이어도 지금 수를 그대로 둔다. */
  function applyStaging(data, keepCounts = false) {
    if (!fresh(data)) return;   // 더 새 목록을 이미 받았다
    ++reloadSeq;                // 이 결과가 더 새것이다 - 진행 중인 reload 응답은 버린다
    staged = data.items; stagedCount = staged.length;
    takeCommon(data);
    if ('counts' in data) { counts = data.counts; needCounts = false; }
    else if (keepCounts) { if (needCounts && open) void reload(); }   // 이 응답이 진행 중인 재집계를 끊었다 - 다시
    else {
      // 수 없이 바뀌었다(창이 닫혀 있을 때 보낸 [스테이징]) - 옛 수는 지금 목록과 안 맞는다(재리뷰 2026-10-15).
      counts = null;
      if (open) void reload();
    }
    getEventMap()?.syncStaged?.();   // 이벤트 맵 [스테이징] 단추의 켜짐(이미 들어간 조합이면 끈다)
    if (data.random_link) getEventMap()?.receiveRandomLink?.(data.random_link);
  }
  /** ref = 추가 프롬프트를 고를 자리 - { stagingId } 또는 { savedId, index }. 글은 서버가 그 자리에서 읽는다. */
  async function randomFrom(sel, andGenerate, ref = {}) {
    const params = new URLSearchParams({ pins: sel.pins.join(','), exclude: sel.exclude.join(','),
      ratings: sel.ratings.join(','), persons: sel.persons.join(','), n: '1', seed: String(Date.now() % 1000003) });
    const body = await request(`/api/event-map/sample?${params}`);
    const s = (body.samples || [])[0];
    if (!s?.tags?.length) throw new Error('이 조합에 맞는 게시물이 없습니다');
    const applied = await request('/api/event-map/apply', { tags: s.tags, rating: String(s.partition || 's').slice(0, 1), ...ref });
    if (!andGenerate) { toast(`랜덤 프롬프트를 할당했습니다 (${String(s.partition || '').replace(/_/g, ' ')})`, 'success'); return; }
    // 적용된 프롬프트가 칸에 들어온 뒤(최대 2초) Generate 와 같은 길 - 이벤트 맵의 applyThenGenerate 와 같다.
    const want = String(applied.prompt || '').trim();
    const read = () => (typeof getPromptText === 'function' ? String(getPromptText() || '') : '').trim();
    for (let n = 0; n < 20 && want && read() !== want; n++) await new Promise(r => setTimeout(r, 100));
    if (typeof generateNow !== 'function') throw new Error('생성 단추가 연결되지 않았습니다');
    generateNow();
    toast('랜덤 프롬프트를 적용하고 생성을 눌렀습니다', 'success');
  }
  async function openInMap(sel) {
    const map = getEventMap();
    if (!map?.openSelection) throw new Error('이벤트 맵을 열 수 없습니다');
    await map.openSelection(sel);
  }

  async function onClick(event) {
    const t = event.target;
    const tb = t.closest('[data-st-tab]');
    if (tb) { tab = tb.dataset.stTab; renaming = ''; openRow = ''; closeMenu(); closeOpt(); paint(); return; }
    if (t.closest('[data-st-opt]')) { if (optOpen) closeOpt(); else openOpt(t.closest('[data-st-opt]')); return; }
    const id = t.closest('[data-st-id]')?.dataset.stId;
    const stagedRow = staged.find(r => r.id === id), savedRow = saved.find(r => r.id === id);
    if (t.closest('[data-st-random]') && stagedRow) { await run(() => randomFrom(stagedRow.selection, false, { stagingId: id }), { readsExtras: true }); return; }
    if (t.closest('[data-st-random-gen]') && stagedRow) { await run(() => randomFrom(stagedRow.selection, true, { stagingId: id }), { readsExtras: true }); return; }
    if (t.closest('[data-st-open]') && stagedRow) { await run(() => openInMap(stagedRow.selection)); return; }
    if (t.closest('[data-st-toggle]') && stagedRow) {
      await run(async () => applyStaging(await request('/api/event-map/staging',
        { action: 'toggle', id, enabled: stagedRow.enabled === false })));
      return;
    }
    if (t.closest('[data-st-remove]') && stagedRow) {
      await run(async () => applyStaging(await request('/api/event-map/staging', { action: 'remove', id })));
      return;
    }
    if (t.closest('[data-st-clear]')) {
      const ok = typeof confirmDialog === 'function' ? await confirmDialog(`스테이징 ${staged.length}개를 비웁니다.`) : true;
      if (ok) await run(async () => applyStaging(await request('/api/event-map/staging', { action: 'clear' })));
      return;
    }
    if (t.closest('[data-st-bundle]')) {
      await run(async () => {
        const data = await request('/api/event-map/staging', { action: 'save_bundle', id: uuid() });
        saved = data.saved; savedCount = saved.length;
        toast(`묶음으로 저장했습니다 — ${data.item.name}`, 'success');
      }, { readsExtras: true });
      return;
    }
    if (t.closest('[data-st-stage-saved]') && savedRow) {
      await run(async () => {
        const data = await request('/api/event-map/staging', { action: 'stage_saved', id });
        const n = data.added || 0;
        applyStaging(data);
        const more = data.common_adopted ? ' · 묶음의 공통 추가 프롬프트도 가져왔습니다' : '';
        toast(n ? `스테이징에 ${n}개 넣었습니다${more}` : `이미 스테이징에 있는 조합입니다${more}`, n || more ? 'success' : 'info');
      }, { readsExtras: true });   // 공통을 가져올지는 지금 공통 글이 비었는지로 정한다
      return;
    }
    if (t.closest('[data-st-open-saved]') && savedRow) { await run(() => openInMap(savedRow.selection)); return; }
    // 저장된 조합의 [랜덤] · [랜덤+생성](사용자 지시 2026-10-17). 묶음은 켜진 조합 중 하나(전부 꺼졌으면 아무거나).
    const savedRandom = t.closest('[data-st-random-saved], [data-st-random-gen-saved]');
    if (savedRandom && savedRow) {
      const sel = savedRow.selections || [savedRow.selection];
      const flags = Array.isArray(savedRow.enabled) && savedRow.enabled.length === sel.length ? savedRow.enabled : null;
      const all = sel.map((_, i) => i);
      const pool = flags && flags.some(Boolean) ? all.filter(i => flags[i]) : all;
      const index = pool[Math.floor(Math.random() * pool.length)];   // 몇 번째인지 = 묶음에 저장된 그 조합의 추가 프롬프트
      await run(() => randomFrom(sel[index], savedRandom.hasAttribute('data-st-random-gen-saved'), { savedId: id, index }));
      return;
    }
    // 스테이징 줄 펼치기 · 접기(단추 · 추가 프롬프트 칸을 누른 것이 아닐 때)
    const pick = t.closest('[data-st-pick]');
    if (pick && !t.closest('button, input, .st-extra')) {
      openRow = openRow === id ? '' : id;
      if (tab === 'saved') { closeMenu(); paintSavedList(); } else paintBody();
      return;
    }
    if (t.closest('[data-st-pen]') && savedRow) {
      closeMenu();
      renaming = id; paintBody();
      const field = panel.body.querySelector('[data-st-name]');
      field?.focus(); field?.select();
      return;
    }
    if (t.closest('[data-st-more]') && savedRow) {
      if (menuFor === id) closeMenu(); else openMenu(savedRow, t.closest('[data-st-more]'));
    }
  }
  // ── 저장된 조합 [⋯] 메뉴 ─────────────────────────────────────────────────────
  function openMenu(row, btn) {
    if (!menuEl) {
      menuEl = document.createElement('div');
      menuEl.className = 'st-menu';
      menuEl.setAttribute('role', 'menu');
      menuEl.hidden = true;
      document.body.append(menuEl);
      menuEl.addEventListener('click', onMenuClick);
      menuEl.addEventListener('keydown', event => {
        event.stopPropagation();
        if (event.key === 'Escape') { closeMenu(); return; }
        if (event.key === 'Enter' && !event.isComposing && event.target.matches('[data-stm-newcat]')) {
          event.preventDefault();
          menuEl.querySelector('[data-stm-addcat]')?.click();
        }
      });
    }
    menuFor = row.id;
    const cats = ['', ...categories];
    menuEl.innerHTML = `
      <div class="st-menu-label">분류 옮기기</div>
      ${cats.map(c => `<button type="button" role="menuitemradio" aria-checked="${row.category === c}" class="st-menu-cat${row.category === c ? ' is-cur' : ''}" data-stm-cat="${esc(c)}"><i>${row.category === c ? '✓' : ''}</i>${esc(c || '미분류')}</button>`).join('')}
      <div class="st-menu-new"><input data-stm-newcat maxlength="60" placeholder="새 분류" aria-label="새 분류 이름"><button type="button" data-stm-addcat>추가</button></div>
      <div class="st-menu-sep"></div>
      <button type="button" role="menuitem" class="is-danger" data-stm="delete">삭제</button>`;
    menuEl.hidden = false;
    menuEl.style.zIndex = String(Number(panel.el.style.zIndex || 0) + 2);
    const r = btn.getBoundingClientRect(), m = menuEl.getBoundingClientRect();
    menuEl.style.left = `${Math.round(Math.max(8, Math.min(r.right - m.width, window.innerWidth - m.width - 8)))}px`;
    menuEl.style.top = `${Math.round(r.bottom + 4 + m.height > window.innerHeight - 8 ? Math.max(8, r.top - m.height - 4) : r.bottom + 4)}px`;
    document.addEventListener('pointerdown', onMenuOutside, true);
    paintBody();
  }
  function closeMenu() {
    if (!menuEl || menuEl.hidden) { menuFor = ''; return; }
    menuEl.hidden = true;
    menuFor = '';
    document.removeEventListener('pointerdown', onMenuOutside, true);
    if (panel && open) paintBody();
  }
  function onMenuOutside(event) {
    if (menuEl?.contains(event.target) || event.target.closest?.('[data-st-more]')) return;
    closeMenu();
  }
  async function onMenuClick(event) {
    const t = event.target, id = menuFor, row = saved.find(r => r.id === id);
    if (!row) { closeMenu(); return; }
    const cat = t.closest('[data-stm-cat]');
    if (cat) {
      closeMenu();
      if (cat.dataset.stmCat !== row.category) {
        await run(() => mutateSaved({ action: 'move', id, category: cat.dataset.stmCat }, `[${cat.dataset.stmCat || '미분류'}] 으로 옮겼습니다`));
      }
      return;
    }
    if (t.closest('[data-stm-addcat]')) {
      const name = menuEl.querySelector('[data-stm-newcat]')?.value.trim();
      if (!name) return;
      closeMenu();
      await run(async () => {
        if (!categories.includes(name)) await mutateSaved({ action: 'add_category', category: name });
        await mutateSaved({ action: 'move', id, category: name }, `[${name}] 으로 옮겼습니다`);
      });
      return;
    }
    if (t.closest('[data-stm="delete"]')) {
      closeMenu();
      const ok = typeof confirmDialog === 'function' ? await confirmDialog(`'${row.name}' 을 지웁니다.`) : true;
      if (ok) await run(() => mutateSaved({ action: 'delete', id }, '삭제했습니다'));
    }
  }
  async function mutateSaved(body, done) {
    const data = await request('/api/event-map/library', body);
    saved = data.items; categories = data.categories || []; savedCount = saved.length;
    if (done) toast(done, 'success');
  }
  // ── 추가 프롬프트 ─────────────────────────────────────────────────────────
  // run() 을 쓰지 않는다 - run 은 창을 inert 로 만들어, 칸을 옮겨 가며 치던 초점을 뺏는다.
  // 한 줄로 세워 보낸다 - 동시에 보내면 서버가 뒤집힌 순서로 처리해 마지막 편집을 잃을 수 있다(Codex 리뷰 2026-10-19).
  let saveQueue = Promise.resolve();
  // 글 칸 키 -> 큐에 넣고 아직 끝나지 않은 **마지막** 요청 {seq, text(trim)}. 지우기는 요청 번호로 - 글로 비교하면
  // B -> C -> B 에서 첫 B 의 응답이 마지막 B 의 표시를 지운다(Codex 3차).
  const queued = new Map();
  let saveSeq = 0;
  function saveExtra(body, key, sent) {
    const mark = typeof sent === 'string' && key ? { seq: ++saveSeq, text: sent.trim() } : null;
    if (mark) queued.set(key, mark);
    saveQueue = saveQueue.then(() => sendExtra(body, key, sent, mark)).finally(() => {
      if (mark && queued.get(key) === mark) queued.delete(key);
    });
    return saveQueue;
  }
  async function sendExtra(body, key, sent, mark = null) {
    try {
      const data = await request('/api/event-map/staging', body);
      // 그 사이 더 친 글 · 뒤에 줄 선 요청이 있으면 초안을 남긴다(옛 응답이 화면을 뒤 요청 전의 글로 돌리지 않게)
      if (key && drafts.get(key) === sent && (!mark || queued.get(key) === mark)) drafts.delete(key);
      applyStaging(data, true);
    } catch (error) {
      toast(`추가 프롬프트를 저장하지 못했습니다 — ${error.message}`, 'error');
      void reload({ keepCounts: true });   // 미리 바꿔 그린 켜짐을 서버 것으로 되돌린다(친 글은 drafts 에 남는다)
    }
    paint();
  }
  function onExtraChange(t) {
    const id = t.closest('[data-st-id]')?.dataset.stId, row = staged.find(r => r.id === id);
    if (t.matches('[data-st-extra-on]') && row) {
      const text = extraText(id, row.extra);
      row.extra = { ...(row.extra || {}), on: t.checked };   // 먼저 그린다 - 켜면 칸이 바로 열린다
      paintBody();
      if (t.checked) panel.body.querySelector(`[data-st-id="${CSS.escape(id)}"] [data-st-extra-text]`)?.focus();
      holdPending(id, { on: t.checked }, saveExtra({ action: 'extra', id, on: t.checked, text }, id, text));
      return true;
    }
    if (t.matches('[data-st-common-on]')) {
      common = { ...common, on: t.checked };
      paintBody();
      const body = { action: 'common', on: t.checked };
      if (drafts.has('common')) body.text = drafts.get('common');
      holdPending('common', { on: t.checked }, saveExtra(body, 'common', body.text));
      return true;
    }
    return false;
  }
  /** 글 칸을 떠날 때 - 서버 글과 다르면 저장한다. `change` 를 쓰지 않는다: 다시 그린 칸은 초안이 처음 값이라, 더 치지 않고
   *  떠나면 change 가 안 난다(Codex 리뷰 2026-10-19). 다시 그리며 떼어 낸 칸도 여기로 온다 - 같으면 아무것도 안 한다. */
  function commitText(t) {
    const isCommon = t.matches('[data-st-common-text]');
    const id = isCommon ? 'common' : t.closest('[data-st-id]')?.dataset.stId;
    const row = isCommon ? null : staged.find(r => r.id === id);
    if (!id || (!isCommon && !row)) return;
    // 비교 대상 = 큐에 넣고 아직 답을 못 받은 마지막 글, 없으면 서버 글 - 저장 중에 원래 글로 되돌린 편집도 보낸다(Codex 2차).
    const server = queued.has(id) ? queued.get(id).text : String((isCommon ? common : row.extra)?.text || '').trim();
    const text = t.value;
    // 같으면 보낼 것이 없다. 초안은 **서버** 글과 같을 때만 지운다 - 대기 중인 글과 같을 뿐이면 그 저장이 실패할 수 있다(Codex 4차).
    if (text.trim() === server) { if (!queued.has(id) && drafts.get(id) === text) drafts.delete(id); return; }
    void saveExtra(isCommon ? { action: 'common', text } : { action: 'extra', id, on: row.extra?.on === true, text }, id, text);
  }

  // ── 하단 [옵션] - 확장 기능 팝업(optionExtras.mjs)과 같은 옷(.ia-alt-popup.opt-extras-popup) ─────────────
  const MODES = [['merge', '프롬프트 합치기', '기본'], ['common_only', '공통 추가 프롬프트만 사용', ''],
    ['item_first', '개별 추가 프롬프트 우선 적용', '']];
  const MODE_FOOT = {
    merge: '개별 추가 프롬프트와 공통 추가 프롬프트를 <b>함께</b> 붙입니다. 같은 태그는 한 번만 붙습니다.',
    common_only: '개별 추가 프롬프트는 쓰지 않고 <b>공통</b> 추가 프롬프트만 붙입니다.',
    item_first: '개별 추가 프롬프트가 있는 조합은 <b>그것만</b>, 없는 조합은 공통 추가 프롬프트를 붙입니다.',
  };
  function paintOpt() {
    if (!optEl) return;
    optEl.innerHTML = '<div class="ia-alt-head">옵션</div><div class="ia-alt-list">'
      + '<div class="ia-alt-group">개별 스테이지에 추가 프롬프트가 있을 때</div>'
      + MODES.map(([key, label, hint]) => `<button type="button" class="ia-alt-row${common.mode === key ? ' is-on' : ''}" role="menuitemradio"
          aria-checked="${common.mode === key}" data-st-mode="${key}"><span class="ia-alt-box"></span><span class="ia-alt-label">${label}${hint
          ? ` <span class="st-opt-hint">(${hint})</span>` : ''}</span></button>`).join('')
      + `</div><div class="ia-alt-foot">${MODE_FOOT[common.mode] || MODE_FOOT.merge}${common.on ? ''
        : '<br>공통 추가 프롬프트가 꺼져 있으면 공통 쪽은 붙지 않습니다.'}</div>`;
  }
  function openOpt(btn) {
    if (!optEl) {
      optEl = document.createElement('div');
      optEl.className = 'ia-alt-popup opt-extras-popup st-opt-popup';
      optEl.setAttribute('role', 'dialog');
      optEl.setAttribute('aria-label', '스테이징 옵션');
      optEl.hidden = true;
      document.body.append(optEl);
      optEl.addEventListener('mousedown', event => event.preventDefault());   // 초점을 뺏지 않는다(확장 기능과 같다)
      optEl.addEventListener('click', event => {
        const row = event.target.closest('[data-st-mode]');
        if (!row || row.dataset.stMode === common.mode) return;
        common = { ...common, mode: row.dataset.stMode };   // 팝업은 열린 채로 - 고른 줄만 바뀐다
        paint();
        holdPending('common', { mode: row.dataset.stMode }, saveExtra({ action: 'common', mode: row.dataset.stMode }));
      });
    }
    optOpen = true;
    paintOpt();
    optEl.hidden = false;
    optEl.style.zIndex = String(Number(panel.el.style.zIndex || 0) + 2);
    // 단추 오른쪽 끝에 맞춰 **위로**(단추가 창 아래에 있다). 위가 모자라면 아래로.
    const r = btn.getBoundingClientRect(), m = optEl.getBoundingClientRect();
    optEl.style.left = `${Math.round(Math.max(8, Math.min(r.right - m.width, window.innerWidth - m.width - 8)))}px`;
    let top = r.top - m.height - 6;
    if (top < 8) top = Math.min(window.innerHeight - m.height - 8, r.bottom + 6);
    optEl.style.top = `${Math.round(Math.max(8, top))}px`;
    document.addEventListener('mousedown', onOptOutside, true);
    document.addEventListener('keydown', onOptKey, true);
    paintBody();
  }
  function closeOpt() {
    if (!optOpen) return;
    optOpen = false;
    if (optEl) optEl.hidden = true;
    document.removeEventListener('mousedown', onOptOutside, true);
    document.removeEventListener('keydown', onOptKey, true);
    if (panel && open) paintBody();
  }
  function onOptOutside(event) {
    if (optEl?.contains(event.target) || event.target.closest?.('[data-st-opt]')) return;   // 단추는 제 손이 처리한다
    closeOpt();
  }
  function onOptKey(event) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); closeOpt(); }
  }

  async function onChange(event) {
    const t = event.target;
    if (onExtraChange(t)) return;
    if (t.matches('[data-st-filter]')) { category = t.value; paintBody(); return; }
    if (t.matches('[data-st-link]')) {
      // ⚠️ 바라는 값을 먼저 잡는다 - run() 이 시작하며 다시 그리면 체크박스가 서버 상태(아직 옛것)로 돌아간다.
      const want = t.checked;
      await run(async () => {
        const state = await request('/api/event-map/random-link', want ? { enabled: true, mode: 'staging' } : { enabled: false });
        getEventMap()?.receiveRandomLink?.(state);
        toast(want ? '랜덤 버튼이 스테이징에서 뽑습니다 (ST Random)' : '스테이징 연결을 풀었습니다', 'success');
      });
    }
  }

  // ── 이벤트 맵에서 ───────────────────────────────────────────────────────────
  /** 이벤트 맵 [⋯] 의 '스테이징에 넣기' - 지금 조합을 얼려 넣는다. */
  async function stage(selection) {
    try {
      const data = await request('/api/event-map/staging', { action: 'add', selection, counts: open });
      applyStaging(data);
      toast(data.added ? `스테이징에 넣었습니다 — ${staged.length}개` : '이미 스테이징에 있는 조합입니다', data.added ? 'success' : 'info');
      paint();
    } catch (error) { toast(error.message, 'error'); }
  }

  if (tabBtn) {
    tabBtn.addEventListener('mousedown', event => event.preventDefault());
    tabBtn.addEventListener('click', () => { if (open) close(); else void show(); });
  }
  void refreshCounts();
  return {
    show, close, toggle: () => (open ? close() : void show()), isOpen: () => open,
    stage, refreshCounts, paint, isStaged, paintTab,
    /** 소켓이 다시 열렸다(서버 재실행 · 늦은 기동) - 열려 있으면 통째로, 아니면 수만 다시 받는다. */
    reconnected: () => (open ? reload() : refreshCounts()),
    stagedCount: () => (staged.length ? activeCount() : stagedCount), stagedTotal: () => stagedCount,
    /** 다른 창이 스테이징을 바꿨다(WS event_map_staging) - 수만 고치고, 열려 있으면 다시 받는다. */
    /** same_counts = 추가 프롬프트만 바뀌었다 - 수는 다시 세지 않는다. */
    receiveCount: message => {
      stagedCount = Number(message?.total ?? message?.count) || 0;
      if (open) void reload({ keepCounts: message?.same_counts === true }); else void refreshCounts();
    },
  };
}
