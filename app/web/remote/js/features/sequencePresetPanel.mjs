// Sequence 패널 — 검증된 실제 이벤트 그룹을 태그 검색으로 서빙 (Dev0714 EventSearcher 모델).
// 검색바를 영속화(input autocomplete/포커스 보존) 하고 결과 영역만 갱신한다. 수위·컷 칩은
// 검색 버튼 없이 즉시 반영. 포함/제외 입력에 tagAssist(태그 자동완성) 바인딩.
// 좌측 #tabSequence 상주. 생성은 표준 PE 경유 — Storyteller 비커플링.
// 2026-10-18(사용자): 항목을 누르면 고른다 - 메인 Generate = 고른 이야기(`#id Generate`). ★ = 즐겨찾기(서버 파일) ·
// [★ 즐겨찾기 N] 칩 = 목록을 즐겨찾기로. 목록 아래 '방금 생성' 칸 = 마지막으로 생성한 이야기 하나(SEQ Random 이 고른 것을
// 다시 찾을 수 있게 · Auto Gen 의 다음 라운드도 따라간다 · 서버를 다시 켜면 비어 있다). [노말 | 라지 (유료)] = 만화 크기.

async function readJsonResponse(response) {
  let data = null;
  try { data = await response.json(); } catch (_) { data = null; }
  if (!response.ok) throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
  return data || {};
}
function postJson(url, payload) {
  return fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload || {}), cache: 'no-store'}).then(readJsonResponse);
}
function getJson(url) { return fetch(url, {cache: 'no-store'}).then(readJsonResponse); }

const STAGE_LABELS = {
  baseline_presentation: '일상', tease_exposure: '노출', solo_stimulation: '솔로',
  partnered_contact: '접촉', oral_manual: '오럴', penetration: '삽입',
  release: '절정', aftermath: '여운',
};
const RATING_LABELS = {g: 'G', s: 'S', q: 'Q', e: 'E'};
const ALL_RATINGS = ['e', 'q', 's', 'g'];
// 2~4컷만(사용자 2026-10-18 - 5 · 6컷은 모델이 받는지 검증되지 않았다. 백엔드도 데이터를 읽을 때 뺀다).
const CUTS = [2, 3, 4];
// [노말 | 라지 (유료)] 는 숨겼다(사용자 2026-10-18 - "NAI 가 아직 감당하지 못한다"). 서버도 라지를 받지 않는다
// (sequence_preset_routes.LARGE_SIZE_ENABLED) - 되살릴 때 둘을 함께 켠다.
const LARGE_SIZE_ENABLED = false;

export function createSequencePresetPanel({panel, escHtml, showToast, bindTagAssist, getApiMode, onSelectionChange,
  beforeGenerate, onSizeChange}) {
  const state = {
    available: null,        // null=미확인
    presentRatings: [],
    groupCount: 0,
    // G · S 이야기는 백엔드가 뺀다(사용자 2026-10-18) - 수위 칩은 Q · E 만 남고 기본은 Q.
    query: {include: '1girl', exclude: '', ratings: new Set(['q']), cuts: new Set()},
    results: null,
    detail: null,
    openGroupId: null,      // 미리보기 툴팁에 떠 있는 그룹
    // 하단 '고정' 토글은 숨기고 강제 해제(사용자 2026-10-18). 백엔드도 요청 값을 받지 않는다.
    fixSeed: false,
    fixResolution: false,
    useVibe: false,
    previews: new Map(),    // groupId -> /sequence 응답(미리보기 툴팁 캐시)
    busy: false,
    selected: null,         // 고른 이야기의 카드 요약 {groupId, peakRating, frameCount, stages, preview} - 메인 Generate 가 이것
    recent: null,           // 아래 칸의 카드 요약(방금 생성 · 히스토리에서 고른 그림의 이야기)
    boxLabel: '방금 생성',
    recentId: 0,            // 마지막으로 생성한 그룹 번호(요약을 받기 전에도 같은 번호를 두 번 묻지 않게)
    pendingBox: null,       // 패널이 뜨기 전에 온 칸 {gid, label}
    runSeen: {runId: '', round: 0},   // 런 상태로 본 가장 새 라운드 - 늦게 온 첫 라운드 HTTP 답이 칸을 되돌리지 않게
    runActive: false,       // Auto Gen 연속 런이 도는 중(런 상태) - 칩 · 검색을 바꾸면 그 런의 다음 라운드 조건도 바꾼다
    favorites: [],          // 즐겨찾기 카드 요약(새로 단 것이 먼저 · 데이터에 없으면 {groupId, missing})
    favLoaded: false,
    favOnly: false,         // 목록 = 즐겨찾기
    favPending: new Set(),  // 별 요청을 보내는 중인 그룹(연타 막기)
    // [노말 | 라지 (유료)](사용자 2026-10-18). 저장하지 않는다 - 새로 열면 노말(모르는 새 유료로 나가지 않게).
    size: 'normal',
  };
  let incEl = null, excEl = null, bodyEl = null, popupEl = null, recentEl = null, dlTimer = null;

  function ratingBadge(r) {
    return `<span class="seq-badge seq-r-${escHtml(r)}">${escHtml(RATING_LABELS[r] || r)}</span>`;
  }

  // Vibe 사용은 NAI 전용 — 모드를 모르면 NAI 로 간주(백엔드가 비NAI 에서 작업을 안 하므로 안전).
  function vibeAllowed() {
    try {
      const mode = typeof getApiMode === 'function' ? getApiMode() : 'NAI';
      return String(mode || 'NAI').toUpperCase() === 'NAI';
    } catch (_) { return true; }
  }

  // 모드 전환 시 Vibe 체크박스 비활성/복원(state.useVibe 값 자체는 보존). app.js syncMode 가 호출.
  function refreshVibeGate() {
    const box = panel.querySelector('[data-seq-fix="vibe"]');
    if (!box) return;
    const allowed = vibeAllowed();
    box.disabled = !allowed;
    box.checked = allowed && state.useVibe;   // 비NAI 에서는 해제 표시(값은 state 에 남음)
    const label = box.closest('.seq-fixchk');
    if (label) {
      label.classList.toggle('seq-chk-disabled', !allowed);
      label.title = allowed
        ? '라운드의 첫 이미지를 인코딩해(2 Anlas) 이후 컷에 임시 vibe 로 적용합니다(기존 Vibe Transfer 가 있으면 그 RS 는 절반으로 줄입니다). NAI 전용·라운드마다 새로 인코딩.'
        : 'NAI 모드 전용입니다 — 현재 모드에서는 Vibe 사용이 동작하지 않습니다.';
    }
  }

  // -------------------------------------------------------------- 초기화/셸
  async function ensureReady() {
    if (state.available !== null) return;
    panel.innerHTML = '<div class="seq-empty">불러오는 중…</div>';
    try {
      const st = await getJson('/api/sequence-preset/status');
      if (!st.ok) {
        if (st.dataAvailability && st.dataAvailability.data === 'missing') {
          state.available = 'missing';
          let dl = null;
          try { dl = await getJson('/api/sequence-preset/download/status'); } catch (_) { dl = null; }
          renderMissing(dl);
          if (dl && dl.active) pollDownload();
        } else {
          state.available = false; renderUnavailable();
        }
        return;
      }
      state.presentRatings = (st.ratings || []).filter(r => ALL_RATINGS.includes(r));
      state.groupCount = st.groupCount || 0;
      if (!state.presentRatings.includes('q')) state.query.ratings.delete('q');
      state.available = true;
      buildShell();
      void loadFavorites();
      renderRecent();
      if (state.pendingBox && !state.recent) {   // 패널을 열기 전에 런 상태 · 히스토리 고르기가 왔다
        const {gid, label} = state.pendingBox;
        void fillBox(gid, label);
      }
      await runSearch();
    } catch (error) {
      state.available = false; renderUnavailable();
      showToast(`시퀀스 로드 실패: ${error.message}`, 'error');
    }
  }

  function renderUnavailable() {
    panel.innerHTML = `<div class="seq-empty">시퀀스 데이터를 불러오지 못했습니다.<br>
      잠시 후 다시 시도하세요.</div>`;
  }

  // ---- HF 다운로드(데이터 미설치) — Event Preset 패턴 ----
  function renderMissing(dl) {
    const active = !!(dl && dl.active);
    const pct = Math.max(0, Math.min(100, (dl && dl.percent) || 0));
    panel.innerHTML = `
      <div class="seq-dl-card">
        <div class="seq-dl-title">시퀀스 데이터 미설치</div>
        <div class="seq-dl-desc">검증된 시퀀스 데이터(~90MB)를 HuggingFace에서 1회 받습니다.</div>
        ${active
          ? `<div class="seq-dl-bar"><div class="seq-dl-fill" style="width:${pct}%"></div></div>
             <div class="seq-dl-msg">${escHtml((dl && dl.message) || '다운로드 중…')}</div>`
          : `<button type="button" class="seq-btn primary" data-seq-download>다운로드</button>
             ${dl && dl.error ? `<div class="seq-dl-msg err">${escHtml(dl.error)}</div>` : ''}`}
      </div>`;
  }

  async function startDownload() {
    try {
      const s = await postJson('/api/sequence-preset/download/start', {});
      renderMissing(s);
      pollDownload();
    } catch (error) {
      showToast(`다운로드 시작 실패: ${error.message}`, 'error');
    }
  }

  function pollDownload() {
    if (dlTimer) return;
    dlTimer = setInterval(async () => {
      let s = null;
      try { s = await getJson('/api/sequence-preset/download/status'); } catch (_) { return; }
      if (s.done || (s.availability && s.availability.data === 'ready')) {
        clearInterval(dlTimer); dlTimer = null;
        state.available = null;   // 재초기화 → buildShell + 검색
        ensureReady();
        return;
      }
      if (!s.active && s.error) {
        clearInterval(dlTimer); dlTimer = null;
      }
      renderMissing(s);
    }, 1000);
  }

  // 검색바는 한 번만 빌드 → input/autocomplete/포커스 유지. 결과는 #seqBody 만 교체.
  function buildShell() {
    const q = state.query;
    const ratingChips = state.presentRatings.map(r =>
      `<button type="button" class="seq-rchip ${q.ratings.has(r) ? 'active' : ''}"
        data-seq-rating="${escHtml(r)}">${ratingBadge(r)}</button>`).join('');
    const cutChips = CUTS.map(n =>
      `<button type="button" class="seq-rchip seq-cut ${q.cuts.has(n) ? 'active' : ''}"
        data-seq-cut="${n}">${n}</button>`).join('');
    panel.innerHTML = `
      <div class="seq-searchbar">
        <input id="seqInclude" class="seq-input" type="text" placeholder="포함 태그 (쉼표: 1girl, nude)" autocomplete="off">
        <input id="seqExclude" class="seq-input" type="text" placeholder="제외 태그" autocomplete="off">
        <div class="seq-filters">
          <span class="seq-flabel">수위</span>${ratingChips}
          <span class="seq-flabel">컷</span>${cutChips}
          ${LARGE_SIZE_ENABLED ? `<span class="seq-sizeseg" role="group" aria-label="만화 크기">
            <button type="button" class="seq-size ${state.size === 'normal' ? 'active' : ''}" data-seq-size="normal"
              aria-pressed="${state.size === 'normal'}" title="2컷 896x1152 · 3컷 768x1344 · 4컷 1088x960">노말</button>
            <button type="button" class="seq-size seq-size-large ${state.size === 'large' ? 'active' : ''}" data-seq-size="large"
              aria-pressed="${state.size === 'large'}" title="2컷 1152x1472 · 3컷 1024x1792 · 4컷 1280x1280 - 1MP 를 넘어 Anlas 를 씁니다">라지 (유료)</button>
          </span>` : ''}
          <button type="button" class="seq-rchip seq-favchip ${state.favOnly ? 'active' : ''}" data-seq-favonly
            title="즐겨찾기만 봅니다 - 항목의 ☆ 를 누르면 넣고 뺍니다">★ 즐겨찾기 <span data-seq-favcount>${state.favorites.length}</span></button>
        </div>
        <div class="seq-actions-row">
          <button type="button" class="seq-btn" data-seq-search>검색</button>
          <button type="button" class="seq-btn ghost" data-seq-random>랜덤</button>
        </div>
      </div>
      <div class="seq-body" id="seqBody"></div>
      <div class="seq-recent" id="seqRecent" hidden></div>
      <div class="seq-popup seq-peek" id="seqPopup"></div>`;
    incEl = panel.querySelector('#seqInclude');
    excEl = panel.querySelector('#seqExclude');
    bodyEl = panel.querySelector('#seqBody');
    popupEl = panel.querySelector('#seqPopup');
    recentEl = panel.querySelector('#seqRecent');
    incEl.value = q.include;
    excEl.value = q.exclude;
    // 태그 자동완성 (포함/제외) — input 도 value/selection 기반이라 동작.
    // 시퀀스 데이터는 danbooru 기반이라 e621 제안은 제외(excludeE621).
    if (typeof bindTagAssist === 'function') {
      try {
        bindTagAssist(incEl, {excludeE621: true});
        bindTagAssist(excEl, {excludeE621: true});
      } catch (_) { /* tagAssist 미준비 */ }
    }
    refreshVibeGate();   // 현재 모드 기준 Vibe 체크박스 활성/비활성 동기화
  }

  function syncChips() {
    panel.querySelectorAll('[data-seq-rating]').forEach(b =>
      b.classList.toggle('active', state.query.ratings.has(b.dataset.seqRating)));
    panel.querySelectorAll('[data-seq-cut]').forEach(b =>
      b.classList.toggle('active', state.query.cuts.has(Number(b.dataset.seqCut))));
    panel.querySelectorAll('[data-seq-favonly]').forEach(b => b.classList.toggle('active', state.favOnly));
    panel.querySelectorAll('[data-seq-favcount]').forEach(el => { el.textContent = String(state.favorites.length); });
  }

  function collectInputs() {
    if (incEl) state.query.include = incEl.value;
    if (excEl) state.query.exclude = excEl.value;
  }

  // 현재 검색 필터 페이로드 — 생성/연속 추첨 모집단(전체 매칭)을 백엔드가 동일 조건으로 잡도록.
  function searchPayload() {
    collectInputs();
    const q = state.query;
    return {
      include: q.include, exclude: q.exclude,
      ratings: Array.from(q.ratings),
      frameCounts: Array.from(q.cuts),
      // 만화 크기 - 런 상태에 남아 Auto Gen 다음 라운드도 같은 크기다.
      size: LARGE_SIZE_ENABLED ? state.size : 'normal',
      // 하단 '고정' 토글 — 생성/연속 추첨에 전달(런 상태에 저장돼 auto-continue 라운드에도 적용).
      fixSeed: state.fixSeed,
      fixResolution: state.fixResolution,
      useVibe: state.useVibe,
    };
  }

  // Auto Gen 이 도는 동안 컷 · 수위 칩 · 검색을 바꾸면 그 런의 다음 라운드 조건도 바꾼다(사용자 2026-10-18 - 예전엔 시작할 때의
  // 조건으로 계속 뽑았다). 한 줄로 보내고 조건은 **보낼 때** 읽는다 - 칩을 연달아 눌러도 마지막 조건이 마지막에 닿는다.
  let runQueryChain = Promise.resolve();
  function pushRunQuery() {
    if (!state.runActive) return;
    runQueryChain = runQueryChain
      .then(() => postJson('/api/sequence-preset/run-query', searchPayload()))
      .catch(() => null);      // 실패해도 다음 칩 변경이 다시 보낸다
  }

  // -------------------------------------------------------------- 검색/생성
  async function runSearch(opts = {}) {
    collectInputs();
    closePopup();
    state.favOnly = false;      // 검색 · 칩을 누르면 검색 결과를 본다
    syncChips();
    pushRunQuery();             // 도는 런이 있으면 다음 라운드부터 이 조건으로
    state.busy = true; renderBody();
    try {
      const q = state.query;
      state.results = await postJson('/api/sequence-preset/search', {
        include: q.include, exclude: q.exclude,
        ratings: Array.from(q.ratings),
        frameCounts: Array.from(q.cuts),
        limit: 60, random: opts.random !== false,   // 검색은 기본 랜덤(사용자 요청)
      });
    } catch (error) {
      showToast(`검색 실패: ${error.message}`, 'error');
    } finally {
      state.busy = false; renderBody();
    }
  }

  // [미리보기] 에 마우스를 올리면 툴팁으로 그 그룹의 만화 한 장 구성을 보여 준다(사용자 2026-10-18). 항목 누름 = 고르기.
  // 응답은 그룹별로 캐시한다. 늦게 온 응답은 지금 떠 있는 그룹일 때만 그린다(그새 다른 항목으로 옮겼을 수 있다).
  async function openGroup(groupId) {
    const id = Number(groupId);
    state.openGroupId = id;
    state.detail = state.previews.get(id) || null;
    highlightCards();
    renderPopup();
    if (state.detail) return;
    try {
      const d = await postJson('/api/sequence-preset/sequence', {groupId: id});
      state.previews.set(id, d);
      if (state.openGroupId !== id) return;
      state.detail = d;
      renderPopup();
    } catch (error) {
      showToast(`그룹 로드 실패: ${error.message}`, 'error');
      if (state.openGroupId === id) closePopup();
    }
  }

  // 생성 전에 퀵 패널의 가상 캐릭터(인셋) 편집이 서버에 다 닿기를 기다린다(Codex 리뷰 - 안 기다리면 화면의 최신 글이 아니라
  // 옛 인물로 그린다). 기다리는 사이 저장이 실패했으면 생성하지 않는다.
  async function charactersSettled() {
    if (typeof beforeGenerate !== 'function') return true;
    try {
      if (await beforeGenerate() !== false) return true;
    } catch (_) { /* 아래에서 알린다 */ }
    showToast('캐릭터 편집이 저장되지 않아 생성하지 않았습니다 - 확인한 뒤 다시 눌러 주세요.', 'error');
    return false;
  }

  // 이 런의 런 상태(module_state)를 이미 받았으면 HTTP 답은 칸에 그리지 않는다 - 런 상태가 먼저 칸을 채웠고, 그 뒤 사람이
  // 다른 카드를 골랐을 수 있다(Codex 재리뷰: 같은 라운드의 늦은 HTTP 답이 그 선택을 되돌려 Generate 가 엉뚱한 번호를 보냈다).
  function runAlreadySeen(runId) {
    return !!runId && state.runSeen.runId === String(runId);
  }

  async function generateGroup(groupId) {
    if (state.busy) return;
    state.busy = true; syncGenerateButtons();
    try {
      if (!(await charactersSettled())) return;
      const out = await postJson('/api/sequence-preset/generate',
        {groupId: Number(groupId), ...searchPayload()});
      // 등록 성공 알림은 띄우지 않는다(사용자 2026-10-18 - 이야기 하나 = 한 장이라 뜻이 없다 · 무엇을 그렸는지는 '방금 생성' 칸).
      if (!out.ok) {
        const failed = (out.frames || []).find(f => !f.ok);
        showToast(`생성 등록 실패: ${failed?.error || out.error || '자격증명/큐 확인'}`, 'error');
      }
      if (out.ok && !runAlreadySeen(out.runId)) setRecent(out.group, out.groupId);
    } catch (error) {
      showToast(`생성 실패: ${error.message}`, 'error');
    } finally {
      state.busy = false; syncGenerateButtons();
    }
  }

  function syncGenerateButtons() {
    panel.querySelectorAll('[data-seq-generate]').forEach(b => { b.disabled = !!state.busy; });
  }

  // 메인 Random(Alt+Enter) — Sequence 컨텍스트. 현재 매칭 전체에서 랜덤 그룹 1개를 연속 생성.
  // Auto Gen ON 이면 백엔드 러너가 라운드 완료마다 다음 랜덤 그룹으로 이어간다.
  async function runRandomGenerate() {
    if (state.busy) return true;
    state.busy = true;
    try {
      if (!(await charactersSettled())) return true;
      const out = await postJson('/api/sequence-preset/random-generate', searchPayload());
      if (!out.ok) {   // 등록 성공 알림은 없다(위 generateGroup 과 같다)
        const failed = (out.frames || []).find(f => !f.ok);
        showToast(`연속 생성 실패: ${failed?.error || out.error || '매칭/자격증명/큐 확인'}`, 'error');
      }
      if (out.ok && !runAlreadySeen(out.runId)) setRecent(out.group, out.groupId);
    } catch (error) {
      showToast(`연속 생성 실패: ${error.message}`, 'error');
    } finally {
      state.busy = false;
    }
    return true;
  }

  // -------------------------------------------------------------- body 렌더
  function renderBody() {
    if (!bodyEl) return;
    if (state.favOnly) { bodyEl.innerHTML = renderFavorites(); return; }
    if (state.busy && !state.results) { bodyEl.innerHTML = '<div class="seq-empty">검색 중…</div>'; return; }
    bodyEl.innerHTML = renderResults();
  }

  function isFavorite(groupId) {
    return state.favorites.some(f => f.groupId === groupId);
  }

  // 항목 = 글 + 오른쪽 끝 [☆] [생성] [미리보기](사용자 2026-10-18). 항목을 누르면 고른다(메인 Generate = 고른 것).
  // 검색 결과 · 즐겨찾기 · 방금 생성이 같은 카드를 쓴다 - 같은 그룹이 두 곳에 있으면 두 곳 다 고른 표시가 난다.
  function renderCard(g) {
    const gid = Number(g.groupId);
    const id = escHtml(String(gid));
    const fav = isFavorite(gid);
    const star = `<button type="button" class="seq-star ${fav ? 'on' : ''}" data-seq-star="${id}"
      title="${fav ? '즐겨찾기에서 뺍니다' : '즐겨찾기에 넣습니다'}" aria-label="즐겨찾기" aria-pressed="${fav}">${fav ? '★' : '☆'}</button>`;
    if (g.missing) {
      // 데이터가 바뀌어 빠진 이야기 - 고르거나 생성할 수 없다. 별만 뗄 수 있다.
      return `
      <div class="seq-flow-card seq-flow-item seq-missing">
        <div class="seq-flow-text"><span class="seq-flow-meta">#${id}</span>
          <span class="seq-flow-name">지금 데이터에 없는 이야기입니다</span></div>
        <div class="seq-flow-actions">${star}</div>
      </div>`;
    }
    const selected = state.selected?.groupId === gid;
    return `
      <div class="seq-flow-card seq-flow-item ${state.openGroupId === gid ? 'active' : ''} ${selected ? 'selected' : ''}"
        data-seq-group="${id}" aria-selected="${selected}" title="누르면 고릅니다 - 메인 Generate 가 이 이야기를 생성합니다">
        <div class="seq-flow-text">
          <span class="seq-flow-meta">${ratingBadge(g.peakRating)} ${escHtml(String(g.frameCount))}컷
            <span class="seq-arc">${(g.stages || []).map(s => escHtml(STAGE_LABELS[s] || s)).join('›')}</span>
            <span class="seq-gid">#${id}</span></span>
          <span class="seq-flow-name">${escHtml(g.preview || '')}</span>
        </div>
        <div class="seq-flow-actions">
          ${star}
          <button type="button" class="seq-btn primary seq-mini" data-seq-generate="${id}" ${state.busy ? 'disabled' : ''}>생성</button>
          <button type="button" class="seq-btn seq-mini" data-seq-peek="${id}">미리보기</button>
        </div>
      </div>`;
  }

  function renderResults() {
    const r = state.results;
    if (!r) return '';
    if (!r.groups || !r.groups.length) {
      return `<div class="seq-empty">결과 없음 — 태그/필터를 바꿔보세요.</div>`;
    }
    const head = `<div class="seq-rescount">${r.total.toLocaleString()}건 매칭 · ${r.groups.length} 표시
      ${state.groupCount ? `<span class="seq-count">전체 ${state.groupCount.toLocaleString()}</span>` : ''}</div>`;
    return head + `<div class="seq-flow-list">${r.groups.map(renderCard).join('')}</div>`;
  }

  function renderFavorites() {
    if (!state.favLoaded) return '<div class="seq-empty">즐겨찾기 불러오는 중…</div>';
    if (!state.favorites.length) {
      return '<div class="seq-empty">즐겨찾기가 없습니다 — 항목의 ☆ 를 누르면 여기에 남습니다.</div>';
    }
    const head = `<div class="seq-rescount">즐겨찾기 ${state.favorites.length.toLocaleString()}개</div>`;
    return head + `<div class="seq-flow-list">${state.favorites.map(renderCard).join('')}</div>`;
  }

  // '방금 생성' 칸 - 목록 아래(스크롤해도 바닥에 붙어 있다). 마지막 하나만.
  function renderRecent() {
    if (!recentEl) return;
    if (!state.recent) { recentEl.hidden = true; recentEl.innerHTML = ''; return; }
    recentEl.hidden = false;
    recentEl.innerHTML = `<div class="seq-recent-head">${escHtml(state.boxLabel || '방금 생성')}</div>${renderCard(state.recent)}`;
  }

  function renderLists() {
    renderBody();
    renderRecent();
    syncChips();
  }

  // ---------------------------------------------------------------- 고르기
  function findSummary(groupId) {
    const gid = Number(groupId);
    return (state.results?.groups || []).find(g => g.groupId === gid)
      || state.favorites.find(g => g.groupId === gid && !g.missing)
      || (state.recent?.groupId === gid ? state.recent : null)
      || state.previews.get(gid)?.group || null;
  }

  function applySelection(summary) {
    state.selected = summary && !summary.missing ? summary : null;
    panel.querySelectorAll('[data-seq-group]').forEach(card => {
      const on = Number(card.dataset.seqGroup) === state.selected?.groupId;
      card.classList.toggle('selected', on);
      card.setAttribute('aria-selected', String(on));
    });
    try { onSelectionChange?.(state.selected); } catch (_) { /* 단추 글자 갱신 실패가 고르기를 막지 않는다 */ }
  }

  // 사람이 카드를 누른 차례. 칸을 채우는 사이(요약을 받아 오는 동안) 사람이 직접 골랐으면 늦게 온 칸은 그 선택을 덮지
  // 않는다 - 안 그러면 다음 Generate 가 사람이 고르지 않은 이야기를 보냈다(Codex 재리뷰).
  let userSelectSeq = 0;

  function selectGroup(groupId) {
    const gid = Number(groupId);
    userSelectSeq += 1;
    applySelection(state.selected?.groupId === gid ? null : findSummary(gid));   // 다시 누르면 푼다
  }

  // 아래 칸이 바뀌면 고른 것도 그리로 옮긴다(사용자 2026-10-18 - 바로 Generate 로 다시 그릴 수 있게).
  function showRecentCard(summary, label = '방금 생성', {autoSelect = true} = {}) {
    state.recent = summary;
    state.boxLabel = label;
    renderRecent();
    // 데이터에 없는 이야기는 고를 수 없다 - 고른 것을 그대로 둔다.
    if (autoSelect && !summary.missing) applySelection(summary);
  }

  // ---------------------------------------------------------------- 아래 칸(방금 생성 · 히스토리에서 고른 그림)
  let boxSeq = 0;      // 칸을 바꾸는 차례 - 요약을 받아 오는 사이 더 새 것이 오면 늦은 답은 버린다
  let fillKind = '';   // 지금 칸을 채우는 쪽('recent' | 'history') - 히스토리에서 다른 그림을 고르면 히스토리 채우기만 무른다

  // 요약이 손에 없으면(Auto Gen 의 다음 라운드 · 히스토리 · 패널을 늦게 연 경우) 미리보기와 같은 응답으로 받는다(캐시 공유).
  // selectAt = 이 칸을 부른 순간의 '사람이 고른 차례' - 그 뒤로 사람이 골랐으면 칸만 바꾸고 고르지는 않는다.
  async function fillBox(gid, label, kind = 'recent', selectAt = userSelectSeq) {
    const my = ++boxSeq;
    fillKind = kind;
    if (state.available !== true) { state.pendingBox = {gid, label}; return; }   // 셸이 생기면 ensureReady 가 다시 부른다
    state.pendingBox = null;
    let summary = findSummary(gid);
    if (!summary) {
      try {
        const d = state.previews.get(gid) || await postJson('/api/sequence-preset/sequence', {groupId: gid});
        state.previews.set(gid, d);
        summary = d.group || null;
      } catch (_) {
        summary = null;
      }
      if (my !== boxSeq) return;              // 그새 다음 라운드 · 다른 그림이 왔다
    }
    showRecentCard(summary || {groupId: gid, missing: true}, label, {autoSelect: userSelectSeq === selectAt});
  }

  function setRecent(group, groupId) {
    const gid = Number(group?.groupId ?? groupId);
    if (!Number.isFinite(gid) || gid <= 0) return;
    state.recentId = gid;
    if (group && group.groupId === gid && state.available === true) {
      boxSeq += 1;                            // 받아 오던 늦은 답을 무른다
      state.pendingBox = null;
      showRecentCard(group);
      return;
    }
    void fillBox(gid, '방금 생성');
  }

  // 런 상태(module_state `sequence_run`) - Auto Gen 이 다음 라운드로 넘어가면 그 그룹이 '방금 생성' 이 된다.
  // 라운드마다 **한 번만** 반영한다 - 같은 라운드의 거듭된 알림(한 장 완료 · 런 종료)이 사람이 히스토리에서 고른 칸을
  // 되돌리지 않게. 칸이 이미 그 그룹이면 다시 고르지 않는다(HTTP 답이 먼저 채운 경우).
  let appliedRunKey = '';
  function onRunState(st) {
    state.runActive = st?.is_running === true || String(st?.is_running).toLowerCase() === 'true';
    const runId = String(st?.run_id || '');
    const round = Number(st?.round_count) || 0;
    if (runId && (runId !== state.runSeen.runId || round > state.runSeen.round)) state.runSeen = {runId, round};
    const key = `${runId}:${round}`;
    if (key === appliedRunKey) return;
    appliedRunKey = key;
    const gid = Number(st?.group_id) || 0;
    if (gid <= 0) return;
    if (gid === state.recentId && state.recent?.groupId === gid) return;
    state.recentId = gid;
    void fillBox(gid, '방금 생성');
  }

  // 히스토리에서 고른 그림이 Sequence 로 만든 것이면 그 이야기를 칸에 띄운다(사용자 2026-10-18 - 고르면 따라간다).
  // selectStamp = 그림을 고른 순간의 selectionStamp() - 메타를 받아 오는 사이 사람이 카드를 골랐으면 그 선택을 둔다.
  function showFromHistory(gid, selectStamp) {
    const n = Number(gid) || 0;
    if (n <= 0) return;
    const stamp = Number.isFinite(Number(selectStamp)) ? Number(selectStamp) : userSelectSeq;
    void fillBox(n, n === state.recentId ? '방금 생성' : '히스토리에서 고른 그림의 이야기', 'history', stamp);
  }

  // 히스토리에서 다른 그림을 골랐다 - 아직 채우는 중인 앞 그림의 칸은 무른다(일반 그림을 골랐는데 앞 그림이 뒤늦게 뜨지 않게).
  function cancelHistoryFill() {
    if (fillKind === 'history') boxSeq += 1;
  }

  // ---------------------------------------------------------------- 즐겨찾기
  // 조회 · 별 달기 · 떼기를 **한 줄로** 보낸다(Codex 리뷰). 서버는 매번 목록 전체를 돌려주는데, 따로 보내면 늦게 온 앞의 답이
  // 뒤의 답을 덮었다(A · B 를 연달아 달면 B 가 사라짐 · 처음 조회가 떼기 뒤에 오면 뗀 별이 되살아남).
  let favChain = Promise.resolve();
  function queueFavorites(task) {
    const run = favChain.then(task);
    favChain = run.catch(() => null);
    return run;
  }

  function loadFavorites() {
    return queueFavorites(async () => {
      try {
        const out = await getJson('/api/sequence-preset/favorites');
        state.favorites = Array.isArray(out.favorites) ? out.favorites : [];
      } catch (error) {
        showToast(`즐겨찾기 불러오기 실패: ${error.message}`, 'error');
      } finally {
        state.favLoaded = true;
        renderLists();
      }
    });
  }

  function toggleFavorite(groupId) {
    const gid = Number(groupId);
    if (!Number.isFinite(gid) || state.favPending.has(gid)) return;
    const favorite = !isFavorite(gid);       // 누른 순간 보이던 별의 반대
    state.favPending.add(gid);
    void queueFavorites(async () => {
      try {
        const out = await postJson('/api/sequence-preset/favorites', {groupId: gid, favorite});
        state.favorites = Array.isArray(out.favorites) ? out.favorites : state.favorites;
        state.favLoaded = true;
      } catch (error) {
        showToast(`즐겨찾기 ${favorite ? '넣기' : '빼기'} 실패: ${error.message}`, 'error');
      } finally {
        state.favPending.delete(gid);
        renderLists();
      }
    });
  }

  // 미리보기 툴팁(사용자 2026-10-18): 모양은 예전 우측 팝업 그대로. 캐릭터 특징은 뺀 채(백엔드 comic_preview)
  //   character clothing 상자 · scene 1 = 실을 태그 · scene 2~ = `add :` / `rem :` 두 줄(옷은 rem 에 안 보인다).
  //   생성 버튼은 없다 - 항목의 [생성] 이 한다.
  function renderPopup() {
    if (!popupEl) return;
    popupEl.classList.add('open');
    if (!state.detail) {
      popupEl.innerHTML = `
        <div class="seq-popup-head"><span class="seq-popup-title">불러오는 중…</span></div>
        <div class="seq-popup-body"><div class="seq-empty">미리보기 불러오는 중…</div></div>`;
      return;
    }
    const g = state.detail.group;
    const comic = state.detail.comic || {clothing: [], scenes: []};
    const join = list => escHtml((list || []).join(', '));
    const clothing = (comic.clothing || []).length ? `
      <div class="seq-frame seq-clothing">
        <div class="seq-frame-head"><span class="seq-frame-stage">character clothing</span></div>
        <div class="seq-frame-prompt">${join(comic.clothing)}</div>
      </div>` : '';
    const scenes = (comic.scenes || []).map(sc => `
      <div class="seq-frame">
        <div class="seq-frame-head">
          <span class="seq-frame-no">${escHtml(String(sc.index))}</span>
          ${ratingBadge(sc.rating)}
          <span class="seq-frame-stage">scene ${escHtml(String(sc.index))}</span>
        </div>
        ${sc.index === 1
          ? `<div class="seq-frame-prompt">${join(sc.tags)}</div>`
          : `<div class="seq-frame-prompt seq-add">add : ${join(sc.add)}</div>
             <div class="seq-frame-prompt seq-rem">rem : ${join(sc.rem)}</div>`}
      </div>`).join('');
    popupEl.innerHTML = `
      <div class="seq-popup-head">
        <span class="seq-popup-title">group #${escHtml(String(g.groupId))}</span>
        ${ratingBadge(g.peakRating)}
        <span class="seq-count">${escHtml(String((comic.scenes || []).length))}장면</span>
      </div>
      <div class="seq-popup-body">${clothing}${scenes}</div>`;
  }

  function closePopup() {
    state.detail = null;
    state.openGroupId = null;
    if (popupEl) { popupEl.classList.remove('open'); popupEl.innerHTML = ''; }
    highlightCards();
  }

  function highlightCards() {
    panel.querySelectorAll('[data-seq-group]').forEach(b =>
      b.classList.toggle('active', Number(b.dataset.seqGroup) === state.openGroupId));
  }

  // -------------------------------------------------------------- 이벤트 (위임, 1회 부착)
  panel.addEventListener('click', event => {
    if (event.target.closest('[data-seq-download]')) { startDownload(); return; }
    const star = event.target.closest('[data-seq-star]');
    if (star) { void toggleFavorite(star.dataset.seqStar); return; }
    const sizeBtn = event.target.closest('[data-seq-size]');
    if (sizeBtn) {
      state.size = sizeBtn.dataset.seqSize === 'large' ? 'large' : 'normal';
      panel.querySelectorAll('[data-seq-size]').forEach(b => {
        const on = b.dataset.seqSize === state.size;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', String(on));
      });
      try { onSizeChange?.(state.size); } catch (_) { /* 단추 · 경고 갱신 실패가 고르기를 막지 않는다 */ }
      return;
    }
    if (event.target.closest('[data-seq-favonly]')) {
      closePopup();
      state.favOnly = !state.favOnly;
      if (state.favOnly && !state.favLoaded) void loadFavorites();
      renderLists();
      return;
    }
    const rchip = event.target.closest('[data-seq-rating]');
    if (rchip) {
      const r = rchip.dataset.seqRating;
      if (state.query.ratings.has(r)) state.query.ratings.delete(r);
      else state.query.ratings.add(r);
      syncChips(); runSearch(); return;     // 즉시 반영
    }
    const cchip = event.target.closest('[data-seq-cut]');
    if (cchip) {
      const n = Number(cchip.dataset.seqCut);
      if (state.query.cuts.has(n)) state.query.cuts.delete(n);
      else state.query.cuts.add(n);
      syncChips(); runSearch(); return;     // 즉시 반영
    }
    if (event.target.closest('[data-seq-search]')) { runSearch(); return; }
    if (event.target.closest('[data-seq-random]')) { runSearch({random: true}); return; }
    const gen = event.target.closest('[data-seq-generate]');
    if (gen) { generateGroup(gen.dataset.seqGenerate); return; }
    if (event.target.closest('[data-seq-peek]')) return;          // 미리보기는 호버 - 누름은 고르기가 아니다
    const card = event.target.closest('[data-seq-group]');
    if (card) selectGroup(card.dataset.seqGroup);
  });

  // [미리보기] 호버 = 툴팁. 버튼에 들어올 때 열고 버튼에서 나갈 때 닫는다(버튼 안의 자식 사이 이동은 무시).
  panel.addEventListener('mouseover', event => {
    const peek = event.target.closest('[data-seq-peek]');
    if (!peek || (event.relatedTarget && peek.contains(event.relatedTarget))) return;
    openGroup(peek.dataset.seqPeek);
  });
  panel.addEventListener('mouseout', event => {
    const peek = event.target.closest('[data-seq-peek]');
    if (!peek || (event.relatedTarget && peek.contains(event.relatedTarget))) return;
    closePopup();
  });

  // 하단 '고정' 체크박스 — change 위임(라벨 클릭도 정확히 잡힘). 즉시 state 반영(검색 불필요).
  panel.addEventListener('change', event => {
    const fix = event.target.closest('[data-seq-fix]');
    if (!fix) return;
    const kind = fix.dataset.seqFix;
    if (kind === 'seed') state.fixSeed = fix.checked;
    else if (kind === 'resolution') state.fixResolution = fix.checked;
    else if (kind === 'vibe') { if (!fix.disabled) state.useVibe = fix.checked; }  // 비NAI(disabled)면 값 보존
  });

  // 포함/제외 칸에서 Enter = 검색(사용자 2026-10-18 - 눌러도 아무 일이 없었다). 자동완성이 후보를 고른 Enter 는
  // 그쪽이 칸에서 stopPropagation 으로 삼켜 여기까지 안 온다(그 Enter 는 태그 넣기). 조합 중(IME) · Ctrl/Alt+Enter
  // (전역 생성 · 랜덤)는 건드리지 않는다.
  panel.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.defaultPrevented) return;
    if (event.isComposing || event.keyCode === 229) return;
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (!event.target.closest('#seqInclude, #seqExclude')) return;
    event.preventDefault();
    runSearch();
  });

  // Esc로 우측 팝업 닫기(검색 입력 포커스 중에도). 패널은 1회 생성이라 리스너도 1회.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && popupEl && popupEl.classList.contains('open')) {
      closePopup();
    }
  });

  return {
    onOpen() { ensureReady(); },
    onModeChange() { refreshVibeGate(); },   // app.js syncMode → Vibe 체크박스 NAI 게이트 갱신
    // 메인 하단 버튼 라우팅용(app.js). Sequence 탭 활성일 때 Ctrl/Alt+Enter 가 위임된다.
    // 메인 Generate = 고른 이야기(사용자 2026-10-18). 고른 것이 없으면 app.js 가 안내만 한다.
    selectedGroupId() { return state.selected ? state.selected.groupId : 0; },
    isLarge() { return LARGE_SIZE_ENABLED && state.size === 'large'; },   // app.js 금액 판정 - 라지는 1MP 를 넘는다
    hasSelection() { return !!state.selected; },
    generateSelected() {
      if (!state.selected) return false;
      void generateGroup(state.selected.groupId);
      return true;
    },
    randomGenerate() { return runRandomGenerate(); },  // req2/3: 랜덤 그룹 연속 생성
    onRunState(st) { onRunState(st); },                // app.js onModuleState('sequence_run') - 방금 생성 칸
    showFromHistory(gid, stamp) { showFromHistory(gid, stamp); },   // app.js 히스토리 고르기 - 그 그림의 이야기
    cancelHistoryFill() { cancelHistoryFill(); },
    selectionStamp() { return userSelectSeq; },
  };
}
