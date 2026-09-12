/* Event Map — Ctrl+E 로 여는 **이벤트 추적** 창.
 *
 * 태그를 하나 꽂으면 그것과 **같은 게시물에 실제로 함께 달린** 태그가 lift 순으로 나온다.
 * 하나를 누르면 그것이 다음 핀이 되어 한 단계 깊이 들어가고(빵부스러기 줄에 쌓인다),
 * 부스러기를 누르거나 ← 로 언제든 앞 단계로 돌아온다(사용자 스케치 2026-09-12).
 *
 * 서버가 다 계산한다(`/api/event-map/*`). 여기서는 그리기·키·삽입·복사만 한다.
 *
 * ⚠️ Fast Search(Ctrl+F)와 계약이 다르다. 저쪽은 **클립보드 전용**이고, 이 창은
 *    **삽입과 복사 둘 다** 한다(사용자 지시 2026-09-11). 삽입은 Tag Search 와 같은
 *    `insertTagIntoPrompt` 를 빌려 커서 자리에 넣는다 - 프롬프트를 덮지 않는다.
 *
 * 실측이 정한 세 가지(2026-09-12, full-20260912 색인):
 *  1. **인원 태그(1girl·solo)는 핀이 아니라 분면 필터다.** 핀으로 꽂으면 `1girl+solo`
 *     교집합이 457만건이라 1초가 걸리고 후보는 lift 2~4 짜리 잡음이다. 같은 것을 분면
 *     `1girl_solo` 로 보내면 112ms 에 같은 답이 나온다. 그래서 프롬프트의 인원 태그는
 *     `/resolve` 가 `person_group` 으로 돌려주고, 여기서 인원 필터에 넣는다.
 *  2. **프롬프트를 통째로 심으면 무너진다.** 화면의 프롬프트 13개를 전부 핀으로 꽂으니
 *     1건이 남았다. 그래서 프롬프트의 태그는 **씨앗 칩**으로만 보이고, 사용자가 하나를
 *     골라야 첫 핀이 된다. 핀이 없으면 explore 를 부르지 않는다.
 *  3. 깊이 1부터는 200ms 남짓이고 lift 30~500 으로 뜻이 있다. 추적은 거기서부터다.
 *
 * 크기 규약은 Fast Search 와 같다(결과 칸 가운데, 폭 ≤ 720, 높이 ≤ 결과 칸의 절반).
 */

const DEBOUNCE_MS = 150;
const CANDIDATE_LIMIT = 40;
const SUGGEST_LIMIT = 12;
const SAMPLE_COUNT = 5;
const RATING_OPTIONS = [
  { id: 'g', label: 'G', title: 'General' },
  { id: 's', label: 'S', title: 'Sensitive' },
  { id: 'q', label: 'Q', title: 'Questionable' },
  { id: 'e', label: 'E', title: 'Explicit' },
];
// 인원 13분면. 묶음과 기본값은 Fast Search 와 같다(여성이 들어간 구성 전부).
const PERSON_GROUPS = [
  { g: '여성', ids: ['1girl_solo', '1girl', '2girls', 'multiple_girls'] },
  { g: '혼성', ids: ['1girl_1boy', '1girl_multiple_boys', '1boy_multiple_girls', 'multiple_girls_multiple_boys'] },
  { g: '남성', ids: ['1boy_solo', '1boy', '2boys', 'multiple_boys'] },
  { g: '기타', ids: ['other'] },
];
const PERSON_IDS = PERSON_GROUPS.flatMap(group => group.ids);
// 첫 시작 기본값(사용자 지정 2026-09-12): 여1 단독 · 여1 · 여1 남1 · 여1 남다수. 그 뒤로는
// 사용자가 바꾼 대로 브라우저에 기억한다(프롬프트의 인원 태그로 **덮어쓰지 않는다**).
// 기본 = 여1 단독 · S 등급(사용자 지정 2026-09-12 밤). 키를 v2 로 올려 기존 저장값 대신 이 기본이 한 번 먹는다.
const DEFAULT_PERSONS = ['1girl_solo'];
const DEFAULT_RATINGS = ['s'];
const PREF_KEY = 'naia_event_map_prefs_v2';

function loadPrefs() {
  try {
    const raw = JSON.parse(localStorage.getItem(PREF_KEY) || 'null');
    if (!raw || typeof raw !== 'object') return null;
    const persons = Array.isArray(raw.persons) ? raw.persons.filter(id => PERSON_IDS.includes(id)) : [];
    const ratings = Array.isArray(raw.ratings) ? raw.ratings.filter(id => RATING_OPTIONS.some(r => r.id === id)) : [];
    return { persons: persons.length ? persons : null, ratings: ratings.length ? ratings : null };
  } catch { return null; }
}
function savePrefs(persons, ratings) {
  try { localStorage.setItem(PREF_KEY, JSON.stringify({ persons: [...persons], ratings: [...ratings] })); } catch { /* 저장 못 해도 동작한다 */ }
}

export function initEventMap({ insertTag, showToast } = {}) {
  let overlay = null, input = null, statusEl = null, trailEl = null, bodyEl = null;
  let filtersEl = null, personBtn = null, personPopup = null, footEl = null, tabBtn = null;
  let sideEl = null;              // 실제 조합 둘째 패널
  let open = false, seq = 0, suggestSeq = 0, timer = null;
  let mapState = null;            // /state 응답. 열 때마다 새로 받는다(색인이 바뀔 수 있다).
  let personLabels = new Map();   // id -> 화면 문구 (서버가 준다)
  let pins = [], excludes = [];
  const prefs = loadPrefs();
  let ratings = new Set(prefs?.ratings || DEFAULT_RATINGS);
  let persons = new Set(prefs?.persons || DEFAULT_PERSONS);
  let roles = new Set();          // 대분류 필터(갈래 id). 비면 전부
  let group = '';                 // 첫 화면에서 고른 대분류(핀이 없을 때만 뜻이 있다)
  let browse = null;              // 마지막 browse 결과
  let result = null;              // 마지막 explore
  let suggest = null;             // 마지막 suggest (검색 칸에 글자가 있을 때만)
  let samples = null;             // 실제 조합
  // 프롬프트 엔지니어링 설정(Auto-Hide · Remove ...)이 지우는 태그 -> 라운드 이름. 후보와 실제 조합을
  // 진한 회색으로 칠하고, 넣기·복사에서 뺀다(사용자 지정 2026-09-12 밤). 매 결과마다 다시 묻는다 -
  // 패널을 열어 둔 채 설정을 바꿀 수 있다.
  let peHidden = new Map();
  let rows = [];                  // 키보드 이동 단위(지금 보이는 목록)
  let active = -1;
  let heightCaps = { base: 0, hard: 0 };

  const esc = value => String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const fmt = n => Number(n || 0).toLocaleString('en-US');
  const toast = (message, kind) => { if (typeof showToast === 'function') showToast(message, kind || 'info'); };

  // ── 프롬프트 -> 태그 목록 ────────────────────────────────────────────────
  /** 프롬프트 칸의 글을 태그로 쪼갠다. 가중치(`0.8::x ::`·`-0.25::y`)는 벗기고, `#주석` 줄과
   *  빈 조각은 버린다. 무엇이 맵에 있는지는 서버(`/resolve`)가 정한다. */
  // ── 서버 ─────────────────────────────────────────────────────────────────
  async function getJson(path, params) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params || {})) {
      if (value !== '' && value != null) query.set(key, String(value));
    }
    const res = await fetch(`${path}?${query.toString()}`, { cache: 'no-store' });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(body.message || res.statusText), { code: body.code, body });
    return body;
  }

  function filterParams() {
    return {
      ratings: ratings.size === RATING_OPTIONS.length ? '' : RATING_OPTIONS.map(r => r.id).filter(id => ratings.has(id)).join(','),
      persons: persons.size === PERSON_IDS.length ? '' : PERSON_IDS.filter(id => persons.has(id)).join(','),
      groups: roles.size ? [...roles].join(',') : '',
    };
  }

  async function loadState() {
    try {
      mapState = await getJson('/api/event-map/state', {});
    } catch (error) {
      mapState = { state: 'missing', message: String(error && error.message || error) };
    }
    personLabels = new Map((mapState.persons || []).map(p => [p.id, p.label]));
    return mapState;
  }

  /** 이 태그들 중 지금 PE 설정이 지우는 것을 서버에 묻는다. 실패하면 조용히 '아무것도 안 지움'. */
  async function loadPeHidden(tags) {
    const list = [...new Set((tags || []).filter(Boolean))].slice(0, 400);
    if (!list.length) { peHidden = new Map(); return; }
    try {
      const body = await getJson('/api/event-map/pe-filter', { tags: list.join(',') });
      peHidden = new Map(Object.entries(body.hidden || {}));
    } catch { peHidden = new Map(); }
  }
  const peTitle = tag => peHidden.has(tag) ? ` · 프롬프트 엔지니어링 설정(${peHidden.get(tag)})이 지웁니다` : '';

  async function loadBrowse() {
    const mine = ++seq;
    setStatus('찾는 중…', 'busy');
    try {
      const body = await getJson('/api/event-map/browse', { group, limit: CANDIDATE_LIMIT, ...filterParams(), groups: '' });
      if (mine !== seq) return;
      await loadPeHidden((body.candidates || []).map(c => c.tag));
      if (mine !== seq) return;
      browse = body;
    } catch (error) {
      if (mine !== seq) return;
      browse = { status: 'error', message: error.message, candidates: [] };
    }
    render();
  }

  async function explore() {
    samples = null;
    if (!pins.length) {
      result = null;
      if (group) { void loadBrowse(); return; }
      render(); return;
    }
    const mine = ++seq;
    setStatus('찾는 중…', 'busy');
    try {
      const body = await getJson('/api/event-map/explore', {
        pins: pins.join(','), exclude: excludes.join(','), limit: CANDIDATE_LIMIT, ...filterParams(),
      });
      if (mine !== seq) return;
      await loadPeHidden((body.candidates || []).map(c => c.tag));
      if (mine !== seq) return;
      result = body;
    } catch (error) {
      if (mine !== seq) return;
      result = { status: 'error', message: error.message, code: error.code, candidates: [] };
    }
    render();
  }

  function scheduleSuggest() {
    clearTimeout(timer);
    const q = input.value.trim();
    if (!q) { suggest = null; render(); return; }
    timer = setTimeout(async () => {
      const mine = ++suggestSeq;
      try {
        const body = await getJson('/api/event-map/suggest', { q, limit: SUGGEST_LIMIT });
        if (mine !== suggestSeq) return;
        suggest = body;
      } catch (error) {
        if (mine !== suggestSeq) return;
        suggest = { items: [], error: error.message };
      }
      render();
    }, DEBOUNCE_MS);
  }

  async function drawSamples() {
    if (!pins.length) return;
    const mine = ++seq;
    setStatus('실제 조합을 뽑는 중…', 'busy');
    try {
      const body = await getJson('/api/event-map/sample', {
        pins: pins.join(','), exclude: excludes.join(','), n: SAMPLE_COUNT,
        seed: Date.now() % 1000003, ...filterParams(),
      });
      if (mine !== seq) return;
      // 후보 목록의 회색도 유지해야 하니 후보 태그까지 같이 묻는다.
      const shown = (result?.candidates || browse?.candidates || []).map(c => c.tag);
      await loadPeHidden([...shown, ...(body.samples || []).flatMap(s => s.tags || [])]);
      if (mine !== seq) return;
      samples = body;
    } catch (error) {
      if (mine !== seq) return;
      samples = { status: 'error', message: error.message, samples: [] };
    }
    render();
  }

  // ── 상태 조작 ────────────────────────────────────────────────────────────
  function pin(tag) {
    const clean = String(tag || '').trim();
    if (!clean || pins.includes(clean)) return;
    const max = Number(mapState?.limits?.max_pins || 16);
    if (pins.length >= max) { toast(`핀은 ${max}개까지입니다.`, 'warning'); return; }
    pins.push(clean);
    excludes = excludes.filter(t => t !== clean);
    input.value = ''; suggest = null;
    void explore();
  }
  function exclude(tag) {
    const clean = String(tag || '').trim();
    if (!clean || excludes.includes(clean)) return;
    excludes.push(clean);
    pins = pins.filter(t => t !== clean);
    void explore();
  }
  function goTo(depth) {          // depth = 남길 핀 개수
    pins = pins.slice(0, Math.max(0, depth));
    void explore();
  }
  function goBack() {
    if (pins.length) { goTo(pins.length - 1); return; }
    if (group) { group = ''; browse = null; render(); }
  }
  function pickGroup(id) { group = id; browse = null; void loadBrowse(); }
  function clearExclude(tag) { excludes = excludes.filter(t => t !== tag); void explore(); }

  function currentPrompt() { return pins.join(', '); }
  /** 실제 조합 i 를 넣거나 복사할 문자열 - PE 설정이 지우는 태그는 뺀다(화면의 회색과 같은 것). */
  function samplePrompt(i) {
    const s = (samples?.samples || [])[i];
    if (!s) return '';
    const tags = s.tags || String(s.prompt || '').split(', ');
    return tags.filter(t => t && !peHidden.has(t)).join(', ');
  }
  function insertText(text) {
    const clean = String(text || '').trim();
    if (!clean) return;
    const ok = typeof insertTag === 'function' && insertTag(clean);
    toast(ok === false ? '프롬프트에 넣지 못했습니다.' : `프롬프트에 넣었습니다 — ${clean.slice(0, 40)}`,
      ok === false ? 'error' : 'success');
  }
  async function copyText(text) {
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch { ok = false; }
    if (!ok) {
      try {
        const scratch = document.createElement('textarea');
        scratch.value = text; scratch.setAttribute('readonly', '');
        scratch.style.cssText = 'position:fixed;top:-1000px;opacity:0';
        document.body.append(scratch); scratch.select();
        ok = document.execCommand('copy'); scratch.remove();
      } catch { ok = false; }
    }
    toast(ok ? `복사했습니다 — ${text.slice(0, 40)}` : '복사가 막혔습니다. 직접 선택해 Ctrl+C 하세요.',
      ok ? 'success' : 'error');
  }

  // ── 그리기 ───────────────────────────────────────────────────────────────
  function setStatus(text, kind, title) {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.title = title || '';
    statusEl.className = `em-status${kind ? ` is-${kind}` : ''}`;
  }

  function paintTrail() {
    const crumbs = pins.map((tag, i) =>
      `<span class="em-crumb${i === pins.length - 1 ? ' is-last' : ''}">`
      + `<button type="button" class="em-crumb-go" data-em-goto="${i + 1}" title="이 단계로 돌아가기">${esc(tag)}</button>`
      + `<button type="button" class="em-crumb-x" data-em-unpin="${esc(tag)}" aria-label="${esc(tag)} 빼기">×</button></span>`)
      .join('<span class="em-sep">›</span>');
    const ex = excludes.map(tag =>
      `<button type="button" class="em-ex" data-em-unexclude="${esc(tag)}" title="제외 풀기">− ${esc(tag)}</button>`).join('');
    const g = group ? groupInfo(group) : null;
    const groupCrumb = g ? `<span class="em-crumb em-crumb-group em-g-${esc(group)}"><button type="button" class="em-crumb-go" data-em-group-back
        title="이 대분류의 목록으로">${esc(g.label)}</button></span>${crumbs ? '<span class="em-sep">›</span>' : ''}` : '';
    trailEl.innerHTML = `
      <button type="button" class="em-back" data-em-back ${(pins.length || group) ? '' : 'disabled'} title="한 단계 위로 (Backspace)">←</button>
      <div class="em-crumbs">${groupCrumb}${crumbs || (group ? '' : '<span class="em-crumb-empty">대분류를 고르거나 태그를 찾아 시작합니다</span>')}${ex}</div>`;
    paintActions();
  }
  function groupInfo(id) { return (mapState?.groups || []).find(g => g.id === id) || null; }

  /** 동작 단추는 발줄 오른쪽에 산다 - 부스러기 줄에 두면 핀이 셋만 돼도 겹쳤다. */
  function paintActions() {
    if (!footEl) return;
    const on = pins.length > 0;
    footEl.querySelector('[data-em-insert]').disabled = !on;
    footEl.querySelector('[data-em-copy]').disabled = !on;
    const sb = overlay.querySelector('[data-em-samples]');   // 조건 줄 오른쪽에 산다(사용자 지정 2026-09-12 밤)
    if (sb) { sb.disabled = !on; sb.classList.toggle('is-on', !!samples); }
  }

  function paintFilters() {
    filtersEl.innerHTML = `
      <button type="button" class="em-person-btn" data-em-person aria-haspopup="dialog" aria-expanded="false"
              title="인원 구성 고르기">인원 <b data-em-person-count></b></button>
      <span class="em-rating-bar" role="group" aria-label="등급">${RATING_OPTIONS.map(r =>
        `<button type="button" class="em-rating-btn${ratings.has(r.id) ? ' active' : ''}" data-em-r="${r.id}"
                 aria-pressed="${ratings.has(r.id)}" title="${r.title}">${r.label}</button>`).join('')}</span>
      <span class="em-actions em-actions-right"><button type="button" data-em-samples disabled
              title="핀을 전부 포함하는 실제 게시물의 조합">실제 조합</button></span>`;
    personBtn = filtersEl.querySelector('[data-em-person]');
    paintPersonButton();
    paintActions();
  }

  /** 카테고리 탭 줄. 서버가 준 갈래별 후보 수로 그린다(접힌 팝업 대신 - 사용자 지정 2026-09-12).
   *  핀이 있으면 탭 = 후보 필터, 대분류 목록이면 탭 = 대분류 바꾸기. */
  function catsHtml(counts, activeId, total) {
    // 갈래는 **항상 전부** 그린다(핀을 고른 뒤에도 - 사용자 지정 2026-09-12). counts 는 있으면 얹는다;
    // 없으면(옛 백엔드) 수 없이 그리고, 0 인 갈래는 흐리게 두고 못 누른다.
    const groups = (mapState?.groups || []).filter(g => g.id !== 'unsorted' && g.tags > 0);
    if (!groups.length) return '';
    const byId = counts ? new Map(counts.map(r => [r.id, r.count])) : null;
    const tab = (id, label, n, on) => {
      const empty = byId != null && id && !n;
      return `<button type="button" class="em-cat em-g-${esc(id)}${on ? ' is-on' : ''}${empty ? ' is-empty' : ''}" data-em-cat="${esc(id)}"
        ${empty ? 'disabled' : ''} title="${esc(label)}${n != null ? ' · ' + fmt(n) : ''}"><span class="em-tag">${esc(label)}</span>${n != null ? `<span class="em-cat-n">${fmt(n)}</span>` : ''}</button>`;
    };
    return `<div class="em-cats" role="tablist">${total != null ? tab('', '전체', total, !activeId) : ''}${groups.map(g => tab(g.id, g.label, byId ? (byId.get(g.id) || 0) : null, g.id === activeId)).join('')}</div>`;
  }

  /** 접기 표의 대분류 12개(서버가 준다). 첫 화면 축(depth1)과 나머지로 묶는다. */
  function roleOptions() {
    const all = (mapState?.groups || []).filter(g => g.tags > 0);
    return [{ g: '축', items: all.filter(g => g.depth1) }, { g: '함께 오는 것', items: all.filter(g => !g.depth1) }]
      .filter(x => x.items.length);
  }

  function paintPersonButton() {
    if (!personBtn) return;
    const count = personBtn.querySelector('[data-em-person-count]');
    const all = persons.size === PERSON_IDS.length;
    if (persons.size === 1) count.textContent = personLabels.get([...persons][0]) || [...persons][0];
    else count.textContent = all ? '전체' : `${persons.size}/${PERSON_IDS.length}`;
    personBtn.classList.toggle('is-filtered', !all);
  }

  function candidateRow(c, i) {
    const lift = Number(c.lift || 0);
    const liftText = lift >= 100 ? `×${Math.round(lift)}` : `×${lift.toFixed(lift >= 10 ? 0 : 1)}`;
    const obs = c.observed_estimate != null && c.observed_estimate !== c.observed
      ? `≈${fmt(c.observed_estimate)}` : fmt(c.observed);
    const hid = peHidden.has(c.tag);
    return `<div class="em-row em-g-${esc(c.group || 'unsorted')}${i === active ? ' is-active' : ''}${hid ? ' is-pe-hidden' : ''}" data-em-row="${i}" data-em-pin="${esc(c.tag)}" role="option">
      <span class="em-tag" title="${esc(roleLabel(c.group || 'unsorted'))}${esc(peTitle(c.tag))}">${esc(c.tag)}</span>
      <span class="em-lift" title="핀이 있을 때 이 태그가 나올 확률이 평소의 몇 배인가">${liftText}</span>
      <span class="em-obs" title="핀과 같은 게시물에 함께 달린 수">${obs}</span>
      <button type="button" class="em-row-x" data-em-exclude="${esc(c.tag)}" title="이 태그가 없는 게시물만">−</button>
    </div>`;
  }
  function roleLabel(id) {
    const found = (mapState?.groups || []).find(g => g.id === id);
    return found ? found.label : id;
  }

  function suggestHtml() {
    if (!suggest) return '';
    const items = suggest.items || [];
    if (!items.length) return `<div class="em-empty">${esc(suggest.error || '맞는 태그가 없습니다')}</div>`;
    let k = 0;
    return `<div class="em-cap">검색${suggest.translated?.length ? `<span class="em-note">한글 → ${esc(suggest.translated.slice(0, 3).join(', '))}</span>` : ''}</div>
      ${items.map(it => {
        const usable = !it.blocked && !pins.includes(it.tag);
        const i = usable ? k++ : -1;
        return `<div class="em-row em-g-${esc(it.group || 'unsorted')}${usable ? '' : ' is-off'}${i === active ? ' is-active' : ''}" ${usable ? `data-em-row="${i}" data-em-pin="${esc(it.tag)}"` : ''} role="option">
          <span class="em-tag" title="${esc(roleLabel(it.group || 'unsorted'))}">${esc(it.tag)}</span>
          <span class="em-obs">${fmt(it.observed)}</span>${it.blocked ? `<span class="em-blocked">${esc(it.blocked)}</span>` : ''}
        </div>`;
      }).join('')}`;
  }

  /** 첫 화면의 대분류 단추. 축(depth1) 넷이 크게, 나머지는 작게. 태그 수 0 이면 흐리게. */
  function groupsHtml() {
    const all = mapState?.groups || [];
    if (!all.length) return `<div class="em-empty">대분류 표가 없습니다 (KR_tags.parquet 를 못 찾음)</div>`;
    const btn = g => `<button type="button" class="em-group em-g-${esc(g.id)}" data-em-group="${esc(g.id)}"
        ${g.tags ? '' : 'disabled'} title="태그 ${fmt(g.tags)} · 관측 ${fmt(g.observed)}">
        <span class="em-group-label">${esc(g.label)}</span><span class="em-group-n">${fmt(g.tags)}</span></button>`;
    return `<div class="em-cap">대분류 <span class="em-note">고른 인원·등급에서 특징적인 태그를 봅니다</span></div>
      <div class="em-groups">${all.filter(g => g.depth1).map(btn).join('')}</div>
      <div class="em-cap em-cap-sub">함께 오는 것</div>
      <div class="em-groups em-groups-rest">${all.filter(g => !g.depth1 && g.id !== 'unsorted').map(btn).join('')}</div>`;
  }

  /** 대분류를 고른 뒤: 그 분면에서 특징적인 태그. 행을 누르면 첫 핀이 된다. */
  function browseHtml() {
    if (!browse) return '';
    if (browse.status === 'error') { setStatus('오류', 'error'); return `<div class="em-empty">${esc(browse.message || '실패')}</div>`; }
    const cs = browse.candidates || [];
    rows = cs.map(c => c.tag);
    setStatus(`${fmt(browse.observed_posts)}건${browse.sampled ? ' · 표본' : ''}`, 'ok',
      `${Math.round(browse.elapsed_ms || 0)}ms · 이 분면에서의 비율 ÷ 코퍼스 전체에서의 비율`);
    const tabs = (mapState?.groups || []).filter(g => g.tags > 0 && g.id !== 'unsorted').map(g => ({ id: g.id, count: g.tags }));
    return catsHtml(tabs, group, null)
      + `<div class="em-cap">${esc(roleLabel(group))} <span class="em-note">이 인원·등급에서 특징적인 순 · ${cs.length}개</span></div>`
      + (cs.length ? cs.map(candidateRow).join('') : `<div class="em-empty">이 분면에서 5건 이상인 태그가 없습니다.</div>`);
  }

  /** 실제 조합은 본문 아래가 아니라 **오른쪽 둘째 패널**에 그린다(사용자 지정 2026-09-12) -
   *  아래에 붙이면 후보 목록을 지나 스크롤해야 보였다. 창을 닫거나 핀이 바뀌면 같이 사라진다. */
  function paintSide() {
    if (!sideEl) return;
    if (!samples || !open) { sideEl.hidden = true; sideEl.innerHTML = ''; return; }
    const list = samples.samples || [];
    sideEl.hidden = false;
    sideEl.innerHTML = `<div class="em-bar em-side-bar">
        <span class="em-side-title">실제 조합</span>
        <span class="em-status">${samples.status === 'error' ? esc(samples.message) : `${fmt(samples.observed_posts)}건 중 ${list.length}개`}</span>
        <button type="button" class="em-mini" data-em-samples-again title="다시 뽑기">↻</button>
        <button type="button" class="em-close" data-em-side-close aria-label="닫기">×</button>
      </div>
      <div class="em-side-note">핀을 전부 포함하는 게시물 하나에 <b>실제로 함께 달린</b> 태그입니다. 이어 붙인 것이 아닙니다.${
        peHidden.size ? ' <span class="em-pe-hidden">회색</span>은 프롬프트 엔지니어링 설정이 지우는 태그 - 넣기·복사에서 빠집니다.' : ''}</div>
      <div class="em-body em-side-body">${list.map((s, i) => `
        <div class="em-sample">
          <div class="em-sample-tags">${(s.tags || String(s.prompt || '').split(', ')).map(t =>
            peHidden.has(t) ? `<span class="em-pe-hidden" title="${esc(peTitle(t).slice(3))}">${esc(t)}</span>` : esc(t)).join(', ')}</div>
          <div class="em-sample-actions">
            <span class="em-note">${esc(String(s.partition || '').replace(/_/g, ' '))}</span>
            <button type="button" data-em-sample-insert="${i}">넣기</button>
            <button type="button" data-em-sample-copy="${i}">복사</button>
          </div>
        </div>`).join('') || '<div class="em-empty">조합이 없습니다</div>'}</div>`;
    positionSide();
  }
  function positionSide() {
    if (!sideEl || sideEl.hidden || !overlay) return;
    const r = overlay.getBoundingClientRect();
    const width = Math.round(Math.min(360, Math.max(240, window.innerWidth - r.right - 24)));
    sideEl.style.left = `${Math.round(r.right + 8)}px`;
    sideEl.style.top = `${Math.round(r.top)}px`;
    sideEl.style.width = `${width}px`;
    sideEl.style.height = `${Math.round(r.height)}px`;
  }

  function render() {
    if (!overlay) return;
    paintTrail();
    paintFilters();
    rows = [];
    let html = '';
    if (!mapState || mapState.state !== 'ready') {
      const searched = (mapState?.searched || []).map(p => `<li>${esc(p)}</li>`).join('');
      html = `<div class="em-missing"><b>이벤트 맵 색인이 없습니다.</b>
        <div>${esc(mapState?.message || '')}</div>
        ${searched ? `<div class="em-note">찾아본 곳</div><ul>${searched}</ul>` : ''}
        <div class="em-note">색인은 <code>tools/build_event_map_index.py</code> 로 만들고
        <code>&lt;user-data&gt;/data/event_map/event_map.naiamap</code> 에 둡니다.</div></div>`;
      bodyEl.innerHTML = html;
      setStatus('미설치', 'error');
      return;
    }
    if (input.value.trim()) {
      html += suggestHtml();
      rows = (suggest?.items || []).filter(it => !it.blocked && !pins.includes(it.tag)).map(it => it.tag);
    } else if (!pins.length && group) {
      html += browseHtml();
    } else if (!pins.length) {
      html += groupsHtml();
      setStatus(`태그 ${fmt(mapState.tags)} · 게시물 ${fmt(mapState.posts)}`);
    } else if (result) {
      if (result.status === 'error') {
        html += `<div class="em-empty">${esc(result.message || '실패')}</div>`;
        setStatus('오류', 'error');
      } else if (result.status === 'unknown_tag') {
        html += `<div class="em-empty">맵에 없는 태그: ${esc((result.unknown_pins || []).join(', '))}</div>`;
        setStatus('모르는 태그', 'error');
      } else if (!result.observed_posts) {
        html += `<div class="em-empty">이 조합으로 달린 게시물이 없습니다. ← 로 한 단계 올라가 보세요.</div>`;
        setStatus('0건', 'error');
      } else {
        const cs = result.candidates || [];
        rows = cs.map(c => c.tag);
        const gc = result.group_counts || null;   // 옛 백엔드(재시작 전)는 이 키가 없다 - 그래도 탭은 그린다
        html += catsHtml(gc, roles.size ? [...roles][0] : '', gc ? gc.reduce((n, r) => n + r.count, 0) : null);
        html += `<div class="em-cap">함께 달린 태그 <span class="em-note">lift 순 · ${cs.length}개${result.sampled ? ' · 표본으로 셈' : ''}</span></div>`;
        html += cs.length ? cs.map(candidateRow).join('') : `<div class="em-empty">5건 이상 함께 달린 태그가 없습니다.</div>`;
        setStatus(`${fmt(result.observed_posts)}건${result.sampled ? ' · 표본' : ''}`, 'ok',
          `${Math.round(result.elapsed_ms || 0)}ms${result.sampled ? ' · 교집합이 커서 표본으로 셌다(건수는 정확하다)' : ''}`);
      }
    }
    bodyEl.innerHTML = html;
    paintSide();
    if (active >= rows.length) active = rows.length - 1;
    paintActive();
    fitHeight();
  }

  function paintActive() {
    bodyEl.querySelectorAll('[data-em-row]').forEach(el => {
      el.classList.toggle('is-active', Number(el.dataset.emRow) === active);
    });
    const el = bodyEl.querySelector(`[data-em-row="${active}"]`);
    if (el) el.scrollIntoView({ block: 'nearest' });
  }

  // ── 인원 팝업 (Fast Search 와 같은 체크 목록) ────────────────────────────
  function ensurePersonPopup() {
    if (personPopup) return personPopup;
    personPopup = document.createElement('div');
    personPopup.className = 'em-person-popup';
    personPopup.hidden = true;
    personPopup.setAttribute('role', 'dialog');
    document.body.append(personPopup);
    personPopup.addEventListener('click', event => {
      const quick = event.target.closest('[data-em-quick]');
      if (quick) {
        const which = quick.dataset.emQuick;
        if (which === 'all') persons = new Set(PERSON_IDS);
        else if (which === 'default') persons = new Set(DEFAULT_PERSONS);
        else { const g = PERSON_GROUPS.find(x => x.g === which); if (g) persons = new Set(g.ids); }
      } else {
        const row = event.target.closest('[data-em-person-id]');
        if (!row) return;
        const id = row.dataset.emPersonId;
        if (persons.has(id)) { if (persons.size > 1) persons.delete(id); } else persons.add(id);
      }
      personPopup.innerHTML = personPopupHtml();
      paintPersonButton();
      savePrefs(persons, ratings);
      void explore();
    });
    return personPopup;
  }
  function personPopupHtml() {
    return `<div class="em-person-head"><span>인원 구성</span><span class="em-person-quick">
        <button type="button" data-em-quick="default">기본</button><button type="button" data-em-quick="all">전체</button>
        ${PERSON_GROUPS.map(g => `<button type="button" data-em-quick="${esc(g.g)}">${esc(g.g)}</button>`).join('')}</span></div>
      <div class="em-person-list">${PERSON_GROUPS.map(g => `<div class="em-person-group">${esc(g.g)}</div>`
        + g.ids.map(id => `<button type="button" class="em-person-row${persons.has(id) ? ' is-on' : ''}" data-em-person-id="${esc(id)}">
            <span class="em-person-check">${persons.has(id) ? '✓' : ''}</span><span>${esc(personLabels.get(id) || id.replace(/_/g, ' '))}</span></button>`).join('')).join('')}</div>`;
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
    personPopup.hidden = true; personPopup.innerHTML = '';
    if (personBtn) personBtn.setAttribute('aria-expanded', 'false');
    document.removeEventListener('pointerdown', onPersonOutside, true);
  }
  function onPersonOutside(event) {
    if (personPopup && personPopup.contains(event.target)) return;
    if (event.target.closest?.('[data-em-person]')) return;
    closePersonPopup();
  }


  // ── 창 ───────────────────────────────────────────────────────────────────
  function build() {
    if (overlay) return overlay;
    overlay = document.createElement('div');
    overlay.className = 'em-overlay';
    overlay.hidden = true;
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', '이벤트 맵');
    overlay.innerHTML = `
      <div class="em-bar">
        <span class="em-icon" aria-hidden="true">E</span>
        <input class="em-input" type="search" autocomplete="off" spellcheck="false"
               aria-label="태그 찾기" placeholder="태그 찾기…">
        <span class="em-status" role="status" aria-live="polite"></span>
        <button type="button" class="em-close" aria-label="닫기">×</button>
      </div>
      <div class="em-trail"></div>
      <div class="em-filters"></div>
      <div class="em-body" role="listbox"></div>
      <div class="em-foot">
        <span class="em-keys" title="↑↓ 이동 · Enter 꽂기 · − 제외 · Backspace 한 단계 위로 · 우클릭 제외 · Esc 닫기"><b>Enter</b> 꽂기 · <b>−</b> 제외 · <b>⌫</b> 위로</span>
        <span class="em-actions">
          <button type="button" data-em-insert disabled title="핀 전부를 프롬프트 커서 자리에">넣기</button>
          <button type="button" data-em-copy disabled title="핀 전부를 클립보드로">복사</button>
        </span>
      </div>`;
    document.body.append(overlay);
    input = overlay.querySelector('.em-input');
    statusEl = overlay.querySelector('.em-status');
    trailEl = overlay.querySelector('.em-trail');
    filtersEl = overlay.querySelector('.em-filters');
    bodyEl = overlay.querySelector('.em-body');
    footEl = overlay.querySelector('.em-foot');

    overlay.querySelector('.em-close').addEventListener('click', close);
    input.addEventListener('input', () => { active = -1; scheduleSuggest(); });
    input.addEventListener('keydown', onKeyDown);

    trailEl.addEventListener('click', event => {
      const t = event.target;
      const goto = t.closest('[data-em-goto]');
      if (goto) { goTo(Number(goto.dataset.emGoto)); return; }
      const unpin = t.closest('[data-em-unpin]');
      if (unpin) { pins = pins.filter(x => x !== unpin.dataset.emUnpin); void explore(); return; }
      const unex = t.closest('[data-em-unexclude]');
      if (unex) { clearExclude(unex.dataset.emUnexclude); return; }
      if (t.closest('[data-em-group-back]')) { pins = []; excludes = []; browse = null; void loadBrowse(); return; }
      if (t.closest('[data-em-back]')) { goBack(); return; }
    });
    footEl.addEventListener('click', event => {
      const t = event.target;
      if (t.closest('[data-em-insert]')) { insertText(currentPrompt()); return; }
      if (t.closest('[data-em-copy]')) { void copyText(currentPrompt()); return; }
    });
    filtersEl.addEventListener('click', event => {
      const t = event.target;
      if (t.closest('[data-em-samples]')) { if (samples) { samples = null; render(); } else void drawSamples(); return; }
      if (t.closest('[data-em-person]')) {
        if (personPopup && !personPopup.hidden) closePersonPopup(); else openPersonPopup();
        return;
      }

      const pill = t.closest('[data-em-r]');
      if (pill) {
        const id = pill.dataset.emR;
        if (ratings.has(id) && ratings.size === 1) return;      // 최소 하나는 남긴다
        if (ratings.has(id)) ratings.delete(id); else ratings.add(id);
        savePrefs(persons, ratings);
        void explore(); return;
      }
    });
    bodyEl.addEventListener('click', event => {
      const t = event.target;
      const ex = t.closest('[data-em-exclude]');
      if (ex) { event.stopPropagation(); exclude(ex.dataset.emExclude); return; }
      const again = t.closest('[data-em-samples-again]');
      if (again) { void drawSamples(); return; }
      const si = t.closest('[data-em-sample-insert]');
      if (si) { insertText(samplePrompt(Number(si.dataset.emSampleInsert))); return; }
      const sc = t.closest('[data-em-sample-copy]');
      if (sc) { void copyText(samplePrompt(Number(sc.dataset.emSampleCopy))); return; }
      const gb = t.closest('[data-em-group]');
      if (gb) { pickGroup(gb.dataset.emGroup); return; }
      const cat = t.closest('[data-em-cat]');
      if (cat) {
        const id = cat.dataset.emCat;
        if (pins.length) { roles = id ? new Set([id]) : new Set(); void explore(); }
        else if (id) pickGroup(id);
        return;
      }
      const row = t.closest('[data-em-pin]');
      if (row) pin(row.dataset.emPin);
    });
    // 우클릭 = 제외(시험대와 같은 손버릇).
    bodyEl.addEventListener('contextmenu', event => {
      const row = event.target.closest('[data-em-pin]');
      if (!row) return;
      event.preventDefault();
      exclude(row.dataset.emPin);
    });
    bodyEl.addEventListener('mousedown', event => {
      // 행을 눌러도 포커스는 검색 칸에 남긴다(키보드가 계속 먹게).
      if (event.target.closest('button, input')) return;
      event.preventDefault();
    });
    window.addEventListener('resize', position);
    // Generation Info 를 끌어 키우면 뷰어가 줄어든다 - 창 크기가 아니라 뷰어 크기를 따라간다.
    const viewer = document.querySelector('#resultViewer');
    if (viewer && typeof ResizeObserver === 'function') new ResizeObserver(() => position()).observe(viewer);

    sideEl = document.createElement('div');
    sideEl.className = 'em-overlay em-side';
    sideEl.hidden = true;
    sideEl.setAttribute('role', 'dialog');
    sideEl.setAttribute('aria-label', '실제 조합');
    document.body.append(sideEl);
    sideEl.addEventListener('click', event => {
      const t = event.target;
      if (t.closest('[data-em-side-close]')) { samples = null; render(); return; }
      if (t.closest('[data-em-samples-again]')) { void drawSamples(); return; }
      const si = t.closest('[data-em-sample-insert]');
      if (si) { insertText(samplePrompt(Number(si.dataset.emSampleInsert))); return; }
      const sc = t.closest('[data-em-sample-copy]');
      if (sc) { void copyText(samplePrompt(Number(sc.dataset.emSampleCopy))); }
    });
    return overlay;
  }

  function onKeyDown(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!rows.length) return;
      event.preventDefault();
      active = event.key === 'ArrowDown' ? Math.min(rows.length - 1, active + 1) : Math.max(0, active - 1);
      paintActive();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (!rows.length) return;
      pin(rows[active >= 0 ? active : 0]);
      return;
    }
    if (event.key === '-' && rows.length && active >= 0) {
      event.preventDefault();
      exclude(rows[active]);
      return;
    }
    if (event.key === 'Backspace' && !input.value) {
      event.preventDefault();
      goBack();
    }
  }

  /** 결과 칸의 **왼쪽**에 붙는다(사용자 지정 2026-09-12): 폭은 Fast Search 의 절반(≤ 360),
   *  높이는 빈 화면이면 결과 칸의 절반, 목록이 길면 결과 칸 높이까지 자란다(한 번에 보이는 태그를
   *  늘리자는 사용자 지정 2026-09-12). 이미지 왼편 가장자리를 살짝 가리는 정도. */
  function position() {
    if (!overlay || overlay.hidden) return;
    // 뷰어(이미지 칸)만 호스트다 - #rightTabResult 로 재면 Generation Info 위까지 내려간다(사용자 제보).
    const host = document.querySelector('#resultViewer') || document.querySelector('#rightTabResult') || document.querySelector('.app-layout');
    const r = host ? host.getBoundingClientRect() : null;
    if (!r || r.width < 240 || r.height < 160) {
      overlay.style.left = '16px'; overlay.style.transform = 'none'; overlay.style.top = '64px';
      overlay.style.width = 'min(360px, calc(100vw - 32px))';
      heightCaps = { base: Math.min(440, window.innerHeight - 96), hard: window.innerHeight - 32 };
      fitHeight(); return;
    }
    const pad = 14;
    // E 단추(반구, 24px)가 왼쪽 가장자리에 있으니 그 오른쪽부터 시작한다.
    const width = Math.round(Math.min(360, Math.max(240, (r.width - pad * 2) / 2)));
    overlay.style.transform = 'none';
    overlay.style.left = `${Math.round(r.left + pad + 20)}px`;
    overlay.style.top = `${Math.round(r.top + pad)}px`;
    overlay.style.width = `${width}px`;
    heightCaps = { base: Math.round(Math.min(r.height - pad * 2, Math.max(280, r.height * 0.5))),
                   hard: Math.round(r.height - pad * 2) };
    fitHeight();
  }
  function fitHeight() {
    if (!overlay || overlay.hidden || !heightCaps.base) return;
    // 몸통이 내용만큼 자란다(hard 를 넘지 않게). 8줄 상한은 걷어냈다 - 사용자가 더 보고 싶어했다.
    let want = heightCaps.base;
    const chrome = overlay.offsetHeight - bodyEl.clientHeight;
    want = Math.max(want, Math.ceil(chrome + bodyEl.scrollHeight + 4));
    overlay.style.maxHeight = `${Math.round(Math.min(heightCaps.hard, want))}px`;
    positionSide();
  }

  async function show() {
    build();
    overlay.hidden = false;
    open = true;
    if (tabBtn) tabBtn.setAttribute('aria-pressed', 'true');
    position();
    setStatus('여는 중…', 'busy');
    await loadState();
    render();
    if (pins.length) void explore();
    position();
    input.focus();
  }
  function close() {
    if (!overlay) return;
    closePersonPopup();
    overlay.hidden = true;
    open = false;
    if (sideEl) { sideEl.hidden = true; sideEl.innerHTML = ''; }
    if (tabBtn) tabBtn.setAttribute('aria-pressed', 'false');
    clearTimeout(timer);
    seq += 1; suggestSeq += 1;
  }
  function toggle() { if (open) close(); else void show(); }

  // 프롬프트 옆의 작은 E 단추(index.html 의 #eventMapTab). 없어도 Ctrl+E 는 된다.
  tabBtn = document.getElementById('eventMapTab');
  if (tabBtn) tabBtn.addEventListener('click', toggle);

  // Ctrl+E. 브라우저의 기본 동작(주소창 검색)은 막는다. Esc 는 어디에 포커스가 있든 닫되,
  // 인원 팝업이 열려 있으면 그것만 먼저 닫는다.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && open) {
      event.preventDefault(); event.stopPropagation();
      if (personPopup && !personPopup.hidden) { closePersonPopup(); return; }
      close(); return;
    }
    const hit = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && String(event.key || '').toLowerCase() === 'e';
    if (!hit) return;
    event.preventDefault();
    if (open) { input.select(); input.focus(); return; }
    void show();
  }, true);

  return { show, close, toggle, isOpen: () => open, pins: () => pins.slice() };
}
