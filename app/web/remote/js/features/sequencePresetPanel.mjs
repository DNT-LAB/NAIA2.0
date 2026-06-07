// Sequence 패널 — 검증된 실제 이벤트 그룹을 태그 검색으로 서빙 (Dev0714 EventSearcher 모델).
// 검색바를 영속화(input autocomplete/포커스 보존) 하고 결과 영역만 갱신한다. 수위·컷 칩은
// 검색 버튼 없이 즉시 반영. 포함/제외 입력에 tagAssist(태그 자동완성) 바인딩.
// 좌측 #tabSequence 상주. 생성은 표준 PE 경유 — Storyteller 비커플링.

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
const CUTS = [2, 3, 4, 5, 6];

export function createSequencePresetPanel({panel, escHtml, showToast, bindTagAssist}) {
  const state = {
    available: null,        // null=미확인
    presentRatings: [],
    groupCount: 0,
    query: {include: '1girl', exclude: '', ratings: new Set(['s']), cuts: new Set()},
    results: null,
    detail: null,
    openGroupId: null,      // 우측 팝업에 열린 그룹 (카드 하이라이트용)
    busy: false,
  };
  let incEl = null, excEl = null, bodyEl = null, popupEl = null, dlTimer = null;

  function ratingBadge(r) {
    return `<span class="seq-badge seq-r-${escHtml(r)}">${escHtml(RATING_LABELS[r] || r)}</span>`;
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
      if (!state.presentRatings.includes('s')) state.query.ratings.delete('s');
      state.available = true;
      buildShell();
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
        </div>
        <div class="seq-actions-row">
          <button type="button" class="seq-btn" data-seq-search>검색</button>
          <button type="button" class="seq-btn ghost" data-seq-random>랜덤</button>
        </div>
      </div>
      <div class="seq-body" id="seqBody"></div>
      <div class="seq-popup" id="seqPopup"></div>`;
    incEl = panel.querySelector('#seqInclude');
    excEl = panel.querySelector('#seqExclude');
    bodyEl = panel.querySelector('#seqBody');
    popupEl = panel.querySelector('#seqPopup');
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
  }

  function syncChips() {
    panel.querySelectorAll('[data-seq-rating]').forEach(b =>
      b.classList.toggle('active', state.query.ratings.has(b.dataset.seqRating)));
    panel.querySelectorAll('[data-seq-cut]').forEach(b =>
      b.classList.toggle('active', state.query.cuts.has(Number(b.dataset.seqCut))));
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
    };
  }

  // -------------------------------------------------------------- 검색/생성
  async function runSearch(opts = {}) {
    collectInputs();
    closePopup();
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

  // 그룹 클릭 → 좌측 결과는 유지하고 우측 팝업에 상세+연속생성 표시(← 뒤로가기 불필요).
  // 다른 카드를 누르면 팝업이 그 그룹으로 갱신된다.
  async function openGroup(groupId) {
    const id = Number(groupId);
    state.openGroupId = id;
    state.detail = null;
    highlightCards();
    renderPopup();              // 로딩 상태로 즉시 표시
    try {
      const d = await postJson('/api/sequence-preset/sequence', {groupId: id});
      if (state.openGroupId !== id) return;   // 그새 다른 카드를 누른 경우
      state.detail = d;
      renderPopup();
    } catch (error) {
      showToast(`그룹 로드 실패: ${error.message}`, 'error');
      if (state.openGroupId === id) closePopup();
    }
  }

  async function generateGroup(groupId) {
    if (state.busy) return;
    state.busy = true; renderPopup();
    try {
      const out = await postJson('/api/sequence-preset/generate',
        {groupId: Number(groupId), ...searchPayload()});
      const failed = (out.frames || []).filter(f => !f.ok);
      if (!out.ok) {
        showToast(`생성 등록 실패: ${failed.length ? failed[0].error : (out.error || '자격증명/큐 확인')}`, 'error');
      } else if (failed.length) {
        const detail = failed.map(f => `컷${f.index + 1}(${f.error || 'failed'})`).join(', ');
        showToast(`${out.total}컷 중 ${out.enqueued}컷 등록 · 실패: ${detail}`, 'warning');
      } else {
        showToast(out.autoGen ? `연속 생성 시작 (그룹 #${out.groupId}, Auto Gen)`
                              : `${out.total}컷 생성 큐 등록`, 'success');
      }
    } catch (error) {
      showToast(`생성 실패: ${error.message}`, 'error');
    } finally {
      state.busy = false; renderPopup();
    }
  }

  // 메인 Random(Alt+Enter) — Sequence 컨텍스트. 현재 매칭 전체에서 랜덤 그룹 1개를 연속 생성.
  // Auto Gen ON 이면 백엔드 러너가 라운드 완료마다 다음 랜덤 그룹으로 이어간다.
  async function runRandomGenerate() {
    if (state.busy) return true;
    state.busy = true;
    try {
      const out = await postJson('/api/sequence-preset/random-generate', searchPayload());
      if (!out.ok) {
        const failed = (out.frames || []).filter(f => !f.ok);
        showToast(`연속 생성 실패: ${failed.length ? failed[0].error : (out.error || '매칭/자격증명/큐 확인')}`, 'error');
      } else {
        showToast(out.autoGen ? `연속 생성 시작 (그룹 #${out.groupId}, Auto Gen)`
                              : `${out.total}컷 생성 큐 등록 (그룹 #${out.groupId})`, 'success');
      }
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
    if (state.busy && !state.results) { bodyEl.innerHTML = '<div class="seq-empty">검색 중…</div>'; return; }
    bodyEl.innerHTML = renderResults();
  }

  function renderResults() {
    const r = state.results;
    if (!r) return '';
    if (!r.groups || !r.groups.length) {
      return `<div class="seq-empty">결과 없음 — 태그/필터를 바꿔보세요.</div>`;
    }
    const head = `<div class="seq-rescount">${r.total.toLocaleString()}건 매칭 · ${r.groups.length} 표시
      ${state.groupCount ? `<span class="seq-count">전체 ${state.groupCount.toLocaleString()}</span>` : ''}</div>`;
    const cards = r.groups.map(g => `
      <button type="button" class="seq-flow-card ${state.openGroupId === g.groupId ? 'active' : ''}" data-seq-group="${escHtml(String(g.groupId))}">
        <span class="seq-flow-meta">${ratingBadge(g.peakRating)} ${escHtml(String(g.frameCount))}컷
          <span class="seq-arc">${g.stages.map(s => escHtml(STAGE_LABELS[s] || s)).join('›')}</span></span>
        <span class="seq-flow-name">${escHtml(g.preview || '')}</span>
      </button>`).join('');
    return head + `<div class="seq-flow-list">${cards}</div>`;
  }

  // 우측 팝업: 결과 리스트는 그대로 두고 상세+연속생성을 보여준다. 헤더 ×로 닫고,
  // 다른 카드를 누르면 openGroup 이 내용을 교체한다.
  function renderPopup() {
    if (!popupEl) return;
    popupEl.classList.add('open');
    if (!state.detail) {
      popupEl.innerHTML = `
        <div class="seq-popup-head">
          <span class="seq-popup-title">불러오는 중…</span>
          <button type="button" class="seq-popup-close" data-seq-popup-close aria-label="닫기">&times;</button>
        </div>
        <div class="seq-popup-body"><div class="seq-empty">시퀀스 불러오는 중…</div></div>`;
      return;
    }
    const g = state.detail.group;
    const frames = state.detail.frames.map(fr => `
      <div class="seq-frame">
        <div class="seq-frame-head">
          <span class="seq-frame-no">${escHtml(String(fr.index + 1))}</span>
          ${ratingBadge(fr.rating)}
          <span class="seq-frame-stage">${escHtml(fr.stageLabel || STAGE_LABELS[fr.stage] || fr.stage)}</span>
        </div>
        <div class="seq-frame-prompt">${escHtml(fr.preview)}</div>
      </div>`).join('');
    popupEl.innerHTML = `
      <div class="seq-popup-head">
        <span class="seq-popup-title">group #${escHtml(String(g.groupId))}</span>
        ${ratingBadge(g.peakRating)}
        <span class="seq-count">${escHtml(String(g.frameCount))}컷</span>
        <button type="button" class="seq-popup-close" data-seq-popup-close aria-label="닫기">&times;</button>
      </div>
      <div class="seq-popup-body">${frames}</div>
      <div class="seq-popup-foot">
        <button type="button" class="seq-btn primary" data-seq-generate="${escHtml(String(g.groupId))}"
          ${state.busy ? 'disabled' : ''}>${state.busy ? '처리 중…' : `연속 생성 (${g.frameCount}컷)`}</button>
        <div class="seq-hint">정체성(작가/캐릭터)은 현재 PE·캐릭터 설정이 채웁니다. 장면만 흐름대로 진행됩니다.</div>
      </div>`;
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
    if (event.target.closest('[data-seq-popup-close]')) { closePopup(); return; }
    const card = event.target.closest('[data-seq-group]');
    if (card) { openGroup(card.dataset.seqGroup); return; }
    const gen = event.target.closest('[data-seq-generate]');
    if (gen) { generateGroup(gen.dataset.seqGenerate); return; }
  });

  // Esc로 우측 팝업 닫기(검색 입력 포커스 중에도). 패널은 1회 생성이라 리스너도 1회.
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && popupEl && popupEl.classList.contains('open')) {
      closePopup();
    }
  });

  return {
    onOpen() { ensureReady(); },
    // 메인 하단 버튼 라우팅용(app.js). Sequence 탭 활성일 때 Ctrl/Alt+Enter 가 위임된다.
    hasOpenGroup() {
      return !!(popupEl && popupEl.classList.contains('open') && state.openGroupId != null);
    },
    generateOpenGroup() {  // req1: 보고 있는 그룹의 '연속 생성'. 열린 그룹 없으면 false(폴백).
      if (popupEl && popupEl.classList.contains('open') && state.openGroupId != null) {
        generateGroup(state.openGroupId);
        return true;
      }
      return false;
    },
    randomGenerate() { return runRandomGenerate(); },  // req2/3: 랜덤 그룹 연속 생성
  };
}
