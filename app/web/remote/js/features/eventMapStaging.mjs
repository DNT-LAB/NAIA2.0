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
      if (fresh(s)) { staged = s.items; stagedCount = staged.length; }
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
    });
    panel.body.addEventListener('keydown', event => {
      event.stopPropagation();
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
    open = false;
    if (panel?.isOpen()) panel.close();
    paintTab();
  }
  async function reload() {
    const mine = ++reloadSeq;   // 늦게 온 옛 응답이 새 결과(빼기 등)를 덮지 않게
    try {
      const [s, l] = await Promise.all([request('/api/event-map/staging'), request('/api/event-map/library')]);
      if (mine !== reloadSeq) return;
      if (fresh(s)) { staged = s.items; counts = s.counts || null; }
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
      // 줄은 태그 · 칩만. 누르면 펼쳐져 단추가 아래 줄에 나온다(마우스를 대면 펼치면 줄이 밀려 다른 줄을 집는다).
      // 맨 앞 스위치 = 켜기 · 끄기(사용자 지시 2026-10-15). 꺼진 줄은 흐리게 - 랜덤 후보 · 전체 수에서 빠진다.
      body.innerHTML = staged.length ? staged.map(r => `<div class="st-row st-pick${openRow === r.id ? ' is-open' : ''}${r.enabled === false ? ' is-off' : ''}" data-st-id="${esc(r.id)}" data-st-pick
          aria-expanded="${openRow === r.id}" title="${openRow === r.id ? '' : '눌러서 랜덤 · 랜덤+생성 · 맵에서 열기 · 제외'}">
          <button type="button" class="st-sw" data-st-toggle role="switch" aria-checked="${r.enabled !== false}"
            title="${r.enabled === false ? '꺼짐 - 눌러서 랜덤 후보에 넣기' : '켜짐 - 눌러서 랜덤 후보에서 빼기'}"></button>
          <div class="st-bd"><div class="st-head"><span class="st-name">${esc(r.selection.pins.join(', '))}</span>${counts?.per?.[r.id] != null
            ? `<span class="st-count" title="이 조합에 맞는 게시물(프롬프트) 수">${Number(counts.per[r.id]).toLocaleString('en-US')}</span>` : ''}</div>
          <div class="st-meta">${metaHtml(r.selection)}</div>
          </div>
          ${openRow === r.id ? `<div class="st-acts st-acts-open"><button type="button" data-st-random>랜덤</button><button type="button" class="is-primary" data-st-random-gen>랜덤+생성</button><button type="button" data-st-open>맵에서 열기</button><button type="button" class="is-danger" data-st-remove>제외</button></div>` : ''}
        </div>`).join('')
        : '<div class="st-empty">스테이징된 조합이 없습니다. 이벤트 맵 [⋯] 의 <b>스테이징에 넣기</b>, 또는 저장된 조합의 <b>스테이징 +</b>.</div>';
      foot.innerHTML = `<button type="button" data-st-bundle ${staged.length ? '' : 'disabled'} title="지금 스테이징을 저장된 조합의 '묶음' 하나로">통째로 저장</button>
        <button type="button" data-st-clear ${staged.length ? '' : 'disabled'}>비우기</button>`;
      return;
    }
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
            ? `<span class="st-chip st-bundle" title="조합 ${sel.length}개를 묶은 것 - 스테이징하면 전부 들어갑니다">묶음 ${sel.length}</span>` : ''}${renaming === r.id
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
  async function run(task) {
    busy++; paint();
    try { await task(); } catch (error) { toast(error.message, 'error'); } finally { busy--; paint(); }
  }
  function applyStaging(data) {
    if (!fresh(data)) return;   // 더 새 목록을 이미 받았다
    ++reloadSeq;                // 이 결과가 더 새것이다 - 진행 중인 reload 응답은 버린다
    staged = data.items; stagedCount = staged.length;
    if ('counts' in data) counts = data.counts;
    else {
      // 수 없이 바뀌었다(창이 닫혀 있을 때 보낸 [스테이징]) - 옛 수는 지금 목록과 안 맞는다(재리뷰 2026-10-15).
      counts = null;
      if (open) void reload();
    }
    getEventMap()?.syncStaged?.();   // 이벤트 맵 [스테이징] 단추의 켜짐(이미 들어간 조합이면 끈다)
    if (data.random_link) getEventMap()?.receiveRandomLink?.(data.random_link);
  }
  async function randomFrom(sel, andGenerate) {
    const params = new URLSearchParams({ pins: sel.pins.join(','), exclude: sel.exclude.join(','),
      ratings: sel.ratings.join(','), persons: sel.persons.join(','), n: '1', seed: String(Date.now() % 1000003) });
    const body = await request(`/api/event-map/sample?${params}`);
    const s = (body.samples || [])[0];
    if (!s?.tags?.length) throw new Error('이 조합에 맞는 게시물이 없습니다');
    const applied = await request('/api/event-map/apply', { tags: s.tags, rating: String(s.partition || 's').slice(0, 1) });
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
    if (tb) { tab = tb.dataset.stTab; renaming = ''; openRow = ''; closeMenu(); paint(); return; }
    const id = t.closest('[data-st-id]')?.dataset.stId;
    const stagedRow = staged.find(r => r.id === id), savedRow = saved.find(r => r.id === id);
    if (t.closest('[data-st-random]') && stagedRow) { await run(() => randomFrom(stagedRow.selection, false)); return; }
    if (t.closest('[data-st-random-gen]') && stagedRow) { await run(() => randomFrom(stagedRow.selection, true)); return; }
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
      });
      return;
    }
    if (t.closest('[data-st-stage-saved]') && savedRow) {
      await run(async () => {
        const data = await request('/api/event-map/staging', { action: 'stage_saved', id });
        const n = data.added || 0;
        applyStaging(data);
        toast(n ? `스테이징에 ${n}개 넣었습니다` : '이미 스테이징에 있는 조합입니다', n ? 'success' : 'info');
      });
      return;
    }
    if (t.closest('[data-st-open-saved]') && savedRow) { await run(() => openInMap(savedRow.selection)); return; }
    // 저장된 조합의 [랜덤] · [랜덤+생성](사용자 지시 2026-10-17). 묶음은 켜진 조합 중 하나(전부 꺼졌으면 아무거나).
    const savedRandom = t.closest('[data-st-random-saved], [data-st-random-gen-saved]');
    if (savedRandom && savedRow) {
      const sel = savedRow.selections || [savedRow.selection];
      const flags = Array.isArray(savedRow.enabled) && savedRow.enabled.length === sel.length ? savedRow.enabled : null;
      const pool = flags && flags.some(Boolean) ? sel.filter((_, i) => flags[i]) : sel;
      const pick = pool[Math.floor(Math.random() * pool.length)];
      await run(() => randomFrom(pick, savedRandom.hasAttribute('data-st-random-gen-saved')));
      return;
    }
    // 스테이징 줄 펼치기 · 접기(단추를 누른 것이 아닐 때)
    const pick = t.closest('[data-st-pick]');
    if (pick && !t.closest('button, input')) {
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
  async function onChange(event) {
    const t = event.target;
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
    receiveCount: message => { stagedCount = Number(message?.total ?? message?.count) || 0; if (open) void reload(); else void refreshCounts(); },
  };
}
