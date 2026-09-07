/* Fast Search — Ctrl+F 로 여는 한 칸 검색.
 *
 * 태그·아티스트·캐릭터·와일드카드·프리셋·이벤트를 한 자리에서 찾고,
 * 고른 것은 **클립보드로만** 간다(사용자 지시 2026-09-05).
 *
 * ⚠️ 이 창은 **프롬프트를 절대 건드리지 않는다.** 붙여넣기는 사용자가 한다.
 *    "메인 프롬프트가 덮이는 것"은 이 저장소에서 반복해서 지적받은 사항이라,
 *    삽입 경로를 아예 만들지 않는 것이 계약이다.
 *
 * 검색기는 서버가 갖고 있다(`/api/fast-search`). 여기서는 그리기·키·복사만 한다.
 *
 * 크기 규약(사용자 지적 2026-09-07): Spotlight 처럼 **작게**. 결과 칸 폭의 가운데에
 * 최대 720px, 높이는 내용을 따라 자라되 결과 칸의 **절반**을 넘지 않는다 — 결과
 * 이미지를 통째로 가리면 안 된다. 나머지는 안에서 스크롤한다. 앞 갈래들이 길어 이벤트
 * 구역이 밀리면 머리 + 행 다섯 줄이 들어올 만큼만 늘린다(최대 75%, fitHeight).
 *
 * 몸통(.fs-body)은 두 칸이다: 앞의 갈래들(태그·아티스트·캐릭터·와일드카드·프리셋)을 그리는
 * `.fs-lanes` 와, 마지막의 **이벤트 구역**(.fs-event-section). 이벤트에만 필요한 것들은 전부
 * 이벤트 구역 머리에 있다(사용자 지정 2026-09-07 "이벤트 관련 기능은 이벤트 쪽에 묶어라"):
 *  - 조건 한 줄 [이벤트 · 3–8태그 조합] [인원 ▾] [G S Q E]
 *    · 인원은 Interactive 의 ALT 팝업과 같은 체크 목록(여럿 켬). 기본은 **여성이 들어간
 *      구성 전부**(8/13). 남성만·기타는 꺼져 있다.
 *    · 등급은 Quick Filter 의 G S Q E 알약을 그대로 쓴다(여럿 켬, 기본 전부).
 *  - 걸린 이벤트가 둘 이상이면 **칩** 줄(전부 보인다, 스크롤 없음). 칩 본문을 누르면 그 이벤트
 *    묶음으로 **이동**하고(지금 보이는 묶음의 칩은 연노랑), 칩의 × 를 눌러야만 그 이벤트가
 *    **숨겨진다**(줄 그은 칩으로 남아 다시 누르면 돌아온다). 서버에는 숨긴 것(OFF 목록)만
 *    보낸다 — deep 단계에서 이벤트가 더 발견돼도 파라미터가 안 바뀌어 페이징이 흔들리지 않는다.
 *    이름이 아니라 조합 안의 태그로만 걸린 이벤트(rank 4)는 "그 외 N개" 칩 하나로 묶는다.
 *  머리는 이벤트 구역 **위에 고정**돼 내용과 함께 스크롤된다. 조건 칸이 포커스를 잃지 않게
 *  **한 번만 만들고** 다시 그리지 않는다(목록만 다시 그린다).
 *
 * 이벤트는 "더 보기" 버튼 없이 **스크롤로 이어서** 본다: 3–8태그 조합을 다 보이면
 * 9–16태그 조합으로 넘어가고, 끝나면 끝이라고 말한다.
 *
 * 이벤트 목록은 **이벤트가 카테고리**다: 서버가 이벤트별로 묶어 보내고, 여기서는 이벤트가
 * 바뀌는 자리에 이름을 한 번만 찍는다(머리글 줄은 배경색으로 구분). 행의 본문은 태그 조합이다.
 * **관측 1회** 짜리 행은 묶음마다 뒤로 빼서 "관측 1회 N개 더보기" 로 접어 둔다(사용자 지정
 * 2026-09-07 — 카탈로그의 62% 가 관측 1 이라 그대로 두면 목록이 잡음으로 찬다).
 *
 * 이벤트 행을 누르거나 Enter 하면 **복사하지 않고** 그 행 바로 아래가 인라인으로 펼쳐진다:
 * 머리 = [선택한 조합] [프롬프트 복사] [이웃 조합에서 찾기] [×], 몸 = (1) 고른 조합을 전부
 * 포함하는 더 긴 조합, (2) 핵심(앵커) 태그를 뺀 나머지가 한 태그만 다른 조합. (1)에 든 것은
 * (2)에 다시 나오지 않는다. 비어 있는 절은 아예 안 그리고 둘 다 비면 머리만 남는다. 이웃 행을
 * 누르면 그것이 복사 대상이 되고(연한 강조), [프롬프트 복사] 가 대상을 복사한다. 이웃 행도
 * 관측 1회는 절마다 더보기로 접는다. 찾기 칸은 **이 펼침 안에서만** 거른다(국소 검색).
 */

const SOURCES = [
  { id: 'tag', label: '태그' },
  { id: 'artist', label: '아티스트' },
  { id: 'character', label: '캐릭터' },
  { id: 'wildcard', label: '와일드카드' },
  { id: 'preset', label: '프리셋' },
  { id: 'event', label: '이벤트' },
];
const DEBOUNCE_MS = 170;
const PER_SOURCE = 8;
const EVENT_PAGE = 8;
// 칩으로 묶음을 찾아가는 동안은 큰 쪽으로 받는다. ⚠️ 서버 MAX_LIMIT(20)을 넘기면 잘려 오고, 그걸
// '끝' 으로 오판해 basic 단계가 잘렸다(실측 2026-09-07, 64 로 두었을 때). 서버 상한과 같게 둔다.
const EVENT_SEEK_PAGE = 20;
const EVENT_PHASES = ['basic', 'deep'];   // 3–8태그 -> 9–16태그 -> 끝
const RATING_OPTIONS = [
  { id: 'g', label: 'G', title: 'General' },
  { id: 's', label: 'S', title: 'Sensitive' },
  { id: 'q', label: 'Q', title: 'Questionable' },
  { id: 'e', label: 'E', title: 'Explicit' },
];
// 서버 카탈로그의 13개 인원 분면. 묶음 머리글은 ALT 팝업과 같은 방식(무엇을 고르는지).
const PERSON_GROUPS = [
  { g: '여성', ids: ['1girl_solo', '1girl', '2girls', 'multiple_girls'] },
  { g: '혼성', ids: ['1girl_1boy', '1girl_multiple_boys', '1boy_multiple_girls', 'multiple_girls_multiple_boys'] },
  { g: '남성', ids: ['1boy_solo', '1boy', '2boys', 'multiple_boys'] },
  { g: '기타', ids: ['other'] },
];
const PERSON_IDS = PERSON_GROUPS.flatMap(group => group.ids);
// 기본값: 여성이 들어간 구성 전부(사용자 지정). 남성만·기타는 꺼짐.
const DEFAULT_PERSONS = [...PERSON_GROUPS[0].ids, ...PERSON_GROUPS[1].ids];
const NEIGHBOR_LIMIT = 20;
const REST_KEY = '__rest__';

export function initFastSearch() {
  let overlay = null, input = null, body = null, countEl = null, chipRow = null;
  let lanesEl = null, eventSection = null, eventList = null, eventChips = null, eventNote = null;
  let open = false, seq = 0, timer = null, eventTimer = null;
  let rows = [];            // 평면화된 결과 - 키보드 이동의 단위(갈래들 + 이벤트 순)
  let active = -1;
  // 가벼운 사전들만 기본으로 켠다. 나머지는 사용자가 칩으로 켠다(지연 로딩).
  let enabled = new Set(['tag', 'artist', 'character']);
  let groups = new Map(), pending = new Set();
  let eventOptions = null;
  let eventRatings = new Set(RATING_OPTIONS.map(r => r.id));
  let eventPersons = new Set(DEFAULT_PERSONS);
  let personBtn = null, personPopup = null;
  // 이 질의에 걸린 이벤트들({tag,label,count,rank}) 과 사용자가 숨긴 것. 질의가 바뀌면 둘 다 비운다.
  let eventCatalog = [];
  let eventOff = new Set();
  let currentAnchor = null;   // 지금 화면 위쪽에 보이는 묶음(칩 연노랑)
  let seekAnchor = null;      // 칩을 눌러 찾아가는 중인 이벤트 - 다음 쪽을 이어 받으며 찾는다
  // 필터·칩으로 이벤트만 다시 불러올 때 지킬 스크롤 위치. 새 내용이 더 짧아 클램프되면 그 위치가
  // 들어올 때까지 다음 쪽을 이어 받는다(예전엔 목록을 비운 순간 0 으로 클램프돼 맨 위로 튀었다).
  let restoreScroll = null;
  // "관측 1회 N개 더보기" 를 펼친 묶음. 키 = `${단계}:${앵커}`.
  let moreOpen = new Set();
  // 이벤트 페이징 상태. phase 는 EVENT_PHASES 의 인덱스, offset 은 그 phase 안의 위치.
  let eventPaging = freshEventPaging();
  // 높이 상한. base = 결과 칸의 50%(이미지를 통째로 가리지 않는다), hard = 75%. 이벤트 구역이
  // 아래로 밀려 머리만 보이면 base 와 hard 사이에서 **필요한 만큼만** 늘린다(fitHeight).
  let heightCaps = {base: 0, hard: 0};
  // 인라인으로 펼친 이웃 조합. 한 행만 펼친다.
  // {key, anchor, tags, payload, loading, seq, search, target, more:Set}
  let inline = null, inlineSeq = 0, inlineRows = [];
  const requests = new Map(SOURCES.map(s => [s.id, {busy: false, wanted: null}]));

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  function freshEventPaging() {
    return {phase: 0, offset: 0, done: false, items: [], deepStart: -1};
  }

  function toast(message, kind) {
    if (typeof window !== 'undefined' && typeof window.showToast === 'function') {
      window.showToast(message, kind || 'info');
    }
  }

  /** 관측 수. 서버가 `count` 를 주고, 없으면 meta 의 "관측 N" 을 읽는다. */
  function observed(item) {
    const n = Number(item?.count);
    if (Number.isFinite(n)) return n;
    const m = /관측\s*([\d,]+)/.exec(String(item?.meta || ''));
    return m ? Number(m[1].replace(/,/g, '')) : NaN;
  }

  /** 서버에 보내는 등급·인원·숨긴 이벤트. 전부 켜져 있으면 빈 문자열(= 필터 없음). */
  function filterParams() {
    const rating = eventRatings.size === RATING_OPTIONS.length ? ''
      : RATING_OPTIONS.map(r => r.id).filter(id => eventRatings.has(id)).join(',');
    const person = eventPersons.size === PERSON_IDS.length ? ''
      : PERSON_IDS.filter(id => eventPersons.has(id)).join(',');
    const exclude = eventOff.size ? eventCatalog.map(e => e.tag).filter(tag => eventOff.has(tag)).join(',') : '';
    return {rating, person, exclude};
  }

  function build() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'fs-overlay';
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="fs-bar">
        <span class="fs-icon" aria-hidden="true">⌕</span>
        <input class="fs-input" type="search" autocomplete="off" spellcheck="false"
               aria-label="빠른 검색"
               placeholder="태그 · 아티스트 · 캐릭터 · 와일드카드 · 프리셋 · 이벤트">
        <span class="fs-count" role="status" aria-live="polite"></span>
        <button type="button" class="fs-close" aria-label="닫기">×</button>
      </div>
      <div class="fs-chips"></div>
      <div class="fs-body">
        <div class="fs-lanes" data-fs-lanes></div>
        <div class="fs-event-section" data-fs-event-section hidden>
          <div class="fs-event-head">
            <div class="fs-event-options">
              <span class="fs-cap fs-cap-inline">이벤트<span class="fs-note" data-fs-event-note></span></span>
              <button type="button" class="fs-person-btn" data-fs-person-btn aria-haspopup="dialog"
                      aria-expanded="false" title="이벤트 인원 구성 고르기">인원 <b data-fs-person-count></b></button>
              <span class="fs-rating-bar" role="group" aria-label="이벤트 등급">${RATING_OPTIONS.map(r =>
                `<button type="button" class="fs-rating-btn active" data-r="${r.id}" aria-pressed="true" title="${r.title}">${r.label}</button>`).join('')}</span>
            </div>
            <div class="fs-ev-chips" data-fs-event-chips role="group" aria-label="걸린 이벤트" hidden></div>
          </div>
          <div class="fs-event-list" data-fs-event-list></div>
        </div>
      </div>
      <div class="fs-foot">↑↓ 이동 · <b>Enter</b> 복사 (이벤트는 펼치기) · Esc 닫기 — 프롬프트에는 넣지 않습니다</div>`;
    document.body.append(overlay);
    input = overlay.querySelector('.fs-input');
    body = overlay.querySelector('.fs-body');
    countEl = overlay.querySelector('.fs-count');
    chipRow = overlay.querySelector('.fs-chips');
    lanesEl = body.querySelector('[data-fs-lanes]');
    eventSection = body.querySelector('[data-fs-event-section]');
    eventList = body.querySelector('[data-fs-event-list]');
    eventChips = body.querySelector('[data-fs-event-chips]');
    eventNote = body.querySelector('[data-fs-event-note]');
    eventOptions = body.querySelector('.fs-event-options');
    personBtn = eventOptions.querySelector('[data-fs-person-btn]');
    personBtn.addEventListener('click', () => {
      if (personPopup && !personPopup.hidden) closePersonPopup(); else openPersonPopup();
    });
    paintPersonButton();
    eventOptions.addEventListener('click', event => {
      const pill = event.target.closest('.fs-rating-btn');
      if (!pill) return;
      const id = pill.dataset.r;
      // 마지막 하나까지 끄면 아무것도 안 나온다 - 최소 하나는 남긴다(소스 칩과 같은 규칙).
      if (eventRatings.has(id) && eventRatings.size === 1) return;
      if (eventRatings.has(id)) eventRatings.delete(id); else eventRatings.add(id);
      pill.classList.toggle('active', eventRatings.has(id));
      pill.setAttribute('aria-pressed', String(eventRatings.has(id)));
      scheduleEvents(0);
    });
    // 이벤트 칩: 본문 = 그 묶음으로 이동(숨긴 칩이면 다시 보이기), × = 숨기기. 최소 하나는 보인다.
    eventChips.addEventListener('mousedown', event => event.preventDefault());   // 포커스는 검색 칸에
    eventChips.addEventListener('click', event => {
      const chip = event.target.closest('[data-fs-ev-key]');
      if (!chip) return;
      const key = chip.dataset.fsEvKey;
      const isRest = key === REST_KEY;
      const hide = !!event.target.closest('[data-fs-ev-x]');
      const off = isRest ? !restIsOn() : eventOff.has(key);
      if (hide) {
        if (off || onChipCount() <= 1) return;
        if (isRest) restEvents().forEach(e => eventOff.add(e.tag)); else eventOff.add(key);
        paintEventChips();
        scheduleEvents(0);
        return;
      }
      if (off) {
        if (isRest) restEvents().forEach(e => eventOff.delete(e.tag)); else eventOff.delete(key);
        paintEventChips();
        scheduleEvents(0);
        return;
      }
      const target = isRest ? (restEvents().find(e => !eventOff.has(e.tag)) || {}).tag : key;
      if (target) seekToAnchor(target);
    });

    chipRow.innerHTML = SOURCES.map(s =>
      `<button type="button" class="fs-chip${enabled.has(s.id) ? ' is-on' : ''}" aria-pressed="${enabled.has(s.id)}" data-fs-source="${s.id}">${esc(s.label)}</button>`).join('');
    chipRow.addEventListener('click', event => {
      const chip = event.target.closest('[data-fs-source]');
      if (!chip) return;
      const id = chip.dataset.fsSource;
      // 마지막 하나까지 끄면 아무것도 못 찾는 창이 된다 - 최소 하나는 남긴다.
      if (enabled.has(id) && enabled.size === 1) return;
      if (enabled.has(id)) enabled.delete(id); else enabled.add(id);
      chip.classList.toggle('is-on', enabled.has(id));
      chip.setAttribute('aria-pressed', String(enabled.has(id)));
      schedule(0);
    });

    overlay.querySelector('.fs-close').addEventListener('click', close);
    input.addEventListener('input', () => schedule(DEBOUNCE_MS));
    input.addEventListener('keydown', onKeyDown);
    body.addEventListener('click', event => {
      const t = event.target;
      if (t.closest('[data-fs-inline-close]')) { closeInline(); return; }
      if (t.closest('[data-fs-inline-copy]')) { void copyInlineTarget(); return; }
      if (t.closest('[data-fs-inline-search]')) return;              // 입력 칸 - 아무것도 안 한다
      const more = t.closest('[data-fs-more]');
      if (more) { toggleMore(more.dataset.fsMore, more.dataset.fsMoreScope); return; }
      const inlineRow = t.closest('[data-fs-inline-index]');
      if (inlineRow) {
        // 이웃 행을 누르면 복사 대상이 된다 - 복사는 [프롬프트 복사] 가 한다(사용자 지정 2026-09-07).
        const item = inlineRows[Number(inlineRow.dataset.fsInlineIndex)];
        if (inline && item && item.value) {
          inline.target = String(item.value);
          eventList.querySelectorAll('[data-fs-inline-index]').forEach(node =>
            node.classList.toggle('is-active', node === inlineRow));
        }
        return;
      }
      const row = t.closest('[data-fs-index]');
      if (!row) return;
      active = Number(row.dataset.fsIndex);
      paintActive();
      commit();
    });
    // 펼친 칸의 찾기: 그 펼침 안의 이웃 행만 거른다(국소). 몸통 innerHTML 전체를 다시 만들지
    // 않고 펼친 칸의 몸만 갈아서 커서가 날아가지 않게 한다.
    eventList.addEventListener('input', event => {
      if (!event.target.matches('[data-fs-inline-search]') || !inline) return;
      inline.search = event.target.value.trim();
      paintInlineBody();
    });
    eventList.addEventListener('keydown', event => {
      if (!event.target.matches('[data-fs-inline-search]')) return;
      // ↑↓·Enter 는 찾기 칸 안에서는 목록을 움직이지 않는다(문서 Esc 만 그대로).
      if (['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) event.stopPropagation();
    });
    // 이벤트는 버튼 없이 스크롤로 이어 본다 - 바닥에 가까워지면 다음 쪽을 부른다.
    // 인원 팝업은 버튼 자리에 고정돼 있어 스크롤하면 떨어져 보인다 - 닫는다.
    body.addEventListener('scroll', () => { closePersonPopup(); updateCurrentAnchor(); maybeLoadMoreEvents(); }, {passive: true});
    // 바깥을 누르면 닫는다. 창·인원 팝업 안의 클릭은 각자 처리한다.
    document.addEventListener('pointerdown', event => {
      if (!open) return;
      const t = event.target;
      if (overlay.contains(t)) return;
      if (personPopup && !personPopup.hidden && personPopup.contains(t)) return;
      close();
    }, true);
    window.addEventListener('resize', position);
    return overlay;
  }

  // ── 인원 팝업 (Interactive ALT 팝업과 같은 체크 목록) ─────────────────────
  function ensurePersonPopup() {
    if (personPopup) return personPopup;
    personPopup = document.createElement('div');
    personPopup.className = 'fs-person-popup';
    personPopup.hidden = true;
    document.body.append(personPopup);
    // 포커스를 검색 칸에서 빼앗지 않는다(ALT 팝업과 같다).
    personPopup.addEventListener('mousedown', event => event.preventDefault());
    personPopup.addEventListener('click', event => {
      const quick = event.target.closest('[data-fs-person-set]');
      if (quick) {
        const which = quick.dataset.fsPersonSet;
        eventPersons = new Set(which === 'all' ? PERSON_IDS : DEFAULT_PERSONS);
        paintPersonPopup();
        paintPersonButton();
        scheduleEvents(0);
        return;
      }
      const row = event.target.closest('[data-fs-person]');
      if (!row) return;
      const id = row.dataset.fsPerson;
      if (eventPersons.has(id) && eventPersons.size === 1) return;   // 최소 하나
      if (eventPersons.has(id)) eventPersons.delete(id); else eventPersons.add(id);
      row.classList.toggle('is-on', eventPersons.has(id));
      row.setAttribute('aria-pressed', String(eventPersons.has(id)));
      paintPersonButton();
      scheduleEvents(120);      // 연달아 여러 개를 켜고 끄는 동안 요청을 줄 세우지 않는다
    });
    return personPopup;
  }

  function personPopupHtml() {
    const list = PERSON_GROUPS.map(group =>
      `<div class="fs-person-group">${esc(group.g)}</div>` + group.ids.map(id =>
        `<button type="button" class="fs-person-row${eventPersons.has(id) ? ' is-on' : ''}"
           data-fs-person="${esc(id)}" aria-pressed="${eventPersons.has(id)}">
           <span class="fs-person-box"></span>
           <span class="fs-person-label">${esc(id.replaceAll('_', ' '))}</span></button>`).join('')).join('');
    return `<div class="fs-person-head">인원 구성
        <span class="fs-person-quick">
          <button type="button" data-fs-person-set="default" title="여성이 들어간 구성 전부 (기본)">기본</button>
          <button type="button" data-fs-person-set="all">전체</button>
        </span></div>
      <div class="fs-person-list">${list}</div>
      <div class="fs-person-foot">여럿을 켤 수 있습니다. 기본은 <b>여성이 들어간 구성 전부</b>입니다.</div>`;
  }

  function paintPersonPopup() {
    if (!personPopup || personPopup.hidden) return;
    personPopup.innerHTML = personPopupHtml();
  }

  function paintPersonButton() {
    if (!personBtn) return;
    const count = personBtn.querySelector('[data-fs-person-count]');
    const all = eventPersons.size === PERSON_IDS.length;
    count.textContent = all ? '전체' : `${eventPersons.size}/${PERSON_IDS.length}`;
    personBtn.classList.toggle('is-filtered', !all);
  }

  function openPersonPopup() {
    const popup = ensurePersonPopup();
    popup.innerHTML = personPopupHtml();
    popup.hidden = false;
    personBtn.setAttribute('aria-expanded', 'true');
    const rect = personBtn.getBoundingClientRect();
    const pr = popup.getBoundingClientRect();
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - pr.width - 8));
    let top = rect.bottom + 6;
    if (top + pr.height > window.innerHeight - 8) top = Math.max(8, rect.top - pr.height - 6);
    popup.style.left = `${Math.round(left)}px`;
    popup.style.top = `${Math.round(top)}px`;
    document.addEventListener('pointerdown', onPersonOutside, true);
  }

  function closePersonPopup() {
    if (!personPopup || personPopup.hidden) return;
    personPopup.hidden = true;
    personPopup.innerHTML = '';
    if (personBtn) personBtn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', onPersonOutside, true);
  }

  function onPersonOutside(event) {
    if (personPopup && personPopup.contains(event.target)) return;
    if (event.target.closest?.('[data-fs-person-btn]')) return;   // 버튼 자체가 토글한다
    closePersonPopup();
  }

  // ── 이벤트 칩 ─────────────────────────────────────────────────────────────
  /** 이름으로 걸린 이벤트(rank ≤ 3)는 칩 하나씩. 쉼표 AND 로 행 안의 태그만 걸린 이벤트(rank 4)는
   *  "그 외 N" 칩 하나로 묶어 한 번에 숨기고 되살린다. 칩이 둘 이상일 때만 보인다 - 하나면 숨길 것도
   *  없다. 칩 본문 = 그 묶음으로 이동, × = 숨기기. 지금 보이는 묶음은 연노랑. */
  function namedEvents() { return eventCatalog.filter(e => e.rank <= 3); }
  function restEvents() { return eventCatalog.filter(e => e.rank > 3); }
  function restIsOn() { return restEvents().some(e => !eventOff.has(e.tag)); }
  function onChipCount() { return namedEvents().filter(e => !eventOff.has(e.tag)).length + (restEvents().length && restIsOn() ? 1 : 0); }
  function paintEventChips() {
    if (!eventChips) return;
    const named = namedEvents(), rest = restEvents();
    if (named.length + (rest.length ? 1 : 0) < 2) { eventChips.hidden = true; eventChips.innerHTML = ''; return; }
    eventChips.hidden = false;
    const chip = (key, on, current, label, count, hideTitle) => on
      ? `<span class="fs-ev-toggle is-on${current ? ' is-current' : ''}" data-fs-ev-key="${esc(key)}">`
        + `<button type="button" class="fs-ev-jump" title="이 묶음으로 이동">${esc(label)}<b>${count}</b></button>`
        + `<button type="button" class="fs-ev-x" data-fs-ev-x="1" aria-label="${esc(label)} 숨기기" title="${esc(hideTitle)}">×</button></span>`
      : `<span class="fs-ev-toggle is-off" data-fs-ev-key="${esc(key)}">`
        + `<button type="button" class="fs-ev-jump" title="다시 보이기">${esc(label)}<b>${count}</b></button></span>`;
    const parts = named.map(e => chip(e.tag, !eventOff.has(e.tag), e.tag === currentAnchor,
      e.label && e.label !== e.tag ? `${e.tag} · ${e.label}` : e.tag, Number(e.count) || 0,
      '이 이벤트의 조합을 숨깁니다'));
    if (rest.length) {
      parts.push(chip(REST_KEY, restIsOn(), rest.some(e => e.tag === currentAnchor),
        `그 외 ${rest.length}개 이벤트`, rest.reduce((n, e) => n + (Number(e.count) || 0), 0),
        '이름이 아니라 조합 안의 태그로 걸린 이벤트들을 한 번에 숨깁니다: ' + rest.map(e => e.tag).join(', ')));
    }
    eventChips.innerHTML = parts.join('');
  }

  /** 서버가 첫 쪽에 실어 보낸 이벤트 목록. basic 첫 쪽은 **교체**(replace) - 등급·인원을 조작해
   *  조합이 하나도 안 남는 이벤트의 칩은 조용히 사라져야 한다. deep 첫 쪽은 합친다(더 찾을 수 있다).
   *  숨긴 기록(eventOff)은 건드리지 않아 필터를 되돌리면 숨긴 채 돌아온다. */
  function mergeEventCatalog(list, replace = false) {
    if (!Array.isArray(list)) return;
    if (replace) eventCatalog = [];
    const known = new Set(eventCatalog.map(e => e.tag));
    for (const e of list) {
      if (!e || typeof e.tag !== 'string' || known.has(e.tag)) continue;
      eventCatalog.push({tag: e.tag, label: String(e.label || e.tag), count: Number(e.count) || 0, rank: Number.isFinite(Number(e.rank)) ? Number(e.rank) : 4});
      known.add(e.tag);
    }
    paintEventChips();
  }

  /** 지금 화면 위쪽에 걸린 묶음 = 머리글이 몸통 위 가장자리 위로 지나간 마지막 것. 없으면 첫 보이는 것. */
  function updateCurrentAnchor() {
    if (!eventList || eventSection.hidden) { setCurrentAnchor(null); return; }
    const headers = eventList.querySelectorAll('.fs-cap-ev[data-anchor]');
    if (!headers.length) { setCurrentAnchor(null); return; }
    const b = body.getBoundingClientRect();
    let current = null, firstVisible = null;
    for (const header of headers) {
      const top = header.getBoundingClientRect().top;
      if (top <= b.top + 12) current = header.dataset.anchor;
      else if (firstVisible == null && top < b.bottom) firstVisible = header.dataset.anchor;
    }
    setCurrentAnchor(current ?? firstVisible);
  }

  function setCurrentAnchor(tag) {
    if (tag === currentAnchor) return;
    currentAnchor = tag;
    paintEventChips();
  }

  function headerFor(tag) {
    return eventList.querySelector(`.fs-cap-ev[data-anchor="${CSS.escape(tag)}"]`);
  }

  function scrollToHeader(header) {
    const top = header.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
    body.scrollTop = Math.max(0, Math.round(top - 2));
    updateCurrentAnchor();
  }

  /** 칩 본문: 그 이벤트 묶음으로 이동. 아직 안 받은 쪽에 있으면 큰 쪽으로 이어 받으며 찾는다. */
  function seekToAnchor(tag) {
    const header = headerFor(tag);
    if (header) { seekAnchor = null; scrollToHeader(header); setCurrentAnchor(tag); return; }
    if (eventPaging.done) return;
    seekAnchor = tag;
    requestEventPage(seq);
  }

  /** "관측 1회 N개 더보기/접기". scope = 'list'(묶음) | 'inline'(펼친 칸의 절). */
  function toggleMore(key, scope) {
    if (scope === 'inline') {
      if (!inline) return;
      if (inline.more.has(key)) inline.more.delete(key); else inline.more.add(key);
      paintInlineBody();
      return;
    }
    if (moreOpen.has(key)) moreOpen.delete(key); else moreOpen.add(key);
    render(input.value.trim());
  }

  /** Spotlight 크기. 결과 칸 가운데, 폭 ≤ 720, 높이 ≤ 결과 칸의 절반. */
  function position() {
    if (!overlay || overlay.hidden) return;
    const host = document.querySelector('#rightTabResult') || document.querySelector('.app-layout');
    const r = host ? host.getBoundingClientRect() : null;
    if (!r || r.width < 240 || r.height < 160) {
      overlay.style.left = '50%';
      overlay.style.transform = 'translateX(-50%)';
      overlay.style.top = '64px';
      overlay.style.width = 'min(680px, calc(100vw - 32px))';
      heightCaps = {base: Math.min(420, window.innerHeight - 96), hard: Math.round(window.innerHeight * 0.75)};
      fitHeight();
      return;
    }
    const pad = 14;
    const width = Math.round(Math.min(720, Math.max(240, r.width - pad * 2)));
    // 이미지를 통째로 가리지 않는다: 결과 칸 높이의 절반이 상한. 너무 작아지면
    // 목록이 못 쓰게 되니 260px 은 보장한다(그래도 칸보다 크진 않게).
    const maxH = Math.round(Math.min(r.height - pad * 2, Math.max(260, r.height * 0.5)));
    overlay.style.transform = 'none';
    overlay.style.left = `${Math.round(r.left + (r.width - width) / 2)}px`;
    overlay.style.top = `${Math.round(r.top + pad)}px`;
    overlay.style.width = `${width}px`;
    heightCaps = {base: maxH, hard: Math.round(Math.min(r.height - pad * 2, r.height * 0.75))};
    fitHeight();
  }

  /** 높이 상한을 내용에 맞춘다. 기본은 base. 이벤트 구역이 앞 갈래들에 밀려 머리만 바닥에 걸리면
   *  머리 + 행 다섯 줄이 들어올 만큼만 늘린다. hard(75%) 를 넘지 않는다. */
  function fitHeight() {
    if (!overlay || overlay.hidden || !heightCaps.base) return;
    let want = heightCaps.base;
    if (eventSection && !eventSection.hidden && eventList.children.length) {
      const chrome = overlay.offsetHeight - body.clientHeight;      // 검색 줄 + 칩 줄 + 발 + 테두리
      const top = eventSection.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
      const headH = eventSection.querySelector('.fs-event-head').offsetHeight;
      const rowsH = Math.min(eventList.offsetHeight, 5 * 24 + 26);
      want = Math.max(want, Math.ceil(chrome + top + headH + rowsH));
    }
    overlay.style.maxHeight = `${Math.round(Math.min(heightCaps.hard, want))}px`;
  }

  function schedule(delay) {
    clearTimeout(timer);
    clearTimeout(eventTimer);
    const mine = ++seq; // 디바운스 전에 무효화한다 - Enter/복사도 포함.
    for (const slot of requests.values()) slot.wanted = null;
    rows = [];
    active = -1;
    groups = new Map();
    eventPaging = freshEventPaging();
    // 질의가 바뀌면 걸린 이벤트도 숨긴 것도 펼친 것도 새로 시작한다.
    eventCatalog = [];
    eventOff = new Set();
    currentAnchor = null;
    seekAnchor = null;
    restoreScroll = null;
    moreOpen = new Set();
    inline = null;
    paintEventChips();
    if (!enabled.has('event')) closePersonPopup();
    const query = input.value.trim();
    pending = new Set([...enabled].filter(id => query || id === 'wildcard'));
    body.scrollTop = 0;                   // 새 질의는 맨 위에서
    render(query);
    timer = setTimeout(() => run(mine), delay);
  }

  /** 이벤트 조건(인원·등급·숨긴 이벤트)만 바뀌었을 때 - 다른 갈래는 그대로 둔다. */
  function scheduleEvents(delay) {
    clearTimeout(eventTimer);
    if (!enabled.has('event')) return;
    const mine = seq;
    const slot = requests.get('event');
    slot.wanted = null;
    // 옛 행은 새 첫 쪽이 올 때까지 그대로 둔다 - 비우면 내용이 짧아져 스크롤이 0 으로 클램프된다.
    eventPaging = freshEventPaging();
    seekAnchor = null;
    restoreScroll = body.scrollTop;
    moreOpen = new Set();
    inline = null;
    const query = input.value.trim();
    if (query) pending.add('event');
    render(query);
    eventTimer = setTimeout(() => {
      if (mine !== seq || !open || !query) return;
      requestEventPage(mine);
    }, delay);
  }

  function run(mine) {
    if (mine !== seq || !open) return;
    const query = input.value.trim();
    for (const source of SOURCES) {
      if (!pending.has(source.id)) continue;
      if (source.id === 'event') { requestEventPage(mine); continue; }
      requests.get(source.id).wanted = {query, mine};
      void drain(source);
    }
  }

  function requestEventPage(mine) {
    if (eventPaging.done) return;
    const query = input.value.trim();
    if (!query) return;
    const slot = requests.get('event');
    const {rating, person, exclude} = filterParams();
    slot.wanted = {
      query, mine, rating, person, exclude,
      detail: EVENT_PHASES[eventPaging.phase], offset: eventPaging.offset,
      limit: seekAnchor ? EVENT_SEEK_PAGE : EVENT_PAGE,
    };
    void drain(SOURCES.find(s => s.id === 'event'));
  }

  function maybeLoadMoreEvents() {
    if (!open || !enabled.has('event') || eventPaging.done) return;
    if (requests.get('event').busy || requests.get('event').wanted) return;
    if (!groups.has('event')) return;                   // 첫 쪽이 아직 안 왔다
    const nearBottom = body.scrollTop + body.clientHeight >= body.scrollHeight - 120;
    const cannotScroll = body.scrollHeight <= body.clientHeight + 4;
    if (nearBottom || cannotScroll) requestEventPage(seq);
  }

  async function drain(source) {
    const slot = requests.get(source.id);
    if (slot.busy) return;
    slot.busy = true;
    try {
      // 갈래마다 진행 요청 하나·최신 대기 하나만 둔다. fetch 를 끊어도 파이썬 쪽
      // 작업은 안 멈추니, 글자마다 새 초기화를 줄 세우지 않는다.
      while (slot.wanted) {
        const request = slot.wanted;
        const {query, mine} = request;
        slot.wanted = null;
        const isEvent = source.id === 'event';
        const params = new URLSearchParams({q: query, sources: source.id, limit: String(isEvent ? request.limit : PER_SOURCE)});
        if (isEvent) {
          params.set('rating', request.rating);
          params.set('person', request.person);
          params.set('event_exclude', request.exclude);
          params.set('event_detail', request.detail);
          params.set('event_offset', String(request.offset));
        }
        let group;
        try {
          const response = await fetch(`/api/fast-search?${params}`, {cache: 'no-store'});
          if (!response.ok) throw new Error('search failed');
          const payload = await response.json();
          group = payload.groups?.find(g => g.source === source.id);
          if (!group || !Array.isArray(group.items)) throw new Error('invalid group');
        } catch {
          group = {source: source.id, label: source.label, items: [], note: '검색에 실패했습니다. 다시 입력해 주세요.', exhausted: true};
        }
        if (mine !== seq || !open || !enabled.has(source.id)) continue;
        if (isEvent) {
          // 같은 phase/offset/조건이 아니면 낡은 쪽이다 - 조건이 바뀐 뒤에 온 답.
          // (걸린 이벤트 목록을 합치기 **전**에 비교한다 - 합친 뒤엔 exclude 문구가 달라질 수 있다.)
          const now = filterParams();
          if (request.detail !== EVENT_PHASES[eventPaging.phase] || request.offset !== eventPaging.offset
              || request.rating !== now.rating || request.person !== now.person
              || request.exclude !== now.exclude) continue;
          mergeEventCatalog(group.events, request.detail === 'basic' && request.offset === 0);
          if (eventPaging.phase === 1 && eventPaging.deepStart < 0 && group.items.length) {
            eventPaging.deepStart = eventPaging.items.length;
          }
          eventPaging.items.push(...group.items);
          eventPaging.offset += group.items.length;
          // 끝 판정은 서버 말을 우선한다 - 서버가 limit 을 잘랐을 수 있어 길이 비교만으로는 오판한다.
          const exhausted = typeof group.exhausted === 'boolean' ? group.exhausted : group.items.length < request.limit;
          if (exhausted) {
            if (eventPaging.phase + 1 < EVENT_PHASES.length) { eventPaging.phase += 1; eventPaging.offset = 0; }
            else eventPaging.done = true;
          }
          groups.set('event', {source: 'event', label: source.label, items: eventPaging.items, note: group.note || ''});
          pending.delete('event');
          render(query);
          if (restoreScroll != null) {
            // 다시 불러온 뒤 옛 스크롤 위치로. 내용이 아직 짧아 못 가면 다음 쪽을 이어 받는다.
            body.scrollTop = restoreScroll;
            if (Math.abs(body.scrollTop - restoreScroll) <= 2 || eventPaging.done || seekAnchor) restoreScroll = null;
            else { requestEventPage(mine); continue; }
          }
          if (seekAnchor) {
            // 칩으로 찾아가는 중: 머리글이 나타났으면 거기로, 아니면 다음 쪽을 이어 받는다.
            const header = headerFor(seekAnchor);
            if (header) { const tag = seekAnchor; seekAnchor = null; scrollToHeader(header); setCurrentAnchor(tag); }
            else if (!eventPaging.done) { requestEventPage(mine); continue; }
            else seekAnchor = null;
          }
          // 한 쪽으로 화면이 안 차면 스크롤이 생길 때까지 이어서 부른다(관측 1회를 접어 두니 더 자주).
          if (!eventPaging.done && body.scrollHeight <= body.clientHeight + 4) requestEventPage(mine);
          continue;
        }
        groups.set(source.id, group);
        pending.delete(source.id);
        render(query);
      }
    } finally {
      slot.busy = false;
    }
  }

  function rowHtml(item, attr, subtitle) {
    return `<button type="button" class="fs-row" ${attr}>`
      + `<span class="fs-title">${esc(item.title)}</span>`
      + (subtitle ? `<span class="fs-sub">${esc(subtitle)}</span>` : '')
      + (item.meta ? `<span class="fs-meta">${esc(item.meta)}</span>` : '')
      + '</button>';
  }

  /** 이벤트 행: 본문은 태그 조합(줄바꿈해 전부 보인다). 이벤트 이름은 머리글이 맡으므로
   *  행에 다시 쓰지 않는다. `chip` 이 있으면(이웃 중 앵커와 다른 이벤트) 작은 칩으로 앞에 단다. */
  function eventRowHtml(item, attr, chip, extraClass = '') {
    return `<button type="button" class="fs-row fs-row-ev${extraClass}" ${attr}>`
      + '<span class="fs-ev-main">'
      + (chip ? `<span class="fs-ev-chip">${esc(chip)}</span>` : '')
      + `<span class="fs-sub">${esc(item.value)}</span></span>`
      + (item.meta ? `<span class="fs-meta">${esc(item.meta)}</span>` : '')
      + '</button>';
  }

  function moreHtml(key, scope, hidden, isOpen) {
    return `<button type="button" class="fs-more" data-fs-more="${esc(key)}" data-fs-more-scope="${scope}" aria-expanded="${isOpen}">`
      + `${isOpen ? '▾' : '▸'} 관측 1회 ${hidden}개 ${isOpen ? '접기' : '더보기'}</button>`;
  }

  /** 펼친 칸의 몸(두 절). 비어 있는 절은 안 그리고, 둘 다 비면 빈 문자열(머리만 남는다).
   *  관측 1회 행은 절마다 더보기로 접는다. 찾기 문구가 있으면 그것에 걸리는 행만, 접지 않고 전부. */
  function inlineBodyHtml() {
    inlineRows = [];
    if (!inline || inline.loading) return '<div class="fs-empty">이웃 조합을 찾는 중…</div>';
    if (!inline.payload || inline.payload.error) return '<div class="fs-empty">이웃 조합을 불러오지 못했습니다.</div>';
    const needle = String(inline.search || '').toLowerCase();
    const sections = [
      ['supersets', '전부 포함하는 더 긴 조합'],
      ['near', `핵심 태그(${inline.anchor}) 외 한 태그만 다른 조합`],
    ];
    const parts = [];
    for (const [key, label] of sections) {
      let items = Array.isArray(inline.payload[key]) ? inline.payload[key] : [];
      if (needle) items = items.filter(item => String(item.value || '').toLowerCase().includes(needle));
      if (!items.length) continue;
      const isOpen = !!needle || inline.more.has(key);
      const shown = isOpen ? items : items.filter(item => observed(item) !== 1);
      const hidden = items.length - shown.length;
      parts.push(`<div class="fs-cap">${esc(label)}<span class="fs-note">${items.length}</span></div>`);
      for (const item of shown) {
        const index = inlineRows.length;
        inlineRows.push(item);
        // 이벤트 이름은 앵커와 **다른** 이벤트 밑에 사는 조합에만 칩으로 단다.
        const foreign = item.anchor && item.anchor !== inline.anchor ? item.title : '';
        const isTarget = inline.target != null && String(item.value) === inline.target;
        parts.push(eventRowHtml(item, `data-fs-inline-index="${index}"`, foreign, isTarget ? ' is-active' : ''));
      }
      if (hidden || (isOpen && !needle && items.some(item => observed(item) === 1))) {
        parts.push(moreHtml(key, 'inline', isOpen ? items.filter(item => observed(item) === 1).length : hidden, isOpen));
      }
    }
    if (!parts.length && needle) return '<div class="fs-end">찾는 문구에 맞는 이웃 조합이 없습니다</div>';
    return parts.join('');
  }

  /** 펼친 칸 전체. 머리 = [선택한 조합] [프롬프트 복사] [찾기] [×]. 몸은 비어 있으면 아예 없다. */
  function inlineHtml() {
    const bodyHtml = inlineBodyHtml();
    return `<div class="fs-inline" data-fs-inline>`
      + '<div class="fs-inline-bar">'
      + '<span class="fs-inline-kicker">선택한 조합</span>'
      + '<button type="button" class="fs-inline-copy" data-fs-inline-copy title="선택한 조합(이웃 행을 눌렀으면 그것)을 클립보드로">프롬프트 복사</button>'
      + `<input class="fs-inline-search" type="search" data-fs-inline-search autocomplete="off" spellcheck="false" placeholder="이웃 조합에서 찾기" aria-label="이웃 조합에서 찾기" value="${esc(inline.search || '')}">`
      + '<button type="button" class="fs-close" data-fs-inline-close aria-label="펼침 닫기">×</button></div>'
      + (bodyHtml ? `<div class="fs-inline-body">${bodyHtml}</div>` : '')
      + '</div>';
  }

  /** 펼친 칸의 몸만 갈아 끼운다(찾기 입력 중 커서 보존). 몸이 없던 자리에 생기거나 사라지면 만들고 뗀다. */
  function paintInlineBody() {
    const panel = eventList.querySelector('[data-fs-inline]');
    if (!panel || !inline) return;
    const html = inlineBodyHtml();
    let bodyEl = panel.querySelector('.fs-inline-body');
    if (!html) { if (bodyEl) bodyEl.remove(); return; }
    if (!bodyEl) { bodyEl = document.createElement('div'); bodyEl.className = 'fs-inline-body'; panel.append(bodyEl); }
    bodyEl.innerHTML = html;
  }

  /** 몸통을 다시 그린다. 앞 갈래들은 `.fs-lanes` 에, 이벤트 목록은 `.fs-event-list` 에 -
   *  이벤트 구역 머리(조건 줄·칩)는 다시 만들지 않는다(입력 포커스 보존). */
  function render(query) {
    const selectedKey = rows[active]?._searchKey;
    const keepScroll = body.scrollTop;
    // 펼친 칸의 찾기 칸에 커서가 있으면 다시 그린 뒤 되돌린다(innerHTML 이 그것을 지운다).
    const searchEl = document.activeElement?.matches?.('[data-fs-inline-search]') ? document.activeElement : null;
    const caret = searchEl ? searchEl.selectionStart : null;
    rows = [];
    inlineRows = [];
    body.setAttribute('aria-busy', String(pending.size > 0));

    // ── 앞 갈래들 ──
    const parts = [];
    let lanePending = false;
    for (const source of SOURCES) {
      if (source.id === 'event' || !enabled.has(source.id)) continue;
      const group = groups.get(source.id) || {source: source.id, label: source.label, items: [],
        note: pending.has(source.id) ? '준비 및 검색 중…' : ''};
      if (pending.has(source.id)) lanePending = true;
      if (!group.items.length && !group.note) continue;
      parts.push(`<div class="fs-cap">${esc(group.label)}`
        + (group.note ? `<span class="fs-note">${esc(group.note)}</span>` : '')
        + '</div>');
      for (const item of group.items) {
        const index = rows.length;
        rows.push({...item, _source: group.source, _searchKey: `${group.source} ${item.value}`});
        parts.push(rowHtml(item, `data-fs-index="${index}"`, item.subtitle));
      }
      if (!group.items.length && !pending.has(source.id) && query) {
        // 갈래 머리만 남고 아래가 비면 "안 왔나?" 로 읽힌다 - 없다고 말한다.
        parts.push('<div class="fs-end">찾은 것이 없습니다</div>');
      }
    }
    const laneRows = rows.length;

    // ── 이벤트 구역 ──
    const showEvents = enabled.has('event');
    eventSection.hidden = !showEvents;
    if (showEvents) {
      const group = groups.get('event');
      const eventPending = pending.has('event');
      eventNote.textContent = group?.note || '';
      const eparts = [];
      let inlineShown = false;
      if (group && group.items.length) {
        // 묶음(앵커 연속 구간)마다: 관측 2 이상은 그대로, 관측 1회는 더보기로 접는다.
        const items = group.items;
        let i = 0;
        while (i < items.length) {
          if (i === eventPaging.deepStart) eparts.push('<div class="fs-cap fs-cap-sub">9–16태그 조합</div>');
          const anchor = items[i].anchor || items[i].title;
          const phase = eventPaging.deepStart >= 0 && i >= eventPaging.deepStart ? 'd' : 'b';
          let j = i;
          while (j < items.length && (items[j].anchor || items[j].title) === anchor
                 && !(j === eventPaging.deepStart && j !== i)) j += 1;
          const run = items.slice(i, j);
          const moreKey = `${phase}:${anchor}`;
          const isOpen = moreOpen.has(moreKey);
          const singles = run.filter(item => observed(item) === 1).length;
          eparts.push(`<div class="fs-cap fs-cap-ev" data-anchor="${esc(anchor)}">${esc(items[i].title)}</div>`);
          for (const item of run) {
            if (!isOpen && observed(item) === 1) continue;
            const index = rows.length;
            const key = `event ${item.value}`;
            rows.push({...item, _source: 'event', _searchKey: key});
            const expanded = inline && inline.key === key;
            eparts.push(eventRowHtml(item, `data-fs-index="${index}"`, '', expanded ? ' is-expanded' : ''));
            if (expanded) { eparts.push(inlineHtml()); inlineShown = true; }
          }
          if (singles) eparts.push(moreHtml(moreKey, 'list', singles, isOpen));
          i = j;
        }
        eparts.push(`<div class="fs-end">${eventPaging.done ? '이벤트 끝' : '아래로 내리면 더 불러옵니다…'}</div>`);
      } else if (eventPending) {
        eparts.push('<div class="fs-end">조합을 찾는 중…</div>');
      } else if (query) {
        eparts.push(`<div class="fs-end">${group && /실패/.test(group.note || '') ? esc(group.note) : '조건에 맞는 조합이 없습니다'}</div>`);
      }
      if (inline && !inlineShown) inline = null;   // 펼친 행이 목록에서 사라졌다(필터 변경·접힘 등)
      eventList.innerHTML = eparts.join('');
    } else if (inline) {
      inline = null;
    }

    // ── 빈 상태 ──
    if (!query) {
      parts.push('<div class="fs-empty">검색어를 입력하세요.</div>');
    } else if (!laneRows && !lanePending && !showEvents) {
      parts.push('<div class="fs-empty">찾은 것이 없습니다.</div>');
    }
    lanesEl.innerHTML = parts.join('');

    body.scrollTop = keepScroll;          // 이어 붙인 뒤 위로 튀지 않게
    countEl.textContent = pending.size ? `${rows.length} · 검색 중` : (rows.length ? `${rows.length}` : '');
    const previousIndex = selectedKey == null ? -1 : rows.findIndex(r => r._searchKey === selectedKey);
    active = previousIndex >= 0 ? previousIndex : (rows.length ? 0 : -1);
    // 다시 그릴 때는 스크롤을 건드리지 않는다. 키보드 이동(move)만 따라간다.
    paintActive(true);
    if (searchEl && inline) {
      const again = eventList.querySelector('[data-fs-inline-search]');
      if (again) { again.focus({preventScroll: true}); if (caret != null) again.setSelectionRange(caret, caret); }
    }
    fitHeight();                          // 이벤트 구역이 보일 만큼 상한을 맞춘다
    updateCurrentAnchor();
  }

  function paintActive(keepView = false) {
    const nodes = body.querySelectorAll('[data-fs-index]');
    nodes.forEach(node => node.classList.toggle('is-active',
      Number(node.dataset.fsIndex) === active));
    if (keepView) return;                 // 이어 붙이기일 땐 스크롤을 건드리지 않는다
    const node = body.querySelector(`[data-fs-index="${active}"]`);
    if (node) node.scrollIntoView({ block: 'nearest' });
  }

  function move(step) {
    if (!rows.length) return;
    active = (active + step + rows.length) % rows.length;
    paintActive();
    maybeLoadMoreEvents();
  }

  async function copyText(text) {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch { ok = false; }
    if (!ok) {
      // 클립보드 권한이 막힌 판이 실제로 있다 - 조용히 실패하지 않는다.
      try {
        const scratch = document.createElement('textarea');
        scratch.value = text;
        scratch.setAttribute('readonly', '');
        scratch.style.cssText = 'position:fixed;top:-1000px;opacity:0';
        document.body.append(scratch);
        scratch.select();
        ok = document.execCommand('copy');
        scratch.remove();
      } catch { ok = false; }
    }
    toast(ok ? `복사했습니다 — ${text.slice(0, 40)}` : '복사가 막혔습니다. 직접 선택해 Ctrl+C 하세요.',
      ok ? 'success' : 'error');
    return ok;
  }

  /** 행 고르기(클릭·Enter). 이벤트 행은 복사하지 않고 펼친다 - 복사는 펼친 칸의 버튼이 한다. */
  async function commit() {
    const item = rows[active];
    if (!item) return;
    const text = String(item.value || '');
    if (!text) return;
    if (item._source === 'event') { openInline(item); return; }
    await copyText(text);
  }

  // ── 인라인 이웃 조합 ────────────────────────────────────────────────────
  function openInline(item) {
    const anchor = String(item.anchor || String(item.title || '').split(' · ')[0] || '').trim();
    const tags = String(item.value || '').trim();
    if (!anchor || !tags) return;
    if (inline && inline.key === item._searchKey) return;     // 이미 펼쳐져 있다
    const mine = ++inlineSeq;
    inline = {key: item._searchKey, anchor, tags, payload: null, loading: true, seq: mine, search: '', target: null, more: new Set()};
    const query = input.value.trim();
    render(query);
    // 펼친 행이 펼친 칸과 함께 보이게 - 행을 몸통 위쪽으로 올린다.
    const row = body.querySelector(`[data-fs-index="${active}"]`);
    if (row) {
      const top = row.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop;
      body.scrollTop = Math.max(0, Math.round(top - 30));
      updateCurrentAnchor();
    }
    const {rating, person} = filterParams();
    const params = new URLSearchParams({tags, anchor, rating, person, limit: String(NEIGHBOR_LIMIT)});
    fetch(`/api/fast-search/event-neighbors?${params}`, {cache: 'no-store'})
      .then(response => { if (!response.ok) throw new Error('neighbors failed'); return response.json(); })
      .then(payload => { if (inline && inline.seq === mine) { inline.payload = payload; inline.loading = false; render(input.value.trim()); } })
      .catch(() => { if (inline && inline.seq === mine) { inline.payload = {error: true}; inline.loading = false; render(input.value.trim()); } });
  }

  /** [프롬프트 복사]: 이웃 행을 눌러 둔 것이 있으면 그것, 아니면 펼친 행 자신. */
  async function copyInlineTarget() {
    if (!inline) return;
    await copyText(inline.target || inline.tags);
  }

  function closeInline() {
    if (!inline) return;
    inline = null;
    inlineSeq += 1;
    render(input.value.trim());
    input.focus({preventScroll: true});
  }

  function onKeyDown(event) {
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.key === 'ArrowDown') { event.preventDefault(); move(1); return; }
    if (event.key === 'ArrowUp') { event.preventDefault(); move(-1); return; }
    if (event.key === 'Enter') { event.preventDefault(); void commit(); }
  }

  function show() {
    build();
    open = true;
    overlay.hidden = false;
    position();
    input.select();
    input.focus();
    schedule(0);
  }

  function close() {
    if (!overlay) return;
    open = false;
    overlay.hidden = true;                // CSS 의 .fs-overlay[hidden] 이 실제로 감춘다
    closePersonPopup();
    inline = null;
    inlineSeq += 1;
    seekAnchor = null;
    restoreScroll = null;
    clearTimeout(timer);
    clearTimeout(eventTimer);
    for (const slot of requests.values()) slot.wanted = null;
    rows = [];
    active = -1;
    pending.clear();
    seq += 1;                 // 도는 중인 요청의 결과를 버린다
  }

  // Ctrl+F. 브라우저에서는 기본 찾기 막대를 대신 가져오고(preventDefault),
  // Electron 에는 기본 동작이 없어 그대로 우리 것이 된다.
  // Esc 는 창 안 어디에 포커스가 있든 닫는다 - 행을 누른 뒤에도. 인원 팝업이 열려
  // 있으면 그것만 먼저 닫는다(전파를 끊어 입력 칸의 Esc 핸들러가 창까지 닫지 않게).
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      event.stopPropagation();
      if (personPopup && !personPopup.hidden) { closePersonPopup(); return; }
      close();
      return;
    }
    const hit = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key || '').toLowerCase() === 'f';
    if (!hit) return;
    event.preventDefault();
    if (open) { input.select(); input.focus(); return; }
    show();
  }, true);

  return { show, close, isOpen: () => open };
}
