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
 *  · 프리셋(사용자 지시 2026-10-31): 맨 위 칩 줄. 칩을 누르면 스테이징이 그 세트로 **통째로 바뀐다**. 프리셋은 **명시적으로 저장할
 *    때만** 바뀐다(사용자 결정) - 저장한 뒤 고쳤으면 칩에 ● 와 [저장]. 고친 채 다른 칩을 누르면 저장할지 묻는다. 공통 추가 프롬프트는
 *    설정이라 프리셋에 안 든다([비우기] 와 같은 원칙). 지금 칩을 다시 누르거나 우클릭 = 이름 · 덮어쓰기 · 삭제.
 *  · 조합 안 찾기(사용자 지시 2026-10-31): 스테이징 탭 위 칸. Quick Filter 칩 문법(hair 부분 · *tag 정확 · -tag 빼기 · 쉼표 = 그리고)으로
 *    조합마다 실제 게시물을 센다(읽기만). 펼친 줄의 [분할] = 맞는 것 / 나머지 두 줄, [만 남기기] = 맞는 것만. 조건은 조합의
 *    `filters` 로 얹혀 함께 저장되고(칩 '찾기 …' · '빼기 …') ST Random · 줄 [랜덤] 도 따른다. 맵에서 열기는 핀 · 제외만 옮긴다.
 *
 * 서버가 다 한다(/api/event-map/staging · library · sample · apply). 여기서는 그리기와 단추뿐이다.
 */
import { createDraggablePanel } from './draggablePanel.mjs?v=20260926-childalign';

export function initEventMapStaging({ showToast, getPromptText, generateNow, confirmDialog, promptDialog,
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
  // 프리셋(사용자 지시 2026-10-31): presetList = [{id, name, count}] · presetState = {active, dirty}(스테이징 응답마다 서버가 싣는다).
  let presetList = [], presetState = null, pmenuEl = null, pmenuFor = '';
  // 조합 안 찾기: 칸 글 · 서버가 센 것({terms, per: {id: n}, total, sum}) · 늦은 응답 버리기.
  let findText = '', findResult = null, findError = '', findSeq = 0, findTimer = 0;
  // 공용 찾기 칸은 꺼 둔다(사용자 지시 2026-10-31: 만들어 둔 것은 두고 비활성화만) - 칸이 안 보이고 찾기 요청도 안 나간다.
  const FIND_ENABLED = false;
  // 줄 검색(사용자 결정 2026-10-31): 펼친 줄의 [찾기] 로 여는 포함 · 제외 칩 칸 - 한 번에 한 줄.
  // rf = {id, inc, exc, m, seq, err} · rfOpen = 칸이 열린 줄 · rfText = 치던 글(다시 그려도 남게).
  // temp = [분할] · [제거] 의 임시 상태 {id, terms, m, n, a: 찾기 남김, b: 나머지 남김, fp} - 화면에만 있고 서버에 쓰지 않는다.
  let rf = null, rfOpen = '', rfText = { inc: '', exc: '' }, temp = null;
  let acEl = null, acItems = [], acActive = -1, acFor = '', acTimer = 0, acSeq = 0;
  const rfFor = id => (rf && rf.id === id ? rf : null);
  const rfTerms = () => (rf ? [...rf.inc, ...rf.exc.map(t => `-${t}`)] : []);
  const fmtN = n => Number(n).toLocaleString('en-US');
  const fmtK = n => (n >= 10000 ? `${Math.round(n / 1000)}k` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n ?? ''));

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
  const filtersKey = s => (s.filters || []).map(g => (g.invert ? '!' : '') + [...new Set((g.terms || []).map(norm))].sort().join(',')).sort();
  const fingerprint = s => JSON.stringify([[...new Set(s.pins.map(norm))].sort(), [...new Set(s.exclude.map(norm))].sort(),
    [...s.ratings].sort(), [...s.persons].sort(), ...(s.filters?.length ? [filtersKey(s)] : [])]);
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
    // 분할로 얹힌 조건(사용자 지시 2026-10-31): 찾기 = 맞는 게시물만 · 빼기 = 맞는 게시물을 뺀 나머지.
    const fs = (s.filters || []).map(g => g.invert
      ? `<span class="st-chip st-f-out" title="이 조건에 맞는 게시물을 뺀 나머지(분할의 나머지 쪽)">빼기 ${esc((g.terms || []).join(', '))}</span>`
      : `<span class="st-chip st-f-in" title="이 조건에 맞는 게시물만(분할 · 만 남기기)">찾기 ${esc((g.terms || []).join(', '))}</span>`).join('');
    return `<span class="st-chips">${ps}${rs}${fs}</span>${s.exclude.length ? `<span class="st-ex">제외 ${esc(s.exclude.join(', '))}</span>` : ''}`;
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

  // 프리셋 줄 · 찾기 칸 · 분할 칩의 모양(사용자 지시 2026-10-31). style.css 는 줄바꿈이 섞여 있어 모듈이 한 번 넣는다.
  function injectStyle() {
    if (document.getElementById('stagingV2Style')) return;
    const style = document.createElement('style');
    style.id = 'stagingV2Style';
    style.textContent = `
.st-presets { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; flex: 0 0 auto; padding: 5px 10px 6px; border-bottom: 1px solid var(--border-dim); }
.st-presets[hidden], .st-find[hidden], .st-find-hint[hidden] { display: none; }
.st-presets .st-plabel { margin-right: 2px; font-size: 9.5px; color: var(--text-dim); }
.st-window button.st-pchip { border-radius: 10px; padding: 1px 9px; }
.st-window button.st-pchip.is-on { color: #fff; border-color: rgba(139,118,255,0.8); background: rgba(88,76,170,0.35); }
.st-pchip .st-pn { margin-left: 4px; color: var(--text-dim); font-size: 9.5px; }
.st-pchip .st-pdirty { margin-left: 3px; color: #e6a84a; }
.st-window button.st-padd { border-style: dashed; border-radius: 10px; color: var(--text-dim); }
.st-window button.st-psave { color: #e6a84a; border-color: rgba(230,168,74,0.55); }
.st-find { display: flex; gap: 5px; flex: 0 0 auto; padding: 6px 10px 2px; }
.st-find input { flex: 1; min-width: 0; height: 24px; box-sizing: border-box; padding: 2px 8px; border: 1px solid var(--border-dim); border-radius: 5px;
  background: rgba(0,0,0,0.26); color: var(--text-primary); font-family: var(--font-mono); font-size: 10.5px; cursor: text; }
.st-find input:focus { outline: none; border-color: var(--accent); }
.st-find-hint { flex: 0 0 auto; padding: 2px 10px 6px; border-bottom: 1px solid var(--border-dim); font-size: 9.5px; color: var(--text-dim); }
.st-count .st-hit, .st-total b.st-find-b { color: #7fd3ff; }
.st-pick.is-miss .st-bd { opacity: 0.42; }
.st-chip.st-f-in { color: #9fd8ff; border-color: rgba(100,180,240,0.5); background: rgba(40,110,170,0.18); }
.st-chip.st-f-out { color: #f2a9b8; border-color: rgba(240,130,150,0.5); background: rgba(170,50,80,0.16); }
.st-window button.st-split { color: #cfeeff; border-color: rgba(100,180,240,0.6); background: rgba(40,110,170,0.2); }
.st-window button.st-rf-btn.is-on { color: #cfeeff; border-color: rgba(100,180,240,0.6); background: rgba(40,110,170,0.2); }
.st-rf, .st-tmp { flex: 1 0 100%; margin-top: 7px; padding-top: 7px; border-top: 1px dashed rgba(139,118,255,0.32); cursor: default; }
.st-rf-bar { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.st-rf-lb { flex: 0 0 26px; font-size: 9.5px; color: var(--text-dim); }
.st-rf-inp { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 3px; min-height: 24px; box-sizing: border-box;
  padding: 2px 5px; border: 1px solid var(--border-dim); border-radius: 5px; background: rgba(0,0,0,0.26); cursor: text; }
.st-rf-inp:focus-within { border-color: var(--accent); }
.st-rf-inp input { flex: 1 0 60px; min-width: 60px; height: 18px; padding: 0 2px; border: 0; outline: none; background: transparent;
  color: var(--text-primary); font-family: var(--font-mono); font-size: 10.5px; }
.st-rf-chip { display: inline-flex; align-items: center; gap: 2px; padding: 0 2px 0 7px; border-radius: 9px; font-family: var(--font-mono); font-size: 10px;
  color: #9fd8ff; background: rgba(40,110,170,0.22); border: 1px solid rgba(100,180,240,0.45); }
.st-rf-chip.is-ex { color: #f2a9b8; background: rgba(170,50,80,0.18); border-color: rgba(240,130,150,0.45); }
.st-window .st-rf-chip button { height: auto; min-height: 0; padding: 0 4px; border: 0; background: transparent; color: inherit; font-size: 11px; line-height: 1; }
.st-rf-sum, .st-tmp-bar { display: flex; align-items: center; gap: 5px; margin-top: 5px; font-size: 10.5px; }
.st-rf-sum > span, .st-tmp-bar > span { flex: 1; min-width: 0; color: var(--text-dim); }
.st-rf-sum b { color: #7fd3ff; font-family: var(--font-mono); font-weight: 600; }
.st-rf-sum i { margin-left: 6px; font-style: normal; }
.st-tmp-row { display: flex; align-items: center; gap: 7px; padding: 3px 0 3px 4px; font-size: 11px; }
.st-tmp-row.is-off .st-tmp-name, .st-tmp-row.is-off .st-tmp-n { opacity: 0.4; text-decoration: line-through; }
.st-window button.st-tmp-dot { flex: 0 0 auto; width: 12px; height: 12px; min-height: 0; padding: 0; border-radius: 50%;
  border: 1px solid rgba(139,118,255,0.85); background: rgba(139,118,255,0.85); }
.st-window button.st-tmp-dot[aria-pressed="false"] { background: transparent; }
.st-tmp-tag { flex: 0 0 auto; font-size: 9px; font-weight: 700; padding: 0 5px; border-radius: 3px; color: #1a1a1a; background: #f5dc8a; }
.st-tmp-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-family: var(--font-mono); color: #f5dc8a; }
.st-tmp-n { flex: 0 0 auto; font-family: var(--font-mono); font-size: 10px; color: var(--text-secondary); }
.st-tmp-bar { padding-top: 6px; border-top: 1px dashed rgba(245,220,138,0.4); }
.st-tmp-bar > span { color: #f5dc8a; }
.st-temp-mode .st-link, .st-temp-mode .st-presets, .st-temp-mode .st-tabs, .st-temp-mode .st-foot,
.st-temp-mode .st-pick:not(.is-temp-row) { opacity: 0.38; pointer-events: none; }
.st-temp-mode .st-pick.is-temp-row > .st-sw { opacity: 0.4; pointer-events: none; }`;
    document.head.append(style);
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
      storageKey: 'staging', width: 400, height: 540, minWidth: 340, minHeight: 240, maxWidth: 900,
      initial: { x: 430, y: 64 }, resizable: true, onClose: close,
    });
    injectStyle();
    panel.body.innerHTML = `
      <label class="st-link"><input type="checkbox" data-st-link>스테이징 이벤트를 랜덤 버튼에 연결 적용합니다</label>
      <div class="st-presets" hidden></div>
      <div class="st-total" role="status"></div>
      <div class="st-tabs" role="tablist"><button type="button" data-st-tab="stage" role="tab"></button><button type="button" data-st-tab="saved" role="tab"></button></div>
      <div class="st-find" hidden><input data-st-find placeholder="조합 안에서 찾기 - hair, *1girl, -red" spellcheck="false" aria-label="조합 안에서 찾기"><button type="button" data-st-find-clear>지우기</button></div>
      <div class="st-find-hint" hidden></div>
      <div class="st-body"></div>
      <div class="st-foot"></div>`;
    panel.body.addEventListener('click', onClick);
    panel.body.addEventListener('contextmenu', event => {
      const chip = event.target.closest('[data-st-preset]');
      if (!chip || temp) return;
      event.preventDefault();
      openPresetMenu(chip.dataset.stPreset, chip);
    });
    panel.body.addEventListener('change', onChange);
    panel.body.addEventListener('input', event => {
      // 칸은 두고 목록만 - 칸까지 갈아 끼우면 첫 글자에서 초점이 나가 연속 입력 · 한글 조합이 끊긴다(리뷰 2026-10-14).
      if (event.target.matches('[data-st-search]')) { query = event.target.value; paintSavedList(); }
      // 조합 안 찾기 - 칸은 다시 그리지 않는다(창 머리에 고정). 치는 동안은 묶어서 한 번만 묻는다.
      if (event.target.matches('[data-st-find]')) { findText = event.target.value; scheduleFind(); }
      // 줄 검색 칸 - 쉼표까지 친 것은 칩으로, 남은 조각은 자동완성
      if (event.target.matches('[data-st-rf-in]')) {
        const kind = event.target.dataset.stRfIn, value = event.target.value;
        if (value.includes(',')) { const cut = value.lastIndexOf(','); addRfTags(kind, value.slice(0, cut), value.slice(cut + 1)); return; }
        rfText[kind] = value;
        scheduleAc(event.target);
      }
      // 추가 프롬프트는 치는 동안 저장하지 않는다(칸을 떠날 때 change) - 그 사이 다시 그려도 글이 남게 둔다.
      if (event.target.matches('[data-st-extra-text]')) drafts.set(event.target.closest('[data-st-id]')?.dataset.stId, event.target.value);
      if (event.target.matches('[data-st-common-text]')) drafts.set('common', event.target.value);
    });
    // 자동완성 목록은 캐럿 자리에 fixed 로 뜬다 - 목록 칸(.st-body)을 굴리면 칸을 따라 다시 놓고, 칸이 화면 밖으로 나가면
    // 칸을 떠나 목록을 닫는다(떠나면 저장된다). 하단 공통 칸은 굴러가지 않는다.
    const scroller = panel.body.querySelector('.st-body');
    scroller.addEventListener('scroll', () => {
      const field = document.activeElement;
      if (!field?.matches?.('.st-extra-text') || !scroller.contains(field)) return;
      if (typeof globalThis.isTagAutocompleteOpen === 'function' && !globalThis.isTagAutocompleteOpen()) return;
      const box = scroller.getBoundingClientRect(), r = field.getBoundingClientRect();
      if (r.bottom <= box.top || r.top >= box.bottom) field.blur();
      else globalThis.positionTagTooltip?.();
    }, { passive: true });
    panel.body.addEventListener('focusout', event => {
      if (event.target.matches?.('[data-st-extra-text], [data-st-common-text]')) commitText(event.target);
    });
    panel.body.addEventListener('keydown', event => {
      event.stopPropagation();
      // Ctrl+Enter = 칸을 떠나며 저장(Enter 는 줄바꿈 그대로)
      if (event.target.matches('.st-extra-text') && event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault(); event.target.blur(); return;
      }
      if (event.target.matches('[data-st-rf-in]')) { onRfKey(event); return; }
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
    closePresetMenu();
    closeAc();
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
      const [s, l, p] = await Promise.all([request(`/api/event-map/staging${reuse ? '?counts=0' : ''}`), request('/api/event-map/library'),
        request('/api/event-map/staging/presets').catch(() => null)]);
      if (mine !== reloadSeq) return;
      if (fresh(s)) { staged = s.items; if (!reuse) { counts = s.counts || null; needCounts = false; } takeCommon(s); takePresets(s); syncRowFind(); if (findText.trim() && !reuse) scheduleFind(0); }
      if (p) takePresetList(p);
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
    paintPresets();
    const total = panel.body.querySelector('.st-total');
    total.hidden = !staged.length;
    const fmt = n => Number(n).toLocaleString('en-US');
    total.innerHTML = findResult && counts
      ? `찾기 맞음 <b class="st-find-b">${fmt(findResult.total)}</b>건 <span>/ 총 ${fmt(counts.total)}건</span>`
      : counts ? `총 프롬프트 <b>${fmt(counts.total)}</b>건${counts.sum !== counts.total
      ? ` <span title="여러 조합에 함께 걸리는 게시물은 한 번만 셉니다">· 중복 ${fmt(counts.sum - counts.total)}건 제외</span>` : ''}`
      : '<span>이벤트 맵 색인이 열리면 프롬프트 수를 셉니다</span>';
    paintFind();
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
    panel.body.classList.toggle('st-temp-mode', !!temp && tab === 'stage');   // 임시 분할 중 = 다른 줄 · 프리셋 · 탭 · 발줄 잠금
    if (tab === 'stage') { paintStage(body, foot); return; }
    paintSavedTab(body, foot);
  }
  /** 추가 프롬프트 칸에 태그 자동완성(사용자 지시 2026-10-19). 다시 그리면 칸이 새것이라 새 칸에만 붙인다. */
  function bindExtraAutocomplete(root) {
    if (typeof globalThis.bindTagAssist !== 'function') return;
    root.querySelectorAll('.st-extra-text').forEach(el => {
      if (el._stAc) return;
      el._stAc = true;
      globalThis.bindTagAssist(el);
    });
  }
  function paintStage(body, foot) {
    // 줄은 태그 · 칩만. 누르면 펼쳐져 단추가 아래 줄에 나온다(마우스를 대면 펼치면 줄이 밀려 다른 줄을 집는다).
    // 맨 앞 스위치 = 켜기 · 끄기(사용자 지시 2026-10-15). 꺼진 줄은 흐리게 - 랜덤 후보 · 전체 수에서 빠진다.
    // 펼친 줄 맨 아래 = [추가 프롬프트] 체크(켜면 칸이 열린다 - 사용자 지시 2026-10-19).
    // 줄 검색 칸은 다시 그리면 새 칸이다 - 치던 칸이면 다 그린 뒤 초점 · 글을 돌려준다.
    const rfFocusKind = document.activeElement?.matches?.('[data-st-rf-in]') ? document.activeElement.dataset.stRfIn : '';
    // 줄 검색의 맞는 수는 칸이 열린 줄(또는 임시 분할 중인 줄)에만 - 접은 줄에 남은 수는 헷갈린다.
    const hit = r => findResult?.per?.[r.id] ?? ((rfOpen === r.id || temp?.id === r.id) ? (rfFor(r.id)?.m ?? undefined) : undefined);
    const countHtml = r => {
      const n = counts?.per?.[r.id], m = hit(r);
      if (n == null && m == null) return '';
      return `<span class="st-count" title="${m != null ? '찾기에 맞는 게시물 / ' : ''}이 조합에 맞는 게시물(프롬프트) 수">${m != null
        ? `<span class="st-hit">${Number(m).toLocaleString('en-US')}</span>${n != null ? ' / ' : ''}` : ''}${n != null ? Number(n).toLocaleString('en-US') : ''}</span>`;
    };
    const rfBtn = r => {
      const s = rfFor(r.id), lit = rfOpen === r.id || (s && s.inc.length + s.exc.length > 0);
      return `<button type="button" class="st-rf-btn${lit ? ' is-on' : ''}" data-st-rf aria-expanded="${rfOpen === r.id}"
        title="이 조합 안에서 태그로 찾아 [제거] · [분할] 합니다">찾기 ${rfOpen === r.id ? '▴' : '▾'}</button>`;
    };
    const rowsHtml = staged.length ? staged.map(r => `<div class="st-row st-pick${openRow === r.id ? ' is-open' : ''}${r.enabled === false ? ' is-off' : ''}${hit(r) === 0 ? ' is-miss' : ''}${temp?.id === r.id ? ' is-temp-row' : ''}" data-st-id="${esc(r.id)}" data-st-pick
        aria-expanded="${openRow === r.id}" title="${openRow === r.id ? '' : '눌러서 랜덤 · 랜덤+생성 · 맵에서 열기 · 제외 · 추가 프롬프트'}">
        <button type="button" class="st-sw" data-st-toggle role="switch" aria-checked="${r.enabled !== false}"
          title="${r.enabled === false ? '꺼짐 - 눌러서 랜덤 후보에 넣기' : '켜짐 - 눌러서 랜덤 후보에서 빼기'}"></button>
        <div class="st-bd"><div class="st-head"><span class="st-name">${esc(r.selection.pins.join(', '))}</span>${countHtml(r)}</div>
        <div class="st-meta">${metaHtml(r.selection)}${extraChip(r.extra)}</div>
        </div>
        ${openRow !== r.id ? '' : temp?.id === r.id ? tempHtml() : `<div class="st-acts st-acts-open"><button type="button" data-st-random>랜덤</button><button type="button" class="is-primary" data-st-random-gen>랜덤+생성</button><button type="button" data-st-open>맵에서 열기</button>${rfBtn(r)}<button type="button" class="is-danger" data-st-remove>제외</button></div>${rfOpen === r.id ? rfHtml(r) : ''}${extraHtml(r)}`}
      </div>`).join('')
      : '<div class="st-empty">스테이징된 조합이 없습니다. 이벤트 맵 [⋯] 의 <b>스테이징에 넣기</b>, 또는 저장된 조합의 <b>스테이징 +</b>.</div>';
    // 하단 = 공통 추가 프롬프트(켜기 · 끄기 - 꺼도 글은 남는다) + [통째로 저장] [비우기] ...... [옵션]
    const commonHtml = `<div class="st-common${common.on ? '' : ' is-off'}">
        <label class="st-extra-on"><input type="checkbox" data-st-common-on ${common.on ? 'checked' : ''}>추가 프롬프트 <span>· 공통 - 뽑힌 조합 뒤에 붙습니다</span></label>
        <textarea class="st-extra-text" data-st-common-text rows="2" maxlength="2000" spellcheck="false" aria-label="공통 추가 프롬프트"
          placeholder="모든 조합 뒤에 붙일 태그 - 예: masterpiece, detailed background">${esc(extraText('common', common))}</textarea>
      </div>`;
    const buttonsHtml = `<button type="button" data-st-bundle ${staged.length ? '' : 'disabled'} title="지금 스테이징을 저장된 조합의 '묶음' 하나로(추가 프롬프트 포함)">통째로 저장</button>
      <button type="button" data-st-clear ${staged.length ? '' : 'disabled'} title="조합만 비웁니다 - 공통 추가 프롬프트는 남습니다">비우기</button>
      <span class="st-foot-gap"></span>
      <button type="button" class="st-opt-btn${common.mode !== 'merge' ? ' has-on' : ''}" data-st-opt aria-haspopup="true"
        aria-expanded="${optOpen}" title="개별 추가 프롬프트가 있을 때 무엇을 붙일지">옵션</button>`;

    // 치던 칸은 **노드째** 살린다(저장 응답 · 다른 창의 알림으로 다시 그려도). 갈아 끼우면 초점 · 캐럿 · 칸 스크롤이 날아가고,
    // 열려 있던 자동완성 목록이 떼어 낸 칸을 가리켜 고른 후보가 사라진다(사용자 지시 2026-10-19 - 자동완성 · 스크롤 주의).
    const act = document.activeElement;
    const keep = act?.matches?.('.st-extra-text') && panel.body.contains(act) ? act : null;
    const keepRowId = keep?.matches('[data-st-extra-text]') ? keep.closest('[data-st-id]')?.dataset.stId : null;
    const keepRow = keepRowId ? keep.closest('[data-st-id]') : null;
    const rowStays = keepRowId && openRow === keepRowId && staged.some(r => r.id === keepRowId && r.extra?.on === true);
    if (keepRow && rowStays && body.contains(keepRow)) {
      const tpl = document.createElement('template');
      tpl.innerHTML = rowsHtml;
      const fresh = [...tpl.content.children];
      const freshRow = fresh.find(el => el.dataset.stId === keepRowId);
      const liveExtra = keep.closest('.st-extra');
      // 그 줄: 겉(클래스 · 제목)과 칸 밖 자식은 새것으로, 추가 프롬프트 칸(.st-extra)만 산 채로
      keepRow.className = freshRow.className;
      keepRow.title = freshRow.title;
      keepRow.setAttribute('aria-expanded', freshRow.getAttribute('aria-expanded'));
      [...keepRow.children].forEach(child => { if (child !== liveExtra) child.remove(); });
      [...freshRow.children].forEach(child => { if (!child.classList.contains('st-extra')) liveExtra.before(child); });
      // 나머지 줄: 산 줄 앞뒤로 새것
      [...body.children].forEach(child => { if (child !== keepRow) child.remove(); });
      const at = fresh.indexOf(freshRow);
      keepRow.before(...fresh.slice(0, at));
      keepRow.after(...fresh.slice(at + 1));
    } else {
      body.innerHTML = rowsHtml;
    }
    const liveCommon = keep?.matches('[data-st-common-text]') ? keep.closest('.st-common') : null;
    if (liveCommon && foot.contains(liveCommon)) {
      liveCommon.classList.toggle('is-off', !common.on);
      const box = liveCommon.querySelector('[data-st-common-on]');
      if (box) box.checked = common.on;
      [...foot.children].forEach(child => { if (child !== liveCommon) child.remove(); });
      liveCommon.insertAdjacentHTML('afterend', buttonsHtml);
    } else {
      foot.innerHTML = commonHtml + buttonsHtml;
    }
    bindExtraAutocomplete(body);
    bindExtraAutocomplete(foot);
    body.querySelectorAll('[data-st-rf-in]').forEach(el => { el.value = rfText[el.dataset.stRfIn] || ''; });
    if (rfFocusKind) {
      const field = body.querySelector(`[data-st-rf-in="${rfFocusKind}"]`);
      if (field) { field.focus({ preventScroll: true }); field.setSelectionRange(field.value.length, field.value.length); }
    }
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
    takePresets(data);
    syncRowFind();
    if (findText.trim() && !keepCounts) scheduleFind(0);   // 줄이 바뀌었다(분할 · 빼기 · 프리셋) - 찾기 수도 다시
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
    if (sel.filters?.length) params.set('filters', JSON.stringify(sel.filters));   // 분할 조건 - ST Random 과 같은 게시물에서
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
    if (sel.filters?.length) toast('찾기 조건(분할)은 맵에 옮겨지지 않습니다 - 핀 · 제외만 열었습니다', 'info');
  }

  async function onClick(event) {
    const t = event.target;
    if (temp && !t.closest('.st-tmp')) return;   // 임시 분할 중에는 커밋 · 버림 · 남길 쪽 고르기만
    const tb = t.closest('[data-st-tab]');
    if (tb) { tab = tb.dataset.stTab; renaming = ''; openRow = ''; closeMenu(); closeOpt(); paint(); return; }
    if (t.closest('[data-st-opt]')) { if (optOpen) closeOpt(); else openOpt(t.closest('[data-st-opt]')); return; }
    const chip = t.closest('[data-st-preset]');
    if (chip) {
      const pid = chip.dataset.stPreset;
      if (pid === presetState?.active) openPresetMenu(pid, chip);   // 지금 칩 = 관리 메뉴
      else await run(() => switchPreset(pid), { readsExtras: true });
      return;
    }
    if (t.closest('[data-st-psave]')) { await run(() => savePreset(presetState?.active), { readsExtras: true }); return; }
    if (t.closest('[data-st-padd]')) { await run(() => savePresetAsNew(), { readsExtras: true }); return; }
    if (t.closest('[data-st-find-clear]')) {
      const field = panel.body.querySelector('[data-st-find]');
      if (field) field.value = '';
      findText = ''; scheduleFind(0);
      return;
    }
    const id = t.closest('[data-st-id]')?.dataset.stId;
    const stagedRow = staged.find(r => r.id === id), savedRow = saved.find(r => r.id === id);
    if (t.closest('[data-st-random]') && stagedRow) { await run(() => randomFrom(stagedRow.selection, false, { stagingId: id }), { readsExtras: true }); return; }
    if (t.closest('[data-st-random-gen]') && stagedRow) { await run(() => randomFrom(stagedRow.selection, true, { stagingId: id }), { readsExtras: true }); return; }
    if (t.closest('[data-st-open]') && stagedRow) { await run(() => openInMap(stagedRow.selection)); return; }
    // ── 줄 검색(사용자 결정 2026-10-31) ──
    if (t.closest('[data-st-rf]') && stagedRow) {
      if (rfOpen === id) { rfOpen = ''; closeAc(); }
      else {
        rfOpen = id;
        if (rf?.id !== id) { rf = { id, inc: [], exc: [], m: null, seq: 0, err: '' }; rfText = { inc: '', exc: '' }; }
      }
      paintBody();
      if (rfOpen) panel.body.querySelector('[data-st-rf-in="inc"]')?.focus({ preventScroll: true });
      return;
    }
    const rx = t.closest('[data-st-rf-x]');
    if (rx && rf?.id === id) { const [kind, i] = rx.dataset.stRfX.split(':'); rf[kind].splice(Number(i), 1); rfChanged(); return; }
    if (t.closest('.st-rf-inp') && !t.closest('button')) { t.closest('.st-rf-inp').querySelector('input')?.focus(); return; }
    const rfAct = t.closest('[data-st-rf-split], [data-st-rf-remove]');
    if (rfAct && stagedRow && rf?.id === id && rf.m != null) {
      const split = rfAct.hasAttribute('data-st-rf-split');
      // [분할] = 찾기 쪽만 켠 채 · [제거] = 나머지 쪽만 켠 채 - 같은 임시 화면(사용자 결정 2026-10-31)
      temp = { id, terms: rfTerms(), m: rf.m, n: counts?.per?.[id], a: split, b: !split, fp: fingerprint(stagedRow.selection) };
      closeAc(); paint();
      return;
    }
    const dot = t.closest('[data-st-tmp]');
    if (dot && temp) { temp[dot.dataset.stTmp] = !temp[dot.dataset.stTmp]; paintBody(); return; }
    if (t.closest('[data-st-tmp-drop]') && temp) { temp = null; paint(); return; }
    if (t.closest('[data-st-tmp-commit]') && temp) { await commitTemp(); return; }
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
    if (pick && !t.closest('button, input, .st-extra, .st-rf, .st-tmp')) {
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
  // ── 줄 검색 · 임시 분할(사용자 결정 2026-10-31) ─────────────────────────────
  // Quick Filter 처럼 포함 · 제외 칩. 칩이 바뀌면 그 줄만 서버에 센다. [제거] · [분할] 은 곧바로 바꾸지 않고
  // 임시 두 갈래(찾기 / 나머지)를 보여 준 뒤 [커밋] 때 서버에 쓴다 - 찾기만 = 남기기 · 나머지만 = 빼기 · 둘 다 = 두 줄.
  function rfHtml(r) {
    const s = rfFor(r.id) || { inc: [], exc: [], m: null, err: '' }, n = counts?.per?.[r.id];
    const chips = (list, kind) => list.map((tag, i) => `<span class="st-rf-chip${kind === 'exc' ? ' is-ex' : ''}">${esc(tag)}<button type="button"
      data-st-rf-x="${kind}:${i}" aria-label="${esc(tag)} 지우기">×</button></span>`).join('');
    const bar = (kind, label, ph) => `<div class="st-rf-bar"><span class="st-rf-lb">${label}</span><div class="st-rf-inp">${chips(s[kind], kind)}<input
      data-st-rf-in="${kind}" placeholder="${ph}" spellcheck="false" autocomplete="off" aria-label="${label}할 태그"></div></div>`;
    const has = s.inc.length + s.exc.length > 0, m = s.m;
    const can = has && !s.err && m != null && n != null && m > 0 && m < n;
    const why = !has ? '태그를 넣으면 이 조합 안에서 셉니다 - 쉼표 · Enter 로 칩'
      : s.err ? `찾지 못했습니다 — ${s.err}` : m == null ? '세는 중…' : m === 0 ? '맞는 게시물이 없습니다'
        : n != null && m === n ? '모두 맞습니다 - 나눌 것이 없습니다' : '';
    return `<div class="st-rf">${bar('inc', '포함', '태그 - 자동완성 · *정확히')}${bar('exc', '제외', '태그')}
      <div class="st-rf-sum"><span>${has && m != null && !s.err ? `맞음 <b>${fmtN(m)}</b>${n != null ? ` / ${fmtN(n)}` : ''}` : ''}${why ? `<i>${esc(why)}</i>` : ''}</span>
      <button type="button" data-st-rf-remove ${can ? '' : 'disabled'} title="맞는 게시물을 뺀 모습을 임시로 보여 줍니다 - 커밋해야 바뀝니다">제거</button>
      <button type="button" data-st-rf-split ${can ? '' : 'disabled'} title="맞는 것 / 나머지 두 갈래를 임시로 보여 줍니다 - 커밋해야 바뀝니다">분할</button></div></div>`;
  }
  function tempHtml() {
    const tp = temp, label = tp.terms.join(', '), n = tp.n ?? tp.m;
    const sub = (k, name, count) => `<div class="st-tmp-row${tp[k] ? '' : ' is-off'}"><button type="button" class="st-tmp-dot" data-st-tmp="${k}"
      aria-pressed="${tp[k]}" aria-label="${esc(name)} 남기기" title="${tp[k] ? '커밋하면 남습니다 - 눌러서 빼기' : '커밋하면 빠집니다 - 눌러서 남기기'}"></button><span
      class="st-tmp-tag">임시</span><span class="st-tmp-name">${esc(name)}</span><span class="st-tmp-n">${fmtN(count)}</span></div>`;
    const keep = (tp.a ? tp.m : 0) + (tp.b ? n - tp.m : 0);
    const msg = !tp.a && !tp.b ? '하나는 켜야 커밋할 수 있습니다' : tp.a && tp.b ? '커밋하면 두 줄로 나뉩니다' : `커밋하면 ${fmtN(keep)} / ${fmtN(n)}`;
    return `<div class="st-tmp">${sub('a', `찾기 ${label}`, tp.m)}${sub('b', '나머지', n - tp.m)}
      <div class="st-tmp-bar"><span>${esc(msg)}</span><button type="button" class="is-primary" data-st-tmp-commit ${tp.a || tp.b ? '' : 'disabled'}>커밋</button><button
        type="button" data-st-tmp-drop title="분할 전 그대로 둡니다">버림</button></div></div>`;
  }
  async function commitTemp() {
    const tp = temp, label = tp.terms.join(', ');
    const body = tp.a && tp.b ? { action: 'split', id: tp.id, terms: tp.terms }
      : { action: 'narrow', id: tp.id, terms: tp.terms, invert: !tp.a };
    await run(async () => {
      const data = await request('/api/event-map/staging', body);
      temp = null; rf = null; rfOpen = ''; rfText = { inc: '', exc: '' };
      if (body.action === 'split') openRow = '';
      applyStaging(data);
      toast(body.action === 'split' ? `두 줄로 나눴습니다 - '${label}' 맞는 것 / 나머지`
        : tp.a ? `'${label}' 에 맞는 것만 남겼습니다` : `'${label}' 에 맞는 것을 뺐습니다`, 'success');
    });
  }
  /** 목록을 새로 받았다 - 줄이 없어졌거나 조건이 바뀌었으면 검색 · 임시 분할을 내려놓는다. */
  function syncRowFind() {
    if (rf && !staged.some(r => r.id === rf.id)) { rf = null; rfOpen = ''; rfText = { inc: '', exc: '' }; closeAc(); }
    if (temp) {
      const row = staged.find(r => r.id === temp.id);
      if (!row || fingerprint(row.selection) !== temp.fp) { temp = null; toast('조합이 바뀌어 임시 분할을 버렸습니다', 'info'); }
    }
  }
  function rfChanged() {
    if (!rf) return;
    rf.m = null; rf.err = '';
    paintBody();
    void runRowFind();
  }
  async function runRowFind() {
    const s = rf;
    if (!s) return;
    const terms = rfTerms(), mine = ++s.seq;
    if (!terms.length) return;
    try {
      const data = await request('/api/event-map/staging/search', { terms, id: s.id });
      if (rf !== s || mine !== s.seq) return;
      s.m = Number(data.per?.[s.id] ?? 0);
    } catch (error) {
      if (rf !== s || mine !== s.seq) return;
      s.err = error.message;
    }
    if (open) paintBody();
  }
  /** 칸에 친 것을 칩으로. `-x` 는 제외 칸으로 · `*x` 는 정확히(그대로 둔다) · 한 갈래에 16개까지(서버와 같다). */
  function addRfTags(kind, text, rest = '') {
    if (!rf) return;
    closeAc();
    rfText[kind] = rest;
    for (const raw of String(text || '').split(',')) {
      let tag = raw.trim().replace(/_/g, ' ').replace(/\s+/g, ' ').toLowerCase(), k = kind;
      if (tag.startsWith('-')) { k = 'exc'; tag = tag.replace(/^-+/, '').trim(); }
      if (!tag || /^\*+$/.test(tag) || rf[k].includes(tag)) continue;
      if (rf.inc.length + rf.exc.length >= 16) { toast('한 번에 16개까지 찾을 수 있습니다', 'info'); break; }
      rf[k].push(tag);
    }
    rfChanged();
  }
  function onRfKey(event) {
    const el = event.target, kind = el.dataset.stRfIn;
    if (event.isComposing) return;
    if (acEl && !acEl.hidden && acFor === kind && acItems.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        acActive = (acActive + (event.key === 'ArrowDown' ? 1 : -1) + acItems.length) % acItems.length;
        paintAc(el);
        return;
      }
      if ((event.key === 'Enter' || event.key === 'Tab') && acActive >= 0) { event.preventDefault(); chooseAc(acActive); return; }
      if (event.key === 'Escape') { event.preventDefault(); closeAc(); return; }
    }
    if (event.key === 'Enter') { event.preventDefault(); if (el.value.trim()) addRfTags(kind, el.value); return; }
    if (event.key === 'Backspace' && !el.value && rf?.[kind]?.length) { event.preventDefault(); rf[kind].pop(); rfChanged(); return; }
    if (event.key === 'Escape') { rfOpen = ''; closeAc(); paintBody(); }
  }
  // 자동완성 = 이벤트 맵 태그(/api/event-map/suggest - 한글도 받는다). 목록은 body 에 fixed 로 - 창보다 위로.
  function scheduleAc(input) {
    clearTimeout(acTimer);
    const kind = input.dataset.stRfIn, q = input.value.split(',').pop().trim().replace(/^[-*]+/, '');
    if (!q) { closeAc(); return; }
    acTimer = setTimeout(async () => {
      const mine = ++acSeq;
      try {
        const body = await request(`/api/event-map/suggest?${new URLSearchParams({ q, limit: '8' })}`);
        if (mine !== acSeq) return;
        acItems = body.items || []; acActive = acItems.length ? 0 : -1; acFor = kind;
      } catch { if (mine === acSeq) { acItems = []; acActive = -1; } }
      const live = panel?.body.querySelector(`[data-st-rf-in="${kind}"]`);
      if (live && document.activeElement === live) paintAc(live); else closeAc();
    }, 200);
  }
  function paintAc(input) {
    if (!acEl) {
      acEl = document.createElement('div');
      acEl.className = 'emt-ac';
      acEl.setAttribute('role', 'listbox');
      acEl.hidden = true;
      document.body.append(acEl);
      acEl.addEventListener('mousedown', event => event.preventDefault());   // 칸이 초점을 잃지 않게
      acEl.addEventListener('click', event => { const row = event.target.closest('[data-ac]'); if (row) chooseAc(Number(row.dataset.ac)); });
    }
    if (!acItems.length) { acEl.hidden = true; return; }
    acEl.innerHTML = acItems.map((it, i) => `<div class="emt-ac-row${i === acActive ? ' is-active' : ''}" data-ac="${i}" role="option">
      <span class="emt-ac-tag">${esc(it.tag)}</span><span class="emt-ac-kind">${esc(it.role_label || '')}</span><span class="emt-ac-n">${fmtK(it.observed)}</span></div>`).join('');
    acEl.hidden = false;
    acEl.style.zIndex = String(Number(panel.el.style.zIndex || 0) + 3);
    const r = input.getBoundingClientRect();
    acEl.style.left = `${Math.round(r.left)}px`;
    acEl.style.top = `${Math.round(r.bottom + 4)}px`;
    acEl.style.width = `${Math.round(Math.max(240, Math.min(r.width + 40, 360)))}px`;
  }
  function closeAc() {
    clearTimeout(acTimer); ++acSeq;
    acItems = []; acActive = -1;
    if (acEl) acEl.hidden = true;
  }
  function chooseAc(i) {
    const it = acItems[i], kind = acFor;
    if (!it) return;
    const input = panel?.body.querySelector(`[data-st-rf-in="${kind}"]`);
    const raw = input?.value || '', cut = raw.lastIndexOf(',');
    const prefix = (raw.slice(cut + 1).trim().match(/^[-*]+/) || [''])[0];
    addRfTags(kind, `${cut >= 0 ? raw.slice(0, cut + 1) : ''}${prefix}${it.tag}`);
  }

  // ── 프리셋(사용자 지시 2026-10-31) ──────────────────────────────────────────
  /** 스테이징 응답의 요약 `presets: {active, dirty, ...}` - 파일이 깨졌으면 null(줄만 숨긴다). */
  function takePresets(data) {
    if (!data || !('presets' in data)) return;
    const p = data.presets;
    presetState = p && typeof p === 'object' ? { active: p.active || '', dirty: p.dirty === true } : null;
    if (Array.isArray(p?.items)) presetList = p.items;
  }
  /** GET /staging/presets 또는 프리셋 동작의 응답 - 목록과 상태. */
  function takePresetList(data) {
    const p = Array.isArray(data?.items) ? data : data?.presets;
    if (!p || !Array.isArray(p.items)) return;
    presetList = p.items;
    presetState = { active: p.active || '', dirty: p.dirty === true };
  }
  async function loadPresets() {
    try { takePresetList(await request('/api/event-map/staging/presets')); } catch { /* 줄만 옛것 */ }
    if (open) paint();
  }
  function paintPresets() {
    const row = panel?.body.querySelector('.st-presets');
    if (!row) return;
    row.hidden = !presetList.length && !staged.length;
    if (row.hidden) return;
    const act = presetState?.active || '', dirty = !!act && presetState?.dirty;
    const cur = presetList.find(p => p.id === act);
    row.innerHTML = '<span class="st-plabel">프리셋</span>' + presetList.map(p => {
      const on = p.id === act;
      return `<button type="button" class="st-pchip${on ? ' is-on' : ''}" data-st-preset="${esc(p.id)}"
        title="${on ? `지금 프리셋${dirty ? ' - 저장한 뒤 고쳤습니다' : ''} · 누르면 이름 · 덮어쓰기 · 삭제` : '눌러서 스테이징을 이 프리셋으로 바꾸기 · 우클릭 = 관리'}">${esc(p.name)}<span class="st-pn">${Number(p.count) || 0}</span>${on && dirty ? '<span class="st-pdirty">●</span>' : ''}</button>`;
    }).join('')
      + (cur && dirty ? `<button type="button" class="st-psave" data-st-psave title="지금 스테이징을 '${esc(cur.name)}' 에 저장합니다">저장</button>` : '')
      + `<button type="button" class="st-padd" data-st-padd ${staged.length ? '' : 'disabled'} title="지금 스테이징을 새 프리셋으로 저장합니다">+ 지금 것으로</button>`;
  }
  async function presetAction(body) {
    const data = await request('/api/event-map/staging/presets', body);
    takePresetList(data);
    return data;
  }
  async function askPresetName(title, value = '') {
    const fallback = staged[0]?.selection?.pins?.slice(0, 2).join(', ') || '프리셋';
    const name = typeof promptDialog === 'function'
      ? await promptDialog('프리셋 이름', { title, defaultValue: value || fallback, okText: '저장', placeholder: '예: 야외 구도' })
      : window.prompt('프리셋 이름', value || fallback);
    return String(name || '').trim();
  }
  async function savePresetAsNew() {
    const name = await askPresetName('새 프리셋');
    if (!name) return false;
    await presetAction({ action: 'save_new', name });
    toast(`새 프리셋 저장: ${name} — ${staged.length}개`, 'success');
    return true;
  }
  async function savePreset(pid) {
    const cur = presetList.find(p => p.id === pid);
    if (!cur) return;
    await presetAction({ action: 'save', id: pid });
    toast(`프리셋 저장: ${cur.name}`, 'success');
  }
  /** 칩을 눌렀다 - 지금 스테이징이 어느 프리셋에도 저장되지 않았거나 저장한 뒤 고쳤으면 먼저 묻는다(사용자 결정 2026-10-31). */
  async function switchPreset(pid) {
    const target = presetList.find(p => p.id === pid);
    if (!target) return;
    const cur = presetList.find(p => p.id === presetState?.active);
    const changed = staged.length > 0 && (!cur || presetState?.dirty);
    if (changed && typeof confirmDialog === 'function') {
      const pick = await confirmDialog(cur
        ? `지금 프리셋(${cur.name})을 저장한 뒤 고친 것이 있습니다.`
        : '지금 스테이징은 어느 프리셋에도 저장되어 있지 않습니다.', {
        title: `프리셋 바꾸기: ${target.name}`,
        choices: [cur ? { key: 'save', label: `${cur.name}에 저장하고 바꾸기` } : { key: 'new', label: '새 프리셋으로 저장하고 바꾸기' },
          { key: 'drop', label: '저장하지 않고 바꾸기' }],
      });
      if (!pick) return;
      if (pick === 'save') await savePreset(cur.id);
      if (pick === 'new' && !(await savePresetAsNew())) return;
    }
    const data = await request('/api/event-map/staging/presets', { action: 'load', id: pid });
    openRow = '';
    applyStaging(data);
    takePresetList(data);
    toast(`프리셋 바꿈: ${target.name} — ${staged.length}개`, 'success');
  }
  function openPresetMenu(pid, anchor) {
    const p = presetList.find(x => x.id === pid);
    if (!p) return;
    if (!pmenuEl) {
      pmenuEl = document.createElement('div');
      pmenuEl.className = 'st-menu';
      pmenuEl.setAttribute('role', 'menu');
      pmenuEl.hidden = true;
      document.body.append(pmenuEl);
      pmenuEl.addEventListener('click', onPresetMenu);
    }
    const on = pid === presetState?.active;
    pmenuFor = pid;
    pmenuEl.innerHTML = `<div class="st-menu-label">${esc(p.name)} · 조합 ${Number(p.count) || 0}개</div>
      ${on ? '' : '<button type="button" role="menuitem" data-stp="load">이 프리셋으로 바꾸기</button>'}
      <button type="button" role="menuitem" data-stp="rename">이름 바꾸기</button>
      <button type="button" role="menuitem" data-stp="save" ${staged.length ? '' : 'disabled'}>지금 스테이징으로 덮어쓰기</button>
      <div class="st-menu-sep"></div>
      <button type="button" role="menuitem" class="is-danger" data-stp="delete">삭제</button>`;
    pmenuEl.hidden = false;
    pmenuEl.style.zIndex = String(Number(panel.el.style.zIndex || 0) + 2);
    const r = anchor.getBoundingClientRect(), w = pmenuEl.offsetWidth, h = pmenuEl.offsetHeight;
    pmenuEl.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - w - 4))}px`;
    pmenuEl.style.top = `${r.bottom + 4 + h > window.innerHeight ? Math.max(4, r.top - h - 4) : r.bottom + 4}px`;
    setTimeout(() => document.addEventListener('pointerdown', onPresetMenuOutside, true), 0);
  }
  function closePresetMenu() {
    if (pmenuEl) pmenuEl.hidden = true;
    pmenuFor = '';
    document.removeEventListener('pointerdown', onPresetMenuOutside, true);
  }
  function onPresetMenuOutside(event) { if (!pmenuEl?.contains(event.target)) closePresetMenu(); }
  async function onPresetMenu(event) {
    const what = event.target.closest('[data-stp]')?.dataset.stp;
    const pid = pmenuFor, p = presetList.find(x => x.id === pid);
    if (!what || !p) return;
    closePresetMenu();
    if (what === 'load') { await run(() => switchPreset(pid), { readsExtras: true }); return; }
    if (what === 'save') {
      const ok = typeof confirmDialog === 'function' ? await confirmDialog(`지금 스테이징(${staged.length}개)으로 프리셋을 덮어씁니다: ${p.name}`) : true;
      if (ok) await run(() => savePreset(pid), { readsExtras: true });
      return;
    }
    if (what === 'rename') {
      const name = await askPresetName('프리셋 이름 바꾸기', p.name);
      if (name && name !== p.name) await run(async () => { await presetAction({ action: 'rename', id: pid, name }); toast('이름을 바꿨습니다', 'success'); });
      return;
    }
    if (what === 'delete') {
      const ok = typeof confirmDialog === 'function' ? await confirmDialog(`프리셋을 지웁니다: ${p.name} · 지금 스테이징은 그대로 남습니다.`) : true;
      if (ok) await run(async () => { await presetAction({ action: 'delete', id: pid }); toast('프리셋을 지웠습니다', 'success'); });
    }
  }

  // ── 조합 안 찾기(사용자 지시 2026-10-31) ─────────────────────────────────────
  function scheduleFind(delay = 250) {
    if (!FIND_ENABLED) return;
    clearTimeout(findTimer);
    findTimer = setTimeout(() => { void runFind(); }, delay);
  }
  async function runFind() {
    const text = findText.trim(), mine = ++findSeq;
    if (!text || !staged.length) { findResult = null; findError = ''; if (open) paint(); return; }
    try {
      const data = await request('/api/event-map/staging/search', { terms: text });
      if (mine !== findSeq) return;
      findResult = data; findError = '';
    } catch (error) {
      if (mine !== findSeq) return;
      findResult = null; findError = error.message;
    }
    if (open) paint();
  }
  function paintFind() {
    const row = panel?.body.querySelector('.st-find'), hint = panel?.body.querySelector('.st-find-hint');
    if (!row || !hint) return;
    const show = FIND_ENABLED && tab === 'stage' && staged.length > 0;
    row.hidden = hint.hidden = !show;
    if (!show) return;
    const field = row.querySelector('[data-st-find]');
    if (field && document.activeElement !== field && field.value !== findText) field.value = findText;
    if (findError) { hint.textContent = `찾지 못했습니다 — ${findError}`; return; }
    if (!findResult) { hint.textContent = 'Quick Filter 문법 - hair(부분) · *1girl(정확) · -red(빼기) · 쉼표 = 그리고'; return; }
    const hitRows = staged.filter(r => (findResult.per?.[r.id] || 0) > 0).length;
    hint.textContent = `맞는 조합 ${hitRows}/${staged.length}개 · 줄을 눌러 [분할] = 맞는 것 / 나머지 두 줄 · [만 남기기] = 맞는 것만`;
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
    /** 다른 창이 프리셋을 저장 · 이름 바꿈 · 삭제했다(WS event_map_staging_presets). */
    receivePresets: () => { if (open) void loadPresets(); },
    receiveCount: message => {
      stagedCount = Number(message?.total ?? message?.count) || 0;
      if (open) void reload({ keepCounts: message?.same_counts === true }); else void refreshCounts();
    },
  };
}
